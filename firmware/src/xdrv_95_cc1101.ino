/*
  xdrv_95_cc1101.ino — CC1101 433 MHz node driver (ESP32-C3 SuperMini + D-SUN CC1101)
  Part of firmware/ (github.com/mithro/esp32-to-433mhz)
  SPDX-License-Identifier: GPL-3.0-or-later

  Template: GPIO4=SPI CLK, GPIO5=SPI MISO, GPIO6=SPI MOSI, GPIO7=SPI CS, GPIO3=CC1101 GDO0, GPIO10=CC1101 GDO2
  Design spec §4-§6: 2026-08-20-esp32c3-cc1101-tasmota-design.md (project repo github.com/mithro/433mhz)
*/
#ifdef USE_CC1101_NODE
#ifdef ESP32

#include <SPI.h>
#include "esp_timer.h"
#include "cc1101_node/cc1101_radio.h"
#include "cc1101_node/sx1278_radio.h"
#include "cc1101_node/cc1101_presets.h"
#include "cc1101_node/cc1101_weather.h"
#include "cc1101_node/sx1278_weather.h"
#include "cc1101_node/cc1101_pulse.h"
#include "cc1101_node/secplus2.h"
#include "cc1101_node/decoders/decode_common.h"
#include "cc1101_node/decoders/decode_fineoffset.h"
#include "cc1101_node/decoders/decode_ookpwm.h"

#define XDRV_95 95
#define CC_LOGPFX "CC1: "

/* ---------- persisted config (/cc1101.cfg on the Tasmota filesystem) ---------- */
#define CC_CFG_MAGIC 0xCC110101u
#define CC_CFG_FILE  "/cc1101.cfg"
enum CcMode : uint8_t { CC_MODE_REMOTES = 0, CC_MODE_WEATHER = 1 };
enum CcRadioSel : uint8_t { RADIO_AUTO = 0, RADIO_CC1101 = 1, RADIO_SX1278 = 2 };
struct CcConfig {
  uint32_t magic; uint8_t version; uint8_t mode; uint8_t raw; uint8_t radio;
  uint64_t secplus_id; uint32_t rolling; uint32_t tx_count;
  double secplus_freq[3]; uint8_t secplus_nfreq; uint8_t pad2[7];
};
static CcConfig CcCfg;

static void CcCfgDefaults(void) {
  memset(&CcCfg, 0, sizeof CcCfg);
  CcCfg.magic = CC_CFG_MAGIC; CcCfg.version = 1; CcCfg.mode = CC_MODE_REMOTES; CcCfg.radio = RADIO_AUTO;
  CcCfg.secplus_freq[0] = 433.92; CcCfg.secplus_nfreq = 1;
}
static void CcCfgLoad(void) {
  CcCfgDefaults();
#ifdef USE_UFILESYS
  CcConfig tmp;
  // TfsLoadFile() clamps the read length to the file size and still returns true, so a
  // truncated file would leave the tail of tmp as stack garbage. Require an exact-size file.
  if (TfsFileExists(CC_CFG_FILE) && TfsFileSize(CC_CFG_FILE) == sizeof tmp &&
      TfsLoadFile(CC_CFG_FILE, (uint8_t*)&tmp, sizeof tmp) && tmp.magic == CC_CFG_MAGIC && tmp.version == 1) {
    CcCfg = tmp;
  }
#endif
}
static void CcCfgSave(void) {
#ifdef USE_UFILESYS
  if (!TfsSaveFile(CC_CFG_FILE, (const uint8_t*)&CcCfg, sizeof CcCfg)) { AddLog(LOG_LEVEL_ERROR, PSTR(CC_LOGPFX "cfg save failed")); }
#endif
}

/* ---------- SPI bus (chip-agnostic; shared by CC1101 and SX1278) ---------- */
class ArduinoSpiBus : public SpiBus {
 public:
  void begin(int cs) { cs_ = cs; pinMode(cs_, OUTPUT); digitalWrite(cs_, HIGH); }
  void select() override {
    SPI.beginTransaction(SPISettings(1000000, MSBFIRST, SPI_MODE0));
    digitalWrite(cs_, LOW);
    // No CHIP_RDYn/MISO wait here — that is CC1101-specific (it would hang an SX1278, which
    // shares this bus). The CC1101 chip-ready hand-shake now lives in CC1101Radio::reset().
  }
  void deselect() override { digitalWrite(cs_, HIGH); SPI.endTransaction(); }
  uint8_t transfer(uint8_t b) override { return SPI.transfer(b); }
  void delay_ms(uint32_t ms) override { delay(ms); }
  uint32_t millis() override { return ::millis(); }
 private:
  int cs_ = -1;
};

/* Active-low RST line for the SX1278 (drives a GPIO). */
class ArduinoResetLine : public Sx1278ResetLine {
 public:
  void begin(int pin) { pin_ = pin; }
  void set(bool high) override { digitalWrite(pin_, high ? HIGH : LOW); }
 private:
  int pin_ = -1;
};

/* ---------- per-board pin maps (VERIFIED) ----------
 * The adapter routes SPI + control lines differently per module. Radio selection (below)
 * SPI-probes these maps for a CC1101, or uses the RA-02 map for an SX1278. GPIO5 is the
 * board-type strap (float = CC1101, tied low = SX1278) and is NOT used by any map. */
struct CcPins { int8_t sck, miso, mosi, cs, gdo0, gdo2; };
struct SxPins { int8_t sck, miso, mosi, nss, rst, dio0; };
static const CcPins CC_MAP_BLUE  = { 3, 7, 4, 9, 10, 6 };   // blue E07:    SCK3 MISO7 MOSI4 CSN9  GDO0=10 GDO2=6
static const CcPins CC_MAP_GREEN = { 9, 3, 10, 6, 7, 4 };   // green D-Sun: SCK9 MISO3 MOSI10 CSN6 GDO0=7  GDO2=4
static const SxPins SX_MAP_RA02  = { 3, 7, 4, 9, 10, 6 };   // RA-02:       SCK3 MISO7 MOSI4 NSS9  RST=10  DIO0=6
#define CC_STRAP_PIN 5

/* ---------- driver state ---------- */
struct CcState {
  ArduinoSpiBus bus; CC1101Radio* radio = nullptr;
  CcPins pins = { -1, -1, -1, -1, -1, -1 };             // resolved by the SPI probe
  bool present = false; uint8_t partnum = 0, version = 0;
  int preset = -1; uint32_t rx = 0, decoded = 0, tx = 0, reinit = 0, overflow = 0;
  uint32_t bad_state_ms = 0; int last_rssi = -128;
  char last_key[RF_JSON_MAX] = {0}; uint32_t last_key_ms = 0; uint32_t repeats = 0;  // intra-node repeat collapsing (full-length key: a decoded event can be up to RF_JSON_MAX)
  uint32_t tx_window_ms = 0; uint8_t tx_in_window = 0;                        // rate limit
};
static CcState Cc;

/* ---------- SX1278 (RA-02) state — identify / register I/O + Fine Offset FSK RX ---------- */
struct SxState {
  ArduinoSpiBus bus; ArduinoResetLine rst; SX1278Radio* radio = nullptr;
  bool present = false; uint8_t version = 0; int rst_pin = -1;
  bool weather_rx = false;                              // FSK RX preset programmed + RX entered
  uint32_t rx = 0, decoded = 0; int last_rssi = -128;   // weather RX counters
};
static SxState Sx;
static uint8_t CcActiveRadio = RADIO_CC1101;            // which engine bring-up selected

static void CcPublishEvent(const char* json);         // forward (below)
static bool CcRepeatSuppressed(const char* key, uint32_t now);
void CcEnterMode(void);                               // forward (Task 5 extends)
static bool SxConfigureWeatherRx(void);               // forward: SX1278 FSK RX preset + enter RX
static void SxWeatherPoll(void);                      // forward: SX1278 weather-RX drain (FUNC_EVERY_50_MSECOND)
static void CcApplyMode(void);                        // forward: dispatch mode entry to the active radio
static void CcSecplusFrame(const uint32_t* us, size_t n, uint32_t now);  // Task 6 replaces the stub below
void CmndSecplusId(void); void CmndSecplusSend(void); void CmndSecplusCounter(void); void CmndSecplusFreq(void);  // forward: table below is defined before these bodies

/* ---------- helpers ---------- */
static void CcNodeTopic(char* out, size_t len, const char* leaf) {
  snprintf_P(out, len, PSTR("rtl_433/nodes/%s/%s"), NetworkHostname(), leaf);
}
static void CcPublishEvent(const char* json) {
  char topic[96]; CcNodeTopic(topic, sizeof topic, "events");
  MqttPublishPayload(topic, json);
}
/* identical decodes within 500 ms collapse into one event (spec §7.1) */
static bool CcRepeatSuppressed(const char* key, uint32_t now) {
  if (strncmp(Cc.last_key, key, sizeof Cc.last_key - 1) == 0 && (now - Cc.last_key_ms) < 500) { Cc.repeats++; Cc.last_key_ms = now; return true; }
  strlcpy(Cc.last_key, key, sizeof Cc.last_key); Cc.last_key_ms = now; Cc.repeats = 1; return false;
}
/* prepend time/receiver to a decoder JSON object: {"time":"…","receiver":"…",<decoder fields>} */
static void CcWrapEvent(const char* decoder_json, int rssi, char* out, size_t len) {
  const char* body = decoder_json; if (*body == '{') body++;
  snprintf_P(out, len, PSTR("{\"time\":\"%s\",\"receiver\":\"%s\",\"rssi\":%d,%s"), GetDateAndTime(DT_LOCAL).c_str(), NetworkHostname(), rssi, body);
}

/* ---------- OOK edge capture on GDO2 (ISR ring buffer; ruling R1: ISR instead of RMT) ---------- */
#define CC_EDGE_BUF 1024
#define CC_FRAME_GAP_US 12000
#define CC_MAX_PULSES 512
struct CcEdge { uint32_t t_us; uint8_t level; };
static volatile CcEdge CcEdges[CC_EDGE_BUF];
static volatile uint16_t CcEdgeHead = 0, CcEdgeTail = 0;
static int CcGdo2Pin = -1; static bool CcCapturing = false;
static uint32_t CcFramePulses[CC_MAX_PULSES]; static uint32_t CcFrameT[CC_MAX_PULSES + 1]; static uint8_t CcFrameL[CC_MAX_PULSES + 1];
static size_t CcFrameN = 0; static uint32_t CcFrameLastUs = 0;
static secplus2_state_t CcSecplus;                                   // Task 6 uses it

static void IRAM_ATTR CcGdo2Isr(void) {
  uint16_t next = (CcEdgeHead + 1) % CC_EDGE_BUF;
  if (next == CcEdgeTail) return;                                    // full: drop (counted by the consumer as a gap)
  CcEdges[CcEdgeHead].t_us = (uint32_t)esp_timer_get_time();
  CcEdges[CcEdgeHead].level = digitalRead(CcGdo2Pin);
  CcEdgeHead = next;
}
static void CcCaptureStart(void) {
  if (CcCapturing) return;
  CcGdo2Pin = Cc.pins.gdo2; pinMode(CcGdo2Pin, INPUT);
  CcEdgeHead = CcEdgeTail = 0; CcFrameN = 0;
  attachInterrupt(digitalPinToInterrupt(CcGdo2Pin), CcGdo2Isr, CHANGE);
  CcCapturing = true;
}
static void CcCaptureStop(void) {
  if (!CcCapturing) return;
  detachInterrupt(digitalPinToInterrupt(CcGdo2Pin)); CcCapturing = false;
}
static void CcPublishRaw(const uint32_t* us, size_t n) {
  char raw[1200]; int l = snprintf_P(raw, sizeof raw, PSTR("{\"Pulses\":["));
  for (size_t i = 0; i < n && i < 200 && l < (int)sizeof raw - 16; i++)
    l += snprintf_P(raw + l, sizeof raw - l, PSTR("%s%s%u"), i ? "," : "", (i % 2) ? "-" : "", (unsigned)us[i]);
  snprintf_P(raw + l, sizeof raw - l, PSTR("]}"));
  MqttPublishPayloadPrefixTopicRulesProcess_P(TELE, PSTR("CCRAW"), raw);
}
static void CcPublishRfReceived(const char* code_hex, int bits, unsigned short_us, int rssi) {
  // Data = first 24 bits of the code (Sonoff bridge convention; the aggregator's code_key does the same).
  // RULING R7: the generic ookpwm_decode() has no notion of an RCSwitch sync symbol, so a real
  // RCSwitch protocol-1 24-bit remote is reported as 25 bits (the sync's leading-mark-width pulse
  // is consumed as a spurious trailing data bit — see tests/test_rcswitch_roundtrip.py and
  // tests/test_pulse.py::test_rcswitch1_pulses_then_decode_as_ookpwm for the proof). The >>(width-24)
  // shift below discards exactly that spurious bit (plus the decoder's own nibble padding) and
  // recovers the true code, so `Data` and cross-receiver dedup are correct for the 24-bit case.
  // `bits` (and the events-JSON `code`) are still passed through as the decoder reported them
  // (25, not 24) because there is no way from the waveform alone to tell "spurious 25th bit from
  // an RCSwitch sync" apart from "a genuine 25-bit OOK-PWM protocol whose real last bit is 0" —
  // ookpwm_decode is shared with non-RCSwitch families and does not carry protocol identity.
  // Trimming Bits to a canonical 24 needs a real remote capture to confirm which case applies
  // (carried to the Task 7 runbook); do not guess here.
  uint64_t v = strtoull(code_hex, nullptr, 16); int width = strlen(code_hex) * 4;
  if (width > 24) v >>= (width - 24);
  char payload[128];
  snprintf_P(payload, sizeof payload, PSTR("{\"RfReceived\":{\"Data\":\"0x%06llX\",\"Bits\":%d,\"Protocol\":1,\"Pulse\":%u,\"RSSI\":%d}}"),
             (unsigned long long)(v & 0xFFFFFF), bits, short_us, rssi);
  MqttPublishPayloadPrefixTopicRulesProcess_P(TELE, PSTR("RESULT"), payload);
}
static void CcProcessFrame(const uint32_t* us, size_t n) {
  Cc.rx++;
  int rssi = Cc.radio->rssi_dbm(); Cc.last_rssi = rssi; uint32_t now = millis();
  if (CcCfg.raw) CcPublishRaw(us, n);
  size_t pos = 0; char dec[RF_JSON_MAX];
  while (ookpwm_decode(us, n, &pos, dec, sizeof dec) == RF_DECODE_OK) {
    Cc.decoded++;
    if (CcRepeatSuppressed(dec, now)) continue;
    char ev[RF_JSON_MAX + 96]; CcWrapEvent(dec, rssi, ev, sizeof ev); CcPublishEvent(ev);
    // pull code/bits/short_us back out of the decoder JSON for RfReceived
    const char* c = strstr(dec, "\"code\":\""); const char* b = strstr(dec, "\"bits\":"); const char* s = strstr(dec, "\"short_us\":");
    if (c && b && s) { char code[24] = {0}; sscanf(c + 8, "%23[0-9a-fA-F]", code); CcPublishRfReceived(code, atoi(b + 7), (unsigned)atoi(s + 11), rssi); }
  }
  CcSecplusFrame(us, n, now);                                      // Task 6 (stub below until then)
}
static void CcCapturePoll(void) {                                  // FUNC_EVERY_50_MSECOND in remotes mode
  uint32_t now_us = (uint32_t)esp_timer_get_time();
  while (CcEdgeTail != CcEdgeHead) {
    CcEdge e; noInterrupts(); e.t_us = CcEdges[CcEdgeTail].t_us; e.level = CcEdges[CcEdgeTail].level; CcEdgeTail = (CcEdgeTail + 1) % CC_EDGE_BUF; interrupts();
    if (CcFrameN && (e.t_us - CcFrameLastUs) > CC_FRAME_GAP_US) {   // gap: close the current frame
      size_t np = edges_to_pulses(CcFrameT, CcFrameL, CcFrameN, CcFramePulses, CC_MAX_PULSES);
      if (np >= 2 * OOKPWM_MIN_BITS) CcProcessFrame(CcFramePulses, np);
      CcFrameN = 0;
    }
    if (CcFrameN < CC_MAX_PULSES + 1) { CcFrameT[CcFrameN] = e.t_us; CcFrameL[CcFrameN] = e.level; CcFrameN++; }
    CcFrameLastUs = e.t_us;
  }
  if (CcFrameN && (now_us - CcFrameLastUs) > CC_FRAME_GAP_US) {    // idle: flush the pending frame
    size_t np = edges_to_pulses(CcFrameT, CcFrameL, CcFrameN, CcFramePulses, CC_MAX_PULSES);
    if (np >= 2 * OOKPWM_MIN_BITS) CcProcessFrame(CcFramePulses, np);
    CcFrameN = 0;
  }
}

/* ---------- TX (ruling R2: chips through the CC1101 TX FIFO) ---------- */
static bool CcTxAllowed(void) {
  uint32_t now = millis();
  if (now - Cc.tx_window_ms > 10000) { Cc.tx_window_ms = now; Cc.tx_in_window = 0; }
  if (Cc.tx_in_window >= 10) return false;
  Cc.tx_in_window++; return true;
}
static void CcAnnounceTx(const char* json) { char topic[96]; CcNodeTopic(topic, sizeof topic, "tx"); MqttPublishPayload(topic, json); }
/* Transmit a pulse list as OOK: preset chip rate 100 kchip/s (10 us chips). Returns to the RX preset of the mode. */
static bool CcTxPulses(const uint32_t* us, size_t n, int repeats, uint32_t gap_ms) {
  static uint8_t chips[4096];                                       // up to 32768 chips = 327 ms at 10 us
  size_t nbits = pulses_to_chips(us, n, 10, chips, sizeof chips);
  bool was_capturing = CcCapturing; CcCaptureStop();
  bool ok = Cc.radio->load_preset(CC_PRESET_OOK_TX_100K);
  for (int r = 0; ok && r < repeats; r++) { ok = Cc.radio->tx_bits(chips, nbits, 2000); if (gap_ms) delay(gap_ms); }
  if (!ok) AddLog(LOG_LEVEL_ERROR, PSTR(CC_LOGPFX "tx: %s"), Cc.radio->last_error());
  CcEnterMode(); if (was_capturing) CcCaptureStart();
  if (ok) { Cc.tx++; CcCfg.tx_count++; }
  return ok;
}
void CmndCcRfSend(void) {                                          // Tasmota RfSend compatible subset, as CcRfSend
  if (!Cc.present) { ResponseCmndChar_P(PSTR("no radio")); return; }
  uint32_t data = 0; int bits = 24, protocol = 1, pulse = 350, repeat = 10;
  if (XdrvMailbox.data_len) {
    JsonParser parser(XdrvMailbox.data); JsonParserObject root = parser.getRootObject();
    if (root) {
      JsonParserToken t;
      if ((t = root[PSTR("Data")]).isValid()) data = strtoul(t.getStr(), nullptr, 0);
      if ((t = root[PSTR("Bits")]).isValid()) bits = t.getUInt();
      if ((t = root[PSTR("Protocol")]).isValid()) protocol = t.getUInt();
      if ((t = root[PSTR("Pulse")]).isValid()) pulse = t.getUInt();
      if ((t = root[PSTR("Repeat")]).isValid()) repeat = t.getUInt();
    } else { data = strtoul(XdrvMailbox.data, nullptr, 0); }
  }
  if (protocol != 1 || bits < 8 || bits > 32 || pulse < 100 || pulse > 2000) { ResponseCmndChar_P(PSTR("only Protocol 1, Bits 8..32, Pulse 100..2000")); return; }
  if (!CcTxAllowed()) { ResponseCmndChar_P(PSTR("rate limited")); return; }
  char ann[128]; snprintf_P(ann, sizeof ann, PSTR("{\"Data\":\"0x%0*lX\",\"Bits\":%d,\"Protocol\":1,\"Pulse\":%d,\"model\":\"OOK-PWM\",\"code\":\"%0*lx\"}"),
                            (bits + 3) / 4, (unsigned long)data, bits, pulse, (bits + 3) / 4, (unsigned long)data);
  CcAnnounceTx(ann); delay(50);
  uint32_t us[80]; size_t n = rcswitch1_pulses(data, bits, pulse, us, 80);
  bool ok = CcTxPulses(us, n, repeat > 0 ? repeat : 1, 0);
  ResponseCmndChar_P(ok ? PSTR("Done") : PSTR("Failed"));
}
/* ---------- Security+ 2.0 (ruling R3: configurable frequency legs, default 433.92) ---------- */
static void CcSecplusFrame(const uint32_t* us, size_t n, uint32_t now) {
  uint8_t fid = 0, payload[8]; size_t bits = 0;
  if (!secplus2_demod(us, n, &fid, payload, &bits)) return;
  char dec[RF_JSON_MAX];
  int rc = secplus2_collect(&CcSecplus, fid, payload, bits, now, dec, sizeof dec);
  if (rc == 1) {
    Cc.decoded++;
    if (!CcRepeatSuppressed(dec, now)) { char ev[RF_JSON_MAX + 96]; CcWrapEvent(dec, Cc.last_rssi, ev, sizeof ev); CcPublishEvent(ev); }
  } else if (rc < 0) { AddLog(LOG_LEVEL_DEBUG, PSTR(CC_LOGPFX "secplus halves did not decode")); }
}
const char kCcSecplusCommands[] PROGMEM = "Secplus|Id|Send|Counter|Freq";
void (* const CcSecplusCommand[])(void) PROGMEM = { &CmndSecplusId, &CmndSecplusSend, &CmndSecplusCounter, &CmndSecplusFreq };

void CmndSecplusId(void) {
  if (XdrvMailbox.data_len) { CcCfg.secplus_id = strtoull(XdrvMailbox.data, nullptr, 0) & 0xF0FFFFFFFFULL; CcCfgSave(); }
  Response_P(PSTR("{\"SecplusId\":%llu}"), (unsigned long long)CcCfg.secplus_id);
}
void CmndSecplusCounter(void) {
  if (XdrvMailbox.data_len) { CcCfg.rolling = strtoul(XdrvMailbox.data, nullptr, 0) & 0x0FFFFFFF; CcCfgSave(); }
  ResponseCmndNumber(CcCfg.rolling);
}
void CmndSecplusFreq(void) {
  if (XdrvMailbox.data_len) {
    double f[3]; int n = 0; char* p = XdrvMailbox.data;
    while (*p && n < 3) {
      char* start = p; f[n] = strtod(p, &p);
      if (p == start) break;                         // strtod made no progress: an unparseable byte — stop (else infinite loop)
      if (f[n] > 300 && f[n] < 1000) n++;
      while (*p == ',' || *p == ' ') p++;
    }
    if (n) { for (int i = 0; i < n; i++) CcCfg.secplus_freq[i] = f[i]; CcCfg.secplus_nfreq = n; CcCfgSave(); }
  }
  Response_P(PSTR("{\"SecplusFreq\":["));
  for (int i = 0; i < CcCfg.secplus_nfreq; i++) ResponseAppend_P(PSTR("%s%.2f"), i ? "," : "", CcCfg.secplus_freq[i]);
  ResponseAppend_P(PSTR("]}"));
}
void CmndSecplusSend(void) {
  if (!Cc.present) { ResponseCmndChar_P(PSTR("no radio")); return; }
  if (!CcCfg.secplus_id) { ResponseCmndChar_P(PSTR("set SecplusId first")); return; }
  int button = XdrvMailbox.payload; if (button < 0 || button > 15) button = 1;
  if (!CcTxAllowed()) { ResponseCmndChar_P(PSTR("rate limited")); return; }
  uint32_t rolling = (CcCfg.rolling + 1) & 0x0FFFFFFF;
  uint64_t fixed = (CcCfg.secplus_id & 0xF0FFFFFFFFULL) | ((uint64_t)button << 32);
  char ann[160]; snprintf_P(ann, sizeof ann, PSTR("{\"model\":\"Secplus-v2\",\"id\":%llu,\"button\":%d,\"rolling\":%lu,\"fixed\":%llu}"),
                            (unsigned long long)(CcCfg.secplus_id), button, (unsigned long)rolling, (unsigned long long)fixed);
  CcAnnounceTx(ann); delay(50);
  CcCfg.rolling = rolling; CcCfgSave();                           // persist before keying: never reuse a counter
  static uint8_t chips01[1024]; static uint8_t packed[128 * 3];
  size_t nchips = secplus2_encode_chips(rolling, fixed, 0, 0, chips01, sizeof chips01);
  if (!nchips) { ResponseCmndChar_P(PSTR("encode failed")); return; }
  size_t nbits = 0; memset(packed, 0, sizeof packed);
  for (int rep = 0; rep < 3; rep++) for (size_t i = 0; i < nchips; i++, nbits++) if (chips01[i]) packed[nbits / 8] |= 0x80 >> (nbits % 8);
  bool was_capturing = CcCapturing; CcCaptureStop();
  bool ok = true;
  for (int leg = 0; ok && leg < CcCfg.secplus_nfreq; leg++) {
    ok = Cc.radio->load_preset(CC_PRESET_OOK_TX_4K);
    if (ok) { Cc.radio->set_freq(CcCfg.secplus_freq[leg] * 1e6); ok = Cc.radio->tx_bits(packed, nbits, 3000); }
  }
  CcEnterMode(); if (was_capturing) CcCaptureStart();
  if (ok) { Cc.tx++; CcCfg.tx_count++; }
  ResponseCmndChar_P(ok ? PSTR("Done") : PSTR("Failed"));
}

/* ---------- radio bring-up: selection + per-board SPI probe ---------- */
// GPIO5 board-type strap: sample with an internal pulldown then an internal pullup. A floating
// pin follows each internal resistor (reads 0 then 1) -> CC1101 board; a pin externally tied low
// stays 0 against the weak pullup -> SX1278 (RA-02) board.
static uint8_t CcStrapRadio(void) {
  pinMode(CC_STRAP_PIN, INPUT_PULLDOWN); delayMicroseconds(50); int lo = digitalRead(CC_STRAP_PIN);
  pinMode(CC_STRAP_PIN, INPUT_PULLUP);   delayMicroseconds(50); int hi = digitalRead(CC_STRAP_PIN);
  pinMode(CC_STRAP_PIN, INPUT);
  return (lo == 0 && hi == 0) ? RADIO_SX1278 : RADIO_CC1101;
}
// Bring SPI up on one board's pins and check for a CC1101 (PARTNUM 0x00, VERSION in {0x04,0x14}).
static bool CcProbeCc1101(int8_t sck, int8_t miso, int8_t mosi, int8_t cs, int8_t gdo0, int8_t gdo2) {
  SPI.end();
  SPI.begin(sck, miso, mosi, -1);
  Cc.bus.begin(cs);
  if (!Cc.radio) Cc.radio = new CC1101Radio(Cc.bus);
  if (!Cc.radio->reset()) return false;
  uint8_t pn = 0, ver = 0;
  if (!Cc.radio->identify(&pn, &ver)) return false;
  Cc.partnum = pn; Cc.version = ver;
  Cc.pins.sck = sck; Cc.pins.miso = miso; Cc.pins.mosi = mosi; Cc.pins.cs = cs; Cc.pins.gdo0 = gdo0; Cc.pins.gdo2 = gdo2;
  return true;
}
static void CcCc1101BringUp(void) {
  Cc.present = false;
  // Probe the legacy Tasmota template map first (if commissioned), then the verified board maps.
  if (PinUsed(GPIO_SPI_CS)) {
    if (CcProbeCc1101(Pin(GPIO_SPI_CLK), Pin(GPIO_SPI_MISO), Pin(GPIO_SPI_MOSI),
                      Pin(GPIO_SPI_CS), Pin(GPIO_CC1101_GDO0), Pin(GPIO_CC1101_GDO2))) Cc.present = true;
  }
  if (!Cc.present && CcProbeCc1101(CC_MAP_BLUE.sck, CC_MAP_BLUE.miso, CC_MAP_BLUE.mosi, CC_MAP_BLUE.cs, CC_MAP_BLUE.gdo0, CC_MAP_BLUE.gdo2))  Cc.present = true;
  if (!Cc.present && CcProbeCc1101(CC_MAP_GREEN.sck, CC_MAP_GREEN.miso, CC_MAP_GREEN.mosi, CC_MAP_GREEN.cs, CC_MAP_GREEN.gdo0, CC_MAP_GREEN.gdo2)) Cc.present = true;
  if (!Cc.present) {
    AddLog(LOG_LEVEL_ERROR, PSTR(CC_LOGPFX "no CC1101 on any board map (last PARTNUM 0x%02X VERSION 0x%02X) - check wiring"), Cc.partnum, Cc.version);
    return;
  }
  AddLog(LOG_LEVEL_INFO, PSTR(CC_LOGPFX "CC1101 PARTNUM 0x%02X VERSION 0x%02X, SCK=%d MISO=%d MOSI=%d CS=%d GDO0=%d GDO2=%d"),
         Cc.partnum, Cc.version, Cc.pins.sck, Cc.pins.miso, Cc.pins.mosi, Cc.pins.cs, Cc.pins.gdo0, Cc.pins.gdo2);
  CcEnterMode();
}
static void CcSx1278BringUp(void) {
  Sx.present = false;
  SPI.end();
  SPI.begin(SX_MAP_RA02.sck, SX_MAP_RA02.miso, SX_MAP_RA02.mosi, -1);
  Sx.bus.begin(SX_MAP_RA02.nss);
  Sx.rst_pin = SX_MAP_RA02.rst; pinMode(Sx.rst_pin, OUTPUT); digitalWrite(Sx.rst_pin, HIGH);
  Sx.rst.begin(Sx.rst_pin);
  pinMode(SX_MAP_RA02.dio0, INPUT);                    // DIO0 reserved for the FSK/OOK roadmap
  if (!Sx.radio) Sx.radio = new SX1278Radio(Sx.bus, Sx.rst);
  Sx.radio->reset();
  Sx.present = Sx.radio->identify(&Sx.version);
  if (Sx.present)
    AddLog(LOG_LEVEL_INFO, PSTR(CC_LOGPFX "SX1278 present, RegVersion 0x%02X, SCK=%d MISO=%d MOSI=%d NSS=%d RST=%d DIO0=%d"),
           Sx.version, SX_MAP_RA02.sck, SX_MAP_RA02.miso, SX_MAP_RA02.mosi, SX_MAP_RA02.nss, SX_MAP_RA02.rst, SX_MAP_RA02.dio0);
  else
    AddLog(LOG_LEVEL_ERROR, PSTR(CC_LOGPFX "no SX1278 (RegVersion 0x%02X, expected 0x12) - check SPI/RST wiring"), Sx.version);
  Sx.weather_rx = false;
  if (Sx.present && CcCfg.mode == CC_MODE_WEATHER) SxConfigureWeatherRx();  // arm FSK RX at boot when commissioned for weather
}
static void CcRadioBringUp(void) {
  uint8_t sel = CcCfg.radio;
  if (sel == RADIO_AUTO) sel = CcStrapRadio();
  CcActiveRadio = sel;
  if (sel == RADIO_SX1278) CcSx1278BringUp();
  else                     CcCc1101BringUp();
}
static bool CcLoadPresetAndRx(int preset) {
  if (!Cc.radio->load_preset(preset)) return false;
  Cc.preset = preset;
  return Cc.radio->enter_rx();
}

/* ---------- FSK weather path ---------- */
// Fineoffset FSK RX runs the CC1101 in INFINITE packet-length mode (preset PKTCTRL0 = 0x02).
// The framing/drain/dispatch lives in cc1101_weather.cpp (cc_weather_drain), shared verbatim
// with the host harness so tests/test_weather_rx.py exercises the identical logic. The FIFO
// only starts filling after the 0x2DD4 sync match, so a whole frame sits at the head with
// demodulated noise behind it; we drain a fixed CC_FSK_DRAIN_LEN (>= the longest WS85 frame)
// and fineoffset_decode() dispatches by family byte (0x24 WS69 / 0x51 WH51 / 0x85 WS85),
// ignoring the trailing bytes. One config thus receives all three families. cc_weather_drain
// flushes the FIFO and re-enters RX after each frame (and on overflow) to re-arm sync.
static void CcWeatherPoll(void) {
  uint8_t raw[CC_FSK_DRAIN_LEN]; size_t nbytes = 0; int rssi = 0; char dec[RF_JSON_MAX];
  int rc = cc_weather_drain(*Cc.radio, raw, sizeof raw, &nbytes, &rssi, dec, sizeof dec);
  if (rc == CC_WX_IDLE) return;
  if (rc == CC_WX_OVERFLOW) { Cc.overflow++; return; }
  Cc.rx++; Cc.last_rssi = rssi;
  if (rc == CC_WX_DECODED) {
    Cc.decoded++;
    if (!CcRepeatSuppressed(dec, millis())) { char ev[RF_JSON_MAX + 96]; CcWrapEvent(dec, rssi, ev, sizeof ev); CcPublishEvent(ev); }
  } else if (CcCfg.raw) {                                 // CC_WX_RAW: drained but undecodable — publish hex if raw mode on
    char rawmsg[128]; int l = snprintf_P(rawmsg, sizeof rawmsg, PSTR("{\"Packet\":\""));
    for (size_t i = 0; i < nbytes && l < (int)sizeof rawmsg - 8; i++) l += snprintf_P(rawmsg + l, sizeof rawmsg - l, PSTR("%02X"), raw[i]);
    snprintf_P(rawmsg + l, sizeof rawmsg - l, PSTR("\",\"RSSI\":%d}"), rssi);
    MqttPublishPayloadPrefixTopicRulesProcess_P(TELE, PSTR("CCRAW"), rawmsg);
  }
}

/* ---------- SX1278 (RA-02) Fine Offset FSK weather path ----------
 * The SX127x counterpart of the CC1101 weather path: program the 2-FSK RX preset
 * (433.92 MHz, 17.241 kbps, ~50 kHz fdev, sync 0x2DD4, fixed-length packet = SX_FSK_RX_LEN),
 * enter RX, and each poll drain a fixed byte count out of RegFifo on PayloadReady and
 * dispatch by family byte via fineoffset_decode (sx1278_weather.cpp, shared with the host
 * harness tests/sx1278_host.cpp so tests/test_sx1278_weather_rx.py exercises identical logic).
 * SX1278 OOK-continuous "remotes" RX is NOT possible on this adapter (DIO2 is not routed —
 * see the roadmap in sx1278_radio.cpp), so the SX1278 supports weather RX only. */
static bool SxConfigureWeatherRx(void) {
  if (!Sx.present || !Sx.radio) { Sx.weather_rx = false; return false; }
  Sx.radio->configure_fineoffset_fsk();
  Sx.radio->enter_rx();
  Sx.weather_rx = true;
  AddLog(LOG_LEVEL_INFO, PSTR(CC_LOGPFX "SX1278 FSK weather RX: 433.92 MHz 17.241 kbps sync 0x2DD4, fixed len %d"), (int)SX_FSK_RX_LEN);
  return true;
}
static void SxWeatherPoll(void) {                                 // FUNC_EVERY_50_MSECOND when SX1278 active + weather
  uint8_t raw[SX_FSK_DRAIN_LEN]; size_t nbytes = 0; int rssi = 0; char dec[RF_JSON_MAX];
  int rc = sx_weather_drain(*Sx.radio, raw, sizeof raw, &nbytes, &rssi, dec, sizeof dec);
  if (rc == SX_WX_IDLE) return;
  Sx.rx++; Sx.last_rssi = rssi;
  if (rc == SX_WX_DECODED) {
    Sx.decoded++;
    if (!CcRepeatSuppressed(dec, millis())) { char ev[RF_JSON_MAX + 96]; CcWrapEvent(dec, rssi, ev, sizeof ev); CcPublishEvent(ev); }
  } else if (CcCfg.raw) {                                         // SX_WX_RAW: drained but undecodable — publish hex if raw mode on
    char rawmsg[128]; int l = snprintf_P(rawmsg, sizeof rawmsg, PSTR("{\"Packet\":\""));
    for (size_t i = 0; i < nbytes && l < (int)sizeof rawmsg - 8; i++) l += snprintf_P(rawmsg + l, sizeof rawmsg - l, PSTR("%02X"), raw[i]);
    snprintf_P(rawmsg + l, sizeof rawmsg - l, PSTR("\",\"RSSI\":%d}"), rssi);
    MqttPublishPayloadPrefixTopicRulesProcess_P(TELE, PSTR("CCRAW"), rawmsg);
  }
}

/* ---------- mode entry (Task 5 adds the OOK capture start/stop) ---------- */
void CcEnterMode(void) {
  if (!Cc.present) return;
  if (CcCfg.mode == CC_MODE_WEATHER) { CcLoadPresetAndRx(CC_PRESET_FINEOFFSET_FSK); }
  else { CcLoadPresetAndRx(CC_PRESET_OOK_RX); }
  if (CcCfg.mode == CC_MODE_REMOTES) CcCaptureStart(); else CcCaptureStop();
  Cc.bad_state_ms = 0;
  AddLog(LOG_LEVEL_INFO, PSTR(CC_LOGPFX "mode %s preset %s"), CcCfg.mode == CC_MODE_WEATHER ? "weather" : "remotes", cc_preset_name(Cc.preset));
}
/* Dispatch mode entry to whichever radio bring-up selected. The CC1101 does OOK "remotes"
 * + Fine Offset "weather"; the SX1278 does "weather" (FSK RX) only. */
static void CcApplyMode(void) {
  if (CcActiveRadio == RADIO_SX1278) {
    if (CcCfg.mode == CC_MODE_WEATHER) { SxConfigureWeatherRx(); }
    else {
      Sx.weather_rx = false;
      if (Sx.present && Sx.radio) Sx.radio->standby();
      AddLog(LOG_LEVEL_INFO, PSTR(CC_LOGPFX "SX1278 remotes mode unsupported (OOK-continuous needs DIO2, not routed) — idle"));
    }
  } else {
    CcEnterMode();
  }
}
static void CcHealth50ms(void) {
  uint8_t m = Cc.radio->marcstate();
  bool ok = (m == MARC_RX) || (m == MARC_RXFIFO_OVERFLOW);
  uint32_t now = millis();
  if (ok) { Cc.bad_state_ms = 0; return; }
  if (!Cc.bad_state_ms) Cc.bad_state_ms = now;
  else if (now - Cc.bad_state_ms > 2000) { Cc.reinit++; AddLog(LOG_LEVEL_INFO, PSTR(CC_LOGPFX "MARCSTATE 0x%02X for >2 s, re-init"), m); CcCc1101BringUp(); }
}

/* ---------- commands ---------- */
const char kCcCommands[] PROGMEM = "Cc|Mode|Preset|Reg|Status|Raw";
void (* const CcCommand[])(void) PROGMEM = { &CmndCcMode, &CmndCcPreset, &CmndCcReg, &CmndCcStatus, &CmndCcRaw };
// Un-prefixed command table: named CcRfSend, not RfSend — xdrv_17_rcswitch.ino (USE_RC_SWITCH,
// which IS compiled into this tasmota32c3 build) already defines CmndRfSend/"RfSend", so the
// bare Tasmota name collides at link time. Renamed to avoid the redefinition.
const char kCcCommands2[] PROGMEM = "|CcRfSend";
void (* const CcCommand2[])(void) PROGMEM = { &CmndCcRfSend };

void CmndCcMode(void) {
  if (XdrvMailbox.data_len) {
    if (!strcasecmp(XdrvMailbox.data, "weather")) CcCfg.mode = CC_MODE_WEATHER;
    else if (!strcasecmp(XdrvMailbox.data, "remotes")) CcCfg.mode = CC_MODE_REMOTES;
    else if (!strcasecmp(XdrvMailbox.data, "auto")) { ResponseCmndChar_P(PSTR("auto not implemented (spec follow-on)")); return; }
    else { ResponseCmndChar_P(PSTR("remotes|weather")); return; }
    CcCfgSave(); CcApplyMode();
  }
  ResponseCmndChar_P(CcCfg.mode == CC_MODE_WEATHER ? PSTR("weather") : PSTR("remotes"));
}
void CmndCcPreset(void) {          // debug: load a preset and enter RX with it
  if (XdrvMailbox.data_len) {
    int id = cc_preset_by_name(XdrvMailbox.data);
    if (id < 0 || !Cc.present) { ResponseCmndChar_P(PSTR("fineoffset-fsk|ook-433|ook-tx-100k|ook-tx-4k")); return; }
    CcLoadPresetAndRx(id);
  }
  ResponseCmndChar(cc_preset_name(Cc.preset));
}
void CmndCcReg(void) {             // CcReg <addr> [value]  (hex or decimal); addr 0x00-0x3F. NB writing 0x30-0x3D issues a command strobe.
  if (!Cc.present || !XdrvMailbox.data_len) { ResponseCmndChar_P(PSTR("addr 0x00-0x3F [val]")); return; }
  char* p; uint32_t addr = strtoul(XdrvMailbox.data, &p, 0);
  if (addr > 0x3F) { ResponseCmndChar_P(PSTR("addr 0x00-0x3F")); return; }
  while (*p == ' ' || *p == ',') p++;
  if (*p) { uint32_t val = strtoul(p, nullptr, 0); Cc.radio->write_reg(addr, val & 0xFF); }
  uint8_t v = (addr < 0x30) ? Cc.radio->read_reg(addr) : Cc.radio->read_status(addr);
  Response_P(PSTR("{\"CcReg\":{\"Addr\":\"0x%02X\",\"Value\":\"0x%02X\"}}"), (unsigned)addr, v);
}
void CmndCcStatus(void) {
  Response_P(PSTR("{\"CcStatus\":{\"Present\":%d,\"PARTNUM\":\"0x%02X\",\"VERSION\":\"0x%02X\",\"MARCSTATE\":\"0x%02X\",\"Mode\":\"%s\",\"Preset\":\"%s\",\"RSSI\":%d,\"Rx\":%u,\"Decoded\":%u,\"Tx\":%u,\"Reinit\":%u,\"Overflow\":%u,\"Repeats\":%u,\"Raw\":%d,\"SecplusId\":%llu,\"Rolling\":%u}}"),
             Cc.present, Cc.partnum, Cc.version, Cc.present ? Cc.radio->marcstate() : 0,
             CcCfg.mode == CC_MODE_WEATHER ? "weather" : "remotes", cc_preset_name(Cc.preset),
             Cc.present ? Cc.radio->rssi_dbm() : 0, Cc.rx, Cc.decoded, Cc.tx, Cc.reinit, Cc.overflow, Cc.repeats, CcCfg.raw,
             (unsigned long long)CcCfg.secplus_id, (unsigned)CcCfg.rolling);
}
void CmndCcRaw(void) {
  if (XdrvMailbox.data_len) { CcCfg.raw = (XdrvMailbox.payload != 0); CcCfgSave(); }
  ResponseCmndNumber(CcCfg.raw);
}

/* ---------- SX1278 + radio-selection commands ---------- */
void CmndSxStatus(void) {
  Response_P(PSTR("{\"SxStatus\":{\"Present\":%d,\"VERSION\":\"0x%02X\",\"Active\":%d,\"Mode\":\"%s\",\"WeatherRx\":%d,\"RSSI\":%d,\"Rx\":%u,\"Decoded\":%u}}"),
             Sx.present, Sx.version, CcActiveRadio == RADIO_SX1278,
             CcCfg.mode == CC_MODE_WEATHER ? "weather" : "remotes", Sx.weather_rx,
             (Sx.present && Sx.weather_rx) ? Sx.radio->rssi_dbm() : 0, Sx.rx, Sx.decoded);
}
void CmndSxReg(void) {             // SxReg <addr 0x00-0x7F> [val]; SX127x address byte bit7 = write
  if (!Sx.radio || CcActiveRadio != RADIO_SX1278 || !XdrvMailbox.data_len) { ResponseCmndChar_P(PSTR("addr 0x00-0x7F [val] (SX1278 must be the active radio)")); return; }
  char* p; uint32_t addr = strtoul(XdrvMailbox.data, &p, 0);
  if (addr > 0x7F) { ResponseCmndChar_P(PSTR("addr 0x00-0x7F")); return; }
  while (*p == ' ' || *p == ',') p++;
  if (*p) { uint32_t val = strtoul(p, nullptr, 0); Sx.radio->write_reg(addr, val & 0xFF); }
  uint8_t v = Sx.radio->read_reg(addr);
  Response_P(PSTR("{\"SxReg\":{\"Addr\":\"0x%02X\",\"Value\":\"0x%02X\"}}"), (unsigned)addr, v);
}
void CmndSxReset(void) {
  if (!Sx.radio || CcActiveRadio != RADIO_SX1278) { ResponseCmndChar_P(PSTR("SX1278 must be the active radio")); return; }
  Sx.radio->reset();
  Sx.present = Sx.radio->identify(&Sx.version);
  Response_P(PSTR("{\"SxReset\":{\"Present\":%d,\"VERSION\":\"0x%02X\"}}"), Sx.present, Sx.version);
}
static const char kCcRadioNames[] PROGMEM = "auto|cc1101|sx1278";
void CmndCcRadioSel(void) {             // Radio [auto|cc1101|sx1278] — persisted; re-runs bring-up
  if (XdrvMailbox.data_len) {
    if (!strcasecmp(XdrvMailbox.data, "auto")) CcCfg.radio = RADIO_AUTO;
    else if (!strcasecmp(XdrvMailbox.data, "cc1101")) CcCfg.radio = RADIO_CC1101;
    else if (!strcasecmp(XdrvMailbox.data, "sx1278")) CcCfg.radio = RADIO_SX1278;
    else { ResponseCmndChar_P(kCcRadioNames); return; }
    CcCfgSave();
    CcRadioBringUp();
  }
  const char* cfg = CcCfg.radio == RADIO_SX1278 ? "sx1278" : (CcCfg.radio == RADIO_CC1101 ? "cc1101" : "auto");
  const char* act = CcActiveRadio == RADIO_SX1278 ? "sx1278" : "cc1101";
  Response_P(PSTR("{\"Radio\":{\"Config\":\"%s\",\"Active\":\"%s\"}}"), cfg, act);
}
const char kSxCommands[] PROGMEM = "Sx|Status|Reg|Reset";
void (* const SxCommand[])(void) PROGMEM = { &CmndSxStatus, &CmndSxReg, &CmndSxReset };
const char kRadioCommands[] PROGMEM = "|Radio";
void (* const RadioCommand[])(void) PROGMEM = { &CmndCcRadioSel };

/* ---------- tele/SENSOR + web ---------- */
static void CcShowJson(void) {
  ResponseAppend_P(PSTR(",\"CC1101\":{\"Mode\":\"%s\",\"Preset\":\"%s\",\"RSSI\":%d,\"Rx\":%u,\"Decoded\":%u,\"Tx\":%u,\"Reinit\":%u,\"SecplusId\":%llu,\"Rolling\":%u}"),
                   CcCfg.mode == CC_MODE_WEATHER ? "weather" : "remotes", cc_preset_name(Cc.preset),
                   Cc.present ? Cc.radio->rssi_dbm() : 0, Cc.rx, Cc.decoded, Cc.tx, Cc.reinit,
                   (unsigned long long)CcCfg.secplus_id, (unsigned)CcCfg.rolling);
}
#ifdef USE_WEBSERVER
static void CcShowWeb(void) {
  if (CcActiveRadio == RADIO_SX1278) {
    WSContentSend_PD(PSTR("{s}SX1278 %s{m}RegVersion 0x%02X, %s, rx %u, decoded %u{e}"),
                     Sx.present ? "" : "(absent)", Sx.version,
                     Sx.weather_rx ? "weather FSK RX" : "idle", Sx.rx, Sx.decoded);
    return;
  }
  WSContentSend_PD(PSTR("{s}CC1101 %s{m}%s, RSSI %d dBm, rx %u, decoded %u{e}"),
                   Cc.present ? "" : "(absent)", CcCfg.mode == CC_MODE_WEATHER ? "weather" : "remotes",
                   Cc.present ? Cc.radio->rssi_dbm() : 0, Cc.rx, Cc.decoded);
}
#endif

/* ---------- Tasmota entry ---------- */
void Cc1101NodeInit(void) {
  CcCfgLoad();
  CcRadioBringUp();
}

bool Xdrv95(uint32_t function) {
  // Always active: dedicated CC1101/SX1278 build. Bring-up (GPIO5 strap + SPI probe of the
  // per-board pin maps) runs at FUNC_INIT and degrades gracefully when no radio is found.
  bool result = false;
  switch (function) {
    case FUNC_INIT:
      Cc1101NodeInit();
      break;
    case FUNC_EVERY_50_MSECOND:
      if (CcActiveRadio == RADIO_SX1278) {
        if (Sx.present && Sx.weather_rx) SxWeatherPoll();
      } else if (Cc.present) {
        if (CcCfg.mode == CC_MODE_WEATHER) CcWeatherPoll(); else CcCapturePoll();
        CcHealth50ms();
      }
      break;
    case FUNC_JSON_APPEND:
      CcShowJson();
      break;
#ifdef USE_WEBSERVER
    case FUNC_WEB_SENSOR:
      CcShowWeb();
      break;
#endif
    case FUNC_COMMAND:
      result = DecodeCommand(kCcCommands, CcCommand) || DecodeCommand(kCcCommands2, CcCommand2) || DecodeCommand(kCcSecplusCommands, CcSecplusCommand)
             || DecodeCommand(kSxCommands, SxCommand) || DecodeCommand(kRadioCommands, RadioCommand);
      break;
    case FUNC_ACTIVE:
      result = true;
      break;
  }
  return result;
}

#endif  // ESP32
#endif  // USE_CC1101_NODE

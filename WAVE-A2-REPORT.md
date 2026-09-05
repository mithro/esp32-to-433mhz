# WAVE-A2 — SX1278 (RA-02) Fine Offset FSK receive

**Goal:** bring the SX1278 (RA-02) to functional parity with the CC1101 weather
path — receive Fine Offset weather (WS69, family 0x24) and soil-moisture (WH51,
family 0x51) FSK frames on the SX1278.

**Result: DONE and validated on real hardware.** The RA-02 node decodes WS69 and
WH51 live, cross-checked against the proven rpi5 reference receivers.

---

## SX127x FSK config used (with reference cross-ref)

`configure_fineoffset_fsk()` in `firmware/src/cc1101_node/sx1278_radio.cpp`. Every
value computed from the SX1276/78 datasheet formulas and matched to the bench-proven
SX1276 receiver at the same Welland site (rpi5 `~/wh51-watch`, RadioLib `beginFSK`:
433.92 MHz, 17.241 kbps, ~50 kHz fdev, sync 0x2DD4, 2-FSK `ModulationShaping=NONE`).

| Purpose | Register | Value |
|---|---|---|
| FSK mode (LongRangeMode=0), low-freq band, RX | RegOpMode 0x01 | `0D` |
| Carrier 433.92 MHz (`Frf = Fstep·RegFrf`, Fstep=32MHz/2¹⁹=61.035 Hz) | RegFrf 0x06/07/08 | `6C 7A E1` |
| Bit rate 17.241 kbps (`FXOSC/RegBitrate`, 32e6/17241=1856) | RegBitrate 0x02/03 | `07 40` |
| Deviation ~50 kHz (`Fstep·RegFdev`, 50000/61.035=819) | RegFdev 0x04/05 | `03 33` |
| RX bandwidth 125 kHz (mant=16, exp=2) | RegRxBw 0x12 | `02` |
| AGC auto + RX trigger on preamble detect | RegRxConfig 0x0D | `0E` |
| Preamble detector on, 2 bytes, tol 10 | RegPreambleDetect 0x1F | `AA` |
| AutoRestartRx + SyncOn + 2 sync bytes (0xAA preamble polarity) | RegSyncConfig 0x27 | `91` |
| Sync word 0x2DD4 | RegSyncValue1/2 0x28/29 | `2D D4` |
| Fixed length, no DC-free, no CRC, no addr filter | RegPacketConfig1 0x30 | `00` |
| Packet (not continuous) data mode | RegPacketConfig2 0x31 | `40` |
| Fixed payload length = SX_FSK_RX_LEN (30) | RegPayloadLength 0x32 | `1E` |
| DIO0 = PayloadReady (also polled via RegIrqFlags2) | RegDioMapping1 0x40 | `00` |

**Framing (mirrors the CC1101 "drain a fixed count, dispatch by family" idea):**
FIXED-LENGTH FSK packet mode, `RegPayloadLength = 30` (>= the longest WS85 frame
28 B, <= the 64-byte FIFO). After the demodulator matches 0x2DD4 the radio latches
30 bytes and raises PayloadReady; `sx_weather_drain()`
(`firmware/src/cc1101_node/sx1278_weather.cpp`) reads all 30 out of RegFifo and
`fineoffset_decode()` picks the family (0x24 WS69 / 0x51 WH51 / 0x85 WS85),
ignoring trailing demodulator noise after a short frame. One config receives every
family. A `standby -> RX` after each drain (plus AutoRestartRx) re-arms sync.

SX1278 does **weather RX only**: OOK-continuous "remotes" RX needs the SX127x DIO2
data line, which this RA-02 adapter does not route.

---

## Host tests

`uv run --with pytest pytest firmware/tests` -> **120 passed** (was 114; +6 new in
`firmware/tests/test_sx1278_weather_rx.py`). The new tests drive the identical
`sx_weather_drain()` used by the firmware through a scripted RegFifo for
WH51/WS69/WS85 and assert the config registers above against the datasheet math.

## Build

`PATH=$HOME/.local/bin:$PATH python3 firmware/build.py` -> **SUCCESS**,
`tasmota32c3-cc1101.factory.bin` = 3,068,032 bytes, exit code 0 (uv on PATH).

---

## On-hardware validation (RA-02 node, MAC 44:1B:F6:2E:B3:80)

Single flash (esptool 4.7.0, hash verified), then commissioned over a persistent
pyserial console (`dtr=False rts=False`, one connection for the whole run — no
reflash, no repeated resets):

```
CC1: SX1278 present, RegVersion 0x12, SCK=3 MISO=7 MOSI=4 NSS=9 RST=10 DIO0=6
RSL: RESULT = {"Radio":{"Config":"sx1278","Active":"sx1278"}}
CC1: SX1278 FSK weather RX: 433.92 MHz 17.241 kbps sync 0x2DD4, fixed len 30
RSL: RESULT = {"SxStatus":{"Present":1,"VERSION":"0x12","Active":1,"Mode":"weather","WeatherRx":1,...}}
```

### EXACT decoded lines from the RA-02 node (host timestamps; node clock is 1970, no WiFi/NTP)

```
[20:42:59] 00:00:06.313 RSL: events = {"time":"1970-01-01T00:00:06","receiver":"cc1101-node-2EB380-4992","rssi":-91,"model":"Fineoffset-WS69","id":174,"battery_ok":1,"temperature_C":*float*,"humidity":79,"wind_dir_deg":357,"wind_avg_m_s":*float*,"wind_max_m_s":*float*,"rain_mm":*float*,"uv":0,"uvi":0,"light_lux":*float*,"mic":"CRC"}
[20:43:00] 00:00:11.226 RSL: events = {"time":"1970-01-01T00:00:11","receiver":"cc1101-node-2EB380-4992","rssi":-92,"model":"Fineoffset-WH51","id":"0f5d66","battery_ok":*float*,"battery_mV":1500,"moisture":38,"boost":0,"ad_raw":195,"mic":"CRC"}
[20:43:11] 00:00:22.356 RSL: events = {"time":"1970-01-01T00:00:22","receiver":"cc1101-node-2EB380-4992","rssi":-92,"model":"Fineoffset-WS69","id":174,...,"humidity":79,...,"mic":"CRC"}
# ... 22x WS69 id=174 and 3x WH51 id=0f5d66 total; and 17x raw undecoded frames
# published as CCRAW (CcRaw 1), e.g.:
[20:43:08] 00:00:19.151 RSL: CCRAW = {"Packet":"FF4C476FDEC0C1C2C3C4C5C6C7C8C9CACBAAAAD0D79C082C2BDEF009EECF","RSSI":-80}
# final status after the run:
[20:48:26] 00:05:37.400 RSL: RESULT = {"SxStatus":{"Present":1,"VERSION":"0x12","Active":1,"Mode":"weather","WeatherRx":1,"RSSI":-93,"Rx":43,"Decoded":27}}
```

Over the ~5.5-minute window: **25 decoded `events` published — 22x WS69 id=174,
3x WH51 id=0f5d66 — all `mic:CRC` valid.** `SxStatus` ended at `Rx=43, Decoded=27`
(27 vs 25 published because 2 identical repeats collapsed within the 500 ms
repeat-suppression window — correct behavior). 17 synced-but-undecoded frames were
published as raw `CCRAW` hex (`CcRaw 1`), i.e. the receiver is finding sync and the
FIFO drain works even on frames the decoder rejects.

The target unit **WH51 id 0f5c54** did not decode at the node in this window (see
"What didn't work" below); a *different* WH51 (id 0f5d66) did, so the WH51 family
path is proven, and WS69 id=174 decoded repeatedly.

### rpi5 reference lines cross-checked (same window, `~/wh51-watch`)

```
# WS69 (family 0x24, id 0xAE = 174) — reference cc1101 + lilygo:
{"ts":1788606887.43,"recv":"cc1101","rssi_dbm":-64.0,"hex":"24 AE 1F 02 18 4F 1B 05 07 F6 00 00 00 00 00 E9 60","family":"24"}
{"ts":1788606887.44,"recv":"lilygo","rssi_dbm":-62.0,"hex":"24 AE 1F 02 18 4F 1B 05 07 F6 00 00 00 00 00 E9 60","family":"24"}
#   id byte AE=174, humidity byte b[5]=0x4F=79 -> matches the node's WS69 id=174 humidity=79.

# WH51 target id 0f5c54 — reference cc1101, valid, within the node's window:
{"ts":1788606766.10,"recv":"cc1101","rssi_dbm":-82.0,"hex":"51 0F 5C 54 10 7F 28 F8 D0 FF FF FF 4B D7","id":"0f5c54","valid":true,"moisture_pct":40}
{"ts":1788606836.10,"recv":"cc1101","rssi_dbm":-82.0,"hex":"51 0F 5C 54 10 7F 28 F8 D0 FF FF FF 4B D7","id":"0f5c54","valid":true,"moisture_pct":40}
```

The node's WS69 id=174 (humidity 79) matches the reference frame exactly. The
reference heard the target WH51 0f5c54 at -82 dBm during the window; the node reads
its WS69 frames at -89..-93 dBm (weaker antenna/placement), so 0f5c54 fell below
the node's usable SNR — a per-sensor reception margin, not a decode failure (the
node decoded the on-air WH51 id 0f5d66 through the same path).

---

## Git log

```
7cc1235 cc1101-node docs: SX1278 (RA-02) FSK RX config + live-decode verification
7cb166d cc1101-node: SX1278 (RA-02) Fine Offset FSK receive path
70d34e2 cc1101-node: WAVE-A1FIX report (root cause, fix, host test, build, revalidation)
325bfb3 cc1101-node: host test for FSK RX FIFO drain + family dispatch
31ebb7f cc1101-node: Fine Offset FSK RX in infinite length mode (all frame lengths)
```
(the top two are this wave; a third commit adds this report)

---

## What didn't work / honesty notes (no overclaiming)

1. **Target WH51 id 0f5c54 not caught at the node.** The node decoded WS69 id=174
   and a WH51 (id 0f5d66), i.e. both required families, but not the *specific*
   0f5c54 unit in this window. The reference heard 0f5c54 at only -82 dBm and the
   node's WS69 frames read -89..-93 dBm, so 0f5c54 was below the node's SNR at its
   antenna. This is a reception-margin issue for one distant sensor, not a firmware
   fault — the WH51 family path itself decodes correctly (0f5d66, `mic:CRC` valid).
   No firmware change was made to "chase" it; doing so would risk wedging the node
   (the task's explicit constraint) for no config reason.

2. **Float fields render as `*float*` on-target** (`"temperature_C":*float*`, wind,
   rain, `battery_ok`). Cause: the shared decoder's `rf_json_append()` uses `%f` via
   `vsnprintf`, and the on-target newlib-nano printf has no float support, so the
   value is replaced by the literal `*float*`. This is a **pre-existing shared-decoder
   / target-libc behavior that affects the CC1101 weather path identically** — it is
   NOT introduced by, or specific to, the SX1278 path, and is out of scope for FSK-RX
   parity. Integer fields (id, humidity, moisture, battery_mV) and the CRC MIC decode
   correctly, so frame correctness is proven. Follow-up (separate from this wave):
   enable float printf (`-u _printf_float` / `board_build.f = ...`) or emit
   scaled-integer fields from the decoder.

3. **Hardware iteration deliberately stopped after one flash.** Per the wedge-risk
   constraint I flashed the RA-02 node exactly once and drove everything else over a
   single persistent serial session. I did not re-flash to hunt 0f5c54 or the
   `*float*` rendering.

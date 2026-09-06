/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "sx1278_radio.h"

/* SX127x crystal + derived steps (datasheet 4.1.1 / 4.1.5). */
static const double SX_FXOSC = 32000000.0;
static const double SX_FSTEP = SX_FXOSC / 524288.0;   // FXOSC / 2^19 = 61.03515625 Hz

void SX1278Radio::reset() {
  // SX127x hardware reset (datasheet 7.2.2): RST is active-low. Pull it low for >=100 us,
  // release it (high), then wait >=5 ms for the power-on-reset sequence to complete before
  // any SPI access. delay_ms(1)/delay_ms(10) are comfortably above those minimums.
  rst_.set(false);
  bus_.delay_ms(1);
  rst_.set(true);
  bus_.delay_ms(10);
}

bool SX1278Radio::identify(uint8_t* version) {
  uint8_t v = read_reg(SX_REG_VERSION);
  if (version) *version = v;
  if (v != SX_CHIP_VERSION) { err_ = "unexpected RegVersion"; return false; }
  return true;
}

uint8_t SX1278Radio::read_reg(uint8_t addr) {
  bus_.select();
  bus_.transfer(addr & 0x7F);          // bit7 = 0 -> read
  uint8_t v = bus_.transfer(0x00);     // dummy byte clocks the value out
  bus_.deselect();
  return v;
}

void SX1278Radio::write_reg(uint8_t addr, uint8_t val) {
  bus_.select();
  bus_.transfer(addr | SX_WRITE);      // bit7 = 1 -> write
  bus_.transfer(val);
  bus_.deselect();
}

/* ============================ Fine Offset FSK RECEIVE ============================
 * 2-FSK receive matched to the Fine Offset / Ecowitt on-air format, cross-checked against
 * the proven SX1276 receiver at the same Welland site (rpi5 ~/wh51-watch, RadioLib beginFSK):
 *
 *   carrier      433.92 MHz
 *   bit rate     17.241 kbps  (RegBitrate = FXOSC/bitrate = 0x0740)
 *   fdev         ~50 kHz      (RegFdev    = fdev/Fstep     = 0x0333)
 *   RX bandwidth 125 kHz      (RegRxBw mant=16 exp=2 -> 0x02; ~ Carson 2*(50+8.6) kHz)
 *   sync word    0x2DD4       (2 bytes, after the 0xAA preamble)  -- rtl_433 fineoffset
 *   modulation   2-FSK, no data shaping   (shaping is a TX-only concern; RX ignores it)
 *
 * Packet handling: FIXED-LENGTH packet mode, RegPayloadLength = SX_FSK_RX_LEN (30). After the
 * demodulator matches 0x2DD4, the radio latches SX_FSK_RX_LEN bytes into the FIFO and raises
 * PayloadReady; we drain them and dispatch by family byte. A short frame (WH51 14 B) simply
 * has the extra bytes filled with post-frame demodulator noise, which the decoder ignores --
 * exactly the CC1101 infinite-length "drain a fixed count" strategy, one config for every
 * family. AutoRestartRx (RegSyncConfig) re-arms sync detection after each read.
 * ================================================================================= */

void SX1278Radio::set_frequency(double hz) {
  uint32_t frf = (uint32_t)(hz / SX_FSTEP + 0.5);
  write_reg(SX_REG_FRF_MSB, (uint8_t)(frf >> 16));
  write_reg(SX_REG_FRF_MID, (uint8_t)(frf >> 8));
  write_reg(SX_REG_FRF_LSB, (uint8_t)(frf));
}

void SX1278Radio::set_payload_length(uint8_t n) {
  write_reg(SX_REG_PAYLOADLENGTH, n);
}

void SX1278Radio::configure_fineoffset_fsk() {
  // LongRangeMode (RegOpMode bit7) can only change in Sleep: force FSK sleep, then standby.
  write_reg(SX_REG_OPMODE, SX_OPMODE_FSK_SLEEP);
  write_reg(SX_REG_OPMODE, SX_OPMODE_FSK_STDBY);

  // Bit rate 17.241 kbps: RegBitrate = round(FXOSC / bitrate) = round(32e6 / 17241) = 0x0740.
  write_reg(SX_REG_BITRATE_MSB, 0x07);
  write_reg(SX_REG_BITRATE_LSB, 0x40);

  // Frequency deviation ~50 kHz: RegFdev = round(fdev / Fstep) = round(50000 / 61.035) = 0x0333.
  {
    uint32_t fdev = (uint32_t)(50000.0 / SX_FSTEP + 0.5);
    write_reg(SX_REG_FDEV_MSB, (uint8_t)((fdev >> 8) & 0x3F));
    write_reg(SX_REG_FDEV_LSB, (uint8_t)(fdev));
  }

  set_frequency(433920000.0);

  // RX front end: AGC auto (bit3), RX (re)start triggered on preamble detect (RxTrigger=110).
  // AFC left off so the receiver holds the programmed carrier rather than chasing per-frame offset.
  write_reg(SX_REG_RXCONFIG, 0x0E);
  write_reg(SX_REG_LNA, 0x20);           // LnaGain G1 (max); AGC-auto overrides during RX
  write_reg(SX_REG_RXBW, 0x02);          // 125 kHz
  write_reg(SX_REG_AFCBW, 0x02);         // 125 kHz (unused with AFC off; kept consistent)

  // Preamble detector on, 2 bytes, tolerance 10 -- gates the preamble RX trigger above.
  write_reg(SX_REG_PREAMBLEDETECT, 0xAA);

  // Sync: AutoRestartRx on with PLL relock (10b), 0xAA preamble polarity, SyncOn, 2 sync bytes.
  write_reg(SX_REG_SYNCCONFIG, 0x91);
  write_reg(SX_REG_SYNCVALUE1, 0x2D);
  write_reg(SX_REG_SYNCVALUE2, 0xD4);

  // Fixed-length packet mode, no DC-free, no CRC, no address filter; packet (not continuous) data mode.
  write_reg(SX_REG_PACKETCONFIG1, 0x00);
  write_reg(SX_REG_PACKETCONFIG2, 0x40);
  set_payload_length(SX_FSK_RX_LEN);

  // DIO0 = PayloadReady in packet RX (also polled via RegIrqFlags2, so the wire is optional).
  write_reg(SX_REG_DIOMAPPING1, 0x00);
}

void SX1278Radio::enter_rx()  { write_reg(SX_REG_OPMODE, SX_OPMODE_FSK_RX); }
void SX1278Radio::standby()   { write_reg(SX_REG_OPMODE, SX_OPMODE_FSK_STDBY); }

void SX1278Radio::restart_rx() {
  // Standby -> RX empties the FIFO and clears the RX flags (FifoOverrun/PayloadReady only
  // clear on leaving RX/standby), re-arming sync detection cleanly for the next frame.
  standby();
  enter_rx();
}

bool SX1278Radio::payload_ready() {
  return (read_reg(SX_REG_IRQFLAGS2) & SX_IRQ2_PAYLOAD_READY) != 0;
}

size_t SX1278Radio::read_fifo(uint8_t* d, size_t n) {
  bus_.select();
  bus_.transfer(SX_REG_FIFO & 0x7F);         // 0x00, bit7=0 -> read; FIFO addr does not increment
  for (size_t i = 0; i < n; i++) d[i] = bus_.transfer(0x00);
  bus_.deselect();
  return n;
}

int SX1278Radio::rssi_dbm() {
  // FSK RegRssiValue -> RSSI[dBm] = -RegRssiValue/2. Read after PayloadReady it reflects the
  // current (post-frame) level rather than the peak, so it is an approximate floor, not a
  // calibrated per-frame RSSI (same caveat as the CC1101 weather path).
  return -(int)read_reg(SX_REG_RSSIVALUE) / 2;
}

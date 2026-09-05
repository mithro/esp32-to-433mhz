/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "sx1278_radio.h"

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

/* ============================ STAGED RF ROADMAP (TODO) ============================
 * The foundation increment provides ONLY: reset, identify, register read/write, and
 * the radio-selection plumbing in xdrv_95_cc1101.ino. The RF path is intentionally
 * NOT wired yet. Bring it up in this order, each stage gated on real RA-02 hardware:
 *
 *   1. FSK-RX : RegOpMode -> FSK/standby; set carrier (RegFrf 0x06-0x08), bitrate
 *               (RegBitrate 0x02-0x03), fdev (RegFdev 0x04-0x05), RX bandwidth
 *               (RegRxBw 0x12); packet or continuous mode; read the FIFO when DIO0
 *               signals payload-ready. Mirrors the CC1101 "weather" (Fineoffset) path.
 *   2. FSK-TX : write the FIFO, RegOpMode -> TX, wait for DIO0 = packet-sent.
 *   3. OOK-RX : RegOpMode modulation = OOK; continuous mode -> raw demod bitstream.
 *               *** OOK-continuous needs a DIO2 wire that the current RA-02 adapter does
 *               NOT route (only DIO0 = GPIO6 is brought out). A future adapter revision
 *               must expose DIO2 before OOK-continuous RX is possible. ***
 *   4. OOK-TX : OOK modulation; key the PA from the FIFO / DIO2 data line.
 *   5. LoRa   : RegOpMode LongRangeMode = 1 selects the LoRa modem — a different
 *               register bank (spreading factor / bandwidth / coding rate) entirely.
 * ================================================================================= */

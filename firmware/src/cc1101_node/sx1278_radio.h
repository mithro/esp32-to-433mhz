/* SX1278 (RA-02) radio engine with an injectable SPI bus + reset line (host-testable).
 *
 * FOUNDATION increment: reset / identify / register I/O only. No FSK/OOK/LoRa RF yet —
 * see the staged-roadmap TODO block at the bottom of sx1278_radio.cpp.
 *
 * SX127x SPI framing: every access begins with an address byte whose bit7 selects the
 * direction (1 = write, 0 = read); the low 7 bits are the register address. A read then
 * clocks one dummy byte to shift the value out; a write clocks the value in.
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef SX1278_RADIO_H
#define SX1278_RADIO_H
#include <stdint.h>
#include "spi_bus.h"

enum : uint8_t {
  SX_REG_FIFO     = 0x00,
  SX_REG_OPMODE   = 0x01,   // (roadmap) mode + LongRangeMode/modulation select
  SX_REG_VERSION  = 0x42,   // silicon revision; 0x12 on SX1276/77/78/79
  SX_WRITE        = 0x80,   // address-byte bit7: 1 = write, 0 = read
  SX_CHIP_VERSION = 0x12,   // the value identify() expects in RegVersion
};

/* Active-low hardware RESET line for the SX127x, abstracted so the engine is host-testable
 * (the driver wires this to a GPIO; the host tests wire it to a recording fake). */
struct Sx1278ResetLine {
  virtual ~Sx1278ResetLine() {}
  virtual void set(bool high) = 0;   // drive the RST pin high (released) / low (asserted)
};

class SX1278Radio {
 public:
  SX1278Radio(SpiBus& bus, Sx1278ResetLine& rst) : bus_(bus), rst_(rst), err_("") {}
  void reset();                                // pulse RST low then high, wait for power-on reset
  bool identify(uint8_t* version);             // true iff RegVersion(0x42) == 0x12
  uint8_t read_reg(uint8_t addr);              // address bit7 forced to 0 (read)
  void write_reg(uint8_t addr, uint8_t val);   // address bit7 forced to 1 (write)
  const char* last_error() const { return err_; }

  // ---- Staged RF roadmap (foundation implements NONE of it) ----
  // FSK-RX -> FSK-TX -> OOK-RX -> OOK-TX -> LoRa. See the TODO block in sx1278_radio.cpp.

 private:
  SpiBus& bus_;
  Sx1278ResetLine& rst_;
  const char* err_;
};
#endif

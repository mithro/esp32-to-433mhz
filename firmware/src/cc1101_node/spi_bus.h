/* Dumb byte-oriented SPI bus, shared by every radio engine (CC1101, SX1278, ...).
 *
 * This interface is deliberately radio-agnostic: it does plain SPI framing only
 * (assert CS, clock bytes, release CS) plus timing helpers. It knows nothing about
 * any particular chip.
 *
 * NOTE (history): the CC1101 engine's old bus (CC1101Bus) made select() *wait for
 * MISO to go low* — the CC1101's CHIP_RDYn hand-shake. That wait is CC1101-specific
 * (an SX1278 does not drive CHIP_RDYn and would hang forever), so it has been moved
 * OUT of the bus and INTO the CC1101 engine (see CC1101Radio::reset(), which polls
 * the CHIP_RDYn bit of the status byte). select() here is now a plain "CS low".
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef SPI_BUS_H
#define SPI_BUS_H
#include <stdint.h>

struct SpiBus {
  virtual ~SpiBus() {}
  virtual void select() = 0;              // CS low (begin a transaction); no chip-ready wait
  virtual void deselect() = 0;            // CS high (end the transaction)
  virtual uint8_t transfer(uint8_t b) = 0;
  virtual void delay_ms(uint32_t ms) = 0;
  virtual uint32_t millis() = 0;
};

#endif

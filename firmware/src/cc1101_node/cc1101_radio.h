/* CC1101 radio engine with an injectable SPI bus (host-testable). SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef CC1101_RADIO_H
#define CC1101_RADIO_H
#include <stddef.h>
#include <stdint.h>
#include "spi_bus.h"
#include "cc1101_presets.h"

enum : uint8_t { CC_SRES = 0x30, CC_SFSTXON = 0x31, CC_SCAL = 0x33, CC_SRX = 0x34, CC_STX = 0x35, CC_SIDLE = 0x36,
                 CC_SFRX = 0x3A, CC_SFTX = 0x3B, CC_SNOP = 0x3D,
                 CC_PARTNUM = 0x30, CC_VERSION = 0x31, CC_RSSI = 0x34, CC_MARCSTATE = 0x35, CC_TXBYTES = 0x3A,
                 CC_RXBYTES = 0x3B, CC_PATABLE = 0x3E, CC_FIFO = 0x3F, CC_READ = 0x80, CC_BURST = 0x40,
                 CC_REG_PKTLEN = 0x06, CC_REG_PKTCTRL0 = 0x08, CC_REG_FREQ2 = 0x0D,
                 MARC_IDLE = 0x01, MARC_RX = 0x0D, MARC_RXFIFO_OVERFLOW = 0x11, MARC_TX = 0x13, MARC_TX_END = 0x14,
                 MARC_RXTX_SWITCH = 0x15, MARC_TXFIFO_UNDERFLOW = 0x16 };

/* The CC1101 engine drives a plain byte-SPI bus (see spi_bus.h). The CHIP_RDYn hand-shake
 * (wait for the chip to be ready after reset/power-up) is a CC1101 concern and lives in the
 * engine — reset() polls the CHIP_RDYn bit (0x80) of the status byte — NOT in the bus, whose
 * select() no longer waits on MISO (that would hang a chip like the SX1278 that shares the bus). */
using CC1101Bus = SpiBus;

class CC1101Radio {
 public:
  explicit CC1101Radio(SpiBus& bus) : bus_(bus), err_("") {}
  bool reset();                                         // SRES, then poll CHIP_RDYn (status byte 0x80)
  bool identify(uint8_t* partnum, uint8_t* version);    // true if PARTNUM==0x00 and VERSION in {0x04,0x14}
  void write_reg(uint8_t addr, uint8_t val);
  uint8_t read_reg(uint8_t addr);                       // config regs (< 0x30)
  uint8_t read_status(uint8_t addr);                    // status regs (>= 0x30): READ|BURST
  uint8_t strobe(uint8_t cmd);                          // returns status byte
  void burst_write(uint8_t addr, const uint8_t* d, size_t n);
  void burst_read(uint8_t addr, uint8_t* d, size_t n);
  void write_patable(const uint8_t* vals, size_t n);
  void load(const cc_reg_t* regs, size_t n);            // write a preset table (and its PATABLE if any via load_preset)
  bool load_preset(int id);                             // regs + patable
  void set_freq(double hz);                             // FREQ2/1/0 only (call after load)
  bool enter_rx();                                      // SIDLE, SFRX, SCAL, SRX; wait MARCSTATE==RX (≤50 ms)
  bool enter_tx();                                      // SIDLE, SFTX, STX; wait MARCSTATE==TX (≤50 ms)
  void idle();                                          // SIDLE
  uint8_t marcstate();
  int rssi_dbm();                                       // (signed RSSI)/2 - 74
  uint8_t rxbytes(bool* overflow);
  void flush_rx();
  void flush_tx();
  size_t read_fifo(uint8_t* d, size_t n);
  bool tx_bits(const uint8_t* bytes, size_t nbits, uint32_t timeout_ms);   // see cc1101.py transmit_bitstream
  const char* last_error() const { return err_; }
 private:
  bool wait_marc(uint8_t want, uint32_t timeout_ms);
  bool wait_tx_done(uint32_t timeout_ms);
  SpiBus& bus_;
  const char* err_;
};
#endif

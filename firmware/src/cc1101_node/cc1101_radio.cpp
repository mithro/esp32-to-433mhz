/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "cc1101_radio.h"

bool CC1101Radio::reset() {
  strobe(CC_SRES);
  bus_.delay_ms(50);
  for (int i = 0; i < 100; i++) { if (!(strobe(CC_SNOP) & 0x80)) return true; bus_.delay_ms(1); }
  err_ = "chip not ready after SRES"; return false;
}
bool CC1101Radio::identify(uint8_t* partnum, uint8_t* version) {
  *partnum = read_status(CC_PARTNUM); *version = read_status(CC_VERSION);
  if (*partnum != 0x00 || (*version != 0x14 && *version != 0x04)) { err_ = "unexpected PARTNUM/VERSION"; return false; }
  return true;
}
void CC1101Radio::write_reg(uint8_t addr, uint8_t val) { bus_.select(); bus_.transfer(addr & 0x3F); bus_.transfer(val); bus_.deselect(); }
uint8_t CC1101Radio::read_reg(uint8_t addr) { bus_.select(); bus_.transfer((addr & 0x3F) | CC_READ); uint8_t v = bus_.transfer(0); bus_.deselect(); return v; }
uint8_t CC1101Radio::read_status(uint8_t addr) { bus_.select(); bus_.transfer((addr & 0x3F) | CC_READ | CC_BURST); uint8_t v = bus_.transfer(0); bus_.deselect(); return v; }
uint8_t CC1101Radio::strobe(uint8_t cmd) { bus_.select(); uint8_t s = bus_.transfer(cmd); bus_.deselect(); return s; }
void CC1101Radio::burst_write(uint8_t addr, const uint8_t* d, size_t n) { bus_.select(); bus_.transfer((addr & 0x3F) | CC_BURST); for (size_t i = 0; i < n; i++) bus_.transfer(d[i]); bus_.deselect(); }
void CC1101Radio::burst_read(uint8_t addr, uint8_t* d, size_t n) { bus_.select(); bus_.transfer((addr & 0x3F) | CC_READ | CC_BURST); for (size_t i = 0; i < n; i++) d[i] = bus_.transfer(0); bus_.deselect(); }
void CC1101Radio::write_patable(const uint8_t* vals, size_t n) { burst_write(CC_PATABLE, vals, n); }
void CC1101Radio::load(const cc_reg_t* regs, size_t n) { strobe(CC_SIDLE); for (size_t i = 0; i < n; i++) write_reg(regs[i].addr, regs[i].val); }
bool CC1101Radio::load_preset(int id) {
  size_t n = 0; const cc_reg_t* regs = cc_preset_regs(id, &n);
  if (!regs) { err_ = "unknown preset"; return false; }
  load(regs, n);
  size_t pn = 0; const uint8_t* pa = cc_preset_patable(id, &pn);
  if (pa) write_patable(pa, pn);
  return true;
}
void CC1101Radio::set_freq(double hz) { uint8_t f[3]; cc_freq_regs(hz, f); strobe(CC_SIDLE); write_reg(CC_REG_FREQ2, f[0]); write_reg(CC_REG_FREQ2 + 1, f[1]); write_reg(CC_REG_FREQ2 + 2, f[2]); }
uint8_t CC1101Radio::marcstate() { return read_status(CC_MARCSTATE) & 0x1F; }
bool CC1101Radio::wait_marc(uint8_t want, uint32_t timeout_ms) {
  uint32_t t0 = bus_.millis();
  while (bus_.millis() - t0 <= timeout_ms) { if (marcstate() == want) return true; bus_.delay_ms(1); }
  err_ = "MARCSTATE timeout"; return false;
}
bool CC1101Radio::enter_rx() { strobe(CC_SIDLE); strobe(CC_SFRX); strobe(CC_SCAL); bus_.delay_ms(1); strobe(CC_SRX); return wait_marc(MARC_RX, 50); }
bool CC1101Radio::enter_tx() { strobe(CC_SIDLE); strobe(CC_SFTX); strobe(CC_STX); return wait_marc(MARC_TX, 50); }
void CC1101Radio::idle() { strobe(CC_SIDLE); }
int CC1101Radio::rssi_dbm() { int8_t raw = (int8_t)read_status(CC_RSSI); return raw / 2 - 74; }
uint8_t CC1101Radio::rxbytes(bool* overflow) { uint8_t v = read_status(CC_RXBYTES); if (overflow) *overflow = v & 0x80; return v & 0x7F; }
void CC1101Radio::flush_rx() { strobe(CC_SIDLE); strobe(CC_SFRX); }
void CC1101Radio::flush_tx() { strobe(CC_SIDLE); strobe(CC_SFTX); }
size_t CC1101Radio::read_fifo(uint8_t* d, size_t n) { burst_read(CC_FIFO, d, n); return n; }
bool CC1101Radio::wait_tx_done(uint32_t timeout_ms) {
  uint32_t t0 = bus_.millis();
  while (bus_.millis() - t0 <= timeout_ms) {
    uint8_t m = marcstate();
    if (m != MARC_TX && m != MARC_TX_END && m != MARC_RXTX_SWITCH) return true;
    bus_.delay_ms(1);
  }
  strobe(CC_SIDLE); err_ = "TX timeout"; return false;
}
/* Stream a bitstream through the TX FIFO. <= 64 bytes: fixed-length packet. Longer: CC1101 infinite-length
 * mode with FIFO refill (TXBYTES < 62), switching to fixed length when < 256 bytes remain (datasheet 15.3). */
bool CC1101Radio::tx_bits(const uint8_t* bytes, size_t nbits, uint32_t timeout_ms) {
  size_t n = (nbits + 7) / 8;
  if (n == 0) return true;
  strobe(CC_SIDLE); strobe(CC_SFTX);
  if (n <= 64) {
    write_reg(CC_REG_PKTCTRL0, 0x00); write_reg(CC_REG_PKTLEN, (uint8_t)n);
    burst_write(CC_FIFO, bytes, n);
    strobe(CC_STX);
    return wait_tx_done(timeout_ms);
  }
  write_reg(CC_REG_PKTLEN, (uint8_t)(n & 0xFF));
  write_reg(CC_REG_PKTCTRL0, 0x02);                     // infinite length
  burst_write(CC_FIFO, bytes, 64);
  size_t idx = 64; bool switched = false;
  strobe(CC_STX);
  if (n < 256) { write_reg(CC_REG_PKTCTRL0, 0x00); switched = true; }
  uint32_t t0 = bus_.millis();
  while (idx < n) {
    if (bus_.millis() - t0 > timeout_ms) { strobe(CC_SIDLE); err_ = "TX refill timeout"; return false; }
    uint8_t txb = read_status(CC_TXBYTES) & 0x7F;
    if (txb >= 62) continue;
    if (!switched && (n - idx) < 256) { write_reg(CC_REG_PKTCTRL0, 0x00); switched = true; }
    size_t space = 64 - txb, chunk = (n - idx < space) ? (n - idx) : space;
    burst_write(CC_FIFO, bytes + idx, chunk); idx += chunk;
  }
  return wait_tx_done(timeout_ms);
}

/* SX1278 (RA-02) radio engine with an injectable SPI bus + reset line (host-testable).
 *
 * Implements: reset / identify (RegVersion 0x12) / register I/O AND the Fine Offset
 * FSK RECEIVE path (2-FSK, 433.92 MHz, 17.241 kbps, ~50 kHz fdev, sync 0x2DD4). The RX
 * path mirrors the CC1101 "weather" path: run a fixed-length FSK packet whose length is
 * >= the longest Fine Offset frame, wait for PayloadReady, drain a fixed byte count out
 * of RegFifo and let fineoffset_decode() dispatch by family byte (see sx1278_weather.*).
 *
 * SX127x SPI framing: every access begins with an address byte whose bit7 selects the
 * direction (1 = write, 0 = read); the low 7 bits are the register address. A read then
 * clocks one dummy byte to shift the value out; a write clocks the value in. The FIFO
 * (register 0x00) does NOT auto-increment its address, so a burst read holds NSS low,
 * sends 0x00 once, then clocks N dummy bytes to pull N successive FIFO bytes out.
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef SX1278_RADIO_H
#define SX1278_RADIO_H
#include <stddef.h>
#include <stdint.h>
#include "spi_bus.h"

/* Fixed FSK payload length (RegPayloadLength) the receiver drains after every 0x2DD4 sync
 * match. Chosen >= the longest Fine Offset frame (WS85 = 28 B) yet <= the 64-byte FIFO, so
 * one packet setting receives every family (WH51 14 B / WS69 25 B / WS85 28 B): PayloadReady
 * fires once these many bytes are in, we read them all and fineoffset_decode() picks the
 * family and ignores the trailing bytes. sx1278_weather.h SX_FSK_DRAIN_LEN mirrors this. */
#define SX_FSK_RX_LEN 30

enum : uint8_t {
  SX_REG_FIFO          = 0x00,
  SX_REG_OPMODE        = 0x01,   // LongRangeMode/modulation select + operating mode
  SX_REG_BITRATE_MSB   = 0x02,   // bit rate = FXOSC / RegBitrate
  SX_REG_BITRATE_LSB   = 0x03,
  SX_REG_FDEV_MSB      = 0x04,   // fdev = Fstep * RegFdev  (Fstep = FXOSC/2^19)
  SX_REG_FDEV_LSB      = 0x05,
  SX_REG_FRF_MSB       = 0x06,   // carrier = Fstep * RegFrf
  SX_REG_FRF_MID       = 0x07,
  SX_REG_FRF_LSB       = 0x08,
  SX_REG_PA_CONFIG     = 0x09,
  SX_REG_LNA           = 0x0C,
  SX_REG_RXCONFIG      = 0x0D,   // AFC/AGC auto + RX trigger source
  SX_REG_RSSIVALUE     = 0x11,   // RSSI[dBm] = -RegRssiValue / 2
  SX_REG_RXBW          = 0x12,   // RX bandwidth (mantissa/exponent)
  SX_REG_AFCBW         = 0x13,
  SX_REG_PREAMBLEDETECT= 0x1F,   // preamble detector on/size/tolerance
  SX_REG_SYNCCONFIG    = 0x27,   // AutoRestartRx + sync-word on/size
  SX_REG_SYNCVALUE1    = 0x28,   // 0x2D
  SX_REG_SYNCVALUE2    = 0x29,   // 0xD4
  SX_REG_PACKETCONFIG1 = 0x30,   // fixed vs variable length, DcFree, CRC
  SX_REG_PACKETCONFIG2 = 0x31,   // packet vs continuous data mode
  SX_REG_PAYLOADLENGTH = 0x32,   // fixed payload length (bytes drained after sync)
  SX_REG_IRQFLAGS1     = 0x3E,   // ModeReady / RxReady / SyncAddressMatch
  SX_REG_IRQFLAGS2     = 0x3F,   // FifoFull / FifoEmpty / FifoOverrun / PayloadReady / CrcOk
  SX_REG_DIOMAPPING1   = 0x40,   // DIO0 = PayloadReady in packet RX
  SX_REG_VERSION       = 0x42,   // silicon revision; 0x12 on SX1276/77/78/79

  SX_WRITE             = 0x80,   // address-byte bit7: 1 = write, 0 = read
  SX_CHIP_VERSION      = 0x12,   // the value identify() expects in RegVersion

  // RegOpMode composed values: LongRangeMode=0 (FSK), LowFrequencyModeOn=1 (bit3, <525 MHz band).
  SX_OPMODE_FSK_SLEEP  = 0x00,   // FSK, sleep (only mode in which LongRangeMode may change)
  SX_OPMODE_FSK_STDBY  = 0x09,   // FSK, low-freq band, standby (0x08 | mode 001)
  SX_OPMODE_FSK_RX     = 0x0D,   // FSK, low-freq band, receiver (0x08 | mode 101)

  SX_IRQ2_PAYLOAD_READY= 0x04,   // RegIrqFlags2 bit2
  SX_IRQ2_FIFO_OVERRUN = 0x08,   // RegIrqFlags2 bit3
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

  // ---- Fine Offset FSK RECEIVE path (see sx1278_weather.*) ----
  void configure_fineoffset_fsk();             // program the full 2-FSK RX preset (fixed length = drain len)
  void set_frequency(double hz);               // RegFrf from a carrier in Hz
  void set_payload_length(uint8_t n);          // fixed FSK payload length (bytes read out per packet)
  void enter_rx();                             // RegOpMode -> FSK RX (continuous packet RX)
  void standby();                              // RegOpMode -> FSK standby
  void restart_rx();                           // standby -> RX: flush the FIFO and re-arm sync detection
  bool payload_ready();                        // RegIrqFlags2 PayloadReady bit set?
  size_t read_fifo(uint8_t* d, size_t n);      // burst-read n bytes out of RegFifo (0x00)
  int rssi_dbm();                              // -RegRssiValue / 2

  const char* last_error() const { return err_; }

 private:
  SpiBus& bus_;
  Sx1278ResetLine& rst_;
  const char* err_;
};
#endif

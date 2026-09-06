// Host harness for SX1278Radio: fake SPI bus (register file + scripted FIFO) + fake reset line.
// Mirrors tests/radio_host.cpp for the CC1101. SPDX-License-Identifier: GPL-3.0-or-later
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include "sx1278_radio.h"
#include "sx1278_weather.h"

struct FakeBus : SpiBus {
  std::vector<std::string> log;      // "S" select, "D" deselect, "xx" bytes clocked out
  uint8_t regs[0x80] = {0};
  std::vector<uint8_t> rxfifo;       // scripted RX FIFO bytes (streamed on reads of RegFifo 0x00)
  size_t rxpos = 0;
  int addr = -1; bool writing = false; uint32_t now = 0;
  void select() override { log.push_back("S"); addr = -1; }
  void deselect() override { log.push_back("D"); }
  uint8_t transfer(uint8_t b) override {
    char h[4]; snprintf(h, sizeof h, "%02x", b); log.push_back(h);
    if (addr < 0) { addr = b & 0x7F; writing = b & 0x80; return 0x00; }   // address byte
    if (writing) { regs[addr] = b; return 0x00; }
    if (addr == SX_REG_FIFO) return rxpos < rxfifo.size() ? rxfifo[rxpos++] : 0;  // FIFO stream (addr not incremented)
    return regs[addr];                                                            // ordinary register read
  }
  void delay_ms(uint32_t ms) override { now += ms; }
  uint32_t millis() override { return now; }
};

struct FakeReset : Sx1278ResetLine {
  std::vector<std::string> log;      // "L" low (asserted), "H" high (released)
  void set(bool high) override { log.push_back(high ? "H" : "L"); }
};

static void print_log(const std::vector<std::string>& log) {
  for (size_t i = 0; i < log.size(); i++) printf("%s\"%s\"", i ? "," : "", log[i].c_str());
}

// Parse a hex string ("510f5c54...") into bytes.
static std::vector<uint8_t> from_hex(const char* s) {
  std::vector<uint8_t> v;
  for (size_t i = 0; s[i] && s[i + 1]; i += 2) {
    auto nib = [](char c) -> int { return c <= '9' ? c - '0' : (c | 0x20) - 'a' + 10; };
    v.push_back((uint8_t)((nib(s[i]) << 4) | nib(s[i + 1])));
  }
  return v;
}

int main(int argc, char** argv) {
  FakeBus bus; FakeReset rst; SX1278Radio r(bus, rst);
  std::string cmd = argc > 1 ? argv[1] : "";
  if (cmd == "identify") {
    bus.regs[0x42] = 0x12;
    uint8_t v; bool ok = r.identify(&v);
    printf("{\"ok\":%d,\"ver\":%d,\"log\":[", ok, v); print_log(bus.log); printf("]}\n");
  } else if (cmd == "identify_bad") {
    bus.regs[0x42] = 0x00;
    uint8_t v; bool ok = r.identify(&v);
    printf("{\"ok\":%d,\"ver\":%d}\n", ok, v);
  } else if (cmd == "write_reg") {
    r.write_reg(0x01, 0x0A);
    printf("{\"reg1\":%d,\"log\":[", bus.regs[0x01]); print_log(bus.log); printf("]}\n");
  } else if (cmd == "read_reg") {
    bus.regs[0x06] = 0x6C;
    uint8_t v = r.read_reg(0x06);
    printf("{\"val\":%d,\"log\":[", v); print_log(bus.log); printf("]}\n");
  } else if (cmd == "reset") {
    r.reset();
    printf("{\"rst\":["); print_log(rst.log); printf("]}\n");
  } else if (cmd == "configure") {
    // Program the Fine Offset FSK RX preset; report the key registers so the test can assert
    // the exact bitrate/fdev/frf/sync/packet config against the datasheet math.
    r.configure_fineoffset_fsk();
    r.enter_rx();
    printf("{\"opmode\":%d,\"br_msb\":%d,\"br_lsb\":%d,\"fdev_msb\":%d,\"fdev_lsb\":%d,"
           "\"frf_msb\":%d,\"frf_mid\":%d,\"frf_lsb\":%d,\"rxbw\":%d,\"preambledetect\":%d,"
           "\"syncconfig\":%d,\"sync1\":%d,\"sync2\":%d,\"packetconfig1\":%d,\"packetconfig2\":%d,"
           "\"payloadlength\":%d,\"diomapping1\":%d,\"rxconfig\":%d}\n",
           bus.regs[0x01], bus.regs[0x02], bus.regs[0x03], bus.regs[0x04], bus.regs[0x05],
           bus.regs[0x06], bus.regs[0x07], bus.regs[0x08], bus.regs[0x12], bus.regs[0x1F],
           bus.regs[0x27], bus.regs[0x28], bus.regs[0x29], bus.regs[0x30], bus.regs[0x31],
           bus.regs[0x32], bus.regs[0x40], bus.regs[0x0D]);
  } else if (cmd == "weather_drain") {
    // weather_drain <fifo-hex> [irqflags2]
    //   fifo-hex  : bytes physically sitting in the RX FIFO (frame at the head + trailing noise)
    //   irqflags2 : value RegIrqFlags2 reports (default 0x04 = PayloadReady set); 0x00 => not ready
    std::vector<uint8_t> fifo = argc > 2 ? from_hex(argv[2]) : std::vector<uint8_t>();
    uint8_t irq2 = argc > 3 ? (uint8_t)strtoul(argv[3], nullptr, 0) : (uint8_t)SX_IRQ2_PAYLOAD_READY;
    bus.rxfifo = fifo;
    bus.regs[0x3F] = irq2;                 // RegIrqFlags2 (PayloadReady in bit2)
    bus.regs[0x11] = 0x50;                 // RegRssiValue 0x50 -> -0x50/2 = -40 dBm
    uint8_t raw[SX_FSK_DRAIN_LEN]; size_t n = 0; int rssi = 0; char json[512] = {0};
    int rc = sx_weather_drain(r, raw, sizeof raw, &n, &rssi, json, sizeof json);
    printf("{\"rc\":%d,\"n\":%zu,\"rssi\":%d,\"json\":%s}\n",
           rc, n, rssi, (rc == SX_WX_DECODED) ? json : "null");
  } else {
    fprintf(stderr, "usage: sx1278_host identify|identify_bad|write_reg|read_reg|reset|configure|weather_drain <hex> [irqflags2]\n");
    return 2;
  }
  return 0;
}

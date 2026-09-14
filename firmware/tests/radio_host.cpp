// Host harness for CC1101Radio: fake SPI bus with a scripted register file. SPDX-License-Identifier: GPL-3.0-or-later
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include "cc1101_radio.h"
#include "cc1101_presets.h"
#include "cc1101_weather.h"

struct FakeBus : CC1101Bus {
  std::vector<std::string> log;      // "S" select, "D" deselect, "xx" bytes
  uint8_t regs[0x40] = {0};          // config registers
  uint8_t status[0x40] = {0};        // status registers read with READ|BURST
  std::vector<uint8_t> rxfifo;       // scripted RX FIFO bytes (read via burst-read of 0x3F)
  size_t rxpos = 0;
  int addr = -1; bool burst = false; bool reading = false; uint32_t now = 0;
  void select() override { log.push_back("S"); addr = -1; }
  void deselect() override { log.push_back("D"); }
  uint8_t transfer(uint8_t b) override {
    char h[4]; snprintf(h, sizeof h, "%02x", b); log.push_back(h);
    if (addr < 0) { addr = b & 0x3F; burst = b & 0x40; reading = b & 0x80; return 0x0F; }   // status byte
    if (reading) {
      if (addr == CC_FIFO) return rxpos < rxfifo.size() ? rxfifo[rxpos++] : 0;              // RX FIFO stream
      return (burst && addr >= 0x30 && addr <= 0x3D) ? status[addr] : regs[addr];
    }
    regs[addr] = b; if (burst && addr < 0x3E) addr++;
    return 0x0F;
  }
  void delay_ms(uint32_t ms) override { now += ms; }
  uint32_t millis() override { return now; }
};

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
  FakeBus bus; CC1101Radio r(bus);
  std::string cmd = argc > 1 ? argv[1] : "";
  if (cmd == "identify") {
    bus.status[0x30] = 0x00; bus.status[0x31] = 0x14;
    uint8_t p, v; bool ok = r.identify(&p, &v);
    printf("{\"ok\":%d,\"part\":%d,\"ver\":%d}\n", ok, p, v);
  } else if (cmd == "load") {
    size_t n; const cc_reg_t* regs = cc_preset_regs(atoi(argv[2]), &n);
    r.load(regs, n);
    printf("{\"regs\":{");
    for (size_t i = 0; i < n; i++) { printf("%s\"%d\":%d", i ? "," : "", regs[i].addr, bus.regs[regs[i].addr]); }
    printf("}}\n");
  } else if (cmd == "enter_rx") {
    bus.status[0x35] = 0x0D;                                   // MARCSTATE says RX immediately
    bool ok = r.enter_rx();
    printf("{\"ok\":%d,\"log\":[", ok);
    for (size_t i = 0; i < bus.log.size(); i++) { printf("%s\"%s\"", i ? "," : "", bus.log[i].c_str()); }
    printf("]}\n");
  } else if (cmd == "tx_small") {
    bus.status[0x35] = 0x01;                                   // idle after TX (fake: never in TX)
    uint8_t data[] = {0xAA, 0x55, 0x0F};
    bool ok = r.tx_bits(data, 20, 100);
    printf("{\"ok\":%d,\"pktlen\":%d,\"pktctrl0\":%d,\"log\":[", ok, bus.regs[0x06], bus.regs[0x08]);
    for (size_t i = 0; i < bus.log.size(); i++) { printf("%s\"%s\"", i ? "," : "", bus.log[i].c_str()); }
    printf("]}\n");
  } else if (cmd == "weather_drain") {
    // weather_drain <fifo-hex> [rxbytes] [marcstate]
    //   fifo-hex  : bytes physically sitting in the RX FIFO (frame at the head + trailing noise)
    //   rxbytes   : value the RXBYTES status reg reports (default = fifo length); OR 0x80 in bit7
    //               marks an RX-FIFO overflow
    //   marcstate : MARCSTATE status value (default 0x0D = RX)
    std::vector<uint8_t> fifo = argc > 2 ? from_hex(argv[2]) : std::vector<uint8_t>();
    uint8_t rxb = argc > 3 ? (uint8_t)strtoul(argv[3], nullptr, 0) : (uint8_t)fifo.size();
    uint8_t marc = argc > 4 ? (uint8_t)strtoul(argv[4], nullptr, 0) : 0x0D;
    bus.rxfifo = fifo;
    bus.status[0x3B] = rxb;                 // RXBYTES (bit7 = overflow, low 7 = count)
    bus.status[0x35] = marc;                // MARCSTATE
    bus.status[0x34] = 0x60;               // RSSI raw 0x60 -> 0x60/2 - 74 = -26 dBm
    uint8_t raw[CC_FSK_DRAIN_LEN]; size_t n = 0; int rssi = 0; char json[512] = {0};
    int rc = cc_weather_drain(r, raw, sizeof raw, &n, &rssi, json, sizeof json);
    printf("{\"rc\":%d,\"n\":%zu,\"rssi\":%d,\"json\":%s}\n",
           rc, n, rssi, (rc == CC_WX_DECODED) ? json : "null");
  } else { fprintf(stderr, "usage: radio_host identify|load <id>|enter_rx|tx_small|weather_drain <hex> [rxbytes] [marc]\n"); return 2; }
  return 0;
}

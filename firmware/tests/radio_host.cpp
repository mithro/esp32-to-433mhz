// Host harness for CC1101Radio: fake SPI bus with a scripted register file. SPDX-License-Identifier: GPL-3.0-or-later
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>
#include "cc1101_radio.h"
#include "cc1101_presets.h"

struct FakeBus : CC1101Bus {
  std::vector<std::string> log;      // "S" select, "D" deselect, "xx" bytes
  uint8_t regs[0x40] = {0};          // config registers
  uint8_t status[0x40] = {0};        // status registers read with READ|BURST
  int addr = -1; bool burst = false; bool reading = false; uint32_t now = 0;
  void select() override { log.push_back("S"); addr = -1; }
  void deselect() override { log.push_back("D"); }
  uint8_t transfer(uint8_t b) override {
    char h[4]; snprintf(h, sizeof h, "%02x", b); log.push_back(h);
    if (addr < 0) { addr = b & 0x3F; burst = b & 0x40; reading = b & 0x80; return 0x0F; }   // status byte
    if (reading) { return (burst && addr >= 0x30 && addr <= 0x3D) ? status[addr] : regs[addr]; }
    regs[addr] = b; if (burst && addr < 0x3E) addr++;
    return 0x0F;
  }
  void delay_ms(uint32_t ms) override { now += ms; }
  uint32_t millis() override { return now; }
};

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
  } else { fprintf(stderr, "usage: radio_host identify|load <id>|enter_rx|tx_small\n"); return 2; }
  return 0;
}

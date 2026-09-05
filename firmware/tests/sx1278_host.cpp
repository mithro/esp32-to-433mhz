// Host harness for SX1278Radio: fake SPI bus (register file) + fake reset line. Mirrors
// tests/radio_host.cpp for the CC1101. SPDX-License-Identifier: GPL-3.0-or-later
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>
#include "sx1278_radio.h"

struct FakeBus : SpiBus {
  std::vector<std::string> log;      // "S" select, "D" deselect, "xx" bytes clocked out
  uint8_t regs[0x80] = {0};
  int addr = -1; bool writing = false; uint32_t now = 0;
  void select() override { log.push_back("S"); addr = -1; }
  void deselect() override { log.push_back("D"); }
  uint8_t transfer(uint8_t b) override {
    char h[4]; snprintf(h, sizeof h, "%02x", b); log.push_back(h);
    if (addr < 0) { addr = b & 0x7F; writing = b & 0x80; return 0x00; }   // address byte
    if (writing) { regs[addr] = b; return 0x00; }
    return regs[addr];                                                    // read: shift value out
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
  } else {
    fprintf(stderr, "usage: sx1278_host identify|identify_bad|write_reg|read_reg|reset\n");
    return 2;
  }
  return 0;
}

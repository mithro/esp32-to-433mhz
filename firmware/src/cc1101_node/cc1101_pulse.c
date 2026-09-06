/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "cc1101_pulse.h"

static void put_chip(uint8_t* out, size_t out_bytes, size_t idx, int one) {
  if (idx / 8 >= out_bytes) return;
  if (one) out[idx / 8] |= (uint8_t)(0x80 >> (idx % 8)); else out[idx / 8] &= (uint8_t)~(0x80 >> (idx % 8));
}
size_t pulses_to_chips(const uint32_t* us, size_t n, uint32_t chip_us, uint8_t* out, size_t out_bytes) {
  size_t idx = 0;
  for (size_t i = 0; i < out_bytes; i++) out[i] = 0;
  for (size_t i = 0; i < n; i++) {
    uint32_t k = (us[i] + chip_us / 2) / chip_us;
    int mark = (i % 2) == 0;
    if (mark && k == 0) k = 1;
    for (uint32_t j = 0; j < k && idx / 8 < out_bytes; j++) put_chip(out, out_bytes, idx++, mark);
  }
  return idx;
}
size_t chips_to_pulses(const uint8_t* chips01, size_t n, uint32_t chip_us, uint32_t* us, size_t max) {
  size_t i = 0, m = 0;
  while (i < n && !chips01[i]) i++;                      /* start on the first 1-chip (a mark) */
  while (i < n && m < max) {
    uint8_t lvl = chips01[i]; size_t run = 0;
    while (i < n && chips01[i] == lvl) { run++; i++; }
    us[m++] = (uint32_t)run * chip_us;
  }
  return m;
}
size_t rcswitch1_pulses(uint32_t data, unsigned bits, uint32_t p, uint32_t* us, size_t max) {
  size_t m = 0;
  for (int i = (int)bits - 1; i >= 0 && m + 2 <= max; i--) {
    int one = (data >> i) & 1;
    us[m++] = one ? 3 * p : p; us[m++] = one ? p : 3 * p;
  }
  if (m + 2 <= max) { us[m++] = p; us[m++] = 31 * p; }
  return m;
}
size_t pwm_code_pulses(uint64_t code, unsigned bits, uint32_t short_us, uint32_t long_us, uint32_t gap_us, uint32_t* us, size_t max) {
  size_t m = 0;
  for (int i = (int)bits - 1; i >= 0 && m + 2 <= max; i--) {
    int one = (code >> i) & 1;                              /* repo convention: long mark = 1 */
    us[m++] = one ? long_us : short_us; us[m++] = one ? short_us : long_us;
  }
  if (m) us[m - 1] = gap_us;
  return m;
}
size_t edges_to_pulses(const uint32_t* t_us, const uint8_t* level_after, size_t n, uint32_t* us, size_t max) {
  size_t i = 0, m = 0;
  while (i < n && !level_after[i]) i++;                  /* first rising edge */
  for (; i + 1 < n && m < max; i++) us[m++] = t_us[i + 1] - t_us[i];
  return m;
}

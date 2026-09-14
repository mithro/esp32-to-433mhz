/* SPDX-License-Identifier: GPL-3.0-or-later */
#include <stdio.h>
#include <string.h>
#include "secplus2.h"
#include "secplus/secplus.h"

static size_t push_manchester(uint8_t* chips, size_t max, size_t idx, int bit) {   /* 0 -> 1,0 ; 1 -> 0,1 */
  if (idx + 2 > max) return idx;
  chips[idx++] = bit ? 0 : 1; chips[idx++] = bit ? 1 : 0; return idx;
}
static size_t push_packet(uint8_t* chips, size_t max, size_t idx, int frame_id, const uint8_t* payload, size_t nbits) {
  for (int i = 0; i < 16; i++) idx = push_manchester(chips, max, idx, 0);
  for (int i = 0; i < 4; i++) idx = push_manchester(chips, max, idx, 1);
  idx = push_manchester(chips, max, idx, 0); idx = push_manchester(chips, max, idx, frame_id);
  for (size_t i = 0; i < nbits; i++) idx = push_manchester(chips, max, idx, (payload[i / 8] >> (7 - i % 8)) & 1);
  for (int i = 0; i < SECPLUS2_BLANK_CHIPS && idx < max; i++) chips[idx++] = 0;
  return idx;
}
size_t secplus2_encode_chips(uint32_t rolling, uint64_t fixed, int has_data, uint32_t data, uint8_t* chips, size_t max) {
  uint8_t p1[8] = {0}, p2[8] = {0};
  uint8_t frame_type = has_data ? 1 : 0;
  if (encode_v2(rolling, fixed, has_data ? data : 0, frame_type, p1, p2) < 0) return 0;
  size_t nbits = frame_type ? 64 : 40, idx = 0;
  idx = push_packet(chips, max, idx, 0, p1, nbits);
  idx = push_packet(chips, max, idx, 1, p2, nbits);
  return idx;
}
/* pulses -> chips at 250 us (runs of 1 or 2 only are valid Manchester; longer marks are junk) */
static size_t slice_chips(const uint32_t* us, size_t n, uint8_t* chips, size_t max) {
  size_t idx = 0;
  for (size_t i = 0; i < n && idx < max; i++) {
    uint32_t k = (us[i] + SECPLUS2_CHIP_US / 2) / SECPLUS2_CHIP_US;
    uint32_t dev = (us[i] > k * SECPLUS2_CHIP_US) ? us[i] - k * SECPLUS2_CHIP_US : k * SECPLUS2_CHIP_US - us[i];
    if (k == 0 || dev > 80) { if (i % 2 == 0) return 0; k = (k == 0) ? 1 : k; }    /* a bad mark kills the frame; a long space just ends it */
    if (i % 2 == 1 && k > 40) { break; }
    for (uint32_t j = 0; j < k && idx < max; j++) chips[idx++] = (i % 2 == 0);
  }
  return idx;
}
int secplus2_demod(const uint32_t* us, size_t n, uint8_t* frame_id, uint8_t* payload, size_t* payload_bits) {
  uint8_t chips[400]; size_t nc = slice_chips(us, n, chips, sizeof chips);
  static const uint8_t pat[24] = {1,0,1,0,1,0,1,0,1,0,1,0,1,0,1,0, 0,1,0,1,0,1,0,1};   /* 8 zeros + 1111 */
  for (size_t s = 0; s + 24 + 4 <= nc; s++) {
    if (memcmp(chips + s, pat, 24) != 0) continue;
    size_t p = s + 24;                                     /* frame id (2 bits) then payload */
    uint8_t bits[70]; size_t nb = 0;
    while (p + 1 < nc && nb < 66) {
      if (chips[p] == 1 && chips[p + 1] == 0) bits[nb++] = 0;
      else if (chips[p] == 0 && chips[p + 1] == 1) bits[nb++] = 1;
      else break;
      p += 2;
    }
    if (nb < 42) return 0;
    if (bits[0] != 0) return 0;                            /* frame id is 00 or 01 */
    *frame_id = bits[1];
    size_t want = (bits[2] == 0 && bits[3] == 0) ? 40 : 64;  /* payload type 00 -> 40-bit half, 01 -> 64-bit */
    if (nb < 2 + want) return 0;
    memset(payload, 0, 8);
    for (size_t i = 0; i < want; i++) if (bits[2 + i]) payload[i / 8] |= (uint8_t)(0x80 >> (i % 8));
    *payload_bits = want;
    return 1;
  }
  return 0;
}
int secplus2_collect(secplus2_state_t* st, uint8_t frame_id, const uint8_t* payload, size_t bits, uint32_t now_ms, char* json, size_t json_len) {
  if (st->have1 && now_ms - st->t1_ms > SECPLUS2_HALF_TIMEOUT_MS) st->have1 = 0;
  if (frame_id == 0) { memcpy(st->p1, payload, 8); st->bits1 = bits; st->t1_ms = now_ms; st->have1 = 1; return 0; }
  if (!st->have1 || st->bits1 != bits) return 0;
  uint32_t rolling = 0, data = 0; uint64_t fixed = 0;
  uint8_t frame_type = (bits == 64) ? 1 : 0;
  st->have1 = 0;
  if (decode_v2(frame_type, st->p1, payload, &rolling, &fixed, &data) < 0) return -1;
  unsigned long long rid = (unsigned long long)(fixed & 0xF0FFFFFFFFULL);
  int button = (int)((fixed >> 32) & 0xF);
  int len = snprintf(json, json_len, "{\"model\":\"Secplus-v2\",\"id\":%llu,\"button\":%d,\"rolling\":%lu,\"fixed\":%llu",
                     rid, button, (unsigned long)rolling, (unsigned long long)fixed);
  if (frame_type) len += snprintf(json + len, json_len - len, ",\"data\":%lu", (unsigned long)data);
  snprintf(json + len, json_len - len, "}");
  return 1;
}

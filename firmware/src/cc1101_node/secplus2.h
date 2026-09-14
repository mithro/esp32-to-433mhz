/* Security+ 2.0 over-the-air framing (Manchester, 250 us chips) around argilo/secplus encode_v2/decode_v2.
 * SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef SECPLUS2_H
#define SECPLUS2_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
#define SECPLUS2_CHIP_US 250
#define SECPLUS2_BLANK_CHIPS 33
#define SECPLUS2_HALF_TIMEOUT_MS 800
typedef struct { uint8_t have1; uint8_t p1[8]; size_t bits1; uint32_t t1_ms; } secplus2_state_t;
/* Manchester chips for one transmission (packet1, blank, packet2, blank). Returns chip count (0 on error). */
size_t secplus2_encode_chips(uint32_t rolling, uint64_t fixed, int has_data, uint32_t data, uint8_t* chips01, size_t max);
/* Find one packet in a mark/space pulse list. payload_bytes holds 40 or 64 bits MSB-first. 1 found / 0 none. */
int secplus2_demod(const uint32_t* us, size_t n, uint8_t* frame_id, uint8_t* payload_bytes, size_t* payload_bits);
/* Pair halves; 1 = decoded (json filled), 0 = waiting, -1 = decode error. */
int secplus2_collect(secplus2_state_t* st, uint8_t frame_id, const uint8_t* payload, size_t bits, uint32_t now_ms, char* json, size_t json_len);
#ifdef __cplusplus
}
#endif
#endif

/* Fineoffset / Ecowitt FSK decoders (WS69 family 0x24, WH51 family 0x51, WS85 family 0x85).
 * SPDX-License-Identifier: GPL-2.0-or-later
 * Ported from rtl_433 src/devices/fineoffset.c and fineoffset_ws85.c. */
#ifndef DECODE_FINEOFFSET_H
#define DECODE_FINEOFFSET_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* b = payload bytes as they follow the 2DD4 sync word (family byte first).
 * Family 0x24: n >= 25 -> "Fineoffset-WS69" (by length as rtl_433 does), 17 <= n < 25 -> "Fineoffset-WH65B".
 *   The 8-byte tail (if n >= 25) has its own CRC/sum; tail CRC/sum validity gates pressure_hPa emission only.
 * Family 0x51: WH51 soil moisture, 14-byte frame (n >= 14; trailing bytes ignored so a WH51
 *   frame decodes even inside a longer fixed-length FSK read). CRC-8 poly 0x31 + additive sum.
 * Family 0x85: WS85 (n >= 28).
 * Returns RF_DECODE_* ; on RF_DECODE_OK json holds one rtl_433-shaped object. */
int fineoffset_decode(const uint8_t *b, size_t n, char *json, size_t json_len);
#ifdef __cplusplus
}
#endif
#endif

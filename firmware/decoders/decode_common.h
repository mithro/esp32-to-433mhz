/* Common helpers shared by all rf433 decoders.
 * SPDX-License-Identifier: GPL-2.0-or-later
 * rf_crc8 / rf_add_bytes are ports of rtl_433 src/bit_util.c (GPL-2.0+). */
#ifndef DECODE_COMMON_H
#define DECODE_COMMON_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

#define RF_JSON_MAX 512

enum {
    RF_DECODE_OK        =  1,   /* decoded; json filled */
    RF_DECODE_NONE      =  0,   /* not this protocol */
    RF_DECODE_BAD_MIC   = -1,   /* checksum/CRC failed */
    RF_DECODE_TOO_SHORT = -2,
    RF_DECODE_TRUNCATED = -3,   /* json buffer too small */
};

/* CRC-8, MSB-first, as rtl_433 crc8(): e.g. poly 0x31 init 0 for Fineoffset. */
uint8_t rf_crc8(const uint8_t *msg, size_t n, uint8_t poly, uint8_t init);
/* Byte sum modulo 256, as rtl_433 add_bytes(). */
uint8_t rf_add_bytes(const uint8_t *msg, size_t n);

/* snprintf-append into json at offset len. Returns the new length, or -1
 * if len was already -1 or the result did not fit (NUL always written). */
int rf_json_append(char *json, size_t json_len, int len, const char *fmt, ...);

/* Render `value` as a fixed-point decimal with `decimals` (0, 1 or 2)
 * fractional digits (e.g. 13.1, 1013.25, -0.4) into buf, and return buf. Uses
 * only integer printf conversions: the ESP32-C3 Tasmota image links picolibc's
 * size-optimised integer-only printf (tinystdio __i_vfprintf), which renders
 * %f/%g as the literal "*float*". Formatting decimals ourselves keeps the
 * weather JSON numeric on-target. buf should hold at least 32 bytes.
 * Rounds half away from zero. */
const char *rf_ftoa(char *buf, size_t bufsz, double value, int decimals);

#ifdef __cplusplus
}
#endif
#endif

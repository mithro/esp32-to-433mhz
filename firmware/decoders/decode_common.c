/* SPDX-License-Identifier: GPL-2.0-or-later
 * rf_crc8/rf_add_bytes ported from rtl_433 src/bit_util.c, (c) rtl_433 authors. */
#include <stdarg.h>
#include <stdio.h>
#include "decode_common.h"

uint8_t rf_crc8(const uint8_t *msg, size_t n, uint8_t poly, uint8_t init)
{
    uint8_t rem = init;
    for (size_t i = 0; i < n; ++i) {
        rem ^= msg[i];
        for (int bit = 0; bit < 8; ++bit)
            rem = (rem & 0x80) ? (uint8_t)((rem << 1) ^ poly) : (uint8_t)(rem << 1);
    }
    return rem;
}

uint8_t rf_add_bytes(const uint8_t *msg, size_t n)
{
    unsigned sum = 0;
    for (size_t i = 0; i < n; ++i) sum += msg[i];
    return (uint8_t)sum;
}

int rf_json_append(char *json, size_t json_len, int len, const char *fmt, ...)
{
    if (len < 0 || (size_t)len >= json_len) return -1;
    va_list ap;
    va_start(ap, fmt);
    int r = vsnprintf(json + len, json_len - (size_t)len, fmt, ap);
    va_end(ap);
    if (r < 0 || (size_t)r >= json_len - (size_t)len) return -1;
    return len + r;
}

/* Fixed-point decimal formatter (see decode_common.h for why %f is avoided).
 * Splits the rounded, scaled value into whole and fractional parts and prints
 * them with %d, so it depends only on integer printf. Rounds half away from
 * zero, matching the %.Nf output these decoders used previously. Only one or two
 * fractional digits are needed here (weather values); the whole part fits int.
 * Fixed-width conversions keep gcc -Wformat-truncation happy for a 32-byte buf. */
const char *rf_ftoa(char *buf, size_t bufsz, double value, int decimals)
{
    long scale = 1;
    for (int i = 0; i < decimals; ++i) scale *= 10;
    double rounded = value * (double)scale + (value >= 0 ? 0.5 : -0.5);
    long scaled = (long)rounded;
    int neg = scaled < 0;
    long mag = neg ? -scaled : scaled;
    int whole = (int)(mag / scale);
    int frac = (int)(mag % scale);
    const char *sign = neg ? "-" : "";
    if (decimals == 2)
        snprintf(buf, bufsz, "%s%d.%02d", sign, whole, frac);
    else if (decimals == 1)
        snprintf(buf, bufsz, "%s%d.%d", sign, whole, frac);
    else
        snprintf(buf, bufsz, "%s%d", sign, whole);
    return buf;
}

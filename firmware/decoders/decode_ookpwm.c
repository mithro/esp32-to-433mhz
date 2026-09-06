/* SPDX-License-Identifier: Apache-2.0 */
#include "decode_common.h"
#include "decode_ookpwm.h"

typedef struct {
    const char *family;
    uint32_t short_us, long_us;   /* nominal mark widths */
    uint32_t reset_us;            /* a space >= this ends the packet */
} pwm_family_t;

/* Timings from protocols/ook-pwm-remotes.md (rtl_433 flex specs s/l/r).
 * Best-match by relative error (lowest score); table order does not matter
 * except on an exact score tie, which resolves in table order. */
static const pwm_family_t FAMILIES[] = {
    {"standard",     200,  730, 2500},   /* grey power remotes s=200 l=730 r=7300; doorbell s=208 l=724 */
    {"fixed-period", 340, 1000, 1012},   /* bed remote s=340 l=1000 r=1012 */
};
#define NFAM (sizeof(FAMILIES) / sizeof(FAMILIES[0]))

static int within(uint32_t v, uint32_t nominal, uint32_t pct)
{
    uint32_t tol = nominal * pct / 100;
    return v + tol >= nominal && v <= nominal + tol;
}

/* Try to decode one packet starting at mark index i (even) with one family.
 * On success fills bits/nbits, stats, and sets *end to the index after the packet. */
static int try_family(const pwm_family_t *f, const uint32_t *us, size_t n, size_t i,
                      uint8_t *bits, int *nbits, uint32_t *sh, uint32_t *lo, uint32_t *gap, size_t *end)
{
    uint32_t mid = (f->short_us + f->long_us) / 2;
    uint32_t sum_s = 0, cnt_s = 0, sum_l = 0, cnt_l = 0;
    int nb = 0;
    size_t k = i;
    while (k < n && nb < OOKPWM_MAX_BITS) {
        uint32_t mark = us[k];
        if (!within(mark, f->short_us, 45) && !within(mark, f->long_us, 35)) break; /* not ours */
        int is_long = mark > mid;
        if (is_long) { sum_l += mark; cnt_l++; } else { sum_s += mark; cnt_s++; }
        bits[nb++] = (uint8_t)(is_long == OOKPWM_LONG_IS_ONE);
        k++;                                            /* space (may be missing at the very end) */
        uint32_t space = (k < n) ? us[k] : f->reset_us; /* missing trailing space == reset */
        k++;
        if (space >= f->reset_us) { *gap = space; break; }
    }
    /* cnt_s == 0 || cnt_l == 0 rejects packets whose marks are all-short or
     * all-long (uniform bit codes); known limitation, no local code is uniform. */
    if (nb < OOKPWM_MIN_BITS || cnt_s == 0 || cnt_l == 0) return 0;
    *nbits = nb;
    *sh = sum_s / cnt_s;
    *lo = sum_l / cnt_l;
    *end = k;
    return 1;
}

static int emit(const pwm_family_t *f, const uint8_t *bits, int nbits, uint32_t sh, uint32_t lo,
                uint32_t gap, char *json, size_t json_len)
{
    int pad = (4 - nbits % 4) % 4;
    int digits = (nbits + pad) / 4;
    char code[OOKPWM_MAX_BITS / 4 + 2];
    int ci = 0;
    for (int d = 0; d < digits; ++d) {
        int v = 0;
        for (int b = 0; b < 4; ++b) {
            int idx = d * 4 + b;
            v = (v << 1) | (idx < nbits ? bits[idx] : 0);
        }
        code[ci++] = "0123456789abcdef"[v];
    }
    code[ci] = 0;
    int len = rf_json_append(json, json_len, 0,
        "{\"model\":\"OOK-PWM\",\"family\":\"%s\",\"bits\":%d,\"code\":\"%s\",\"short_us\":%u,\"long_us\":%u,\"gap_us\":%u}",
        f->family, nbits, code, (unsigned)sh, (unsigned)lo, (unsigned)gap);
    return len < 0 ? RF_DECODE_TRUNCATED : RF_DECODE_OK;
}

int ookpwm_decode(const uint32_t *us, size_t n, size_t *pos, char *json, size_t json_len)
{
    size_t i = *pos;
    if (i & 1) i++;                                   /* always start on a mark */
    while (i < n) {
        int best_fi = -1;
        uint32_t best_score = (uint32_t)-1;
        uint8_t best_bits[OOKPWM_MAX_BITS];
        int best_nbits = 0;
        uint32_t best_sh = 0, best_lo = 0, best_gap = 0;
        size_t best_end = i;

        for (size_t fi = 0; fi < NFAM; ++fi) {
            uint8_t bits[OOKPWM_MAX_BITS];
            int nbits = 0;
            uint32_t sh = 0, lo = 0, gap = 0;
            size_t end = i;
            if (try_family(&FAMILIES[fi], us, n, i, bits, &nbits, &sh, &lo, &gap, &end)) {
                /* Calculate score: relative error sum for short and long marks */
                uint32_t score = (sh > FAMILIES[fi].short_us ? sh - FAMILIES[fi].short_us : FAMILIES[fi].short_us - sh) * 1000 / FAMILIES[fi].short_us
                               + (lo > FAMILIES[fi].long_us ? lo - FAMILIES[fi].long_us : FAMILIES[fi].long_us - lo) * 1000 / FAMILIES[fi].long_us;
                if (score < best_score) {
                    best_score = score;
                    best_fi = (int)fi;
                    best_nbits = nbits;
                    best_sh = sh;
                    best_lo = lo;
                    best_gap = gap;
                    best_end = end;
                    for (int bi = 0; bi < nbits; ++bi) {
                        best_bits[bi] = bits[bi];
                    }
                }
            }
        }

        if (best_fi >= 0) {
            *pos = best_end;
            return emit(&FAMILIES[best_fi], best_bits, best_nbits, best_sh, best_lo, best_gap, json, json_len);
        }

        i += 2;                                       /* slide to the next mark */
    }
    *pos = n;
    return RF_DECODE_NONE;
}

/* SPDX-License-Identifier: GPL-2.0-or-later
 * Ported from rtl_433 (c) Christian W. Zuckschwerdt and contributors:
 *   src/devices/fineoffset.c (fineoffset_WH24_callback), fineoffset_ws85.c. */
#include "decode_common.h"
#include "decode_fineoffset.h"

/* WH24 / WH65B / WS69: FF II DD VT TT HH WW GG RR RR UU UU LL LL LL CC BB [+8 WS69 tail] */
static int decode_wh24_family(const uint8_t *b, size_t n, char *json, size_t json_len)
{
    if (n < 17) return RF_DECODE_TOO_SHORT;
    if (rf_crc8(b, 16, 0x31, 0x00) != 0 || rf_add_bytes(b, 16) != b[16]) return RF_DECODE_BAD_MIC;

    int ws69 = 0;
    double pressure_hpa = -1.0;
    if (n >= 25) {                                  /* WS69 tail: 6 bytes + CRC + SUM */
        ws69 = 1;                                   /* WS69 named by frame length (rtl_433 behavior); tail CRC/sum validity only gates pressure_hPa */
        if (rf_crc8(b, 24, 0x31, 0x00) == 0 && rf_add_bytes(b, 24) == b[24]) {
            /* pressure offsets b[17..19] (0.01 hPa, 0x01FFFF = no sensor) per
             * rtl_433 fineoffset.c; not yet cross-checked against a real
             * barometer-equipped frame. */
            long praw = ((long)b[17] << 16) | ((long)b[18] << 8) | b[19];   /* 0x01FFFF = none */
            if (praw < 0x01FFFF) pressure_hpa = praw * 0.01;
        }
    }

    int id          = b[1];
    int wind_dir    = b[2] | ((b[3] & 0x80) << 1);          /* 0x1FF invalid */
    int low_batt    = (b[3] & 0x08) >> 3;
    int temp_raw    = ((b[3] & 0x07) << 8) | b[4];          /* 0x7FF invalid */
    int humidity    = b[5];                                 /* 0xFF invalid */
    int wind_raw    = b[6] | ((b[3] & 0x10) << 4);          /* 0x1FF invalid */
    int gust_raw    = b[7];                                 /* 0xFF invalid */
    int rain_raw    = (b[8] << 8) | b[9];
    int uv_raw      = (b[10] << 8) | b[11];                 /* 0xFFFF invalid */
    long light_raw  = ((long)b[12] << 16) | ((long)b[13] << 8) | b[14]; /* 0xFFFFFF invalid */
    /* WS69/WH65 factors (WH24 would be 1.12 m/s and 0.3 mm; our fleet is WS69). */
    const double wind_factor = 0.51, rain_cup_mm = 0.254;
    static const int uvi_upper[13] = {432, 851, 1210, 1570, 2017, 2450, 2761, 3100, 3512, 3918, 4277, 4650, 5029};
    int uvi = 0;
    while (uvi < 13 && uvi_upper[uvi] < uv_raw) ++uvi;

    int len = 0;
    len = rf_json_append(json, json_len, len, "{\"model\":\"%s\",\"id\":%d,\"battery_ok\":%d",
                         ws69 ? "Fineoffset-WS69" : "Fineoffset-WH65B", id, !low_batt);
    if (temp_raw != 0x7FF)   len = rf_json_append(json, json_len, len, ",\"temperature_C\":%.1f", (temp_raw - 400) * 0.1);
    if (humidity != 0xFF)    len = rf_json_append(json, json_len, len, ",\"humidity\":%d", humidity);
    if (pressure_hpa >= 0)   len = rf_json_append(json, json_len, len, ",\"pressure_hPa\":%.2f", pressure_hpa);
    if (wind_dir != 0x1FF)   len = rf_json_append(json, json_len, len, ",\"wind_dir_deg\":%d", wind_dir);
    if (wind_raw != 0x1FF)   len = rf_json_append(json, json_len, len, ",\"wind_avg_m_s\":%.1f", wind_raw * 0.125 * wind_factor);
    if (gust_raw != 0xFF)    len = rf_json_append(json, json_len, len, ",\"wind_max_m_s\":%.1f", gust_raw * wind_factor);
    len = rf_json_append(json, json_len, len, ",\"rain_mm\":%.1f", rain_raw * rain_cup_mm);
    if (uv_raw != 0xFFFF)    len = rf_json_append(json, json_len, len, ",\"uv\":%d,\"uvi\":%d", uv_raw, uvi);
    if (light_raw != 0xFFFFFF) len = rf_json_append(json, json_len, len, ",\"light_lux\":%.1f", light_raw * 0.1);
    len = rf_json_append(json, json_len, len, ",\"mic\":\"CRC\"}");
    return len < 0 ? RF_DECODE_TRUNCATED : RF_DECODE_OK;
}

/* WS85: YY II II II BB FF UU WW DD GG UU UU RS UU UU R1 R2 SS ... ZZ XX AA  (28+ bytes) */
static int decode_ws85(const uint8_t *b, size_t n, char *json, size_t json_len)
{
    if (n < 28) return RF_DECODE_TOO_SHORT;
    if (rf_crc8(b, 26, 0x31, 0x00) != b[26] || rf_add_bytes(b, 27) != b[27]) return RF_DECODE_BAD_MIC;

    long id         = ((long)b[1] << 16) | ((long)b[2] << 8) | b[3];
    int battery_mv  = b[4] * 20;
    int flags       = b[5];
    int wind_avg    = ((b[5] & 0x10) << 4) | b[7];      /* 0.1 m/s, 0x1FF invalid */
    int wind_dir    = ((b[5] & 0x20) << 3) | b[8];      /* deg, 0x1FF invalid */
    int wind_max    = ((b[5] & 0x40) << 2) | b[9];
    int rain_start  = (b[12] & 0x10) >> 4;
    int rain_raw    = (b[15] << 8) | b[16];             /* 0.1 mm */
    int supercap    = b[17] & 0x3F;                     /* 0.1 V */
    int firmware    = b[25];
    int battery_ok  = battery_mv > 2400;
    int battery_pct = battery_mv < 1400 ? 0 : (battery_mv - 1400) / 16;
    if (battery_pct > 100) battery_pct = 100;

    int len = 0;
    len = rf_json_append(json, json_len, len,
        "{\"model\":\"Fineoffset-WS85\",\"id\":%ld,\"battery_ok\":%d,\"battery_pct\":%d,\"battery_mV\":%d",
        id, battery_ok, battery_pct, battery_mv);
    if (wind_dir != 0x1FF) len = rf_json_append(json, json_len, len, ",\"wind_dir_deg\":%d", wind_dir);
    if (wind_avg != 0x1FF) len = rf_json_append(json, json_len, len, ",\"wind_avg_m_s\":%.1f", wind_avg * 0.1);
    if (wind_max != 0x1FF) len = rf_json_append(json, json_len, len, ",\"wind_max_m_s\":%.1f", wind_max * 0.1);
    len = rf_json_append(json, json_len, len,
        ",\"flags\":%d,\"rain_mm\":%.1f,\"rain_start\":%d,\"supercap_V\":%.1f,\"firmware\":%d,\"mic\":\"CRC\"}",
        flags, rain_raw * 0.1, rain_start, supercap * 0.1, firmware);
    return len < 0 ? RF_DECODE_TRUNCATED : RF_DECODE_OK;
}

int fineoffset_decode(const uint8_t *b, size_t n, char *json, size_t json_len)
{
    if (n < 1) return RF_DECODE_TOO_SHORT;
    if (b[0] == 0x24) return decode_wh24_family(b, n, json, json_len);
    if (b[0] == 0x85) return decode_ws85(b, n, json, json_len);
    return RF_DECODE_NONE;
}

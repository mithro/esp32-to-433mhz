/* cc1101_hass.c — Home Assistant MQTT Discovery for decoded 433 MHz sensors.
 * SPDX-License-Identifier: GPL-3.0-or-later
 * See cc1101_hass.h. Pure C (snprintf only) so the published bytes are
 * byte-identical on the host tests and in the Tasmota image. */
#include "cc1101_hass.h"
#include <stdio.h>
#include <string.h>

#define DEG "\xC2\xB0"   /* UTF-8 U+00B0 DEGREE SIGN */

/* Field metadata. Table order is stable; host tests index it. Units use HA's
 * expected strings; NULL device_class/unit/state_class are omitted from config. */
static const cc_hass_field_t FIELDS[] = {
    {"temperature_C", "Temperature",     "temperature",   DEG "C", "measurement",      "{{ value|float|round(1) }}"},
    {"humidity",      "Humidity",        "humidity",      "%",     "measurement",      "{{ value|float }}"},
    {"moisture",      "Moisture",        "humidity",      "%",     "measurement",      "{{ value|float }}"},
    {"wind_avg_m_s",  "Wind Speed",      "wind_speed",    "m/s",   "measurement",      "{{ value|float|round(1) }}"},
    {"wind_max_m_s",  "Wind Gust",       "wind_speed",    "m/s",   "measurement",      "{{ value|float|round(1) }}"},
    {"wind_dir_deg",  "Wind Direction",  NULL,            DEG,     "measurement",      "{{ value|float }}"},
    {"rain_mm",       "Rain",            "precipitation", "mm",    "total_increasing", "{{ value|float|round(1) }}"},
    {"battery_mV",    "Battery Voltage", "voltage",       "mV",    "measurement",      "{{ value|float }}"},
    {"battery_pct",   "Battery",         "battery",       "%",     "measurement",      "{{ value|float }}"},
    {"supercap_V",    "Supercapacitor",  "voltage",       "V",     "measurement",      "{{ value|float }}"},
    // battery_ok is the ONLY battery signal WS69/WH65B emit (no mV/pct there), so expose it or a
    // WS69 gets no battery entity at all. It is 0/1 on WS69 and 0.0-1.0 on WH51/WS85; leave it a
    // plain numeric sensor (no device_class — the "battery" sensor class wants a %) that passes the
    // raw value through, rather than a per-model normalisation the shaping layer can't know.
    {"battery_ok",    "Battery OK",      NULL,            NULL,    NULL,               NULL},
};

const cc_hass_field_t *cc_hass_fields(size_t *count)
{
    if (count) *count = sizeof FIELDS / sizeof FIELDS[0];
    return FIELDS;
}

const cc_hass_field_t *cc_hass_field_lookup(const char *field)
{
    for (size_t i = 0; i < sizeof FIELDS / sizeof FIELDS[0]; i++)
        if (strcmp(FIELDS[i].field, field) == 0) return &FIELDS[i];
    return NULL;
}

static int fit(char *out, size_t out_len, int r)
{
    if (r < 0 || (size_t)r >= out_len) { if (out_len) out[0] = '\0'; return -1; }
    return r;
}

int cc_hass_state_topic(char *out, size_t out_len, const char *node,
                        const char *model, const char *id, const char *field)
{
    return fit(out, out_len, snprintf(out, out_len,
        "rtl_433/nodes/%s/devices/%s/%s/%s", node, model, id, field));
}

int cc_hass_config_topic(char *out, size_t out_len,
                         const char *model, const char *id, const char *field)
{
    return fit(out, out_len, snprintf(out, out_len,
        "homeassistant/sensor/%s-%s/%s-%s-%s/config", model, id, model, id, field));
}

int cc_hass_config_payload(char *out, size_t out_len, const char *node,
                           const char *model, const char *id,
                           const cc_hass_field_t *f, const char *state_topic,
                           const char *avail_topic)
{
    int len, r;
    (void)node;
    r = snprintf(out, out_len,
        "{\"name\":\"%s\",\"uniq_id\":\"%s-%s-%s\",\"stat_t\":\"%s\"",
        f->name, model, id, f->field, state_topic);
    if (r < 0 || (size_t)r >= out_len) { if (out_len) out[0] = '\0'; return -1; }
    len = r;
#define APPEND(...) do { \
        r = snprintf(out + len, out_len - (size_t)len, __VA_ARGS__); \
        if (r < 0 || (size_t)r >= out_len - (size_t)len) { if (out_len) out[0] = '\0'; return -1; } \
        len += r; \
    } while (0)
    if (f->device_class)   APPEND(",\"dev_cla\":\"%s\"", f->device_class);
    if (f->unit)           APPEND(",\"unit_of_meas\":\"%s\"", f->unit);
    if (f->state_class)    APPEND(",\"stat_cla\":\"%s\"", f->state_class);
    if (f->value_template) APPEND(",\"val_tpl\":\"%s\"", f->value_template);
    if (avail_topic)
        APPEND(",\"avty_t\":\"%s\",\"pl_avail\":\"Online\",\"pl_not_avail\":\"Offline\"", avail_topic);
    APPEND(",\"dev\":{\"ids\":[\"%s-%s\"],\"name\":\"%s %s\",\"mdl\":\"%s\",\"mf\":\"Fine Offset\"}}",
           model, id, model, id, model);
#undef APPEND
    return len;
}

int cc_hass_extract(const char *json, const char *key, char *out, size_t out_len)
{
    if (out_len) out[0] = '\0';
    /* find "\"<key>\":" (a quoted key immediately followed by a colon) */
    char pat[48];
    int pn = snprintf(pat, sizeof pat, "\"%s\":", key);
    if (pn < 0 || (size_t)pn >= sizeof pat) return -1;
    const char *p = strstr(json, pat);
    if (!p) return -1;
    p += pn;
    while (*p == ' ') p++;
    size_t n = 0;
    if (*p == '"') {                         /* string value: copy until the closing quote */
        p++;
        while (*p && *p != '"') {
            if (n + 1 >= out_len) { if (out_len) out[0] = '\0'; return -1; }
            out[n++] = *p++;
        }
    } else {                                 /* number/bool: copy until , } or whitespace */
        while (*p && *p != ',' && *p != '}' && *p != ' ') {
            if (n + 1 >= out_len) { if (out_len) out[0] = '\0'; return -1; }
            out[n++] = *p++;
        }
    }
    out[n] = '\0';
    return (int)n;
}

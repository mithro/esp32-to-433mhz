/* cc1101_hass.h — Home Assistant MQTT Discovery for decoded 433 MHz sensors.
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Pure C (no Arduino/Tasmota deps) so the exact discovery topics and JSON the
 * firmware publishes are covered by the host tests in firmware/tests.
 *
 * The node publishes, per decoded sensor field:
 *   - a retained STATE message to a per-field device topic
 *       rtl_433/nodes/<node>/devices/<model>/<id>/<field>   payload = raw value
 *   - a retained CONFIG message to the HA discovery topic
 *       homeassistant/sensor/<model>-<id>/<model>-<id>-<field>/config
 *     whose state_topic points back at the device topic, so Home Assistant
 *     creates the entity natively — no rtl_433 add-on/aggregator required.
 * Per-field topics (not the shared events JSON) mean each entity has its own
 * state, so a WH51 message never clobbers a WS69 entity. */
#ifndef CC1101_HASS_H
#define CC1101_HASS_H
#include <stddef.h>
#ifdef __cplusplus
extern "C" {
#endif

/* HA metadata for one rtl_433 JSON field. NULL members are omitted from the
 * config so HA falls back to its own defaults. */
typedef struct {
    const char *field;          /* rtl_433 JSON key, e.g. "temperature_C" */
    const char *name;           /* HA entity name, e.g. "Temperature" */
    const char *device_class;   /* HA device_class or NULL */
    const char *unit;           /* unit_of_measurement or NULL */
    const char *state_class;    /* "measurement" / "total_increasing" or NULL */
    const char *value_template; /* formats the raw `value`, or NULL for passthrough */
} cc_hass_field_t;

/* The field table (weather + moisture fields the shipped decoders emit). */
const cc_hass_field_t *cc_hass_fields(size_t *count);

/* Look up one field's metadata by rtl_433 key, or NULL if not a known sensor
 * field (model/id/mic/etc. are intentionally absent). */
const cc_hass_field_t *cc_hass_field_lookup(const char *field);

/* Per-field device (state) topic: "rtl_433/nodes/<node>/devices/<model>/<id>/<field>".
 * Returns strlen(out), or -1 on truncation. */
int cc_hass_state_topic(char *out, size_t out_len, const char *node,
                        const char *model, const char *id, const char *field);

/* HA discovery config topic:
 * "homeassistant/sensor/<model>-<id>/<model>-<id>-<field>/config".
 * Returns strlen(out), or -1 on truncation. */
int cc_hass_config_topic(char *out, size_t out_len,
                         const char *model, const char *id, const char *field);

/* HA discovery config payload for one field. `state_topic` is the device topic
 * built by cc_hass_state_topic(); `avail_topic` is the node LWT topic (or NULL
 * to omit availability). Returns strlen(out), or -1 on truncation. */
int cc_hass_config_payload(char *out, size_t out_len, const char *node,
                           const char *model, const char *id,
                           const cc_hass_field_t *f, const char *state_topic,
                           const char *avail_topic);

/* Extract one field's value from a flat rtl_433 decoder JSON object into `out`
 * (surrounding quotes stripped for string values; numbers/bools copied raw).
 * Returns strlen(out) if the key is present, or -1 if absent/truncated. Only
 * handles the flat, single-object JSON the decoders emit (no nesting/arrays). */
int cc_hass_extract(const char *json, const char *key, char *out, size_t out_len);

#ifdef __cplusplus
}
#endif
#endif

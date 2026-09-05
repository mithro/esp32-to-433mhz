/* cc1101_mqtt.c — MQTT topic + event-JSON shaping for the CC1101/SX1278 node.
 * SPDX-License-Identifier: GPL-3.0-or-later
 * See cc1101_mqtt.h. Uses only <stdio.h> snprintf so it is byte-identical on the
 * host test harness and in the Tasmota image. */
#include "cc1101_mqtt.h"
#include <stdio.h>
#include <string.h>

/* Wrap a raw snprintf: return the written length, or -1 if it did not fit. */
static int fit(char *out, size_t out_len, int r)
{
    if (r < 0 || (size_t)r >= out_len) { if (out_len) out[0] = '\0'; return -1; }
    return r;
}

int cc_events_topic(char *out, size_t out_len, int hass, const char *host)
{
    if (hass == CC_HASS_DIRECT)
        return fit(out, out_len, snprintf(out, out_len, "rtl_433/%s/events", host));
    return fit(out, out_len, snprintf(out, out_len, "rtl_433/nodes/%s/events", host));
}

int cc_node_topic(char *out, size_t out_len, const char *host, const char *leaf)
{
    return fit(out, out_len, snprintf(out, out_len, "rtl_433/nodes/%s/%s", host, leaf));
}

int cc_wrap_event(char *out, size_t out_len, const char *time,
                  const char *receiver, int rssi, const char *decoder_json)
{
    const char *body = decoder_json;
    if (*body == '{') body++;                 /* splice our prefix in ahead of the decoder fields */
    return fit(out, out_len, snprintf(out, out_len,
        "{\"time\":\"%s\",\"receiver\":\"%s\",\"rssi\":%d,%s", time, receiver, rssi, body));
}

/* cc1101_mqtt.h — MQTT topic + event-JSON shaping for the CC1101/SX1278 node.
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Pure C (no Arduino/Tasmota deps) so the host tests in firmware/tests exercise
 * the exact topic strings and event JSON the firmware publishes to MQTT.
 * The Tasmota driver (xdrv_95_cc1101.ino) calls these and hands the result to
 * MqttPublishPayload(); nothing here talks to the network. */
#ifndef CC1101_MQTT_H
#define CC1101_MQTT_H
#include <stddef.h>
#ifdef __cplusplus
extern "C" {
#endif

/* Home Assistant events-topic layout selector (persisted CcConfig.hass). */
enum {
    CC_HASS_AGG    = 0,   /* rtl_433/nodes/<host>/events  — aggregator-fronted (default) */
    CC_HASS_DIRECT = 1,   /* rtl_433/<host>/events        — matches the HA add-on's rtl_433/+/events */
};

/* Build the decoded-events topic.
 *   hass == CC_HASS_AGG (0):    "rtl_433/nodes/<host>/events"
 *   hass == CC_HASS_DIRECT (1): "rtl_433/<host>/events"
 * The single-level '+' in the rtl_433 HA autodiscovery subscription
 * (rtl_433/+/events) matches the DIRECT form but NOT the 4-level AGG form,
 * which is why AGG deployments rely on the aggregator republishing to
 * rtl_433/<site>/events. Returns strlen(out), or -1 on truncation. */
int cc_events_topic(char *out, size_t out_len, int hass, const char *host);

/* Build "rtl_433/nodes/<host>/<leaf>" (used for the per-node tx-announce topic,
 * which is not consumed by HA autodiscovery). Returns strlen(out) or -1. */
int cc_node_topic(char *out, size_t out_len, const char *host, const char *leaf);

/* Prepend time/receiver/rssi to a decoder JSON object, producing rtl_433-shaped
 * JSON: {"time":"<time>","receiver":"<receiver>","rssi":<rssi>,<decoder fields>}.
 * decoder_json must be a complete "{...}" object; its leading '{' is dropped and
 * the rest (including the closing '}') is appended. Returns strlen(out) or -1. */
int cc_wrap_event(char *out, size_t out_len, const char *time,
                  const char *receiver, int rssi, const char *decoder_json);

#ifdef __cplusplus
}
#endif
#endif

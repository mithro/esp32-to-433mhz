/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "sx1278_weather.h"

/* Forward-declared instead of #include'd so this TU compiles unchanged in both the host build
 * (decoders reached via -I firmware/decoders) and the firmware overlay (decoders live under
 * tasmota/cc1101_node/decoders/). fineoffset_decode() returns the RF_DECODE_* codes from
 * decoders/decode_common.h: the only positive code is RF_DECODE_OK (1); every failure is <= 0. */
extern "C" int fineoffset_decode(const uint8_t* b, size_t n, char* json, size_t json_len);

int sx_weather_drain(SX1278Radio& radio, uint8_t* raw, size_t raw_cap,
                     size_t* out_n, int* out_rssi, char* json, size_t json_len) {
  /* PayloadReady is set only once RegPayloadLength bytes have been latched after a sync match;
     until then there is nothing to drain (nothing to reset either). */
  if (!radio.payload_ready()) return SX_WX_IDLE;

  int rssi = radio.rssi_dbm();
  size_t take = SX_FSK_DRAIN_LEN;
  if (take > raw_cap) take = raw_cap;
  radio.read_fifo(raw, take);
  radio.restart_rx();                    // standby -> RX: flush the FIFO and re-arm sync detection

  *out_n = take; *out_rssi = rssi;
  int rc = fineoffset_decode(raw, take, json, json_len);
  return (rc > 0) ? SX_WX_DECODED : SX_WX_RAW;
}

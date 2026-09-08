/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "cc1101_weather.h"

/* Forward-declared instead of #include'd so this TU compiles unchanged in both the
 * host build (decoders reached via -I firmware/decoders) and the firmware overlay
 * (decoders live under tasmota/cc1101_node/decoders/). fineoffset_decode() returns
 * the RF_DECODE_* codes from decoders/decode_common.h: the only positive code is
 * RF_DECODE_OK (1); every failure is <= 0. */
extern "C" int fineoffset_decode(const uint8_t* b, size_t n, char* json, size_t json_len);

int cc_weather_drain(CC1101Radio& radio, uint8_t* raw, size_t raw_cap,
                     size_t* out_n, int* out_rssi, char* json, size_t json_len) {
  bool overflow = false;
  uint8_t n = radio.rxbytes(&overflow);
  bool ovf = overflow || (radio.marcstate() == MARC_RXFIFO_OVERFLOW);

  /* Frame not yet fully in the FIFO: keep waiting (nothing to reset). */
  if (n < CC_FSK_DRAIN_LEN && !ovf) return CC_WX_IDLE;

  size_t take = n < CC_FSK_DRAIN_LEN ? n : CC_FSK_DRAIN_LEN;
  if (take > raw_cap) take = raw_cap;
  if (take < CC_FSK_MIN_FRAME) {                 /* overflow before a whole frame arrived */
    radio.flush_rx(); radio.enter_rx();
    return CC_WX_OVERFLOW;
  }

  /* On an RX-FIFO overflow the CC1101 keeps the first 64 received bytes (new bytes
   * are dropped), so the frame at the head is still intact and readable. */
  radio.read_fifo(raw, take);
  int rssi = radio.rssi_dbm();                    /* frame already in FIFO; RSSI reg now reads the ambient floor */
  radio.flush_rx(); radio.enter_rx();             /* SFRX + re-enter RX: re-arm sync detection for the next frame */

  *out_n = take; *out_rssi = rssi;
  int rc = fineoffset_decode(raw, take, json, json_len);
  return (rc > 0) ? CC_WX_DECODED : CC_WX_RAW;
}

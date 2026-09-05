/* Fine Offset FSK weather RX framing: CC1101 infinite-length FIFO drain + family
 * dispatch. Shared by the Tasmota driver (xdrv_95_cc1101.ino) and the host harness
 * (tests/radio_host.cpp) so both exercise the identical framing logic.
 * SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef CC1101_WEATHER_H
#define CC1101_WEATHER_H
#include <stddef.h>
#include <stdint.h>
#include "cc1101_radio.h"

/* The Fine Offset FSK preset runs the CC1101 in INFINITE packet-length mode
 * (PKTCTRL0 length_config = 10b / 0x02), NOT fixed length. In fixed-length mode a
 * single PKTLEN can only complete one frame size, so a 14-byte WH51 never finishes
 * and is never decoded. In infinite mode the RX FIFO simply keeps filling after the
 * 0x2DD4 sync match, so we drain a fixed number of bytes (>= the longest frame) and
 * let the decoder pick the family and ignore the trailing bytes. One config then
 * receives every family: WH51 (14 B), WS69 (25 B), WS85 (28 B). */
#define CC_FSK_DRAIN_LEN 30   /* >= WS85's 28 B; also < the 64-byte RX FIFO */
#define CC_FSK_MIN_FRAME 14   /* shortest frame we decode (WH51) */

/* cc_weather_drain() return codes. */
enum {
  CC_WX_IDLE     = 0,   /* FIFO still filling; nothing drained */
  CC_WX_DECODED  = 1,   /* frame drained and decoded; json/out_n/out_rssi valid */
  CC_WX_RAW      = 2,   /* frame drained but did not decode; raw/out_n/out_rssi valid */
  CC_WX_OVERFLOW = 3,   /* RX FIFO overflow with no usable frame; RX was reset */
};

/* One weather-RX poll against the CC1101 in infinite-length mode.
 *
 * In infinite-length mode the RX FIFO only starts filling once the demodulator has
 * matched the 0x2DD4 sync word (MDMCFG2 = 16/16 sync), so a whole frame always sits
 * at the FIFO head with demodulated noise behind it. When at least CC_FSK_DRAIN_LEN
 * bytes are present (or the FIFO has overflowed with a frame already latched at the
 * head), drain up to CC_FSK_DRAIN_LEN bytes into raw[], dispatch by the family byte
 * via fineoffset_decode(), then flush the FIFO and re-enter RX to re-arm sync
 * detection for the next frame.
 *
 * raw must have capacity for at least CC_FSK_DRAIN_LEN bytes; json is the decoder
 * output buffer. Returns a CC_WX_* code. */
int cc_weather_drain(CC1101Radio& radio, uint8_t* raw, size_t raw_cap,
                     size_t* out_n, int* out_rssi, char* json, size_t json_len);
#endif

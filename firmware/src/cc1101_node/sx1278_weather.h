/* Fine Offset FSK weather RX framing for the SX1278 (RA-02): fixed-length FSK packet drain +
 * family dispatch. The SX127x counterpart of cc1101_weather.*. Shared by the Tasmota driver
 * (xdrv_95_cc1101.ino) and the host harness (tests/sx1278_host.cpp) so both exercise the
 * identical framing logic.
 * SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef SX1278_WEATHER_H
#define SX1278_WEATHER_H
#include <stddef.h>
#include <stdint.h>
#include "sx1278_radio.h"

/* The SX1278 Fine Offset preset runs FIXED-LENGTH FSK packet mode with RegPayloadLength =
 * SX_FSK_RX_LEN. After the 0x2DD4 sync match the radio collects exactly that many bytes and
 * raises PayloadReady, so a whole frame sits at the FIFO head with post-frame demodulator
 * noise behind it (for frames shorter than the drain length). We drain the fixed count and
 * fineoffset_decode() dispatches by family byte, ignoring the trailing bytes -- one config
 * receives every family: WH51 (14 B), WS69 (25 B), WS85 (28 B). Mirrors CC_FSK_DRAIN_LEN. */
#define SX_FSK_DRAIN_LEN SX_FSK_RX_LEN   /* == RegPayloadLength; both derive from SX_FSK_RX_LEN */
#define SX_FSK_MIN_FRAME 14              /* shortest frame we decode (WH51) */

/* sx_weather_drain() return codes (mirror the CC_WX_* codes). */
enum {
  SX_WX_IDLE    = 0,   /* no PayloadReady yet; nothing drained */
  SX_WX_DECODED = 1,   /* frame drained and decoded; json/out_n/out_rssi valid */
  SX_WX_RAW     = 2,   /* frame drained but did not decode; raw/out_n/out_rssi valid */
};

/* One weather-RX poll against the SX1278 in fixed-length FSK packet mode.
 *
 * If RegIrqFlags2 PayloadReady is not set the FIFO has not yet latched a full packet: return
 * SX_WX_IDLE (nothing to do). Otherwise read SX_FSK_DRAIN_LEN bytes out of RegFifo into raw[],
 * dispatch by family byte via fineoffset_decode(), then restart RX (standby -> RX) to flush the
 * FIFO and re-arm sync detection for the next frame.
 *
 * raw must have capacity for at least SX_FSK_DRAIN_LEN bytes; json is the decoder output buffer.
 * Returns an SX_WX_* code. */
int sx_weather_drain(SX1278Radio& radio, uint8_t* raw, size_t raw_cap,
                     size_t* out_n, int* out_rssi, char* json, size_t json_len);
#endif

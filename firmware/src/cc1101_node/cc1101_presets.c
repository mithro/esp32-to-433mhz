/* SPDX-License-Identifier: GPL-3.0-or-later */
#include <math.h>
#include <string.h>
#include "cc1101_presets.h"

/* Fineoffset FSK packet RX: modem params from cc1101.py configure_fineoffset_fsk_rx (order = write
 * order there), but PKTCTRL0 (0x08) is 0x02 = INFINITE length, not the reference's 0x00 = fixed.
 * Fixed length completes only one frame size (a 14-byte WH51 never finishes under a 25-byte PKTLEN);
 * infinite length lets the FIFO keep filling past the sync so one config receives every Fine Offset
 * family (WH51 14 B / WS69 25 B / WS85 28 B) — the driver drains a fixed count and dispatches by
 * family byte. PKTLEN (0x06) is ignored in infinite mode; left at 0x19 to match the reference.
 *
 * MDMCFG4 (0x10) = 0x59 sets a 325 kHz RX bandwidth, NOT the reference default 101 kHz (0xC9).
 * Cheap 433 MHz modules carry crystal offsets up to ~+/-90 ppm (~+/-39 kHz each for TX and RX);
 * the CC1101 frequency-offset compensation only pulls in +/-BW/4, so a 101 kHz filter (+/-25 kHz)
 * drops any frame whose combined offset exceeds that. Measured on the blue node: +40 kHz (~92 ppm)
 * -> zero decodes at 101 kHz, full decode at 325 kHz (FOC +/-81 kHz). 325 kHz covers worst-case
 * crystal spread across boards with margin, at a ~5 dB noise-floor cost negligible for the local
 * -70 dBm sensors. Only the low nibble (DRATE_E=9) is shared with 0xC9; the high nibble is BW. */
static const cc_reg_t FINEOFFSET_FSK[] = {
    {0x00, 0x29}, {0x02, 0x06}, {0x03, 0x47}, {0x04, 0x2D}, {0x05, 0xD4}, {0x06, 0x19}, {0x07, 0x04}, {0x08, 0x02},
    {0x0A, 0x00}, {0x0B, 0x06}, {0x0C, 0x00}, {0x0D, 0x10}, {0x0E, 0xB0}, {0x0F, 0x71}, {0x10, 0x59}, {0x11, 0x5C},
    {0x12, 0x02}, {0x13, 0x72}, {0x14, 0xF8}, {0x15, 0x50}, {0x17, 0x3C}, {0x18, 0x18}, {0x19, 0x16}, {0x1A, 0x6C},
    {0x1B, 0x43}, {0x1C, 0x40}, {0x1D, 0x91}, {0x21, 0x56}, {0x22, 0x10}, {0x23, 0xE9}, {0x24, 0x2A}, {0x25, 0x00},
    {0x26, 0x1F}, {0x2C, 0x81}, {0x2D, 0x35}, {0x2E, 0x09},
};
/* OOK async-serial RX: cc1101.py configure_ook_async_rx() defaults (10 kbps timing, 232 kHz BW). */
static const cc_reg_t OOK_RX[] = {
    {0x0D, 0x10}, {0x0E, 0xB0}, {0x0F, 0x71}, {0x00, 0x0D}, {0x02, 0x2E}, {0x03, 0x47}, {0x07, 0x00}, {0x08, 0x32},
    {0x0B, 0x06}, {0x0C, 0x00}, {0x10, 0x78}, {0x11, 0x93}, {0x12, 0x30}, {0x13, 0x00}, {0x14, 0xF8}, {0x17, 0x3C},
    {0x18, 0x18}, {0x19, 0x16}, {0x1A, 0x6C}, {0x1B, 0x03}, {0x1C, 0x00}, {0x1D, 0x91}, {0x21, 0x56}, {0x22, 0x11},
    {0x23, 0xE9}, {0x24, 0x2A}, {0x25, 0x00}, {0x26, 0x1F}, {0x2C, 0x81}, {0x2D, 0x35}, {0x2E, 0x09},
};
/* OOK TX, FIFO bits are the waveform: cc1101.py configure_ook_tx(chip_rate=...). */
#define OOK_TX_COMMON(mdm4, mdm3) \
    {0x0D, 0x10}, {0x0E, 0xB0}, {0x0F, 0x71}, {0x10, mdm4}, {0x11, mdm3}, {0x12, 0x30}, {0x13, 0x00}, {0x14, 0x00}, \
    {0x07, 0x00}, {0x08, 0x00}, {0x0B, 0x06}, {0x22, 0x11}, {0x18, 0x18}, {0x23, 0xE9}, {0x24, 0x2A}, {0x25, 0x00}, \
    {0x26, 0x1F}, {0x2C, 0x81}, {0x2D, 0x35}, {0x2E, 0x09}
static const cc_reg_t OOK_TX_100K[] = { OOK_TX_COMMON(0x0B, 0xF8) };
static const cc_reg_t OOK_TX_4K[]   = { OOK_TX_COMMON(0x07, 0x43) };
static const uint8_t  OOK_PATABLE[] = { 0x00, 0xC0 };
static const char* const NAMES[CC_PRESET_COUNT] = { "fineoffset-fsk", "ook-433", "ook-tx-100k", "ook-tx-4k" };

const cc_reg_t* cc_preset_regs(int id, size_t* n) {
    switch (id) {
    case CC_PRESET_FINEOFFSET_FSK: *n = sizeof FINEOFFSET_FSK / sizeof FINEOFFSET_FSK[0]; return FINEOFFSET_FSK;
    case CC_PRESET_OOK_RX:         *n = sizeof OOK_RX / sizeof OOK_RX[0];                 return OOK_RX;
    case CC_PRESET_OOK_TX_100K:    *n = sizeof OOK_TX_100K / sizeof OOK_TX_100K[0];       return OOK_TX_100K;
    case CC_PRESET_OOK_TX_4K:      *n = sizeof OOK_TX_4K / sizeof OOK_TX_4K[0];           return OOK_TX_4K;
    default: *n = 0; return NULL;
    }
}
const uint8_t* cc_preset_patable(int id, size_t* n) {
    if (id == CC_PRESET_OOK_TX_100K || id == CC_PRESET_OOK_TX_4K) { *n = 2; return OOK_PATABLE; }
    *n = 0; return NULL;
}
const char* cc_preset_name(int id) { return (id >= 0 && id < CC_PRESET_COUNT) ? NAMES[id] : "?"; }
int cc_preset_by_name(const char* name) {
    for (int i = 0; i < CC_PRESET_COUNT; i++) if (name && strcmp(name, NAMES[i]) == 0) return i;
    return -1;
}
void cc_freq_regs(double freq_hz, uint8_t out[3]) {
    uint32_t fw = (uint32_t)floor(freq_hz * 65536.0 / CC_XOSC_HZ + 0.5);
    out[0] = (fw >> 16) & 0xFF; out[1] = (fw >> 8) & 0xFF; out[2] = fw & 0xFF;
}

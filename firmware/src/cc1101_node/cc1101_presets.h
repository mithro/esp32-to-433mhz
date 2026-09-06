/* CC1101 register presets for the 433 MHz node. Values are generated from the bench-proven maths in
 * tools/cc1101.py and unit-tested against it (tests/test_presets.py).
 * SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef CC1101_PRESETS_H
#define CC1101_PRESETS_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
typedef struct { uint8_t addr, val; } cc_reg_t;
enum cc_preset_id { CC_PRESET_FINEOFFSET_FSK = 0, CC_PRESET_OOK_RX = 1, CC_PRESET_OOK_TX_100K = 2, CC_PRESET_OOK_TX_4K = 3, CC_PRESET_COUNT = 4 };
const cc_reg_t* cc_preset_regs(int id, size_t* n);          /* NULL if id invalid */
const uint8_t* cc_preset_patable(int id, size_t* n);        /* NULL if the preset does not set PATABLE */
const char* cc_preset_name(int id);
int cc_preset_by_name(const char* name);                    /* -1 if unknown */
void cc_freq_regs(double freq_hz, uint8_t out[3]);         /* FREQ2,FREQ1,FREQ0 for a 26 MHz XOSC */
#define CC_XOSC_HZ 26000000.0
#ifdef __cplusplus
}
#endif
#endif

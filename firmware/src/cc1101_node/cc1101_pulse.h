/* Pulse/chip helpers shared by the firmware and host tests. SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef CC1101_PULSE_H
#define CC1101_PULSE_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
size_t pulses_to_chips(const uint32_t* us, size_t n, uint32_t chip_us, uint8_t* out, size_t out_bytes);
size_t chips_to_pulses(const uint8_t* chips01, size_t n, uint32_t chip_us, uint32_t* us, size_t max);
size_t rcswitch1_pulses(uint32_t data, unsigned bits, uint32_t pulse_us, uint32_t* us, size_t max);
size_t pwm_code_pulses(uint64_t code, unsigned bits, uint32_t short_us, uint32_t long_us, uint32_t gap_us, uint32_t* us, size_t max);
size_t edges_to_pulses(const uint32_t* t_us, const uint8_t* level_after, size_t n, uint32_t* us, size_t max);
#ifdef __cplusplus
}
#endif
#endif

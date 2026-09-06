/* OOK-PWM 25-bit remote decoder (grey power remotes, doorbell, bed remote).
 * SPDX-License-Identifier: Apache-2.0 */
#ifndef DECODE_OOKPWM_H
#define DECODE_OOKPWM_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* Bit sense: 1 => a LONG mark is a '1' (convention of cc1101.py pwm_code_to_pulses
 * and sites/welland/rf-codes.md). rtl_433's OOK_PWM slicer uses the opposite
 * (short = 1); to be verified against a real remote (Plan A Task 6 — PENDING;
 * see protocols/ook-pwm-remotes.md). */
#ifndef OOKPWM_LONG_IS_ONE
#define OOKPWM_LONG_IS_ONE 1
#endif
#define OOKPWM_MIN_BITS 16
#define OOKPWM_MAX_BITS 64
/* us: alternating mark,space,mark,... in microseconds starting with a mark.
 * Scans from *pos; on RF_DECODE_OK writes json and advances *pos past the packet.
 * gap_us in the json is the measured trailing space when present, else the
 * family's nominal reset_us (the last packet of a capture-tool train has no
 * trailing space). */
int ookpwm_decode(const uint32_t *us, size_t n, size_t *pos, char *json, size_t json_len);
#ifdef __cplusplus
}
#endif
#endif

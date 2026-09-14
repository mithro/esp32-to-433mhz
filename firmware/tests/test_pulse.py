"""cc1101_pulse helpers: chips packing, RCSwitch protocol-1 / PWM code generation, edges→pulses, round trips."""
import ctypes
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import firmwarelib  # noqa: E402
from decoderlib import decode_pulses, load  # noqa: E402

U32P = ctypes.POINTER(ctypes.c_uint32)


def lib():
    L = firmwarelib.build_c()
    L.pulses_to_chips.restype = ctypes.c_size_t
    L.pulses_to_chips.argtypes = [U32P, ctypes.c_size_t, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t]
    L.rcswitch1_pulses.restype = ctypes.c_size_t
    L.rcswitch1_pulses.argtypes = [ctypes.c_uint32, ctypes.c_uint, ctypes.c_uint32, U32P, ctypes.c_size_t]
    L.pwm_code_pulses.restype = ctypes.c_size_t
    L.pwm_code_pulses.argtypes = [ctypes.c_uint64, ctypes.c_uint, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, U32P, ctypes.c_size_t]
    L.edges_to_pulses.restype = ctypes.c_size_t
    L.edges_to_pulses.argtypes = [U32P, ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t, U32P, ctypes.c_size_t]
    L.chips_to_pulses.restype = ctypes.c_size_t
    L.chips_to_pulses.argtypes = [ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t, ctypes.c_uint32, U32P, ctypes.c_size_t]
    return L


def test_pulses_to_chips_packs_msb_first():
    L = lib(); us = (ctypes.c_uint32 * 4)(30, 20, 10, 40); out = (ctypes.c_uint8 * 4)()
    n = L.pulses_to_chips(us, 4, 10, out, 4)           # 3 ones, 2 zeros, 1 one, 4 zeros = 10 chips
    assert n == 10 and list(out[:2]) == [0b11100100, 0b00000000]


def test_rcswitch1_pulses_then_decode_as_ookpwm():
    L = lib(); us = (ctypes.c_uint32 * 64)()
    n = L.rcswitch1_pulses(0xC3FF3F, 24, 200, us, 64)
    assert n == 50                                     # 24 bits × (mark,space) + sync (mark, space)
    assert list(us[:4]) == [600, 200, 600, 200]        # 0xC3 = 1100 0011: '1' = 3p high, 1p low
    assert list(us[48:50]) == [200, 6200]              # sync: 1p high, 31p low
    dec = decode_pulses(load(), list(us[:n]))
    # The generic OOK-PWM decoder has no notion of an RCSwitch sync symbol: the sync's leading
    # 1p-high pulse (200 us) is indistinguishable from a data "0" bit under the "standard" family's
    # short/long thresholds, so it is consumed as a 25th bit before the trailing 31p-low space is
    # recognized as the reset gap. That yields 25 bits (24 data bits + a trailing 0) / code "c3ff3f0",
    # not the 24-bit "c3ff3f" one might expect from the RCSwitch payload alone.
    assert dec and dec[0]["code"] == "c3ff3f0" and dec[0]["bits"] == 25


def test_pwm_code_pulses_matches_pulsegen_convention():
    from pulsegen import pwm_standard
    L = lib(); us = (ctypes.c_uint32 * 64)()
    n = L.pwm_code_pulses(0xC3FF3F8 >> 3, 25, 200, 730, 7300, us, 64)
    assert list(us[:n]) == pwm_standard("c3ff3f8")     # identical waveform to the Python generator


def test_edges_to_pulses_and_chip_round_trip():
    L = lib()
    t = (ctypes.c_uint32 * 6)(1000, 1730, 1930, 2130, 2860, 10160); lvl = (ctypes.c_uint8 * 6)(1, 0, 1, 0, 1, 0)
    us = (ctypes.c_uint32 * 8)()
    n = L.edges_to_pulses(t, lvl, 6, us, 8)
    assert list(us[:n]) == [730, 200, 200, 730, 7300]
    chips = (ctypes.c_uint8 * 64)(); nch = 0
    # chips_to_pulses inverse: build a 0/1 chip list by hand and back
    seq = [1, 1, 1, 0, 0, 1, 0, 0, 0, 0]
    arr = (ctypes.c_uint8 * 10)(*seq); out = (ctypes.c_uint32 * 8)()
    m = L.chips_to_pulses(arr, 10, 250, out, 8)
    assert list(out[:m]) == [750, 500, 250, 1000]

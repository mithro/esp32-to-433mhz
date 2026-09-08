"""Security+ 2.0 Manchester framing round trip using argilo's published test vector."""
import ctypes
import json
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import firmwarelib  # noqa: E402

ROLLING, FIXED = 240124710, 0x1074C58200
CODE = ("0001000100001011111000111111011011101110" "0010010110001110011110010011011011011011")   # encode_v2 bits, 80


def lib():
    L = firmwarelib.build_c()
    L.encode_v2.restype = ctypes.c_int8
    L.encode_v2.argtypes = [ctypes.c_uint32, ctypes.c_uint64, ctypes.c_uint32, ctypes.c_uint8, ctypes.POINTER(ctypes.c_uint8), ctypes.POINTER(ctypes.c_uint8)]
    L.secplus2_encode_chips.restype = ctypes.c_size_t
    L.secplus2_encode_chips.argtypes = [ctypes.c_uint32, ctypes.c_uint64, ctypes.c_int, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t]
    L.chips_to_pulses.restype = ctypes.c_size_t
    L.chips_to_pulses.argtypes = [ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32), ctypes.c_size_t]
    L.secplus2_demod.restype = ctypes.c_int
    L.secplus2_demod.argtypes = [ctypes.POINTER(ctypes.c_uint32), ctypes.c_size_t, ctypes.POINTER(ctypes.c_uint8), ctypes.POINTER(ctypes.c_uint8), ctypes.POINTER(ctypes.c_size_t)]
    L.secplus2_collect.restype = ctypes.c_int
    L.secplus2_collect.argtypes = [ctypes.c_void_p, ctypes.c_uint8, ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_size_t]
    return L


def test_vendored_encode_v2_matches_argilo_vector():
    L = lib(); p1 = (ctypes.c_uint8 * 8)(); p2 = (ctypes.c_uint8 * 8)()
    assert L.encode_v2(ROLLING, FIXED, 0, 0, p1, p2) == 0
    bits = "".join(format(b, "08b") for b in p1[:5]) + "".join(format(b, "08b") for b in p2[:5])
    assert bits == CODE


def test_encode_chips_layout():
    L = lib(); chips = (ctypes.c_uint8 * 512)()
    n = L.secplus2_encode_chips(ROLLING, FIXED, 0, 0, chips, 512)
    # packet = 20 preamble + 2 frame id + 40 payload = 62 bits -> 124 chips; ×2 packets + 2×33 blanks
    assert n == 2 * 124 + 2 * 33
    pre = list(chips[:40])
    assert pre == [1, 0] * 16 + [0, 1] * 4          # 16 zeros then 4 ones, Manchester (0->10, 1->01)
    assert list(chips[40:44]) == [1, 0, 1, 0]       # frame id 00 for packet 1
    assert list(chips[124 + 33 + 40: 124 + 33 + 44]) == [1, 0, 0, 1]   # frame id 01 for packet 2


def test_manchester_round_trip_decodes_rolling_and_fixed():
    L = lib(); chips = (ctypes.c_uint8 * 512)()
    n = L.secplus2_encode_chips(ROLLING, FIXED, 0, 0, chips, 512)
    # split into the two packets by the blank (>= 33 zero chips) as the capture tool's burst gap would
    us = (ctypes.c_uint32 * 512)()
    m = L.chips_to_pulses(chips, 124, 250, us, 512)                  # packet 1 pulses
    fid = ctypes.c_uint8(); payload = (ctypes.c_uint8 * 8)(); bits = ctypes.c_size_t()
    assert L.secplus2_demod(us, m, ctypes.byref(fid), payload, ctypes.byref(bits)) == 1
    assert fid.value == 0 and bits.value == 40
    st = ctypes.create_string_buffer(64); out = ctypes.create_string_buffer(256)
    assert L.secplus2_collect(st, 0, payload, 40, 1000, out, 256) == 0          # waiting for half 2
    off = 124 + 33
    m2 = L.chips_to_pulses((ctypes.c_uint8 * 124).from_buffer_copy(bytes(chips[off:off + 124])), 124, 250, us, 512)
    assert L.secplus2_demod(us, m2, ctypes.byref(fid), payload, ctypes.byref(bits)) == 1 and fid.value == 1
    assert L.secplus2_collect(st, 1, payload, 40, 1008, out, 256) == 1
    j = json.loads(out.value.decode())
    assert j == {"model": "Secplus-v2", "id": FIXED & 0xF0FFFFFFFF, "button": (FIXED >> 32) & 0xF, "rolling": ROLLING, "fixed": FIXED}


def test_stale_half_is_dropped_and_noise_rejected():
    L = lib(); st = ctypes.create_string_buffer(64); out = ctypes.create_string_buffer(256)
    payload = (ctypes.c_uint8 * 8)()
    assert L.secplus2_collect(st, 0, payload, 40, 0, out, 256) == 0
    assert L.secplus2_collect(st, 1, payload, 40, 900, out, 256) == 0          # > 800 ms later: half 1 expired, nothing decodes
    us = (ctypes.c_uint32 * 6)(300, 300, 1200, 100, 50, 9000); fid = ctypes.c_uint8(); bits = ctypes.c_size_t()
    assert L.secplus2_demod(us, 6, ctypes.byref(fid), payload, ctypes.byref(bits)) == 0

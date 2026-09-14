"""RULING R7 round trip: rcswitch1_pulses() -> ookpwm_decode() for a real RCSwitch protocol-1
24-bit remote code, and confirmation that the firmware's Data-field truncation (see
CcPublishRfReceived() in xdrv_95_cc1101.ino) recovers the original 24-bit code from the
decoder's 25-bit report.

Context (Task 3 review, carried as ruling R7 into Task 5): decode_ookpwm.c is a *generic*
OOK-PWM slicer shared with non-RCSwitch families (grey power remotes, doorbells, bed remotes).
It has no notion of an RCSwitch sync symbol, so when fed a real RCSwitch protocol-1 waveform
(rcswitch1_pulses()'s 24 data bits + trailing 1p-mark/31p-space sync) it greedily consumes the
sync's short leading mark as a spurious 25th data bit before the sync's long trailing space is
recognized as the family's reset gap. The result is a 25-bit code, not the 24-bit one a human
would expect from the RCSwitch payload alone.

This file's job is narrower than test_pulse.py's existing
test_rcswitch1_pulses_then_decode_as_ookpwm (which proves the 24->25 bit behaviour at
pulse_us=200, the width used by that RCSwitch code's "standard"-family match): here we also
confirm the *firmware's* truncation formula (v >>= width_bits - 24; v & 0xFFFFFF) recovers the
original 24-bit code from the decoder's 25-bit / padded-hex-string output, which is the
dedup-critical path (rtl_433/nodes/<host>/RfReceived's Data field and the aggregator's
code_key both key on this truncated 24-bit value, per xdrv_95_cc1101.ino's CcPublishRfReceived).

Deviation from the task brief: the brief's example call was
rcswitch1_pulses(0xC3FF3F, 24, 350) (pulse_us=350). Empirically that pulse width does not
reproduce the R7 scenario at all -- it selects the "fixed-period" family (short=340, long=1000,
reset_us=1012), whose reset_us (1012) sits just below a "0" data bit's own 3p=1050us space, so
the decode terminates after only a few bits (never reaching OOKPWM_MIN_BITS=16) and
ookpwm_decode() returns no packet whatsoever. pulse_us=200 is the width Task 3 actually
established (see test_pulse.py) and is what genuinely produces the 25-bit report this test
documents; it is used here instead.
"""
import ctypes
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import firmwarelib  # noqa: E402
from decoderlib import decode_pulses, load  # noqa: E402

U32P = ctypes.POINTER(ctypes.c_uint32)

CODE_24BIT = 0xC3FF3F
BITS_24 = 24
PULSE_US = 200  # see module docstring: the width that actually reproduces R7


def _lib():
    L = firmwarelib.build_c()
    L.rcswitch1_pulses.restype = ctypes.c_size_t
    L.rcswitch1_pulses.argtypes = [ctypes.c_uint32, ctypes.c_uint, ctypes.c_uint32, U32P, ctypes.c_size_t]
    return L


def _cc_publish_rf_received_truncate(code_hex: str) -> int:
    """Python port of CcPublishRfReceived()'s Data truncation in xdrv_95_cc1101.ino:
        uint64_t v = strtoull(code_hex, nullptr, 16); int width = strlen(code_hex) * 4;
        if (width > 24) v >>= (width - 24);
        ... v & 0xFFFFFF ...
    """
    v = int(code_hex, 16)
    width = len(code_hex) * 4
    if width > 24:
        v >>= (width - 24)
    return v & 0xFFFFFF


def test_rcswitch_roundtrip_reports_25_bits():
    """Document the raw decoder output for a real RCSwitch protocol-1 waveform (Task 3 finding)."""
    L = _lib()
    us = (ctypes.c_uint32 * 64)()
    n = L.rcswitch1_pulses(CODE_24BIT, BITS_24, PULSE_US, us, 64)
    assert n == 50  # 24 bits x (mark,space) + sync (mark,space)

    dec = decode_pulses(load(), list(us[:n]))
    assert len(dec) == 1
    packet = dec[0]
    # Raw decoder output: 25 bits (24 real data bits + the sync's leading mark consumed as a
    # spurious 25th bit), code "c3ff3f0" (0xC3FF3F with a trailing zero bit appended).
    assert packet["bits"] == 25
    assert packet["code"] == "c3ff3f0"


def test_first_24_bit_truncation_recovers_original_code():
    """The dedup-critical path: CcPublishRfReceived()'s truncation must recover 0xC3FF3F."""
    L = _lib()
    us = (ctypes.c_uint32 * 64)()
    n = L.rcswitch1_pulses(CODE_24BIT, BITS_24, PULSE_US, us, 64)
    dec = decode_pulses(load(), list(us[:n]))
    assert dec and dec[0]["bits"] == 25

    recovered = _cc_publish_rf_received_truncate(dec[0]["code"])
    assert recovered == CODE_24BIT

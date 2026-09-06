"""Synthesize OOK-PWM pulse trains (mark/space µs, starting with a mark).

Conventions match protocols/ook-pwm-remotes.md and cc1101.py:pwm_code_to_pulses:
a code is written MSB-first as hex left-aligned to whole digits (25 bits -> 7 hex
digits with 3 zero pad bits, e.g. 'c3ff3f8'); a '1' bit is a LONG mark when
long_is_one=True (the default; see OOKPWM_LONG_IS_ONE in decode_ookpwm.h).
"""


def code_to_bits(code_hex: str, bits: int) -> list[int]:
    v = int(code_hex, 16)
    width = len(code_hex) * 4
    v >>= (width - bits)                      # drop the left-align pad bits
    return [(v >> (bits - 1 - i)) & 1 for i in range(bits)]


def bits_to_code(bitlist: list[int]) -> str:
    bits = len(bitlist)
    v = 0
    for b in bitlist:
        v = (v << 1) | b
    pad = (4 - bits % 4) % 4
    return format(v << pad, "0%dx" % ((bits + pad) // 4))


def pwm_standard(code_hex, bits=25, short=200, long=730, sync_gap=7300, long_is_one=True, repeats=1):
    """'Standard' family (grey power remotes, doorbell): each bit = mark + space with
    constant period short+long; the packet ends with a long sync gap."""
    out = []
    for _ in range(repeats):
        for b in code_to_bits(code_hex, bits):
            is_long = bool(b) == long_is_one
            out += [long if is_long else short, short if is_long else long]
        out[-1] = sync_gap
    return out


def pwm_fixed_period(code_hex, bits=25, short=340, long=1000, period=1340, reset_gap=3000,
                     long_is_one=True, repeats=1):
    """'Fixed-period' family (3-button bed remote): mark width varies, period fixed."""
    out = []
    for _ in range(repeats):
        for b in code_to_bits(code_hex, bits):
            mark = long if (bool(b) == long_is_one) else short
            out += [mark, period - mark]
        out[-1] = reset_gap
    return out

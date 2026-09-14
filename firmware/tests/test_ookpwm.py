import pytest
from conftest import decode_pulses
from pulsegen import pwm_standard, pwm_fixed_period

# Codes from sites/welland/rf-codes.md
GREY5_ON, GREY5_OFF = "c3ff3f8", "c3ffff8"
BED_LEFT, DOORBELL = "fa07cb8", "5596fc8"


def test_grey_remote_standard_family(lib):
    r = decode_pulses(lib, pwm_standard(GREY5_ON))
    assert len(r) == 1
    assert r[0]["model"] == "OOK-PWM" and r[0]["family"] == "standard"
    assert r[0]["bits"] == 25 and r[0]["code"] == GREY5_ON
    assert 150 <= r[0]["short_us"] <= 250 and 680 <= r[0]["long_us"] <= 780


def test_three_repeats_give_three_packets(lib):
    r = decode_pulses(lib, pwm_standard(GREY5_OFF, repeats=3))
    assert [x["code"] for x in r] == [GREY5_OFF] * 3


def test_doorbell_timing_variant(lib):
    r = decode_pulses(lib, pwm_standard(DOORBELL, short=208, long=724))
    assert len(r) == 1 and r[0]["code"] == DOORBELL


def test_bed_remote_fixed_period_family(lib):
    r = decode_pulses(lib, pwm_fixed_period(BED_LEFT))
    assert len(r) == 1 and r[0]["family"] == "fixed-period" and r[0]["code"] == BED_LEFT


def test_jitter_tolerated(lib):
    us = pwm_standard(GREY5_ON)
    us = [v + ((i * 37) % 61 - 30) for i, v in enumerate(us)]   # ±30 µs deterministic jitter
    r = decode_pulses(lib, us)
    assert len(r) == 1 and r[0]["code"] == GREY5_ON


def test_noise_rejected(lib):
    noise = [50, 120, 90, 3000, 40, 60, 500, 9000]            # too few bits, erratic widths
    assert decode_pulses(lib, noise) == []


def test_train_without_trailing_gap_still_decodes(lib):
    us = pwm_standard(GREY5_ON)[:-1]                          # drop final sync gap (odd length)
    r = decode_pulses(lib, us)
    assert len(r) == 1 and r[0]["code"] == GREY5_ON


def test_family_chosen_by_closest_timing_not_table_order(lib):
    # standard marks (200/730) are inside the fixed-period tolerance windows too;
    # best-match must still say "standard", and 340/1000 must still say "fixed-period".
    r = decode_pulses(lib, pwm_standard(GREY5_ON))
    assert r[0]["family"] == "standard"
    r = decode_pulses(lib, pwm_fixed_period(BED_LEFT))
    assert r[0]["family"] == "fixed-period"
    # a train half-way between families (short 270, long 860) must still decode to ONE family, deterministically
    r = decode_pulses(lib, pwm_standard(GREY5_ON, short=270, long=860))
    assert len(r) == 1 and r[0]["family"] in ("standard", "fixed-period") and r[0]["code"] == GREY5_ON

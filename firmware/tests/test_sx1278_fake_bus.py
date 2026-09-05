"""SX1278Radio against a fake bus + fake reset line: RegVersion identify, SPI framing, reset pulse.

Mirrors test_radio_fake_bus.py (the CC1101 equivalent)."""
import json
import os
import subprocess
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import firmwarelib  # noqa: E402


def host(*args):
    exe = firmwarelib.build_sx1278_host()
    out = subprocess.run([exe, *args], check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def test_identify_reads_regversion_0x42_read_framing():
    r = host("identify")
    assert r["ok"] == 1 and r["ver"] == 0x12
    # read RegVersion: select, address 0x42 (bit7=0 -> read), dummy byte, deselect
    assert r["log"] == ["S", "42", "00", "D"]


def test_identify_rejects_wrong_version():
    r = host("identify_bad")
    assert r == {"ok": 0, "ver": 0}


def test_write_reg_sets_address_bit7():
    r = host("write_reg")
    assert r["reg1"] == 0x0A
    # write RegOpMode(0x01): address byte is 0x01|0x80 = 0x81, then the value 0x0a
    assert r["log"] == ["S", "81", "0a", "D"]


def test_read_reg_clears_address_bit7_and_returns_value():
    r = host("read_reg")
    assert r["val"] == 0x6C
    assert r["log"] == ["S", "06", "00", "D"]   # 0x06 has bit7 clear -> read


def test_reset_pulses_low_then_high():
    r = host("reset")
    assert r["rst"] == ["L", "H"]               # active-low: assert then release

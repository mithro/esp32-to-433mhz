"""WH51 soil-moisture decoder tests, driven by REAL frames captured on hardware.

Ground truth: frames captured by the rpi5-433mhz reference CC1101 logger
(~/wh51-watch/cc1101.hits.jsonl) and independently field-decoded by
~/wh51-watch/wh51.py, itself a port of rtl_433 src/devices/fineoffset.c
(fineoffset_WH51_callback). The asserted values below match what that
reference reported for the very same bytes.
"""
import json
import os
import pytest
from conftest import decode_bytes

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(os.path.dirname(HERE), "fixtures")


def load_packets(name):
    with open(os.path.join(FIX, name)) as f:
        d = json.load(f)
    assert d["format"] == "rf433-packets-v1"
    return d["packets"]


def test_real_wh51_id0f5c54_frame(lib):
    # Real frame from the reference CC1101 logger (valid=true, is_target=true).
    pk = load_packets("wh51_id0f5c54_2026-09-05.json")[0]
    rc, obj = decode_bytes(lib, "fineoffset_decode", bytes.fromhex(pk["hex"]))
    assert rc == 1
    assert obj["model"] == "Fineoffset-WH51"
    assert obj["id"] == "0f5c54"
    assert obj["moisture"] == 40
    assert obj["battery_mV"] == 1600
    assert obj["battery_ok"] == pytest.approx(1.0)   # rtl_433 level ladder: >=1600 mV -> 1.0
    assert obj["boost"] == 0
    assert obj["ad_raw"] == 208
    assert obj["mic"] == "CRC"


def test_real_wh51_id0f5d66_frame(lib):
    # Second real WH51 sensor seen at Welland (valid=true).
    pk = load_packets("wh51_id0f5c54_2026-09-05.json")[1]
    rc, obj = decode_bytes(lib, "fineoffset_decode", bytes.fromhex(pk["hex"]))
    assert rc == 1
    assert obj["model"] == "Fineoffset-WH51"
    assert obj["id"] == "0f5d66"
    assert obj["moisture"] == 38
    assert obj["battery_mV"] == 1500
    assert obj["battery_ok"] == pytest.approx(0.9)   # rtl_433 ladder: 0x0f=15 bits -> 0.9
    assert obj["ad_raw"] == 195


def test_wh51_glitch_frame_is_rejected(lib):
    # Real 0x51-prefixed noise the logger recorded with crc_ok=false: must not decode.
    pk = load_packets("wh51_id0f5c54_2026-09-05.json")[2]
    rc, _ = decode_bytes(lib, "fineoffset_decode", bytes.fromhex(pk["hex"]))
    assert rc == -1   # RF_DECODE_BAD_MIC


def test_wh51_decoded_inside_longer_drained_read(lib):
    # On the CC1101 the FSK RX preset runs infinite length mode and the driver drains a
    # fixed 30 bytes, so a 14-byte WH51 frame arrives at the head of a longer buffer with
    # trailing demodulated noise behind it. The decoder must ignore the tail.
    pk = load_packets("wh51_id0f5c54_2026-09-05.json")[0]
    frame = bytes.fromhex(pk["hex"])                 # 14 real bytes
    padded = frame + bytes.fromhex("DEADBEEFCAFE1122334455")  # +11 noise -> 25 bytes
    assert len(padded) == 25
    rc, obj = decode_bytes(lib, "fineoffset_decode", padded)
    assert rc == 1
    assert obj["model"] == "Fineoffset-WH51"
    assert obj["id"] == "0f5c54"
    assert obj["moisture"] == 40


def test_wh51_too_short(lib):
    rc, _ = decode_bytes(lib, "fineoffset_decode", bytes.fromhex("510F5C5410"))
    assert rc == -2   # RF_DECODE_TOO_SHORT


def test_wh51_bad_crc_rejected(lib):
    # Flip a payload byte inside the CRC range: additive sum may still differ, but
    # either way the frame must be rejected as bad MIC.
    b = bytearray.fromhex("510F5C54107F28F8D0FFFFFF4BD7")
    b[6] ^= 0x01                                      # corrupt moisture byte
    rc, _ = decode_bytes(lib, "fineoffset_decode", bytes(b))
    assert rc == -1

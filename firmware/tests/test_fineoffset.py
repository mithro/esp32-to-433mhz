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


def _crc8_0x31(data):
    """MSB-first CRC8, poly 0x31, init 0 -- mirrors decode_common.c rf_crc8()."""
    rem = 0
    for byte in data:
        rem ^= byte
        for _ in range(8):
            rem = ((rem << 1) ^ 0x31) & 0xFF if (rem & 0x80) else (rem << 1) & 0xFF
    return rem


def _ws85_with_checks(b):
    """Recompute the WS85 tail CRC (b[26]) and SUM (b[27]) for a mutated frame."""
    b[26] = _crc8_0x31(bytes(b[0:26]))
    b[27] = sum(b[0:27]) & 0xFF
    return bytes(b)


def test_real_ws69_id174_frame(lib):
    pk = load_packets("ws69_id174_2026-08-20.json")[0]
    rc, obj = decode_bytes(lib, "fineoffset_decode", bytes.fromhex(pk["hex"]))
    assert rc == 1
    assert obj["model"] == "Fineoffset-WS69"
    assert obj["id"] == 174
    assert obj["battery_ok"] == 1
    assert obj["temperature_C"] == pytest.approx(13.1)
    assert obj["humidity"] == 82
    assert obj["wind_dir_deg"] == 349
    assert obj["wind_avg_m_s"] == pytest.approx(0.3)     # 5 * 0.125 * 0.51 = 0.319 -> "%.1f"
    assert obj["wind_max_m_s"] == pytest.approx(0.5)     # 1 * 0.51
    assert obj["rain_mm"] == pytest.approx(464.3)        # 0x0724 * 0.254
    assert obj["uv"] == 0 and obj["uvi"] == 0
    assert obj["light_lux"] == pytest.approx(0.0)
    assert "pressure_hPa" not in obj                     # 0x01FFFF = no pressure module
    assert obj["mic"] == "CRC"


def test_noise_and_beacon_frames_are_rejected(lib):
    for pk in load_packets("ws69_id174_2026-08-20.json")[2:]:
        rc, _ = decode_bytes(lib, "fineoffset_decode", bytes.fromhex(pk["hex"]))
        assert rc <= 0, pk["note"]


def test_rtl433_doc_wh24_vector_as_17_bytes(lib):
    # rtl_433 fineoffset.c doc example (WH24): 17-byte payload only -> named WH65B
    # by byte count, WH65 factors (0.51 m/s, 0.254 mm) as rtl_433 does for non-WH24.
    b = bytes.fromhex("24bf0ae2064e0802004a000100000" "08f07")
    rc, obj = decode_bytes(lib, "fineoffset_decode", b)
    assert rc == 1
    assert obj["model"] == "Fineoffset-WH65B"
    assert obj["id"] == 191
    assert obj["temperature_C"] == pytest.approx(11.8)
    assert obj["humidity"] == 78
    assert obj["wind_dir_deg"] == 266
    assert obj["wind_avg_m_s"] == pytest.approx(0.5)     # 8 * 0.125 * 0.51
    assert obj["wind_max_m_s"] == pytest.approx(1.0)     # 2 * 0.51
    assert obj["rain_mm"] == pytest.approx(18.8)         # 74 * 0.254
    assert obj["uv"] == 1 and obj["uvi"] == 0


def test_corrupted_frame_is_bad_mic(lib):
    b = bytearray.fromhex("24AE5D8213520501072400000000005AA101FFFFFF016B8733")
    b[5] ^= 0x10
    rc, _ = decode_bytes(lib, "fineoffset_decode", bytes(b))
    assert rc == -1


def test_ws69_with_corrupted_tail_keeps_model_but_drops_pressure(lib):
    # Real frame with one tail byte flipped (b[20] ^= 0x01): main 16-byte CRC still valid,
    # 24-byte tail CRC invalid. rtl_433 parity: still "Fineoffset-WS69", pressure omitted.
    b = bytes.fromhex("24AE5D8213520501072400000000005AA101FFFFFE016B8733")
    rc, obj = decode_bytes(lib, "fineoffset_decode", b)
    assert rc == 1
    assert obj["model"] == "Fineoffset-WS69" and obj["id"] == 174
    assert "pressure_hPa" not in obj


def test_ws69_with_pressure_module(lib):
    # Real frame with bytes 17-19 set to raw 0x018BCD (= 1013.25 hPa) and the tail CRC
    # (b[23]) and tail SUM (b[24]) recomputed so both tail checks pass.
    b = bytes.fromhex("24AE5D8213520501072400000000005AA1018BCDFF016B9298")
    rc, obj = decode_bytes(lib, "fineoffset_decode", b)
    assert rc == 1
    assert obj["model"] == "Fineoffset-WS69"
    assert obj["pressure_hPa"] == pytest.approx(1013.25)
    assert obj["temperature_C"] == pytest.approx(13.1)   # rest of the frame unchanged


def test_short_frame(lib):
    rc, _ = decode_bytes(lib, "fineoffset_decode", bytes.fromhex("24AE5D82"))
    assert rc == -2


def test_unknown_family_is_none(lib):
    rc, _ = decode_bytes(lib, "fineoffset_decode", bytes(17))
    assert rc == 0


def test_rtl433_doc_ws85_vector(lib):
    # rtl_433 fineoffset_ws85.c doc example; CRC(26)=0xDD, SUM(27)=0x0F verified.
    b = bytes.fromhex("850028EB87826F0083003FFF00000000000B0000FFEFFD00006BDD0F000000")
    rc, obj = decode_bytes(lib, "fineoffset_decode", b)
    assert rc == 1
    assert obj["model"] == "Fineoffset-WS85"
    assert obj["id"] == 0x0028EB
    assert obj["battery_mV"] == 2700 and obj["battery_ok"] == 1 and obj["battery_pct"] == 81
    assert obj["wind_dir_deg"] == 131
    assert obj["wind_avg_m_s"] == pytest.approx(0.0) and obj["wind_max_m_s"] == pytest.approx(0.0)
    assert obj["flags"] == 0x82
    assert obj["rain_mm"] == pytest.approx(0.0) and obj["rain_start"] == 0
    assert obj["supercap_V"] == pytest.approx(1.1)
    assert obj["firmware"] == 107
    assert obj["mic"] == "CRC"


def test_ws85_bad_crc(lib):
    b = bytearray.fromhex("850028EB87826F0083003FFF00000000000B0000FFEFFD00006BDD0F000000")
    b[7] ^= 0x01
    rc, _ = decode_bytes(lib, "fineoffset_decode", bytes(b))
    assert rc == -1


def test_ws85_too_short(lib):
    rc, _ = decode_bytes(lib, "fineoffset_decode", bytes.fromhex("850028EB8782"))
    assert rc == -2


def test_ws85_msb_extension_bits_and_rain_start(lib):
    # Same doc vector as test_rtl433_doc_ws85_vector, but with the wind MSB flag
    # bits (0x10/0x20/0x40 in b[5]) set so wind_avg/wind_dir/wind_max each gain
    # bit 8, non-zero low bytes, and rain_start set in b[12]. Tail CRC/SUM
    # recomputed since the mutated bytes fall inside the checked range.
    b = bytearray.fromhex("850028EB87826F0083003FFF00000000000B0000FFEFFD00006BDD0F000000")
    b[5] |= 0x70          # 0x10 | 0x20 | 0x40: wind_avg/wind_dir/wind_max MSBs
    b[7] = 0x05           # wind_avg low byte
    b[8] = 0x20           # wind_dir low byte
    b[9] = 0x07           # wind_max low byte
    b[12] |= 0x10         # rain_start
    b = _ws85_with_checks(b)
    rc, obj = decode_bytes(lib, "fineoffset_decode", b)
    assert rc == 1
    assert obj["wind_avg_m_s"] == pytest.approx((0x100 | 0x05) * 0.1)
    assert obj["wind_dir_deg"] == (0x100 | 0x20)
    assert obj["wind_max_m_s"] == pytest.approx((0x100 | 0x07) * 0.1)
    assert obj["rain_start"] == 1
    assert obj["flags"] == (0x82 | 0x70)


def test_ws69_pressure_dropped_when_tail_crc_bad_nonsentinel(lib):
    # Real-pressure vector (test_ws69_with_pressure_module) with one tail byte
    # flipped: main 16-byte CRC intact, 24-byte tail CRC now wrong, and the
    # pressure bytes are a genuine reading (not the 0x01FFFF sentinel).
    b = bytearray.fromhex("24AE5D8213520501072400000000005AA1018BCDFF016B9298")
    b[20] ^= 0x01
    rc, obj = decode_bytes(lib, "fineoffset_decode", bytes(b))
    assert rc == 1
    assert obj["model"] == "Fineoffset-WS69"
    assert "pressure_hPa" not in obj

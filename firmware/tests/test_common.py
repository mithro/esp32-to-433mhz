"""rf_crc8 / rf_add_bytes must match rtl_433's bit_util.c (poly 0x31, init 0)."""
import ctypes


def test_crc8_ws69_frame_is_zero_over_16_bytes(lib):
    # Real Fineoffset WS69 id 174 frame, rpi5-433mhz CC1101, 2026-08-20.
    b = bytes.fromhex("24AE5D8213520501072400000000005AA101FFFFFF016B8733")
    buf = (ctypes.c_uint8 * len(b)).from_buffer_copy(b)
    assert lib.rf_crc8(buf, 16, 0x31, 0x00) == 0
    assert lib.rf_add_bytes(buf, 16) == b[16] == 0xA1
    assert lib.rf_crc8(buf, 24, 0x31, 0x00) == 0
    assert lib.rf_add_bytes(buf, 24) == b[24] == 0x33


def test_crc8_detects_corruption(lib):
    b = bytearray.fromhex("24AE5D8213520501072400000000005AA1")
    b[4] ^= 0x01
    buf = (ctypes.c_uint8 * len(b)).from_buffer_copy(bytes(b))
    assert lib.rf_crc8(buf, 16, 0x31, 0x00) != 0


def test_json_append_truncates_cleanly(lib):
    buf = ctypes.create_string_buffer(8)
    SZ, I = ctypes.c_size_t, ctypes.c_int                    # explicit widths: variadic, no argtypes
    n = lib.rf_json_append(buf, SZ(8), I(0), b"%s", b"1234567")   # fits exactly (7 + NUL)
    assert n == 7 and buf.value == b"1234567"
    n = lib.rf_json_append(buf, SZ(8), I(n), b"%s", b"x")          # would overflow
    assert n == -1
    n = lib.rf_json_append(buf, SZ(8), I(-1), b"%s", b"y")         # stays failed
    assert n == -1


def test_wiring_diagram_matches_spec_pins():
    import importlib.util, os
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools", "esp32c3-cc1101-node-wiring.py")
    spec = importlib.util.spec_from_file_location("wiring", p)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    wires = {d: e for d, e, _, _ in m.WIRES}
    assert wires == {"VCC": "3V3", "GND": "GND", "SCK": "GPIO4", "MOSI": "GPIO6", "MISO": "GPIO5",
                     "CSN": "GPIO7", "GDO0": "GPIO3", "GDO2": "GPIO10"}
    assert not ({"GPIO2", "GPIO8", "GPIO9"} & set(wires.values()))
    svg = m.build_svg()
    for name in list(wires) + list(wires.values()):
        assert name in svg

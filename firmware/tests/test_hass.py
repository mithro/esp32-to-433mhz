"""Home Assistant MQTT Discovery shaping (cc1101_node/cc1101_hass.c), host-tested.

The node self-publishes HA discovery so Home Assistant creates the weather/moisture
entities natively — no rtl_433 add-on. These tests assert the exact discovery topics
and config JSON, and run the real decoder so the field extraction is exercised against
genuine decoder output (not a hand-written string).
"""
import ctypes
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import firmwarelib  # noqa: E402

TMAX, JMAX = 192, 512
WS69_HEX = "24AE5D8213520501072400000000005AA101FFFFFF016B8733"  # id 174 (test_fineoffset)
WH51_HEX = "510F5C54107F28F8D0FFFFFF4BD7"                        # id 5c5410 (test_wh51/mqtt_shape)


def lib():
    L = firmwarelib.build_c()
    for n in ("cc_hass_state_topic", "cc_hass_config_topic", "cc_hass_config_payload", "cc_hass_extract"):
        getattr(L, n).restype = ctypes.c_int
    cp, sz = ctypes.c_char_p, ctypes.c_size_t
    L.cc_hass_state_topic.argtypes = [cp, sz, cp, cp, cp, cp]
    L.cc_hass_config_topic.argtypes = [cp, sz, cp, cp, cp]
    L.cc_hass_field_lookup.restype = ctypes.c_void_p
    L.cc_hass_field_lookup.argtypes = [cp]
    L.cc_hass_config_payload.argtypes = [cp, sz, cp, cp, cp, ctypes.c_void_p, cp, cp]
    L.cc_hass_extract.argtypes = [cp, cp, cp, sz]
    L.fineoffset_decode.restype = ctypes.c_int
    L.fineoffset_decode.argtypes = [ctypes.POINTER(ctypes.c_uint8), sz, cp, sz]
    return L


def decode_json(L, hexstr):
    frame = bytes.fromhex(hexstr)
    out = ctypes.create_string_buffer(512)
    rc = L.fineoffset_decode((ctypes.c_uint8 * len(frame))(*frame), len(frame), out, 512)
    assert rc > 0, "decoder rejected the fixture frame"
    return out.value.decode()


def test_state_topic():
    L = lib()
    buf = ctypes.create_string_buffer(TMAX)
    L.cc_hass_state_topic(buf, TMAX, b"blue", b"Fineoffset-WS69", b"174", b"temperature_C")
    assert buf.value == b"rtl_433/nodes/blue/devices/Fineoffset-WS69/174/temperature_C"


def test_config_topic():
    L = lib()
    buf = ctypes.create_string_buffer(TMAX)
    L.cc_hass_config_topic(buf, TMAX, b"Fineoffset-WS69", b"174", b"temperature_C")
    assert buf.value == b"homeassistant/sensor/Fineoffset-WS69-174/Fineoffset-WS69-174-temperature_C/config"


def test_config_payload_valid_json():
    L = lib()
    buf = ctypes.create_string_buffer(JMAX)
    f = L.cc_hass_field_lookup(b"temperature_C")
    assert f, "temperature_C must be a known field"
    st = b"rtl_433/nodes/blue/devices/Fineoffset-WS69/174/temperature_C"
    n = L.cc_hass_config_payload(buf, JMAX, b"blue", b"Fineoffset-WS69", b"174", f, st, b"tele/blue/LWT")
    assert n > 0
    cfg = json.loads(buf.value.decode("utf-8"))
    assert cfg["name"] == "Temperature"
    assert cfg["uniq_id"] == "Fineoffset-WS69-174-temperature_C"
    assert cfg["stat_t"] == st.decode()
    assert cfg["dev_cla"] == "temperature"
    assert cfg["unit_of_meas"] == "°C"
    assert cfg["stat_cla"] == "measurement"
    assert cfg["val_tpl"] == "{{ value|float|round(1) }}"
    assert cfg["avty_t"] == "tele/blue/LWT"
    assert cfg["dev"]["ids"] == ["Fineoffset-WS69-174"]
    assert cfg["dev"]["mf"] == "Fine Offset"
    assert cfg["dev"]["mdl"] == "Fineoffset-WS69"


def test_config_payload_omits_null_meta():
    """wind_dir_deg has no device_class → the key must be absent, still valid JSON."""
    L = lib()
    buf = ctypes.create_string_buffer(JMAX)
    f = L.cc_hass_field_lookup(b"wind_dir_deg")
    assert f
    L.cc_hass_config_payload(buf, JMAX, b"n", b"Fineoffset-WS69", b"174", f,
                             b"rtl_433/nodes/n/devices/Fineoffset-WS69/174/wind_dir_deg", None)
    cfg = json.loads(buf.value.decode("utf-8"))
    assert "dev_cla" not in cfg           # NULL device_class omitted
    assert "avty_t" not in cfg            # NULL avail_topic omitted
    assert cfg["unit_of_meas"] == "°"


def test_config_payload_battery_ok_all_null_meta():
    """battery_ok (WS69's only battery signal) has no device_class/unit/state_class/val_tpl —
    the config must still be valid JSON with just name/uniq_id/stat_t/dev."""
    L = lib()
    buf = ctypes.create_string_buffer(JMAX)
    f = L.cc_hass_field_lookup(b"battery_ok")
    assert f, "battery_ok must be a known field"
    L.cc_hass_config_payload(buf, JMAX, b"n", b"Fineoffset-WS69", b"174", f,
                             b"rtl_433/nodes/n/devices/Fineoffset-WS69/174/battery_ok", None)
    cfg = json.loads(buf.value.decode("utf-8"))
    assert cfg["name"] == "Battery OK"
    assert cfg["uniq_id"] == "Fineoffset-WS69-174-battery_ok"
    for k in ("dev_cla", "unit_of_meas", "stat_cla", "val_tpl", "avty_t"):
        assert k not in cfg
    assert cfg["dev"]["ids"] == ["Fineoffset-WS69-174"]


def test_extract_string_and_number_and_absent():
    L = lib()
    buf = ctypes.create_string_buffer(48)
    js = b'{"model":"Fineoffset-WH51","id":"0f4b37","battery_ok":0.9,"moisture":24,"mic":"CRC"}'
    L.cc_hass_extract(js, b"id", buf, 48);        assert buf.value == b"0f4b37"
    L.cc_hass_extract(js, b"moisture", buf, 48);  assert buf.value == b"24"
    L.cc_hass_extract(js, b"model", buf, 48);     assert buf.value == b"Fineoffset-WH51"
    L.cc_hass_extract(js, b"battery_ok", buf, 48); assert buf.value == b"0.9"
    assert L.cc_hass_extract(js, b"temperature_C", buf, 48) == -1


def test_integration_ws69_discovery_from_real_decode():
    L = lib()
    js = decode_json(L, WS69_HEX)
    mbuf, ibuf = ctypes.create_string_buffer(32), ctypes.create_string_buffer(24)
    L.cc_hass_extract(js.encode(), b"model", mbuf, 32)
    L.cc_hass_extract(js.encode(), b"id", ibuf, 24)
    assert mbuf.value == b"Fineoffset-WS69"
    assert ibuf.value == b"174"
    # every present, known field must yield a valid discovery config
    vbuf = ctypes.create_string_buffer(24)
    for field in (b"temperature_C", b"humidity", b"wind_avg_m_s", b"rain_mm"):
        assert L.cc_hass_extract(js.encode(), field, vbuf, 24) >= 0, field
        f = L.cc_hass_field_lookup(field)
        assert f
        st = ctypes.create_string_buffer(TMAX)
        L.cc_hass_state_topic(st, TMAX, b"blue", mbuf.value, ibuf.value, field)
        cbuf = ctypes.create_string_buffer(JMAX)
        n = L.cc_hass_config_payload(cbuf, JMAX, b"blue", mbuf.value, ibuf.value, f, st.value, b"tele/blue/LWT")
        assert n > 0
        json.loads(cbuf.value.decode("utf-8"))  # must be valid JSON


def test_integration_wh51_moisture():
    L = lib()
    js = decode_json(L, WH51_HEX)
    ibuf, vbuf = ctypes.create_string_buffer(24), ctypes.create_string_buffer(24)
    L.cc_hass_extract(js.encode(), b"id", ibuf, 24)
    assert L.cc_hass_extract(js.encode(), b"moisture", vbuf, 24) >= 0
    f = L.cc_hass_field_lookup(b"moisture")
    assert f
    cbuf = ctypes.create_string_buffer(JMAX)
    st = b"rtl_433/nodes/blue/devices/Fineoffset-WH51/" + ibuf.value + b"/moisture"
    L.cc_hass_config_payload(cbuf, JMAX, b"blue", b"Fineoffset-WH51", ibuf.value, f, st, None)
    cfg = json.loads(cbuf.value.decode("utf-8"))
    assert cfg["dev_cla"] == "humidity"
    assert cfg["unit_of_meas"] == "%"

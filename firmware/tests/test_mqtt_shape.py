"""MQTT topic + event-JSON shaping (cc1101_node/cc1101_mqtt.c), host-tested.

The Tasmota driver publishes decoded RF as rtl_433-shaped JSON. The exact topic
string and the wrapped-event bytes are built by the pure-C helpers in
cc1101_mqtt.c (called from xdrv_95_cc1101.ino), so these tests assert the very
bytes that reach MQTT — including that the Home Assistant "direct" topic actually
matches the rtl_433 autodiscovery subscription rtl_433/+/events, and that the
default aggregator topic does not (it needs the aggregator's republish).
"""
import ctypes
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import firmwarelib  # noqa: E402

TOPIC_MAX = 128
JSON_MAX = 512
CC_HASS_AGG, CC_HASS_DIRECT = 0, 1

# A real WH51 soil-moisture frame (same one used by test_wh51.py), so the wrapped
# event is asserted against a genuine decoder payload, not a hand-written string.
WH51_HEX = "510F5C54107F28F8D0FFFFFF4BD7"


def lib():
    L = firmwarelib.build_c()
    for name in ("cc_events_topic", "cc_node_topic", "cc_wrap_event"):
        getattr(L, name).restype = ctypes.c_int
    L.cc_events_topic.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_int, ctypes.c_char_p]
    L.cc_node_topic.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p, ctypes.c_char_p]
    L.cc_wrap_event.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p,
                                ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p]
    L.fineoffset_decode.restype = ctypes.c_int
    L.fineoffset_decode.argtypes = [ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t,
                                    ctypes.c_char_p, ctypes.c_size_t]
    return L


def events_topic(L, hass, host):
    buf = ctypes.create_string_buffer(TOPIC_MAX)
    n = L.cc_events_topic(buf, TOPIC_MAX, hass, host.encode())
    return n, buf.value.decode()


def node_topic(L, host, leaf):
    buf = ctypes.create_string_buffer(TOPIC_MAX)
    n = L.cc_node_topic(buf, TOPIC_MAX, host.encode(), leaf.encode())
    return n, buf.value.decode()


def wrap_event(L, time, receiver, rssi, decoder_json):
    buf = ctypes.create_string_buffer(JSON_MAX)
    n = L.cc_wrap_event(buf, JSON_MAX, time.encode(), receiver.encode(), rssi, decoder_json.encode())
    return n, buf.value.decode()


def decode(L, hexstr):
    data = bytes.fromhex(hexstr)
    arr = (ctypes.c_uint8 * len(data)).from_buffer_copy(data)
    out = ctypes.create_string_buffer(JSON_MAX)
    rc = L.fineoffset_decode(arr, len(data), out, JSON_MAX)
    return rc, out.value.decode()


def mqtt_matches(filt, topic):
    """Minimal MQTT topic-filter match (single-level '+', multi-level '#')."""
    f, t = filt.split("/"), topic.split("/")
    for i, seg in enumerate(f):
        if seg == "#":
            return True
        if i >= len(t):
            return False
        if seg != "+" and seg != t[i]:
            return False
    return len(f) == len(t)


# ---- topics --------------------------------------------------------------

def test_aggregator_events_topic_default():
    _, topic = events_topic(lib(), CC_HASS_AGG, "cc1101-welland-carport")
    assert topic == "rtl_433/nodes/cc1101-welland-carport/events"


def test_direct_events_topic():
    _, topic = events_topic(lib(), CC_HASS_DIRECT, "cc1101-welland-carport")
    assert topic == "rtl_433/cc1101-welland-carport/events"


def test_direct_topic_matches_hass_autodiscovery_but_aggregator_does_not():
    L = lib()
    _, direct = events_topic(L, CC_HASS_DIRECT, "cc1101-welland-carport")
    _, agg = events_topic(L, CC_HASS_AGG, "cc1101-welland-carport")
    # The rtl_433 HA add-on subscribes to this:
    assert mqtt_matches("rtl_433/+/events", direct) is True
    assert mqtt_matches("rtl_433/+/events", agg) is False
    # ...and the aggregator's per-node subscription only sees the AGG form:
    assert mqtt_matches("rtl_433/nodes/+/events", agg) is True
    assert mqtt_matches("rtl_433/nodes/+/events", direct) is False


def test_node_topic_used_for_tx_announce():
    _, topic = node_topic(lib(), "cc1101-welland-carport", "tx")
    assert topic == "rtl_433/nodes/cc1101-welland-carport/tx"


def test_events_topic_truncation_returns_error():
    buf = ctypes.create_string_buffer(8)
    assert lib().cc_events_topic(buf, 8, CC_HASS_AGG, b"averylonghostname") == -1
    assert buf.value == b""


# ---- event JSON ----------------------------------------------------------

def test_wrap_event_is_valid_rtl433_json():
    L = lib()
    rc, dec = decode(L, WH51_HEX)
    assert rc == 1
    n, ev = wrap_event(L, "2026-09-05T14:03:11", "cc1101-welland-carport", -71, dec)
    assert n == len(ev)
    obj = json.loads(ev)                      # must be valid JSON for HA to ingest it
    # rtl_433 envelope fields the HA autodiscovery keys off:
    assert obj["time"] == "2026-09-05T14:03:11"
    assert obj["receiver"] == "cc1101-welland-carport"
    assert obj["rssi"] == -71
    # decoder fields survive unchanged (so HA builds moisture/battery entities):
    assert obj["model"] == "Fineoffset-WH51"
    assert obj["id"] == "0f5c54"
    assert obj["moisture"] == 40
    assert obj["battery_mV"] == 1600
    assert obj["mic"] == "CRC"


def test_wrap_event_float_field_is_numeric_not_star_float():
    # WS69 temperature_C is a float; picolibc's integer printf would emit the
    # literal *float* (invalid JSON). rf_ftoa must keep it a real number so HA
    # accepts the message and creates a temperature sensor.
    L = lib()
    ws69 = ('{"model":"Fineoffset-WS69","id":174,"battery_ok":1,'
            '"temperature_C":13.1,"humidity":82}')
    _, ev = wrap_event(L, "2026-09-05T14:03:11", "cc1101-welland-carport", -84, ws69)
    obj = json.loads(ev)
    assert obj["temperature_C"] == 13.1
    assert isinstance(obj["temperature_C"], float)


def test_wrap_event_truncation_returns_error():
    L = lib()
    buf = ctypes.create_string_buffer(16)
    assert L.cc_wrap_event(buf, 16, b"2026-09-05T14:03:11", b"host", -71,
                           b'{"model":"X"}') == -1
    assert buf.value == b""

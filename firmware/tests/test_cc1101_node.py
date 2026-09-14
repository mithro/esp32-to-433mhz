"""cc1101_node.py — Tasmota console line parser (spec §6.2 USB phase 1)."""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
from cc1101_node import parse_console_line, iter_events, should_republish  # noqa: E402

SENSOR = '12:34:56.789 MQT: rtl_433/nodes/cc1101-welland-bench/events = {"model":"Fineoffset-WS69","id":174,"temperature_C":13.1}'
RESULT = '12:34:57.001 MQT: tele/cc1101-welland-bench/RESULT = {"RfReceived":{"Data":"0xC3FF3F","Bits":24,"Protocol":1,"Pulse":350}}'
LWT = '12:34:50 MQT: tele/cc1101-welland-bench/LWT = Online (retained)'
NOTS = 'MQT: stat/cc1101-welland-bench/RESULT = {"CcStatus":{"Mode":"remotes"}}'
NOISE = '12:34:56.000 CMD: CcStatus'
RAW = '00:00:01.000 MQT: tele/cc1101-welland-bench/CCRAW = {"Pulses":[350,-1050,350]}'


def test_parse_json_payload_with_timestamp():
    topic, payload, retained = parse_console_line(SENSOR)
    assert topic == "rtl_433/nodes/cc1101-welland-bench/events"
    assert payload == {"model": "Fineoffset-WS69", "id": 174, "temperature_C": 13.1} and retained is False


def test_parse_rfreceived_and_raw():
    assert parse_console_line(RESULT)[1]["RfReceived"]["Data"] == "0xC3FF3F"
    assert parse_console_line(RAW)[1] == {"Pulses": [350, -1050, 350]}


def test_parse_plain_payload_and_retained_flag():
    topic, payload, retained = parse_console_line(LWT)
    assert topic == "tele/cc1101-welland-bench/LWT" and payload == "Online" and retained is True


def test_parse_without_timestamp_and_reject_noise():
    assert parse_console_line(NOTS)[0] == "stat/cc1101-welland-bench/RESULT"
    assert parse_console_line(NOISE) is None
    assert parse_console_line("") is None


def test_iter_events_skips_non_mqt_lines_and_bad_json():
    lines = [NOISE, SENSOR, '12:00:00.000 MQT: tele/x/RESULT = {not json', LWT]
    out = list(iter_events(lines))
    assert [t for t, _, _ in out] == ["rtl_433/nodes/cc1101-welland-bench/events", "tele/x/RESULT", "tele/cc1101-welland-bench/LWT"]
    assert out[1][1] == "{not json"          # unparsable JSON is passed through as a string


DEFAULT_PREFIXES = ["rtl_433/nodes/", "tele/"]


def test_should_republish_matches_a_configured_prefix():
    assert should_republish("rtl_433/nodes/cc1101-welland-bench/events", DEFAULT_PREFIXES) is True


def test_should_republish_rejects_lwt_even_with_matching_prefix():
    assert should_republish("tele/cc1101-welland-bench/LWT", DEFAULT_PREFIXES) is False


def test_should_republish_rejects_unmatched_prefix():
    assert should_republish("stat/cc1101-welland-bench/RESULT", DEFAULT_PREFIXES) is False

"""Aggregator dedup/coverage behaviour — spec §7.2 / §7.6 scenarios 1,2,3,5,10,16."""
import json
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
from rf433_aggregate import Aggregator, Publish, event_key, dedup_key, code_key, identity  # noqa: E402

SITE = "welland"


def agg(**kw):
    return Aggregator(SITE, **kw)


def ws69(receiver, rssi=-85.5, temp=13.1, t="2026-08-22 10:00:00"):
    return json.dumps({"time": t, "model": "Fineoffset-WS69", "id": 174, "battery_ok": 1,
                       "temperature_C": temp, "humidity": 82, "rssi": rssi, "mic": "CRC",
                       "receiver": receiver, "repeats": 1})


def ws85(receiver, rssi=-70.0):
    return json.dumps({"time": "x", "model": "Fineoffset-WS85", "id": 10222, "wind_avg_m_s": 0.3,
                       "rssi": rssi, "mic": "CRC", "receiver": receiver})


def grey(receiver, code="c3ff3f8", rssi=-61, short=201, long=731):
    return json.dumps({"time": "x", "model": "OOK-PWM", "family": "standard", "bits": 25, "code": code,
                       "short_us": short, "long_us": long, "gap_us": 7300, "rssi": rssi, "receiver": receiver})


def topic_events(node):
    return "rtl_433/nodes/%s/events" % node


def by_topic(pubs, topic):
    return [p for p in pubs if p.topic == topic]


def test_event_key_strips_per_receiver_fields():
    a = json.loads(ws69("n1", rssi=-80, t="t1"))
    b = json.loads(ws69("n2", rssi=-90, t="t2"))
    assert event_key(a) == event_key(b)
    c = json.loads(ws69("n1", temp=13.2))
    assert event_key(a) != event_key(c)


def test_code_key_first_24_bits():
    assert code_key("c3ff3f8") == "rf:c3ff3f"          # 25-bit left-aligned decoder code
    assert code_key("0xC3FF3F") == "rf:c3ff3f"         # Sonoff bridge 24-bit Data
    assert code_key("C3FF3F", 24) == "rf:c3ff3f"
    assert code_key("fa07c", 20) == "rf:fa07c"          # short codes unchanged
    assert dedup_key(json.loads(grey("n1"))) == "rf:c3ff3f"
    assert dedup_key(json.loads(grey("n2", short=199, long=734))) == "rf:c3ff3f"


def test_code_key_accepts_ints():
    assert code_key(0xC3FF3F) == "rf:c3ff3f"
    assert code_key(0xC3FF3F8, 28) == "rf:c3ff3f"      # 25-bit code written left-aligned as an int
    assert code_key(0x0FF3F8, 24) == "rf:0ff3f8"       # leading zero restored from bits
    assert code_key(0xFA07C, 20) == "rf:fa07c"


def test_code_key_never_raises_on_any_input():
    assert code_key("zz") == "rf:invalid" and code_key("") == "rf:invalid"
    # `bits` may arrive as any JSON value off an untrusted MQTT payload; non-int values
    # must be coerced to None (i.e. ignored) rather than raising out of code_key().
    assert code_key("0xC3FF3F", "24") == "rf:c3ff3f"
    assert code_key("c3ff3f8", None) == "rf:c3ff3f"
    assert code_key("c3ff3f8", {"x": 1}) == "rf:c3ff3f"


def test_secplus_key_uses_id_and_rolling():
    e = {"model": "Secplus-v2", "id": 1234, "button": 1, "rolling": 777, "rssi": -50, "receiver": "a"}
    assert dedup_key(e) == "secplus:1234:777"
    assert identity(e) == ("Secplus-v2", "1234")


def test_scenario_1_two_nodes_same_burst_one_event_plus_coverage():
    a = agg()
    p1 = a.on_message(topic_events("cc1101-welland-carport"), ws69("cc1101-welland-carport", -61), now=100.000)
    p2 = a.on_message(topic_events("cc1101-welland-shed"), ws69("cc1101-welland-shed", -84), now=100.004)
    ev1 = by_topic(p1, a.t_events()); ev2 = by_topic(p2, a.t_events())
    assert len(ev1) == 1 and ev2 == []
    out = json.loads(ev1[0].payload)
    assert out["model"] == "Fineoffset-WS69" and out["id"] == 174 and out["receiver"] == "cc1101-welland-carport"
    cov = by_topic(p2, a.t_coverage("Fineoffset-WS69", "174"))
    assert len(cov) == 1 and cov[0].retain is True
    c = json.loads(cov[0].payload)
    assert c["receivers"] == ["cc1101-welland-carport", "cc1101-welland-shed"]
    assert c["rssi_by_receiver"] == {"cc1101-welland-carport": -61, "cc1101-welland-shed": -84}
    assert c["best_receiver"] == "cc1101-welland-carport"
    assert c["last"].startswith("1970-01-01T00:01:40")     # iso of now=100 s epoch (UTC)


def test_scenario_2_node_plus_sdr_100ms_later():
    a = agg()
    a.on_message(topic_events("cc1101-monarto-shed"), ws69("cc1101-monarto-shed", -70), now=5.0)
    p = a.on_message(topic_events("rtlsdr-monarto"), ws69("rtlsdr-monarto", -12), now=5.1)
    assert by_topic(p, a.t_events()) == []
    c = json.loads(by_topic(p, a.t_coverage("Fineoffset-WS69", "174"))[0].payload)
    assert set(c["receivers"]) == {"cc1101-monarto-shed", "rtlsdr-monarto"}


def test_scenario_3_identical_readings_16s_apart_are_two_events():
    a = agg()
    p1 = a.on_message(topic_events("n1"), ws69("n1", t="a"), now=0.0)
    p2 = a.on_message(topic_events("n1"), ws69("n1", t="b"), now=16.0)
    assert len(by_topic(p1, a.t_events())) == 1 and len(by_topic(p2, a.t_events())) == 1


def test_scenario_5_held_button_publishes_once_per_window():
    a = agg()
    pubs = [a.on_message(topic_events(n), grey(n), now=t) for t in (0.0, 1.0, 2.0, 3.0) for n in ("n1", "n2")]
    published_at = [i // 2 for i, p in enumerate(pubs) if by_topic(p, a.t_events())]
    assert published_at == [0, 2]                         # t=0 and t=2 (window 2 s from first sighting)


def test_scenario_10_two_remotes_same_code_within_window_one_event():
    a = agg()
    p1 = a.on_message(topic_events("n1"), grey("n1"), now=0.0)
    p2 = a.on_message(topic_events("n2"), grey("n2", short=205), now=0.5)
    assert len(by_topic(p1, a.t_events())) == 1 and by_topic(p2, a.t_events()) == []


def test_scenario_16_ws85_two_nodes_one_event():
    a = agg()
    p1 = a.on_message(topic_events("n1"), ws85("n1"), now=0.0)
    p2 = a.on_message(topic_events("n2"), ws85("n2"), now=0.2)
    assert len(by_topic(p1, a.t_events())) == 1 and by_topic(p2, a.t_events()) == []
    p3 = a.on_message(topic_events("n1"), ws85("n1"), now=8.0)
    assert len(by_topic(p3, a.t_events())) == 1


def test_per_model_window_override():
    a = agg(window_by_model={"Fineoffset-WS69": 0.5})
    a.on_message(topic_events("n1"), ws69("n1"), now=0.0)
    p = a.on_message(topic_events("n2"), ws69("n2"), now=0.6)
    assert len(by_topic(p, a.t_events())) == 1            # window expired for this model


def test_unknown_and_malformed_messages_are_ignored():
    a = agg()
    assert a.on_message("tele/cc1101-welland-carport/LWT", "Online", now=0.0) == []
    assert a.on_message("tele/cc1101-welland-carport/SENSOR", '{"CC1101":{"Mode":"remotes"}}', now=0.0) == []
    assert a.on_message(topic_events("n1"), "not json", now=0.0) == []


def test_on_event_ignores_events_without_model_code_or_id():
    a = agg()
    assert a.on_message(topic_events("n1"), "{}", now=0.0) == []
    assert a.on_message(topic_events("n1"), json.dumps({"time": "x"}), now=0.0) == []


def test_scenario_2b_sdr_protocol_field_does_not_break_dedup():
    # Same as scenario 2, but the SDR's payload carries an extra "protocol" field (and a
    # "mod" already-stripped field) that the node's own event does not.
    a = agg()
    a.on_message(topic_events("cc1101-monarto-shed"), ws69("cc1101-monarto-shed", -70), now=5.0)
    sdr_ev = json.loads(ws69("rtlsdr-monarto", -12))
    sdr_ev["protocol"] = 78
    sdr_ev["mod"] = "FSK"
    p = a.on_message(topic_events("rtlsdr-monarto"), json.dumps(sdr_ev), now=5.1)
    assert by_topic(p, a.t_events()) == []
    c = json.loads(by_topic(p, a.t_coverage("Fineoffset-WS69", "174"))[0].payload)
    assert set(c["receivers"]) == {"cc1101-monarto-shed", "rtlsdr-monarto"}


def test_coverage_topic_is_sanitised():
    a = agg()
    ev = json.dumps({"time": "x", "model": "a/b#", "id": "+", "rssi": -50, "receiver": "n1"})
    p = a.on_message(topic_events("n1"), ev, now=0.0)
    topics = [pub.topic for pub in p]
    assert "rtl_433/welland/coverage/a_b_/_" in topics
    assert all("+" not in t and "#" not in t for t in topics)


def test_own_secplus_ids_accepts_hex_strings():
    a = Aggregator(SITE, own_secplus_ids=["0x1234"])
    assert 0x1234 in a.own_secplus_ids

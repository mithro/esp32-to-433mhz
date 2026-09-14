"""RfReceived compatibility, controlled-code annotation, forwarding — scenarios 4, 8."""
import json
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
from rf433_aggregate import Aggregator  # noqa: E402

SITE = "welland"


def rf(data="0xC3FF3F", bits=24, rssi=-61):
    return json.dumps({"RfReceived": {"Data": data, "Bits": bits, "Protocol": 1, "Pulse": 350, "RSSI": rssi}})


def grey(receiver, code="c3ff3f8"):
    return json.dumps({"time": "x", "model": "OOK-PWM", "family": "standard", "bits": 25, "code": code,
                       "short_us": 201, "long_us": 731, "gap_us": 7300, "rssi": -61, "receiver": receiver})


def by_topic(pubs, topic):
    return [p for p in pubs if p.topic == topic]


def test_scenario_4_three_nodes_one_event_and_one_rfreceived():
    a = Aggregator(SITE)
    pubs = []
    for i, n in enumerate(("cc1101-welland-carport", "cc1101-welland-shed", "cc1101-welland-bench")):
        pubs += a.on_message("rtl_433/nodes/%s/events" % n, grey(n), now=0.01 * i)
        pubs += a.on_message("tele/%s/RESULT" % n, rf(), now=0.01 * i + 0.005)
    assert len(by_topic(pubs, a.t_events())) == 1
    res = by_topic(pubs, a.t_result())
    assert len(res) == 1
    r = json.loads(res[0].payload)
    assert r["RfReceived"]["Data"] == "0xC3FF3F" and r["RfReceived"]["Bits"] == 24
    cov = by_topic(pubs, a.t_coverage("RfReceived", "c3ff3f"))
    assert len(cov) == 3 and json.loads(cov[-1].payload)["receivers"] == sorted(
        ["cc1101-welland-carport", "cc1101-welland-shed", "cc1101-welland-bench"])


def test_scenario_8_controlled_code_is_annotated_not_suppressed():
    a = Aggregator(SITE, controlled_codes=["c3ff3f8", "c3ffff8"])
    p = a.on_message("rtl_433/nodes/n1/events", grey("n1"), now=0.0)
    ev = json.loads(by_topic(p, a.t_events())[0].payload)
    assert ev["controlled"] is True
    p = a.on_message("tele/cc1101-welland-shed/RESULT", rf(), now=0.1)
    r = json.loads(by_topic(p, a.t_result())[0].payload)
    assert r["RfReceived"]["controlled"] is True
    p = a.on_message("rtl_433/nodes/n1/events", grey("n1", code="5596fc8"), now=0.2)
    assert "controlled" not in json.loads(by_topic(p, a.t_events())[0].payload)


def test_result_without_rfreceived_is_ignored_and_non_node_topics_too():
    a = Aggregator(SITE)
    assert a.on_message("tele/cc1101-welland-shed/RESULT", '{"POWER":"ON"}', now=0.0) == []
    assert a.on_message("tele/tasmota-E7041B-1051/RESULT", rf(), now=0.0) == []   # not a cc1101- node


def test_forward_to_designated_transmitter():
    a = Aggregator(SITE, designated_transmitter="cc1101-welland-carport")
    p = a.on_message("rf433/welland/cmnd/SecplusSend", "open", now=0.0)
    assert p == [type(p[0])("cmnd/cc1101-welland-carport/SecplusSend", "open", False)]
    assert Aggregator(SITE).on_message("rf433/welland/cmnd/SecplusSend", "open", now=0.0) == []
    assert a.on_message("rf433/monarto/cmnd/SecplusSend", "open", now=0.0) == []      # other site


def test_on_result_with_bits_as_string_does_not_raise():
    # Bits may arrive as a JSON string (e.g. "24") off some bridges; must not raise and
    # must still key the same as an int Bits value.
    a = Aggregator(SITE)
    payload = json.dumps({"RfReceived": {"Data": "0xC3FF3F", "Bits": "24"}})
    p = a.on_message("tele/cc1101-welland-shed/RESULT", payload, now=0.0)
    assert len(by_topic(p, a.t_result())) == 1


def test_controlled_mark_does_not_leak_into_first_event():
    a = Aggregator(SITE, controlled_codes=["c3ff3f8"])
    a.on_message("tele/cc1101-welland-shed/RESULT", rf(), now=0.0)
    s = next(iter(a.seen.values()))
    assert "controlled" not in s.first_event["RfReceived"]

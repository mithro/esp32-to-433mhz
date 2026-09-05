"""Own-transmission echo suppression — scenarios 6, 7, 9, 11, 12."""
import json
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
from rf433_aggregate import Aggregator  # noqa: E402

SITE = "welland"


def sec(receiver, id_=4660, rolling=1000, rssi=-55):
    return json.dumps({"time": "x", "model": "Secplus-v2", "id": id_, "button": 1, "rolling": rolling,
                       "rssi": rssi, "receiver": receiver})


def grey(receiver, code="c3ff3f8"):
    return json.dumps({"time": "x", "model": "OOK-PWM", "family": "standard", "bits": 25, "code": code,
                       "short_us": 201, "long_us": 731, "gap_us": 7300, "rssi": -61, "receiver": receiver})


def rf(data="0xC3FF3F"):
    return json.dumps({"RfReceived": {"Data": data, "Bits": 24, "Protocol": 1, "Pulse": 350, "RSSI": -61}})


def by_topic(pubs, topic):
    return [p for p in pubs if p.topic == topic]


def test_scenario_6_secplus_send_heard_by_three_nodes_is_echo():
    a = Aggregator(SITE)
    tx = json.dumps({"model": "Secplus-v2", "id": 4660, "button": 1, "rolling": 1000})
    assert a.on_message("rtl_433/nodes/cc1101-welland-carport/tx", tx, now=0.0) == []
    pubs = []
    for n in ("cc1101-welland-shed", "cc1101-welland-bench", "cc1101-welland-north"):
        pubs += a.on_message("rtl_433/nodes/%s/events" % n, sec(n), now=0.06)
    assert by_topic(pubs, a.t_events()) == []
    echoes = by_topic(pubs, a.t_echo())
    assert len(echoes) == 3 and all(json.loads(e.payload)["echo_of"] == "cc1101-welland-carport" for e in echoes)
    # the NEXT press (rolling+1), not announced, is a real event
    p = a.on_message("rtl_433/nodes/cc1101-welland-shed/events", sec("cc1101-welland-shed", rolling=1001), now=5.0)
    assert len(by_topic(p, a.t_events())) == 1


def test_scenario_7_bridge_rfsend_heard_by_two_nodes_is_echo():
    a = Aggregator(SITE)
    a.on_message("cmnd/tasmota-E7041B-1051/RfSend", '{"Data":"0xC3FF3F","Bits":24,"Protocol":1,"Pulse":350}', now=0.0)
    p1 = a.on_message("rtl_433/nodes/n1/events", grey("n1"), now=0.2)
    p2 = a.on_message("tele/cc1101-welland-shed/RESULT", rf(), now=0.25)
    assert by_topic(p1, a.t_events()) == [] and by_topic(p2, a.t_result()) == []
    assert json.loads(by_topic(p1, a.t_echo())[0].payload)["echo_of"] == "tasmota-E7041B-1051"
    assert json.loads(by_topic(p2, a.t_echo())[0].payload)["echo_of"] == "tasmota-E7041B-1051"


def test_bridge_rfkey_uses_config_map_and_expires():
    a = Aggregator(SITE, bridge_rfkeys={"tasmota-E7041B-1051": {"3": "c3ff3f8"}}, tx_ledger_s=3.0)
    a.on_message("cmnd/tasmota-E7041B-1051/RfKey3", "", now=0.0)
    assert by_topic(a.on_message("rtl_433/nodes/n1/events", grey("n1"), now=0.5), a.t_echo())
    a2 = Aggregator(SITE, bridge_rfkeys={"tasmota-E7041B-1051": {"3": "c3ff3f8"}}, tx_ledger_s=3.0)
    a2.on_message("cmnd/tasmota-E7041B-1051/RfKey3", "", now=0.0)
    assert by_topic(a2.on_message("rtl_433/nodes/n1/events", grey("n1"), now=3.5), a2.t_events())   # ledger expired
    assert a2.on_message("cmnd/tasmota-E7041B-1051/RfKey9", "", now=0.0) == []                        # unknown key


def test_scenario_9_late_tx_announcement_publishes_correction_and_flags_coverage():
    a = Aggregator(SITE)
    p1 = a.on_message("rtl_433/nodes/cc1101-welland-shed/events", sec("cc1101-welland-shed"), now=0.0)
    assert len(by_topic(p1, a.t_events())) == 1
    tx = json.dumps({"model": "Secplus-v2", "id": 4660, "button": 1, "rolling": 1000})
    p2 = a.on_message("rtl_433/nodes/cc1101-welland-carport/tx", tx, now=0.4)
    e = json.loads(by_topic(p2, a.t_echo())[0].payload)
    assert e["late"] is True and e["echo_of"] == "cc1101-welland-carport" and e["id"] == 4660
    c = json.loads(by_topic(p2, a.t_coverage("Secplus-v2", "4660"))[0].payload)
    assert c["echo_suspect"] is True
    # and a third node hearing it afterwards is an echo, not a second event
    p3 = a.on_message("rtl_433/nodes/cc1101-welland-north/events", sec("cc1101-welland-north"), now=0.5)
    assert by_topic(p3, a.t_events()) == [] and by_topic(p3, a.t_echo())


def test_late_tx_corrects_rfreceived_sighting_too():
    a = Aggregator(SITE)
    p1 = a.on_message("tele/cc1101-welland-shed/RESULT", rf(), now=0.0)
    assert len(by_topic(p1, a.t_result())) == 1
    p2 = a.on_message("cmnd/tasmota-E7041B-1051/RfSend",
                      '{"Data":"0xC3FF3F","Bits":24,"Protocol":1}', now=0.4)
    echoes = by_topic(p2, a.t_echo())
    assert len(echoes) == 1
    e = json.loads(echoes[0].payload)
    assert e["late"] is True and e["echo_of"] == "tasmota-E7041B-1051" and "RfReceived" in e
    c = json.loads(by_topic(p2, a.t_coverage("RfReceived", "c3ff3f"))[0].payload)
    assert c["echo_suspect"] is True


def test_own_secplus_id_is_always_echo():
    a = Aggregator(SITE, own_secplus_ids=[4660])
    p = a.on_message("rtl_433/nodes/n1/events", sec("n1"), now=0.0)
    assert by_topic(p, a.t_events()) == [] and json.loads(by_topic(p, a.t_echo())[0].payload)["echo_of"] == "own-secplus-id"


def test_scenario_11_foreign_secplus_is_a_normal_event():
    a = Aggregator(SITE, own_secplus_ids=[4660])
    p = a.on_message("rtl_433/nodes/n1/events", sec("n1", id_=99999), now=0.0)
    assert len(by_topic(p, a.t_events())) == 1


def test_scenario_12_lwt_does_not_disturb_dedup():
    a = Aggregator(SITE)
    a.on_message("rtl_433/nodes/n1/events", grey("n1"), now=0.0)
    assert a.on_message("tele/cc1101-welland-shed/LWT", "Offline", now=0.1) == []
    assert by_topic(a.on_message("rtl_433/nodes/n2/events", grey("n2"), now=0.2), a.t_events()) == []


def test_tx_rfsend_form_and_malformed_tx():
    a = Aggregator(SITE)
    a.on_message("rtl_433/nodes/cc1101-welland-carport/tx", '{"Data":"0xC3FF3F","Bits":24,"Protocol":1}', now=0.0)
    assert by_topic(a.on_message("rtl_433/nodes/n1/events", grey("n1"), now=0.1), a.t_echo())
    assert a.on_message("rtl_433/nodes/cc1101-welland-carport/tx", "garbage", now=0.0) == []


def test_malformed_bridge_rfsend_is_ignored_not_crash():
    a = Aggregator(SITE)
    for bad in ("x", "xxxx", "c3xf3f", "", "   ", "{not json"):
        assert a.on_message("cmnd/tasmota-E7041B-1051/RfSend", bad, now=0.0) == []
    # bare hex (with or without 0x) still registers
    a.on_message("cmnd/tasmota-E7041B-1051/RfSend", "0xC3FF3F", now=0.0)
    assert by_topic(a.on_message("rtl_433/nodes/n1/events", grey("n1"), now=0.1), a.t_echo())


def test_rfcode_hash_prefixed_hex_is_echo():
    a = Aggregator(SITE)
    a.on_message("cmnd/tasmota-E7041B-1051/RfCode", "#C3FF3F", now=0.0)
    assert by_topic(a.on_message("rtl_433/nodes/n1/events", grey("n1"), now=0.1), a.t_echo())


def test_bare_rfsend_decimal_form_is_also_registered():
    # Tasmota's bare RfSend/RfCode form is decimal. 12844863 decimal == 0xC3FF3F, the code
    # `grey()` reports (first 24 bits of the 25-bit "c3ff3f8" left-aligned code).
    a = Aggregator(SITE)
    a.on_message("cmnd/tasmota-E7041B-1051/RfSend", "12844863", now=0.0)
    assert by_topic(a.on_message("rtl_433/nodes/n1/events", grey("n1"), now=0.1), a.t_echo())

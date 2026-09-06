"""Config loading, subscriptions and offline replay for the aggregator runner."""
import json
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
from rf433_aggregate import load_config, build_aggregator, subscriptions, replay  # noqa: E402

TOML = """
site = "welland"
[mqtt]
host = "mqtt.example"
port = 1883
username = "u"
password = "p"
[dedup]
window_s = 2.0
[dedup.window_by_model]
"Secplus-v2" = 3.0
[tx]
ledger_s = 3.0
designated_transmitter = "cc1101-welland-carport"
[echo]
own_secplus_ids = [4660]
[controlled]
codes = ["c3ff3f8", "c3ffff8"]
[bridge_rfkeys."tasmota-E7041B-1051"]
"1" = "c3ff3f8"
"""


def test_load_config_and_build(tmp_path):
    p = tmp_path / "a.toml"
    p.write_text(TOML)
    cfg = load_config(str(p))
    assert cfg["site"] == "welland" and cfg["mqtt"]["host"] == "mqtt.example"
    a = build_aggregator(cfg)
    assert a.site == "welland" and a.window_by_model == {"Secplus-v2": 3.0}
    assert a.designated_transmitter == "cc1101-welland-carport" and 4660 in a.own_secplus_ids
    assert "rf:c3ff3f" in a.controlled and a.bridge_rfkeys == {"tasmota-E7041B-1051": {"1": "c3ff3f8"}}


def test_subscriptions_cover_every_input_topic():
    subs = subscriptions("welland")
    for t in ("rtl_433/nodes/+/events", "rtl_433/nodes/+/tx", "tele/+/RESULT", "cmnd/+/RfSend",
              "cmnd/+/RfCode", "cmnd/+/RfKey1", "cmnd/+/RfKey16", "rf433/welland/cmnd/+"):
        assert t in subs


def test_replay_produces_expected_publishes(tmp_path):
    p = tmp_path / "a.toml"
    p.write_text(TOML)
    a = build_aggregator(load_config(str(p)))
    ev = {"time": "x", "model": "Fineoffset-WS69", "id": 174, "temperature_C": 13.1, "rssi": -80, "receiver": "n1"}
    lines = [json.dumps({"ts": 0.0, "topic": "rtl_433/nodes/n1/events", "payload": json.dumps(ev)}),
             json.dumps({"ts": 0.1, "topic": "rtl_433/nodes/n2/events", "payload": json.dumps(dict(ev, receiver="n2", rssi=-70))})]
    pubs = replay(a, lines)
    assert [p.topic for p in pubs] == ["rtl_433/welland/events", "rtl_433/welland/coverage/Fineoffset-WS69/174",
                                       "rtl_433/welland/coverage/Fineoffset-WS69/174"]

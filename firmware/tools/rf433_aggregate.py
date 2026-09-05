#!/usr/bin/env python3
"""rf433 per-site aggregator: N receivers in, one HA-facing event stream out.

SPDX-License-Identifier: Apache-2.0

Design (spec docs/superpowers/specs/2026-08-20-esp32c3-cc1101-tasmota-design.md §7,
scenarios in protocols/rf-aggregation.md):

  rtl_433/nodes/<node>/events ─┐
  tele/<cc1101-node>/RESULT   ─┼─► Aggregator ─► rtl_433/<site>/events        (HA autodiscovery)
  rtl_433/nodes/<node>/tx     ─┤                 tele/rf433-<site>/RESULT     (RfReceived compat)
  cmnd/<bridge>/RfSend|RfKey  ─┤                 rtl_433/<site>/echo          (our own TX, diagnostics)
  rf433/<site>/cmnd/<Command> ─┘                 rtl_433/<site>/coverage/<model>/<id>  (retained)
                                                 cmnd/<designated>/<Command>  (forwarded)

The Aggregator class is pure: on_message(topic, payload, now) -> [Publish]. The
clock is always passed in; the MQTT runner (Task 4) passes time.time().

Run:   uv run --with paho-mqtt hardware/devices/esp32c3-cc1101-node/tools/rf433_aggregate.py --config rf433_aggregate.toml
Test:  uv run --with pytest pytest hardware/devices/esp32c3-cc1101-node/tests -k aggregate
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

# Per-receiver / per-measurement fields that must not distinguish two views of one frame.
STRIP_FIELDS = frozenset({
    "time", "rssi", "snr", "noise", "lqi", "freq", "freq1", "freq2", "mod", "protocol",
    "receiver", "repeats", "short_us", "long_us", "gap_us", "Pulse",
})


@dataclass
class Publish:
    topic: str
    payload: str
    retain: bool = False


@dataclass
class Sighting:
    first_ts: float
    first_event: dict
    identity: tuple
    receivers: dict = field(default_factory=dict)   # receiver -> rssi (or None)
    flagged: bool = False


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def event_key(ev: dict) -> str:
    """Canonical key: every field except the per-receiver ones, sorted."""
    return json.dumps({k: v for k, v in ev.items() if k not in STRIP_FIELDS},
                      sort_keys=True, separators=(",", ":"))


def code_key(data, bits=None) -> str:
    """Key for an OOK code. Codes are compared on their FIRST 24 BITS: the Sonoff/Tasmota
    bridge reports 24-bit Data ('0xC3FF3F'), our OOK-PWM decoder reports 25 bits left-aligned
    in 7 hex digits ('c3ff3f8' -> first 24 bits 'c3ff3f'). The hex string's width is the
    alignment; `bits` only matters when the value was written without leading zeros.
    Codes shorter than 24 bits are kept as written."""
    if isinstance(data, int):
        s = "%x" % data
    else:
        s = str(data).strip().lower()
        if s.startswith("#"):
            s = s[1:]
        if s.startswith("0x"):
            s = s[2:]
    if not s:
        # Empty string is not a real code either (e.g. a blank RfSend payload after
        # stripping "0x"). Treat it the same as invalid hex, below.
        return "rf:invalid"
    bits = _as_int(bits)                              # bits may be any JSON value (str, None, dict, ...)
    width = len(s) * 4
    if bits is not None and bits > width:            # written without leading zeros
        s = s.rjust((bits + 3) // 4, "0")
        width = len(s) * 4
    try:
        value = int(s, 16)
    except ValueError:
        # Not valid hex (e.g. "zz"). "rf:invalid" never matches a real ledger/sighting
        # key, so this degrades to "no match" everywhere instead of raising out of
        # on_message() for a bad payload from an untrusted MQTT topic.
        return "rf:invalid"
    if width > 24:
        value >>= width - 24
    if width >= 24:
        return "rf:%06x" % value
    return "rf:%s" % (s.lstrip("0") or "0")


def dedup_key(ev: dict) -> str:
    model = str(ev.get("model", ""))
    if "code" in ev:                                   # OOK-PWM decoder output
        return code_key(ev["code"], ev.get("bits"))
    if model.startswith("Secplus"):
        return "secplus:%s:%s" % (ev.get("id"), ev.get("rolling"))
    return event_key(ev)


def identity(ev: dict) -> tuple:
    model = str(ev.get("model", "unknown"))
    if "code" in ev and "id" not in ev:
        return (model, code_key(ev["code"], ev.get("bits"))[3:])
    return (model, str(ev.get("id", "unknown")))


class Aggregator:
    def __init__(self, site, *, window_s=2.0, window_by_model=None, tx_ledger_s=3.0,
                 own_secplus_ids=(), controlled_codes=(), designated_transmitter=None,
                 bridge_rfkeys=None, node_topic_prefix="cc1101-"):
        self.site = site
        self.window_s = float(window_s)
        self.window_by_model = dict(window_by_model or {})
        self.tx_ledger_s = float(tx_ledger_s)
        self.own_secplus_ids = {int(i, 0) if isinstance(i, str) else int(i) for i in own_secplus_ids}
        self.controlled = {code_key(c) for c in controlled_codes}
        self.designated_transmitter = designated_transmitter
        self.bridge_rfkeys = {b: {str(k): v for k, v in m.items()} for b, m in (bridge_rfkeys or {}).items()}
        self.node_topic_prefix = node_topic_prefix
        self.seen: dict = {}
        self.tx_ledger: dict = {}

    # ── topics ────────────────────────────────────────────────────────
    def t_events(self):
        return "rtl_433/%s/events" % self.site

    def t_echo(self):
        return "rtl_433/%s/echo" % self.site

    def t_result(self):
        return "tele/rf433-%s/RESULT" % self.site

    def t_coverage(self, model, ident):
        # model/ident come from untrusted receiver payloads; sanitise so they can't inject
        # MQTT wildcard chars ("+", "#") or extra topic levels ("/") into the retained topic.
        safe_model = re.sub(r"[^A-Za-z0-9._-]", "_", str(model))
        safe_ident = re.sub(r"[^A-Za-z0-9._-]", "_", str(ident))
        return "rtl_433/%s/coverage/%s/%s" % (self.site, safe_model, safe_ident)

    # ── dispatch ──────────────────────────────────────────────────────
    def on_message(self, topic: str, payload: str, now: float) -> list:
        self._expire(now)
        p = topic.split("/")
        if len(p) == 4 and p[0] == "rtl_433" and p[1] == "nodes" and p[3] == "events":
            return self._on_event(p[2], payload, now)
        if len(p) == 4 and p[0] == "rtl_433" and p[1] == "nodes" and p[3] == "tx":
            return self._on_tx(p[2], payload, now)
        if len(p) == 3 and p[0] == "tele" and p[2] == "RESULT" and p[1].startswith(self.node_topic_prefix):
            return self._on_result(p[1], payload, now)
        if len(p) == 3 and p[0] == "cmnd" and (p[2] in ("RfSend", "RfCode") or p[2].startswith("RfKey")):
            return self._on_bridge_cmd(p[1], p[2], payload, now)
        if len(p) == 4 and p[0] == "rf433" and p[1] == self.site and p[2] == "cmnd":
            return self._on_forward(p[3], payload)
        return []

    # ── helpers ───────────────────────────────────────────────────────
    def _window(self, model: str) -> float:
        return float(self.window_by_model.get(model, self.window_s))

    def _expire(self, now: float) -> None:
        for k in [k for k, s in self.seen.items() if now - s.first_ts >= self._window(s.identity[0])]:
            del self.seen[k]
        for k in [k for k, (ts, _) in self.tx_ledger.items() if now - ts >= self.tx_ledger_s]:
            del self.tx_ledger[k]

    @staticmethod
    def _json(payload: str):
        try:
            obj = json.loads(payload)
        except (ValueError, TypeError):
            return None
        return obj if isinstance(obj, dict) else None

    def _coverage_update(self, s: Sighting, now: float) -> Publish:
        model, ident = s.identity
        best = None
        for r, rssi in s.receivers.items():
            if best is None or (rssi is not None and (best[1] is None or rssi > best[1])):
                best = (r, rssi)
        rec = {"model": model, "id": ident, "receivers": sorted(s.receivers),
               "rssi_by_receiver": dict(s.receivers), "best_receiver": best[0] if best else None,
               "last": iso(now)}
        if s.flagged:
            rec["echo_suspect"] = True
        return Publish(self.t_coverage(model, ident), json.dumps(rec, sort_keys=True), retain=True)

    def _echo(self, body: dict, source: str, extra=None) -> Publish:
        out = dict(body)
        out["echo_of"] = source
        if extra:
            out.update(extra)
        return Publish(self.t_echo(), json.dumps(out, sort_keys=True))

    # ── decoded events from receivers ─────────────────────────────────
    def _on_event(self, node: str, payload: str, now: float) -> list:
        ev = self._json(payload)
        if ev is None:
            return []
        if not any(k in ev for k in ("model", "code", "id")):
            return []      # not a decoded reading (e.g. a stray/empty JSON object) — nothing to key on
        ev.setdefault("receiver", node)
        key = dedup_key(ev)
        ident = identity(ev)
        return self._accept(key, ident, ev, node, ev.get("rssi"), now,
                            publish=lambda body: Publish(self.t_events(), json.dumps(body, sort_keys=True)),
                            echo_body=ev)

    def _accept(self, key, ident, body, node, rssi, now, publish, echo_body) -> list:
        """Shared dedup/echo path for decoded events and RfReceived results."""
        model = ident[0]
        if model.startswith("Secplus") and _as_int(body.get("id")) in self.own_secplus_ids:
            return [self._echo(echo_body, "own-secplus-id")]
        # RfReceived sightings are keyed with a "result-" prefix (Task 2) so they stay
        # distinct from the OOK-PWM decoder's own sighting of the same code; the TX
        # ledger itself is keyed unprefixed, so strip it for the lookup.
        ledger_key = key[len("result-"):] if key.startswith("result-") else key
        if ledger_key in self.tx_ledger:
            return [self._echo(echo_body, self.tx_ledger[ledger_key][1])]
        out = []
        s = self.seen.get(key)
        if s is None:
            s = Sighting(first_ts=now, first_event=copy.deepcopy(body), identity=ident, receivers={node: rssi})
            self.seen[key] = s
            pub = copy.deepcopy(body)
            # RfReceived keys carry "result-" prefix and are handled by the caller's publish function,
            # not by _is_controlled, so this check intentionally returns False for RESULT messages.
            if self._is_controlled(key):
                _mark_controlled(pub)
            out.append(publish(pub))
        else:
            s.receivers[node] = rssi
        out.append(self._coverage_update(s, now))
        return out

    def _is_controlled(self, key: str) -> bool:
        return key in self.controlled

    # Tasks 2–3 implement these:
    def _on_result(self, node_topic: str, payload: str, now: float) -> list:
        obj = self._json(payload)
        if obj is None or not isinstance(obj.get("RfReceived"), dict):
            return []
        r = obj["RfReceived"]
        if "Data" not in r:
            return []
        code_k = code_key(r["Data"], r.get("Bits"))
        # Use result-prefixed key to track separately from OOK-PWM events with same code
        key = "result-" + code_k
        ident = ("RfReceived", code_k[3:])
        body = {"RfReceived": dict(r)}
        # Check controlled status using the unwrapped code key
        is_controlled = code_k in self.controlled
        def publish_result(b):
            if is_controlled:
                _mark_controlled(b)
            return Publish(self.t_result(), json.dumps(b, sort_keys=True))
        return self._accept(key, ident, body, node_topic, r.get("RSSI"), now,
                            publish=publish_result, echo_body=body)

    def _register_tx(self, keys, source: str, now: float) -> list:
        out = []
        for key in keys:
            self.tx_ledger[key] = (now, source)
            # A "tx" (or bridge RfSend/RfKey) announcement can correct either a plain
            # event/OOK sighting (keyed as `key`) or an RfReceived sighting, which Task 2
            # keys with a "result-" prefix to keep it distinct from the OOK-PWM sighting.
            for seen_key in (key, "result-" + key):
                s = self.seen.get(seen_key)
                if s is not None and not s.flagged:      # late announcement: event already went out
                    s.flagged = True
                    out.append(self._echo(s.first_event, source, {"late": True}))
                    out.append(self._coverage_update(s, now))
        return out

    def _on_tx(self, node: str, payload: str, now: float) -> list:
        ev = self._json(payload)
        if ev is None:
            return []
        keys = set()
        if "Data" in ev:
            keys.add(code_key(ev["Data"], ev.get("Bits")))
        if "code" in ev:
            keys.add(code_key(ev["code"], ev.get("bits")))
        if "model" in ev or "id" in ev:
            keys.add(dedup_key(ev))
        return self._register_tx(keys, node, now)

    def _on_bridge_cmd(self, bridge: str, cmd: str, payload: str, now: float) -> list:
        if cmd in ("RfSend", "RfCode"):
            obj = self._json(payload)
            if obj is not None and "Data" in obj:
                return self._register_tx({code_key(obj["Data"], obj.get("Bits"))}, bridge, now)
            # Bare (non-JSON) payloads: Tasmota's `RfSend <hex>` form is hex, its bare
            # decimal form (as sent by some bridges) is decimal, and `RfCode` may carry a
            # leading "#" hex marker (e.g. "#C3FF3F"). An all-digit payload is ambiguous
            # between hex and decimal, so register both readings — the ledger is
            # suppression-only, so an extra key is harmless.
            text = payload.strip()
            if text.startswith("#"):
                text = text[1:]
            if re.fullmatch(r"[0-9]+", text):
                return self._register_tx({code_key(text), code_key(int(text))}, bridge, now)
            if re.fullmatch(r"(?:0x)?[0-9a-fA-F]+", text):
                return self._register_tx({code_key(text)}, bridge, now)
            return []
        n = cmd[len("RfKey"):]
        code = self.bridge_rfkeys.get(bridge, {}).get(n)
        if code is None:
            return []
        return self._register_tx({code_key(code)}, bridge, now)

    def _on_forward(self, command: str, payload: str) -> list:
        if not self.designated_transmitter:
            return []
        return [Publish("cmnd/%s/%s" % (self.designated_transmitter, command), payload)]


def _as_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _mark_controlled(pub: dict) -> None:
    if "RfReceived" in pub and isinstance(pub["RfReceived"], dict):
        pub["RfReceived"]["controlled"] = True
    else:
        pub["controlled"] = True


# ── config / runner ────────────────────────────────────────────────────

def load_config(path: str) -> dict:
    import tomllib
    with open(path, "rb") as f:
        return tomllib.load(f)


def build_aggregator(cfg: dict) -> Aggregator:
    d = cfg.get("dedup", {})
    t = cfg.get("tx", {})
    return Aggregator(cfg["site"],
                      window_s=d.get("window_s", 2.0),
                      window_by_model=d.get("window_by_model", {}),
                      tx_ledger_s=t.get("ledger_s", 3.0),
                      own_secplus_ids=cfg.get("echo", {}).get("own_secplus_ids", []),
                      controlled_codes=cfg.get("controlled", {}).get("codes", []),
                      designated_transmitter=t.get("designated_transmitter"),
                      bridge_rfkeys=cfg.get("bridge_rfkeys", {}),
                      node_topic_prefix=cfg.get("node_topic_prefix", "cc1101-"))


def subscriptions(site: str) -> list:
    return (["rtl_433/nodes/+/events", "rtl_433/nodes/+/tx", "tele/+/RESULT", "cmnd/+/RfSend", "cmnd/+/RfCode"]
            + ["cmnd/+/RfKey%d" % i for i in range(1, 17)]
            + ["rf433/%s/cmnd/+" % site])


def replay(agg: Aggregator, lines) -> list:
    """Offline: feed JSONL {"ts","topic","payload"} records through the aggregator."""
    out = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        # Note: replay should raise on errors (bad fixtures must be visible); only run() catches.
        out.extend(agg.on_message(rec["topic"], rec["payload"], float(rec["ts"])))
    return out


def run(cfg: dict) -> None:
    import paho.mqtt.client as mqtt          # lazy: tests don't need it
    agg = build_aggregator(cfg)
    m = cfg.get("mqtt", {})
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="rf433-aggregate-%s" % cfg["site"])
    if m.get("username"):
        client.username_pw_set(m["username"], m.get("password", ""))

    def on_connect(c, userdata, flags, reason_code, properties):
        print("connected:", reason_code, file=sys.stderr)
        for t in subscriptions(cfg["site"]):
            c.subscribe(t)

    def on_message(c, userdata, msg):
        payload = msg.payload.decode("utf-8", errors="replace")
        try:
            for p in agg.on_message(msg.topic, payload, time.time()):
                c.publish(p.topic, p.payload, retain=p.retain)
        except Exception as e:
            print("aggregator error on %s: %r" % (msg.topic, e), file=sys.stderr)

    client.on_connect = on_connect
    client.on_message = on_message
    # Use connect_async + loop_forever(retry_first_connection=True) so unreachable broker retries
    # instead of raising OSError (with blocking connect() the retry flag is ignored in paho 2.x)
    client.connect_async(m.get("host", "localhost"), int(m.get("port", 1883)), 60)
    client.loop_forever(retry_first_connection=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="rf433 per-site aggregator (dedup + echo suppression)")
    ap.add_argument("--config", required=True, help="TOML config (see rf433_aggregate.example.toml)")
    ap.add_argument("--replay", help="JSONL of {ts,topic,payload} to run offline; prints publishes and exits")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    if args.replay:
        with open(args.replay) as f:
            for p in replay(build_aggregator(cfg), f):
                print(json.dumps({"topic": p.topic, "retain": p.retain, "payload": json.loads(p.payload) if p.payload.startswith("{") else p.payload}))
        return 0
    run(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())

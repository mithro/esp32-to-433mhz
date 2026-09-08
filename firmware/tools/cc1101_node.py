#!/usr/bin/env python3
"""USB host tool for an ESP32-C3 + CC1101 Tasmota node (spec §6.2, USB phase 1).

SPDX-License-Identifier: Apache-2.0

The node's native-USB CDC port carries the Tasmota console. With `SerialLog 2`
every MQTT publish is echoed as `MQT: <topic> = <payload>`, so this tool turns
the console back into the same events the node would publish over WiFi, and
can re-publish them to the broker on the node's behalf (a WiFi-less bench node
then feeds the aggregator like any other receiver — scenario 15).

    uv run --with pyserial hardware/devices/esp32c3-cc1101-node/tools/cc1101_node.py --port /dev/radio-cc1101-node-XXXX --json
    uv run --with pyserial --with paho-mqtt …/cc1101_node.py --port … --republish --mqtt broker.example
    uv run --with pyserial …/cc1101_node.py --port … --cmd CcStatus

Phase 2 (spec §6.3, line-JSON console) adds a second framing to iter_events();
the event schema is unchanged.

--republish-filter is a comma list of topic prefixes (default "rtl_433/nodes/,tele/");
only topics matching one of these prefixes are republished to MQTT, and a topic ending
in "/LWT" is never republished (the bench node's own LWT would otherwise shadow the
real node's retained availability topic on the broker).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time

LINE_RE = re.compile(r"^(?:\d{2}:\d{2}:\d{2}(?:\.\d+)?\s+)?MQT: (\S+) = (.*)$")
RETAINED_SUFFIX = " (retained)"


def parse_console_line(line: str):
    """Tasmota console line -> (topic, payload, retained) or None for non-MQT lines.
    JSON payloads are decoded; anything else (incl. unparsable JSON) is the raw string."""
    m = LINE_RE.match(line.rstrip("\r\n"))
    if not m:
        return None
    topic, text = m.group(1), m.group(2)
    retained = text.endswith(RETAINED_SUFFIX)
    if retained:
        text = text[: -len(RETAINED_SUFFIX)]
    payload = text
    if text.startswith("{"):
        try:
            payload = json.loads(text)
        except ValueError:
            payload = text
    return topic, payload, retained


def iter_events(lines):
    for line in lines:
        ev = parse_console_line(line)
        if ev is not None:
            yield ev


def should_republish(topic: str, prefixes) -> bool:
    """True if `topic` should be republished to MQTT: it matches one of `prefixes`
    and is not a retained LWT status topic (own LWT would shadow the real node's)."""
    if topic.endswith("/LWT"):
        return False
    return any(topic.startswith(p) for p in prefixes)


class Node:
    """Serial wrapper; pyserial is imported lazily so the parser is importable without it."""

    def __init__(self, port: str, baud: int = 115200, timeout: float = 0.5):
        import serial
        self.ser = serial.Serial(port, baud, timeout=timeout)

    def send(self, cmd: str) -> None:
        self.ser.write((cmd.strip() + "\n").encode())

    def lines(self):
        while True:
            raw = self.ser.readline()
            if raw:
                yield raw.decode("utf-8", errors="replace")
            else:
                yield None            # timeout tick; lets callers implement deadlines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ESP32-C3+CC1101 node USB console -> events")
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--json", action="store_true", help="print each event as one JSON line {topic,payload,retained}")
    ap.add_argument("--cmd", help="send one Tasmota command, print what comes back for --cmd-timeout s, exit")
    ap.add_argument("--cmd-timeout", type=float, default=2.0)
    ap.add_argument("--republish", action="store_true", help="publish every parsed event to MQTT on its own topic")
    ap.add_argument("--mqtt", help="broker host[:port] for --republish")
    ap.add_argument("--mqtt-user")
    ap.add_argument("--mqtt-pass")
    ap.add_argument("--republish-filter", default="rtl_433/nodes/,tele/",
                    help="comma list of topic prefixes to republish (default: %(default)s); "
                         "a topic ending in /LWT is never republished")
    args = ap.parse_args(argv)
    prefixes = [p for p in args.republish_filter.split(",") if p]

    node = Node(args.port, args.baud)
    client = None
    if args.republish:
        if not args.mqtt:
            ap.error("--republish needs --mqtt host[:port]")
        import paho.mqtt.client as mqtt
        host, _, port = args.mqtt.partition(":")
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="cc1101-node-usb")
        if args.mqtt_user:
            client.username_pw_set(args.mqtt_user, args.mqtt_pass or "")
        client.connect(host, int(port or 1883), 60)
        client.loop_start()

    try:
        if args.cmd:
            node.send(args.cmd)
            deadline = time.monotonic() + args.cmd_timeout
            for line in node.lines():
                if time.monotonic() > deadline:
                    break
                if line:
                    print(line.rstrip())
            return 0

        for line in node.lines():
            if not line:
                continue
            ev = parse_console_line(line)
            if ev is None:
                if not args.json:
                    print(line.rstrip())
                continue
            topic, payload, retained = ev
            if args.json:
                print(json.dumps({"topic": topic, "payload": payload, "retained": retained}))
            else:
                print("%s = %s" % (topic, payload if isinstance(payload, str) else json.dumps(payload)))
            if client is not None and should_republish(topic, prefixes):
                client.publish(topic, payload if isinstance(payload, str) else json.dumps(payload), retain=retained)
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        if client is not None:
            client.loop_stop()
            client.disconnect()


if __name__ == "__main__":
    sys.exit(main())

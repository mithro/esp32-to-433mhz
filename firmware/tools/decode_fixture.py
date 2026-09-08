#!/usr/bin/env python3
"""Run the C decoders over a fixture file and print one JSON line per decode.

    uv run hardware/devices/esp32c3-cc1101-node/tools/decode_fixture.py fixtures/ws69_id174_2026-08-20.json
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tests"))
import decoderlib  # noqa: E402


def main():
    path = sys.argv[1]
    with open(path) as f:
        d = json.load(f)
    L = decoderlib.load()
    if d["format"] == "rf433-packets-v1":
        for pk in d["packets"]:
            rc, obj = decoderlib.decode_bytes(L, "fineoffset_decode", bytes.fromhex(pk["hex"]))
            print(json.dumps({"rc": rc, "rssi_dbm": pk.get("rssi_dbm"), "note": pk.get("note"), "decoded": obj}))
    elif d["format"] == "rf433-pulses-v1":
        for i, tr in enumerate(d["trains"]):
            for obj in decoderlib.decode_pulses(L, tr["us"]):
                print(json.dumps({"train": i, "t0_us": tr["t0_us"], "decoded": obj}))
    else:
        raise SystemExit("unknown fixture format %r" % d["format"])


if __name__ == "__main__":
    main()

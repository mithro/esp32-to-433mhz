"""FSK weather-RX framing: infinite-length FIFO drain + family dispatch.

Proves the ONE Fine Offset FSK config (CC1101 infinite packet-length mode, preset
PKTCTRL0 = 0x02) receives every frame length -- WH51 (14 B), WS69 (25 B), WS85
(28 B) -- from a single simulated RX FIFO drain. The C harness (radio_host
"weather_drain") scripts the FakeBus RX FIFO with a frame at the head plus trailing
demodulated noise (as arrives on-air in infinite mode) and runs the exact
cc_weather_drain() used by the firmware; this test asserts the dispatch by family
byte and that the trailing noise is ignored.

Ground truth for WH51/WS69 is the same real hardware frames used by test_wh51.py /
test_fineoffset.py; WS85 uses the rtl_433 doc vector (not audible at Welland).
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import firmwarelib  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(os.path.dirname(HERE), "fixtures")

# cc_weather_drain() return codes (cc1101_weather.h).
CC_WX_IDLE, CC_WX_DECODED, CC_WX_RAW, CC_WX_OVERFLOW = 0, 1, 2, 3
DRAIN_LEN = 30

# WS85: rtl_433 fineoffset_ws85.c doc vector (28+ bytes; the decoder reads the first 28).
WS85_HEX = "850028EB87826F0083003FFF00000000000B0000FFEFFD00006BDD0F000000"


def fixture_hex(name, idx):
    with open(os.path.join(FIX, name)) as f:
        d = json.load(f)
    assert d["format"] == "rf433-packets-v1"
    return d["packets"][idx]["hex"]


def drain(fifo_hex, rxbytes=None, marc=None):
    """Run the radio_host weather_drain command over a scripted RX FIFO."""
    exe = firmwarelib.build_radio_host()
    args = [exe, "weather_drain", fifo_hex]
    if rxbytes is not None:
        args.append(str(rxbytes))
    if marc is not None:
        args.append(str(marc))
    out = subprocess.run(args, check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def _pad_to_drain(frame_hex):
    """Frame at the FIFO head + trailing demodulated noise, as arrives in infinite mode."""
    frame = bytes.fromhex(frame_hex)
    noise = bytes((0xDE + i) & 0xFF for i in range(max(0, DRAIN_LEN - len(frame))))
    return (frame + noise).hex()


def test_wh51_14byte_frame_drained_and_dispatched():
    # 14-byte WH51 with trailing noise filling the FIFO past the drain length.
    r = drain(_pad_to_drain(fixture_hex("wh51_id0f5c54_2026-09-05.json", 0)))
    assert r["rc"] == CC_WX_DECODED
    assert r["n"] == DRAIN_LEN
    assert r["json"]["model"] == "Fineoffset-WH51"
    assert r["json"]["id"] == "0f5c54"
    assert r["json"]["moisture"] == 40


def test_ws69_25byte_frame_drained_and_dispatched():
    r = drain(_pad_to_drain(fixture_hex("ws69_id174_2026-08-20.json", 0)))
    assert r["rc"] == CC_WX_DECODED
    assert r["json"]["model"] == "Fineoffset-WS69"
    assert r["json"]["id"] == 174
    assert r["json"]["temperature_C"] == 13.1


def test_ws85_28byte_frame_drained_and_dispatched():
    r = drain(WS85_HEX)                                   # already >= drain length
    assert r["rc"] == CC_WX_DECODED
    assert r["n"] == DRAIN_LEN
    assert r["json"]["model"] == "Fineoffset-WS85"
    assert r["json"]["id"] == 0x0028EB


def test_all_three_families_use_one_config():
    # The whole point of the fix: the same drain path decodes all three lengths.
    models = set()
    for name, idx in (("wh51_id0f5c54_2026-09-05.json", 0), ("ws69_id174_2026-08-20.json", 0)):
        models.add(drain(_pad_to_drain(fixture_hex(name, idx)))["json"]["model"])
    models.add(drain(WS85_HEX)["json"]["model"])
    assert models == {"Fineoffset-WH51", "Fineoffset-WS69", "Fineoffset-WS85"}


def test_partial_frame_is_not_drained():
    # Fewer than the drain length in the FIFO and no overflow: keep waiting (IDLE).
    partial = fixture_hex("wh51_id0f5c54_2026-09-05.json", 0)   # 14 bytes only
    r = drain(partial)
    assert r["rc"] == CC_WX_IDLE
    assert r["json"] is None


def test_overflow_still_recovers_head_frame():
    # In infinite mode the FIFO overflows normally (fills faster than the 50 ms poll);
    # the CC1101 keeps the first 64 bytes, so the frame at the head is still decodable.
    frame = bytes.fromhex(fixture_hex("wh51_id0f5c54_2026-09-05.json", 0))
    fifo = (frame + bytes(64 - len(frame))).hex()          # 64 bytes total
    r = drain(fifo, rxbytes=0x80 | 64, marc=0x11)          # RXBYTES overflow bit + MARCSTATE overflow
    assert r["rc"] == CC_WX_DECODED
    assert r["json"]["model"] == "Fineoffset-WH51"
    assert r["json"]["id"] == "0f5c54"

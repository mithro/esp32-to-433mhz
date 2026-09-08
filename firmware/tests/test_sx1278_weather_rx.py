"""SX1278 (RA-02) Fine Offset FSK weather-RX framing: fixed-length FSK packet drain + family dispatch.

Proves the ONE SX1278 FSK config (fixed-length packet mode, RegPayloadLength = SX_FSK_RX_LEN)
receives every frame length -- WH51 (14 B), WS69 (25 B), WS85 (28 B) -- from a single simulated
RegFifo drain, mirroring tests/test_weather_rx.py for the CC1101. The C harness (sx1278_host
"weather_drain") scripts the FakeBus FIFO with a frame at the head plus trailing demodulated
noise (as arrives after a short frame) and runs the exact sx_weather_drain() used by the
firmware; this asserts dispatch by family byte and that the trailing noise is ignored.

test_configure_registers also asserts the programmed FSK registers against the datasheet math,
cross-referenced to the proven SX1276 receiver at Welland (rpi5 ~/wh51-watch, RadioLib beginFSK:
433.92 MHz, 17.241 kbps, ~50 kHz fdev, sync 0x2DD4, 2-FSK no shaping).

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

# sx_weather_drain() return codes (sx1278_weather.h).
SX_WX_IDLE, SX_WX_DECODED, SX_WX_RAW = 0, 1, 2
DRAIN_LEN = 30

# WS85: rtl_433 fineoffset_ws85.c doc vector (28+ bytes; the decoder reads the first 28).
WS85_HEX = "850028EB87826F0083003FFF00000000000B0000FFEFFD00006BDD0F000000"


def host(*args):
    exe = firmwarelib.build_sx1278_host()
    out = subprocess.run([exe, *args], check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def fixture_hex(name, idx):
    with open(os.path.join(FIX, name)) as f:
        d = json.load(f)
    assert d["format"] == "rf433-packets-v1"
    return d["packets"][idx]["hex"]


def drain(fifo_hex, irqflags2=None):
    """Run the sx1278_host weather_drain command over a scripted RegFifo."""
    args = ["weather_drain", fifo_hex]
    if irqflags2 is not None:
        args.append(str(irqflags2))
    return host(*args)


def _pad_to_drain(frame_hex):
    """Frame at the FIFO head + trailing demodulated noise, as latched for a short frame."""
    frame = bytes.fromhex(frame_hex)
    noise = bytes((0xDE + i) & 0xFF for i in range(max(0, DRAIN_LEN - len(frame))))
    return (frame + noise).hex()


def test_configure_registers_match_fineoffset_fsk():
    r = host("configure")
    assert r["opmode"] == 0x0D               # FSK, low-freq band, RX
    assert (r["br_msb"], r["br_lsb"]) == (0x07, 0x40)      # 17.241 kbps
    assert (r["fdev_msb"], r["fdev_lsb"]) == (0x03, 0x33)  # ~50 kHz
    assert (r["frf_msb"], r["frf_mid"], r["frf_lsb"]) == (0x6C, 0x7A, 0xE1)  # 433.92 MHz
    assert r["rxbw"] == 0x02                  # 125 kHz
    assert r["preambledetect"] == 0xAA        # on, 2 bytes, tol 10
    assert r["syncconfig"] == 0x91            # AutoRestartRx + SyncOn + 2 sync bytes
    assert (r["sync1"], r["sync2"]) == (0x2D, 0xD4)        # 0x2DD4
    assert r["packetconfig1"] == 0x00         # fixed length, no CRC, no DC-free
    assert r["packetconfig2"] == 0x40         # packet data mode
    assert r["payloadlength"] == DRAIN_LEN    # fixed drain length >= WS85
    assert r["diomapping1"] == 0x00           # DIO0 = PayloadReady
    assert r["rxconfig"] == 0x0E              # AGC auto + preamble-detect RX trigger


def test_wh51_14byte_frame_drained_and_dispatched():
    r = drain(_pad_to_drain(fixture_hex("wh51_id0f5c54_2026-09-05.json", 0)))
    assert r["rc"] == SX_WX_DECODED
    assert r["n"] == DRAIN_LEN
    assert r["rssi"] == -40
    assert r["json"]["model"] == "Fineoffset-WH51"
    assert r["json"]["id"] == "0f5c54"
    assert r["json"]["moisture"] == 40


def test_ws69_25byte_frame_drained_and_dispatched():
    r = drain(_pad_to_drain(fixture_hex("ws69_id174_2026-08-20.json", 0)))
    assert r["rc"] == SX_WX_DECODED
    assert r["json"]["model"] == "Fineoffset-WS69"
    assert r["json"]["id"] == 174
    assert r["json"]["temperature_C"] == 13.1


def test_ws85_28byte_frame_drained_and_dispatched():
    r = drain(WS85_HEX)                                   # already >= drain length
    assert r["rc"] == SX_WX_DECODED
    assert r["n"] == DRAIN_LEN
    assert r["json"]["model"] == "Fineoffset-WS85"
    assert r["json"]["id"] == 0x0028EB


def test_all_three_families_use_one_config():
    # The whole point: the same fixed-length drain path decodes all three lengths.
    models = set()
    for name, idx in (("wh51_id0f5c54_2026-09-05.json", 0), ("ws69_id174_2026-08-20.json", 0)):
        models.add(drain(_pad_to_drain(fixture_hex(name, idx)))["json"]["model"])
    models.add(drain(WS85_HEX)["json"]["model"])
    assert models == {"Fineoffset-WH51", "Fineoffset-WS69", "Fineoffset-WS85"}


def test_no_payload_ready_is_idle():
    # RegIrqFlags2 PayloadReady clear: no full packet latched yet -> keep waiting (IDLE).
    r = drain(_pad_to_drain(fixture_hex("wh51_id0f5c54_2026-09-05.json", 0)), irqflags2=0x00)
    assert r["rc"] == SX_WX_IDLE
    assert r["json"] is None

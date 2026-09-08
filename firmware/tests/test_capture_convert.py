import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
from cc1101_ook_capture import edges_to_trains, write_ook   # noqa: E402


def _events(us_seq, start_ns=1_000_000_000):
    """Turn a mark/space µs sequence into (t_ns, rising) edges; first edge rising."""
    t = start_ns
    ev = [(t, True)]
    level = True
    for d in us_seq:
        t += d * 1000
        level = not level
        ev.append((t, level))
    return ev


def test_single_train_roundtrip():
    us = [730, 200, 200, 730, 730, 7300]
    trains = edges_to_trains(_events(us + [500]))   # trailing mark of 500 then nothing
    assert len(trains) == 1
    assert trains[0]["us"] == [730, 200, 200, 730, 730, 7300, 500]
    assert trains[0]["t0_us"] == 0


def test_split_on_burst_gap():
    us = [300, 300, 300, 20000, 300, 300, 300]
    trains = edges_to_trains(_events(us), burst_gap_us=15000)
    assert [t["us"] for t in trains] == [[300, 300, 300], [300, 300, 300]]
    assert trains[1]["t0_us"] == 300 + 300 + 300 + 20000


def test_glitches_are_merged():
    # a 10 µs dropout inside a 730 µs mark must be absorbed
    ev = _events([360, 10, 360, 200, 200, 9000])
    trains = edges_to_trains(ev, min_pulse_us=40)
    assert trains[0]["us"][:2] == [730, 200]


def test_write_ook_format(tmp_path):
    p = tmp_path / "x.ook"
    write_ook(str(p), [{"t0_us": 0, "us": [730, 200, 200, 7300]}], 433920000)
    txt = p.read_text().splitlines()
    assert txt[0] == ";pulse data" and ";timescale 1us" in txt
    assert ";ook 2 pulses" in txt
    assert txt[-1] == ";end"
    assert "730 200" in txt and "200 7300" in txt

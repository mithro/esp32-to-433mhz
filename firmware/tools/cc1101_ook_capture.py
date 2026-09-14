#!/usr/bin/env python3
"""Capture OOK pulse trains from the Pi's direct-SPI CC1101 (async-serial mode).

Runs ON rpi5-433mhz with the SYSTEM python3 (python3-spidev and python3-libgpiod
are Debian packages there; uv is not installed on the Pi). Deploy next to
hardware/devices/tools/cc1101.py (cc1101_find_gdo_pins.py, the GDO-wiring
probe, lives alongside both on the host and belongs in the same directory
on the Pi):

    scp hardware/devices/tools/cc1101.py hardware/devices/esp32c3-cc1101-node/tools/cc1101_ook_capture.py rpi5-433mhz:~/cc1101-node/
    ssh rpi5-433mhz 'cd ~/cc1101-node && python3 cc1101_ook_capture.py --seconds 30 --out grey5_on.json --device "Grey Power Remote 5 On x3" --ook grey5_on.ook'

Wiring (Pi 5 header, measured 2026-08-22 with cc1101_find_gdo_pins.py): CC1101
GDO2 -> GPIO24 (pin 18, black wire). GDO0 -> GPIO25 (pin 22, green wire) is
not read here but is reserved for Plan B's async TX check.

Output: rf433-pulses-v1 JSON (see fixtures/README.md) and optionally an rtl_433
".ook" pulse file for cross-checking with `rtl_433 -r file.ook ...`.
Host-side use (no hardware): --export-ook in.json out.ook
"""
import argparse
import datetime as dt
import json
import os
import sys
import time

# An odd-length train ends on a mark; rtl_433's format needs a gap after every pulse, so pad with a long silence.
OOK_TRAILING_GAP_US = 100000


def edges_to_trains(events, burst_gap_us=15000, min_pulse_us=40):
    """events: iterable of (t_ns, rising). Returns list of {"t0_us", "us"} trains.

    Segments shorter than min_pulse_us are glitches: they are merged into the
    preceding segment together with the segment that follows them (which has the
    same level as the preceding one), so a 10 us dropout inside a mark vanishes.
    The merge is one-step: a glitch is absorbed together with the following
    same-level segment regardless of that segment's own length, so a pair of
    back-to-back glitches (e.g. 5 us low, 5 us high) is swallowed whole, but a
    longer alternating run of glitches can leave residue. Not tuned beyond the
    single-glitch case exercised by test_capture_convert.py.
    """
    ev = sorted(events)
    while ev and not ev[0][1]:            # start on a rising edge
        ev.pop(0)
    if len(ev) < 2:
        return []
    base_ns = ev[0][0]
    # segments: [level_high, duration_us, start_ns]
    segs = [[lvl, (t1 - t0) / 1000.0, t0] for (t0, lvl), (t1, _) in zip(ev, ev[1:])]
    merged = []
    i = 0
    while i < len(segs):
        lvl, us, t0 = segs[i]
        if merged and us < min_pulse_us:
            merged[-1][1] += us                      # absorb the glitch ...
            if i + 1 < len(segs) and segs[i + 1][0] == merged[-1][0]:
                merged[-1][1] += segs[i + 1][1]      # ... and the same-level segment after it
                i += 2
                continue
            i += 1
            continue
        merged.append([lvl, us, t0])
        i += 1
    trains, cur = [], None
    for lvl, us, t0 in merged:
        if cur is None:
            if not lvl:
                continue
            cur = {"t0_us": int(round((t0 - base_ns) / 1000.0)), "us": []}
        if not lvl and us >= burst_gap_us:
            trains.append(cur)
            cur = None
            continue
        cur["us"].append(int(round(us)))
    if cur and cur["us"]:
        trains.append(cur)
    return trains


def write_ook(path, trains, freq_hz):
    """rtl_433 pulse-data text format (src/pulse_data.c). One file, all trains;
    rtl_433 treats each 'pulse gap' list terminated by ;end as a package, so
    write one block per train."""
    with open(path, "w") as f:
        for tr in trains:
            us = tr["us"]
            pairs = [(us[i], us[i + 1] if i + 1 < len(us) else OOK_TRAILING_GAP_US) for i in range(0, len(us), 2)]
            f.write(";pulse data\n;version 1\n;timescale 1us\n")
            f.write(";ook %d pulses\n;freq1 %d\n;centerfreq %d Hz\n;samplerate 250000 Hz\n" % (len(pairs), freq_hz, freq_hz))
            for p, g in pairs:
                f.write("%d %d\n" % (p, g))
            f.write(";end\n")


def _find_rp1_chip():
    import glob
    import gpiod
    for path in sorted(glob.glob("/dev/gpiochip*")):
        with gpiod.Chip(path) as chip:
            if chip.get_info().label == "pinctrl-rp1":
                return path
    raise SystemExit("no pinctrl-rp1 gpiochip found - is this a Pi 5?")


def capture(args):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from cc1101 import CC1101, configure_ook_async_rx
    import gpiod
    from gpiod import EdgeEvent
    from gpiod.line import Direction, Edge
    c = CC1101(bus=0, device=0, spi_hz=500_000)
    c.reset()
    partnum, version = c.identify()
    print("CC1101 partnum=0x%02X version=0x%02X" % (partnum, version))
    if partnum != 0x00:
        raise SystemExit("CC1101 not detected")
    cfg = configure_ook_async_rx(c, freq_hz=args.freq_hz)
    print("async OOK RX:", json.dumps(cfg))
    # MCSM0's auto-cal-on-IDLE->RX re-triggers a calibration cycle after the
    # SRX strobe, so MARCSTATE walks STARTCAL/BWBOOST/FS_LOCK/IFADCON/ENDCAL
    # before landing on RX (0x0D); give it up to ~50ms to settle before we
    # report the state (real captures below aren't affected: gpiod line
    # setup takes longer than this anyway).
    marc = c.get_marcstate()
    settle_deadline = time.monotonic() + 0.05
    while marc != 0x0D and time.monotonic() < settle_deadline:
        time.sleep(0.005)
        marc = c.get_marcstate()
    print("MARCSTATE=0x%02X (0x0D = RX)" % marc)
    chip = _find_rp1_chip()
    events = []
    deadline = time.monotonic() + args.seconds
    with gpiod.request_lines(chip, consumer="cc1101-ook",
                             config={args.gpio: gpiod.LineSettings(direction=Direction.INPUT,
                                                                  edge_detection=Edge.BOTH)}) as req:
        print("capturing GDO2 edges on GPIO%d for %d s - press the remote now" % (args.gpio, args.seconds))
        while time.monotonic() < deadline:
            if req.wait_edge_events(dt.timedelta(milliseconds=200)):
                for e in req.read_edge_events():
                    events.append((e.timestamp_ns, e.event_type == EdgeEvent.Type.RISING_EDGE))
    trains = edges_to_trains(events, args.burst_gap_us)
    # keep only trains with a plausible number of pulses (>= 2*OOKPWM_MIN_BITS edges)
    trains = [t for t in trains if len(t["us"]) >= 32]
    print("edges=%d trains(>=16 pulses)=%d" % (len(events), len(trains)))
    doc = {"format": "rf433-pulses-v1",
           "source": "rpi5-433mhz CC1101 spidev0.0 async-serial OOK, GDO2 -> GPIO%d via gpiod" % args.gpio,
           "captured": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
           "freq_hz": int(args.freq_hz), "device": args.device, "trains": trains}
    with open(args.out, "w") as f:
        json.dump(doc, f)
    print("wrote", args.out)
    if args.ook:
        write_ook(args.ook, trains, int(args.freq_hz))
        print("wrote", args.ook)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=30)
    ap.add_argument("--out", help="fixture JSON to write")
    ap.add_argument("--device", default="", help="free-text description of what was pressed")
    ap.add_argument("--ook", help="also write rtl_433 .ook pulse file")
    ap.add_argument("--gpio", type=int, default=24, help="Pi GPIO wired to CC1101 GDO2 (24 on rpi5-433mhz)")
    ap.add_argument("--freq-hz", type=float, default=433.92e6)
    ap.add_argument("--burst-gap-us", type=int, default=15000)
    ap.add_argument("--export-ook", nargs=2, metavar=("IN_JSON", "OUT_OOK"))
    args = ap.parse_args()
    if args.export_ook:
        with open(args.export_ook[0]) as f:
            d = json.load(f)
        write_ook(args.export_ook[1], d["trains"], d["freq_hz"])
        print("wrote", args.export_ook[1])
        return
    if not args.out:
        ap.error("--out is required for capture")
    capture(args)


if __name__ == "__main__":
    main()

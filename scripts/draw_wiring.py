#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Draw the jumper-wire hook-up of an ESP32-C3 SuperMini to each radio board,
using the socket adapter's GPIO assignment, as docs/images/wiring-<radio>.svg.

Wire colours follow the rainbow ribbon order the user asked for (brown GND,
red 3V3, orange GPIO5, yellow GPIO6, green GPIO7, blue GPIO8, purple GPIO9,
grey GPIO10).  GPIO8 is not wired to the radio, so its blue goes to GPIO3,
and GPIO4, the other power-row pin the socket uses, takes the ribbon's
remaining colour, white.  GPIO5 is the radio-type strap: for the
Ra-02 breakout it goes to GPIO1, which the firmware drives low while it reads
the strap (the SuperMini's only GND pin is taken by the brown wire); for a
CC1101 board it is left open.

Boards: the blue E07-M1101D and the green D-Sun CC1101 boards, and the Ra-02
breakout.  All three plug into the same socket positions; only the names of
the signals at each position differ (the firmware uses a pin map per board),
so the three diagrams share one wiring layout.

Both boards are drawn from the back (deadbug style, the way they sit with
header pins pointing at you): the SuperMini top left, USB-C up, and the
radio board lower right with its header edge up.  Wires from the SuperMini's
GPIO column (on the right in this view) turn down the gap and along lanes
into the header from above; GND, 3V3, GPIO4 and GPIO3 come down the
SuperMini's left side.  GND and 3V3 enter the header's first column from the
left; GPIO4 runs along the back of the radio board below the header and up
into its pin; GPIO3 takes the lowest lane and drops into its pin, crossing
the two wires of the second column, which cannot be avoided.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import generate_cc1101 as cc  # noqa: E402
import generate_dsun as ds  # noqa: E402
import generate_ra02_breakout as rb  # noqa: E402
import generate_supermini as sm  # noqa: E402
from draw_pinouts import INK, PIN, S, View, dsun_views, e07_views, ra02_views  # noqa: E402

OUT = pathlib.Path(__file__).resolve().parent.parent / "docs" / "images"

# SuperMini pin -> (colour name, fill).  Keyed by the GPIO number as printed
# on the SuperMini ("G" and "3V3" for the supplies).
WIRES = {
    "G": ("brown", "#7b4a1e"),
    "3V3": ("red", "#d81e1e"),
    "5": ("orange", "#f28c1e"),
    "6": ("yellow", "#f2d21e"),
    "7": ("green", "#2e9e4f"),
    "9": ("purple", "#7d3fa8"),
    "10": ("grey", "#8c8c8c"),
    "4": ("white", "#f4f4f4"),
    "3": ("blue", "#2464c8"),
}
# SuperMini columns, top to bottom (front view, USB-C up).
SM_LEFT = ["5", "6", "7", "8", "9", "10", "20", "21"]
SM_RIGHT = ["5V", "G", "3V3", "4", "3", "2", "1", "0"]
# Socket position (numbered like the E07-M1101D: pin 1 right of the outer
# row seen from the front, even pins in the inner row, columns to -x) ->
# SuperMini pin, as on the socket adapter.
POS_PIN = {1: "G", 2: "3V3", 3: "10", 4: "9", 5: "3", 6: "4", 7: "7", 8: "6"}
# ... and -> the signal name printed on each radio board.
E07_NAMES = {1: "GND", 2: "VCC", 3: "GDO0", 4: "CSN", 5: "SCK", 6: "MOSI", 7: "MISO", 8: "GDO2"}
DSUN_NAMES = {1: "GND", 2: "VCC", 3: "MOSI", 4: "SCK", 5: "MISO", 6: "GDO2", 7: "GDO0", 8: "CSN"}
RA02_NAMES = {1: "GND", 2: "3V3", 3: "RST", 4: "NSS", 5: "SCK", 6: "MOSI", 7: "MISO", 8: "DIO0"}
SIGNAL = {"GND": "ground", "VCC": "3.3 V", "3V3": "3.3 V", "MOSI": "SPI MOSI", "MISO": "SPI MISO", "SCK": "SPI clock",
          "CSN": "SPI chip select", "NSS": "SPI chip select", "GDO0": "IRQ / packet (CC1101 GDO0)", "GDO2": "second IRQ (CC1101 GDO2)",
          "RST": "reset (drive as an output)", "DIO0": "IRQ / packet (SX1278 DIO0)"}
RADIOS = {  # name -> (title, radio column heading, signal name at each socket position)
    "cc1101": ("blue CC1101 E07-M1101D-SMA", "E07-M1101D", E07_NAMES),
    "cc1101-dsun": ("green D-Sun CC1101", "D-Sun CC1101", DSUN_NAMES),
    "ra02": ("SX1278 Ra-02 breakout", "Ra-02 breakout", RA02_NAMES),
}


def supermini_view() -> tuple[View, dict[str, tuple[float, float]]]:
    """Back view of the SuperMini (deadbug: header pins towards the viewer)
    with every pin named; returns the pin centres (mm, back-view frame)."""
    W, H = sm.BOARD_W, sm.BOARD_H
    v = View(W, H, True)  # mirrored: drawn in front-view coordinates
    v.rect(0, 0, W, H, fill="#1f2430", stroke="#0b0d12", width=0.25, rx=0.6)
    v.rect(W / 2 - 4.5, -1.5, W / 2 + 4.5, 5.85, fill="#c9ced6", stroke=INK, width=0.12, rx=0.8)
    v.text(W / 2, 2.4, "USB-C", size=1.0)
    v.text(W / 2, 12.0, "ESP32-C3", size=1.1, fill="#ffffff", weight="bold")
    v.text(W / 2, 13.8, "SuperMini", size=1.1, fill="#ffffff", weight="bold")
    v.text(W / 2, 16.2, "back", size=0.9, fill="#ffffff")
    pins = {}
    for i in range(8):
        y = sm.PIN_TOP_Y + i * sm.PITCH
        for x, name, anchor, lx in ((sm.PIN_EDGE_X, SM_LEFT[i], "end", 2.6), (W - sm.PIN_EDGE_X, SM_RIGHT[i], "start", W - 2.6)):
            v.circle(x, y, 0.8, fill=PIN, stroke=INK, width=0.12)
            v.circle(x, y, 0.45, fill="#ffffff", stroke=INK, width=0.08)
            v.text(lx, y, name, size=0.95, anchor=anchor, fill="#ffffff", weight="bold")
            pins[name] = (W - x, y)  # where it lands in the mirrored drawing
    return v, pins


def rounded_path(pts: list[tuple[float, float]], r: float) -> str:
    """SVG path through the points with corners rounded by r (px)."""
    d = [f"M {pts[0][0]:.1f} {pts[0][1]:.1f}"]
    for i in range(1, len(pts) - 1):
        (x0, y0), (x1, y1), (x2, y2) = pts[i - 1], pts[i], pts[i + 1]
        l1 = max(((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5, 1e-6)
        l2 = max(((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5, 1e-6)
        rr = min(r, l1 / 2, l2 / 2)
        ax, ay = x1 - (x1 - x0) / l1 * rr, y1 - (y1 - y0) / l1 * rr
        bx, by = x1 + (x2 - x1) / l2 * rr, y1 + (y2 - y1) / l2 * rr
        d.append(f"L {ax:.1f} {ay:.1f} Q {x1:.1f} {y1:.1f} {bx:.1f} {by:.1f}")
    d.append(f"L {pts[-1][0]:.1f} {pts[-1][1]:.1f}")
    return " ".join(d)


LANE = 1.8  # mm between parallel wires


def draw(radio: str) -> None:
    title, radio_col, names = RADIOS[radio]
    # Header pin positions in the back view (mirrored x).
    if radio == "cc1101":
        board = e07_views()[1]
        W = cc.BOARD_W
        hdr = {n: (W - (W - cc.HDR_COL_X - ((n - 1) // 2) * cc.PITCH), cc.HDR_ROW_Y + ((n - 1) % 2) * cc.PITCH) for n in range(1, 9)}
    elif radio == "cc1101-dsun":
        board = dsun_views()[1]
        W = ds.BOARD_W
        hdr = {n: (W - (W - ds.HDR_COL_X - ((n - 1) // 2) * ds.PITCH), ds.HDR_ROW_Y + ((n - 1) % 2) * ds.PITCH) for n in range(1, 9)}
    else:
        board = ra02_views()[1]
        pos = {n: (rb.BOARD_W - rb.hdr_x(n), rb.hdr_y(n)) for n in range(1, 9)}
        remap = {1: 7, 2: 8, 3: 5, 4: 6, 5: 3, 6: 4, 7: 1, 8: 2}
        hdr = {n: pos[remap[n]] for n in range(1, 9)}
    smv, sm_pins = supermini_view()

    # Layout (mm).  SuperMini top left, back view: GPIO column on the right.
    # Radio board lower right, back view with the header up: its GND/VCC
    # column is the one nearest the gap.
    sx, sy = 16.0, 14.0
    sm_bot = sy + smv.h
    gap_x = [sx + smv.w + 3.5 + i * LANE for i in range(5)]  # vertical lanes in the gap, innermost first
    lane_y = [sm_bot + 2.0 + k * LANE for k in range(5)]  # horizontal lanes, highest first
    bx = gap_x[-1] + 5.0
    by = lane_y[-1] + 2.5 - cc.HDR_ROW_Y
    left_x = [sx - 2.5 - i * LANE for i in range(4)]  # left-side lanes, innermost first: GPIO4, GPIO3, 3V3, GND
    total_w = max(bx + board.w + 8.0, 102.0)  # room for the legend's signal column
    hang = 4.0 if radio == "ra02" else 14.5  # the SMA jack and size caption below the outline
    legend_y = by + board.h + hang + 4.0
    total_h = legend_y + 22.0
    px = lambda x, y, ox, oy: ((ox + x) * S, (oy + y) * S)  # noqa: E731
    hp = lambda n: px(*hdr[n], bx, by)  # noqa: E731
    sp = lambda name: px(*sm_pins[name], sx, sy)  # noqa: E731

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_w * S:.0f}" height="{total_h * S:.0f}" viewBox="0 0 {total_w * S:.0f} {total_h * S:.0f}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{total_w * S / 2:.1f}" y="{3.0 * S:.1f}" font-size="{2.0 * S:.1f}" font-family="Helvetica, Arial, sans-serif" font-weight="bold" fill="{INK}" text-anchor="middle" dy="0.36em">ESP32-C3 SuperMini to the {title} with jumper wires</text>',
        f'<text x="{total_w * S / 2:.1f}" y="{5.6 * S:.1f}" font-size="{1.2 * S:.1f}" font-family="Helvetica, Arial, sans-serif" fill="{INK}" text-anchor="middle" dy="0.36em">Same pins as the socket adapter. Both boards seen from the back, header pins towards you.</text>',
        board.svg_group(bx * S, by * S, "", 0, 0),
        smv.svg_group(sx * S, sy * S, "", 0, 0),
    ]

    half = cc.PITCH / 2 * S
    wires: list[tuple[str, list[tuple[float, float]]]] = []
    # GPIO column: positions 7/8 (column D, from the top pins GPIO7/6) take
    # the outer gap lanes and the top horizontal lanes, positions 3/4 (column
    # B, GPIO10/9) the inner and lower ones, so none of them cross.  Inner-row
    # pins are entered by a drop just right of their column.
    for n, gi, li in ((8, 4, 0), (7, 3, 1), (4, 1, 2), (3, 0, 3)):
        pin = POS_PIN[n]
        (smx, smy), (hx, hy) = sp(pin), hp(n)
        gx, ly = gap_x[gi] * S, lane_y[li] * S
        if n % 2:
            pts = [(smx, smy), (gx, smy), (gx, ly), (hx, ly), (hx, hy)]
        else:
            pts = [(smx, smy), (gx, smy), (gx, ly), (hx + half, ly), (hx + half, hy), (hx, hy)]
        wires.append((WIRES[pin][1], pts))
    # Left column.  GND and 3V3 straight into the first column from the left
    # (they cross once, unavoidably).
    for n, lx_i in ((1, 3), (2, 2)):
        pin = POS_PIN[n]
        (smx, smy), (hx, hy) = sp(pin), hp(n)
        wires.append((WIRES[pin][1], [(smx, smy), (left_x[lx_i] * S, smy), (left_x[lx_i] * S, hy), (hx, hy)]))
    # GPIO4 -> position 6 (column C, inner row): along the back of the radio
    # board just below the header, then up into the pin.
    (smx, smy), (hx, hy) = sp("4"), hp(6)
    ly = hy + 3.0 * S
    wires.append((WIRES["4"][1], [(smx, smy), (left_x[0] * S, smy), (left_x[0] * S, ly), (hx, ly), (hx, hy)]))
    # GPIO3 -> position 5 (column C, outer row): the lowest lane and a drop
    # from above, across column B's two drops.
    (smx, smy), (hx, hy) = sp("3"), hp(5)
    ly = lane_y[4] * S
    wires.append((WIRES["3"][1], [(smx, smy), (left_x[1] * S, smy), (left_x[1] * S, ly), (hx, ly), (hx, hy)]))
    # Strap: GPIO5 over the top of the SuperMini to GPIO1 (Ra-02), or a free end (CC1101).
    (smx, smy) = sp("5")
    if radio == "ra02":
        gx, gy = sp("1")
        over = (sy - 3.0) * S
        wires.append((WIRES["5"][1], [(smx, smy), (smx, over), (gx + 4.3 * S, over), (gx + 4.3 * S, gy), (gx, gy)]))
    else:
        wires.append((WIRES["5"][1], [(smx, smy), (gap_x[0] * S, smy), (gap_x[0] * S, smy - 3.5 * S)]))
    for fill, pts in wires:
        d = rounded_path(pts, 1.6 * S)
        parts.append(f'<path d="{d}" fill="none" stroke="{INK}" stroke-width="{1.3 * S:.1f}" stroke-linecap="round"/>')
        parts.append(f'<path d="{d}" fill="none" stroke="{fill}" stroke-width="{0.85 * S:.1f}" stroke-linecap="round"/>')
        for x, y in (pts[0], pts[-1]):  # crimp ends
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{0.8 * S:.1f}" fill="{fill}" stroke="{INK}" stroke-width="{0.15 * S:.1f}"/>')
    note_x = (gap_x[0] + 1.2) * S
    if radio == "ra02":
        parts.append(f'<text x="{(sx + smv.w / 2) * S:.1f}" y="{(sy - 4.6) * S:.1f}" font-size="{0.95 * S:.1f}" font-family="Helvetica, Arial, sans-serif" fill="{INK}" text-anchor="middle" dy="0.36em">GPIO5 strap to GPIO1 (firmware drives GPIO1 low to read it)</text>')
    else:
        parts.append(f'<text x="{note_x:.1f}" y="{smy - 5.0 * S:.1f}" font-size="{0.95 * S:.1f}" font-family="Helvetica, Arial, sans-serif" fill="{INK}" text-anchor="middle" dy="0.36em">GPIO5: leave open</text>')
    # The header's pin names again, on top of the wires (with a halo).
    overlay = View(board.w, board.h, False)
    for n in range(1, 9):
        hx, hy = hdr[n]
        outer = n % 2 == 1
        overlay.text(hx, hy + (-1.5 if outer else 1.5), names[n], size=1.05, anchor="start" if outer else "end", angle=-90, weight="bold", halo=True)
    parts.append(overlay.svg_group(bx * S, by * S, "", 0, 0))
    # ... and the SuperMini's pin names (the strap wire runs over some of them).
    overlay = View(smv.w, smv.h, True)
    for i in range(8):
        y = sm.PIN_TOP_Y + i * sm.PITCH
        overlay.text(2.6, y, SM_LEFT[i], size=0.95, anchor="end", weight="bold", halo=True)
        overlay.text(smv.w - 2.6, y, SM_RIGHT[i], size=0.95, anchor="start", weight="bold", halo=True)
    parts.append(overlay.svg_group(sx * S, sy * S, "", 0, 0))

    # Legend: one row per wire, in socket-position order plus the strap.
    ly0 = legend_y
    margin = 8.0
    cols = ((margin + 12, "SuperMini"), (margin + 24, radio_col), (margin + 40, "Signal"))
    parts.append(f'<text x="{margin * S:.1f}" y="{ly0 * S:.1f}" font-size="{1.2 * S:.1f}" font-family="Helvetica, Arial, sans-serif" font-weight="bold" fill="{INK}" dy="0.36em">Wire</text>')
    for x, t in cols:
        parts.append(f'<text x="{x * S:.1f}" y="{ly0 * S:.1f}" font-size="{1.2 * S:.1f}" font-family="Helvetica, Arial, sans-serif" font-weight="bold" fill="{INK}" dy="0.36em">{t}</text>')
    rows = [(POS_PIN[n], names[n], SIGNAL[names[n]]) for n in range(1, 9)]
    rows.append(("5", "(to the SuperMini's GPIO1)" if radio == "ra02" else "(none)", "radio-type strap: to GPIO1 for the Ra-02, open for a CC1101"))
    for i, (pin, name, signal) in enumerate(rows):
        colour, fill = WIRES[pin]
        y = ly0 + 2.0 + i * 2.0
        parts.append(f'<rect x="{margin * S:.1f}" y="{(y - 0.6) * S:.1f}" width="{4.0 * S:.1f}" height="{1.2 * S:.1f}" fill="{fill}" stroke="{INK}" stroke-width="{0.1 * S:.1f}" rx="{0.5 * S:.1f}"/>')
        parts.append(f'<text x="{(margin + 5.0) * S:.1f}" y="{y * S:.1f}" font-size="{1.1 * S:.1f}" font-family="Helvetica, Arial, sans-serif" fill="{INK}" dy="0.36em">{colour}</text>')
        for (x, _), t in zip(cols, (pin + ("" if pin in ("G", "3V3") else f" (GPIO{pin})"), name, signal)):
            parts.append(f'<text x="{x * S:.1f}" y="{y * S:.1f}" font-size="{1.1 * S:.1f}" font-family="Helvetica, Arial, sans-serif" fill="{INK}" dy="0.36em">{t}</text>')
    parts.append("</svg>")
    path = OUT / f"wiring-{radio}.svg"
    path.write_text("\n".join(parts) + "\n")
    print(f"wrote {path.relative_to(path.parents[2])}")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for radio in RADIOS:
        draw(radio)


if __name__ == "__main__":
    main()

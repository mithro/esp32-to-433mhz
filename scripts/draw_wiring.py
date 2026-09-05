#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Draw the jumper-wire hook-up of an ESP32-C3 SuperMini to each radio board,
using the socket adapter's GPIO assignment, as docs/images/wiring-<radio>.svg.

Wire colours follow the rainbow ribbon order the user asked for (brown GND,
red 3V3, then orange..grey for GPIO5..GPIO10); the chip select on GPIO0 gets
the next colour, white.  GPIO5 is the radio-type strap: to GND for the Ra-02
breakout, left open for the CC1101 board.

Both boards are drawn from the back (deadbug style, the way they sit with
header pins pointing at you): the SuperMini top left, USB-C up, and the
radio board lower right with its header edge up.  Wires from the SuperMini's
GPIO column (on the right in this view) turn down the gap and along lanes
into the header from above; GND, 3V3 and GPIO0 come down the SuperMini's
left side and into the header's first column from the left.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import generate_cc1101 as cc  # noqa: E402
import generate_ra02_breakout as rb  # noqa: E402
import generate_supermini as sm  # noqa: E402
from draw_pinouts import INK, PIN, S, View, e07_views, ra02_views  # noqa: E402

OUT = pathlib.Path(__file__).resolve().parent.parent / "docs" / "images"

# net -> (colour name, fill, SuperMini pin name)
WIRES = {
    "GND": ("brown", "#7b4a1e", "G"),
    "+3V3": ("red", "#d81e1e", "3V3"),
    "RADIO_ID": ("orange", "#f28c1e", "5"),
    "GDO2_DIO0": ("yellow", "#f2d21e", "6"),
    "MISO": ("green", "#2e9e4f", "7"),
    "MOSI": ("blue", "#2464c8", "8"),
    "SCK": ("purple", "#7d3fa8", "9"),
    "GDO0_RST": ("grey", "#8c8c8c", "10"),
    "CSN_NSS": ("white", "#f4f4f4", "0"),
}
# SuperMini columns, top to bottom (front view, USB-C up).
SM_LEFT = ["5", "6", "7", "8", "9", "10", "20", "21"]
SM_RIGHT = ["5V", "G", "3V3", "4", "3", "2", "1", "0"]
# Radio header position (front view) -> net, numbered like the E07-M1101D:
# pin 1 right of the outer row, even pins in the inner row, columns to -x.
E07_NETS = {1: "GND", 2: "+3V3", 3: "GDO0_RST", 4: "CSN_NSS", 5: "SCK", 6: "MOSI", 7: "MISO", 8: "GDO2_DIO0"}
RADIOS = {
    "cc1101": ("CC1101 E07-M1101D-SMA", "GDO0", "GDO2", "CSN"),
    "ra02": ("SX1278 Ra-02 breakout", "RST", "DIO0", "NSS"),
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
    title, gdo0, gdo2, csn = RADIOS[radio]
    # Header pin positions in the back view (mirrored x), numbered like the E07.
    if radio == "cc1101":
        board = e07_views()[1]
        W = cc.BOARD_W
        hdr = {n: (W - (W - cc.HDR_COL_X - ((n - 1) // 2) * cc.PITCH), cc.HDR_ROW_Y + ((n - 1) % 2) * cc.PITCH) for n in range(1, 9)}
    else:
        board = ra02_views()[1]
        pos = {n: (rb.BOARD_W - rb.hdr_x(n), rb.hdr_y(n)) for n in range(1, 9)}
        hdr = {n: pos[{1: 7, 2: 8, 3: 5, 4: 6, 5: 3, 6: 4, 7: 1, 8: 2}[n]] for n in range(1, 9)}
    smv, sm_pins = supermini_view()

    # Layout (mm).  SuperMini top left, back view: GPIO column on the right.
    # Radio board lower right, back view with the header up: its GND/VCC
    # column is the one nearest the gap.  GPIO wires leave to the right, turn
    # down the gap and run along lanes between the SuperMini's bottom and the
    # header; GND and 3V3 go down the SuperMini's left side and straight into
    # their pins from the left; GPIO0 the same way via the lowest lane.
    sx, sy = 16.0, 14.0
    sm_bot = sy + smv.h
    gap_x = [sx + smv.w + 3.5 + i * LANE for i in range(5)]  # vertical lanes in the gap, innermost first
    lane_y = [sm_bot + 2.0 + k * LANE for k in range(6)]  # horizontal lanes, highest first
    bx = gap_x[-1] + 5.0
    by = lane_y[-1] + 2.5 - cc.HDR_ROW_Y
    left_x = [sx - 2.5 - i * LANE for i in range(3)]  # left-side lanes: GPIO0, 3V3, GND
    total_w = max(bx + board.w + 8.0, 102.0)  # room for the legend's signal column
    hang = 12.5 if radio == "cc1101" else 4.0  # the E07's SMA jack, or the size caption, below the outline
    legend_y = by + board.h + hang + 4.0
    total_h = legend_y + 22.0
    px = lambda x, y, ox, oy: ((ox + x) * S, (oy + y) * S)  # noqa: E731
    hp = lambda n: px(*hdr[n], bx, by)  # noqa: E731
    sp = lambda name: px(*sm_pins[name], sx, sy)  # noqa: E731

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_w * S:.0f}" height="{total_h * S:.0f}" viewBox="0 0 {total_w * S:.0f} {total_h * S:.0f}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{total_w * S / 2:.1f}" y="{3.0 * S:.1f}" font-size="{2.0 * S:.1f}" font-family="Helvetica, Arial, sans-serif" font-weight="bold" fill="{INK}" text-anchor="middle" dy="0.36em">ESP32-C3 SuperMini to {title} with jumper wires</text>',
        f'<text x="{total_w * S / 2:.1f}" y="{5.6 * S:.1f}" font-size="{1.2 * S:.1f}" font-family="Helvetica, Arial, sans-serif" fill="{INK}" text-anchor="middle" dy="0.36em">Same pins as the socket adapter. Both boards seen from the back, header pins towards you.</text>',
        board.svg_group(bx * S, by * S, "", 0, 0),
        smv.svg_group(sx * S, sy * S, "", 0, 0),
    ]

    half = cc.PITCH / 2 * S
    wires: list[tuple[str, list[tuple[float, float]]]] = []
    # GPIO column -> header columns D (pins 6, 7), C (8, 9), B (10): the
    # further the column, the higher the lane and the further out the drop.
    # Inner-row pins are entered from a drop just right of their column.
    plan = [("GDO2_DIO0", 8, 4, 0), ("MISO", 7, 3, 1), ("MOSI", 6, 2, 2), ("SCK", 5, 1, 3), ("GDO0_RST", 3, 0, 4)]
    for net, n, gi, li in plan:
        fill, pin = WIRES[net][1], WIRES[net][2]
        (smx, smy), (hx, hy) = sp(pin), hp(n)
        gx, ly = gap_x[gi] * S, lane_y[li] * S
        if n % 2:  # outer row: straight down into the pin
            pts = [(smx, smy), (gx, smy), (gx, ly), (hx, ly), (hx, hy)]
        else:
            pts = [(smx, smy), (gx, smy), (gx, ly), (hx + half, ly), (hx + half, hy), (hx, hy)]
        wires.append((fill, pts))
    # Left column: GND and 3V3 straight into the header's first column from
    # the left (they cross once, unavoidably); GPIO0 along the lowest lane to
    # a drop between the first two columns.
    for net, n, lx_i in (("GND", 1, 2), ("+3V3", 2, 1)):
        fill, pin = WIRES[net][1], WIRES[net][2]
        (smx, smy), (hx, hy) = sp(pin), hp(n)
        wires.append((fill, [(smx, smy), (left_x[lx_i] * S, smy), (left_x[lx_i] * S, hy), (hx, hy)]))
    fill, pin = WIRES["CSN_NSS"][1], WIRES["CSN_NSS"][2]
    (smx, smy), (hx, hy) = sp(pin), hp(4)
    ly = lane_y[5] * S
    wires.append((fill, [(smx, smy), (left_x[0] * S, smy), (left_x[0] * S, ly), (hx - half, ly), (hx - half, hy), (hx, hy)]))
    # Strap: GPIO5 over the top of the SuperMini to its own G pin (Ra-02), or a free end (CC1101).
    fill = WIRES["RADIO_ID"][1]
    (smx, smy) = sp("5")
    if radio == "ra02":
        gx, gy = sp("G")
        over = (sy - 3.0) * S
        wires.append((fill, [(smx, smy), (smx, over), (gx + 5.5 * S, over), (gx + 5.5 * S, gy), (gx, gy)]))
    else:
        wires.append((fill, [(smx, smy), (gap_x[0] * S, smy), (gap_x[0] * S, smy - 3.5 * S)]))
    for fill, pts in wires:
        d = rounded_path(pts, 1.6 * S)
        parts.append(f'<path d="{d}" fill="none" stroke="{INK}" stroke-width="{1.3 * S:.1f}" stroke-linecap="round"/>')
        parts.append(f'<path d="{d}" fill="none" stroke="{fill}" stroke-width="{0.85 * S:.1f}" stroke-linecap="round"/>')
        for x, y in (pts[0], pts[-1]):  # crimp ends
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{0.8 * S:.1f}" fill="{fill}" stroke="{INK}" stroke-width="{0.15 * S:.1f}"/>')
    note_x = (gap_x[0] + 1.2) * S
    if radio == "cc1101":
        parts.append(f'<text x="{note_x:.1f}" y="{smy - 5.0 * S:.1f}" font-size="{0.95 * S:.1f}" font-family="Helvetica, Arial, sans-serif" fill="{INK}" text-anchor="middle" dy="0.36em">GPIO5: leave open</text>')
    else:
        parts.append(f'<text x="{(sx + smv.w / 2) * S:.1f}" y="{(sy - 4.6) * S:.1f}" font-size="{0.95 * S:.1f}" font-family="Helvetica, Arial, sans-serif" fill="{INK}" text-anchor="middle" dy="0.36em">GPIO5 strap to GND (shares the G pin)</text>')
    # The header's pin names again, on top of the wires (with a halo).
    overlay = View(board.w, board.h, False)
    for n in range(1, 9):
        hx, hy = hdr[n]
        name = cc.PIN_NAMES[str(n)] if radio == "cc1101" else rb.HDR_LABELS[str({1: 7, 2: 8, 3: 5, 4: 6, 5: 3, 6: 4, 7: 1, 8: 2}[n])]
        outer = n % 2 == 1
        overlay.text(hx, hy + (-1.5 if outer else 1.5), name, size=1.05, anchor="start" if outer else "end", angle=-90, weight="bold", halo=True)
    parts.append(overlay.svg_group(bx * S, by * S, "", 0, 0))
    # ... and the SuperMini's pin names (the strap wire runs over two of them).
    overlay = View(smv.w, smv.h, True)
    for i in range(8):
        y = sm.PIN_TOP_Y + i * sm.PITCH
        overlay.text(2.6, y, SM_LEFT[i], size=0.95, anchor="end", weight="bold", halo=True)
        overlay.text(smv.w - 2.6, y, SM_RIGHT[i], size=0.95, anchor="start", weight="bold", halo=True)
    parts.append(overlay.svg_group(sx * S, sy * S, "", 0, 0))

    # Legend
    ly0 = legend_y
    margin = 8.0
    parts.append(f'<text x="{margin * S:.1f}" y="{ly0 * S:.1f}" font-size="{1.2 * S:.1f}" font-family="Helvetica, Arial, sans-serif" font-weight="bold" fill="{INK}" dy="0.36em">Wire</text>')
    cols = ((margin + 12, "SuperMini"), (margin + 24, "Ra-02 breakout" if radio == "ra02" else "E07-M1101D"), (margin + 40, "Signal"))
    for x, t in cols:
        parts.append(f'<text x="{x * S:.1f}" y="{ly0 * S:.1f}" font-size="{1.2 * S:.1f}" font-family="Helvetica, Arial, sans-serif" font-weight="bold" fill="{INK}" dy="0.36em">{t}</text>')
    names = {"GND": "GND", "+3V3": "VCC" if radio == "cc1101" else "3V3", "RADIO_ID": "(to the SuperMini's G)" if radio == "ra02" else "(none)",
             "GDO2_DIO0": gdo2, "MISO": "MISO", "MOSI": "MOSI", "SCK": "SCK", "GDO0_RST": gdo0, "CSN_NSS": csn}
    signal = {"GND": "ground", "+3V3": "3.3 V", "RADIO_ID": "radio-type strap: to GND for the Ra-02, open for the CC1101",
              "GDO2_DIO0": "second IRQ (GDO2 / DIO0)", "MISO": "SPI MISO", "MOSI": "SPI MOSI", "SCK": "SPI clock",
              "GDO0_RST": "IRQ (CC1101 GDO0) / reset (Ra-02 RST)", "CSN_NSS": "SPI chip select"}
    for i, (net, (colour, fill, pin)) in enumerate(WIRES.items()):
        y = ly0 + 2.0 + i * 2.0
        parts.append(f'<rect x="{margin * S:.1f}" y="{(y - 0.6) * S:.1f}" width="{4.0 * S:.1f}" height="{1.2 * S:.1f}" fill="{fill}" stroke="{INK}" stroke-width="{0.1 * S:.1f}" rx="{0.5 * S:.1f}"/>')
        parts.append(f'<text x="{(margin + 5.0) * S:.1f}" y="{y * S:.1f}" font-size="{1.1 * S:.1f}" font-family="Helvetica, Arial, sans-serif" fill="{INK}" dy="0.36em">{colour}</text>')
        for (x, _), t in zip(cols, (f"{pin}" + ("" if pin in ("G", "3V3") else f" (GPIO{pin})"), names[net], signal[net])):
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

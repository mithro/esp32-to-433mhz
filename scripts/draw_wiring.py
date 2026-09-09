#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Draw the jumper-wire hook-up of an ESP32-C3 SuperMini to each radio board,
using the socket adapter's GPIO assignment, as docs/images/wiring-<radio>.svg.

Wire colours follow the rainbow ribbon order the user asked for (brown GND,
red 3V3, orange GPIO5, yellow GPIO6, green GPIO7, blue GPIO8, purple GPIO9,
grey GPIO10).  GPIO8 and GPIO9 are boot straps the socket no longer uses, so
their blue and purple go instead to the power-row pins the socket does use at
those positions -- blue to GPIO3 (SCK), purple to GPIO1 (CSN/SCK/NSS) -- and
GPIO4 (MOSI) takes the ribbon's remaining colour, white.  GPIO5 is the
radio-type strap: for the
Ra-02 breakout it goes to GPIO0, which the firmware drives low while it reads
the strap (the SuperMini's only GND pin is taken by the brown wire); for a
CC1101 board it is left open.  The Ra-02 gets a tenth wire, black: DIO2 to
GPIO20.  It is not a header pin -- the carrier brings out DIO0 and nothing
else of the SX1278's six DIO lines -- so it is soldered to the module's pin-7
castellation, or to the carrier land just outside it, on the face away from
the header.  Continuous mode puts the raw bitstream on DIO2 alone, so OOK
receive and transmit need it; see
https://github.com/mithro/433mhz/blob/worktree-ra02-dio2-wire-diagram/hardware/devices/sx1278-ra02-dio2-wire.md

Boards: the blue E07-M1101D and the green D-Sun CC1101 boards, and the Ra-02
breakout.  All three plug into the same socket positions; only the names of
the signals at each position differ (the firmware uses a pin map per board),
so the three diagrams share one wiring layout.

Both boards are drawn from the back (deadbug style, the way they sit with
header pins pointing at you): the SuperMini top left, USB-C up, and the
radio board lower right with its header edge up.  Wires from the SuperMini's
GPIO column (on the right in this view) turn down the gap and along lanes
into the header from above; the power-column wires come down the
SuperMini's left side.  GND and 3V3 enter the header's first column from the
left at pin height; GPIO4 (MOSI) runs along the back of the radio board just
below the header and up into its pin; GPIO3 (SCK) and GPIO1 (CSN/NSS) take
lanes above the header and drop in.

The lane order was chosen by exhaustive search over which channel each wire
takes (above or below the header, or at pin height) and the order of the
lanes, counting every crossing between wire segments.  The remaining
crossings are forced: GND and 3V3 must swap once (G is above 3V3 on the
SuperMini but GND is the outer header row), and the wires bound for the
header's second and third columns from the SuperMini's left side have to
cross the GDO0/RST wire, which drops into the second column from the gap.
The Ra-02's DIO2 wire drops between the first two header columns to reach
its pad below the header.
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
    "1": ("purple", "#7d3fa8"),
    "10": ("grey", "#8c8c8c"),
    "4": ("white", "#f4f4f4"),
    "3": ("blue", "#2464c8"),
    "20": ("black", "#26262e"),  # the Ra-02's DIO2 wire, which is not a header pin
}
# SuperMini columns, top to bottom (front view, USB-C up).
SM_LEFT = ["5", "6", "7", "8", "9", "10", "20", "21"]
SM_RIGHT = ["5V", "G", "3V3", "4", "3", "2", "1", "0"]
# Socket position (numbered like the E07-M1101D: pin 1 right of the outer
# row seen from the front, even pins in the inner row, columns to -x) ->
# SuperMini pin, as on the socket adapter.
POS_PIN = {1: "G", 2: "3V3", 3: "10", 4: "1", 5: "3", 6: "4", 7: "7", 8: "6"}
# ... and -> the signal name printed on each radio board.
E07_NAMES = {1: "GND", 2: "VCC", 3: "GDO0", 4: "CSN", 5: "SCK", 6: "MOSI", 7: "MISO", 8: "GDO2"}
DSUN_NAMES = {1: "GND", 2: "VCC", 3: "MOSI", 4: "SCK", 5: "MISO", 6: "GDO2", 7: "GDO0", 8: "CSN"}
RA02_NAMES = {1: "GND", 2: "3V3", 3: "RST", 4: "NSS", 5: "SCK", 6: "MOSI", 7: "MISO", 8: "DIO0"}
DIO2_SIGNAL = "raw data, OOK RX and TX (DIO2/DATA)"
SIGNAL = {"GND": "ground", "VCC": "3.3 V", "3V3": "3.3 V", "MOSI": "SPI MOSI", "MISO": "SPI MISO", "SCK": "SPI clock",
          "CSN": "SPI chip select", "NSS": "SPI chip select", "GDO0": "IRQ / packet (GDO0)", "GDO2": "second IRQ (GDO2)",
          "RST": "reset (drive as an output)", "DIO0": "IRQ / packet (DIO0)"}
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
    # The USB-C connector is on the component (far) side and overhangs the top
    # edge.  Draw it first, poking past the top, then the board on top, so only
    # the overhanging sliver shows and the board hides the rest.
    v.rect(W / 2 - 4.4, -2.6, W / 2 + 4.4, 2.6, fill="#b9bdc5", stroke=INK, width=0.12, rx=1.1)
    v.rect(W / 2 - 2.9, -1.9, W / 2 + 2.9, 2.6, fill="#8b909a", stroke="none", width=0.0, rx=0.8)
    v.rect(0, 0, W, H, fill="#1f2430", stroke="#0b0d12", width=0.25, rx=0.6)
    v.text(W / 2 - 3.0, -3.7, "USB-C (far side)", size=0.85)  # the view is mirrored, so this lands right of centre, clear of the Ra-02 strap wire
    v.text(W / 2, 11.6, "ESP32-C3", size=1.1, fill="#ffffff", weight="bold")
    v.text(W / 2, 13.4, "SuperMini", size=1.1, fill="#ffffff", weight="bold")
    v.text(W / 2, 16.0, "back", size=0.9, fill="#ffffff")
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


LANE = 2.2  # mm between parallel wires (1.3 mm wide: 0.9 mm of daylight)


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
        # DIO2's land (module pin 7), on the far face in this view and near the
        # board's left edge, which is the edge facing the SuperMini.
        dio2 = (rb.BOARD_W - (rb.MOD_X + rb.mod_pad(7)[0]), rb.MOD_Y + rb.mod_pad(7)[1])
    smv, sm_pins = supermini_view()

    # Layout (mm).  SuperMini top left, back view: GPIO column on the right.
    # Radio board lower right, back view with the header up: its GND/VCC
    # column is the one nearest the gap.
    dio2_wire = radio == "ra02"
    sx, sy = 15.0, 15.5 if dio2_wire else 12.5  # room above for the strap looping over the SuperMini
    sm_bot = sy + smv.h
    # Lanes.  Gap (vertical, innermost first): DIO2, GDO0/RST, MISO, GDO2/DIO0.
    # Above the header (highest first): GDO2/DIO0, MISO, GDO0/RST, SCK, DIO2, CSN/NSS.
    # Left of the SuperMini (innermost first): CSN/NSS, SCK, MOSI, 3V3, GND.
    gap_order = (["20"] if dio2_wire else []) + ["10", "7", "6"]
    above_order = ["6", "7", "10", "3"] + (["20"] if dio2_wire else []) + ["1"]
    left_order = ["1", "3", "4", "3V3", "G"]
    gap_x = {p: sx + smv.w + 3.5 + i * LANE for i, p in enumerate(gap_order)}
    lane_y = {p: sm_bot + 2.0 + k * LANE for k, p in enumerate(above_order)}
    left_x = {p: sx - 2.5 - i * LANE for i, p in enumerate(left_order)}
    bx = max(gap_x.values()) + 5.0
    by = max(lane_y.values()) + 2.5 - cc.HDR_ROW_Y
    total_w = max(bx + board.w + 8.0, 104.0)  # room for the legend, top right
    hang = 8.5 if dio2_wire else 14.5  # the SMA jack, or the DIO2 note (below the size line), below the outline
    total_h = by + board.h + hang + 1.5
    legend_x, legend_y = bx + 2.0, 9.0  # the legend fills the corner right of the gap lanes, above the header lanes
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

    def above(pin: str, n: int, side: int = 0) -> None:
        """From the SuperMini pin along its gap or left lane, along its lane
        above the header, and down into socket position n: straight into an
        outer-row pin, or beside the column (side = +1 right, -1 left) and
        across into an inner-row pin."""
        (smx, smy), (hx, hy) = sp(pin), hp(n)
        vx = (gap_x[pin] if pin in gap_x else left_x[pin]) * S
        ly = lane_y[pin] * S
        pts = [(smx, smy), (vx, smy), (vx, ly)]
        if side:
            pts += [(hx + side * half, ly), (hx + side * half, hy), (hx, hy)]
        else:
            pts += [(hx, ly), (hx, hy)]
        wires.append((WIRES[pin][1], pts))

    above("6", 8, +1)  # GDO2/DIO0: outer gap lane, top lane, round the right of column D
    above("7", 7)  # MISO
    above("10", 3)  # GDO0/RST
    above("3", 5)  # SCK, from the left
    above("1", 4, +1)  # CSN/NSS, from the left, round the right of column B
    # GND and 3V3: straight into the first column from the left, at pin height.
    for n in (1, 2):
        pin = POS_PIN[n]
        (smx, smy), (hx, hy) = sp(pin), hp(n)
        wires.append((WIRES[pin][1], [(smx, smy), (left_x[pin] * S, smy), (left_x[pin] * S, hy), (hx, hy)]))
    # MOSI (GPIO4) -> position 6 (column C, inner row): along the back of the
    # radio board just below the header, then up into the pin.
    (smx, smy), (hx, hy) = sp("4"), hp(6)
    ly = hy + 3.0 * S
    wires.append((WIRES["4"][1], [(smx, smy), (left_x["4"] * S, smy), (left_x["4"] * S, ly), (hx, ly), (hx, hy)]))
    # Strap: GPIO5 over the top of the SuperMini to GPIO0 (Ra-02), or a free end (CC1101).
    (smx, smy) = sp("5")
    if dio2_wire:
        gx, gy = sp("0")
        over = (sy - 5.2) * S
        wires.append((WIRES["5"][1], [(smx, smy), (smx, over), (gx + 4.3 * S, over), (gx + 4.3 * S, gy), (gx, gy)]))
    else:
        wires.append((WIRES["5"][1], [(smx, smy), (gap_x["10"] * S, smy), (gap_x["10"] * S, smy - 3.5 * S)]))
    # DIO2 -> GPIO20: innermost gap lane, its lane above the header, then down
    # between the first two header columns to the pad's height and across.
    if dio2_wire:
        (smx, smy), (dx, dy) = sp("20"), px(*dio2, bx, by)
        vx, ly, drop = gap_x["20"] * S, lane_y["20"] * S, hp(1)[0] + half
        wires.append((WIRES["20"][1], [(smx, smy), (vx, smy), (vx, ly), (drop, ly), (drop, dy), (dx, dy)]))
    for fill, pts in wires:
        d = rounded_path(pts, 1.6 * S)
        parts.append(f'<path d="{d}" fill="none" stroke="{INK}" stroke-width="{1.3 * S:.1f}" stroke-linecap="round"/>')
        parts.append(f'<path d="{d}" fill="none" stroke="{fill}" stroke-width="{0.85 * S:.1f}" stroke-linecap="round"/>')
        for x, y in (pts[0], pts[-1]):  # crimp ends
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{0.8 * S:.1f}" fill="{fill}" stroke="{INK}" stroke-width="{0.15 * S:.1f}"/>')
    if dio2_wire:
        parts.append(f'<text x="{(sx + smv.w / 2) * S:.1f}" y="{(sy - 6.9) * S:.1f}" font-size="{0.95 * S:.1f}" font-family="Helvetica, Arial, sans-serif" fill="{INK}" text-anchor="middle" dy="0.36em">GPIO5 strap to GPIO0 (firmware drives GPIO0 low to read it)</text>')
    else:
        parts.append(f'<text x="{(gap_x["10"] + 1.2) * S:.1f}" y="{smy - 5.0 * S:.1f}" font-size="{0.95 * S:.1f}" font-family="Helvetica, Arial, sans-serif" fill="{INK}" text-anchor="middle" dy="0.36em">GPIO5: leave open</text>')
    if dio2_wire:
        for i, t in enumerate(("DIO2 is not on the header: solder to the module's pin-7 castellation,",
                               "or the land just outside it, on the face away from the header pins.")):
            parts.append(f'<text x="{(bx + board.w / 2) * S:.1f}" y="{(by + board.h + 5.6 + i * 1.6) * S:.1f}" font-size="{0.95 * S:.1f}" font-family="Helvetica, Arial, sans-serif" fill="{INK}" text-anchor="middle" dy="0.36em">{t}</text>')
    # The header's pins and their names again, on top of the wires: the pins
    # stand proud of the board, so a wire passing between two of them runs
    # beneath their tips.
    overlay = View(board.w, board.h, False)
    if dio2_wire:
        # The crimp covers DIO2's land, so outline it again over the wire: it is
        # on the far face, which is what the dashes mean.
        overlay.rect(dio2[0] - 0.7, dio2[1] - 0.6, dio2[0] + 0.7, dio2[1] + 0.6, fill="none", stroke="#ffffff", width=0.18, dash="1.2 1.0")
    for n in range(1, 9):
        hx, hy = hdr[n]
        outer = n % 2 == 1
        overlay.circle(hx, hy, 0.8, fill=PIN, stroke=INK, width=0.12)
        overlay.circle(hx, hy, 0.45, fill="#ffffff", stroke=INK, width=0.08)
        overlay.text(hx, hy + (-1.5 if outer else 1.5), names[n], size=1.05, anchor="start" if outer else "end", angle=-90, weight="bold", halo=True)
    parts.append(overlay.svg_group(bx * S, by * S, "", 0, 0))
    # ... and the SuperMini's pin names (the strap wire runs over some of them).
    overlay = View(smv.w, smv.h, True)
    for i in range(8):
        y = sm.PIN_TOP_Y + i * sm.PITCH
        overlay.text(2.6, y, SM_LEFT[i], size=0.95, anchor="end", weight="bold", halo=True)
        overlay.text(smv.w - 2.6, y, SM_RIGHT[i], size=0.95, anchor="start", weight="bold", halo=True)
    parts.append(overlay.svg_group(sx * S, sy * S, "", 0, 0))

    # Legend: one row per wire, in socket-position order plus the strap, in
    # the corner right of the gap lanes and above the header lanes.
    ly0, margin = legend_y, legend_x
    cols = ((margin + 10.5, "SuperMini"), (margin + 20.5, radio_col), (margin + 32.5, "Signal"))
    parts.append(f'<text x="{margin * S:.1f}" y="{ly0 * S:.1f}" font-size="{1.1 * S:.1f}" font-family="Helvetica, Arial, sans-serif" font-weight="bold" fill="{INK}" dy="0.36em">Wire</text>')
    for x, t in cols:
        parts.append(f'<text x="{x * S:.1f}" y="{ly0 * S:.1f}" font-size="{1.1 * S:.1f}" font-family="Helvetica, Arial, sans-serif" font-weight="bold" fill="{INK}" dy="0.36em">{t}</text>')
    rows = [(POS_PIN[n], names[n], SIGNAL[names[n]]) for n in range(1, 9)]
    rows.append(("5", "GPIO0" if dio2_wire else "(none)", "radio-type strap" + (", to GPIO0" if dio2_wire else ", left open")))
    if dio2_wire:
        rows.append(("20", "DIO2 (pin 7)", DIO2_SIGNAL))
    for i, (pin, name, signal) in enumerate(rows):
        colour, fill = WIRES[pin]
        y = ly0 + 2.0 + i * 1.9
        parts.append(f'<rect x="{margin * S:.1f}" y="{(y - 0.55) * S:.1f}" width="{3.6 * S:.1f}" height="{1.1 * S:.1f}" fill="{fill}" stroke="{INK}" stroke-width="{0.1 * S:.1f}" rx="{0.45 * S:.1f}"/>')
        parts.append(f'<text x="{(margin + 4.3) * S:.1f}" y="{y * S:.1f}" font-size="{1.0 * S:.1f}" font-family="Helvetica, Arial, sans-serif" fill="{INK}" dy="0.36em">{colour}</text>')
        for (x, _), t in zip(cols, (pin if pin in ("G", "3V3") else f"{pin} (GPIO{pin})", name, signal)):
            parts.append(f'<text x="{x * S:.1f}" y="{y * S:.1f}" font-size="{1.0 * S:.1f}" font-family="Helvetica, Arial, sans-serif" fill="{INK}" dy="0.36em">{t}</text>')
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

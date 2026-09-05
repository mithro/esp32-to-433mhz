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

The radio board is drawn with its header edge at the top (front view, as in
the pinout diagram) and the SuperMini to its right, USB-C up.  Wires leave
the SuperMini's GPIO column straight into the gap between the boards; the
ones from its other column (GND, 3V3, GPIO0) go round the SuperMini's ends.
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
    """Front view of the SuperMini with every pin named; returns the pin centres (mm)."""
    W, H = sm.BOARD_W, sm.BOARD_H
    v = View(W, H, False)
    v.rect(0, 0, W, H, fill="#1f2430", stroke="#0b0d12", width=0.25, rx=0.6)
    v.rect(W / 2 - 4.5, -1.5, W / 2 + 4.5, 5.85, fill="#c9ced6", stroke=INK, width=0.12, rx=0.8)
    v.text(W / 2, 2.4, "USB-C", size=1.0)
    for dx in (-2.95, 2.95):
        v.circle(W / 2 + dx, 8.84, 1.3, fill="#d9d9d9", stroke=INK, width=0.1)
    v.text(W / 2 - 2.95, 11.2, "BOOT", size=0.7)
    v.text(W / 2 + 2.95, 11.2, "RST", size=0.7)
    v.rect(W / 2 - 2.5, 12.0, W / 2 + 2.5, 17.0, fill="#3a3f4b", stroke=INK, width=0.1)
    v.text(W / 2, 14.5, "ESP32-C3", size=0.8, fill="#ffffff")
    v.rect(5.5, H - 2.6, 12.5, H, fill="#e8e2d0", stroke=INK, width=0.1)
    v.text(W / 2, H - 1.3, "ANT", size=0.7)
    pins = {}
    for i in range(8):
        y = sm.PIN_TOP_Y + i * sm.PITCH
        for x, name, anchor, lx in ((sm.PIN_EDGE_X, SM_LEFT[i], "start", 2.6), (W - sm.PIN_EDGE_X, SM_RIGHT[i], "end", W - 2.6)):
            v.circle(x, y, 0.8, fill=PIN, stroke=INK, width=0.12)
            v.circle(x, y, 0.45, fill="#ffffff", stroke=INK, width=0.08)
            v.text(lx, y, name, size=0.95, anchor=anchor, fill="#ffffff", weight="bold")
            pins[name] = (x, y)
    return v, pins


def rounded_path(pts: list[tuple[float, float]], r: float) -> str:
    """SVG path through the points with corners rounded by r (px)."""
    d = [f"M {pts[0][0]:.1f} {pts[0][1]:.1f}"]
    for i in range(1, len(pts) - 1):
        (x0, y0), (x1, y1), (x2, y2) = pts[i - 1], pts[i], pts[i + 1]
        # points r before and after the corner along each leg
        l1 = max(((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5, 1e-6)
        l2 = max(((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5, 1e-6)
        rr = min(r, l1 / 2, l2 / 2)
        ax, ay = x1 - (x1 - x0) / l1 * rr, y1 - (y1 - y0) / l1 * rr
        bx, by = x1 + (x2 - x1) / l2 * rr, y1 + (y2 - y1) / l2 * rr
        d.append(f"L {ax:.1f} {ay:.1f} Q {x1:.1f} {y1:.1f} {bx:.1f} {by:.1f}")
    d.append(f"L {pts[-1][0]:.1f} {pts[-1][1]:.1f}")
    return " ".join(d)


def draw(radio: str) -> None:
    title, gdo0, gdo2, csn = RADIOS[radio]
    if radio == "cc1101":
        board = e07_views()[0]
        W = cc.BOARD_W
        hdr = {n: (W - cc.HDR_COL_X - ((n - 1) // 2) * cc.PITCH, cc.HDR_ROW_Y + ((n - 1) % 2) * cc.PITCH) for n in range(1, 9)}
    else:
        board = ra02_views()[0]
        # the breakout numbers its header from the left; map E07 positions onto it
        pos = {n: (rb.hdr_x(n), rb.hdr_y(n)) for n in range(1, 9)}
        hdr = {n: pos[{1: 7, 2: 8, 3: 5, 4: 6, 5: 3, 6: 4, 7: 1, 8: 2}[n]] for n in range(1, 9)}
    smv, sm_pins = supermini_view()

    # Layout (mm): radio board left, SuperMini right, header rows level with the SuperMini's top pins.
    margin, gap = 8.0, 34.0
    top = 12.0
    bx, by = margin, top + 6.0
    sx, sy = margin + board.w + gap, top
    hang = 12.5 if radio == "cc1101" else 4.0  # the E07's SMA jack, or the size caption, below the outline
    total_w = sx + smv.w + margin + 2.0
    total_h = max(by + board.h + hang, sy + smv.h) + 26.0
    px = lambda x, y, ox, oy: ((ox + x) * S, (oy + y) * S)  # noqa: E731

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_w * S:.0f}" height="{total_h * S:.0f}" viewBox="0 0 {total_w * S:.0f} {total_h * S:.0f}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{total_w * S / 2:.1f}" y="{3.0 * S:.1f}" font-size="{2.0 * S:.1f}" font-family="Helvetica, Arial, sans-serif" font-weight="bold" fill="{INK}" text-anchor="middle" dy="0.36em">ESP32-C3 SuperMini to {title} with jumper wires</text>',
        f'<text x="{total_w * S / 2:.1f}" y="{5.6 * S:.1f}" font-size="{1.2 * S:.1f}" font-family="Helvetica, Arial, sans-serif" fill="{INK}" text-anchor="middle" dy="0.36em">Same pins as the socket adapter, front views (component side up)</text>',
        board.svg_group(bx * S, by * S, "", 0, 0),
        smv.svg_group(sx * S, sy * S, "", 0, 0),
    ]

    # Wires.  Lanes in the gap between the boards run vertically; lanes above
    # the radio board run horizontally to the header pins.  Outer-row pins are
    # entered straight from above; inner-row pins from the side, by a drop
    # between the header columns, so no wire runs over another pin.  The
    # strap (GPIO5) is a ninth wire: to the Ra-02's GND pin, or a free end.
    order = [7, 8, 5, 6, 3, 4, 1, 2]  # header pins from the left column to the right
    lane_x0 = bx + board.w + 3.0
    lane_y0 = by - 3.0
    half = cc.PITCH / 2 * S

    def to_header(n: int, ly: float) -> list[tuple[float, float]]:
        hx, hy = px(*hdr[n], bx, by)
        if n % 2:  # outer row
            return [(hx, hy), (hx, ly)]
        return [(hx, hy), (hx + half, hy), (hx + half, ly)]

    def from_supermini(pin: str, lx: float) -> list[tuple[float, float]]:
        smx, smy = px(*sm_pins[pin], sx, sy)
        if pin in SM_LEFT:
            return [(lx, smy), (smx, smy)]
        if pin in ("G", "3V3"):  # round the top of the SuperMini
            over = (sy - 3.5 - (0 if pin == "G" else 1.0)) * S
            right = (sx + smv.w + 3.0 + (0 if pin == "G" else 1.0)) * S
            return [(lx, over), (right, over), (right, smy), (smx, smy)]
        under = (sy + smv.h + 3.5) * S  # GPIO0: round the bottom
        right = (sx + smv.w + 3.0) * S
        return [(lx, under), (right, under), (right, smy), (smx, smy)]

    wires = []
    for i, n in enumerate(order):
        net = E07_NETS[n]
        colour, fill, pin = WIRES[net]
        lx, ly = (lane_x0 + i * 1.0) * S, (lane_y0 - i * 1.0) * S
        head = to_header(n, ly)
        wires.append((fill, head + [(lx, ly)] + from_supermini(pin, lx), net))
    colour, fill, pin = WIRES["RADIO_ID"]
    lx = (lane_x0 + 8.0) * S
    smx, smy = px(*sm_pins[pin], sx, sy)
    if radio == "ra02":  # to the same GND pin as the brown wire, entering beside it
        hx, hy = px(*hdr[1], bx, by)
        ly = (lane_y0 - 8.0) * S
        wires.append((fill, [(hx + 0.5 * S, hy), (hx + half, hy - 0.4 * S), (hx + half, ly), (lx, ly), (lx, smy), (smx, smy)], "RADIO_ID"))
    else:  # left open: a stub with a free end
        wires.append((fill, [(smx, smy), (lx + 2.0 * S, smy)], "RADIO_ID"))
    for fill, pts, net in reversed(wires):  # outer-row wires (drawn last) stay on top at the header
        d = rounded_path(pts, 1.6 * S)
        parts.append(f'<path d="{d}" fill="none" stroke="{INK}" stroke-width="{1.3 * S:.1f}" stroke-linecap="round"/>')
        parts.append(f'<path d="{d}" fill="none" stroke="{fill}" stroke-width="{0.85 * S:.1f}" stroke-linecap="round"/>')
        for x, y in (pts[0], pts[-1]):  # crimp ends
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{0.8 * S:.1f}" fill="{fill}" stroke="{INK}" stroke-width="{0.15 * S:.1f}"/>')
    if radio == "cc1101":
        parts.append(f'<text x="{lx + 2.0 * S:.1f}" y="{smy - 2.0 * S:.1f}" font-size="{0.95 * S:.1f}" font-family="Helvetica, Arial, sans-serif" fill="{INK}" text-anchor="middle" dy="0.36em">leave open</text>')
    # The header's pin names again, on top of the wires (with a halo).
    overlay = View(board.w, board.h, False)
    for n in range(1, 9):
        hx, hy = hdr[n]
        name = cc.PIN_NAMES[str(n)] if radio == "cc1101" else rb.HDR_LABELS[str({1: 7, 2: 8, 3: 5, 4: 6, 5: 3, 6: 4, 7: 1, 8: 2}[n])]
        outer = n % 2 == 1
        overlay.text(hx, hy + (-1.5 if outer else 1.5), name, size=1.05, anchor="start" if outer else "end", angle=-90, weight="bold", halo=True)
    parts.append(overlay.svg_group(bx * S, by * S, "", 0, 0))

    # Legend
    ly0 = max(by + board.h + hang, sy + smv.h) + 4.0
    parts.append(f'<text x="{margin * S:.1f}" y="{ly0 * S:.1f}" font-size="{1.2 * S:.1f}" font-family="Helvetica, Arial, sans-serif" font-weight="bold" fill="{INK}" dy="0.36em">Wire</text>')
    cols = ((margin + 12, "SuperMini"), (margin + 24, "Ra-02 breakout" if radio == "ra02" else "E07-M1101D"), (margin + 40, "Signal"))
    for x, t in cols:
        parts.append(f'<text x="{x * S:.1f}" y="{ly0 * S:.1f}" font-size="{1.2 * S:.1f}" font-family="Helvetica, Arial, sans-serif" font-weight="bold" fill="{INK}" dy="0.36em">{t}</text>')
    names = {"GND": "GND", "+3V3": "VCC" if radio == "cc1101" else "3V3", "RADIO_ID": "GND" if radio == "ra02" else "(none)",
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

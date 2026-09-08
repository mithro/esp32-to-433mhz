#!/usr/bin/env python3
"""Generate the ESP32-C3 SuperMini <-> D-SUN CC1101 wiring diagram (SVG + PNG).

    uv run --with cairosvg hardware/devices/pinouts/esp32c3-cc1101-node-wiring.py

Pin assignments are the single source of truth in WIRES below and must match
hardware/devices/esp32c3-cc1101-node.md and the spec (docs/superpowers/specs/
2026-08-20-esp32c3-cc1101-tasmota-design.md §3.1).
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_SVG = os.path.join(HERE, "esp32c3-cc1101-node-wiring.svg")
OUT_PNG = os.path.join(HERE, "esp32c3-cc1101-node-wiring.png")

# (D-SUN pin, ESP32-C3 pin label, role, colour)
WIRES = [
    ("VCC",  "3V3",    "3.3 V supply (module is 3.3 V ONLY)", "#d62728"),
    ("GND",  "GND",    "ground",                              "#000000"),
    ("SCK",  "GPIO4",  "SPI clock",                           "#ff7f0e"),
    ("MOSI", "GPIO6",  "SPI MOSI (SI)",                       "#2ca02c"),
    ("MISO", "GPIO5",  "SPI MISO (SO)",                       "#1f77b4"),
    ("CSN",  "GPIO7",  "chip select",                         "#9467bd"),
    ("GDO0", "GPIO3",  "FSK pkt IRQ / OOK TX data in (RMT out)", "#8c564b"),
    ("GDO2", "GPIO10", "OOK RX data out (RMT capture in)",    "#e377c2"),
]
# SuperMini header as seen USB-C at top: left column top->bottom, right column top->bottom
ESP_LEFT  = ["5V", "GND", "3V3", "GPIO4", "GPIO3", "GPIO2", "GPIO1", "GPIO0"]
ESP_RIGHT = ["GPIO5", "GPIO6", "GPIO7", "GPIO8", "GPIO9", "GPIO10", "GPIO20", "GPIO21"]
STRAPPING = {"GPIO2", "GPIO8", "GPIO9"}
# D-SUN 2x4 header as read from the module silkscreen, row by row (left, right)
DSUN_ROWS = [("VCC", "GND"), ("SCK", "MOSI"), ("GDO2", "MISO"), ("CSN", "GDO0")]


def build_svg():
    W, H = 1320, 520
    s = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" font-family="DejaVu Sans, sans-serif" font-size="13">' % (W, H),
         '<rect width="100%" height="100%" fill="white"/>',
         '<text x="20" y="28" font-size="18" font-weight="bold">ESP32-C3 SuperMini  ↔  D-SUN CC1101 (2×4 header)  —  433 MHz node wiring</text>',
         '<text x="20" y="48" fill="#555">All 3.3 V. Avoid GPIO2/8/9 (strapping), GPIO20/21 (UART0), GPIO18/19 (USB). GDO0=GPIO3, GDO2=GPIO10.</text>']
    # ESP board
    ex, ey, ew, eh = 120, 90, 180, 380
    s.append('<rect x="%d" y="%d" width="%d" height="%d" rx="10" fill="#eef" stroke="#335"/>' % (ex, ey, ew, eh))
    s.append('<rect x="%d" y="%d" width="40" height="14" fill="#999"/><text x="%d" y="%d" font-size="11">USB-C</text>' % (ex + ew / 2 - 20, ey - 14, ex + ew / 2 + 24, ey - 3))
    pin_y = {}
    for i, (l, r) in enumerate(zip(ESP_LEFT, ESP_RIGHT)):
        y = ey + 30 + i * 42
        for name, x, anchor, tx in ((l, ex, "end", ex - 8), (r, ex + ew, "start", ex + ew + 8)):
            fill = "#fdd" if name in STRAPPING else "#fff"
            s.append('<circle cx="%d" cy="%d" r="6" fill="%s" stroke="#333"/>' % (x, y, fill))
            s.append('<text x="%d" y="%d" text-anchor="%s">%s</text>' % (tx, y + 4, anchor, name))
            pin_y[name] = (x, y)
    s.append('<text x="%d" y="%d" text-anchor="middle" fill="#a00" font-size="11">pink = strapping pin, do not use</text>' % (ex + ew / 2, ey + eh - 10))
    # D-SUN module
    dx, dy, dw, dh = 640, 150, 200, 230
    s.append('<rect x="%d" y="%d" width="%d" height="%d" rx="8" fill="#efe" stroke="#353"/>' % (dx, dy, dw, dh))
    # title is centered over the body's left portion, clear of the antenna
    # line/stub at the top-right corner, so its "z" doesn't get clipped
    s.append('<text x="%d" y="%d" text-anchor="middle" font-weight="bold">D-SUN CC1101 433 MHz</text>' % (dx + (dw - 40) / 2, dy - 10))
    s.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#353" stroke-width="3"/><text x="%d" y="%d" font-size="11">antenna</text>' % (dx + dw - 20, dy, dx + dw - 20, dy - 60, dx + dw - 12, dy - 40))
    dsun_xy = {}
    for i, (l, r) in enumerate(DSUN_ROWS):
        y = dy + 40 + i * 50
        # labels drawn *inside* the body so arriving wires never cross the text
        for name, x, anchor, tx in ((l, dx, "start", dx + 12), (r, dx + dw, "end", dx + dw - 12)):
            s.append('<rect x="%d" y="%d" width="12" height="12" fill="#fff" stroke="#333"/>' % (x - 6, y - 6))
            s.append('<text x="%d" y="%d" text-anchor="%s">%s</text>' % (tx, y + 4, anchor, name))
            dsun_xy[name] = (x, y)
    # wires: ESP pin -> D-SUN pin, routed through a mid column
    dsun_right = {r for _, r in DSUN_ROWS}
    for k, (dpin, epin, role, colour) in enumerate(WIRES):
        (x1, y1), (x2, y2) = pin_y[epin], dsun_xy[dpin]
        xm = 430 + k * 22
        pts = [(x1, y1)]
        y1b = y1 + 16
        if epin in ESP_LEFT:
            # jog off the left-column ESP pin between rows so the wire clears
            # the right-column pin circle/label sitting on the same row
            pts += [(x1 + 12, y1), (x1 + 12, y1b), (xm, y1b)]
        else:
            # same 16px jog, mirrored inward, so the wire clears its OWN
            # right-column label (drawn on the same row, just past the pin)
            # instead of running straight through it
            pts += [(x1 - 12, y1), (x1 - 12, y1b), (xm, y1b)]
        if dpin in dsun_right:
            # this pin is on the D-SUN's far (right) column, so the wire must
            # cross the whole body -- dip below the row so it clears the
            # near-side (left-column) pin circle/label on its way in, then
            # rise onto the target pin from the right, past its own label
            y2b = y2 + 16
            pts += [(xm, y2b), (dx + 12, y2b), (x2, y2b), (x2, y2)]
        else:
            pts += [(xm, y2), (x2, y2)]
        pts_str = " ".join("%d,%d" % (px, py) for px, py in pts)
        s.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="2.5"/>' % (pts_str, colour))
    # legend
    ly = 100
    lx = 930
    s.append('<text x="%d" y="%d" font-weight="bold">Wire list</text>' % (lx, ly - 16))
    for k, (dpin, epin, role, colour) in enumerate(WIRES):
        s.append('<rect x="%d" y="%d" width="14" height="4" fill="%s"/>' % (lx, ly + k * 20 - 4, colour))
        s.append('<text x="%d" y="%d" font-size="12">%s ← %s — %s</text>' % (lx + 20, ly + k * 20, dpin, epin, role))
    s.append('</svg>')
    return "\n".join(s)


def main():
    svg = build_svg()
    with open(OUT_SVG, "w") as f:
        f.write(svg + "\n")
    import cairosvg
    cairosvg.svg2png(bytestring=svg.encode(), write_to=OUT_PNG, output_width=1960)
    print("wrote", OUT_SVG, OUT_PNG)


if __name__ == "__main__":
    main()

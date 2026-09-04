#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Generate a KiCad 9 project reproducing the blue "SX1278 LoRa 433MHz v4.0"
breakout: an Ai-Thinker Ra-02 LoRa module (IPEX antenna) on a small carrier
with a 2x4 2.54 mm male header on its back.

Sources:

* Breakout outline, header position and header pinout: the user's photos
  (2026-09-04), scaled from the 2.54 mm header pitch, so +/- 0.3 mm.  The
  header's back-side silk grid, read with the header at the bottom, is
  MISO/DIO0, SCK/MOSI, RST/NSS, GND/3V3 per column (first name in the row
  nearest the edge).
* Ra-02 module: Ai-Thinker "Ra-02 Specifications V1.0" (2019), section 3
  (17 x 16 x 3.2 mm, pads on the two 17 mm edges at 2.0 mm pitch, 1.2 mm
  long, first pad 1.5 mm from the end, R0.45 half-holes, IPEX 1.5 / 1.0 mm
  from the pin-1 corner) and section 4 (pin table: 1 GND, 2 GND, 3 3.3V,
  4 RESET, 5 DIO0, 6 DIO1, 7 DIO2, 8 DIO3, 9 GND, 10 DIO4, 11 DIO5, 12 SCK,
  13 MISO, 14 MOSI, 15 NSS, 16 GND; pins 1-8 down one edge, 9-16 up the
  other, counter-clockwise seen from the top with the IPEX at the pin-1
  corner).

Everything below is drawn as seen from the breakout's component (Ra-02)
side with the header edge at the top, which is how it sits on the carrier.
The module then has its IPEX at the bottom-right, pins 1-8 up the right
edge and 9-16 down the left edge.  The breakout's own decoupling capacitors
are not modelled.  Copper: header-to-module tracks (front, with three nets
crossing on the back through vias, as the real board does) and a GND pour
on both sides.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from kicadgen import Design, Footprint, Pad, Part, SymbolRef, Track, Via, Zone, fp_circle, fp_rect, fp_text, gr_rect, gr_text  # noqa: E402

PROJECT = "sx1278-ra02-breakout"
BOARD_W, BOARD_H = 17.5, 22.5
PITCH = 2.54
HDR_ROW_IN = 1.3  # outer row from the header edge (inner row 2.54 further)
HDR_PAD, HDR_HOLE = 1.5, 0.9
GRID_Y = 5.8  # top of the back-side name grid
# Ra-02 module on the breakout (its 16 mm side across the board)
MOD_W, MOD_H = 16.0, 17.0
MOD_X, MOD_Y = 0.2, BOARD_H - MOD_H  # 0.2, 5.5: flush with the far edge
MOD_PITCH = 2.0
MOD_FIRST = 1.5  # first pad centre from the module end
MOD_HALF_HOLE = 0.9
LAND_L, LAND_W = 1.4, 1.2  # land pads along the module edges
IPEX = (MOD_W - 1.0, MOD_H - 1.5)  # centre, module coordinates (bottom-right corner here)

HDR_NETS = {"1": "MISO", "2": "DIO0", "3": "SCK", "4": "MOSI", "5": "RESET", "6": "NSS", "7": "GND", "8": "+3V3"}
HDR_LABELS = {"1": "MISO", "2": "DIO0", "3": "SCK", "4": "MOSI", "5": "RST", "6": "NSS", "7": "GND", "8": "3V3"}
MOD_NAMES = ["GND", "GND", "3.3V", "RESET", "DIO0", "DIO1", "DIO2", "DIO3", "GND", "DIO4", "DIO5", "SCK", "MISO", "MOSI", "NSS", "GND"]
MOD_NETS = {str(i + 1): {"3.3V": "+3V3"}.get(n, n) for i, n in enumerate(MOD_NAMES)}

CONN16 = SymbolRef("Connector_Generic.kicad_sym", "Connector_Generic", "Conn_01x16")
CONN2X4 = SymbolRef("Connector_Generic.kicad_sym", "Connector_Generic", "Conn_02x04_Odd_Even")


def hdr_x(pin: int) -> float:
    return BOARD_W / 2 - 1.5 * PITCH + ((pin - 1) // 2) * PITCH


def hdr_y(pin: int) -> float:
    return HDR_ROW_IN + ((pin - 1) % 2) * PITCH


def mod_pad(pin: int) -> tuple[float, float]:
    """Land centre of module pin 1..16 in module coordinates (origin top-left
    on the breakout): 1-8 up the right edge, 9-16 down the left edge."""
    if pin <= 8:
        return (MOD_W - LAND_L / 2 + 0.8, MOD_H - MOD_FIRST - (pin - 1) * MOD_PITCH)
    return (LAND_L / 2 - 0.1, MOD_FIRST + (pin - 9) * MOD_PITCH)


def header_fp() -> Footprint:
    pads = [Pad(str(n), (((n - 1) // 2) * PITCH, ((n - 1) % 2) * PITCH), (HDR_PAD, HDR_PAD), "thru_hole", "rect" if n == 1 else "circle", HDR_HOLE) for n in range(1, 9)]
    return Footprint(
        name="PinHeader_2x04_P2.54mm_Ra02_Breakout",
        descr="2x4 2.54 mm male header of the SX1278 Ra-02 breakout, fitted on the back: pin 1 square at the left of the outer row, pin 2 below it, columns stepping to +x; 1.5 mm pads, 0.9 mm holes",
        tags="pin header 2.54mm 2x04 SX1278 Ra-02 breakout",
        pads=pads,
        ref_pos=(3 * PITCH + 1.8, PITCH / 2, 90),
        value_pos=(1.5 * PITCH, PITCH + 2.0),
    )


def ra02_fp() -> Footprint:
    """Land pattern of the Ra-02 in the breakout's orientation (origin at the
    module's top-left corner; IPEX at the bottom-right)."""
    pads = []
    for pin in range(1, 17):
        x, y = mod_pad(pin)
        pads.append(Pad(str(pin), (x, y), (LAND_L, LAND_W), "smd", "rect"))
    extra = [
        fp_rect("ra02:outline", 0, 0, MOD_W, MOD_H, "F.Fab", 0.1),
        fp_rect("ra02:can", 1.0, 0.8, MOD_W - 1.4, MOD_H - 3.2, "F.Fab", 0.1, "dash"),
        fp_text("ra02:label", "Ra-02 (SX1278)", MOD_W / 2, MOD_H / 2 - 1.5, "F.Fab", 0.8),
        fp_circle("ra02:ipex", IPEX[0], IPEX[1], 1.3, "F.Fab", 0.1),
        fp_text("ra02:ipexlbl", "IPEX", IPEX[0] - 2.6, IPEX[1], "F.Fab", 0.6),
    ]
    for pin in range(1, 17):
        x, y = mod_pad(pin)
        dx = -1.4 if pin <= 8 else 1.4
        extra.append(fp_text(f"ra02:name{pin}", MOD_NAMES[pin - 1], x + dx, y, "F.Fab", 0.5, 0, "right" if pin <= 8 else "left"))
    return Footprint(
        name="Ra-02_LoRa_Module_Land",
        descr="Land pattern for the Ai-Thinker Ra-02 LoRa module (17 x 16 mm, 16 castellations at 2.0 mm on the 17 mm edges), oriented with pins 1-8 up the right edge and 9-16 down the left edge; IPEX at the bottom-right",
        tags="Ra-02 SX1278 LoRa module land pattern",
        pads=pads,
        extra=extra,
        attr="smd",
        ref_pos=(MOD_W / 2, MOD_H / 2 + 1.5, 0),
        value_pos=(MOD_W / 2, MOD_H / 2 + 3.0),
    )


def build() -> Design:
    d = Design(
        project=PROJECT,
        title="SX1278 LoRa 433MHz v4.0 breakout (Ai-Thinker Ra-02)",
        comment="Outline, 2x4 back-side header and Ra-02 land pattern of the blue SX1278 LoRa 433MHz v4.0 breakout",
        fp_lib="Ra02Breakout",
        width=BOARD_W,
        height=BOARD_H,
        thickness=1.6,
        sch_note="Blue SX1278 LoRa 433MHz v4.0 breakout.\\nJ1 = 2x4 header on the back (odd pins in the outer row, pin 1 at the left), U1 = Ai-Thinker Ra-02.\\nViewed from the Ra-02 side with the header edge at the top; the IPEX is at the bottom-right.",
    )
    bx, by = d.bx, d.by
    X = lambda v: bx + v  # noqa: E731
    Y = lambda v: by + v  # noqa: E731
    mx = lambda pin: MOD_X + mod_pad(pin)[0]  # noqa: E731  board coordinates of a module land
    my = lambda pin: MOD_Y + mod_pad(pin)[1]  # noqa: E731
    d.parts.append(Part("J1", header_fp(), (X(hdr_x(1)), Y(hdr_y(1))), CONN2X4, "SX1278_Ra-02_breakout", HDR_NETS, (76.2, 101.6), "2x4 header (on the back)"))
    d.parts.append(Part("U1", ra02_fp(), (X(MOD_X), Y(MOD_Y)), CONN16, "Ra-02", MOD_NETS, (114.3, 101.6), "Ai-Thinker Ra-02 LoRa module"))

    T, V, F, B = d.tracks, d.vias, "F.Cu", "B.Cu"

    def track(net: str, layer: str, pts: list[tuple[float, float]], width: float = 0.25) -> None:
        T.append(Track(net, layer, width, [(X(x), Y(y)) for x, y in pts]))

    # Front: nested lanes from the left-edge lands (SCK 12, MOSI 14, NSS 15)
    # and the right-edge land RESET (4) into the header.
    track("SCK", F, [(mx(12), my(12)), (2.4, my(12)), (2.4, 5.1), (hdr_x(3) - PITCH / 2, 5.1), (hdr_x(3) - PITCH / 2, hdr_y(3)), (hdr_x(3), hdr_y(3))])
    track("MOSI", F, [(mx(14), my(14)), (3.0, my(14)), (3.0, 5.7), (hdr_x(4), 5.7), (hdr_x(4), hdr_y(4))])
    track("NSS", F, [(mx(15), my(15)), (3.6, my(15)), (3.6, 6.3), (hdr_x(6), 6.3), (hdr_x(6), hdr_y(6))])
    track("RESET", F, [(mx(4), my(4)), (14.0, my(4)), (14.0, 5.1), (hdr_x(5) + PITCH / 2, 5.1), (hdr_x(5) + PITCH / 2, hdr_y(5)), (hdr_x(5), hdr_y(5))])
    # Back, through vias: MISO (13), DIO0 (5) and 3V3 (3) cross the front lanes.
    for net, pin, via in (("MISO", 13, (2.2, my(13))), ("DIO0", 5, (15.0, my(5))), ("+3V3", 3, (13.0, my(3)))):
        track(net, F, [(mx(pin), my(pin)), via])
        V.append(Via(net, (X(via[0]), Y(via[1]))))
    track("MISO", B, [(2.2, my(13)), (2.2, hdr_y(1)), (hdr_x(1), hdr_y(1))])
    track("+3V3", B, [(13.0, my(3)), (13.0, hdr_y(8)), (hdr_x(8), hdr_y(8))], 0.4)
    track("DIO0", B, [(15.0, my(5)), (15.0, 18.2), (hdr_x(2), 18.2), (hdr_x(2), hdr_y(2))])
    # GND: pours on both sides (solid pad connections, the board is tiny); a
    # via in each GND land ties it to the back pour as well.
    for pin, vx in ((1, 16.0), (2, 16.0), (9, 1.0), (16, 1.0)):
        V.append(Via("GND", (X(vx), Y(my(pin)))))
    m = 0.3
    for layer in ("F.Cu", "B.Cu"):
        d.zones.append(Zone("GND", (layer,), f"gnd_{layer[0].lower()}", [(X(m), Y(m)), (X(BOARD_W - m), Y(m)), (X(BOARD_W - m), Y(BOARD_H - m)), (X(m), Y(BOARD_H - m))], solid_pads=True))

    g = d.graphics
    # Header labels on the back, as printed on the real board: a grid below
    # the header, outer-row names in the first line, inner-row names in the
    # second (the front is covered by the module there).
    # Header pin numbers under each pad (outer-row numbers between the rows,
    # inner-row numbers below the inner row) and the name grid below that.
    for n, lab in HDR_LABELS.items():
        pin = int(n)
        g.append(gr_text(f"hdr_bn{n}", n, X(hdr_x(pin)), Y(hdr_y(1) + PITCH / 2 if pin % 2 else hdr_y(2) + 1.25), "B.SilkS", 0.5, "mirror"))
        yl = GRID_Y + 0.7 if pin % 2 else GRID_Y + 2.0
        g.append(gr_text(f"hdr_b{n}", lab, X(hdr_x(pin)), Y(yl), "B.SilkS", 0.5, "mirror"))
    g.append(gr_rect("hdr_box", X(hdr_x(1) - 1.27), Y(0.3), X(hdr_x(7) + 2.4), Y(GRID_Y), "B.SilkS", 0.12))
    g.append(gr_rect("lbl_box", X(hdr_x(1) - 1.27), Y(GRID_Y), X(hdr_x(7) + 2.4), Y(GRID_Y + 2.7), "B.SilkS", 0.12))
    # Pin names, rotated, in the gap right of each header column (outer-row
    # name level with the outer pad, inner-row name with the inner pad), on
    # both sides: the only part of the front the module leaves visible.
    for n, lab in HDR_LABELS.items():
        pin = int(n)
        xg = hdr_x(pin) + PITCH / 2
        yn = hdr_y(pin) + (0.2 if pin % 2 else 0)
        g.append(gr_text(f"pn_f{n}", lab, X(xg), Y(yn), "F.SilkS", 0.5, None, 90))
        g.append(gr_text(f"pn_b{n}", lab, X(xg), Y(yn), "B.SilkS", 0.5, "mirror", 270))
    # Ra-02 pin numbers beside each land, on the back (the module covers the front).
    for pin in range(1, 17):
        xn = mx(pin) - 1.9 if pin <= 8 else mx(pin) + 2.0
        g.append(gr_text(f"mod_bn{pin}", str(pin), X(xn), Y(my(pin)), "B.SilkS", 0.5, "mirror"))
    g.append(gr_text("name_b", "SX1278 LoRa 433MHz v4.0", X(BOARD_W / 2), Y(15.0), "B.SilkS", 0.6, "mirror", 90))
    g.append(gr_text("name_f", "SX1278 LoRa 433MHz v4.0", X(BOARD_W / 2), Y(BOARD_H - 1.2), "F.Fab", 0.6))
    return d


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=pathlib.Path, default=pathlib.Path(__file__).resolve().parent.parent / "hardware" / PROJECT)
    args = ap.parse_args()
    build().write(args.out)


if __name__ == "__main__":
    main()

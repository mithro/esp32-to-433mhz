#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Generate a KiCad 9 project reproducing the green "433MHz D-Sun CC1101"
board: a CC1101 module with a 2x4 header at one end, an edge-mount SMA
jack at the other and two small holes beside the jack (EasyEDA lists the
same board as "RF1101SE V3.1").

Pinout, from the user's board, viewed from the back (header pins towards
the viewer) with the SMA jack on the left:

    SMA        VCC   GND
               SCK   MOSI
               GDO2  MISO
               CSN   GDO0

The column nearer the SMA (VCC, SCK, GDO2, CSN) is taken to be the header's
inner row and the other the outer row at the board edge.  Numbered here like
the E07-M1101D (pin 1 = GND at the right of the outer row seen from the
component side, pin 2 = VCC below it, columns stepping left):

    outer row  1 GND   3 MOSI  5 MISO  7 GDO0     (left to right: 7 5 3 1)
    inner row  2 VCC   4 SCK   6 GDO2  8 CSN      (left to right: 8 6 4 2)

Compared with the blue E07-M1101D V2.0 only the GND/VCC column is in the
same place; the three signal columns are permuted, so the board does not
fit the socket adapter's pinout (see README).

Dimensions (mm) were measured off the user's photos of the two boards side
by side (the blue E07-M1101D's 15 x 30 mm as the scale; about +/- 0.3 mm):
* Board 14.4 x 30.0 (the same length as the E07, 0.6 mm narrower); the
  thickness is assumed to be 1.6.
* Header rows 2.1 and 4.6 from the header edge; the four columns 2.9 to
  10.5 from the left long edge (seen from the component side, header up),
  so the header sits 0.5 mm left of the centre line.
* Two small (1.8 mm) holes near the SMA end, 2.5 from that edge and 1.7 in
  from the long edges.
* SMA jack centred on the far edge, the same edge-mount part as the E07.
The 3D model (scripts/build_3d.py) and the diagrams read the same constants.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from generate_cc1101 import SMA_GND_OFFSET, SMA_PAD_L, sma_fp  # noqa: E402
from kicadgen import Design, Footprint, Model, Pad, Part, SymbolRef, Track, gr_line, gr_rect, gr_text  # noqa: E402

BOARD_W = 14.4
BOARD_H = 30.0
PITCH = 2.54
HDR_ROW_Y = 2.1  # outer row from the header edge
HDR_COL_LEFT = 2.9  # leftmost column from the left long edge (component side, header up)
HDR_COL_X = BOARD_W - HDR_COL_LEFT - 3 * PITCH  # 3.88: pin 1's column from the right long edge
HOLE_D, HOLE_PAD = 1.8, 2.6
HOLE_X, HOLE_FROM_ANT_EDGE = 1.7, 2.5

PIN_NAMES = {"1": "GND", "2": "VCC", "3": "MOSI", "4": "SCK", "5": "MISO", "6": "GDO2", "7": "GDO0", "8": "CSN"}
PROJECT = "cc1101-dsun"


def header_fp() -> Footprint:
    """2x4 header numbered like the E07's: origin at pin 1, pin 2 below it,
    odd pins in the row nearest the board edge, columns stepping to -x."""
    pads = []
    for n in range(1, 9):
        col, row = (n - 1) // 2, (n - 1) % 2
        pads.append(Pad(str(n), (-col * PITCH, row * PITCH), (1.5, 1.5), "thru_hole", "rect" if n == 1 else "circle", 0.9))
    return Footprint(
        name="PinHeader_2x04_P2.54mm_DSun",
        descr="2x4 2.54 mm header of the D-Sun CC1101 board, numbered like the E07-M1101D's: pin 1 square, pin 2 below it, odd pins in the outer row; 1.5 mm pads, 0.9 mm holes",
        tags="pin header 2.54mm 2x04 D-Sun CC1101",
        pads=pads,
        ref_pos=(-3 * PITCH - 1.8, PITCH / 2, 90),
        value_pos=(-1.5 * PITCH, PITCH + 2.0),
    )


def hole_fp() -> Footprint:
    return Footprint(
        name="MountingHole_1.8mm",
        descr="Mounting hole, 1.8 mm, not plated (D-Sun CC1101 board)",
        tags="mounting hole",
        pads=[Pad("1", (0, 0), (HOLE_D, HOLE_D), "np_thru_hole", "circle", HOLE_D)],
        ref_pos=(0, -2.0, 0),
        value_pos=(0, 2.0),
    )


def build() -> Design:
    d = Design(
        model_root="${KIPRJMOD}/../../3d",
        project=PROJECT,
        title="CC1101 D-Sun form-factor board",
        comment="Outline, 2x4 header, holes and SMA position of the green 433MHz D-Sun CC1101 board (measured from photos, see generate_dsun.py)",
        fp_lib="DSun",
        width=BOARD_W,
        height=BOARD_H,
        thickness=1.6,
        castellated_refs=["J2"],
        sch_note="Green 433MHz D-Sun CC1101 board (2x4 header, SMA, two small holes).\\nJ1 = 2x4 header numbered like the E07-M1101D's (GND/VCC column in the same place, signal columns permuted), J2 = edge-mount SMA, H1/H2 = 1.8 mm holes.\\nViewed from the component side with the header at the top and the SMA at the bottom.  Dimensions measured from photos (+/- 0.3 mm).",
    )
    bx, by = d.bx, d.by
    pin1_x = bx + BOARD_W - HDR_COL_X
    d.parts.append(Part("J1", header_fp(), (pin1_x, by + HDR_ROW_Y), SymbolRef("Connector_Generic.kicad_sym", "Connector_Generic", "Conn_02x04_Odd_Even"), "Conn_02x04_Odd_Even", PIN_NAMES, (76.2, 101.6), "2x4 header", models=[Model("cc1101-dsun-components.step")]))
    d.parts.append(Part("J2", sma_fp(), (bx + BOARD_W / 2, by + BOARD_H), SymbolRef("Connector.kicad_sym", "Connector", "Conn_Coaxial"), "Conn_Coaxial", {"1": "ANT", "2": "GND"}, (147.32, 101.6), "Edge-mount SMA"))
    hole_sym = SymbolRef("Mechanical.kicad_sym", "Mechanical", "MountingHole")
    hole_y = by + BOARD_H - HOLE_FROM_ANT_EDGE
    d.parts.append(Part("H1", hole_fp(), (bx + HOLE_X, hole_y), hole_sym, "MountingHole", {}, (114.3, 101.6), "Mounting hole"))
    d.parts.append(Part("H2", hole_fp(), (bx + BOARD_W - HOLE_X, hole_y), hole_sym, "MountingHole", {}, (127.0, 101.6), "Mounting hole"))

    # GND: header pin 1 down the right edge (above the hole) to the SMA
    # ground legs on both faces, linking the legs above the centre pin's pad.
    sma_gnd_y = by + BOARD_H - SMA_PAD_L / 2
    link_y = by + BOARD_H - SMA_PAD_L - 0.6
    edge_x = bx + BOARD_W - 1.2
    legs = (bx + BOARD_W / 2 + SMA_GND_OFFSET, bx + BOARD_W / 2 - SMA_GND_OFFSET)
    for layer in ("F.Cu", "B.Cu"):
        d.tracks.append(Track("GND", layer, 0.5, [(pin1_x, by + HDR_ROW_Y), (edge_x, by + HDR_ROW_Y), (edge_x, by + BOARD_H - 5.2), (legs[0], link_y), (legs[1], link_y)]))
        for lx in legs:
            d.tracks.append(Track("GND", layer, 0.5, [(lx, link_y), (lx, sma_gnd_y)]))

    g = d.graphics
    # Front: rotated pin names in the gap left of each header column, a box round the header.
    g.append(gr_rect("hdrbox", pin1_x - 3 * PITCH - 2.2, by + HDR_ROW_Y - 1.2, pin1_x + 1.2, by + HDR_ROW_Y + PITCH + 1.2, "F.SilkS", 0.12))
    g.append(gr_rect("hdrboxb", pin1_x - 3 * PITCH - 2.2, by + HDR_ROW_Y - 1.2, pin1_x + 1.2, by + HDR_ROW_Y + PITCH + 1.2, "B.SilkS", 0.12))
    for n, name in PIN_NAMES.items():
        pin = int(n)
        col, row = (pin - 1) // 2, (pin - 1) % 2
        xg = pin1_x - col * PITCH - PITCH / 2
        yn = by + HDR_ROW_Y + row * PITCH + (0.1 if row == 0 else 0)
        g.append(gr_text(f"pn_f{n}", name, xg, yn, "F.SilkS", 0.5, None, 90))
        g.append(gr_text(f"pn_b{n}", name, xg, yn, "B.SilkS", 0.5, "mirror", 270))
    # Back: the pin names as printed on the original, a 4 x 2 grid of cells
    # next to the header, one column per header column, the outer row's
    # names in the row nearer the header; the text runs along the board.
    gy0, gy1, gy2 = by + HDR_ROW_Y + PITCH + 4.0, by + HDR_ROW_Y + PITCH + 7.0, by + HDR_ROW_Y + PITCH + 10.0
    gx0, gx1 = pin1_x - 3 * PITCH - PITCH / 2, pin1_x + PITCH / 2
    g.append(gr_rect("lgrid", gx0, gy0, gx1, gy2, "B.SilkS", 0.12))
    g.append(gr_line("lgrid_h", gx0, gy1, gx1, gy1, "B.SilkS", 0.12))
    for col in range(1, 4):
        g.append(gr_line(f"lgrid_v{col}", pin1_x - col * PITCH + PITCH / 2, gy0, pin1_x - col * PITCH + PITCH / 2, gy2, "B.SilkS", 0.12))
    for col in range(4):
        x = pin1_x - col * PITCH
        g.append(gr_text(f"lbl_o{col}", PIN_NAMES[str(2 * col + 1)], x, (gy0 + gy1) / 2, "B.SilkS", 0.55, "mirror", 90))
        g.append(gr_text(f"lbl_i{col}", PIN_NAMES[str(2 * col + 2)], x, (gy1 + gy2) / 2, "B.SilkS", 0.55, "mirror", 90))
    g.append(gr_text("title_b", "433MHz D-Sun CC1101", bx + BOARD_W / 2, by + 19.0, "B.SilkS", 0.7, "mirror"))
    g.append(gr_text("433m", "433MHz", bx + BOARD_W - 1.0, by + 12.0, "F.SilkS", 0.8, "right"))
    g.append(gr_text("title", "D-Sun CC1101 form factor", bx + BOARD_W / 2, by + 17.0, "F.Fab", 0.5))
    g.append(gr_rect("cc1101", bx + 3.5, by + 13.8, bx + 7.5, by + 17.8, "F.Fab", 0.1, "dash"))
    g.append(gr_rect("xtal", bx + 0.1, by + 13.9, bx + 2.6, by + 17.1, "F.Fab", 0.1, "dash"))
    return d


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=pathlib.Path, default=pathlib.Path(__file__).resolve().parent.parent / "hardware" / "parts" / PROJECT)
    args = ap.parse_args()
    build().write(args.out)


if __name__ == "__main__":
    main()

#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Generate a KiCad 9 project reproducing the Ebyte E07-M1101D-SMA CC1101
433 MHz module (sold as "TENSTAR CC1101 433MHz Wireless Module", PCB marked
E07-M1101D V2.0).

Dimensions (mm) come from the Ebyte E07 series user manuals, section
"Mechanical Characteristics / Size and pin definition" (drawing shared by the
-TH and -SMA variants):

* Board 15.0 x 30.0.  (The parameter table lists the -SMA variant as
  15*30 mm; the -TH spring-antenna variant is listed as 15*28 mm but its
  drawing also says 30.0 +/- 0.1.)
* 2x4 header, 2.54 mm pitch: first row 1.60 from the header edge, columns
  3.70 from the long edges (i.e. centred: 3.69 / 6.23 / 8.77 / 11.31).
  Pad 1.50, hole 0.90, pin 1 square.  Viewed from the component side with
  the antenna at the bottom, the row nearest the edge reads 7 5 3 1 left to
  right and the second row 8 6 4 2.
* Two 3.00 mm plated mounting holes with 4.20 mm pads, 2.70 from each long
  edge and 10.0 from the antenna edge.
* Edge-mount SMA jack centred on the antenna edge (pad geometry follows the
  common 1.6 mm PCB edge-mount SMA: 1.5 mm wide pads, ground legs 4.25 mm
  either side of the centre pin).
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from kicadgen import Design, Footprint, Pad, Part, SymbolRef, Track, fp_rect, fp_text, gr_rect, gr_text  # noqa: E402

BOARD_W = 15.0
BOARD_H = 30.0
PITCH = 2.54
HDR_ROW_Y = 1.60
HDR_COL_X = 3.70  # datasheet dimension from the long edge to the nearest column
HOLE_D = 3.0
HOLE_PAD = 4.2
HOLE_X = 2.70
HOLE_FROM_ANT_EDGE = 10.0
SMA_GND_OFFSET = 4.25
SMA_PAD_W = 1.5
SMA_PAD_L = 4.5

PIN_NAMES = {"1": "GND", "2": "VCC", "3": "GDO0", "4": "CSN", "5": "SCK", "6": "MOSI", "7": "MISO", "8": "GDO2"}
PROJECT = "cc1101-e07-m1101d"


def header_fp() -> Footprint:
    """2x4 header with the Ebyte numbering: origin at pin 1, pin 2 below it,
    odd pins in the row nearest the board edge, columns stepping to -x."""
    pads = []
    for n in range(1, 9):
        col, row = (n - 1) // 2, (n - 1) % 2
        pads.append(Pad(str(n), (-col * PITCH, row * PITCH), (1.5, 1.5), "thru_hole", "rect" if n == 1 else "circle", 0.9))
    return Footprint(
        name="PinHeader_2x04_P2.54mm_E07",
        descr="2x4 2.54 mm header as on the Ebyte E07-M1101D: pin 1 square, pin 2 below it, odd pins in the outer row; 1.5 mm pads, 0.9 mm holes",
        tags="pin header 2.54mm 2x04 E07-M1101D",
        pads=pads,
        ref_pos=(-3 * PITCH - 1.8, PITCH / 2, 90),
        value_pos=(-1.5 * PITCH, PITCH + 2.0),
    )


def hole_fp() -> Footprint:
    return Footprint(
        name="MountingHole_3.0mm_Pad_4.2mm",
        descr="Plated mounting hole, 3.0 mm drill, 4.2 mm pad (Ebyte E07-M1101D)",
        tags="mounting hole 3.0mm",
        pads=[Pad("1", (0, 0), (HOLE_PAD, HOLE_PAD), "thru_hole", "circle", HOLE_D)],
        ref_pos=(0, -2.9, 0),
        value_pos=(0, 2.9),
    )


def sma_fp() -> Footprint:
    """Edge-mount SMA jack; origin on the board edge at the centre pin, pads
    extend in -y (into the board)."""
    pads = [Pad("1", (0, -SMA_PAD_L / 2), (SMA_PAD_W, SMA_PAD_L), "smd", "rect")]
    for sx in (-1, 1):
        pads.append(Pad("2", (sx * SMA_GND_OFFSET, -SMA_PAD_L / 2), (SMA_PAD_W, SMA_PAD_L), "smd", "rect", tag=f"f{sx}"))
        pads.append(Pad("2", (sx * SMA_GND_OFFSET, -SMA_PAD_L / 2), (SMA_PAD_W, SMA_PAD_L), "smd", "rect", layers=("B.Cu", "B.Mask", "B.Paste"), tag=f"b{sx}"))
    body_w = 6.35
    extra = [
        fp_rect("sma:body", -body_w / 2, 0, body_w / 2, 9.5, "F.Fab", 0.1, "dash"),
        fp_text("sma:label", "SMA", 0, 5.0, "F.Fab", 0.8),
    ]
    return Footprint(
        name="SMA_EdgeMount_E07",
        descr="Edge-mount SMA jack for 1.6 mm PCB edge, centre pin on top, ground legs 4.25 mm either side on both faces (as fitted to the Ebyte E07-M1101D-SMA)",
        tags="SMA edge mount coaxial",
        pads=pads,
        extra=extra,
        attr="smd",
        ref_pos=(0, -SMA_PAD_L - 1.0, 0),
        value_pos=(0, 11.0),
    )


def build() -> Design:
    d = Design(
        project=PROJECT,
        title="CC1101 E07-M1101D-SMA form-factor board",
        comment="Outline, 2x4 header, mounting holes and SMA position identical to the Ebyte E07-M1101D-SMA (TENSTAR CC1101 433MHz module)",
        fp_lib="E07",
        width=BOARD_W,
        height=BOARD_H,
        thickness=1.6,
        castellated_refs=["J2"],
        sch_note="Ebyte E07-M1101D-SMA form-factor board (TENSTAR CC1101 433MHz module).\\nJ1 = 2x4 header, H1/H2 = plated mounting holes, J2 = edge-mount SMA.\\nViewed from the component side with the header at the top and the SMA at the bottom.",
    )
    bx, by = d.bx, d.by
    pin1_x = bx + BOARD_W - HDR_COL_X  # 11.30 from the left edge
    d.parts.append(Part("J1", header_fp(), (pin1_x, by + HDR_ROW_Y), SymbolRef("Connector_Generic.kicad_sym", "Connector_Generic", "Conn_02x04_Odd_Even"), "Conn_02x04_Odd_Even", PIN_NAMES, (76.2, 101.6), "2x4 header"))
    hole_sym = SymbolRef("Mechanical.kicad_sym", "Mechanical", "MountingHole_Pad")
    hole_y = by + BOARD_H - HOLE_FROM_ANT_EDGE
    d.parts.append(Part("H1", hole_fp(), (bx + HOLE_X, hole_y), hole_sym, "MountingHole_Pad", {"1": "GND"}, (114.3, 101.6), "Mounting hole"))
    d.parts.append(Part("H2", hole_fp(), (bx + BOARD_W - HOLE_X, hole_y), hole_sym, "MountingHole_Pad", {"1": "GND"}, (127.0, 101.6), "Mounting hole"))
    d.parts.append(Part("J2", sma_fp(), (bx + BOARD_W / 2, by + BOARD_H), SymbolRef("Connector.kicad_sym", "Connector", "Conn_Coaxial"), "Conn_Coaxial", {"1": "ANT", "2": "GND"}, (147.32, 101.6), "Edge-mount SMA"))

    # GND: header pin 1 -> both mounting holes -> SMA ground legs (top and bottom).
    sma_gnd_y = by + BOARD_H - SMA_PAD_L / 2
    for layer in ("F.Cu", "B.Cu"):
        d.tracks.append(Track("GND", layer, 0.5, [(bx + HOLE_X, hole_y), (bx + BOARD_W - HOLE_X, hole_y)]))
        d.tracks.append(Track("GND", layer, 0.5, [(bx + HOLE_X, hole_y), (bx + BOARD_W / 2 - SMA_GND_OFFSET, sma_gnd_y)]))
        d.tracks.append(Track("GND", layer, 0.5, [(bx + BOARD_W - HOLE_X, hole_y), (bx + BOARD_W / 2 + SMA_GND_OFFSET, sma_gnd_y)]))
    d.tracks.append(Track("GND", "F.Cu", 0.5, [(pin1_x, by + HDR_ROW_Y), (bx + BOARD_W - 1.7, by + HDR_ROW_Y), (bx + BOARD_W - 1.7, hole_y), (bx + BOARD_W - HOLE_X, hole_y)]))

    g = d.graphics
    # Silkscreen as on the original: pin 1/2/7/8 markers and a box around the header.
    g.append(gr_text("s1", "1", pin1_x + 1.6, by + HDR_ROW_Y, "F.SilkS", 0.8, "left"))
    g.append(gr_text("s2", "2", pin1_x + 1.6, by + HDR_ROW_Y + PITCH, "F.SilkS", 0.8, "left"))
    g.append(gr_text("s7", "7", pin1_x - 3 * PITCH - 2.4, by + HDR_ROW_Y, "F.SilkS", 0.8, "right"))
    g.append(gr_text("s8", "8", pin1_x - 3 * PITCH - 2.4, by + HDR_ROW_Y + PITCH, "F.SilkS", 0.8, "right"))
    g.append(gr_rect("hdrbox", pin1_x - 3 * PITCH - 2.2, by + HDR_ROW_Y - 1.2, pin1_x + 1.2, by + HDR_ROW_Y + PITCH + 1.2, "F.SilkS", 0.12))
    # Back-side copies (mirrored) of the pin-1/2/7/8 markers and the box.
    g.append(gr_text("s1b", "1", pin1_x + 1.6, by + HDR_ROW_Y, "B.SilkS", 0.8, "right mirror"))
    g.append(gr_text("s2b", "2", pin1_x + 1.6, by + HDR_ROW_Y + PITCH, "B.SilkS", 0.8, "right mirror"))
    g.append(gr_text("s7b", "7", pin1_x - 3 * PITCH - 2.4, by + HDR_ROW_Y, "B.SilkS", 0.8, "left mirror"))
    g.append(gr_text("s8b", "8", pin1_x - 3 * PITCH - 2.4, by + HDR_ROW_Y + PITCH, "B.SilkS", 0.8, "left mirror"))
    g.append(gr_rect("hdrboxb", pin1_x - 3 * PITCH - 2.2, by + HDR_ROW_Y - 1.2, pin1_x + 1.2, by + HDR_ROW_Y + PITCH + 1.2, "B.SilkS", 0.12))
    # Pin names, rotated, in the gap left of each header column (outer-row
    # name level with the outer pad, inner-row name with the inner pad), on
    # both sides.
    for n, name in PIN_NAMES.items():
        pin = int(n)
        col, row = (pin - 1) // 2, (pin - 1) % 2
        xg = pin1_x - col * PITCH - PITCH / 2
        yn = by + HDR_ROW_Y + row * PITCH + (0.1 if row == 0 else 0)
        g.append(gr_text(f"pn_f{n}", name, xg, yn, "F.SilkS", 0.5, None, 90))
        g.append(gr_text(f"pn_b{n}", name, xg, yn, "B.SilkS", 0.5, "mirror", 270))
    for i, (n, name) in enumerate(PIN_NAMES.items()):
        g.append(gr_text(f"name{n}", f"{n} {name}", bx + 1.0, by + 7.5 + i * 1.1, "F.SilkS", 0.6, "left"))
        g.append(gr_text(f"nameb{n}", f"{n} {name}", bx + 1.0, by + 7.5 + i * 1.1, "B.SilkS", 0.6, "right mirror"))
    g.append(gr_text("433m", "433M", bx + BOARD_W - 1.0, by + 12.0, "F.SilkS", 0.8, "right"))
    g.append(gr_text("title", "E07-M1101D form factor", bx + BOARD_W / 2, by + 16.5, "F.Fab", 0.5))
    # CC1101 QFN-20 (4x4) sits roughly centred between header and holes.
    g.append(gr_rect("cc1101", bx + 5.5, by + 10.0, bx + 9.5, by + 14.0, "F.Fab", 0.1, "dash"))
    return d


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=pathlib.Path, default=pathlib.Path(__file__).resolve().parent.parent / "hardware" / "parts" / PROJECT)
    args = ap.parse_args()
    build().write(args.out)


if __name__ == "__main__":
    main()

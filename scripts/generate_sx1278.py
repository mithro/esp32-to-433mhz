#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Generate a KiCad 9 project reproducing the 16-pin castellated SX1278 LoRa
433 MHz module sold as "SX1278 LoRa 433MHz Wireless Module (PXL1276-D01)"
(HKFYD and others).

The module is a derivative of the NiceRF LoRa1276/LoRa1278 layout.  No
manufacturer drawing was found for this variant, so the geometry combines:

* Seller PDF ("Module Size: 17mm x 16.5mm").
* Seller pinout photo (top-down, dimensioned) and close-up photos, measured
  in pixels against the board edges and the 1.27 mm pitch:
  - 12 keyhole pads (plated hole 1.2 mm in from the edge plus a half-hole
    castellation on the edge) at 1.27 mm pitch along one 16.5 mm edge,
    first hole 1.25 mm from the corner.
  - Two small castellation-only notches (DIO4, DIO5) on the adjacent 17 mm
    edge, 1.25 and 2.7 mm from the shared corner.
  - Two keyhole pads (GND, ANT) near the far corner of the opposite 17 mm
    edge, 2.8 and 1.4 mm from that corner, holes 0.9 mm in from the edge.
* NiceRF LoRa127X mechanical drawing for the hole size (0.6 mm) of this
  family.

Pin names follow the seller's pinout photo (GND DIO1 DIO2 DIO3 VCC MISO MOSI
SCK NSS DIO0 REST GND along the row, then DIO4 DIO5, then GND and ANT); the
seller's pin table lists REST twice, which shifts its last entries by one.

Viewed from the component side the 12-pad row is on the left edge with pin 1
at the top, DIO4/DIO5 on the bottom edge at the left corner, and GND/ANT on
the right edge at the top corner.  Positions are accurate to roughly
+/-0.15 mm.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from kicadgen import Design, Footprint, Pad, Part, SymbolRef, Track, gr_rect, gr_text  # noqa: E402

BOARD_W = 17.0  # top/bottom edges
BOARD_H = 16.5  # left/right edges (the 12-pad edge)
PITCH = 1.27
N_LEFT = 12
LEFT_FIRST_Y = 1.2  # pin 1 hole centre from the top edge (photo: 1.25)
ROW_HOLE_IN = 1.2  # row through-hole centre from the edge
ROW_PAD_IN = 1.85  # row copper reaching into the board
BOTTOM_NOTCH_X = (1.25, 2.7)  # DIO4, DIO5 castellation centres from the left edge
RIGHT_PAD_Y = {"ANT": 1.4, "GND": 2.8}  # right-edge keyhole holes from the top edge
RIGHT_HOLE_IN = 0.9
RIGHT_PAD_IN = 1.7
HOLE = 0.6  # through-hole and castellation half-hole diameter
PAD_W = 1.05  # keyhole pad width along the edge
NOTCH_W = 0.8  # castellation-only pad width along the edge
NOTCH_IN = 0.55  # castellation-only copper reaching into the board
NOTCH_OUT = 0.5  # castellation-only copper outside the edge (removed when routed)

PIN_NAMES = ["GND", "DIO1", "DIO2", "DIO3", "VCC", "MISO", "MOSI", "SCK", "NSS", "DIO0", "REST", "GND", "DIO4", "DIO5", "GND", "ANT"]
PROJECT = "sx1278-lora-module"


def keyhole(n: int, x: float, y: float, direction: str, hole_in: float, pad_in: float) -> list[Pad]:
    """Keyhole pad on the board edge at (x, y): a through-hole hole_in into
    the board with oval copper running from the edge to pad_in, plus a
    castellation half-hole centred on the edge.  direction = side of the
    board the pad reaches into: 'right' (from the left edge) or 'left'."""
    dx = {"right": 1, "left": -1}[direction]
    shift = pad_in / 2 - hole_in  # oval centre relative to the through-hole
    return [
        Pad(str(n), (x + dx * hole_in, y), (pad_in, PAD_W), "thru_hole", "oval", HOLE, (dx * shift, 0), tag="th"),
        Pad(str(n), (x, y), (PAD_W, PAD_W), "thru_hole", "circle", HOLE, tag="edge"),
    ]


def notch(n: int, x: float, y: float) -> Pad:
    """Castellation-only pad on the bottom edge at (x, y), copper reaching up
    NOTCH_IN into the board and NOTCH_OUT beyond the edge."""
    length = NOTCH_IN + NOTCH_OUT
    return Pad(str(n), (x, y), (NOTCH_W, length), "thru_hole", "oval", HOLE, (0, -(length / 2 - NOTCH_OUT)), tag="edge")


def module_fp() -> Footprint:
    pads = []
    for i in range(N_LEFT):
        pads += keyhole(i + 1, 0, LEFT_FIRST_Y + i * PITCH, "right", ROW_HOLE_IN, ROW_PAD_IN)
    pads.append(notch(13, BOTTOM_NOTCH_X[0], BOARD_H))
    pads.append(notch(14, BOTTOM_NOTCH_X[1], BOARD_H))
    pads += keyhole(15, BOARD_W, RIGHT_PAD_Y["GND"], "left", RIGHT_HOLE_IN, RIGHT_PAD_IN)
    pads += keyhole(16, BOARD_W, RIGHT_PAD_Y["ANT"], "left", RIGHT_HOLE_IN, RIGHT_PAD_IN)
    return Footprint(
        name="SX1278_Module_16pin_Castellated",
        descr="16-pin castellated SX1278 LoRa module (PXL1276-D01 / NiceRF LoRa1278 derivative): 12 keyhole pads at 1.27 mm on the left edge (0.6 mm through-hole 1.2 mm in from the edge plus a 0.6 mm half-hole on the edge), two castellation-only notches on the bottom edge at the left corner, and two keyhole pads on the right edge at the top corner. Origin at the top-left board corner; board edges must run through the castellation centres.",
        tags="SX1278 LoRa module castellated 1.27mm",
        pads=pads,
        ref_pos=(BOARD_W / 2, BOARD_H / 2 + 2.5, 0),
        value_pos=(BOARD_W / 2, BOARD_H / 2 + 4.0),
    )


def build() -> Design:
    d = Design(
        project=PROJECT,
        title="SX1278 LoRa module form-factor board",
        comment="Outline and 16-pin castellated edge layout of the PXL1276-D01 style SX1278 433MHz LoRa module",
        fp_lib="LoRaModule",
        width=BOARD_W,
        height=BOARD_H,
        thickness=1.0,
        castellated_refs=["J1"],
        sch_note="SX1278 LoRa module (PXL1276-D01 style) form-factor board.\\nJ1 pins 1-12 run down the left edge, 13/14 (DIO4/DIO5) are notches on the bottom edge,\\n15/16 (GND/ANT) are on the right edge near the top, viewed from the component side.",
    )
    bx, by = d.bx, d.by
    nets = {str(i + 1): n for i, n in enumerate(PIN_NAMES)}
    d.parts.append(Part("J1", module_fp(), (bx, by), SymbolRef("Connector_Generic.kicad_sym", "Connector_Generic", "Conn_01x16"), "Conn_01x16", nets, (76.2, 101.6), "Module edge pads"))

    # GND appears on pins 1, 12 and 15; join them with tracks (the original
    # uses a ground plane).  The vertical run sits just clear of the row copper
    # (x <= 1.85) and stops above the DIO5 notch; the top run goes along the
    # top edge and drops down to pad 15 clear of the ANT pad.
    y = lambda pin: by + LEFT_FIRST_Y + (pin - 1) * PITCH  # noqa: E731
    gx = bx + 2.2
    d.tracks.append(Track("GND", "F.Cu", 0.25, [(bx + ROW_PAD_IN - 0.2, y(1)), (gx, y(1)), (gx, y(12)), (bx + ROW_PAD_IN - 0.2, y(12))]))
    d.tracks.append(Track("GND", "F.Cu", 0.25, [(gx, y(1)), (gx, by + 0.6), (bx + 14.0, by + 0.6), (bx + 14.0, by + RIGHT_PAD_Y["GND"]), (bx + BOARD_W - RIGHT_PAD_IN + 0.2, by + RIGHT_PAD_Y["GND"])]))

    g = d.graphics
    for i in range(N_LEFT):
        g.append(gr_text(f"l{i}", PIN_NAMES[i], bx + 2.6, by + LEFT_FIRST_Y + i * PITCH, "F.SilkS", 0.5, "left"))
    # DIO4 / DIO5 notches are labelled to the right of them, in edge order.
    g.append(gr_text("l12", PIN_NAMES[12], bx + BOTTOM_NOTCH_X[1] + 1.6, by + BOARD_H - 0.95, "F.SilkS", 0.5, "left"))
    g.append(gr_text("l13", PIN_NAMES[13], bx + BOTTOM_NOTCH_X[1] + 1.6, by + BOARD_H - 0.3, "F.SilkS", 0.5, "left"))
    g.append(gr_text("l14", PIN_NAMES[14], bx + BOARD_W - RIGHT_PAD_IN - 0.3, by + RIGHT_PAD_Y["GND"], "F.SilkS", 0.5, "right"))
    g.append(gr_text("l15", PIN_NAMES[15], bx + BOARD_W - RIGHT_PAD_IN - 0.3, by + RIGHT_PAD_Y["ANT"], "F.SilkS", 0.5, "right"))
    g.append(gr_text("title", "SX1278 module form factor", bx + BOARD_W / 2 + 1.0, by + BOARD_H - 1.5, "F.Fab", 0.5))
    # Approximate positions of the SX1278 (QFN-28, 6x6) and the 32 MHz crystal, from photos.
    g.append(gr_rect("sx1278", bx + 3.5, by + 8.0, bx + 9.5, by + 14.0, "F.Fab", 0.1, "dash"))
    g.append(gr_text("sx1278", "SX1278", bx + 6.5, by + 11.0, "F.Fab", 0.5))
    g.append(gr_rect("xtal", bx + 4.0, by + 1.2, bx + 7.2, by + 3.7, "F.Fab", 0.1, "dash"))
    return d


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=pathlib.Path, default=pathlib.Path(__file__).resolve().parent.parent / "hardware" / "parts" / PROJECT)
    args = ap.parse_args()
    build().write(args.out)


if __name__ == "__main__":
    main()

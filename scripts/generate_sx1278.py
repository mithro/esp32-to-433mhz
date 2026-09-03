#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Generate a KiCad 9 project reproducing the 16-pin castellated SX1278 LoRa
433 MHz module sold as "SX1278 LoRa 433MHz Wireless Module (PXL1276-D01)"
(HKFYD and others).

The module is a derivative of the NiceRF LoRa1276/LoRa1278 layout with two
extra pins.  No manufacturer drawing was found for this variant, so the
geometry combines:

* Seller PDF ("Module Size: 17mm x 16.5mm").
* A perspective-rectified product photo: 13 castellated pads down one
  16.5 mm edge at 1.27 mm pitch (measured 1.26), one pad around the corner
  on the adjacent 17.0 mm edge, and two pads at 1.27 mm pitch near the top
  of the opposite edge.
* NiceRF LoRa127X mechanical drawing for the pad geometry of this family:
  0.8 mm half-holes, pads 1.5 mm long, 1.27 mm pitch.
* Seller pin table for the names (pin 1 GND ... pin 16 ANT), numbered
  counter-clockwise from the top-left when viewed from the component side.

Pad positions are therefore accurate to roughly +/-0.2 mm; the pitch and
pin count are solid.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from kicadgen import Design, Footprint, Pad, Part, SymbolRef, Track, gr_rect, gr_text  # noqa: E402

BOARD_W = 17.0  # top/bottom edges
BOARD_H = 16.5  # left/right edges (the 13-pad edge)
PITCH = 1.27
N_LEFT = 13
LEFT_FIRST_Y = (BOARD_H - (N_LEFT - 1) * PITCH) / 2  # pads centred on the edge: 0.63
BOTTOM_PAD_X = 2.8  # pin 14, from the left edge (photo: 2.7 +/- 0.2)
RIGHT_PAD_Y = (PITCH, 2 * PITCH)  # pins 16 (upper) and 15 (lower) from the top edge
HOLE = 0.8
PAD_W = 1.05  # along the edge (0.125 mm ring around the 0.8 mm hole, 0.22 mm to the neighbour)
PAD_IN = 1.5  # copper reaching into the board
PAD_OUT = 0.6  # copper outside the edge (removed when the board is routed)

PIN_NAMES = ["GND", "DIO1", "DIO2", "DIO3", "VCC", "MISO", "MOSI", "SCK", "NSS", "DIO0", "REST", "REST", "GND", "DIO4", "DIO5", "ANT"]
PROJECT = "sx1278-lora-module"


def edge_pad(n: int, x: float, y: float, direction: str) -> Pad:
    """Castellated pad: hole centred on the board edge, copper oval reaching
    PAD_IN into the board and PAD_OUT beyond it.  direction = side of the
    board the pad reaches into: 'right' (from the left edge), 'left', 'up'."""
    length = PAD_IN + PAD_OUT
    shift = length / 2 - PAD_OUT
    if direction == "right":
        return Pad(str(n), (x, y), (length, PAD_W), "thru_hole", "oval", HOLE, (shift, 0))
    if direction == "left":
        return Pad(str(n), (x, y), (length, PAD_W), "thru_hole", "oval", HOLE, (-shift, 0))
    return Pad(str(n), (x, y), (PAD_W, length), "thru_hole", "oval", HOLE, (0, -shift))


def module_fp() -> Footprint:
    pads = [edge_pad(i + 1, 0, LEFT_FIRST_Y + i * PITCH, "right") for i in range(N_LEFT)]
    pads.append(edge_pad(14, BOTTOM_PAD_X, BOARD_H, "up"))
    pads.append(edge_pad(15, BOARD_W, RIGHT_PAD_Y[1], "left"))
    pads.append(edge_pad(16, BOARD_W, RIGHT_PAD_Y[0], "left"))
    return Footprint(
        name="SX1278_Module_16pin_Castellated",
        descr="16-pin castellated SX1278 LoRa module (PXL1276-D01 / NiceRF LoRa1278 derivative): 13 pads at 1.27 mm on the left edge, one on the bottom edge, two on the right edge; 0.8 mm half-holes. Origin at the top-left board corner; board edges must run through the hole centres.",
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
        sch_note="SX1278 LoRa module (PXL1276-D01 style) form-factor board.\\nJ1 pins 1-13 run down the left edge, 14 is on the bottom edge, 15/16 on the right edge,\\nviewed from the component side.  Both REST pins are the module reset.",
    )
    bx, by = d.bx, d.by
    nets = {str(i + 1): n for i, n in enumerate(PIN_NAMES)}
    d.parts.append(Part("J1", module_fp(), (bx, by), SymbolRef("Connector_Generic.kicad_sym", "Connector_Generic", "Conn_01x16"), "Conn_01x16", nets, (76.2, 101.6), "Module edge pads"))

    # Nets shared by two pads: GND (pins 1 and 13) and the two REST pins.
    y = lambda pin: by + LEFT_FIRST_Y + (pin - 1) * PITCH  # noqa: E731
    d.tracks.append(Track("GND", "F.Cu", 0.3, [(bx + PAD_IN - 0.2, y(1)), (bx + 1.9, y(1)), (bx + 1.9, y(13)), (bx + PAD_IN - 0.2, y(13))]))
    d.tracks.append(Track("REST", "F.Cu", 0.3, [(bx + PAD_IN - 0.2, y(11)), (bx + PAD_IN - 0.2, y(12))]))

    g = d.graphics
    for i in range(N_LEFT - 1):
        g.append(gr_text(f"l{i}", PIN_NAMES[i], bx + 2.5, by + LEFT_FIRST_Y + i * PITCH, "F.SilkS", 0.5, "left"))
    # Pin 13 (GND) and the corner pad 14 (DIO4) are labelled to the right of pad 14.
    g.append(gr_text("l12", PIN_NAMES[12], bx + BOTTOM_PAD_X + 0.9, by + BOARD_H - 1.3, "F.SilkS", 0.5, "left"))
    g.append(gr_text("l13", PIN_NAMES[13], bx + BOTTOM_PAD_X + 0.9, by + BOARD_H - 0.5, "F.SilkS", 0.5, "left"))
    g.append(gr_text("l14", PIN_NAMES[14], bx + BOARD_W - PAD_IN - 0.3, by + RIGHT_PAD_Y[1], "F.SilkS", 0.5, "right"))
    g.append(gr_text("l15", PIN_NAMES[15], bx + BOARD_W - PAD_IN - 0.3, by + RIGHT_PAD_Y[0], "F.SilkS", 0.5, "right"))
    g.append(gr_text("title", "SX1278 module form factor", bx + BOARD_W / 2 + 1.0, by + BOARD_H - 2.0, "F.Fab", 0.5))
    # Approximate positions of the SX1278 (QFN-28, 6x6) and the 32 MHz crystal, from photos.
    g.append(gr_rect("sx1278", bx + 3.5, by + 8.0, bx + 9.5, by + 14.0, "F.Fab", 0.1, "dash"))
    g.append(gr_text("sx1278", "SX1278", bx + 6.5, by + 11.0, "F.Fab", 0.5))
    g.append(gr_rect("xtal", bx + 4.0, by + 0.8, bx + 7.2, by + 3.3, "F.Fab", 0.1, "dash"))
    return d


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=pathlib.Path, default=pathlib.Path(__file__).resolve().parent.parent / "hardware" / PROJECT)
    args = ap.parse_args()
    build().write(args.out)


if __name__ == "__main__":
    main()

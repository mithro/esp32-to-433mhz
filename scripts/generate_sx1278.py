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
* A perspective-rectified product photo: 12 keyhole pads down one 16.5 mm
  edge at 1.27 mm pitch (measured 1.26), a castellation-only pad at the
  bottom corner of that edge, another castellation-only pad around the
  corner on the adjacent 17.0 mm edge, and two keyhole pads at 1.27 mm
  pitch near the top of the opposite edge.
* NiceRF LoRa127X mechanical drawing and close-up photos for the pad
  geometry of this family: keyhole pads 1.5 mm long at 1.27 mm pitch, each
  with a plated through-hole about 1.0 mm in from the edge and a half-hole
  castellation on the edge (0.6 mm holes).
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
N_LEFT = 12  # keyhole pads on the left edge (pins 1-12)
LEFT_FIRST_Y = 0.72  # pin 1 centre from the top edge (photo: 0.75; leaves 0.2 mm between pad 12 and the corner pad)
CORNER_PAD_Y = BOARD_H - 0.53  # pin 13: castellation-only pad flush with the bottom-left corner
BOTTOM_PAD_X = 2.7  # pin 14: castellation-only pad on the bottom edge (photo: 2.7 +/- 0.2)
RIGHT_PAD_Y = (PITCH, 2 * PITCH)  # pins 16 (upper) and 15 (lower) from the top edge
HOLE = 0.6  # through-hole and castellation half-hole diameter
HOLE_IN = 1.0  # through-hole centre from the board edge
PAD_W = 1.05  # along the edge (0.225 mm ring, 0.22 mm to the neighbour)
PAD_IN = 1.5  # copper reaching into the board
PAD_OUT = 0.5  # copper outside the edge for castellation-only pads (removed when routed)

PIN_NAMES = ["GND", "DIO1", "DIO2", "DIO3", "VCC", "MISO", "MOSI", "SCK", "NSS", "DIO0", "REST", "REST", "GND", "DIO4", "DIO5", "ANT"]
PROJECT = "sx1278-lora-module"


def edge_pad(n: int, x: float, y: float, direction: str, keyhole: bool = True) -> list[Pad]:
    """Pad on the board edge at (x, y).  direction = side of the board the
    pad reaches into: 'right' (from the left edge), 'left', 'up'.

    keyhole=True: a through-hole HOLE_IN into the board with oval copper
    running from the edge to PAD_IN, plus a castellation half-hole centred
    on the edge.  keyhole=False: only the castellation half-hole, with oval
    copper from PAD_OUT outside the edge to PAD_IN inside."""
    dx, dy = {"right": (1, 0), "left": (-1, 0), "up": (0, -1)}[direction]
    if not keyhole:
        length = PAD_IN + PAD_OUT
        shift = length / 2 - PAD_OUT
        size = (length, PAD_W) if dy == 0 else (PAD_W, length)
        return [Pad(str(n), (x, y), size, "thru_hole", "oval", HOLE, (dx * shift, dy * shift), tag="edge")]
    shift = PAD_IN / 2 - HOLE_IN  # oval centre relative to the through-hole
    size = (PAD_IN, PAD_W) if dy == 0 else (PAD_W, PAD_IN)
    return [
        Pad(str(n), (x + dx * HOLE_IN, y + dy * HOLE_IN), size, "thru_hole", "oval", HOLE, (dx * shift, dy * shift), tag="th"),
        Pad(str(n), (x, y), (PAD_W, PAD_W), "thru_hole", "circle", HOLE, tag="edge"),
    ]


def module_fp() -> Footprint:
    pads = []
    for i in range(N_LEFT):
        pads += edge_pad(i + 1, 0, LEFT_FIRST_Y + i * PITCH, "right")
    pads += edge_pad(13, 0, CORNER_PAD_Y, "right", keyhole=False)
    pads += edge_pad(14, BOTTOM_PAD_X, BOARD_H, "up", keyhole=False)
    pads += edge_pad(15, BOARD_W, RIGHT_PAD_Y[1], "left")
    pads += edge_pad(16, BOARD_W, RIGHT_PAD_Y[0], "left")
    return Footprint(
        name="SX1278_Module_16pin_Castellated",
        descr="16-pin castellated SX1278 LoRa module (PXL1276-D01 / NiceRF LoRa1278 derivative): 12 keyhole pads at 1.27 mm on the left edge (0.6 mm through-hole 1.0 mm in from the edge plus a 0.6 mm half-hole on the edge), castellation-only pads at the bottom-left corner and on the bottom edge, and two keyhole pads on the right edge. Origin at the top-left board corner; board edges must run through the castellation centres.",
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
    # The vertical run passes between the pad copper (x <= 1.5) and pad 14 (x >= 2.175).
    gx = bx + 1.84
    d.tracks.append(Track("GND", "F.Cu", 0.25, [(bx + PAD_IN - 0.2, y(1)), (gx, y(1)), (gx, by + CORNER_PAD_Y), (bx + PAD_IN - 0.2, by + CORNER_PAD_Y)]))
    d.tracks.append(Track("REST", "F.Cu", 0.3, [(bx + PAD_IN - 0.2, y(11)), (bx + PAD_IN - 0.2, y(12))]))

    g = d.graphics
    for i in range(N_LEFT):
        g.append(gr_text(f"l{i}", PIN_NAMES[i], bx + 2.5, by + LEFT_FIRST_Y + i * PITCH, "F.SilkS", 0.5, "left"))
    # Pin 13 (GND) and the corner pad 14 (DIO4) are labelled to the right of pad 14.
    g.append(gr_text("l12", PIN_NAMES[12], bx + BOTTOM_PAD_X + 0.9, by + BOARD_H - 1.1, "F.SilkS", 0.5, "left"))
    g.append(gr_text("l13", PIN_NAMES[13], bx + BOTTOM_PAD_X + 0.9, by + BOARD_H - 0.35, "F.SilkS", 0.5, "left"))
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

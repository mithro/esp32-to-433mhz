#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Generate a KiCad 9 project reproducing the ESP32-C3 SuperMini outline and
castellated pin headers.

Dimensions (mm) and their sources:

* Board 18.00 x 22.52, pin rows 15.24 apart, 2.54 pitch:
  - GrabCAD STEP model "ESP32C3-SuperMini" by Ulf Hille (body spans
    x -9.00..9.00, y -11.26..11.26, pins at x = +/-7.62).
  - mischianti.org dimension drawing (18.00 mm / 15.24 mm / 22.50 mm).
* Pin row offset: STEP model puts the first pin 1.74 mm from the USB-C edge
  and the last pin 3.00 mm from the antenna edge (pins at y = 9.52 .. -8.26).
* Pad geometry: STEP model has 1.6 mm copper rings (r = 0.8) around each pin
  and a 1.1 mm wide plated feature from the pin centre to the board edge;
  photos show a round hole plus a half-hole castellation at the edge joined
  by an oval pad.  We use a 1.0 mm drill (standard for 2.54 mm headers,
  matches the ~0.95 mm measured off the drawing) and a 1.6 mm wide oval.
* USB-C shell and button positions come from the STEP model.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from kicadgen import Design, Footprint, Model, Pad, Part, SymbolRef, gr_circle, gr_rect, gr_text  # noqa: E402

BOARD_W = 18.00
BOARD_H = 22.52
PITCH = 2.54
N_PINS = 8
ROW_SPACING = 15.24
PIN_EDGE_X = (BOARD_W - ROW_SPACING) / 2  # 1.38 mm from long edge to pin centre
PIN_TOP_Y = 1.74  # first pin centre from the USB-C edge
DRILL = 1.0
PAD_W = 1.6  # oval pad width / castellation copper diameter
OVAL_LEN = PIN_EDGE_X + PAD_W / 2  # 2.18: copper from (pin - 0.8) out to the edge
OVAL_SHIFT = OVAL_LEN / 2 - PAD_W / 2  # 0.29: oval centre sits this far toward the edge

# Pin names, top (USB-C end) to bottom, viewed from the component side.
LEFT_PINS = ["GPIO5", "GPIO6", "GPIO7", "GPIO8", "GPIO9", "GPIO10", "GPIO20", "GPIO21"]
RIGHT_PINS = ["+5V", "GND", "+3V3", "GPIO4", "GPIO3", "GPIO2", "GPIO1", "GPIO0"]
LEFT_SILK = ["5", "6", "7", "8", "9", "10", "20", "21"]
RIGHT_SILK = ["5V", "G", "3V3", "4", "3", "2", "1", "0"]

PROJECT = "esp32-c3-supermini"


def header(side: str) -> Footprint:
    """side: 'left' => board edge is at -x of the pins; 'right' => at +x."""
    sgn = -1 if side == "left" else 1
    pads = []
    for i in range(N_PINS):
        n, y = str(i + 1), i * PITCH
        # Hole at the pin centre; oval copper pushed toward the board edge.
        pads.append(Pad(n, (0, y), (OVAL_LEN, PAD_W), "thru_hole", "oval", DRILL, (sgn * OVAL_SHIFT, 0), tag="th"))
        # Castellation: hole centred on the board edge.
        pads.append(Pad(n, (sgn * PIN_EDGE_X, y), (PAD_W, PAD_W), "thru_hole", "circle", DRILL, tag="edge"))
    span = (N_PINS - 1) * PITCH
    return Footprint(
        name=f"SuperMini_Header_1x08_P2.54mm_Castellated_{side.capitalize()}",
        descr=f"ESP32-C3 SuperMini {side} header, 1x08, 2.54 mm pitch, 1.0 mm through-holes with castellated half-holes on the board edge 1.38 mm from the pin centres. Board edge must run along the castellation centres.",
        tags="ESP32-C3 SuperMini castellated header 2.54mm",
        pads=pads,
        ref_pos=(-sgn * (PAD_W / 2 + 0.5), span / 2, 90),
        value_pos=(0, span + 2.5),
    )


def build() -> Design:
    d = Design(
        model_root="${KIPRJMOD}/../../3d",
        project=PROJECT,
        title="ESP32-C3 SuperMini form-factor board",
        comment="Outline and castellated 2x8 header layout identical to the ESP32-C3 SuperMini",
        fp_lib="SuperMini",
        width=BOARD_W,
        height=BOARD_H,
        thickness=1.0,
        castellated_refs=["J1", "J2"],
        sch_note="ESP32-C3 SuperMini form-factor board.\\nJ1 = left header (GPIO5..GPIO21), J2 = right header (5V, GND, 3V3, GPIO4..GPIO0),\\nviewed from the component side with the USB-C end at the top.",
    )
    bx, by = d.bx, d.by
    conn = SymbolRef("Connector_Generic.kicad_sym", "Connector_Generic", "Conn_01x08")
    d.parts.append(Part("J1", header("left"), (bx + PIN_EDGE_X, by + PIN_TOP_Y), conn, "Conn_01x08", {str(i + 1): n for i, n in enumerate(LEFT_PINS)}, (76.2, 101.6), "Left header", models=[Model("esp32-c3-supermini-components.step")]))
    d.parts.append(Part("J2", header("right"), (bx + BOARD_W - PIN_EDGE_X, by + PIN_TOP_Y), conn, "Conn_01x08", {str(i + 1): n for i, n in enumerate(RIGHT_PINS)}, (127.0, 101.6), "Right header"))

    g = d.graphics
    # Pin names (as printed on the SuperMini) beside every pad on both sides.
    # Back copies share the anchor and are mirrored with the justification
    # swapped so they still sit inboard of their pad when read from the back.
    label_in = PIN_EDGE_X + PAD_W / 2 + 0.35
    for i, t in enumerate(LEFT_SILK):
        y = by + PIN_TOP_Y + i * PITCH
        g.append(gr_text(f"silkL{i}", t, bx + label_in, y, "F.SilkS", 0.8, "left"))
        g.append(gr_text(f"silkL{i}:b", t, bx + label_in, y, "B.SilkS", 0.8, "right mirror"))
    for i, t in enumerate(RIGHT_SILK):
        y = by + PIN_TOP_Y + i * PITCH
        g.append(gr_text(f"silkR{i}", t, bx + BOARD_W - label_in, y, "F.SilkS", 0.8, "right"))
        g.append(gr_text(f"silkR{i}:b", t, bx + BOARD_W - label_in, y, "B.SilkS", 0.8, "left mirror"))
    # Reference geometry of the original board on F.Fab (from the STEP model).
    usb_w = 9.0
    g.append(gr_rect("usb", bx + (BOARD_W - usb_w) / 2, by - 1.5, bx + (BOARD_W + usb_w) / 2, by + 5.85, "F.Fab", 0.1, "dash"))
    g.append(gr_text("usb", "USB-C", bx + BOARD_W / 2, by + 3.0, "F.Fab", 0.8))
    for key, dx, txt in (("boot", -2.95, "BOOT"), ("rst", 2.95, "RST")):
        g.append(gr_circle(key, bx + BOARD_W / 2 + dx, by + 8.84, 1.5, "F.Fab", 0.1))
        g.append(gr_text(key, txt, bx + BOARD_W / 2 + dx, by + 11.2, "F.Fab", 0.6))
    g.append(gr_rect("ant", bx + 5.5, by + BOARD_H - 2.6, bx + 12.5, by + BOARD_H, "F.Fab", 0.1, "dash"))
    g.append(gr_text("ant", "ANT", bx + BOARD_W / 2, by + BOARD_H - 1.3, "F.Fab", 0.6))
    g.append(gr_text("title", "ESP32-C3 SuperMini form factor", bx + BOARD_W / 2, by + 15.5, "F.Fab", 0.5))
    return d


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=pathlib.Path, default=pathlib.Path(__file__).resolve().parent.parent / "hardware" / "parts" / PROJECT)
    args = ap.parse_args()
    build().write(args.out)


if __name__ == "__main__":
    main()

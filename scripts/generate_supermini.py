#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Generate a KiCad 9 project reproducing the ESP32-C3 SuperMini outline and
castellated pin headers.

The generator is deterministic (UUIDs are derived from stable names), so
re-running it produces byte-identical files.

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
import textwrap
import uuid

NS = uuid.UUID("7a3c5f2e-1b0d-4e8a-9c6f-2d4b8a1e5c30")


def uid(key: str) -> str:
    return str(uuid.uuid5(NS, key))


# --------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------
BOARD_W = 18.00
BOARD_H = 22.52
PITCH = 2.54
N_PINS = 8
ROW_SPACING = 15.24
PIN_EDGE_X = (BOARD_W - ROW_SPACING) / 2  # 1.38 mm from long edge to pin centre
PIN_TOP_Y = 1.74  # first pin centre from the USB-C edge
DRILL = 1.0
PAD_W = 1.6  # oval pad width / castellation copper diameter

# Pad oval runs from (pin centre - PAD_W/2) out to the board edge.
OVAL_LEN = PIN_EDGE_X + PAD_W / 2  # 2.18
OVAL_SHIFT = (OVAL_LEN / 2) - PAD_W / 2  # 0.29: oval centre is this far toward the edge

# Board placement on the sheet (top-left corner).
BX, BY = 100.0, 100.0

# Pin names, top (USB-C end) to bottom, viewed from the component side.
LEFT_PINS = ["GPIO5", "GPIO6", "GPIO7", "GPIO8", "GPIO9", "GPIO10", "GPIO20", "GPIO21"]
RIGHT_PINS = ["+5V", "GND", "+3V3", "GPIO4", "GPIO3", "GPIO2", "GPIO1", "GPIO0"]
LEFT_SILK = ["5", "6", "7", "8", "9", "10", "20", "21"]
RIGHT_SILK = ["5V", "G", "3.3", "4", "3", "2", "1", "0"]

PROJECT = "esp32-c3-supermini"
FP_LIB = "SuperMini"
FP_LEFT = "SuperMini_Header_1x08_P2.54mm_Castellated_Left"
FP_RIGHT = "SuperMini_Header_1x08_P2.54mm_Castellated_Right"


def fmt(v: float) -> str:
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


# --------------------------------------------------------------------------
# Footprints
# --------------------------------------------------------------------------
def footprint(name: str, side: str) -> str:
    """side: 'left' => board edge is at -x of the pins; 'right' => at +x."""
    sgn = -1 if side == "left" else 1
    pads = []
    for i in range(N_PINS):
        n = i + 1
        y = i * PITCH
        # Through-hole pad with oval copper reaching the board edge.  In KiCad
        # the pad position is the hole centre and (offset) shifts the copper
        # shape relative to it, so the oval is pushed toward the board edge.
        pads.append(
            f"""\
	(pad "{n}" thru_hole oval
		(at 0 {fmt(y)})
		(size {fmt(OVAL_LEN)} {fmt(PAD_W)})
		(drill {fmt(DRILL)}
			(offset {fmt(sgn * OVAL_SHIFT)} 0)
		)
		(layers "*.Cu" "*.Mask")
		(remove_unused_layers no)
		(uuid "{uid(f'{name}:pad{n}:th')}")
	)
	(pad "{n}" thru_hole circle
		(at {fmt(sgn * PIN_EDGE_X)} {fmt(y)})
		(size {fmt(PAD_W)} {fmt(PAD_W)})
		(drill {fmt(DRILL)})
		(layers "*.Cu" "*.Mask")
		(remove_unused_layers no)
		(uuid "{uid(f'{name}:pad{n}:castellation')}")
	)"""
        )
    span = (N_PINS - 1) * PITCH
    # Courtyard: pads plus 0.25 mm, clipped to the board edge side.
    cy_x0 = sgn * PIN_EDGE_X if sgn < 0 else -(PAD_W / 2 + 0.25)
    cy_x1 = PAD_W / 2 + 0.25 if sgn < 0 else sgn * PIN_EDGE_X
    pin1_y = -PAD_W / 2 - 0.25
    fab_x = -sgn * (PAD_W / 2 + 0.5)
    return f"""\
(footprint "{name}"
	(version 20241229)
	(generator "generate_supermini.py")
	(generator_version "9.0")
	(layer "F.Cu")
	(descr "ESP32-C3 SuperMini {side} header, 1x08, 2.54 mm pitch, 1.0 mm through-holes with castellated half-holes on the board edge 1.38 mm from the pin centres. Board edge must run along the castellation centres.")
	(tags "ESP32-C3 SuperMini castellated header 2.54mm")
	(property "Reference" "REF**"
		(at {fmt(fab_x)} -2.5 0)
		(layer "F.SilkS")
		(uuid "{uid(f'{name}:ref')}")
		(effects
			(font
				(size 0.8 0.8)
				(thickness 0.12)
			)
		)
	)
	(property "Value" "{name}"
		(at 0 {fmt(span + 2.5)} 0)
		(layer "F.Fab")
		(uuid "{uid(f'{name}:value')}")
		(effects
			(font
				(size 0.8 0.8)
				(thickness 0.12)
			)
		)
	)
	(property "Datasheet" ""
		(at 0 0 0)
		(layer "F.Fab")
		(hide yes)
		(uuid "{uid(f'{name}:datasheet')}")
		(effects
			(font
				(size 1.27 1.27)
				(thickness 0.15)
			)
		)
	)
	(property "Description" ""
		(at 0 0 0)
		(layer "F.Fab")
		(hide yes)
		(uuid "{uid(f'{name}:description')}")
		(effects
			(font
				(size 1.27 1.27)
				(thickness 0.15)
			)
		)
	)
	(attr through_hole)
	(fp_rect
		(start {fmt(cy_x0)} {fmt(pin1_y)})
		(end {fmt(cy_x1)} {fmt(span + PAD_W / 2 + 0.25)})
		(stroke
			(width 0.05)
			(type solid)
		)
		(fill no)
		(layer "F.CrtYd")
		(uuid "{uid(f'{name}:crtyd')}")
	)
	(fp_text user "${{REFERENCE}}"
		(at {fmt(fab_x)} {fmt(span / 2)} 90)
		(layer "F.Fab")
		(uuid "{uid(f'{name}:fabref')}")
		(effects
			(font
				(size 0.6 0.6)
				(thickness 0.1)
			)
		)
	)
{chr(10).join(pads)}
	(embedded_fonts no)
)
"""


# --------------------------------------------------------------------------
# Schematic
# --------------------------------------------------------------------------
def load_conn_symbol(lib_path: pathlib.Path) -> str:
    txt = lib_path.read_text()
    i = txt.index('(symbol "Conn_01x08"')
    depth = 0
    for j in range(i, len(txt)):
        if txt[j] == "(":
            depth += 1
        elif txt[j] == ")":
            depth -= 1
            if depth == 0:
                break
    sym = txt[i : j + 1]
    sym = sym.replace('(symbol "Conn_01x08"', '(symbol "Connector_Generic:Conn_01x08"', 1)
    # Library file indents symbols by one tab; lib_symbols entries use two.
    return textwrap.indent(sym, "\t")


def sch_symbol(ref: str, key: str, x: float, y: float, fp: str, sheet_uuid: str) -> str:
    pins = "\n".join(
        f"""\
		(pin "{n}"
			(uuid "{uid(f'sch:{key}:pin{n}')}")
		)"""
        for n in range(1, N_PINS + 1)
    )
    return f"""\
	(symbol
		(lib_id "Connector_Generic:Conn_01x08")
		(at {fmt(x)} {fmt(y)} 0)
		(unit 1)
		(exclude_from_sim no)
		(in_bom yes)
		(on_board yes)
		(dnp no)
		(fields_autoplaced yes)
		(uuid "{uid(f'sch:{key}')}")
		(property "Reference" "{ref}"
			(at {fmt(x + 2.54)} {fmt(y - 10.16)} 0)
			(effects
				(font
					(size 1.27 1.27)
				)
				(justify left)
			)
		)
		(property "Value" "Conn_01x08"
			(at {fmt(x + 2.54)} {fmt(y + 12.7)} 0)
			(effects
				(font
					(size 1.27 1.27)
				)
				(justify left)
			)
		)
		(property "Footprint" "{FP_LIB}:{fp}"
			(at {fmt(x)} {fmt(y)} 0)
			(effects
				(font
					(size 1.27 1.27)
				)
				(hide yes)
			)
		)
		(property "Datasheet" "~"
			(at {fmt(x)} {fmt(y)} 0)
			(effects
				(font
					(size 1.27 1.27)
				)
				(hide yes)
			)
		)
		(property "Description" "Generic connector, single row, 01x08, script generated (kicad-library-utils/schlib/autogen/connector/)"
			(at {fmt(x)} {fmt(y)} 0)
			(effects
				(font
					(size 1.27 1.27)
				)
				(hide yes)
			)
		)
{pins}
		(instances
			(project "{PROJECT}"
				(path "/{sheet_uuid}"
					(reference "{ref}")
					(unit 1)
				)
			)
		)
	)
"""


def sch_global_label(name: str, key: str, x: float, y: float) -> str:
    return f"""\
	(global_label "{name}"
		(shape bidirectional)
		(at {fmt(x)} {fmt(y)} 180)
		(fields_autoplaced yes)
		(effects
			(font
				(size 1.27 1.27)
			)
			(justify right)
		)
		(uuid "{uid(f'sch:label:{key}')}")
		(property "Intersheetrefs" "${{INTERSHEET_REFS}}"
			(at {fmt(x - 8)} {fmt(y)} 0)
			(effects
				(font
					(size 1.27 1.27)
				)
				(justify right)
				(hide yes)
			)
		)
	)
"""


def sch_text(text: str, key: str, x: float, y: float) -> str:
    return f"""\
	(text "{text}"
		(exclude_from_sim no)
		(at {fmt(x)} {fmt(y)} 0)
		(effects
			(font
				(size 1.27 1.27)
			)
			(justify left bottom)
		)
		(uuid "{uid(f'sch:text:{key}')}")
	)
"""


def schematic(conn_symbol: str) -> str:
    sheet_uuid = uid("sch:root")
    parts = []
    # Symbol pins sit at x = -5.08, y = +7.62 - 2.54*i (library y-up => sheet y-down).
    # Positions are multiples of 1.27 mm so the pins land on the connection grid.
    for ref, key, sx, names, fp in (
        ("J1", "J1", 76.2, LEFT_PINS, FP_LEFT),
        ("J2", "J2", 127.0, RIGHT_PINS, FP_RIGHT),
    ):
        sy = 101.6
        parts.append(sch_symbol(ref, key, sx, sy, fp, sheet_uuid))
        for i, name in enumerate(names):
            parts.append(sch_global_label(name, f"{key}:{i}", sx - 5.08, sy - 7.62 + i * PITCH))
    parts.append(sch_text("ESP32-C3 SuperMini form-factor board.\\nJ1 = left header (GPIO5..GPIO21), J2 = right header (5V, GND, 3V3, GPIO4..GPIO0),\\nviewed from the component side with the USB-C end at the top.", "note", 60.0, 90.0))
    body = "".join(parts)
    return f"""\
(kicad_sch
	(version 20250114)
	(generator "generate_supermini.py")
	(generator_version "9.0")
	(uuid "{sheet_uuid}")
	(paper "A4")
	(title_block
		(title "ESP32-C3 SuperMini form-factor board")
		(rev "1")
		(comment 1 "Outline and castellated 2x8 header layout identical to the ESP32-C3 SuperMini")
	)
	(lib_symbols
{conn_symbol}
	)
{body}	(sheet_instances
		(path "/"
			(page "1")
		)
	)
	(embedded_fonts no)
)
"""


# --------------------------------------------------------------------------
# Board
# --------------------------------------------------------------------------
def pcb_footprint(name: str, ref: str, key: str, x: float, y: float, side: str, nets: dict[str, int], pin_names: list[str], sheet_uuid: str) -> str:
    fp = footprint(name, side)
    # Convert library footprint into a board footprint: add placement, path, nets.
    fp = fp.replace(
        f'(footprint "{name}"\n\t(version 20241229)\n\t(generator "generate_supermini.py")\n\t(generator_version "9.0")\n\t(layer "F.Cu")\n',
        f'(footprint "{FP_LIB}:{name}"\n\t\t(layer "F.Cu")\n\t\t(uuid "{uid(f"pcb:{key}")}")\n\t\t(at {fmt(x)} {fmt(y)})\n',
        1,
    )
    # The silkscreen reference would land outside the outline; the F.Fab
    # ${REFERENCE} text alongside the pads is kept instead.
    fp = fp.replace(
        '(property "Reference" "REF**"\n\t\t(at ',
        f'(property "Reference" "{ref}"\n\t\t(hide yes)\n\t\t(at ',
        1,
    )
    # Board footprints carry the schematic symbol's value, not the footprint name.
    fp = fp.replace(
        f'(property "Value" "{name}"\n\t\t(at 0 {fmt((N_PINS - 1) * PITCH + 2.5)} 0)\n\t\t(layer "F.Fab")\n',
        f'(property "Value" "Conn_01x08"\n\t\t(at 0 {fmt((N_PINS - 1) * PITCH + 2.5)} 0)\n\t\t(layer "F.Fab")\n\t\t(hide yes)\n',
        1,
    )
    fp = fp.replace(
        "\t(attr through_hole)\n",
        f'\t(path "/{sheet_uuid}/{uid(f"sch:{key}")}")\n\t(sheetname "/")\n\t(sheetfile "{PROJECT}.kicad_sch")\n\t(attr through_hole)\n',
        1,
    )
    for n in range(1, N_PINS + 1):
        net = pin_names[n - 1]
        fp = fp.replace(
            f'\t\t(uuid "{uid(f"{name}:pad{n}:th")}")\n',
            f'\t\t(net {nets[net]} "{net}")\n\t\t(pinfunction "Pin_{n}")\n\t\t(pintype "passive")\n\t\t(uuid "{uid(f"{name}:pad{n}:th")}")\n',
        )
        fp = fp.replace(
            f'\t\t(uuid "{uid(f"{name}:pad{n}:castellation")}")\n',
            f'\t\t(net {nets[net]} "{net}")\n\t\t(pinfunction "Pin_{n}")\n\t\t(pintype "passive")\n\t\t(uuid "{uid(f"{name}:pad{n}:castellation")}")\n',
        )
    # Board footprints are indented one level.
    return textwrap.indent(fp, "\t")


def gr_text(text: str, key: str, x: float, y: float, layer: str, size: float, justify: str, angle: float = 0) -> str:
    # KiCad's grammar has no "center" token: centred text simply omits (justify ...).
    justify_block = "" if justify == "center" else f"\t\t\t(justify {justify})\n"
    return f"""\
	(gr_text "{text}"
		(at {fmt(x)} {fmt(y)} {fmt(angle)})
		(layer "{layer}")
		(uuid "{uid(f'pcb:text:{key}')}")
		(effects
			(font
				(size {fmt(size)} {fmt(size)})
				(thickness {fmt(size * 0.15)})
			)
{justify_block}		)
	)
"""


def gr_rect(key: str, x0: float, y0: float, x1: float, y1: float, layer: str, width: float, stype: str = "solid") -> str:
    return f"""\
	(gr_rect
		(start {fmt(x0)} {fmt(y0)})
		(end {fmt(x1)} {fmt(y1)})
		(stroke
			(width {fmt(width)})
			(type {stype})
		)
		(fill no)
		(layer "{layer}")
		(uuid "{uid(f'pcb:rect:{key}')}")
	)
"""


def gr_circle(key: str, cx: float, cy: float, r: float, layer: str, width: float) -> str:
    return f"""\
	(gr_circle
		(center {fmt(cx)} {fmt(cy)})
		(end {fmt(cx + r)} {fmt(cy)})
		(stroke
			(width {fmt(width)})
			(type solid)
		)
		(fill no)
		(layer "{layer}")
		(uuid "{uid(f'pcb:circle:{key}')}")
	)
"""


def board() -> str:
    sheet_uuid = uid("sch:root")
    net_names = LEFT_PINS + RIGHT_PINS
    nets = {n: i + 1 for i, n in enumerate(net_names)}
    net_decls = '\t(net 0 "")\n' + "".join(f'\t(net {i} "{n}")\n' for n, i in nets.items())

    parts = []
    parts.append(pcb_footprint(FP_LEFT, "J1", "J1", BX + PIN_EDGE_X, BY + PIN_TOP_Y, "left", nets, LEFT_PINS, sheet_uuid))
    parts.append(pcb_footprint(FP_RIGHT, "J2", "J2", BX + BOARD_W - PIN_EDGE_X, BY + PIN_TOP_Y, "right", nets, RIGHT_PINS, sheet_uuid))

    # Board outline.
    parts.append(gr_rect("edge", BX, BY, BX + BOARD_W, BY + BOARD_H, "Edge.Cuts", 0.05))

    # Silkscreen pin labels, inboard of the pads.
    label_in = PIN_EDGE_X + PAD_W / 2 + 0.35
    for i, t in enumerate(LEFT_SILK):
        parts.append(gr_text(t, f"silkL{i}", BX + label_in, BY + PIN_TOP_Y + i * PITCH, "F.SilkS", 0.8, "left"))
    for i, t in enumerate(RIGHT_SILK):
        parts.append(gr_text(t, f"silkR{i}", BX + BOARD_W - label_in, BY + PIN_TOP_Y + i * PITCH, "F.SilkS", 0.8, "right"))

    # Reference geometry of the original board on F.Fab (from the STEP model).
    # USB-C shell: 9.0 mm wide, centred; from 1.5 mm past the top edge to 5.85 mm in.
    usb_w = 9.0
    parts.append(gr_rect("usb", BX + (BOARD_W - usb_w) / 2, BY - 1.5, BX + (BOARD_W + usb_w) / 2, BY + 5.85, "F.Fab", 0.1, "dash"))
    parts.append(gr_text("USB-C", "usb", BX + BOARD_W / 2, BY + 3.0, "F.Fab", 0.8, "center"))
    # BOOT / RST buttons: centres 5.9 mm apart, 8.84 mm from the top edge.
    for key, dx, txt in (("boot", -2.95, "BOOT"), ("rst", 2.95, "RST")):
        parts.append(gr_circle(key, BX + BOARD_W / 2 + dx, BY + 8.84, 1.5, "F.Fab", 0.1))
        parts.append(gr_text(txt, key, BX + BOARD_W / 2 + dx, BY + 11.2, "F.Fab", 0.6, "center"))
    # Ceramic antenna area at the bottom centre (approximate, from photos).
    parts.append(gr_rect("ant", BX + 5.5, BY + BOARD_H - 2.6, BX + 12.5, BY + BOARD_H, "F.Fab", 0.1, "dash"))
    parts.append(gr_text("ANT", "ant", BX + BOARD_W / 2, BY + BOARD_H - 1.3, "F.Fab", 0.6, "center"))
    parts.append(gr_text("ESP32-C3 SuperMini form factor", "title", BX + BOARD_W / 2, BY + 15.5, "F.Fab", 0.5, "center"))

    body = "".join(parts)
    return f"""\
(kicad_pcb
	(version 20241229)
	(generator "generate_supermini.py")
	(generator_version "9.0")
	(general
		(thickness 1.0)
		(legacy_teardrops no)
	)
	(paper "A4")
	(title_block
		(title "ESP32-C3 SuperMini form-factor board")
		(rev "1")
		(comment 1 "Outline and castellated 2x8 header layout identical to the ESP32-C3 SuperMini")
	)
	(layers
		(0 "F.Cu" signal)
		(2 "B.Cu" signal)
		(9 "F.Adhes" user "F.Adhesive")
		(11 "B.Adhes" user "B.Adhesive")
		(13 "F.Paste" user)
		(15 "B.Paste" user)
		(5 "F.SilkS" user "F.Silkscreen")
		(7 "B.SilkS" user "B.Silkscreen")
		(1 "F.Mask" user)
		(3 "B.Mask" user)
		(17 "Dwgs.User" user "User.Drawings")
		(19 "Cmts.User" user "User.Comments")
		(21 "Eco1.User" user "User.Eco1")
		(23 "Eco2.User" user "User.Eco2")
		(25 "Edge.Cuts" user)
		(27 "Margin" user)
		(31 "F.CrtYd" user "F.Courtyard")
		(29 "B.CrtYd" user "B.Courtyard")
		(35 "F.Fab" user)
		(33 "B.Fab" user)
	)
	(setup
		(stackup
			(layer "F.SilkS"
				(type "Top Silk Screen")
			)
			(layer "F.Paste"
				(type "Top Solder Paste")
			)
			(layer "F.Mask"
				(type "Top Solder Mask")
				(thickness 0.01)
			)
			(layer "F.Cu"
				(type "copper")
				(thickness 0.035)
			)
			(layer "dielectric 1"
				(type "core")
				(thickness 0.91)
				(material "FR4")
				(epsilon_r 4.5)
				(loss_tangent 0.02)
			)
			(layer "B.Cu"
				(type "copper")
				(thickness 0.035)
			)
			(layer "B.Mask"
				(type "Bottom Solder Mask")
				(thickness 0.01)
			)
			(layer "B.Paste"
				(type "Bottom Solder Paste")
			)
			(layer "B.SilkS"
				(type "Bottom Silk Screen")
			)
			(copper_finish "ENIG")
			(dielectric_constraints no)
		)
		(pad_to_mask_clearance 0)
		(allow_soldermask_bridges_in_footprints no)
		(tenting front back)
		(aux_axis_origin {fmt(BX)} {fmt(BY)})
		(grid_origin {fmt(BX)} {fmt(BY)})
		(pcbplotparams
			(layerselection 0x00000000_00000000_000310ff_ffffffff)
			(plot_on_all_layers_selection 0x00000000_00000000_00000000_00000000)
			(disableapertmacros no)
			(usegerberextensions no)
			(usegerberattributes yes)
			(usegerberadvancedattributes yes)
			(creategerberjobfile yes)
			(dashed_line_dash_ratio 12.000000)
			(dashed_line_gap_ratio 3.000000)
			(svgprecision 4)
			(plotframeref no)
			(mode 1)
			(useauxorigin yes)
			(hpglpennumber 1)
			(hpglpenspeed 20)
			(hpglpendiameter 15.000000)
			(pdf_front_fp_property_popups yes)
			(pdf_back_fp_property_popups yes)
			(pdf_metadata yes)
			(pdf_single_document no)
			(dxfpolygonmode yes)
			(dxfimperialunits yes)
			(dxfusepcbnewfont yes)
			(psnegative no)
			(psa4output no)
			(plot_black_and_white yes)
			(plotinvisibletext no)
			(sketchpadsonfab no)
			(plotpadnumbers no)
			(hidednponfab no)
			(sketchdnponfab yes)
			(crossoutdnponfab yes)
			(subtractmaskfromsilk no)
			(outputformat 1)
			(mirror no)
			(drillshape 0)
			(scaleselection 1)
			(outputdirectory "gerbers/")
		)
	)
{net_decls}{body}	(embedded_fonts no)
)
"""


# --------------------------------------------------------------------------
# Project, rules, library tables
# --------------------------------------------------------------------------
def project() -> str:
    sheet_uuid = uid("sch:root")
    return f"""\
{{
  "board": {{
    "3dviewports": [],
    "design_settings": {{
      "defaults": {{
        "apply_defaults_to_fp_fields": false,
        "apply_defaults_to_fp_shapes": false,
        "apply_defaults_to_fp_text": false,
        "board_outline_line_width": 0.05,
        "copper_line_width": 0.2,
        "copper_text_italic": false,
        "copper_text_size_h": 1.5,
        "copper_text_size_v": 1.5,
        "copper_text_thickness": 0.3,
        "copper_text_upright": false,
        "courtyard_line_width": 0.05,
        "dimension_precision": 4,
        "dimension_units": 3,
        "dimensions": {{
          "arrow_length": 1270000,
          "extension_offset": 500000,
          "keep_text_aligned": true,
          "suppress_zeroes": false,
          "text_position": 0,
          "units_format": 1
        }},
        "fab_line_width": 0.1,
        "fab_text_italic": false,
        "fab_text_size_h": 1.0,
        "fab_text_size_v": 1.0,
        "fab_text_thickness": 0.15,
        "fab_text_upright": false,
        "other_line_width": 0.1,
        "other_text_italic": false,
        "other_text_size_h": 1.0,
        "other_text_size_v": 1.0,
        "other_text_thickness": 0.15,
        "other_text_upright": false,
        "pads": {{
          "drill": 1.0,
          "height": 1.6,
          "width": 1.6
        }},
        "silk_line_width": 0.12,
        "silk_text_italic": false,
        "silk_text_size_h": 0.8,
        "silk_text_size_v": 0.8,
        "silk_text_thickness": 0.12,
        "silk_text_upright": false,
        "zones": {{
          "min_clearance": 0.5
        }}
      }},
      "diff_pair_dimensions": [],
      "drc_exclusions": [],
      "meta": {{
        "version": 2
      }},
      "rule_severities": {{
        "annular_width": "error",
        "clearance": "error",
        "connection_width": "warning",
        "copper_edge_clearance": "error",
        "copper_sliver": "warning",
        "courtyards_overlap": "error",
        "diff_pair_gap_out_of_range": "error",
        "diff_pair_uncoupled_length_too_long": "error",
        "drill_out_of_range": "error",
        "duplicate_footprints": "warning",
        "extra_footprint": "warning",
        "footprint": "error",
        "footprint_filters_mismatch": "ignore",
        "footprint_symbol_mismatch": "warning",
        "footprint_type_mismatch": "ignore",
        "hole_clearance": "error",
        "hole_near_hole": "error",
        "hole_to_hole": "error",
        "holes_co_located": "warning",
        "invalid_outline": "error",
        "isolated_copper": "warning",
        "item_on_disabled_layer": "error",
        "items_not_allowed": "error",
        "length_out_of_range": "error",
        "lib_footprint_issues": "warning",
        "lib_footprint_mismatch": "warning",
        "malformed_courtyard": "error",
        "microvia_drill_out_of_range": "error",
        "mirrored_text_on_front_layer": "warning",
        "missing_courtyard": "ignore",
        "missing_footprint": "warning",
        "net_conflict": "warning",
        "nonmirrored_text_on_back_layer": "warning",
        "npth_inside_courtyard": "ignore",
        "padstack": "warning",
        "pth_inside_courtyard": "ignore",
        "shorting_items": "error",
        "silk_edge_clearance": "warning",
        "silk_over_copper": "warning",
        "silk_overlap": "warning",
        "skew_out_of_range": "error",
        "solder_mask_bridge": "error",
        "starved_thermal": "error",
        "text_height": "warning",
        "text_thickness": "warning",
        "through_hole_pad_without_hole": "error",
        "too_many_vias": "error",
        "track_angle": "error",
        "track_dangling": "warning",
        "track_segment_length": "error",
        "track_width": "error",
        "tracks_crossing": "error",
        "unconnected_items": "error",
        "unresolved_variable": "error",
        "via_dangling": "warning",
        "zones_intersect": "error"
      }},
      "rules": {{
        "max_error": 0.005,
        "min_clearance": 0.0,
        "min_connection": 0.0,
        "min_copper_edge_clearance": 0.0,
        "min_groove_width": 0.0,
        "min_hole_clearance": 0.25,
        "min_hole_to_hole": 0.25,
        "min_microvia_diameter": 0.2,
        "min_microvia_drill": 0.1,
        "min_resolved_spokes": 2,
        "min_silk_clearance": 0.0,
        "min_text_height": 0.6,
        "min_text_thickness": 0.08,
        "min_through_hole_diameter": 0.3,
        "min_track_width": 0.15,
        "min_via_annular_width": 0.1,
        "min_via_diameter": 0.5,
        "solder_mask_to_copper_clearance": 0.0,
        "use_height_for_length_calcs": true
      }},
      "teardrop_options": [
        {{
          "td_onpthpad": true,
          "td_onroundshapesonly": false,
          "td_onsmdpad": true,
          "td_ontrackend": false,
          "td_onvia": true
        }}
      ],
      "teardrop_parameters": [
        {{
          "td_allow_use_two_tracks": true,
          "td_curve_segcount": 0,
          "td_height_ratio": 1.0,
          "td_length_ratio": 0.5,
          "td_maxheight": 2.0,
          "td_maxlen": 1.0,
          "td_on_pad_in_zone": false,
          "td_target_name": "td_round_shape",
          "td_width_to_size_filter_ratio": 0.9
        }},
        {{
          "td_allow_use_two_tracks": true,
          "td_curve_segcount": 0,
          "td_height_ratio": 1.0,
          "td_length_ratio": 0.5,
          "td_maxheight": 2.0,
          "td_maxlen": 1.0,
          "td_on_pad_in_zone": false,
          "td_target_name": "td_rect_shape",
          "td_width_to_size_filter_ratio": 0.9
        }},
        {{
          "td_allow_use_two_tracks": true,
          "td_curve_segcount": 0,
          "td_height_ratio": 1.0,
          "td_length_ratio": 0.5,
          "td_maxheight": 2.0,
          "td_maxlen": 1.0,
          "td_on_pad_in_zone": false,
          "td_target_name": "td_track_end",
          "td_width_to_size_filter_ratio": 0.9
        }}
      ],
      "track_widths": [],
      "tuning_pattern_settings": {{
        "diff_pair_defaults": {{
          "corner_radius_percentage": 80,
          "corner_style": 1,
          "max_amplitude": 1.0,
          "min_amplitude": 0.2,
          "single_sided": false,
          "spacing": 1.0
        }},
        "diff_pair_skew_defaults": {{
          "corner_radius_percentage": 80,
          "corner_style": 1,
          "max_amplitude": 1.0,
          "min_amplitude": 0.2,
          "single_sided": false,
          "spacing": 0.6
        }},
        "single_track_defaults": {{
          "corner_radius_percentage": 80,
          "corner_style": 1,
          "max_amplitude": 1.0,
          "min_amplitude": 0.1,
          "single_sided": false,
          "spacing": 0.6
        }}
      }},
      "via_dimensions": [],
      "zones_allow_external_fillets": false
    }},
    "ipc2581": {{
      "dist": "",
      "distpn": "",
      "internal_id": "",
      "mfg": "",
      "mpn": ""
    }},
    "layer_pairs": [],
    "layer_presets": [],
    "viewports": []
  }},
  "boards": [],
  "cvpcb": {{
    "equivalence_files": []
  }},
  "erc": {{
    "erc_exclusions": [],
    "meta": {{
      "version": 0
    }},
    "pin_map": [
      [0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 2],
      [0, 2, 0, 1, 0, 0, 1, 0, 2, 2, 2, 2],
      [0, 0, 0, 0, 0, 0, 1, 0, 1, 0, 1, 2],
      [0, 1, 0, 0, 0, 0, 1, 1, 2, 1, 1, 2],
      [0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 2],
      [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2],
      [1, 1, 1, 1, 1, 0, 1, 1, 1, 1, 1, 2],
      [0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 2],
      [0, 2, 1, 2, 0, 0, 1, 0, 2, 2, 2, 2],
      [0, 2, 0, 1, 0, 0, 1, 0, 2, 0, 0, 2],
      [0, 2, 1, 1, 0, 0, 1, 0, 2, 0, 0, 2],
      [2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2]
    ],
    "rule_severities": {{
      "bus_definition_conflict": "error",
      "bus_entry_needed": "error",
      "bus_to_bus_conflict": "error",
      "bus_to_net_conflict": "error",
      "conflicting_netclasses": "error",
      "different_unit_footprint": "error",
      "different_unit_net": "error",
      "duplicate_reference": "error",
      "duplicate_sheet_names": "error",
      "endpoint_off_grid": "warning",
      "extra_units": "error",
      "footprint_filter": "ignore",
      "footprint_link_issues": "warning",
      "four_way_junction": "ignore",
      "global_label_dangling": "warning",
      "hier_label_mismatch": "error",
      "label_dangling": "error",
      "label_multiple_wires": "warning",
      "lib_symbol_issues": "warning",
      "lib_symbol_mismatch": "warning",
      "missing_bidi_pin": "warning",
      "missing_input_pin": "warning",
      "missing_power_pin": "error",
      "missing_unit": "warning",
      "multiple_net_names": "warning",
      "net_not_bus_member": "warning",
      "no_connect_connected": "warning",
      "no_connect_dangling": "warning",
      "pin_not_connected": "error",
      "pin_not_driven": "error",
      "pin_to_pin": "warning",
      "power_pin_not_driven": "error",
      "same_local_global_label": "warning",
      "similar_label_and_power": "warning",
      "similar_labels": "warning",
      "similar_power": "warning",
      "simulation_model_issue": "ignore",
      "single_global_label": "ignore",
      "unannotated": "error",
      "unconnected_wire_endpoint": "warning",
      "unit_value_mismatch": "error",
      "unresolved_variable": "error",
      "wire_dangling": "error"
    }}
  }},
  "libraries": {{
    "pinned_footprint_libs": [],
    "pinned_symbol_libs": []
  }},
  "meta": {{
    "filename": "{PROJECT}.kicad_pro",
    "version": 3
  }},
  "net_settings": {{
    "classes": [
      {{
        "bus_width": 12,
        "clearance": 0.2,
        "diff_pair_gap": 0.25,
        "diff_pair_via_gap": 0.25,
        "diff_pair_width": 0.2,
        "line_style": 0,
        "microvia_diameter": 0.3,
        "microvia_drill": 0.1,
        "name": "Default",
        "pcb_color": "rgba(0, 0, 0, 0.000)",
        "priority": 2147483647,
        "schematic_color": "rgba(0, 0, 0, 0.000)",
        "track_width": 0.25,
        "via_diameter": 0.6,
        "via_drill": 0.3,
        "wire_width": 6
      }}
    ],
    "meta": {{
      "version": 4
    }},
    "net_colors": null,
    "netclass_assignments": null,
    "netclass_patterns": []
  }},
  "pcbnew": {{
    "last_paths": {{
      "gencad": "",
      "idf": "",
      "netlist": "",
      "plot": "",
      "pos_files": "",
      "specctra_dsn": "",
      "step": "",
      "svg": "",
      "vrml": ""
    }},
    "page_layout_descr_file": ""
  }},
  "schematic": {{
    "annotate_start_num": 0,
    "bom_export_filename": "${{PROJECTNAME}}.csv",
    "bom_fmt_presets": [],
    "bom_fmt_settings": {{
      "field_delimiter": ",",
      "keep_line_breaks": false,
      "keep_tabs": false,
      "name": "CSV",
      "ref_delimiter": ",",
      "ref_range_delimiter": "",
      "string_delimiter": "\\""
    }},
    "bom_presets": [],
    "bom_settings": {{
      "exclude_dnp": false,
      "fields_ordered": [
        {{
          "group_by": false,
          "label": "Reference",
          "name": "Reference",
          "show": true
        }},
        {{
          "group_by": true,
          "label": "Value",
          "name": "Value",
          "show": true
        }},
        {{
          "group_by": false,
          "label": "Datasheet",
          "name": "Datasheet",
          "show": true
        }},
        {{
          "group_by": false,
          "label": "Footprint",
          "name": "Footprint",
          "show": true
        }},
        {{
          "group_by": false,
          "label": "Qty",
          "name": "${{QUANTITY}}",
          "show": true
        }},
        {{
          "group_by": true,
          "label": "DNP",
          "name": "${{DNP}}",
          "show": true
        }}
      ],
      "filter_string": "",
      "group_symbols": true,
      "include_excluded_from_bom": false,
      "name": "Grouped By Value",
      "sort_asc": true,
      "sort_field": "Reference"
    }},
    "connection_grid_size": 50.0,
    "drawing": {{
      "dashed_lines_dash_length_ratio": 12.0,
      "dashed_lines_gap_length_ratio": 3.0,
      "default_line_thickness": 6.0,
      "default_text_size": 50.0,
      "field_names": [],
      "intersheets_ref_own_page": false,
      "intersheets_ref_prefix": "",
      "intersheets_ref_short": false,
      "intersheets_ref_show": false,
      "intersheets_ref_suffix": "",
      "junction_size_choice": 3,
      "label_size_ratio": 0.375,
      "operating_point_overlay_i_precision": 3,
      "operating_point_overlay_i_range": "~A",
      "operating_point_overlay_v_precision": 3,
      "operating_point_overlay_v_range": "~V",
      "overbar_offset_ratio": 1.23,
      "pin_symbol_size": 25.0,
      "text_offset_ratio": 0.15
    }},
    "legacy_lib_dir": "",
    "legacy_lib_list": [],
    "meta": {{
      "version": 1
    }},
    "net_format_name": "",
    "page_layout_descr_file": "",
    "plot_directory": "",
    "space_save_all_events": true,
    "spice_current_sheet_as_root": false,
    "spice_external_command": "spice \\"%I\\"",
    "spice_model_current_sheet_as_root": true,
    "spice_save_all_currents": false,
    "spice_save_all_dissipations": false,
    "spice_save_all_voltages": false,
    "subpart_first_id": 65,
    "subpart_id_separator": 0
  }},
  "sheets": [
    [
      "{sheet_uuid}",
      "Root"
    ]
  ],
  "text_variables": {{}}
}}
"""


DRU = """\
(version 1)

# The SuperMini pin headers are castellated: every header pad has a plated
# half-hole centred on the board edge.  KiCad's default DRC treats copper and
# holes touching the outline as errors, so relax those checks for the header
# pads only.  Everything else on the board keeps the normal constraints.
(rule "castellated_header_pads_edge"
	(severity ignore)
	(condition "A.Type == 'Pad' && (A.memberOfFootprint('J1') || A.memberOfFootprint('J2'))")
	(constraint edge_clearance)
)
(rule "castellated_header_pads_holes"
	(condition "A.Type == 'Pad' && B.Type == 'Pad' && A.Net == B.Net && (A.memberOfFootprint('J1') || A.memberOfFootprint('J2'))")
	(constraint hole_to_hole (min 0mm))
)
"""

FP_LIB_TABLE = f"""\
(fp_lib_table
  (version 7)
  (lib (name "{FP_LIB}")(type "KiCad")(uri "${{KIPRJMOD}}/footprints/{FP_LIB}.pretty")(options "")(descr "ESP32-C3 SuperMini castellated headers"))
)
"""

SYM_LIB_TABLE = """\
(sym_lib_table
  (version 7)
)
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=pathlib.Path, default=pathlib.Path(__file__).resolve().parent.parent / "hardware" / PROJECT)
    ap.add_argument(
        "--kicad-symbols",
        type=pathlib.Path,
        default=pathlib.Path("/snap/kicad/current/usr/share/kicad/symbols/Connector_Generic.kicad_sym"),
        help="Stock KiCad Connector_Generic library (only used to embed Conn_01x08 in the schematic)",
    )
    args = ap.parse_args()
    out: pathlib.Path = args.out
    (out / "footprints" / f"{FP_LIB}.pretty").mkdir(parents=True, exist_ok=True)

    files = {
        out / "footprints" / f"{FP_LIB}.pretty" / f"{FP_LEFT}.kicad_mod": footprint(FP_LEFT, "left"),
        out / "footprints" / f"{FP_LIB}.pretty" / f"{FP_RIGHT}.kicad_mod": footprint(FP_RIGHT, "right"),
        out / f"{PROJECT}.kicad_sch": schematic(load_conn_symbol(args.kicad_symbols)),
        out / f"{PROJECT}.kicad_pcb": board(),
        out / f"{PROJECT}.kicad_pro": project(),
        out / f"{PROJECT}.kicad_dru": DRU,
        out / "fp-lib-table": FP_LIB_TABLE,
        out / "sym-lib-table": SYM_LIB_TABLE,
    }
    for path, content in files.items():
        path.write_text(content)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()

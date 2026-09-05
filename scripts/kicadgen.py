"""Minimal KiCad 9 project generator used by the per-board scripts.

Everything is emitted as S-expression / JSON text with UUIDs derived from
stable names, so re-running a generator produces byte-identical files.

Model:

* ``Footprint`` - a library footprint made of ``Pad`` objects plus optional
  extra drawing items (courtyard is generated automatically).
* ``Part`` - a placed footprint on the board with a reference, a stock KiCad
  schematic symbol and a pad-number -> net-name mapping.
* ``Design`` - the board outline, the parts, free graphics, and the list of
  references whose pads are allowed to touch the board edge (castellations).
"""

from __future__ import annotations

import os
import pathlib
import re
import textwrap
import uuid
from dataclasses import dataclass, field

NS = uuid.UUID("7a3c5f2e-1b0d-4e8a-9c6f-2d4b8a1e5c30")
KICAD_SHARE = pathlib.Path(os.environ.get("KICAD_SHARE") or next(
    (p for p in ("/snap/kicad/current/usr/share/kicad", "/usr/share/kicad") if pathlib.Path(p).is_dir()),
    "/usr/share/kicad",
))
# Title-block revision: a KiCad text variable that scripts/export_manufacturing.py
# defines from `git describe` at export time, so the committed files never change.
REV = "${GIT_DESCRIBE}"


def uid(key: str) -> str:
    return str(uuid.uuid5(NS, key))


def fmt(v: float) -> str:
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


# --------------------------------------------------------------------------
# Footprints
# --------------------------------------------------------------------------
@dataclass
class Pad:
    number: str
    at: tuple[float, float]
    size: tuple[float, float]
    kind: str = "thru_hole"  # thru_hole | smd | np_thru_hole
    shape: str = "circle"  # circle | oval | rect | roundrect
    drill: float | None = None
    offset: tuple[float, float] = (0.0, 0.0)
    layers: tuple[str, ...] | None = None
    rot: float = 0.0
    tag: str = ""  # disambiguates several pads with the same number

    def sexpr(self, fp_name: str, net: tuple[int, str] | None, pinfunction: str | None) -> str:
        layers = self.layers
        if layers is None:
            layers = ("*.Cu", "*.Mask") if self.kind != "smd" else ("F.Cu", "F.Mask", "F.Paste")
        at = f"{fmt(self.at[0])} {fmt(self.at[1])}" + (f" {fmt(self.rot)}" if self.rot else "")
        lines = [f'\t(pad "{self.number}" {self.kind} {self.shape}', f"\t\t(at {at})", f"\t\t(size {fmt(self.size[0])} {fmt(self.size[1])})"]
        if self.kind != "smd":
            if self.offset != (0.0, 0.0):
                lines += [f"\t\t(drill {fmt(self.drill)}", f"\t\t\t(offset {fmt(self.offset[0])} {fmt(self.offset[1])})", "\t\t)"]
            else:
                lines.append(f"\t\t(drill {fmt(self.drill)})")
        if self.shape == "roundrect":
            lines.append("\t\t(roundrect_rratio 0.25)")
        lines.append("\t\t(layers " + " ".join(f'"{l}"' for l in layers) + ")")
        if self.kind == "thru_hole":
            lines.append("\t\t(remove_unused_layers no)")
        if net is not None:
            lines.append(f'\t\t(net {net[0]} "{net[1]}")')
        if pinfunction:
            lines += [f'\t\t(pinfunction "{pinfunction}")', '\t\t(pintype "passive")']
        lines.append(f'\t\t(uuid "{uid(f"{fp_name}:pad{self.number}:{self.tag}")}")')
        lines.append("\t)")
        return "\n".join(lines)

    def bbox(self) -> tuple[float, float, float, float]:
        cx, cy = self.at[0] + self.offset[0], self.at[1] + self.offset[1]
        w, h = self.size
        if self.rot % 180 == 90:
            w, h = h, w
        return cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2


def fp_rect(key: str, x0: float, y0: float, x1: float, y1: float, layer: str, width: float, stype: str = "solid") -> str:
    return f"""\
	(fp_rect
		(start {fmt(x0)} {fmt(y0)})
		(end {fmt(x1)} {fmt(y1)})
		(stroke
			(width {fmt(width)})
			(type {stype})
		)
		(fill no)
		(layer "{layer}")
		(uuid "{uid(key)}")
	)"""


def fp_circle(key: str, cx: float, cy: float, r: float, layer: str, width: float) -> str:
    return f"""\
	(fp_circle
		(center {fmt(cx)} {fmt(cy)})
		(end {fmt(cx + r)} {fmt(cy)})
		(stroke
			(width {fmt(width)})
			(type solid)
		)
		(fill no)
		(layer "{layer}")
		(uuid "{uid(key)}")
	)"""


def fp_text(key: str, text: str, x: float, y: float, layer: str, size: float, angle: float = 0, justify: str | None = None) -> str:
    j = f"\n\t\t\t(justify {justify})" if justify else ""
    return f"""\
	(fp_text user "{text}"
		(at {fmt(x)} {fmt(y)} {fmt(angle)})
		(layer "{layer}")
		(uuid "{uid(key)}")
		(effects
			(font
				(size {fmt(size)} {fmt(size)})
				(thickness {fmt(size * 0.15)})
			){j}
		)
	)"""


@dataclass
class Footprint:
    name: str
    descr: str
    tags: str
    pads: list[Pad]
    extra: list[str] = field(default_factory=list)  # fp_* items
    attr: str = "through_hole"
    courtyard: bool = True
    ref_pos: tuple[float, float, float] = (0.0, -2.5, 0.0)  # x, y, angle of the reference text
    value_pos: tuple[float, float] = (0.0, 2.5)

    def property_block(self, name: str, value: str, at: tuple[float, float, float], layer: str, hide: bool, size: float) -> str:
        return f"""\
	(property "{name}" "{value}"
		(at {fmt(at[0])} {fmt(at[1])} {fmt(at[2])})
		(layer "{layer}")
{'		(hide yes)' + chr(10) if hide else ''}		(uuid "{uid(f'{self.name}:{name}')}")
		(effects
			(font
				(size {fmt(size)} {fmt(size)})
				(thickness {fmt(size * 0.15)})
			)
		)
	)"""

    def body(self, ref: str, value: str, nets: dict[str, tuple[int, str]] | None, on_board: bool, models: str = "") -> str:
        """Everything after the header line; shared by library and board forms.
        models: pre-rendered (model ...) blocks appended on the board form."""
        parts = [
            self.property_block("Reference", ref, self.ref_pos, "F.SilkS", on_board, 0.8),
            self.property_block("Value", value, (*self.value_pos, 0), "F.Fab", on_board, 0.8),
            self.property_block("Datasheet", "", (0, 0, 0), "F.Fab", True, 1.27),
            self.property_block("Description", "", (0, 0, 0), "F.Fab", True, 1.27),
        ]
        parts.append(f"\t(attr {self.attr})")
        if self.courtyard and self.pads:
            xs0, ys0, xs1, ys1 = zip(*(p.bbox() for p in self.pads))
            m = 0.25
            parts.append(fp_rect(f"{self.name}:crtyd", min(xs0) - m, min(ys0) - m, max(xs1) + m, max(ys1) + m, "F.CrtYd", 0.05))
        parts.append(fp_text(f"{self.name}:fabref", "${REFERENCE}", self.ref_pos[0], self.ref_pos[1], "F.Fab", 0.6, self.ref_pos[2]))
        parts.extend(self.extra)
        for pad in self.pads:
            net = nets.get(pad.number) if nets else None
            parts.append(pad.sexpr(self.name, net, f"Pin_{pad.number}" if net else None))
        parts.append("\t(embedded_fonts no)")
        if models:
            parts.append(models)
        return "\n".join(parts)

    def library_text(self) -> str:
        return f"""\
(footprint "{self.name}"
	(version 20241229)
	(generator "kicadgen.py")
	(generator_version "9.0")
	(layer "F.Cu")
	(descr "{self.descr}")
	(tags "{self.tags}")
{self.body('REF**', self.name, None, on_board=False)}
)
"""


# --------------------------------------------------------------------------
# Schematic symbols (embedded from the stock KiCad libraries)
# --------------------------------------------------------------------------
@dataclass
class SymbolRef:
    lib_file: str  # e.g. Connector_Generic.kicad_sym
    lib: str  # e.g. Connector_Generic
    name: str  # e.g. Conn_01x08


_PIN_RE = re.compile(r'\(pin\s+\w+\s+\w+\s*\n\s*\(at\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\)\s*\n\s*\(length\s+([-\d.]+)\)[\s\S]*?\(number\s+"([^"]+)"')


def load_symbol(sym: SymbolRef, share: pathlib.Path = KICAD_SHARE) -> tuple[str, dict[str, tuple[float, float, float]]]:
    """Return (lib_symbols entry text, {pin number: (x, y, angle)})."""
    txt = (share / "symbols" / sym.lib_file).read_text()
    i = txt.index(f'(symbol "{sym.name}"\n')
    depth = 0
    for j in range(i, len(txt)):
        if txt[j] == "(":
            depth += 1
        elif txt[j] == ")":
            depth -= 1
            if depth == 0:
                break
    body = txt[i : j + 1]
    if "(extends " in body:
        raise ValueError(f"{sym.name} extends another symbol; not supported")
    pins = {m.group(5): (float(m.group(1)), float(m.group(2)), float(m.group(3))) for m in _PIN_RE.finditer(body)}
    body = body.replace(f'(symbol "{sym.name}"', f'(symbol "{sym.lib}:{sym.name}"', 1)
    return textwrap.indent(body, "\t"), pins


# --------------------------------------------------------------------------
# Design
# --------------------------------------------------------------------------
@dataclass
class Model:
    """A 3D model on a footprint: file name under the design's model_root,
    offset in mm and rotation in degrees in KiCad's model frame (X right, Y
    up, Z out of the board).  Note KiCad rotates by the NEGATIVE of the angles
    stored in the file (the footprint editor shows them negated)."""

    file: str
    offset: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotate: tuple[float, float, float] = (0.0, 0.0, 0.0)

    def sexpr(self, root: str) -> str:
        return f"""\
	(model "{root}/{self.file}"
		(offset
			(xyz {fmt(self.offset[0])} {fmt(self.offset[1])} {fmt(self.offset[2])})
		)
		(scale
			(xyz 1 1 1)
		)
		(rotate
			(xyz {fmt(self.rotate[0])} {fmt(self.rotate[1])} {fmt(self.rotate[2])})
		)
	)"""


@dataclass
class Part:
    ref: str
    fp: Footprint
    at: tuple[float, float]  # absolute board position of the footprint origin
    symbol: SymbolRef
    value: str
    nets: dict[str, str]  # pad number -> net name
    sch_at: tuple[float, float]
    description: str = ""
    models: list[Model] = field(default_factory=list)


def gr_text(key: str, text: str, x: float, y: float, layer: str, size: float, justify: str | None = None, angle: float = 0) -> str:
    j = f"\n\t\t\t(justify {justify})" if justify else ""
    return f"""\
	(gr_text "{text}"
		(at {fmt(x)} {fmt(y)} {fmt(angle)})
		(layer "{layer}")
		(uuid "{uid(f'pcb:text:{key}')}")
		(effects
			(font
				(size {fmt(size)} {fmt(size)})
				(thickness {fmt(size * 0.15)})
			){j}
		)
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


def gr_line(key: str, x0: float, y0: float, x1: float, y1: float, layer: str, width: float, stype: str = "solid") -> str:
    return f"""\
	(gr_line
		(start {fmt(x0)} {fmt(y0)})
		(end {fmt(x1)} {fmt(y1)})
		(stroke
			(width {fmt(width)})
			(type {stype})
		)
		(layer "{layer}")
		(uuid "{uid(f'pcb:line:{key}')}")
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


@dataclass
class Track:
    net: str
    layer: str
    width: float
    points: list[tuple[float, float]]  # absolute board coordinates, polyline

    def sexpr(self, key: str, net_id: int) -> str:
        out = []
        for i, (a, b) in enumerate(zip(self.points, self.points[1:])):
            out.append(f"""\
	(segment
		(start {fmt(a[0])} {fmt(a[1])})
		(end {fmt(b[0])} {fmt(b[1])})
		(width {fmt(self.width)})
		(layer "{self.layer}")
		(net {net_id})
		(uuid "{uid(f'pcb:track:{key}:{i}')}")
	)
""")
        return "".join(out)


@dataclass
class Via:
    net: str
    at: tuple[float, float]
    size: float = 0.8
    drill: float = 0.4

    def sexpr(self, key: str, net_id: int) -> str:
        return f"""\
	(via
		(at {fmt(self.at[0])} {fmt(self.at[1])})
		(size {fmt(self.size)})
		(drill {fmt(self.drill)})
		(layers "F.Cu" "B.Cu")
		(net {net_id})
		(uuid "{uid(f'pcb:via:{key}')}")
	)
"""


@dataclass
class Zone:
    """A copper pour (net != "") or a keepout area (net == "")."""

    net: str
    layers: tuple[str, ...]
    name: str
    points: list[tuple[float, float]]  # absolute board coordinates, closed polygon
    clearance: float = 0.3
    min_thickness: float = 0.25
    keepout_tracks: bool = False  # keepout areas only
    keepout_pour: bool = True
    solid_pads: bool = False  # connect pads solidly instead of with thermal reliefs
    fills: str = ""  # (filled_polygon ...) blocks inserted by scripts/fill_zones.py

    def sexpr(self, key: str, net_id: int) -> str:
        pts = "\n".join(f"\t\t\t\t(xy {fmt(x)} {fmt(y)})" for x, y in self.points)
        layer = f'(layer "{self.layers[0]}")' if len(self.layers) == 1 else "(layers " + " ".join(f'"{l}"' for l in self.layers) + ")"
        if self.net:
            body = f"""\
\t\t(connect_pads{' yes' if self.solid_pads else ''}
\t\t\t(clearance {fmt(self.clearance)})
\t\t)
\t\t(min_thickness {fmt(self.min_thickness)})
\t\t(filled_areas_thickness no)
\t\t(fill yes
\t\t\t(thermal_gap 0.5)
\t\t\t(thermal_bridge_width 0.5)
\t\t)
"""
        else:
            allow = lambda b: "not_allowed" if b else "allowed"  # noqa: E731
            body = f"""\
\t\t(connect_pads
\t\t\t(clearance 0)
\t\t)
\t\t(min_thickness {fmt(self.min_thickness)})
\t\t(filled_areas_thickness no)
\t\t(keepout
\t\t\t(tracks {allow(self.keepout_tracks)})
\t\t\t(vias {allow(self.keepout_tracks)})
\t\t\t(pads allowed)
\t\t\t(copperpour {allow(self.keepout_pour)})
\t\t\t(footprints allowed)
\t\t)
\t\t(fill
\t\t\t(thermal_gap 0.5)
\t\t\t(thermal_bridge_width 0.5)
\t\t)
"""
        return f"""\
\t(zone
\t\t(net {net_id})
\t\t(net_name "{self.net}")
\t\t{layer}
\t\t(uuid "{uid(f'pcb:zone:{key}')}")
\t\t(name "{self.name}")
\t\t(hatch edge 0.5)
{body}\t\t(polygon
\t\t\t(pts
{pts}
\t\t\t)
\t\t)
{self.fills}\t)
"""


@dataclass
class Design:
    project: str
    title: str
    comment: str
    fp_lib: str
    width: float
    height: float
    thickness: float
    origin: tuple[float, float] = (100.0, 100.0)
    parts: list[Part] = field(default_factory=list)
    graphics: list[str] = field(default_factory=list)
    tracks: list[Track] = field(default_factory=list)
    vias: list[Via] = field(default_factory=list)
    zones: list[Zone] = field(default_factory=list)
    castellated_refs: list[str] = field(default_factory=list)
    sch_note: str = ""
    model_root: str = "${KIPRJMOD}/../3d"  # where Part.models files live, as written into the board

    # -- helpers ----------------------------------------------------------
    @property
    def bx(self) -> float:
        return self.origin[0]

    @property
    def by(self) -> float:
        return self.origin[1]

    def net_table(self) -> dict[str, int]:
        nets: dict[str, int] = {}
        for p in self.parts:
            for n in p.nets.values():
                nets.setdefault(n, len(nets) + 1)
        return nets

    # -- board --------------------------------------------------------------
    def pcb_footprint(self, part: Part, nets: dict[str, int], sheet_uuid: str) -> str:
        pad_nets = {pn: (nets[n], n) for pn, n in part.nets.items()}
        head = f"""\
(footprint "{self.fp_lib}:{part.fp.name}"
	(layer "F.Cu")
	(uuid "{uid(f'pcb:{part.ref}')}")
	(at {fmt(part.at[0])} {fmt(part.at[1])})
	(descr "{part.fp.descr}")
	(tags "{part.fp.tags}")
	(path "/{sheet_uuid}/{uid(f'sch:{part.ref}')}")
	(sheetname "/")
	(sheetfile "{self.project}.kicad_sch")
"""
        models = "\n".join(m.sexpr(self.model_root) for m in part.models)
        return textwrap.indent(head + part.fp.body(part.ref, part.value, pad_nets, on_board=True, models=models) + "\n)\n", "\t")

    def board_text(self) -> str:
        sheet_uuid = uid("sch:root")
        nets = self.net_table()
        net_decls = '\t(net 0 "")\n' + "".join(f'\t(net {i} "{n}")\n' for n, i in nets.items())
        body = "".join(self.pcb_footprint(p, nets, sheet_uuid) for p in self.parts)
        body += gr_rect("edge", self.bx, self.by, self.bx + self.width, self.by + self.height, "Edge.Cuts", 0.05)
        body += "".join(self.graphics)
        body += "".join(t.sexpr(f"{t.net}:{t.layer}:{i}", nets[t.net]) for i, t in enumerate(self.tracks))
        body += "".join(v.sexpr(f"{v.net}:{i}", nets[v.net]) for i, v in enumerate(self.vias))
        body += "".join(z.sexpr(z.name, nets[z.net] if z.net else 0) for z in self.zones)
        core = self.thickness - 0.07 - 0.02
        return f"""\
(kicad_pcb
	(version 20241229)
	(generator "kicadgen.py")
	(generator_version "9.0")
	(general
		(thickness {fmt(self.thickness)})
		(legacy_teardrops no)
	)
	(paper "A4")
	(title_block
		(title "{self.title}")
		(rev "{REV}")
		(comment 1 "{self.comment}")
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
				(thickness {fmt(core)})
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
		(aux_axis_origin {fmt(self.bx)} {fmt(self.by)})
		(grid_origin {fmt(self.bx)} {fmt(self.by)})
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

    # -- schematic ----------------------------------------------------------
    def sch_symbol(self, part: Part, pins: dict[str, tuple[float, float, float]], sheet_uuid: str) -> str:
        x, y = part.sch_at
        pin_blocks = "\n".join(
            f"""\
		(pin "{n}"
			(uuid "{uid(f'sch:{part.ref}:pin{n}')}")
		)"""
            for n in pins
        )
        return f"""\
	(symbol
		(lib_id "{part.symbol.lib}:{part.symbol.name}")
		(at {fmt(x)} {fmt(y)} 0)
		(unit 1)
		(exclude_from_sim no)
		(in_bom yes)
		(on_board yes)
		(dnp no)
		(fields_autoplaced yes)
		(uuid "{uid(f'sch:{part.ref}')}")
		(property "Reference" "{part.ref}"
			(at {fmt(x + 2.54)} {fmt(y - 12.7)} 0)
			(effects
				(font
					(size 1.27 1.27)
				)
				(justify left)
			)
		)
		(property "Value" "{part.value}"
			(at {fmt(x + 2.54)} {fmt(y + 12.7)} 0)
			(effects
				(font
					(size 1.27 1.27)
				)
				(justify left)
			)
		)
		(property "Footprint" "{self.fp_lib}:{part.fp.name}"
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
		(property "Description" "{part.description}"
			(at {fmt(x)} {fmt(y)} 0)
			(effects
				(font
					(size 1.27 1.27)
				)
				(hide yes)
			)
		)
{pin_blocks}
		(instances
			(project "{self.project}"
				(path "/{sheet_uuid}"
					(reference "{part.ref}")
					(unit 1)
				)
			)
		)
	)
"""

    @staticmethod
    def sch_global_label(name: str, key: str, x: float, y: float, pin_angle: float) -> str:
        rot = {0: 180, 180: 0, 90: 270, 270: 90}[int(pin_angle) % 360]
        justify = "left" if rot in (0, 90) else "right"
        return f"""\
	(global_label "{name}"
		(shape bidirectional)
		(at {fmt(x)} {fmt(y)} {rot})
		(fields_autoplaced yes)
		(effects
			(font
				(size 1.27 1.27)
			)
			(justify {justify})
		)
		(uuid "{uid(f'sch:label:{key}')}")
		(property "Intersheetrefs" "${{INTERSHEET_REFS}}"
			(at {fmt(x)} {fmt(y)} 0)
			(effects
				(font
					(size 1.27 1.27)
				)
				(justify {justify})
				(hide yes)
			)
		)
	)
"""

    def schematic_text(self) -> str:
        sheet_uuid = uid("sch:root")
        lib_symbols: dict[str, str] = {}
        body = []
        for part in self.parts:
            key = f"{part.symbol.lib}:{part.symbol.name}"
            if key not in lib_symbols:
                lib_symbols[key], _ = load_symbol(part.symbol)
            _, pins = load_symbol(part.symbol)
            body.append(self.sch_symbol(part, pins, sheet_uuid))
            sx, sy = part.sch_at
            for n, (px, py, ang) in pins.items():
                net = part.nets.get(n)
                if net is None:
                    continue
                body.append(self.sch_global_label(net, f"{part.ref}:{n}", sx + px, sy - py, ang))
        note = ""
        if self.sch_note:
            note = f"""\
	(text "{self.sch_note}"
		(exclude_from_sim no)
		(at 60 90 0)
		(effects
			(font
				(size 1.27 1.27)
			)
			(justify left bottom)
		)
		(uuid "{uid('sch:text:note')}")
	)
"""
        return f"""\
(kicad_sch
	(version 20250114)
	(generator "kicadgen.py")
	(generator_version "9.0")
	(uuid "{sheet_uuid}")
	(paper "A4")
	(title_block
		(title "{self.title}")
		(rev "{REV}")
		(comment 1 "{self.comment}")
	)
	(lib_symbols
{chr(10).join(lib_symbols.values())}
	)
{''.join(body)}{note}	(sheet_instances
		(path "/"
			(page "1")
		)
	)
	(embedded_fonts no)
)
"""

    # -- project / rules / tables -------------------------------------------
    def dru_text(self) -> str:
        if not self.castellated_refs:
            return "(version 1)\n"
        cond = " || ".join(f"A.memberOfFootprint('{r}')" for r in self.castellated_refs)
        return f"""\
(version 1)

# Pads of these footprints are castellated / reach the board edge.  KiCad's
# default DRC treats copper and holes touching the outline as errors, so
# relax those checks for them only.  Everything else keeps the normal rules.
(rule "edge_pads_edge_clearance"
	(severity ignore)
	(condition "A.Type == 'Pad' && ({cond})")
	(constraint edge_clearance)
)
(rule "edge_pads_hole_to_hole"
	(condition "A.Type == 'Pad' && B.Type == 'Pad' && A.Net == B.Net && ({cond})")
	(constraint hole_to_hole (min 0mm))
)
"""

    def project_text(self) -> str:
        sheet_uuid = uid("sch:root")
        return PROJECT_TEMPLATE.replace("@PROJECT@", self.project).replace("@SHEET_UUID@", sheet_uuid)

    def write(self, out: pathlib.Path) -> None:
        pretty = out / "footprints" / f"{self.fp_lib}.pretty"
        pretty.mkdir(parents=True, exist_ok=True)
        files: dict[pathlib.Path, str] = {}
        seen: set[str] = set()
        for p in self.parts:
            if p.fp.name not in seen:
                seen.add(p.fp.name)
                files[pretty / f"{p.fp.name}.kicad_mod"] = p.fp.library_text()
        files[out / f"{self.project}.kicad_sch"] = self.schematic_text()
        files[out / f"{self.project}.kicad_pcb"] = self.board_text()
        files[out / f"{self.project}.kicad_pro"] = self.project_text()
        files[out / f"{self.project}.kicad_dru"] = self.dru_text()
        files[out / "fp-lib-table"] = f"""\
(fp_lib_table
  (version 7)
  (lib (name "{self.fp_lib}")(type "KiCad")(uri "${{KIPRJMOD}}/footprints/{self.fp_lib}.pretty")(options "")(descr "{self.title}"))
)
"""
        files[out / "sym-lib-table"] = "(sym_lib_table\n  (version 7)\n)\n"
        for path, content in files.items():
            path.write_text(content)
            print(f"wrote {path}")


PROJECT_TEMPLATE = r"""{
  "board": {
    "3dviewports": [],
    "design_settings": {
      "defaults": {
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
        "dimensions": {
          "arrow_length": 1270000,
          "extension_offset": 500000,
          "keep_text_aligned": true,
          "suppress_zeroes": false,
          "text_position": 0,
          "units_format": 1
        },
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
        "pads": {
          "drill": 1.0,
          "height": 1.6,
          "width": 1.6
        },
        "silk_line_width": 0.12,
        "silk_text_italic": false,
        "silk_text_size_h": 0.8,
        "silk_text_size_v": 0.8,
        "silk_text_thickness": 0.12,
        "silk_text_upright": false,
        "zones": {
          "min_clearance": 0.5
        }
      },
      "diff_pair_dimensions": [],
      "drc_exclusions": [],
      "meta": {
        "version": 2
      },
      "rule_severities": {
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
      },
      "rules": {
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
        "min_text_height": 0.5,
        "min_text_thickness": 0.07,
        "min_through_hole_diameter": 0.3,
        "min_track_width": 0.15,
        "min_via_annular_width": 0.1,
        "min_via_diameter": 0.5,
        "solder_mask_to_copper_clearance": 0.0,
        "use_height_for_length_calcs": true
      },
      "teardrop_options": [
        {
          "td_onpthpad": true,
          "td_onroundshapesonly": false,
          "td_onsmdpad": true,
          "td_ontrackend": false,
          "td_onvia": true
        }
      ],
      "teardrop_parameters": [
        {
          "td_allow_use_two_tracks": true,
          "td_curve_segcount": 0,
          "td_height_ratio": 1.0,
          "td_length_ratio": 0.5,
          "td_maxheight": 2.0,
          "td_maxlen": 1.0,
          "td_on_pad_in_zone": false,
          "td_target_name": "td_round_shape",
          "td_width_to_size_filter_ratio": 0.9
        },
        {
          "td_allow_use_two_tracks": true,
          "td_curve_segcount": 0,
          "td_height_ratio": 1.0,
          "td_length_ratio": 0.5,
          "td_maxheight": 2.0,
          "td_maxlen": 1.0,
          "td_on_pad_in_zone": false,
          "td_target_name": "td_rect_shape",
          "td_width_to_size_filter_ratio": 0.9
        },
        {
          "td_allow_use_two_tracks": true,
          "td_curve_segcount": 0,
          "td_height_ratio": 1.0,
          "td_length_ratio": 0.5,
          "td_maxheight": 2.0,
          "td_maxlen": 1.0,
          "td_on_pad_in_zone": false,
          "td_target_name": "td_track_end",
          "td_width_to_size_filter_ratio": 0.9
        }
      ],
      "track_widths": [],
      "tuning_pattern_settings": {
        "diff_pair_defaults": {
          "corner_radius_percentage": 80,
          "corner_style": 1,
          "max_amplitude": 1.0,
          "min_amplitude": 0.2,
          "single_sided": false,
          "spacing": 1.0
        },
        "diff_pair_skew_defaults": {
          "corner_radius_percentage": 80,
          "corner_style": 1,
          "max_amplitude": 1.0,
          "min_amplitude": 0.2,
          "single_sided": false,
          "spacing": 0.6
        },
        "single_track_defaults": {
          "corner_radius_percentage": 80,
          "corner_style": 1,
          "max_amplitude": 1.0,
          "min_amplitude": 0.1,
          "single_sided": false,
          "spacing": 0.6
        }
      },
      "via_dimensions": [],
      "zones_allow_external_fillets": false
    },
    "ipc2581": {
      "dist": "",
      "distpn": "",
      "internal_id": "",
      "mfg": "",
      "mpn": ""
    },
    "layer_pairs": [],
    "layer_presets": [],
    "viewports": []
  },
  "boards": [],
  "cvpcb": {
    "equivalence_files": []
  },
  "erc": {
    "erc_exclusions": [],
    "meta": {
      "version": 0
    },
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
    "rule_severities": {
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
    }
  },
  "libraries": {
    "pinned_footprint_libs": [],
    "pinned_symbol_libs": []
  },
  "meta": {
    "filename": "@PROJECT@.kicad_pro",
    "version": 3
  },
  "net_settings": {
    "classes": [
      {
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
      }
    ],
    "meta": {
      "version": 4
    },
    "net_colors": null,
    "netclass_assignments": null,
    "netclass_patterns": []
  },
  "pcbnew": {
    "last_paths": {
      "gencad": "",
      "idf": "",
      "netlist": "",
      "plot": "",
      "pos_files": "",
      "specctra_dsn": "",
      "step": "",
      "svg": "",
      "vrml": ""
    },
    "page_layout_descr_file": ""
  },
  "schematic": {
    "annotate_start_num": 0,
    "bom_export_filename": "${PROJECTNAME}.csv",
    "bom_fmt_presets": [],
    "bom_fmt_settings": {
      "field_delimiter": ",",
      "keep_line_breaks": false,
      "keep_tabs": false,
      "name": "CSV",
      "ref_delimiter": ",",
      "ref_range_delimiter": "",
      "string_delimiter": "\""
    },
    "bom_presets": [],
    "bom_settings": {
      "exclude_dnp": false,
      "fields_ordered": [
        {
          "group_by": false,
          "label": "Reference",
          "name": "Reference",
          "show": true
        },
        {
          "group_by": true,
          "label": "Value",
          "name": "Value",
          "show": true
        },
        {
          "group_by": false,
          "label": "Datasheet",
          "name": "Datasheet",
          "show": true
        },
        {
          "group_by": false,
          "label": "Footprint",
          "name": "Footprint",
          "show": true
        },
        {
          "group_by": false,
          "label": "Qty",
          "name": "${QUANTITY}",
          "show": true
        },
        {
          "group_by": true,
          "label": "DNP",
          "name": "${DNP}",
          "show": true
        }
      ],
      "filter_string": "",
      "group_symbols": true,
      "include_excluded_from_bom": false,
      "name": "Grouped By Value",
      "sort_asc": true,
      "sort_field": "Reference"
    },
    "connection_grid_size": 50.0,
    "drawing": {
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
    },
    "legacy_lib_dir": "",
    "legacy_lib_list": [],
    "meta": {
      "version": 1
    },
    "net_format_name": "",
    "page_layout_descr_file": "",
    "plot_directory": "",
    "space_save_all_events": true,
    "spice_current_sheet_as_root": false,
    "spice_external_command": "spice \"%I\"",
    "spice_model_current_sheet_as_root": true,
    "spice_save_all_currents": false,
    "spice_save_all_dissipations": false,
    "spice_save_all_voltages": false,
    "subpart_first_id": 65,
    "subpart_id_separator": 0
  },
  "sheets": [
    [
      "@SHEET_UUID@",
      "Root"
    ]
  ],
  "text_variables": {
    "GIT_DESCRIBE": "(git describe)"
  }
}
"""

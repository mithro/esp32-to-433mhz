#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Draw the mechanical drawings (SVG) of the socket adapter's printed case.

Every number on the sheets is an f-string of a constant in
scripts/case_dims.py, the constants scripts/build_case.py builds the solids
from, and every one is tagged with the name of the measurement build_case
takes of the finished solids (hardware/case/esp32c3-radio-adapter-case-
measured.json), so `--check` can read the numbers back out of the SVG
files and compare them with what the solids measure.  The sheets are sized
in millimetres (2:1 for the views, 5:1 and 10:1 for the details), so a
print at 100 % lays on a part.  Written to docs/images/case-*.svg:

  case-bottom-plan.svg      1  bottom half from above: cavity, standoffs and
                               pegs, lip, tabs, the cut-outs on the seam
  case-top-plan.svg         2  top half from below: skirt and rebate, grooves,
                               bosses, the window head, the half-hole, notch
  case-section-antenna.svg  3  section A-A on the antenna axis, closed
  case-end-elevations.svg   4  the USB-C wall and the antenna wall, closed
  case-snap-detail.svg      5  sections C-C (a tab) and D-D (the plain lip),
                               a tab from outside
  case-peg-detail.svg       6  section B-B: peg, PCB and boss at H1 and H3
  case-top-slot-plan.svg    7  the slotted top half from above: the J4 slot

The script also rewrites the caliper checklist in docs/case-drawings.md
(between its checklist markers) from the same constants.

VIEW DIRECTIONS.  The board frame as drawn (x right, y down, z toward the
viewer of a plan) is left-handed, so a view from a side is easy to
mirror.  The rule, derived from the right-handed CadQuery frame (model
Y = -board y) and used for every non-plan view below: a viewer looking
along direction d with z up has board direction d x z to their right, so
  from -x (the USB-C wall from outside)  +y runs RIGHT (antenna end right)
  from +y (the antenna wall from outside) +x runs RIGHT (USB-C wall left)
  from -y (the J4 end from outside)       +x runs LEFT
  from +x (the plain wall from outside)   +y runs LEFT
and a section viewed from -x laid out with y running DOWN the sheet has z
running RIGHT (floor on the left).  Sections A-A and B-B are viewed from
-x, C-C and D-D from +y, and the marks on sheet 1 point that way.
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import re
import subprocess
import sys
import xml.dom.minidom

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import case_dims as d  # noqa: E402
from export_manufacturing import git_describe  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "images"
MEASURED = ROOT / "hardware" / "case" / "esp32c3-radio-adapter-case-measured.json"
DOC = ROOT / "docs" / "case-drawings.md"
MODEL_DIR = "hardware/case"  # the STL files and the measured JSON: the drawings' revision is theirs
STL = {h: f"esp32c3-radio-adapter-case-{h}.stl" for h in ("bottom", "top", "top-slot")}
STEP = {h: f"hardware/3d/esp32c3-radio-adapter-case-{h}.step" for h in ("bottom", "top", "top-slot")}
PART = "ESP32-C3 radio adapter case"
SHEETS_N = 7
CHECK_TOL = 0.025  # a quoted value (2 dp) against the solid's measurement (build_case allows 0.02)
SCALE_BAR = 20.0  # sheet mm each scale bar is long: 10 mm of part at 2:1, 4 at 5:1, 2 at 10:1

INK = "#1a1a2e"
DIM = "#1f4e9c"  # dimension lines and values
REF = "#2e7d32"  # reference parts that are not the case (the PCB, connectors)
HID = "#555566"  # hidden lines
HATCH = "#6b6b7b"
FONT = "Helvetica, Arial, sans-serif"
ARROW_L, ARROW_W = 2.0, 0.7  # sheet mm
EXT_GAP, EXT_OVER = 0.8, 1.2  # extension lines start clear of the feature and run past the dimension line
TXT = 2.6  # dimension text, sheet mm
LBL = 2.4  # labels
LINE = {  # width (sheet mm), dash, colour
    "outline": (0.35, None, INK),
    "thin": (0.18, None, INK),
    "hidden": (0.25, "1.6 0.8", HID),
    "centre": (0.18, "5 0.9 0.9 0.9", HID),
    "ref": (0.22, "3 0.8 0.6 0.8", REF),  # a part that is not the case, shown for reference
    "dim": (0.18, None, DIM),
}


def fmt(v: float) -> str:
    return f"{v:.2f}"


def q(key: str, value: float, num=fmt) -> str:
    """A quoted case dimension: the number tagged with the name of the row
    in the measured JSON that `--check` compares it with."""
    return f'<tspan data-dim="{key}">{num(value)}</tspan>'


def qc(name: str, num="{:g}") -> str:
    """A quoted case_dims constant that is not a feature of the case (the
    PCB, the connectors, a section plane), tagged for `--check` by name."""
    return f'<tspan data-const="{name}">{num.format(getattr(d, name))}</tspan>'


def visible(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s)


def wrap(s: str, size: float, width: float) -> list[str]:
    """Greedy word wrap for Helvetica-ish text (0.48 em average advance),
    counting only the visible characters of tagged numbers."""
    per = width / (0.48 * size)
    out, line = [], ""
    for w in re.split(r"\s+(?![^<]*>)", s.strip()):  # on whitespace outside a tag: a tagged number stays whole
        if line and len(visible(line)) + 1 + len(visible(w)) > per:
            out.append(line)
            line = "   " + w
        else:
            line = f"{line} {w}" if line else w
    return out + [line]


def model_revision() -> str:
    """`git describe` of the last commit that touched hardware/case/ (the
    STL files and the measurements the sheets are checked against), plus
    -dirty if those files are modified: the model's revision, not HEAD's,
    so regenerating the sheets on a later commit changes nothing and CI can
    diff them.  Regenerate the sheets after committing a model change."""
    log = subprocess.run(["git", "-C", str(ROOT), "log", "-1", "--format=%H", "--", MODEL_DIR], capture_output=True, text=True)
    if log.returncode != 0 or not log.stdout.strip():
        raise SystemExit(f"git log failed for {MODEL_DIR}: {log.stderr}")
    status = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--", MODEL_DIR], capture_output=True, text=True)
    return git_describe(log.stdout.strip()) + ("-dirty" if status.stdout.strip() else "")


# ---------------------------------------------------------------------------
# a sheet in millimetres and views on it
# ---------------------------------------------------------------------------
class Sheet:
    """Content is placed in sheet millimetres from the top-left; the height
    is set when the frame and title block are drawn under the content."""

    def __init__(self, w: float):
        self.w, self.h = w, 0.0
        self.items: list[str] = []
        self.defs: list[str] = []

    def add(self, s: str) -> None:
        self.items.append(s)

    def text(self, x, y, s, size=TXT, anchor="middle", angle=0.0, weight="normal", fill=INK, halo=False, free=False):
        """`free` marks prose that may carry untagged numbers (the tooling
        notes' recommendations); everything else is scanned by --check."""
        t = f' transform="rotate({angle:g} {x:.2f} {y:.2f})"' if angle else ""
        h = f' stroke="#ffffff" stroke-width="{0.28 * size:.2f}" paint-order="stroke" stroke-linejoin="round"' if halo else ""
        c = ' class="free"' if free else ""
        self.add(f'<text{c} x="{x:.2f}" y="{y:.2f}" font-size="{size:.2f}" font-family="{FONT}" font-weight="{weight}" fill="{fill}" text-anchor="{anchor}" dy="0.35em"{t}{h}>{s}</text>')

    def line(self, x0, y0, x1, y1, stroke=INK, width=0.35, dash=None, cap="butt"):
        da = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(f'<line x1="{x0:.2f}" y1="{y0:.2f}" x2="{x1:.2f}" y2="{y1:.2f}" stroke="{stroke}" stroke-width="{width:.2f}" stroke-linecap="{cap}"{da}/>')

    def rect(self, x0, y0, x1, y1, stroke=INK, width=0.35, fill="none", dash=None, rx=0.0):
        xa, xb = sorted((x0, x1))
        ya, yb = sorted((y0, y1))
        da = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(f'<rect x="{xa:.2f}" y="{ya:.2f}" width="{xb - xa:.2f}" height="{yb - ya:.2f}" rx="{rx:.2f}" fill="{fill}" stroke="{stroke}" stroke-width="{width:.2f}"{da}/>')

    def arrow(self, x, y, ang, fill=DIM):
        """Filled arrowhead with its tip at (x, y), pointing along `ang` (radians)."""
        c, s = math.cos(ang), math.sin(ang)
        bx, by = x - ARROW_L * c, y - ARROW_L * s
        px, py = -s * ARROW_W / 2, c * ARROW_W / 2
        self.add(f'<polygon points="{x:.2f},{y:.2f} {bx + px:.2f},{by + py:.2f} {bx - px:.2f},{by - py:.2f}" fill="{fill}"/>')

    def caption(self, x, y, s, size=3.4):
        self.text(x, y, s, size=size, anchor="start", weight="bold")

    def note(self, x, y, s, size=2.1, free=False):
        self.text(x, y, s, size=size, anchor="start", free=free)

    def scale_bar(self, x, y, scale: float, label: str) -> None:
        """A SCALE_BAR sheet mm bar, alternating black and white in five steps, labelled with the part length it spans at `scale`."""
        n = 5
        step = SCALE_BAR / n
        for i in range(n):
            self.rect(x + i * step, y, x + (i + 1) * step, y + 1.2, width=0.25, fill=INK if i % 2 == 0 else "#ffffff")
        self.text(x, y + 3.2, "0", size=1.8, anchor="middle")
        self.text(x + n * step, y + 3.2, f"{SCALE_BAR / scale:g} mm", size=1.8, anchor="middle")
        self.text(x + n * step + 5.0, y + 0.6, label, size=1.8, anchor="start")

    def frame_and_title(self, part: str, title: str, scales: list[tuple[float, str]], sheet_no: int, notes: list[str], files: list[str], y_content: float) -> None:
        """Border, the title block bottom-right and the notes bottom-left,
        under the content that ends at sheet y `y_content`; sets the height."""
        tw, nsize, nlead = 82.0, 1.9, 2.7
        nx0, x0 = 1.5, self.w - 1.5 - tw
        lines = []
        for i, s in enumerate(notes):
            lines += wrap(f"{i + 1}. {s}", nsize, x0 - nx0 - 4.0)
        small = [
            "Datums: A the outside bottom face, B the USB-C wall's outer face, C the J4-end outer face. Numbers are in the PCB's frame:",
            f"x right, y down from its top-left corner, z up from its top face; A is z = {q('out_z0', d.OUT_Z0)}, B is x = {q('out_x0', d.OUT_X0)}, C is y = {q('out_y0', d.OUT_Y0)}.",
            "Views are independent, each captioned with its viewing direction; they are not arranged in projection.",
            f"Tolerance: ±{qc('TOL_LINEAR')} linear; ±{qc('TOL_SNAP')} on snap and peg features; heights ±{qc('TOL_Z')} (half a {qc('LAYER_H')} mm layer).",
            f"Print orientation as supplied (open side up). The Ø{q('bore_d_1', d.BOSS_BORE_D)} boss bore is a minimum limit. No draft is modelled.",
            "Material: unspecified (modelled for FDM PLA or PETG). Files: " + ", ".join(files),
            "Drawn by scripts/draw_case.py from scripts/case_dims.py; --check reads every number back against the measured solids.",
        ]
        title_lines = wrap(title, 1.9, tw - 4.0)
        small_lines = [ln for s in small for ln in wrap(s, 1.65, tw - 4.0)]
        title_h = 11.0 + 2.4 * len(title_lines) + 2.6 * len(small_lines) + 9.5
        block_h = max(title_h, 6.4 + len(lines) * nlead + 1.5)
        y0 = y_content + 4.0
        self.h = y0 + block_h + 1.5
        self.rect(1.5, 1.5, self.w - 1.5, self.h - 1.5, width=0.5)
        self.rect(x0, y0, self.w - 1.5, self.h - 1.5, width=0.5)
        y1 = y0 + 6.5 + 2.4 * len(title_lines) + 1.4  # under the title lines
        self.line(x0, y0 + 6.5, self.w - 1.5, y0 + 6.5, width=0.3)
        self.line(x0, y1, self.w - 1.5, y1, width=0.3)
        self.line(x0, y1 + 4.0, self.w - 1.5, y1 + 4.0, width=0.3)
        self.text(x0 + 2, y0 + 3.4, f"{PART} - {part}", size=2.9, anchor="start", weight="bold")
        for i, ln in enumerate(title_lines):
            self.text(x0 + 2, y0 + 8.8 + i * 2.4, ln, size=1.9, anchor="start")
        self.text(x0 + 2, y1 + 2.0, f"Scale {' and '.join(s for _, s in scales)}  |  Units mm  |  Sheet {sheet_no} of {SHEETS_N}  |  Rev {REV}", size=2.0, anchor="start", free=True)
        for i, ln in enumerate(small_lines):
            self.text(x0 + 2, y1 + 6.4 + i * 2.6, ln, size=1.65, anchor="start")
        ys = y1 + 6.4 + len(small_lines) * 2.6 + 0.4
        for i, (k, label) in enumerate(scales):
            self.scale_bar(x0 + 2 + i * 38.0, ys, k, f"at {label}")
        self.rect(nx0, y0, x0, self.h - 1.5, width=0.5)
        self.text(nx0 + 2, y0 + 3.4, "NOTES for an injection-moulded or machined version (tooling notes)", size=2.3, anchor="start", weight="bold")
        for i, s in enumerate(lines):
            self.text(nx0 + 2, y0 + 7.4 + i * nlead, s, size=nsize, anchor="start", free=True)

    def write(self, path: pathlib.Path) -> None:
        defs = "<defs>\n" + "\n".join(self.defs) + "\n</defs>\n" if self.defs else ""
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w:g}mm" height="{self.h:g}mm" viewBox="0 0 {self.w:g} {self.h:g}">\n'
            f'<rect width="{self.w:g}" height="{self.h:g}" fill="#ffffff"/>\n' + defs + "\n".join(self.items) + "\n</svg>\n"
        )
        xml.dom.minidom.parseString(svg)  # refuse to write markup a browser would not render
        path.write_text(svg, encoding="utf-8")
        print(f"wrote {path.relative_to(ROOT)} ({len(svg) // 1024} kB)")


class View:
    """Model (u, v) in mm -> sheet mm: (ox + su*scale*u, oy + sv*scale*v).
    Strokes and text sizes are in sheet mm whatever the scale."""

    def __init__(self, sh: Sheet, ox: float, oy: float, scale: float, flip_u: bool = False, flip_v: bool = False):
        self.sh, self.ox, self.oy, self.k = sh, ox, oy, scale
        self.su, self.sv = (-1 if flip_u else 1), (-1 if flip_v else 1)

    def X(self, u: float) -> float:
        return self.ox + self.su * self.k * u

    def Y(self, v: float) -> float:
        return self.oy + self.sv * self.k * v

    def P(self, u: float, v: float) -> tuple[float, float]:
        return self.X(u), self.Y(v)

    # --- geometry (model coordinates) ---
    def line(self, u0, v0, u1, v1, kind="outline", stroke=None):
        w, dash, col = LINE[kind]
        self.sh.line(*self.P(u0, v0), *self.P(u1, v1), stroke=stroke or col, width=w, dash=dash)

    def rect(self, u0, v0, u1, v1, kind="outline", fill="none", rx=0.0, stroke=None):
        w, dash, col = LINE[kind]
        self.sh.rect(*self.P(u0, v0), *self.P(u1, v1), stroke=stroke or col, width=w, fill=fill, dash=dash, rx=rx * self.k)

    def circle(self, u, v, r, kind="outline", fill="none", stroke=None):
        w, dash, col = LINE[kind]
        x, y = self.P(u, v)
        da = f' stroke-dasharray="{dash}"' if dash else ""
        self.sh.add(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{r * self.k:.2f}" fill="{fill}" stroke="{stroke or col}" stroke-width="{w:.2f}"{da}/>')

    def poly(self, pts, kind="outline", fill="none", close=True, stroke=None):
        w, dash, col = LINE[kind]
        s = " ".join(f"{self.X(u):.2f},{self.Y(v):.2f}" for u, v in pts)
        da = f' stroke-dasharray="{dash}"' if dash else ""
        tag = "polygon" if close else "polyline"
        self.sh.add(f'<{tag} points="{s}" fill="{fill}" stroke="{stroke or col}" stroke-width="{w:.2f}" stroke-linejoin="round"{da}/>')

    def arc_pts(self, cu, cv, r, a0, a1, n=24):
        """Points on a circle, angles in degrees in the model frame (0 = +u, 90 = +v)."""
        return [(cu + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)), cv + r * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n + 1)]

    def hatch(self, pts, angle=45.0, spacing=1.1, colour=HATCH):
        """Section hatching: parallel lines clipped to the polygon.  The lines
        are laid out on the sheet, so adjoining polygons of one part hatch
        seamlessly; use another angle for the mating part."""
        sp = [self.P(u, v) for u, v in pts]
        cid = f"c{len(self.sh.defs)}"
        self.sh.defs.append(f'<clipPath id="{cid}"><polygon points="{" ".join(f"{x:.2f},{y:.2f}" for x, y in sp)}"/></clipPath>')
        xs, ys = [p[0] for p in sp], [p[1] for p in sp]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        diag = math.hypot(x1 - x0, y1 - y0) + 2
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        n0 = -(cx * -s + cy * c)  # phase the lines to the sheet origin so neighbouring polygons line up
        k0 = math.floor((n0 - diag) / spacing)
        lines = []
        for k in range(k0, k0 + int(2 * diag / spacing) + 2):
            off = k * spacing - n0
            px, py = cx - s * off, cy + c * off
            lines.append(f'<line x1="{px - c * diag:.2f}" y1="{py - s * diag:.2f}" x2="{px + c * diag:.2f}" y2="{py + s * diag:.2f}"/>')
        self.sh.add(f'<g clip-path="url(#{cid})" stroke="{colour}" stroke-width="0.12">' + "".join(lines) + "</g>")

    def section(self, pts, angle=45.0, kind="outline", colour=HATCH, spacing=1.1):
        """Cut material: hatched and outlined."""
        self.hatch(pts, angle, spacing=spacing, colour=colour)
        self.poly(pts, kind)

    def break_line(self, u0, v0, u1, v1, amp=0.8):
        """A conventional break: erases the edge between the two model points and draws a zigzag over it."""
        x0, y0 = self.P(u0, v0)
        x1, y1 = self.P(u1, v1)
        self.sh.line(x0, y0, x1, y1, stroke="#ffffff", width=0.9)
        ang = math.atan2(y1 - y0, x1 - x0)
        nx, ny = -math.sin(ang) * amp, math.cos(ang) * amp
        n = max(4, int(math.hypot(x1 - x0, y1 - y0) / 2.5))
        pts = []
        for i in range(n + 1):
            t = i / n
            z = (0 if i in (0, n) else (1 if i % 2 else -1))
            pts.append(f"{x0 + (x1 - x0) * t + nx * z:.2f},{y0 + (y1 - y0) * t + ny * z:.2f}")
        self.sh.add(f'<polyline points="{" ".join(pts)}" fill="none" stroke="{INK}" stroke-width="0.2"/>')

    def centre_mark(self, u, v, r, over=1.5):
        w, dash, col = LINE["centre"]
        x, y = self.P(u, v)
        e = r * self.k + over
        self.sh.line(x - e, y, x + e, y, stroke=col, width=w, dash=dash)
        self.sh.line(x, y - e, x, y + e, stroke=col, width=w, dash=dash)

    def centre_line(self, u0, v0, u1, v1):
        self.line(u0, v0, u1, v1, "centre")

    # --- text and dimensions (positions in model mm, offsets in sheet mm) ---
    def label(self, u, v, s, dx=0.0, dy=0.0, size=LBL, anchor="middle", angle=0.0, fill=INK, halo=True, weight="normal"):
        x, y = self.P(u, v)
        self.sh.text(x + dx, y + dy, s, size=size, anchor=anchor, angle=angle, fill=fill, halo=halo, weight=weight)

    def dim(self, u0, v0, u1, v1, axis, pos, key=None, label="", prefix="", text=None, at=None, nudge=0.0, fill=DIM, num=fmt):
        """Linear dimension between model points (u0, v0) and (u1, v1),
        measured along `axis` ('u' or 'v'), with the dimension line at model
        coordinate `pos` on the other axis.  The value is tagged with `key`
        (a row of the measured JSON) unless `text` is given whole.  `at`
        places the value: None picks inside if it fits, else beyond the
        second point; 'in', 'p0', 'p1' force it.  `nudge` shifts the value
        along the line (sheet mm)."""
        p0, p1 = self.P(u0, v0), self.P(u1, v1)
        value = abs((u1 - u0) if axis == "u" else (v1 - v0))
        if text is None:
            text = prefix + q(key, value, num) + (f" {label}" if label else "")
        tw = 0.52 * TXT * len(visible(text)) + 1.0
        horiz = axis == "u"
        # a: along the dimension line, c: across it (sheet coordinates)
        along = (lambda p: p[0]) if horiz else (lambda p: p[1])
        across = (lambda p: p[1]) if horiz else (lambda p: p[0])
        xy = (lambda a, c: (a, c)) if horiz else (lambda a, c: (c, a))
        cl = self.Y(pos) if horiz else self.X(pos)
        for p in (p0, p1):  # extension lines
            sgn = 1 if cl > across(p) else -1
            self.sh.line(*xy(along(p), across(p) + sgn * EXT_GAP), *xy(along(p), cl + sgn * EXT_OVER), stroke=fill, width=0.18)
        lo, hi = sorted((along(p0), along(p1)))
        inside = at == "in" or (at is None and hi - lo >= tw + 2 * ARROW_L + 1.0)
        self.sh.line(*xy(lo, cl), *xy(hi, cl), stroke=fill, width=0.18)
        fwd = 0.0 if horiz else math.pi / 2  # the direction of increasing `along`
        angle, tx = (0.0, cl - 1.2) if horiz else (-90.0, cl - 1.2)
        if inside:
            self.sh.arrow(*xy(lo, cl), fwd + math.pi, fill)
            self.sh.arrow(*xy(hi, cl), fwd, fill)
            self.sh.text(*xy((lo + hi) / 2 + nudge, tx), text, size=TXT, angle=angle, fill=fill, halo=True)
            return
        self.sh.arrow(*xy(lo, cl), fwd, fill)
        self.sh.arrow(*xy(hi, cl), fwd + math.pi, fill)
        self.sh.line(*xy(lo - ARROW_L - 2.5, cl), *xy(lo, cl), stroke=fill, width=0.18)
        self.sh.line(*xy(hi, cl), *xy(hi + ARROW_L + 2.5, cl), stroke=fill, width=0.18)
        chosen, other = (p0, p1) if at == "p0" else (p1, p0)
        hi_side = along(chosen) > along(other) or (along(chosen) == along(other) and at != "p0")
        a = (hi + ARROW_L + 1.0 if hi_side else lo - ARROW_L - 1.0) + nudge
        anchor = ("start" if hi_side else "end") if horiz else ("end" if hi_side else "start")
        self.sh.text(*xy(a, tx), text, size=TXT, angle=angle, anchor=anchor, fill=fill, halo=True)

    def leader(self, u, v, s, dx, dy, fill=DIM, size=TXT, arrow=True, dot=False):
        """Arrow at model (u, v), a bent leader to a horizontal shoulder and
        the text (a string, or a list of lines) after it."""
        x, y = self.P(u, v)
        ex, ey = x + dx, y + dy
        self.sh.line(x, y, ex, ey, stroke=fill, width=0.18)
        if arrow:
            self.sh.arrow(x, y, math.atan2(y - ey, x - ex), fill)
        if dot:
            self.sh.add(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="0.5" fill="{fill}"/>')
        sh = 3.0 if dx >= 0 else -3.0
        self.sh.line(ex, ey, ex + sh, ey, stroke=fill, width=0.18)
        for i, line in enumerate([s] if isinstance(s, str) else s):
            self.sh.text(ex + sh + (0.8 if dx >= 0 else -0.8), ey + i * (size + 0.5), line, size=size, anchor="start" if dx >= 0 else "end", fill=fill, halo=True)

    def cutting_plane(self, u0, v0, u1, v1, letter, arrow):
        """Section mark between model points p0 and p1 (its outer ends):
        thick ends with arrows pointing the sheet direction `arrow` (the
        viewing direction) and the letter beyond each end.  The caller draws
        the chain line where it wants it (sheet 1 draws short stubs inside
        the outline, leaving the interior clear for leaders)."""
        x0, y0 = self.P(u0, v0)
        x1, y1 = self.P(u1, v1)
        ang = math.atan2(y1 - y0, x1 - x0)
        ca, sa = math.cos(ang), math.sin(ang)
        ax, ay = arrow
        for x, y, back in ((x0, y0, 1), (x1, y1, -1)):
            self.sh.line(x, y, x + back * 4 * ca, y + back * 4 * sa, stroke=INK, width=0.8)
            self.sh.line(x, y, x + ax * 4, y + ay * 4, stroke=INK, width=0.25)
            self.sh.arrow(x + ax * 4, y + ay * 4, math.atan2(ay, ax), INK)
            self.sh.text(x - back * 3.2 * ca, y - back * 3.2 * sa, letter, size=3.2, weight="bold")

    def datum(self, u, v, letter, direction):
        """A datum flag on the face through model (u, v): a filled triangle
        on the face, a stem and a boxed letter, pointing `direction`
        ('l', 'r', 'u', 'd' on the sheet) away from the part."""
        x, y = self.P(u, v)
        dx, dy = {"l": (-1, 0), "r": (1, 0), "u": (0, -1), "d": (0, 1)}[direction]
        px, py = -dy, dx  # along the face
        tri = [(x, y), (x + dx * 1.4 + px * 1.0, y + dy * 1.4 + py * 1.0), (x + dx * 1.4 - px * 1.0, y + dy * 1.4 - py * 1.0)]
        self.sh.add('<polygon points="' + " ".join(f"{a:.2f},{b:.2f}" for a, b in tri) + f'" fill="{INK}"/>')
        self.sh.line(x + dx * 1.4, y + dy * 1.4, x + dx * 3.4, y + dy * 3.4, stroke=INK, width=0.25)
        bx, by = x + dx * 5.2, y + dy * 5.2
        self.sh.rect(bx - 1.8, by - 1.8, bx + 1.8, by + 1.8, width=0.3, fill="#ffffff")
        self.sh.text(bx, by, letter, size=2.6, weight="bold")


# ---------------------------------------------------------------------------
# what every sheet says
# ---------------------------------------------------------------------------
SCALE_2 = (2.0, "2:1")
SCALE_5 = (5.0, "5:1")
SCALE_10 = (10.0, "10:1")
TOOLING_NOTES = [
    "No draft is modelled: add draft on every face parallel to the pull (walls, standoffs, bosses, pegs).",
    f"Internal corners are sharp (only the vertical outside corners are R{q('corner_r', d.CORNER_R)}) and no lead-in chamfers are modelled on the lip, the rebate, the peg tips' holes or the window: add both.",
    f"Walls {q('wall', d.WALL)}, plates {q('floor', d.FLOOR)} (antenna wall {q('front_wall', d.ANT_WALL_T)}); the Ø{q('standoff_d_H1', d.STANDOFF_D)} standoffs and Ø{q('boss_d_1', d.BOSS_D)} bosses on {q('ceiling', d.TOP_T)} plates will sink: core them or accept it.",
    f"The rebate ({q('rebate', d.REBATE)} deep, {q('rebate_h', d.SKIRT_H)} tall inside the skirt) is a thin blade in a mould core, and only {q('skirt_t', d.SKIRT_T)} of skirt is left outside it, {q('skirt_behind_groove', d.SKIRT_T - d.GROOVE_R)} behind the groove.",
    f"The tab bumps and the skirt grooves are undercuts to a z pull: the cantilever tabs need side actions or lifters, or a redesign (a tab that pulls straight, or a living hinge); a {q('bump_past_skirt', d.BUMP_PROUD)} bump-off is not enough.",
    f"The bump's {q('bump_past_skirt', d.BUMP_PROUD)} engagement is within FDM tolerance (±{qc('TOL_SNAP')}), so retention varies from print to print: size the engagement for the process.",
    f"The Ø{q('peg_d', d.PEG_D)} pegs rely on FDM printing oversize to grip the Ø{qc('HOLE_D', '{:.2f}')} holes: size a true interference, or use inserts and screws.",
    f"Material is unspecified. In aluminium the {q('lip_t', d.LIP_T)} tabs cannot flex: use M2 screws through the bosses into tapped standoffs, and radius every internal corner.",
]
NOTES_ELSEWHERE = "Tooling notes 1-8 are on sheet 1; the ones that bear on this sheet:"


def bottom_plan() -> None:
    sh = Sheet(210)
    k = 2.0
    v = View(sh, 75.0, 70.0, k)
    sh.caption(4, 8, "Sheet 1: BOTTOM HALF, plan from above (the open side toward the viewer), 2:1")
    sh.note(4, 13.5, "x right, y down: the USB-C wall (datum B) on the left, the J4 end (datum C) at the top, the antenna wall at the bottom, the plain wall on the right.")
    sh.note(4, 17.5, "The PCB (green) is reference only. A-A (sheet 3) and B-B (sheet 6) are viewed from -x, C-C and D-D (sheet 5) from +y. The cut-outs on the seam are seen from above.")
    # outline, cavity
    v.rect(d.OUT_X0, d.OUT_Y0, d.OUT_X1, d.OUT_Y1, rx=d.CORNER_R)
    v.rect(d.CAV_X0, d.CAV_Y0, d.CAV_X1, d.CAV_Y1)
    # the lip's outer face, gapped in the antenna wall and across the USB-C plug recess, and its end faces
    v.poly([(d.LIP_X0, d.LIP_GAP_USB_Y1), (d.LIP_X0, d.LIP_Y1), (d.LIP_GAP_X0, d.LIP_Y1)], "thin", close=False)
    v.poly([(d.LIP_GAP_X1, d.LIP_Y1), (d.LIP_X1, d.LIP_Y1), (d.LIP_X1, d.LIP_Y0), (d.LIP_X0, d.LIP_Y0), (d.LIP_X0, d.LIP_GAP_USB_Y0)], "thin", close=False)
    for y in (d.LIP_GAP_USB_Y0, d.LIP_GAP_USB_Y1):
        v.line(d.LIP_X0, y, d.CAV_X0, y, "thin")
    for x in (d.LIP_GAP_X0, d.LIP_GAP_X1):
        v.line(x, d.CAV_Y1, x, d.LIP_Y1, "thin")
    # tabs and slots; the bump shows as a strip along the tab's outer face
    for ty in d.TAB_Y:
        for x_in, x_out, side in ((d.CAV_X0, d.LIP_X0, -1), (d.CAV_X1, d.LIP_X1, 1)):
            for s0, s1 in d.slots(ty):
                v.rect(x_in, s0, x_out, s1, "thin")
            v.rect(x_out, ty - d.TAB_W / 2, x_out + side * d.BUMP_R, ty + d.TAB_W / 2, "thin")
    # the USB-C window and the plug recess, cut down through the seam: the recess floor's edge, the recess and window end faces
    v.line(d.USB_RECESS_X, d.LIP_GAP_USB_Y0, d.USB_RECESS_X, d.LIP_GAP_USB_Y1)
    for y in (d.LIP_GAP_USB_Y0, d.LIP_GAP_USB_Y1):
        v.line(d.OUT_X0, y, d.USB_RECESS_X, y)
    for y in (d.USB_WIN_Y - d.USB_WIN_W / 2, d.USB_WIN_Y + d.USB_WIN_W / 2):
        v.line(d.USB_RECESS_X, y, d.CAV_X0, y)
    v.centre_line(d.OUT_X0 - 2.0, d.USB_WIN_Y, d.CAV_X0 + 2.0, d.USB_WIN_Y)
    # the antenna wall: the E07 pocket (deeper than the half-hole) and the half-hole beyond it
    hx0, hx1 = d.SOCKET_MID_X - d.ANT_HOLE_D / 2, d.SOCKET_MID_X + d.ANT_HOLE_D / 2
    px0, px1, py1 = d.SOCKET_MID_X - d.E07_POCKET / 2, d.SOCKET_MID_X + d.E07_POCKET / 2, d.CAV_Y1 + d.E07_POCKET_DEPTH
    v.poly([(px0, d.CAV_Y1), (px0, py1), (px1, py1), (px1, d.CAV_Y1)], close=False)
    v.line(hx0, py1, hx0, d.OUT_Y1)
    v.line(hx1, py1, hx1, d.OUT_Y1)
    v.centre_line(d.SOCKET_MID_X, d.CAV_Y1 - 3.0, d.SOCKET_MID_X, d.OUT_Y1 + 2.0)
    # standoffs and pegs
    for hx, hy in d.HOLES:
        v.circle(hx, hy, d.STANDOFF_D / 2)
        v.circle(hx, hy, d.PEG_D / 2)
        v.circle(hx, hy, d.PEG_D / 2 - d.PEG_CHAMFER, "thin")
        v.centre_mark(hx, hy, d.STANDOFF_D / 2, over=2.0)
    v.label(d.FLUSH_PEG[0] + 2.6, d.FLUSH_PEG[1] + 3.4, "H3: peg flush with the PCB top", size=1.9, anchor="start")
    # the PCB for reference
    v.rect(0, 0, d.W, d.H, "ref")
    for hx, hy in d.HOLES:
        v.circle(hx, hy, d.HOLE_D / 2, "ref")
    v.label(d.W / 2, 17.0, f"PCB {qc('W')} x {qc('H')}, holes Ø{qc('HOLE_D', '{:.2f}')} (reference)", fill=REF, size=2.0)
    v.leader(0, 0, ["PCB origin (0, 0):", f"{q('pcb_edge_from_usb_face', 0 - d.OUT_X0)} from B, {q('pcb_edge_from_back_face', 0 - d.OUT_Y0)} from C"], 6, 10, fill=REF, size=2.0)
    # section marks: A-A and B-B viewed from -x (arrows +x), C-C and D-D from +y (arrows -y); chain-line stubs inside the outline only
    for x, letter in ((d.SOCKET_MID_X, "A"), (d.HOLE_IN, "B")):
        v.cutting_plane(x, d.OUT_Y0 - 16.0, x, d.OUT_Y1 + 16.0, letter, (1, 0))
        v.line(x, d.OUT_Y0, x, d.OUT_Y0 + 6.0, "centre")
        v.line(x, d.OUT_Y1 - 6.0, x, d.OUT_Y1, "centre")
    for y, letter in ((d.SECTION_CC_Y, "C"), (d.SECTION_DD_Y, "D")):
        v.cutting_plane(d.OUT_X0 - 25.0, y, d.OUT_X1 + 16.0, y, letter, (0, -1))
        v.line(d.OUT_X0, y, d.OUT_X0 + 6.0, y, "centre")
        v.line(d.OUT_X1 - 6.0, y, d.OUT_X1, y, "centre")
    # --- across the top, from datum B ---
    t1, t2, t3 = d.OUT_Y0 - 4.5, d.OUT_Y0 - 9.0, d.OUT_Y0 - 13.5
    v.dim(d.OUT_X0, d.OUT_Y0, d.OUT_X1, d.OUT_Y0, "u", t3, key="out_x")
    v.dim(d.CAV_X0, d.CAV_Y0, d.CAV_X1, d.CAV_Y0, "u", t2, key="cav_x", label="cavity")
    v.dim(d.OUT_X0, d.OUT_Y0, d.CAV_X0, d.CAV_Y0, "u", t1, key="wall", label="wall", at="p0")
    v.dim(d.OUT_X0, d.OUT_Y0, d.HOLE_IN, d.HOLE_IN, "u", t1, key="hole_H1_from_usb_face", at="in")
    v.dim(d.HOLE_IN, d.HOLE_IN, d.W - d.HOLE_IN, d.HOLE_IN, "u", t1, key="hole_pitch_x")
    v.dim(d.W - d.HOLE_IN, d.HOLE_IN, d.OUT_X1, d.OUT_Y0, "u", t1, key="hole_H2_from_plain_face", at="p1")
    v.datum(d.OUT_X0, 24.0, "B", "l")
    # --- down the left, from datum C: walls, the window and recess, the cavity ---
    l1, l2, l3, l4, l5 = (d.OUT_X0 - 4.5 * i for i in range(1, 6))
    v.dim(d.OUT_X0, d.OUT_Y0, d.OUT_X0, d.OUT_Y1, "v", l5, key="out_y")
    v.dim(d.CAV_X0, d.CAV_Y0, d.CAV_X0, d.CAV_Y1, "v", l4, key="cav_y", label="cavity")
    v.dim(d.OUT_X0, d.OUT_Y0, d.OUT_X0, d.USB_WIN_Y, "v", l3, key="lip_gap_usb_from_back_face", label="window and lip gap centre")
    v.dim(d.OUT_X0, d.LIP_GAP_USB_Y0, d.OUT_X0, d.LIP_GAP_USB_Y1, "v", l2, key="lip_gap_usb_w", label="recess, no lip")
    v.dim(d.OUT_X0, d.OUT_Y0, d.CAV_X0, d.CAV_Y0, "v", l1, key="back_wall", label="wall", at="p1")
    v.dim(d.USB_RECESS_X, d.USB_WIN_Y - d.USB_WIN_W / 2, d.USB_RECESS_X, d.USB_WIN_Y + d.USB_WIN_W / 2, "v", l1, key="window_w", label="window", at="in")
    v.dim(d.CAV_X0, d.CAV_Y1, d.OUT_X0, d.OUT_Y1, "v", l1, key="front_wall", label="antenna wall", at="p0")
    v.datum(l5 - 1.0, d.OUT_Y0, "C", "l")
    # --- down the right: the tabs and the holes, from datum C ---
    r1, r2, r3 = (d.OUT_X1 + 4.5 * i for i in range(1, 4))
    v.dim(d.OUT_X1, d.OUT_Y0, d.OUT_X1, d.TAB_Y[0], "v", r1, key="tab_r1_from_back_face", label="tab centre")
    v.dim(d.OUT_X1, d.TAB_Y[0], d.OUT_X1, d.TAB_Y[1], "v", r1, key="tab_pitch_r")
    v.dim(d.OUT_X1, d.OUT_Y0, d.W - d.HOLE_IN, d.HOLE_IN, "v", r2, key="hole_H1_from_back_face", at="p0")
    v.dim(d.W - d.HOLE_IN, d.HOLE_IN, d.W - d.HOLE_IN, d.H - d.HOLE_IN, "v", r2, key="hole_pitch_y")
    v.dim(d.W - d.HOLE_IN, d.H - d.HOLE_IN, d.OUT_X1, d.OUT_Y1, "v", r2, key="hole_H3_from_front_face")
    ty = d.TAB_Y[1]
    s = d.slots(ty)
    v.dim(d.LIP_X1, ty - d.TAB_W / 2, d.LIP_X1, ty + d.TAB_W / 2, "v", r3, key="tab_w_r2", label="tab", at="in")
    v.dim(d.LIP_X1, s[1][0], d.LIP_X1, s[1][1], "v", r3, key="slot_after_r1", label="slot", at="p1")
    # --- along the bottom: the hole, the lip gap and the antenna axis from datum B ---
    b0, b1, b2 = d.OUT_Y1 + 4.5, d.OUT_Y1 + 9.0, d.OUT_Y1 + 13.5
    v.dim(hx0, d.OUT_Y1, hx1, d.OUT_Y1, "u", b0, key="hole_d_z", label="hole", prefix="Ø", at="in")
    v.dim(d.LIP_GAP_X0, d.LIP_Y1, d.LIP_GAP_X1, d.LIP_Y1, "u", b1, key="lip_gap_w", label="lip gap", at="in")
    v.dim(d.OUT_X0, d.OUT_Y1, d.SOCKET_MID_X, d.OUT_Y1, "u", b2, key="hole_from_usb_face", label="antenna axis")
    v.dim(d.SOCKET_MID_X, d.OUT_Y1, d.OUT_X1, d.OUT_Y1, "u", b2, key="hole_from_plain_face")
    # --- leaders, inside the cavity where the interior is clear ---
    v.leader(d.OUT_X1 - 0.6, d.OUT_Y1 - 0.6, f"R{q('corner_r', d.CORNER_R)} (4 corners)", 8, 6)
    v.leader(d.W - d.HOLE_IN - 1.4, d.HOLE_IN + 1.4, [f"standoff Ø{q('standoff_d_H2', d.STANDOFF_D)}, {q('standoff_h', d.STANDOFF_Z1 - d.STANDOFF_Z0)} tall,", f"peg Ø{q('peg_d', d.PEG_D)} (4 places, sheet 6)"], -6, 14, size=2.0)
    v.leader(d.LIP_X0 + d.LIP_T / 2, 42.0, f"lip {q('lip_t', d.LIP_T)} thick, {q('lip_h', d.LIP_H)} above the rim", 8, 0, size=2.0)
    v.leader(d.LIP_X0 - d.BUMP_R, d.TAB_Y[0] - 2.5, [f"tab {q('tab_w_l1', d.TAB_W)} wide, {q('tab_h_l', d.TAB_H)} tall,", f"bump R{q('bump_r', d.BUMP_R)} at {q('bump_z_l', d.BUMP_Z)} (4 places, sheet 5)"], 8, 0, size=2.0)
    v.leader(d.USB_RECESS_X, 20.5, [f"USB-C window {q('window_w', d.USB_WIN_W)} wide (sheet 4);", f"plug recess {q('recess_w', d.USB_RECESS_W)} wide, {q('recess_depth', d.USB_RECESS_DEPTH)} deep,", f"{q('wall_under_recess', d.CAV_X0 - d.USB_RECESS_X)} of wall left; no lip across it"], 10, 6, size=2.0)
    v.leader(px0, py1, [f"E07 pocket {q('pocket_w', d.E07_POCKET)} wide,", f"{q('pocket_depth', d.E07_POCKET_DEPTH)} into the wall, floor", f"{q('pocket_floor_below_seam', d.PART_Z - d.POCKET_Z0)} below the rim"], 8, -12, size=2.0)
    sh.frame_and_title("bottom half", "Plan from above: cavity, standoffs and pegs, lip and snap tabs, the window and hole cut down to the seam", [SCALE_2], 1, TOOLING_NOTES, [STL["bottom"], STEP["bottom"]], v.Y(d.OUT_Y1 + 20.5) + 2.0)
    sh.write(OUT / "case-bottom-plan.svg")


def top_plan() -> None:
    sh = Sheet(210)
    k = 2.0
    v = View(sh, 66.0 + k * d.OUT_X1, 80.0, k, flip_u=True)  # x mirrored: the part turned over about its long axis
    sh.caption(4, 8, "Sheet 2: TOP HALF, plan from below (turned over about its long axis, so +x runs to the LEFT), 2:1")
    sh.note(4, 13.5, "Numbers stay in the PCB's frame. The USB-C wall (datum B) is on the RIGHT, the J4 end (datum C) at the top, the antenna wall at the bottom, the plain wall on the left.")
    sh.note(4, 17.5, "Visible from below: the skirt's edge, the rebate's ceiling, the window head, the half-hole and the notch; the grooves in the skirt's faces are hidden (dashed).")
    xs0, xs1 = d.CAV_X0 - d.REBATE, d.CAV_X1 + d.REBATE  # the skirt's inner faces
    ys0, ys1 = d.CAV_Y0 - d.REBATE, d.CAV_Y1 + d.REBATE
    # the outline (the recess ceiling's outer edge keeps it whole), the recess floor's step and the recess ends
    v.rect(d.OUT_X0, d.OUT_Y0, d.OUT_X1, d.OUT_Y1, rx=d.CORNER_R)
    v.line(d.USB_RECESS_X, d.LIP_GAP_USB_Y0, d.USB_RECESS_X, d.LIP_GAP_USB_Y1)
    for y in (d.LIP_GAP_USB_Y0, d.LIP_GAP_USB_Y1):
        v.line(d.OUT_X0, y, d.USB_RECESS_X, y)
    # the skirt's inner faces (the rebate's step), absent across the recess, and the cavity wall
    v.poly([(xs0, d.LIP_GAP_USB_Y1), (xs0, ys1), (xs1, ys1), (xs1, ys0), (xs0, ys0), (xs0, d.LIP_GAP_USB_Y0)], close=False)
    for y in (d.LIP_GAP_USB_Y0, d.LIP_GAP_USB_Y1):
        v.line(xs0, y, d.CAV_X0, y)
    v.rect(d.CAV_X0, d.CAV_Y0, d.CAV_X1, d.CAV_Y1, "thin")
    # the window head, seen through the window
    v.rect(d.USB_RECESS_X, d.USB_WIN_Y - d.USB_WIN_W / 2, d.CAV_X0, d.USB_WIN_Y + d.USB_WIN_W / 2)
    v.centre_line(d.OUT_X0 - 2.0, d.USB_WIN_Y, d.CAV_X0 + 2.0, d.USB_WIN_Y)
    # grooves in the skirt's inner faces (vertical faces: hidden)
    for ty in d.TAB_Y:
        for xf, side in ((xs0, -1), (xs1, 1)):
            v.rect(xf, ty - d.TAB_W / 2 - d.GROOVE_Y_OVER, xf + side * d.GROOVE_R, ty + d.TAB_W / 2 + d.GROOVE_Y_OVER, "hidden")
    # bosses
    for bx, by, dia, bored in d.BOSS_AT:
        v.circle(bx, by, dia / 2)
        if bored:
            v.circle(bx, by, d.BOSS_BORE_D / 2)
        v.centre_mark(bx, by, dia / 2, over=2.0)
    # the half-hole through the antenna wall, and the rebate ceiling it cuts
    hx0, hx1 = d.SOCKET_MID_X - d.ANT_HOLE_D / 2, d.SOCKET_MID_X + d.ANT_HOLE_D / 2
    v.line(hx0, d.CAV_Y1, hx0, d.OUT_Y1)
    v.line(hx1, d.CAV_Y1, hx1, d.OUT_Y1)
    v.centre_line(d.SOCKET_MID_X, d.CAV_Y1 - 3.0, d.SOCKET_MID_X, d.OUT_Y1 + 2.0)
    # pry notch through the skirt at the near end
    v.rect(d.NOTCH_X0, d.OUT_Y0, d.NOTCH_X1, ys0)
    # the J4 slot of the slotted variant, for reference
    v.rect(d.J4_SLOT_X0, d.J4_SLOT_Y0, d.J4_SLOT_X1, d.J4_SLOT_Y1, "ref")
    v.label((d.J4_SLOT_X0 + d.J4_SLOT_X1) / 2, (d.J4_SLOT_Y0 + d.J4_SLOT_Y1) / 2, "J4 slot: the slotted top only (sheet 7)", fill=REF, size=1.8)
    # the PCB for reference
    v.rect(0, 0, d.W, d.H, "ref")
    for hx, hy in d.HOLES:
        v.circle(hx, hy, d.HOLE_D / 2, "ref")
    v.label(d.W / 2, 26.0, "PCB (reference)", fill=REF, size=2.0)
    # --- across the top, from datum B (on the right) ---
    t1, t2, t3, t4, t5 = (d.OUT_Y0 - 4.5 * i for i in range(1, 6))
    v.dim(d.OUT_X0, d.OUT_Y0, d.OUT_X1, d.OUT_Y0, "u", t5, key="out_x_top")
    v.dim(d.OUT_X0, d.OUT_Y0, d.NOTCH_X, d.OUT_Y0, "u", t4, key="notch_from_usb_face", label="notch centre")
    v.dim(xs0, ys0, xs1, ys0, "u", t3, key="skirt_faces", label="between the skirt faces")
    v.dim(xs1, ys0, d.OUT_X1, d.OUT_Y0, "u", t3, key="skirt_t", label="skirt", at="p1")
    v.dim(d.OUT_X0, d.OUT_Y0, d.HOLE_IN, d.HOLE_IN, "u", t2, key="hole_H1_from_usb_face", at="in")
    v.dim(d.HOLE_IN, d.HOLE_IN, d.W - d.HOLE_IN, d.HOLE_IN, "u", t2, key="hole_pitch_x")
    v.dim(d.W - d.HOLE_IN, d.HOLE_IN, d.OUT_X1, d.OUT_Y0, "u", t2, key="hole_H2_from_plain_face", at="p1")
    v.dim(d.NOTCH_X0, d.OUT_Y0, d.NOTCH_X1, d.OUT_Y0, "u", t1, key="notch_w", label=f"pry notch, {q('notch_depth', d.NOTCH_DEPTH)} up from the seam")
    v.datum(d.OUT_X0, 24.0, "B", "r")
    # --- down the right (the USB-C wall): the window head and the recess, from datum C ---
    r1, r2, r3 = (d.OUT_X0 - 4.5 * i for i in range(1, 4))
    v.dim(d.USB_RECESS_X, d.USB_WIN_Y - d.USB_WIN_W / 2, d.USB_RECESS_X, d.USB_WIN_Y + d.USB_WIN_W / 2, "v", r1, key="window_w_top", label="window", at="in")
    v.dim(d.OUT_X0, d.LIP_GAP_USB_Y0, d.OUT_X0, d.LIP_GAP_USB_Y1, "v", r2, key="rebate_gap_usb_w", label="no rebate", at="in")
    v.dim(d.OUT_X0, d.OUT_Y0, d.OUT_X0, d.USB_WIN_Y, "v", r3, key="window_from_back_face", label="window centre")
    # --- down the left (the plain wall): grooves and bosses from datum C ---
    l1, l2, l3, l4 = (d.OUT_X1 + 4.5 * i for i in range(1, 5))
    v.dim(d.OUT_X1, d.OUT_Y0, d.OUT_X1, d.OUT_Y1, "v", l4, key="out_y_top")
    v.dim(d.OUT_X1, d.OUT_Y0, d.W - d.HOLE_IN, d.HOLE_IN, "v", l3, key="hole_H1_from_back_face", at="p0")
    v.dim(d.W - d.HOLE_IN, d.HOLE_IN, d.W - d.HOLE_IN, d.H - d.HOLE_IN, "v", l3, key="hole_pitch_y")
    v.dim(d.W - d.HOLE_IN, d.H - d.HOLE_IN, d.OUT_X1, d.OUT_Y1, "v", l3, key="hole_H3_from_front_face", label="to the antenna face")
    v.dim(d.OUT_X1, d.OUT_Y0, d.OUT_X1, d.TAB_Y[0], "v", l2, key="groove_r1_from_back_face", label="groove centre")
    v.dim(d.OUT_X1, d.TAB_Y[0], d.OUT_X1, d.TAB_Y[1], "v", l2, key="tab_pitch_r")
    gl = d.TAB_W + 2 * d.GROOVE_Y_OVER
    v.dim(xs1, d.TAB_Y[1] - gl / 2, xs1, d.TAB_Y[1] + gl / 2, "v", l1, key="groove_len_r2", label="groove", at="in")
    v.datum(l4 + 1.0, d.OUT_Y0, "C", "l")
    # --- along the bottom: the hole and the antenna axis from datum B ---
    b1, b2 = d.OUT_Y1 + 4.5, d.OUT_Y1 + 9.0
    v.dim(hx0, d.OUT_Y1, hx1, d.OUT_Y1, "u", b1, key="hole_d_z", label="hole", prefix="Ø", at="in")
    v.dim(d.OUT_X0, d.OUT_Y1, d.SOCKET_MID_X, d.OUT_Y1, "u", b2, key="hole_from_usb_face", label="antenna axis")
    v.dim(d.SOCKET_MID_X, d.OUT_Y1, d.OUT_X1, d.OUT_Y1, "u", b2, key="hole_from_plain_face")
    # --- leaders ---
    sbx, sby, sbd, _ = d.SOLID_BOSS
    v.leader(d.W - d.HOLE_IN - 1.5, d.HOLE_IN + 1.6, [f"boss Ø{q('boss_d_2', d.BOSS_D)}, bore Ø{q('bore_d_2', d.BOSS_BORE_D)} min,", f"{q('bore_depth_2', d.BOSS_BORE_DEPTH)} deep (3 places, sheet 6)"], 6, 10, size=2.0)
    v.leader(sbx - sbd / 2 * 0.7, sby + sbd / 2 * 0.7, [f"solid boss Ø{q('boss_d_3', sbd)}:", f"{q('solid_boss_from_usb_face', sbx - d.OUT_X0)} from B, {q('solid_boss_from_back_face', sby - d.OUT_Y0)} from C"], -6, 8, size=2.0)
    v.leader(d.OUT_X0 - 0.6, d.OUT_Y0 + 0.6, f"R{q('corner_r_top', d.CORNER_R)} (4 corners)", 8, -5)
    v.leader(xs1, 58.0, [f"rebate {q('rebate', d.REBATE)} deep,", f"{q('rebate_h', d.SKIRT_H)} tall (sheet 5)"], 8, 0, size=2.0)
    v.leader(xs1 + d.GROOVE_R, d.TAB_Y[1] - 3.0, [f"groove R{q('groove_depth_r', d.GROOVE_R)}, centre {q('groove_z_r', d.BUMP_Z)}", "above the seam (hidden, sheet 5)"], 8, -6, size=2.0)
    v.leader(d.CAV_X0, 12.0, [f"USB-C window: head {q('window_above_seam', d.USB_WIN_Z1 - d.PART_Z)} above", "the seam (sheet 4); no rebate", f"across the {q('recess_w', d.USB_RECESS_W)} plug recess"], -8, 8, size=2.0)
    v.leader(hx1, d.OUT_Y1 - 1.0, [f"Ø{q('hole_d_z', d.ANT_HOLE_D)} hole, half", "in this half"], 10, -9, size=2.0)
    sh.frame_and_title("top half", "Plan from below: skirt and rebate, grooves, bosses, the window head, the half-hole and the pry notch", [SCALE_2], 2, [NOTES_ELSEWHERE] + [TOOLING_NOTES[i] for i in (0, 2, 3)], [STL["top"], STEP["top"]], v.Y(d.OUT_Y1 + 9.0) + 2.0)
    sh.write(OUT / "case-top-plan.svg")


def section_antenna() -> None:
    """Section A-A: the plane x = SOCKET_MID_X, both halves closed, viewed
    from -x and laid out like the plan: y runs down the sheet, so z runs to
    the right (the floor on the left, the ceiling on the right)."""
    sh = Sheet(210)
    k = 2.0
    v = View(sh, 84.0, 80.0, k)  # u = z, v = y
    sh.caption(4, 8, f"Sheet 3: SECTION A-A on the antenna axis (x = {q('hole_x', d.SOCKET_MID_X)}), case closed, viewed from -x, 2:1")
    sh.note(4, 13.5, "Laid out like the plan: y runs down the sheet, so z runs to the RIGHT (floor on the left, ceiling on the right). Bottom half hatched 45°, top half 135°, the PCB green.")
    sh.note(4, 17.5, f"Behind the cut (x > {q('hole_x', d.SOCKET_MID_X)}): the standoffs, pegs and bosses at H2/H4, the plain wall's lip, tabs and rebate ceiling; omitted: the radio, headers and pin stubs, the grooves.")
    sh.note(4, 21.5, f"The E07's SMA jack (green, reference) is its {qc('E07_JACK_BODY')} mm square body, {qc('E07_JACK_LEN')} long, and Ø{qc('SMA_BARREL_D')} barrel, {qc('E07_BARREL_LEN')} long, through the hole.")
    reb = d.REBATE
    hz0, hz1 = d.ANT_HOLE_Z0, d.ANT_HOLE_Z1
    pk_y1 = d.CAV_Y1 + d.E07_POCKET_DEPTH
    zy = lambda pts: [(z, y) for y, z in pts]  # noqa: E731  the polygons are easier to write as (y, z)
    bottom = [
        (d.OUT_Y0, d.OUT_Z0), (d.OUT_Y1, d.OUT_Z0), (d.OUT_Y1, hz0), (pk_y1, hz0), (pk_y1, d.POCKET_Z0), (d.CAV_Y1, d.POCKET_Z0), (d.CAV_Y1, d.CAV_Z0),
        (d.CAV_Y0, d.CAV_Z0), (d.CAV_Y0, d.PART_Z + d.LIP_H), (d.LIP_Y0, d.PART_Z + d.LIP_H), (d.LIP_Y0, d.PART_Z), (d.OUT_Y0, d.PART_Z),
    ]
    v.section(zy(bottom), 45)
    top = [
        (d.OUT_Y0, d.OUT_Z1), (d.OUT_Y1, d.OUT_Z1), (d.OUT_Y1, hz1), (d.CAV_Y1 + reb, hz1), (d.CAV_Y1 + reb, d.PART_Z + d.SKIRT_H), (d.CAV_Y1, d.PART_Z + d.SKIRT_H),
        (d.CAV_Y1, d.CAV_Z1), (d.CAV_Y0, d.CAV_Z1), (d.CAV_Y0, d.PART_Z + d.SKIRT_H), (d.CAV_Y0 - reb, d.PART_Z + d.SKIRT_H), (d.CAV_Y0 - reb, d.PART_Z + d.NOTCH_DEPTH),
        (d.OUT_Y0, d.PART_Z + d.NOTCH_DEPTH),
    ]
    v.section(zy(top), 135)
    # the PCB, cut by the plane (green, hatched across)
    v.section(zy([(0, -d.BOARD_T), (d.H, -d.BOARD_T), (d.H, 0), (0, 0)]), 0, kind="ref", colour=REF, spacing=0.7)
    v.label(-d.BOARD_T / 2, d.H / 2, f"PCB {qc('BOARD_T', '{:.2f}')} (ref.)", fill=REF, size=1.9, angle=-90)
    # behind the cut: the standoffs, pegs (their tips above the PCB) and bosses at H2 and H4
    for hx, hy in (d.HOLES[1], d.HOLES[3]):
        v.rect(d.STANDOFF_Z0, hy - d.STANDOFF_D / 2, d.STANDOFF_Z1, hy + d.STANDOFF_D / 2, "thin")
        r, ch = d.PEG_D / 2, d.PEG_CHAMFER
        v.poly(zy([(hy - r, 0.0), (hy - r, d.PEG_Z1 - ch), (hy - r + ch, d.PEG_Z1), (hy + r - ch, d.PEG_Z1), (hy + r, d.PEG_Z1 - ch), (hy + r, 0.0)]), "thin", close=False)
    for bx, by, dia, bored in (d.BOSS_AT[1], d.BOSS_AT[3]):
        v.rect(d.BOSS_Z0, by - dia / 2, d.BOSS_Z1, by + dia / 2, "thin")
        if bored:
            v.rect(d.BOSS_Z0, by - d.BOSS_BORE_D / 2, d.BOSS_Z0 + d.BOSS_BORE_DEPTH, by + d.BOSS_BORE_D / 2, "hidden")
    # behind the cut: the plain wall's lip top, its slots and tabs, and the rebate ceiling above them
    lip_top, tab_top, reb_top = d.PART_Z + d.LIP_H, d.PART_Z + d.TAB_H, d.PART_Z + d.SKIRT_H
    ya = d.CAV_Y0
    for ty in d.TAB_Y:
        (s0a, s0b), (s1a, s1b) = d.slots(ty)
        v.line(lip_top, ya, lip_top, s0a, "thin")  # plain lip up to the first slot
        v.poly(zy([(s0a, lip_top), (s0a, d.PART_Z), (s0b, d.PART_Z), (s0b, tab_top), (s1a, tab_top), (s1a, d.PART_Z), (s1b, d.PART_Z), (s1b, lip_top)]), "thin", close=False)
        ya = s1b
    v.line(lip_top, ya, lip_top, d.CAV_Y1, "thin")
    v.line(reb_top, d.CAV_Y0, reb_top, d.CAV_Y1, "thin")
    v.leader(tab_top, d.TAB_Y[1] + 2.0, "tab (behind)", 12, 6, fill=INK, size=1.9, arrow=False, dot=True)
    v.leader(reb_top, 41.0, "rebate ceiling (behind)", 12, -4, fill=INK, size=1.9, arrow=False, dot=True)
    # the E07's SMA jack, reference
    jy0 = d.E07_JACK_Y1 - d.E07_JACK_LEN
    v.rect(d.ANT_Z - d.E07_JACK_BODY / 2, jy0, d.ANT_Z + d.E07_JACK_BODY / 2, d.E07_JACK_Y1, "ref")
    v.rect(d.ANT_Z - d.SMA_BARREL_D / 2, d.E07_JACK_Y1, d.ANT_Z + d.SMA_BARREL_D / 2, d.E07_JACK_Y1 + d.E07_BARREL_LEN, "ref")
    v.label(d.ANT_Z, jy0 - 1.6, "E07 jack (ref.)", fill=REF, size=1.7)
    v.centre_line(d.ANT_Z, d.CAV_Y1 - 4.0, d.ANT_Z, d.OUT_Y1 + 9.0)
    v.line(d.PART_Z, d.OUT_Y0 - 2.5, d.PART_Z, d.OUT_Y0 - 0.2, "centre")
    v.label(d.PART_Z, d.OUT_Y0 - 1.5, "seam", dx=-1.2, size=1.9, anchor="end")
    # --- across the top: heights (z) from datum A ---
    t1, t2, t3, t4 = d.OUT_Y0 - 4.0, d.OUT_Y0 - 8.5, d.OUT_Y0 - 13.0, d.OUT_Y0 - 17.5
    v.dim(d.OUT_Z0, d.OUT_Y0, d.OUT_Z1, d.OUT_Y0, "u", t4, key="overall_h", label="overall height")
    v.dim(d.OUT_Z0, d.OUT_Y0, d.PART_Z, d.OUT_Y0, "u", t3, key="bottom_h", at="in")
    v.dim(d.PART_Z, d.OUT_Y0, d.OUT_Z1, d.OUT_Y0, "u", t3, key="top_h", at="in")
    v.label((d.OUT_Z0 + d.PART_Z) / 2, t3, "bottom half", dy=-4.0, size=1.9)
    v.label((d.PART_Z + d.OUT_Z1) / 2, t3, "top half", dy=-4.0, size=1.9)
    v.dim(d.OUT_Z0, d.OUT_Y0, d.CAV_Z0, d.CAV_Y0, "u", t2, key="floor", label="floor", at="p0")
    v.dim(d.CAV_Z0, d.CAV_Y0, d.PART_Z, d.CAV_Y0, "u", t2, key="floor_below_seam", at="in")
    v.dim(d.PART_Z, d.CAV_Y0, d.CAV_Z1, d.CAV_Y0, "u", t2, key="ceiling_above_seam", at="in")
    v.dim(d.CAV_Z1, d.CAV_Y0, d.OUT_Z1, d.OUT_Y0, "u", t2, key="ceiling", label="ceiling", at="p1")
    v.dim(d.PART_Z, d.LIP_Y0, d.PART_Z + d.LIP_H, d.LIP_Y0, "u", t1, key="lip_h", label="lip", at="p1")
    v.datum(d.OUT_Z0, t4 - 1.0, "A", "u")
    # --- down the left: lengths (y) from datum C ---
    c1, c2, c3, c4 = d.OUT_Z0 - 4.0, d.OUT_Z0 - 8.5, d.OUT_Z0 - 13.0, d.OUT_Z0 - 17.5
    v.dim(d.OUT_Z0, d.OUT_Y0, d.OUT_Z0, d.OUT_Y1, "v", c4, key="out_y")
    v.dim(d.OUT_Z0, d.OUT_Y0, d.CAV_Z0, d.CAV_Y0, "v", c3, key="back_wall", label="wall", at="p1")
    v.dim(d.CAV_Z0, d.CAV_Y0, d.CAV_Z0, d.CAV_Y1, "v", c3, key="cav_y", label="cavity")
    v.dim(d.CAV_Z0, d.CAV_Y1, d.OUT_Z0, d.OUT_Y1, "v", c3, key="front_wall", label="antenna wall", at="p0")
    v.dim(d.OUT_Z0, d.OUT_Y0, -d.BOARD_T, 0, "v", c2, key="pcb_edge_from_back_face", label="PCB edge", at="p1", fill=REF)
    v.dim(-d.BOARD_T, 0, -d.BOARD_T, d.H, "v", c2, text=f"{qc('H', '{:.2f}')} PCB", fill=REF)
    v.dim(d.OUT_Z0, d.OUT_Y0, d.STANDOFF_Z0, d.HOLES[1][1], "v", c1, key="hole_H1_from_back_face", at="in")
    v.dim(d.STANDOFF_Z0, d.HOLES[1][1], d.STANDOFF_Z0, d.HOLES[3][1], "v", c1, key="hole_pitch_y", label="standoff pitch")
    v.datum(c4 - 1.0, d.OUT_Y0, "C", "l")
    # --- along the bottom: the antenna hole's height ---
    b1, b2 = d.OUT_Y1 + 4.0, d.OUT_Y1 + 8.5
    v.dim(d.OUT_Z0, d.OUT_Y1, d.ANT_Z, d.OUT_Y1, "u", b2, key="hole_z_from_bottom", label="hole centre, on the seam")
    v.dim(d.OUT_Z0, d.OUT_Y1, hz0, d.OUT_Y1, "u", b1, key="below_hole", label="below the hole", at="p0")
    v.dim(hz0, d.OUT_Y1, hz1, d.OUT_Y1, "u", b1, key="hole_d_z", at="in")
    v.dim(hz1, d.OUT_Y1, d.OUT_Z1, d.OUT_Y1, "u", b1, key="above_hole", label="above the hole", at="p1")
    # --- on the right: leaders ---
    v.leader(hz1, d.OUT_Y1 - 1.0, [f"Ø{q('hole_d_z', d.ANT_HOLE_D)} hole: {q('hole_below_seam', d.ANT_Z - hz0)} below the seam", f"in the bottom half, {q('hole_above_seam', hz1 - d.ANT_Z)} above in the top"], 10, 2)
    v.leader(d.POCKET_Z0, d.CAV_Y1 + 0.3, [f"E07 pocket {q('pocket_w', d.E07_POCKET)} wide, {q('pocket_depth', d.E07_POCKET_DEPTH)} deep,", f"floor {q('pocket_floor_below_seam', d.PART_Z - d.POCKET_Z0)} below the seam (bottom half only)"], 26, -2)
    v.leader(d.BOSS_Z1 - 1.0, d.HOLES[1][1] + d.BOSS_D / 2, f"boss Ø{q('boss_d_2', d.BOSS_D)}, {q('boss_gap', d.BOSS_GAP)} above the PCB", 10, 3)
    v.leader(d.PEG_Z1, d.HOLES[1][1] + 0.5, f"peg tip {q('peg_proud', d.PEG_Z1)} above the PCB", 22, 20)
    v.leader(d.STANDOFF_Z1 - 0.5, d.HOLES[3][1] + d.STANDOFF_D / 2, [f"standoff Ø{q('standoff_d_H4', d.STANDOFF_D)}, {q('standoff_h', d.STANDOFF_Z1 - d.STANDOFF_Z0)} tall:", "floor to the PCB's underside,", "the trimmed pin stubs' room"], 30, 14)
    v.leader(d.PART_Z + d.NOTCH_DEPTH, d.CAV_Y0 - reb / 2, f"pry notch {q('notch_depth', d.NOTCH_DEPTH)} up from the seam", 22, -3)
    v.leader(d.PART_Z + d.SKIRT_H, d.CAV_Y0 - reb / 2, f"rebate {q('rebate', d.REBATE)} x {q('rebate_h', d.SKIRT_H)} (sheet 5)", 22, 3)
    v.leader(d.CAV_Z1, 20.0, f"{q('ceiling_above_pcb', d.CAV_Z1)} PCB top to ceiling", 12, 4)
    sh.frame_and_title("both halves, closed", "Section A-A on the antenna axis: floor, seam, ceiling, the standoff / peg / boss stack, the split hole and the pocket", [SCALE_2], 3, [NOTES_ELSEWHERE] + [TOOLING_NOTES[i] for i in (0, 1, 2)], [STL["bottom"], STL["top"]], v.Y(d.OUT_Y1 + 8.5) + 8.0)
    sh.write(OUT / "case-section-antenna.svg")


def end_elevations() -> None:
    sh = Sheet(210)
    k = 2.0
    # (a) the USB-C wall from outside (-x): y runs to the RIGHT, z up
    va = View(sh, 30.0 - k * d.OUT_Y0, 75.0, k, flip_v=True)
    sh.caption(4, 8, "Sheet 4: USB-C WALL from outside (viewed from -x), case closed: the J4 end on the left, the antenna end on the right, 2:1")
    sh.note(4, 13.5, "Outside faces only; hidden detail (tabs, lip, rebate, bosses) is omitted, see sheets 1, 2 and 5. The seam is drawn as an assembly edge.")
    va.rect(d.OUT_Y0, d.OUT_Z0, d.OUT_Y1, d.OUT_Z1)
    wy0, wy1 = d.USB_WIN_Y - d.USB_WIN_W / 2, d.USB_WIN_Y + d.USB_WIN_W / 2
    va.line(d.OUT_Y0, d.PART_Z, wy0, d.PART_Z, "thin")
    va.line(wy1, d.PART_Z, d.OUT_Y1, d.PART_Z, "thin")
    va.rect(wy0, d.USB_WIN_Z0, wy1, d.USB_WIN_Z1)
    va.rect(d.LIP_GAP_USB_Y0, d.USB_RECESS_Z0, d.LIP_GAP_USB_Y1, d.USB_RECESS_Z1)
    va.centre_line(d.USB_WIN_Y, d.USB_RECESS_Z0 - 3.0, d.USB_WIN_Y, d.USB_RECESS_Z1 + 3.0)
    va.label(d.OUT_Y1, d.PART_Z, "seam", dx=-2.0, dy=-1.6, size=1.9, anchor="end")
    va.label(d.OUT_Y0 + 1.0, d.OUT_Z0, "J4 end (C)", dy=3.0, size=1.9, anchor="start")
    va.label(d.OUT_Y1 - 1.0, d.OUT_Z0, "antenna end", dy=3.0, size=1.9, anchor="end")
    va.label(d.USB_WIN_Y, d.USB_WIN_Z, "window", size=1.9)
    va.label(d.USB_WIN_Y, d.USB_RECESS_Z1 - 1.0, "plug recess", size=1.9)
    va.dim(d.OUT_Y0, d.OUT_Z0, d.OUT_Y1, d.OUT_Z0, "u", d.OUT_Z0 - 6.0, key="out_y")
    va.datum(35.0, d.OUT_Z0, "A", "d")
    va.dim(wy0, d.USB_WIN_Z1, wy1, d.USB_WIN_Z1, "u", d.OUT_Z1 + 4.5, key="window_w", label="window", at="in")
    va.dim(d.LIP_GAP_USB_Y0, d.USB_RECESS_Z1, d.LIP_GAP_USB_Y1, d.USB_RECESS_Z1, "u", d.OUT_Z1 + 9.0, key="recess_w", label="recess", at="in")
    va.dim(d.OUT_Y0, d.OUT_Z1, d.USB_WIN_Y, d.USB_RECESS_Z1, "u", d.OUT_Z1 + 13.5, key="window_from_back_face", label="window and recess centre")
    r1, r2, r3 = (d.OUT_Y1 + 4.5 * i for i in range(1, 4))
    va.dim(d.OUT_Y1, d.OUT_Z0, d.OUT_Y1, d.PART_Z, "v", r1, key="bottom_h", at="in")
    va.dim(d.OUT_Y1, d.OUT_Z0, wy1, d.USB_WIN_Z0, "v", r2, key="window_sill_from_bottom", label="sill", at="p0")
    va.dim(wy1, d.USB_WIN_Z0, wy1, d.USB_WIN_Z1, "v", r2, key="window_h", at="in")
    va.dim(wy1, d.USB_WIN_Z1, d.OUT_Y1, d.OUT_Z1, "v", r2, key="wall_above_window", at="p1")
    va.dim(d.OUT_Y1, d.OUT_Z0, d.OUT_Y1, d.OUT_Z1, "v", r3, key="overall_h")
    l1 = d.OUT_Y0 - 4.5
    va.dim(d.OUT_Y0, d.OUT_Z0, d.LIP_GAP_USB_Y0, d.USB_RECESS_Z0, "v", l1, key="recess_from_bottom", at="p0")
    va.dim(d.LIP_GAP_USB_Y0, d.USB_RECESS_Z0, d.LIP_GAP_USB_Y0, d.USB_RECESS_Z1, "v", l1, key="recess_h", label="recess", at="in")
    va.datum(d.OUT_Y0, d.OUT_Z1 - 1.0, "C", "l")
    va.leader(wy0 + 1.0, d.USB_WIN_Z0 + 1.0, [f"window {q('window_w', d.USB_WIN_W)} x {q('window_h', d.USB_WIN_H)}: sill {q('window_below_seam', d.PART_Z - d.USB_WIN_Z0)} below the seam (bottom half), {q('window_sill_from_bottom', d.USB_WIN_Z0 - d.OUT_Z0)} from A;",
                                                f"head {q('window_above_seam', d.USB_WIN_Z1 - d.PART_Z)} above the seam (top half), {q('window_head_from_bottom', d.USB_WIN_Z1 - d.OUT_Z0)} from A. Plug recess {q('recess_w', d.USB_RECESS_W)} x {q('recess_h', d.USB_RECESS_H)},",
                                                f"bottom {q('recess_from_bottom', d.USB_RECESS_Z0 - d.OUT_Z0)} from A, {q('recess_depth', d.USB_RECESS_DEPTH)} deep, {q('wall_under_recess', d.CAV_X0 - d.USB_RECESS_X)} of wall left under it (sheets 1 and 2)"], 10, 40, size=2.0)
    # (b) the antenna wall from outside (+y): x runs to the RIGHT, z up
    vb = View(sh, 39.0 - k * d.OUT_X0, 166.0, k, flip_v=True)
    sh.caption(4, 122, "ANTENNA WALL from outside (viewed from +y), case closed: the USB-C wall on the left, the plain wall on the right, 2:1")
    vb.rect(d.OUT_X0, d.OUT_Z0, d.OUT_X1, d.OUT_Z1)
    hx0, hx1 = d.SOCKET_MID_X - d.ANT_HOLE_D / 2, d.SOCKET_MID_X + d.ANT_HOLE_D / 2
    vb.line(d.OUT_X0, d.PART_Z, hx0, d.PART_Z, "thin")
    vb.line(hx1, d.PART_Z, d.OUT_X1, d.PART_Z, "thin")
    vb.circle(d.SOCKET_MID_X, d.ANT_Z, d.ANT_HOLE_D / 2)
    vb.centre_mark(d.SOCKET_MID_X, d.ANT_Z, d.ANT_HOLE_D / 2, over=3.0)
    vb.label(d.OUT_X1, d.PART_Z, "seam", dx=-2.0, dy=-1.6, size=1.9, anchor="end")
    vb.label(d.OUT_X0 - 0.5, d.OUT_Z0, "USB-C wall (B)", dy=3.0, size=1.9, anchor="end")
    vb.label(d.OUT_X1 + 0.5, d.OUT_Z0, "plain wall", dy=3.0, size=1.9, anchor="start")
    vb.dim(d.OUT_X0, d.OUT_Z0, d.OUT_X1, d.OUT_Z0, "u", d.OUT_Z0 - 6.0, key="out_x")
    vb.datum(22.0, d.OUT_Z0, "A", "d")
    vb.dim(d.OUT_X0, d.OUT_Z1, d.SOCKET_MID_X, d.ANT_HOLE_Z1, "u", d.OUT_Z1 + 4.5, key="hole_from_usb_face", label="hole centre")
    vb.dim(d.SOCKET_MID_X, d.ANT_HOLE_Z1, d.OUT_X1, d.OUT_Z1, "u", d.OUT_Z1 + 4.5, key="hole_from_plain_face")
    vb.dim(d.OUT_X1, d.OUT_Z0, hx1, d.ANT_Z, "v", d.OUT_X1 + 4.5, key="hole_z_from_bottom", at="in")
    vb.dim(d.OUT_X1, d.OUT_Z0, d.OUT_X1, d.OUT_Z1, "v", d.OUT_X1 + 9.0, key="overall_h")
    xh = hx1 + 3.0
    vb.dim(d.SOCKET_MID_X, d.ANT_HOLE_Z0, d.SOCKET_MID_X, d.ANT_Z, "v", xh, key="hole_below_seam", label="below", at="p0")
    vb.dim(d.SOCKET_MID_X, d.ANT_Z, d.SOCKET_MID_X, d.ANT_HOLE_Z1, "v", xh, key="hole_above_seam", label="above", at="p1")
    vb.datum(d.OUT_X0, d.OUT_Z1 - 1.0, "B", "l")
    vb.leader(hx0 + 0.9, d.ANT_Z - 2.3, [f"Ø{q('hole_d_z', d.ANT_HOLE_D)} thru, centred on the seam ({q('hole_z_from_bottom', d.ANT_Z - d.OUT_Z0)} from A), half in each half;", f"E07 pocket {q('pocket_w', d.E07_POCKET)} sq inside the bottom half (sheet 1)"], 6, 30, size=2.0)
    sh.frame_and_title("both halves, closed", "End elevations from outside: the USB-C window with its plug recess, and the antenna hole, each split by the seam", [SCALE_2], 4, [NOTES_ELSEWHERE, TOOLING_NOTES[1]], [STL["bottom"], STL["top"]], vb.Y(d.OUT_Z0 - 6.0) + 18.0)
    sh.write(OUT / "case-end-elevations.svg")


def snap_detail() -> None:
    sh = Sheet(210)
    k = 10.0
    xo, xl, xc = d.OUT_X0, d.LIP_X0, d.CAV_X0  # the USB-C wall's outer face, the lip/tab's outer face, the cavity
    xs = d.CAV_X0 - d.REBATE  # the skirt's inner face
    bz = d.PART_Z + d.BUMP_Z
    z_lo, z_hi = d.PART_Z - 1.6, d.PART_Z + d.SKIRT_H + 1.6  # the shown range
    # (a) Section C-C through a tab, closed, 10:1, viewed from +y so x runs right: outside on the left
    v = View(sh, 50.0 - k * xo, 22.0 + k * z_hi, k, flip_v=True)
    sh.caption(4, 8, f"Sheet 5: SECTION C-C, a snap tab (y = {q('tab_y_l1', d.SECTION_CC_Y)}), USB-C wall, closed, from +y, 10:1", size=3.0)
    sh.note(4, 13.5, "x runs right: outside on the left, the cavity on the right. Bottom half hatched 45°, top half 135°; the wall continues past the breaks to the floor and the ceiling.")
    bump = v.arc_pts(xl, bz, d.BUMP_R, 90, 270)  # over the top of the bump, round its outside, to its underside
    v.section([(xo, z_lo), (xc, z_lo), (xc, d.PART_Z + d.TAB_H), (xl, d.PART_Z + d.TAB_H)] + bump + [(xl, d.PART_Z), (xo, d.PART_Z)], 45)
    groove = v.arc_pts(xs, bz, d.GROOVE_R, 90, 270)
    v.section([(xo, d.PART_Z), (xs, d.PART_Z)] + groove[::-1] + [(xs, d.PART_Z + d.SKIRT_H), (xc, d.PART_Z + d.SKIRT_H), (xc, z_hi), (xo, z_hi)], 135)
    v.break_line(xo, z_lo, xc, z_lo)
    v.break_line(xo, z_hi, xc, z_hi)
    v.line(xo, d.PART_Z, xo - 0.5, d.PART_Z, "centre")
    v.label(xo - 0.5, d.PART_Z, "seam", dx=-1.0, size=2.0, anchor="end")
    v.label(xc, d.PART_Z - 0.8, "cavity", dx=2.5, size=2.0, anchor="start")
    v.label(xo, d.PART_Z - 0.8, "outside", dx=-2.5, size=2.0, anchor="end")
    v.label(xc, d.PART_Z + d.SKIRT_H, "rebate ceiling", dx=2.5, dy=-1.8, size=1.9, anchor="start")
    # widths, at different heights so they do not collide
    v.dim(xo, z_hi, xc, z_hi, "u", z_hi + 0.3, key="wall", label="wall")
    v.dim(xs, d.PART_Z + d.SKIRT_H + 1.0, xc, d.PART_Z + d.SKIRT_H + 1.0, "u", d.PART_Z + d.SKIRT_H + 1.0, key="rebate", label="rebate", at="p1")
    v.dim(xl, d.PART_Z + 2.6, xc, d.PART_Z + 2.6, "u", d.PART_Z + 2.6, key="lip_t", label="tab", at="in")
    v.dim(xs, d.PART_Z + 1.6, xl, d.PART_Z + 1.6, "u", d.PART_Z + 1.6, key="fit", label="clearance", at="p0")
    v.dim(xo, d.PART_Z + 1.0, xs, d.PART_Z + 1.0, "u", d.PART_Z + 1.0, key="skirt_t", label="skirt", at="in")
    v.dim(xo, z_lo, xc, z_lo, "u", z_lo - 0.3, key="wall", label="wall")
    # heights on the cavity side, from the seam
    c1, c2, c3 = xc + 0.55, xc + 1.15, xc + 1.75
    v.dim(xc, d.PART_Z, xc, d.PART_Z + d.TAB_H, "v", c1, key="tab_h_l", label="tab")
    v.dim(xc, d.PART_Z, xc, d.PART_Z + d.SKIRT_H, "v", c2, key="rebate_h", label="rebate")
    v.dim(xl - d.BUMP_R, d.PART_Z, xl - d.BUMP_R, bz, "v", c3, key="bump_z_l", label="bump and groove centre")
    v.leader(xl + d.LIP_T / 2, d.PART_Z + d.TAB_H + (d.SKIRT_H - d.TAB_H) / 2, f"{q('rebate_over_tab', d.SKIRT_H - d.TAB_H)} over the tab", 8, -9)
    # the bump and groove, leaders to the outside
    v.leader(xs - d.GROOVE_R, bz, [f"groove R{q('groove_depth_l', d.GROOVE_R)} in the skirt,", "centred on its inner face"], -8, -16)
    v.dim(xs - d.GROOVE_R, bz - 1.0, xl - d.BUMP_R, bz - 1.0, "u", bz - 1.0, key="groove_bottom_clear", label="to the groove bottom", at="p0")
    v.leader(xl - d.BUMP_R, bz, [f"bump R{q('bump_r', d.BUMP_R)} across the tab,", f"stands {q('bump_past_skirt', d.BUMP_PROUD)} past the skirt face"], -8, 16)
    # (b) Section D-D through the plain lip, closed, 10:1
    vb = View(sh, 128.0 - k * xo, 22.0 + k * z_hi, k, flip_v=True)
    sh.caption(124, 8, f"SECTION D-D: the plain lip (y = {qc('SECTION_DD_Y')}), from +y, 10:1", size=3.0)
    vb.section([(xo, z_lo), (xc, z_lo), (xc, d.PART_Z + d.LIP_H), (xl, d.PART_Z + d.LIP_H), (xl, d.PART_Z), (xo, d.PART_Z)], 45)
    vb.section([(xo, d.PART_Z), (xs, d.PART_Z), (xs, d.PART_Z + d.SKIRT_H), (xc, d.PART_Z + d.SKIRT_H), (xc, z_hi), (xo, z_hi)], 135)
    vb.break_line(xo, z_lo, xc, z_lo)
    vb.break_line(xo, z_hi, xc, z_hi)
    vb.line(xo, d.PART_Z, xo - 0.5, d.PART_Z, "centre")
    vb.label(xo - 0.5, d.PART_Z, "seam", dx=-1.0, size=2.0, anchor="end")
    vb.dim(xl, d.PART_Z + d.LIP_H, xc, d.PART_Z + d.LIP_H, "u", d.PART_Z + d.LIP_H + 0.5, key="lip_t", label="lip", at="p0")
    vb.dim(xs, d.PART_Z + 0.7, xl, d.PART_Z + 0.7, "u", d.PART_Z + 0.7, key="fit", at="p1")
    vb.dim(xc, d.PART_Z, xc, d.PART_Z + d.LIP_H, "v", xc + 0.55, key="lip_h", label="lip")
    vb.dim(xc, d.PART_Z + d.LIP_H, xc, d.PART_Z + d.SKIRT_H, "v", xc + 0.55, key="rebate_over_lip", label="above the lip", at="p1")
    vb.dim(xo, z_hi, xc, z_hi, "u", z_hi + 0.3, key="wall", label="wall")
    vb.dim(xo, d.PART_Z + 2.6, xs, d.PART_Z + 2.6, "u", d.PART_Z + 2.6, key="skirt_t", label="skirt", at="in")
    vb.label(xc, d.PART_Z + 4.5, "cavity", dx=2.5, size=2.0, anchor="start")
    vb.label(xo, d.PART_Z + 4.5, "outside", dx=-2.5, size=2.0, anchor="end")
    # (c) a tab from outside (viewed from -x), 5:1: y runs to the RIGHT, z up; the bottom half only
    k3 = 5.0
    ty = d.TAB_Y[0]
    vc = View(sh, 100.0 - k3 * ty, 160.0 + k3 * d.TAB_H, k3, flip_v=True)
    sh.caption(4, 118, f"A SNAP TAB from outside (viewed from -x, the USB-C wall at y = {q('tab_y_l1', ty)}), bottom half only, 5:1")
    sh.note(4, 123.5, "y runs right (toward the antenna end). The top half is not drawn; the position of its groove is dashed for reference.")
    s = d.slots(ty)
    y0, y1 = ty - 9.0, ty + 9.0
    vc.rect(y0, d.PART_Z - 1.6, y1, d.PART_Z, "thin")  # the wall below the seam
    vc.break_line(y0, d.PART_Z - 1.6, y1, d.PART_Z - 1.6)
    for a, b in ((y0, s[0][0]), (s[1][1], y1)):  # the plain lip either side
        vc.rect(a, d.PART_Z, b, d.PART_Z + d.LIP_H, "thin")
    vc.rect(ty - d.TAB_W / 2, d.PART_Z, ty + d.TAB_W / 2, d.PART_Z + d.TAB_H)
    vc.rect(ty - d.TAB_W / 2, bz - d.BUMP_R, ty + d.TAB_W / 2, bz + d.BUMP_R, "thin")
    gl = d.TAB_W + 2 * d.GROOVE_Y_OVER
    vc.rect(ty - gl / 2, bz - d.GROOVE_R, ty + gl / 2, bz + d.GROOVE_R, "hidden")
    vc.label(ty, bz, "bump", size=1.9)
    vc.label(ty + 7.0, d.PART_Z + d.LIP_H / 2, "lip", size=1.9)
    vc.label(ty - 7.0, d.PART_Z + d.LIP_H / 2, "lip", size=1.9)
    vc.label(ty, d.PART_Z + 2.0, "tab", size=1.9)
    vc.label(y0, d.PART_Z, "rim (seam)", dx=-2.0, size=1.9, anchor="end")
    vc.label(y0, d.PART_Z - 0.8, "toward the J4 end", dx=2.0, size=1.7, anchor="start")
    vc.label(y1, d.PART_Z - 0.8, "toward the antenna end", dx=-2.0, size=1.7, anchor="end")
    vc.dim(ty - d.TAB_W / 2, d.PART_Z + d.TAB_H, ty + d.TAB_W / 2, d.PART_Z + d.TAB_H, "u", d.PART_Z + d.TAB_H + 1.2, key="tab_w_l1", label="tab")
    vc.dim(s[0][0], d.PART_Z + d.LIP_H, s[0][1], d.PART_Z + d.LIP_H, "u", d.PART_Z + d.TAB_H + 1.2, key="slot_before_l1", label="slot (both sides)", at="p0")
    vc.dim(ty - gl / 2, bz - d.GROOVE_R, ty + gl / 2, bz - d.GROOVE_R, "u", d.PART_Z - 1.0, key="groove_len_l1", label="groove in the top half (reference)", at="in")
    vc.dim(ty + d.TAB_W / 2, d.PART_Z, ty + d.TAB_W / 2, d.PART_Z + d.TAB_H, "v", ty + d.TAB_W / 2 + 3.0, key="tab_h_l", label="tab")
    vc.dim(ty + d.TAB_W / 2, d.PART_Z, ty + d.TAB_W / 2, bz, "v", ty + d.TAB_W / 2 + 4.6, key="bump_z_l", at="in")
    vc.dim(y1, d.PART_Z, y1, d.PART_Z + d.LIP_H, "v", y1 + 0.8, key="lip_h", label="lip", at="p1")
    notes = [NOTES_ELSEWHERE, TOOLING_NOTES[3], TOOLING_NOTES[4], TOOLING_NOTES[5],
             f"Snap as modelled: a {q('lip_t', d.LIP_T)} x {q('tab_h_l', d.TAB_H)} PLA cantilever deflecting {q('bump_past_skirt', d.BUMP_PROUD)} (about 1 % strain); another material or wall changes the retention.",
             "A living hinge or side-action tab changes only this sheet: the lip, rebate and clearance stay as drawn."]
    sh.frame_and_title("both halves", "Snap joint: lip and rebate, tab, bump and groove, engagement", [SCALE_10, SCALE_5], 5, notes, [STL["bottom"], STL["top"]], vc.Y(d.PART_Z - 1.6) + 4.0)
    sh.write(OUT / "case-snap-detail.svg")


def peg_detail() -> None:
    sh = Sheet(210)
    k = 5.0
    r_s, r_p, r_b, r_bore = d.STANDOFF_D / 2, d.PEG_D / 2, d.BOSS_D / 2, d.BOSS_BORE_D / 2
    ch = d.PEG_CHAMFER
    # (a) Section B-B (x = HOLE_IN) at H1: the standoff, peg, PCB and bored boss; viewed from -x: y runs right, z up
    hx, hy = d.HOLES[0]
    y_lo, y_hi = hy - 5.0, hy + 5.0
    v = View(sh, 60.0 - k * y_lo, 34.0 + k * d.OUT_Z1, k, flip_v=True)
    sh.caption(4, 8, f"Sheet 6: SECTION B-B (x = {q('standoff_x_H1', hx)}) at H1: standoff, peg, PCB, boss; from -x, 5:1", size=3.0)
    sh.note(4, 13.5, "y runs right. Bottom half hatched 45°, top half 135°, the PCB sectioned in green.", size=1.9)
    sh.note(4, 17.0, f"Heights at the left run from datum A: the peg tip stands {q('peg_proud', d.PEG_Z1)} above the PCB's top and the boss face {q('boss_gap', d.BOSS_GAP)} above it.", size=1.9)
    sh.note(4, 20.5, f"The standoff's {q('standoff_h', d.STANDOFF_Z1 - d.STANDOFF_Z0)} is the floor to the PCB's underside: the trimmed pin stubs' room.", size=1.9)
    bottom = [
        (y_lo, d.OUT_Z0), (y_hi, d.OUT_Z0), (y_hi, d.CAV_Z0), (hy + r_s, d.CAV_Z0), (hy + r_s, d.STANDOFF_Z1), (hy + r_p, d.STANDOFF_Z1),
        (hy + r_p, d.PEG_Z1 - ch), (hy + r_p - ch, d.PEG_Z1), (hy - r_p + ch, d.PEG_Z1), (hy - r_p, d.PEG_Z1 - ch), (hy - r_p, d.STANDOFF_Z1),
        (hy - r_s, d.STANDOFF_Z1), (hy - r_s, d.CAV_Z0), (y_lo, d.CAV_Z0),
    ]
    v.section(bottom, 45)
    top = [
        (y_lo, d.OUT_Z1), (y_hi, d.OUT_Z1), (y_hi, d.CAV_Z1), (hy + r_b, d.CAV_Z1), (hy + r_b, d.BOSS_Z0), (hy + r_bore, d.BOSS_Z0),
        (hy + r_bore, d.BOSS_Z0 + d.BOSS_BORE_DEPTH), (hy - r_bore, d.BOSS_Z0 + d.BOSS_BORE_DEPTH), (hy - r_bore, d.BOSS_Z0), (hy - r_b, d.BOSS_Z0),
        (hy - r_b, d.CAV_Z1), (y_lo, d.CAV_Z1),
    ]
    v.section(top, 135)
    for z0, z1 in ((d.OUT_Z0, d.CAV_Z0), (d.CAV_Z1, d.OUT_Z1)):  # the floor and ceiling run on
        v.break_line(y_lo, z0, y_lo, z1)
        v.break_line(y_hi, z0, y_hi, z1)
    for a, b in ((y_lo, hy - d.HOLE_D / 2), (hy + d.HOLE_D / 2, y_hi)):  # the PCB, cut by the plane
        v.section([(a, -d.BOARD_T), (b, -d.BOARD_T), (b, 0), (a, 0)], 90, kind="ref", colour=REF, spacing=0.5)
    v.label(hy + 3.7, -d.BOARD_T / 2, "PCB", fill=REF, size=1.9)
    v.centre_line(hy, d.OUT_Z0 - 1.5, hy, d.OUT_Z1 + 1.5)
    v.line(y_lo, d.PART_Z, y_lo + 1.8, d.PART_Z, "centre")
    v.label(y_lo + 0.2, d.PART_Z, "seam", dy=-2.0, size=1.9, anchor="start")
    # the stack from datum A, on the left
    xl = y_lo - 1.0
    for z, key, s in ((d.CAV_Z0, "floor_top_from_bottom", "floor top"), (d.STANDOFF_Z1, "standoff_top_from_bottom", "standoff top"), (0.0, "pcb_top_from_bottom", "PCB top"), (d.PEG_Z1, "peg_tip_from_bottom", "peg tip"),
                      (d.BOSS_Z0, "boss_face_from_bottom", "boss face"), (d.CAV_Z1, "ceiling_from_bottom", "ceiling"), (d.OUT_Z1, "top_face_from_bottom", "top face")):
        v.dim(y_lo, d.OUT_Z0, y_lo, z, "v", xl, key=key, label=s)
        xl -= 1.0
    v.datum(y_lo + 1.0, d.OUT_Z0, "A", "d")
    # the local sizes, on the right
    xr = y_hi + 1.6
    v.dim(y_hi, d.OUT_Z0, y_hi, d.CAV_Z0, "v", xr, key="floor", label="floor", at="p0")
    v.dim(hy + r_s, d.STANDOFF_Z0, hy + r_s, d.STANDOFF_Z1, "v", xr + 2.4, key="standoff_h", label="standoff", at="p0")
    v.dim(hy + r_p, d.STANDOFF_Z1, hy + r_p, d.PEG_Z1, "v", xr, key="peg_h", label="peg", at="p1")
    v.dim(y_hi, d.CAV_Z1, y_hi, d.OUT_Z1, "v", xr, key="ceiling", at="in")
    # diameters
    v.dim(hy - r_s, d.CAV_Z0, hy + r_s, d.CAV_Z0, "u", d.OUT_Z0 - 1.0, key="standoff_d_H1", label="standoff", prefix="Ø")
    v.dim(hy - r_p, d.STANDOFF_Z1, hy + r_p, d.STANDOFF_Z1, "u", d.STANDOFF_Z1 - 3.0, key="peg_d", label="peg", prefix="Ø")
    v.dim(hy - r_bore, d.BOSS_Z0 + d.BOSS_BORE_DEPTH, hy + r_bore, d.BOSS_Z0 + d.BOSS_BORE_DEPTH, "u", d.BOSS_Z0 + d.BOSS_BORE_DEPTH + 2.8, key="bore_d_1", label=f"bore (min), {q('bore_depth_1', d.BOSS_BORE_DEPTH)} deep", prefix="Ø", at="p1")
    v.dim(hy - r_b, d.CAV_Z1, hy + r_b, d.CAV_Z1, "u", d.OUT_Z1 + 1.0, key="boss_d_1", label=f"boss, {q('boss_len', d.BOSS_Z1 - d.BOSS_Z0)} long", prefix="Ø")
    v.dim(hy - d.HOLE_D / 2, -d.BOARD_T, hy + d.HOLE_D / 2, -d.BOARD_T, "u", d.OUT_Z0 - 2.6, text=f"Ø{qc('HOLE_D', '{:.2f}')} hole in the {qc('BOARD_T', '{:.2f}')} PCB", at="p0", fill=REF)
    v.leader(hy + r_p - ch / 2, d.PEG_Z1 - ch / 2, f"chamfer {q('peg_chamfer', ch)} x 45°", 4, 14, size=2.3)
    # (b) the flush peg at H3 with the solid boss beside it, the same section plane, 5:1
    fx, fy = d.FLUSH_PEG
    sbx, sby, sbd, _ = d.SOLID_BOSS
    y_lo2, y_hi2 = fy - 4.0, fy + 3.6
    vb = View(sh, 158.0 - k * y_lo2, 34.0 + k * d.OUT_Z1, k, flip_v=True)
    sh.caption(122, 8, f"Section B-B at H3 (y = {q('standoff_y_H3', fy)}): flush peg, 5:1", size=3.0)
    sh.note(122, 13.5, f"The solid boss beside it is centred at x = {q('boss_x_3', sbx)},", size=1.9)
    sh.note(122, 17.0, f"just off the plane x = {q('standoff_x_H1', hx)}.", size=1.9)
    bottom2 = [
        (y_lo2, d.OUT_Z0), (y_hi2, d.OUT_Z0), (y_hi2, d.CAV_Z0), (fy + r_s, d.CAV_Z0), (fy + r_s, d.STANDOFF_Z1), (fy + r_p, d.STANDOFF_Z1),
        (fy + r_p, 0.0 - ch), (fy + r_p - ch, 0.0), (fy - r_p + ch, 0.0), (fy - r_p, 0.0 - ch), (fy - r_p, d.STANDOFF_Z1),
        (fy - r_s, d.STANDOFF_Z1), (fy - r_s, d.CAV_Z0), (y_lo2, d.CAV_Z0),
    ]
    vb.section(bottom2, 45)
    top2 = [(y_lo2, d.OUT_Z1), (y_hi2, d.OUT_Z1), (y_hi2, d.CAV_Z1), (sby + sbd / 2, d.CAV_Z1), (sby + sbd / 2, d.BOSS_Z0), (sby - sbd / 2, d.BOSS_Z0), (sby - sbd / 2, d.CAV_Z1), (y_lo2, d.CAV_Z1)]
    vb.section(top2, 135)
    for z0, z1 in ((d.OUT_Z0, d.CAV_Z0), (d.CAV_Z1, d.OUT_Z1)):
        vb.break_line(y_lo2, z0, y_lo2, z1)
        vb.break_line(y_hi2, z0, y_hi2, z1)
    for a, b in ((y_lo2, fy - d.HOLE_D / 2), (fy + d.HOLE_D / 2, y_hi2)):
        vb.section([(a, -d.BOARD_T), (b, -d.BOARD_T), (b, 0), (a, 0)], 90, kind="ref", colour=REF, spacing=0.5)
    vb.centre_line(fy, d.OUT_Z0 - 1.5, fy, d.OUT_Z1 + 1.5)
    vb.centre_line(sby, d.BOSS_Z0 - 2.0, sby, d.OUT_Z1 + 1.5)
    vb.dim(fy + r_p, d.STANDOFF_Z1, fy + r_p, 0.0, "v", y_hi2 + 1.2, key="peg_h_H3", label="peg", at="in")
    vb.dim(fy, d.OUT_Z1 + 0.6, sby, d.OUT_Z1 + 0.6, "u", d.OUT_Z1 + 1.0, key="solid_boss_offset", label="boss offset", at="p1")
    vb.dim(sby - sbd / 2, d.BOSS_Z0 + 3.0, sby + sbd / 2, d.BOSS_Z0 + 3.0, "u", d.BOSS_Z0 + 3.0, key="boss_d_3", label="solid boss", prefix="Ø", at="p0")
    vb.dim(fy - r_p, d.STANDOFF_Z1, fy + r_p, d.STANDOFF_Z1, "u", d.STANDOFF_Z1 - 3.0, key="peg_d", label="peg", prefix="Ø")
    vb.dim(y_lo2, d.OUT_Z0, y_lo2, 0.0, "v", y_lo2 - 1.0, key="peg_tip_H3_from_bottom", label="peg tip, at the PCB top")
    vb.leader(sby - sbd / 2, d.BOSS_Z0 + 0.4, ["boss face", f"{q('boss_face_from_bottom', d.BOSS_Z0 - d.OUT_Z0)} from A"], -2, -10, size=2.1)
    vb.label(fy + 0.25, d.OUT_Z0 - 2.6, "the peg stops at the PCB top: a jumper cap on JP1", size=1.8)
    vb.label(fy + 0.25, d.OUT_Z0 - 2.6, "and the Ra-02 breakout's overhang sit above it", dy=2.3, size=1.8)
    vb.label(fy + 0.25, d.OUT_Z0 - 2.6, f"(standoff Ø{q('standoff_d_H3', d.STANDOFF_D)} and floor as at H1)", dy=4.6, size=1.8)
    notes = [NOTES_ELSEWHERE, TOOLING_NOTES[2], TOOLING_NOTES[6],
             f"Bosses on {q('ceiling', d.TOP_T)} plates: core them or thin them to about 60 % of the plate for moulding; machine the Ø{q('bore_d_1', d.BOSS_BORE_D)} bore with a flat end mill.",
             TOOLING_NOTES[7]]
    sh.frame_and_title("both halves", "Peg, PCB and boss stack at H1 and at the flush peg H3", [SCALE_5], 6, notes, [STL["bottom"], STL["top"]], vb.Y(d.OUT_Z0 - 2.6) + 8.0)
    sh.write(OUT / "case-peg-detail.svg")


def top_slot_plan() -> None:
    sh = Sheet(210)
    k = 2.0
    v = View(sh, 75.0, 70.0, k)
    sh.caption(4, 8, "Sheet 7: SLOTTED TOP HALF, plan from above (the outside of the ceiling), 2:1")
    sh.note(4, 13.5, "x right, y down, as sheet 1: the USB-C wall (datum B) on the left, the J4 end (datum C) at the top. This half is sheet 2's top half with a slot through the ceiling")
    sh.note(4, 17.5, "over J4, the spare-GPIO header, for jumper wires out of the closed case. Hidden detail is omitted (see sheet 2); the header and the PCB are drawn in green for reference.")
    v.rect(d.OUT_X0, d.OUT_Y0, d.OUT_X1, d.OUT_Y1, rx=d.CORNER_R)
    v.rect(d.J4_SLOT_X0, d.J4_SLOT_Y0, d.J4_SLOT_X1, d.J4_SLOT_Y1)
    v.centre_line(d.J4_SLOT_X0 - 3.0, (d.J4_SLOT_Y0 + d.J4_SLOT_Y1) / 2, d.J4_SLOT_X1 + 3.0, (d.J4_SLOT_Y0 + d.J4_SLOT_Y1) / 2)
    v.centre_line((d.J4_SLOT_X0 + d.J4_SLOT_X1) / 2, d.J4_SLOT_Y0 - 3.0, (d.J4_SLOT_X0 + d.J4_SLOT_X1) / 2, d.J4_SLOT_Y1 + 3.0)
    # the PCB and J4's plastic body, seen through, for reference
    v.rect(0, 0, d.W, d.H, "ref")
    v.rect(d.J4_SLOT_X0 + d.SLOT_OVER, d.J4_SLOT_Y0 + d.SLOT_OVER, d.J4_SLOT_X1 - d.SLOT_OVER, d.J4_SLOT_Y1 - d.SLOT_OVER, "ref")
    v.label(d.W / 2, 12.0, f"J4 header body (reference), the slot {qc('SLOT_OVER')} past it on every side", fill=REF, size=2.0)
    v.label(d.W / 2, 30.0, "PCB (reference)", fill=REF, size=2.0)
    v.label(d.W / 2, 50.0, "top face; the antenna wall is at the bottom, the USB-C wall on the left", size=2.0)
    # --- across the top: the slot from datum B ---
    t1, t2, t3 = (d.OUT_Y0 - 4.5 * i for i in range(1, 4))
    v.dim(d.OUT_X0, d.OUT_Y0, d.OUT_X1, d.OUT_Y0, "u", t3, key="out_x_top")
    v.dim(d.OUT_X0, d.OUT_Y0, (d.J4_SLOT_X0 + d.J4_SLOT_X1) / 2, d.J4_SLOT_Y0, "u", t2, key="slot_from_usb_face", label="slot centre")
    v.dim(d.J4_SLOT_X0, d.J4_SLOT_Y0, d.J4_SLOT_X1, d.J4_SLOT_Y0, "u", t1, key="slot_len", label="slot")
    v.datum(d.OUT_X0, t3 - 1.0, "B", "u")
    # --- down the left: the slot from datum C ---
    l1, l2, l3 = (d.OUT_X0 - 4.5 * i for i in range(1, 4))
    v.dim(d.OUT_X0, d.OUT_Y0, d.OUT_X0, d.OUT_Y1, "v", l3, key="out_y_top")
    v.dim(d.OUT_X0, d.OUT_Y0, d.J4_SLOT_X0, (d.J4_SLOT_Y0 + d.J4_SLOT_Y1) / 2, "v", l2, key="slot_from_back_face", label="slot centre", at="p1")
    v.dim(d.J4_SLOT_X0, d.J4_SLOT_Y0, d.J4_SLOT_X0, d.J4_SLOT_Y1, "v", l1, key="slot_w", label="slot", at="p1")
    v.datum(l3 - 1.0, d.OUT_Y0, "C", "l")
    v.leader(d.OUT_X1 - 0.6, d.OUT_Y1 - 0.6, f"R{q('corner_r_top', d.CORNER_R)} (4 corners)", 8, 6)
    v.leader(d.J4_SLOT_X1, d.J4_SLOT_Y1, f"slot through the {q('ceiling', d.TOP_T)} ceiling; everything else as sheet 2", 10, 8, size=2.1)
    sh.frame_and_title("top half, slotted", "Plan from above: the J4 slot through the ceiling of the second top half", [SCALE_2], 7, [NOTES_ELSEWHERE, TOOLING_NOTES[0]], [STL["top-slot"], STEP["top-slot"]], v.Y(d.OUT_Y1) + 6.0)
    sh.write(OUT / "case-top-slot-plan.svg")


SHEETS = [bottom_plan, top_plan, section_antenna, end_elevations, snap_detail, peg_detail, top_slot_plan]


# ---------------------------------------------------------------------------
# the caliper checklist in docs/case-drawings.md
# ---------------------------------------------------------------------------
CHECKLIST_BEGIN, CHECKLIST_END = "<!-- checklist:begin (written by scripts/draw_case.py) -->", "<!-- checklist:end -->"
TOL_LIN, TOL_SNAP, TOL_Z = f"±{d.TOL_LINEAR:.2f}", f"±{d.TOL_SNAP:.2f}", f"±{d.TOL_Z:.2f}"


def checklist() -> list[tuple[str, str, list[tuple[str, float]], str]]:
    """Rows of (what to measure and from where, the expected value's format,
    its (key, value) pairs, the tolerance): outside first, then each half's
    depths, then its features.  The keys name rows of the measured JSON."""
    lip_top = d.PART_Z + d.LIP_H
    return [
        ("Each half outside, width x length (calipers across the outside faces)", "{} x {}", [("out_x", d.OUT_X1 - d.OUT_X0), ("out_y", d.OUT_Y1 - d.OUT_Y0)], TOL_LIN),
        ("Closed case height, outside bottom face (A) to the outside top face", "{}", [("overall_h", d.OUT_Z1 - d.OUT_Z0)], TOL_Z),
        ("Bottom half: A to the wall's top (the rim, on the seam), beside a tab; tab tips above A", "{}; {}", [("bottom_h", d.PART_Z - d.OUT_Z0), ("tab_tips_from_bottom", d.PART_Z + d.TAB_H - d.OUT_Z0)], TOL_Z),
        ("Top half: outside top face to the skirt's edge (on the seam); boss faces standing past the skirt's edge (straight edge across the skirt)", "{}; {}", [("top_h", d.OUT_Z1 - d.PART_Z), ("boss_past_skirt", d.PART_Z - d.BOSS_Z0)], TOL_Z),
        ("Vertical corner radius (radius gauge), each half", "R{}", [("corner_r", d.CORNER_R)], TOL_LIN),
        ("Bottom half: long wall, back (J4 end) wall and antenna wall thickness at the rim, below the lip", "{}; {}; {}", [("wall", d.WALL), ("back_wall", d.WALL), ("front_wall", d.ANT_WALL_T)], TOL_LIN),
        ("Bottom half: cavity, width x length, below the lip", "{} x {}", [("cav_x", d.CAV_X1 - d.CAV_X0), ("cav_y", d.CAV_Y1 - d.CAV_Y0)], TOL_LIN),
        ("Bottom half: lip thickness; lip height above the rim", "{}; {}", [("lip_t", d.LIP_T), ("lip_h", d.LIP_H)], TOL_SNAP),
        ("Bottom half: lip gaps, in the antenna wall (centred on the antenna axis) and in the USB-C wall (across the plug recess)", "{}; {}", [("lip_gap_w", d.LIP_GAP_X1 - d.LIP_GAP_X0), ("lip_gap_usb_w", d.LIP_GAP_USB_Y1 - d.LIP_GAP_USB_Y0)], TOL_LIN),
        ("Bottom half: tab width; tab height above the rim; tab thickness through the bump; pitch of the two tabs", "{}; {}; {}; {}", [("tab_w_l1", d.TAB_W), ("tab_h_l", d.TAB_H), ("tab_t_at_bump_l", d.LIP_T + d.BUMP_R), ("tab_pitch_l", d.TAB_Y[1] - d.TAB_Y[0])], TOL_SNAP),
        ("Bottom half: first tab's centre from the J4-end outside face (C); bump centre above the rim", "{}; {}", [("tab_l1_from_back_face", d.TAB_Y[0] - d.OUT_Y0), ("bump_z_l", d.BUMP_Z)], TOL_LIN),
        (f"Bottom half, depth rod with the base across both lips at y = {d.SECTION_DD_Y:g} (section D-D, no tab there), so from {fmt(d.LIP_H)} above the rim: floor; standoff top; peg tip (H1, H2, H4); peg tip H3", "{}; {}; {}; {}",
         [("floor_below_lip", lip_top - d.CAV_Z0), ("standoff_top_below_lip", lip_top - d.STANDOFF_Z1), ("peg_tip_below_lip", lip_top - d.PEG_Z1), ("peg_tip_H3_below_lip", lip_top - 0.0)], TOL_Z),
        ("Bottom half: floor thickness (bottom half height less the floor depth from the rim)", "{}", [("floor", d.FLOOR)], TOL_Z),
        ("Bottom half: standoff diameter; standoff height, floor to the PCB's underside (the trimmed pin stubs' room); pitch across x along", "{}; {}; {} x {}", [("standoff_d_H1", d.STANDOFF_D), ("standoff_h", d.STANDOFF_Z1 - d.STANDOFF_Z0), ("hole_pitch_x", d.W - 2 * d.HOLE_IN), ("hole_pitch_y", d.H - 2 * d.HOLE_IN)], TOL_LIN),
        ("Bottom half: H1 standoff centre from the USB-C wall's outside face (B) and from the J4-end face (C)", "{}; {}", [("hole_H1_from_usb_face", d.HOLE_IN - d.OUT_X0), ("hole_H1_from_back_face", d.HOLE_IN - d.OUT_Y0)], TOL_LIN),
        ("Bottom half: peg diameter below the chamfer; peg above the standoff (H1, H2, H4); H3", "{}; {}; {}", [("peg_d", d.PEG_D), ("peg_h", d.PEG_H), ("peg_h_H3", d.BOARD_T)], TOL_SNAP),
        ("Bottom half: USB-C window width; its sill below the rim; window centre from C", "{}; {}; {}", [("window_w", d.USB_WIN_W), ("window_below_seam", d.PART_Z - d.USB_WIN_Z0), ("window_from_back_face", d.USB_WIN_Y - d.OUT_Y0)], TOL_LIN),
        ("Both halves: plug recess width; recess depth into the wall; wall left under it; recess bottom above A (bottom half) and top above A (top half)", "{}; {}; {}; {}; {}",
         [("recess_w", d.USB_RECESS_W), ("recess_depth", d.USB_RECESS_DEPTH), ("wall_under_recess", d.CAV_X0 - d.USB_RECESS_X), ("recess_from_bottom", d.USB_RECESS_Z0 - d.OUT_Z0), ("recess_top_from_bottom", d.USB_RECESS_Z1 - d.OUT_Z0)], TOL_LIN),
        ("Bottom half: antenna half-hole width at the rim; its depth below the rim; centre from B; E07 pocket width; pocket depth into the wall; pocket floor below the rim", "{}; {}; {}; {}; {}; {}",
         [("hole_d_z", d.ANT_HOLE_D), ("hole_below_seam", d.ANT_Z - d.ANT_HOLE_Z0), ("hole_from_usb_face", d.SOCKET_MID_X - d.OUT_X0), ("pocket_w", d.E07_POCKET), ("pocket_depth", d.E07_POCKET_DEPTH), ("pocket_floor_below_seam", d.PART_Z - d.POCKET_Z0)], TOL_LIN),
        ("Top half: skirt thickness at its edge; between the skirt's inner faces", "{}; {}", [("skirt_t", d.SKIRT_T), ("skirt_faces", d.CAV_X1 - d.CAV_X0 + 2 * d.REBATE)], TOL_SNAP),
        (f"Top half: rebate height above the skirt's edge. No depth rod fits the {fmt(d.REBATE)} rebate: a strip of {fmt(d.LIP_T)} card cut to this height should just enter it, or take it from the tab height plus the clearance over the tab", "{} ({} over the tab)", [("rebate_h", d.SKIRT_H), ("rebate_over_tab", d.SKIRT_H - d.TAB_H)], TOL_SNAP),
        ("Top half, depth rod with the base across the skirt's edge (on the seam plane): ceiling", "{}", [("ceiling_above_seam", d.CAV_Z1 - d.PART_Z)], TOL_Z),
        ("Top half: ceiling thickness (top half height less the ceiling depth)", "{}", [("ceiling", d.TOP_T)], TOL_Z),
        ("Top half: boss diameter; bore diameter (minimum); bore depth; solid boss diameter", "{}; {} min; {}; {}", [("boss_d_1", d.BOSS_D), ("bore_d_1", d.BOSS_BORE_D), ("bore_depth_1", d.BOSS_BORE_DEPTH), ("boss_d_3", d.SOLID_BOSS[2])], TOL_SNAP),
        ("Top half: groove centres from C (a pin in the groove, against a rule along the skirt); groove length", "{}, {}; {}", [("groove_r1_from_back_face", d.TAB_Y[0] - d.OUT_Y0), ("groove_r2_from_back_face", d.TAB_Y[1] - d.OUT_Y0), ("groove_len_r1", d.TAB_W + 2 * d.GROOVE_Y_OVER)], TOL_LIN),
        ("Top half: USB-C window head above the skirt's edge; antenna half-hole depth above the skirt's edge", "{}; {}", [("window_above_seam", d.USB_WIN_Z1 - d.PART_Z), ("hole_above_seam", d.ANT_HOLE_Z1 - d.ANT_Z)], TOL_LIN),
        ("Top half: pry notch width; notch height above the skirt's edge; notch centre from B", "{}; {}; {}", [("notch_w", d.NOTCH_W), ("notch_depth", d.NOTCH_DEPTH), ("notch_from_usb_face", d.NOTCH_X - d.OUT_X0)], TOL_LIN),
        ("Slotted top half: J4 slot length x width; slot centre from B and from C", "{} x {}; {}, {}", [("slot_len", d.J4_SLOT_X1 - d.J4_SLOT_X0), ("slot_w", d.J4_SLOT_Y1 - d.J4_SLOT_Y0), ("slot_from_usb_face", (d.J4_SLOT_X0 + d.J4_SLOT_X1) / 2 - d.OUT_X0), ("slot_from_back_face", (d.J4_SLOT_Y0 + d.J4_SLOT_Y1) / 2 - d.OUT_Y0)], TOL_LIN),
        ("Function: the PCB presses onto the pegs by hand and sits flat on the standoffs; the halves close with no gap at the seam and all four tabs click; the E07's jack, or the pigtail's bulkhead, passes the hole; a USB-C plug reaches the receptacle through the recess", "-", [], "-"),
    ]


def checklist_markdown() -> str:
    lines = [
        "| # | Measurement | Expected | Tolerance |",
        "| --- | --- | --- | --- |",
    ]
    for i, (what, form, pairs, tol) in enumerate(checklist(), 1):
        lines.append(f"| {i} | {what} | {form.format(*(fmt(v) for _, v in pairs))} | {tol} |")
    return "\n".join(lines)


def write_checklist() -> None:
    """Replace the checklist section of docs/case-drawings.md."""
    text = DOC.read_text(encoding="utf-8")
    a, b = text.index(CHECKLIST_BEGIN), text.index(CHECKLIST_END)
    n_quoted = sum(len(pairs) for _, _, pairs, _ in checklist())
    body = (
        f"{CHECKLIST_BEGIN}\n"
        f"Tolerances (the sheets' note): ±{d.TOL_LINEAR:.2f} linear, ±{d.TOL_SNAP:.2f} on snap and peg\n"
        f"features, heights ±{d.TOL_Z:.2f} (half a {d.LAYER_H:g} mm layer), each half printed as\n"
        f"supplied (open side up); the Ø{d.BOSS_BORE_D:.2f} boss bore is a minimum limit.\n"
        f"Every expected value below is one of the {n_quoted} that `--check` compares\n"
        f"with the measured solids.\n\n{checklist_markdown()}\n"
    )
    new = text[:a] + body + text[b:]
    if new != text:
        DOC.write_text(new, encoding="utf-8")
        print(f"wrote the checklist into {DOC.relative_to(ROOT)}")
    else:
        print(f"checklist in {DOC.relative_to(ROOT)} is current")


# ---------------------------------------------------------------------------
# --check: read the numbers back out of the sheets against the measured solids
# ---------------------------------------------------------------------------
def check() -> int:
    measured = json.loads(MEASURED.read_text(encoding="utf-8"))
    bad: list[str] = []
    n_dim = n_const = 0
    tspan = re.compile(r'<tspan data-(dim|const)="([^"]+)">([^<]*)</tspan>')
    for svg in sorted(OUT.glob("case-*.svg")):
        txt = svg.read_text(encoding="utf-8")
        for kind, key, val in tspan.findall(txt):
            try:
                value = float(val)
            except ValueError:
                bad.append(f"{svg.name}: {key}: '{val}' is not a number")
                continue
            if kind == "dim":
                n_dim += 1
                if key not in measured:
                    bad.append(f"{svg.name}: {key} = {val}: no such measurement in {MEASURED.name}")
                elif abs(measured[key]["measured"] - value) > CHECK_TOL:
                    bad.append(f"{svg.name}: {key} = {val}, but the solid measures {measured[key]['measured']:.4f} ({measured[key]['what']})")
            else:
                n_const += 1
                ref = getattr(d, key, None)
                if not isinstance(ref, (int, float)):
                    bad.append(f"{svg.name}: {key}: not a scalar in case_dims")
                elif abs(ref - value) > 0.005:
                    bad.append(f"{svg.name}: {key} = {val}, but case_dims.{key} = {ref}")
        # any decimal number outside a tagged span, in text that is not marked free, is hand-typed
        for attrs, body in re.findall(r"<text([^>]*)>(.*?)</text>", txt):
            if 'class="free"' in attrs:
                continue
            for num in re.findall(r"\d+\.\d+", re.sub(r"<tspan[^>]*>[^<]*</tspan>", "", body)):
                bad.append(f"{svg.name}: untagged number {num} in '{visible(body)}'")
    n_list = 0
    for i, (what, _, pairs, _) in enumerate(checklist(), 1):
        for key, value in pairs:
            n_list += 1
            if key not in measured:
                bad.append(f"checklist row {i}: {key}: no such measurement")
            elif abs(measured[key]["measured"] - value) > CHECK_TOL:
                bad.append(f"checklist row {i}: {key} = {value:.2f}, but the solid measures {measured[key]['measured']:.4f}")
    for line in bad:
        print(f"MISMATCH  {line}")
    print(f"{n_dim} dimensions and {n_const} constants on the sheets, {n_list} checklist values, against {len(measured)} measurements: {len(bad)} mismatch(es)")
    return 1 if bad else 0


def main() -> None:
    global REV
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="compare every number on the written sheets and in the checklist with the measured solids")
    args = ap.parse_args()
    if args.check:
        sys.exit(check())
    REV = model_revision()
    OUT.mkdir(parents=True, exist_ok=True)
    for sheet in SHEETS:
        sheet()
    write_checklist()


REV = ""

if __name__ == "__main__":
    main()

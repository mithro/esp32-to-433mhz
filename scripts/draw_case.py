#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Draw the mechanical drawings (SVG) of the socket adapter's printed case.

Every number on the sheets comes from scripts/case_dims.py, the constants
scripts/build_case.py builds the solids from, so the drawings cannot drift
from the model.  The sheets are sized in millimetres (scale 2:1 for the
views, 5:1 and 10:1 for the details), so a print at 100 % can be laid on a
part.  Written to docs/images/case-*.svg:

  case-bottom-plan.svg      bottom half from above: cavity, walls, standoffs
                            and pegs, lip, snap tabs, section marks
  case-top-plan.svg         top half from below: skirt and rebate, grooves,
                            bosses, USB-C window, antenna hole and pocket
  case-section-antenna.svg  section A-A on the antenna axis, case closed
  case-end-elevations.svg   the USB-C wall and the antenna wall from outside
  case-snap-detail.svg      section C-C through a snap tab, D-D through the
                            plain lip, and a tab from outside
  case-peg-detail.svg       section B-B through the peg / board / boss stack
                            at H1 and at the flush peg

With --check the script rebuilds the solids with CadQuery (re-running
itself under uv with CadQuery added) and measures the dimensions the sheets
quote on them, printing expected against measured and failing on any
mismatch.
"""

from __future__ import annotations

import argparse
import math
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import case_dims as d  # noqa: E402

OUT = pathlib.Path(__file__).resolve().parent.parent / "docs" / "images"
PART = "ESP32-C3 radio adapter case"

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
COMMON_NOTES = [
    "No draft is modelled: add 1-2° on every face parallel to the pull (walls, standoffs, bosses, pegs).",
    "Internal corners are sharp (only the vertical outside corners are R2): add R0.3-0.5 at wall/floor and boss roots.",
    "Walls 2.2, plates 2.0 (antenna wall 2.5); the Ø4.0 standoffs and Ø4.4 bosses on 2 mm plates will sink: core or accept.",
    "The tab bumps and skirt grooves are undercuts to a z pull: side actions or lifters, or accept a 0.2 mm bump-off.",
    "The Ø2.15 pegs rely on FDM printing oversize to grip the Ø2.2 holes: size a true interference, or use inserts and screws.",
    "Aluminium: 0.8 mm tabs cannot flex; use M2 screws through the bosses into tapped standoffs, and R1+ internal corners.",
]


# ---------------------------------------------------------------------------
# a sheet in millimetres and views on it
# ---------------------------------------------------------------------------
class Sheet:
    def __init__(self, w: float, h: float):
        self.w, self.h = w, h
        self.items: list[str] = []
        self.defs: list[str] = []

    def add(self, s: str) -> None:
        self.items.append(s)

    def text(self, x, y, s, size=TXT, anchor="middle", angle=0.0, weight="normal", fill=INK, halo=False):
        t = f' transform="rotate({angle:g} {x:.2f} {y:.2f})"' if angle else ""
        h = f' stroke="#ffffff" stroke-width="{0.28 * size:.2f}" paint-order="stroke" stroke-linejoin="round"' if halo else ""
        self.add(f'<text x="{x:.2f}" y="{y:.2f}" font-size="{size:.2f}" font-family="{FONT}" font-weight="{weight}" fill="{fill}" text-anchor="{anchor}" dy="0.35em"{t}{h}>{s}</text>')

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

    def note(self, x, y, s, size=2.1):
        self.text(x, y, s, size=size, anchor="start")

    def frame_and_title(self, part: str, title: str, scale: str, sheet_no: str, notes: list[str]) -> None:
        """Border, the title block bottom-right and the engineering notes bottom-left."""
        tw, nsize, nlead = 78.0, 1.9, 2.7
        nx0, x0 = 1.5, self.w - 1.5 - tw
        lines = []
        for i, s in enumerate(notes):
            lines += wrap(f"{i + 1}. {s}", nsize, x0 - nx0 - 4.0)
        block_h = max(25.0, 6.4 + len(lines) * nlead + 1.5)
        y0 = self.h - 1.5 - block_h
        self.rect(1.5, 1.5, self.w - 1.5, self.h - 1.5, width=0.5)
        self.rect(x0, y0, self.w - 1.5, self.h - 1.5, width=0.5)
        self.line(x0, y0 + 6.5, self.w - 1.5, y0 + 6.5, width=0.3)
        self.line(x0, y0 + 11.0, self.w - 1.5, y0 + 11.0, width=0.3)
        self.line(x0, y0 + 15.0, self.w - 1.5, y0 + 15.0, width=0.3)
        self.text(x0 + 2, y0 + 3.4, f"{PART} - {part}", size=2.9, anchor="start", weight="bold")
        self.text(x0 + 2, y0 + 8.8, title, size=1.9, anchor="start")
        self.text(x0 + 2, y0 + 13.0, f"Scale {scale}  |  Units mm  |  Sheet {sheet_no}  |  scripts/draw_case.py", size=2.1, anchor="start")
        small = [
            "All dimensions from the model (scripts/case_dims.py); no draft angles modelled.",
            "Tolerance: FDM print +/-0.2 unless noted; snap and peg features +/-0.05 as modelled.",
            "Frame: x right, y down from the PCB's top-left corner, z up from the PCB's top face.",
        ]
        for i, s in enumerate(small):
            self.text(x0 + 2, y0 + 17.4 + i * 2.6, s, size=1.8, anchor="start")
        self.rect(nx0, y0, x0, self.h - 1.5, width=0.5)
        self.text(nx0 + 2, y0 + 3.4, "NOTES for an injection-moulded or machined version", size=2.3, anchor="start", weight="bold")
        for i, s in enumerate(lines):
            self.text(nx0 + 2, y0 + 7.4 + i * nlead, s, size=nsize, anchor="start")

    def write(self, path: pathlib.Path) -> None:
        defs = "<defs>\n" + "\n".join(self.defs) + "\n</defs>\n" if self.defs else ""
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w:g}mm" height="{self.h:g}mm" viewBox="0 0 {self.w:g} {self.h:g}">\n'
            f'<rect width="{self.w:g}" height="{self.h:g}" fill="#ffffff"/>\n' + defs + "\n".join(self.items) + "\n</svg>\n"
        )
        path.write_text(svg)
        print(f"wrote {path.relative_to(OUT.parents[1])} ({len(svg) // 1024} kB)")


def wrap(s: str, size: float, width: float) -> list[str]:
    """Greedy word wrap for Helvetica-ish text (0.48 em average advance)."""
    per = width / (0.48 * size)
    out, line = [], ""
    for w in s.split():
        if line and len(line) + 1 + len(w) > per:
            out.append(line)
            line = "   " + w
        else:
            line = f"{line} {w}" if line else w
    return out + [line]


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

    def section(self, pts, angle=45.0, kind="outline"):
        """Cut material: hatched and outlined."""
        self.hatch(pts, angle)
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

    def dim(self, u0, v0, u1, v1, axis, pos, text=None, at=None, nudge=0.0, fill=DIM, fmt="{:.2f}"):
        """Linear dimension between model points (u0, v0) and (u1, v1),
        measured along `axis` ('u' or 'v'), with the dimension line at
        model coordinate `pos` on the other axis.  `at` places the value:
        None picks inside if it fits, else beyond the second point; 'in',
        'p0', 'p1' force it.  `nudge` shifts the value along the line (sheet mm)."""
        x0, y0 = self.P(u0, v0)
        x1, y1 = self.P(u1, v1)
        value = abs((u1 - u0) if axis == "u" else (v1 - v0))
        s = text if text is not None else fmt.format(value)
        tw = 0.52 * TXT * len(s) + 1.0
        if axis == "u":
            yl = self.Y(pos)
            xa, xb = x0, x1
            for x, y in ((x0, y0), (x1, y1)):  # extension lines
                sgn = 1 if yl > y else -1
                self.sh.line(x, y + sgn * EXT_GAP, x, yl + sgn * EXT_OVER, stroke=fill, width=0.18)
            span = abs(xb - xa)
            inside = at == "in" or (at is None and span >= tw + 2 * ARROW_L + 1.0)
            self.sh.line(xa, yl, xb, yl, stroke=fill, width=0.18)
            lo, hi = sorted((xa, xb))
            if inside:
                self.sh.arrow(lo, yl, math.pi, fill)
                self.sh.arrow(hi, yl, 0.0, fill)
                self.sh.text((lo + hi) / 2 + nudge, yl - 1.2, s, size=TXT, fill=fill, halo=True)
            else:
                self.sh.arrow(lo, yl, 0.0, fill)
                self.sh.arrow(hi, yl, math.pi, fill)
                self.sh.line(lo - ARROW_L - 2.5, yl, lo, yl, stroke=fill, width=0.18)
                self.sh.line(hi, yl, hi + ARROW_L + 2.5, yl, stroke=fill, width=0.18)
                right = (at == "p1" and x1 >= x0) or (at == "p0" and x0 > x1) or (at is None and x1 >= x0)
                if right:
                    self.sh.text(hi + ARROW_L + 1.0 + nudge, yl - 1.2, s, size=TXT, anchor="start", fill=fill, halo=True)
                else:
                    self.sh.text(lo - ARROW_L - 1.0 + nudge, yl - 1.2, s, size=TXT, anchor="end", fill=fill, halo=True)
        else:
            xl = self.X(pos)
            ya, yb = y0, y1
            for x, y in ((x0, y0), (x1, y1)):
                sgn = 1 if xl > x else -1
                self.sh.line(x + sgn * EXT_GAP, y, xl + sgn * EXT_OVER, y, stroke=fill, width=0.18)
            span = abs(yb - ya)
            inside = at == "in" or (at is None and span >= tw + 2 * ARROW_L + 1.0)
            self.sh.line(xl, ya, xl, yb, stroke=fill, width=0.18)
            lo, hi = sorted((ya, yb))
            if inside:
                self.sh.arrow(xl, lo, -math.pi / 2, fill)
                self.sh.arrow(xl, hi, math.pi / 2, fill)
                self.sh.text(xl - 1.2, (lo + hi) / 2 + nudge, s, size=TXT, angle=-90, fill=fill, halo=True)
            else:
                self.sh.arrow(xl, lo, math.pi / 2, fill)
                self.sh.arrow(xl, hi, -math.pi / 2, fill)
                self.sh.line(xl, lo - ARROW_L - 2.5, xl, lo, stroke=fill, width=0.18)
                self.sh.line(xl, hi, xl, hi + ARROW_L + 2.5, stroke=fill, width=0.18)
                up = (at == "p1" and y1 <= y0) or (at == "p0" and y0 < y1) or (at is None and y1 <= y0)
                if up:
                    self.sh.text(xl - 1.2, lo - ARROW_L - 1.0 + nudge, s, size=TXT, angle=-90, anchor="start", fill=fill, halo=True)
                else:
                    self.sh.text(xl - 1.2, hi + ARROW_L + 1.0 + nudge, s, size=TXT, angle=-90, anchor="end", fill=fill, halo=True)

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

    def cutting_plane(self, u0, v0, u1, v1, letter, side=1):
        """Section mark: a chain line with thick ends, arrows for the viewing
        direction and the letter at both ends.  The arrows point to the
        `side` of the line (+1: the sheet-space left normal of p0->p1)."""
        x0, y0 = self.P(u0, v0)
        x1, y1 = self.P(u1, v1)
        self.sh.line(x0, y0, x1, y1, stroke=INK, width=0.25, dash="5 1 1 1")
        ang = math.atan2(y1 - y0, x1 - x0)
        nx, ny = -math.sin(ang) * side, math.cos(ang) * side
        for x, y, back in ((x0, y0, 1), (x1, y1, -1)):
            self.sh.line(x, y, x + back * 4 * math.cos(ang), y + back * 4 * math.sin(ang), stroke=INK, width=0.8)
            self.sh.line(x, y, x + nx * 4, y + ny * 4, stroke=INK, width=0.25)
            self.sh.arrow(x + nx * 4, y + ny * 4, math.atan2(ny, nx), INK)
            self.sh.text(x + nx * 6.5, y + ny * 6.5, letter, size=3.2, weight="bold")


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


# ---------------------------------------------------------------------------
# the sheets
# ---------------------------------------------------------------------------
def bottom_plan() -> None:
    sh = Sheet(210, 252)
    k = 2.0
    v = View(sh, 62.0, 66.0, k)
    sh.caption(4, 8, "BOTTOM HALF, plan from above (open side toward the viewer), 2:1")
    sh.note(4, 13.5, "The PCB (green) is reference only. Sections: A-A on sheet 3, B-B on sheet 6, C-C and D-D on sheet 5.")
    # outline, wall top, lip, cavity
    v.rect(d.OUT_X0, d.OUT_Y0, d.OUT_X1, d.OUT_Y1, rx=d.CORNER_R)
    v.rect(d.LIP_X0, d.LIP_Y0, d.LIP_X1, d.LIP_Y1, "thin")
    v.rect(d.CAV_X0, d.CAV_Y0, d.CAV_X1, d.CAV_Y1)
    # the lip's gap in the antenna wall
    v.line(d.LIP_GAP_X0, d.CAV_Y1, d.LIP_GAP_X0, d.LIP_Y1, "thin")
    v.line(d.LIP_GAP_X1, d.CAV_Y1, d.LIP_GAP_X1, d.LIP_Y1, "thin")
    v.label(d.SOCKET_MID_X, d.CAV_Y1, f"lip gapped {fmt(d.LIP_GAP_X1 - d.LIP_GAP_X0)} wide", dy=-3.0, size=2.0)
    # tabs and slots; the bump shows as a strip along the tab's outer face
    for ty in d.TAB_Y:
        for x_in, x_out, side in ((d.CAV_X0, d.LIP_X0, -1), (d.CAV_X1, d.LIP_X1, 1)):
            for s0, s1 in d.slots(ty):
                v.rect(x_in, s0, x_out, s1, "thin")
            v.rect(x_out, ty - d.TAB_W / 2, x_out + side * d.BUMP_R, ty + d.TAB_W / 2, "thin")
    # standoffs and pegs
    for hx, hy in d.HOLES:
        v.circle(hx, hy, d.STANDOFF_D / 2)
        v.circle(hx, hy, d.PEG_D / 2)
        v.circle(hx, hy, d.PEG_D / 2 - d.PEG_CHAMFER, "thin")
        v.centre_mark(hx, hy, d.STANDOFF_D / 2, over=2.0)
    v.label(d.FLUSH_PEG[0] + 0.6, 40.4, "peg flush with the PCB top here (H3)", size=1.9, anchor="start")
    # the PCB for reference
    v.rect(0, 0, d.W, d.H, "ref")
    for hx, hy in d.HOLES:
        v.circle(hx, hy, d.HOLE_D / 2, "ref")
    v.label(d.W / 2, 17.0, f"PCB {d.W:g} x {d.H:g}, holes Ø{fmt(d.HOLE_D)} (reference)", fill=REF, size=2.0)
    v.leader(0, 0, "PCB origin (0, 0)", 4, 11, fill=REF, size=2.0)
    # section marks (the arrows point the way the section is viewed)
    v.cutting_plane(d.SOCKET_MID_X, d.OUT_Y1 + 3.0, d.SOCKET_MID_X, d.OUT_Y0 - 3.0, "A", side=-1)  # viewed from +x
    v.cutting_plane(d.HOLE_IN, d.OUT_Y1 + 3.0, d.HOLE_IN, d.OUT_Y0 - 3.0, "B", side=-1)
    v.cutting_plane(d.OUT_X0 - 3.0, d.TAB_Y[0], d.OUT_X1 + 3.0, d.TAB_Y[0], "C", side=1)  # viewed from -y
    v.cutting_plane(d.OUT_X0 - 3.0, 44.0, d.OUT_X1 + 3.0, 44.0, "D", side=1)
    # --- across the top, from the outside faces ---
    t1, t2, t3 = d.OUT_Y0 - 8.0, d.OUT_Y0 - 13.0, d.OUT_Y0 - 18.0
    v.dim(d.OUT_X0, d.OUT_Y0, d.OUT_X1, d.OUT_Y0, "u", t3)
    v.dim(d.CAV_X0, d.CAV_Y0, d.CAV_X1, d.CAV_Y0, "u", t2, text=f"{fmt(d.CAV_X1 - d.CAV_X0)} cavity")
    v.dim(d.OUT_X0, d.OUT_Y0, d.CAV_X0, d.CAV_Y0, "u", t1, at="p0", text=f"{fmt(d.WALL)} wall")
    v.dim(d.OUT_X0, d.OUT_Y0, d.HOLE_IN, d.HOLE_IN, "u", t1, at="in")
    v.dim(d.HOLE_IN, d.HOLE_IN, d.W - d.HOLE_IN, d.HOLE_IN, "u", t1)
    v.dim(d.W - d.HOLE_IN, d.HOLE_IN, d.OUT_X1, d.OUT_Y0, "u", t1, at="p1")
    # --- down the left, from the near (y = 0 end) outside face ---
    l1, l2, l3 = d.OUT_X0 - 7.0, d.OUT_X0 - 12.5, d.OUT_X0 - 18.0
    v.dim(d.OUT_X0, d.OUT_Y0, d.OUT_X0, d.OUT_Y1, "v", l3)
    v.dim(d.CAV_X0, d.CAV_Y0, d.CAV_X0, d.CAV_Y1, "v", l2, text=f"{fmt(d.CAV_Y1 - d.CAV_Y0)} cavity")
    v.dim(d.OUT_X0, d.OUT_Y0, d.CAV_X0, d.CAV_Y0, "v", l1, at="p0", text=f"{fmt(d.WALL)} wall")
    v.dim(d.OUT_X0, d.OUT_Y0, d.HOLE_IN, d.HOLE_IN, "v", l1, at="in")
    v.dim(d.HOLE_IN, d.HOLE_IN, d.HOLE_IN, d.H - d.HOLE_IN, "v", l1)
    v.dim(d.CAV_X0, d.CAV_Y1, d.OUT_X0, d.OUT_Y1, "v", l1, at="p0", text=f"{fmt(d.ANT_WALL_T)} antenna wall")
    # --- down the right: the tabs, from the outside face and (green) from the PCB origin ---
    r1, r2 = d.OUT_X1 + 7.0, d.OUT_X1 + 12.5
    v.dim(d.OUT_X1, d.OUT_Y0, d.OUT_X1, d.TAB_Y[0], "v", r1, text=f"{fmt(d.TAB_Y[0] - d.OUT_Y0)} tab centre")
    v.dim(d.OUT_X1, d.TAB_Y[0], d.OUT_X1, d.TAB_Y[1], "v", r1)
    v.dim(d.W, 0, d.W, d.TAB_Y[0], "v", r2, fill=REF, text=f"{fmt(d.TAB_Y[0])} from PCB y = 0")
    v.dim(d.W, d.TAB_Y[0], d.W, d.TAB_Y[1], "v", r2, fill=REF)
    ty = d.TAB_Y[1]
    s = d.slots(ty)
    v.dim(d.LIP_X1, ty - d.TAB_W / 2, d.LIP_X1, ty + d.TAB_W / 2, "v", d.OUT_X1 + 2.5, at="in", text=f"{fmt(d.TAB_W)} tab")
    v.dim(d.LIP_X1, s[1][0], d.LIP_X1, s[1][1], "v", d.OUT_X1 + 2.5, at="p1", text=f"{fmt(d.SLOT)} slot")
    # --- along the bottom: the antenna axis and the PCB position ---
    b1, b2 = d.OUT_Y1 + 7.0, d.OUT_Y1 + 12.0
    v.dim(d.OUT_X0, d.OUT_Y1, d.SOCKET_MID_X, d.OUT_Y1, "u", b1, text=f"{fmt(d.SOCKET_MID_X - d.OUT_X0)} antenna axis")
    v.dim(d.OUT_X0, d.OUT_Y1, 0, d.H, "u", b2, at="p0", text=f"{fmt(0 - d.OUT_X0)} to the PCB edge")
    # --- leaders ---
    v.leader(d.OUT_X1 - 0.6, d.OUT_Y1 - 0.6, f"R{fmt(d.CORNER_R)} (4 corners)", 8, 6)
    v.leader(d.LIP_X0 + d.LIP_T / 2, 10.0, f"lip {fmt(d.LIP_T)} thick, {fmt(d.LIP_H)} tall", 8, 6)
    v.leader(d.W - d.HOLE_IN - 1.4, d.HOLE_IN + 1.4, f"standoff Ø{fmt(d.STANDOFF_D)}, peg Ø{fmt(d.PEG_D)} (4 places)", -8, 6)
    v.leader(d.LIP_X0 - d.BUMP_R, d.TAB_Y[0] - 2.5, f"tab {fmt(d.TAB_W)} wide x {fmt(d.TAB_H)} tall, bump R{fmt(d.BUMP_R)} (4 places)", 12, -8)
    sh.frame_and_title("bottom half", "Plan from above: cavity, standoffs and pegs, lip and snap tabs", "2:1", "1 of 6", COMMON_NOTES)
    sh.write(OUT / "case-bottom-plan.svg")


def top_plan() -> None:
    sh = Sheet(210, 252)
    k = 2.0
    v = View(sh, 53.0 + k * d.OUT_X1, 70.0, k, flip_u=True)  # x mirrored: the part turned over about its long axis
    sh.caption(4, 8, "TOP HALF, plan from below (turned over about its long axis, so +x runs to the LEFT), 2:1")
    sh.note(4, 13.5, "Dimensions stay in the PCB frame. The USB-C wall is on the right, the antenna wall at the bottom; hidden features dashed.")
    v.rect(d.OUT_X0, d.OUT_Y0, d.OUT_X1, d.OUT_Y1, rx=d.CORNER_R)
    xs0, xs1 = d.CAV_X0 - d.REBATE, d.CAV_X1 + d.REBATE  # the skirt's inner faces
    v.rect(xs0, d.CAV_Y0 - d.REBATE, xs1, d.CAV_Y1 + d.REBATE)
    v.rect(d.CAV_X0, d.CAV_Y0, d.CAV_X1, d.CAV_Y1, "thin")  # where the rebate's ceiling meets the cavity wall
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
    # USB-C window: in a vertical wall above the skirt's bottom face, so hidden
    v.rect(d.OUT_X0, d.USB_WIN_Y - d.USB_WIN_W / 2, d.CAV_X0, d.USB_WIN_Y + d.USB_WIN_W / 2, "hidden")
    v.centre_line(d.OUT_X0 - 2.0, d.USB_WIN_Y, d.CAV_X0 + 2.0, d.USB_WIN_Y)
    # antenna hole and E07 pocket, hidden
    v.rect(d.SOCKET_MID_X - d.ANT_HOLE_D / 2, d.CAV_Y1, d.SOCKET_MID_X + d.ANT_HOLE_D / 2, d.OUT_Y1, "hidden")
    v.rect(d.SOCKET_MID_X - d.E07_POCKET / 2, d.CAV_Y1, d.SOCKET_MID_X + d.E07_POCKET / 2, d.CAV_Y1 + d.E07_POCKET_DEPTH, "hidden")
    v.centre_line(d.SOCKET_MID_X, d.CAV_Y1 - 3.0, d.SOCKET_MID_X, d.OUT_Y1 + 3.0)
    # pry notch through the skirt at the near end
    v.rect(d.NOTCH_X0, d.OUT_Y0, d.NOTCH_X1, d.CAV_Y0 - d.REBATE, "thin")
    # the PCB for reference
    v.rect(0, 0, d.W, d.H, "ref")
    for hx, hy in d.HOLES:
        v.circle(hx, hy, d.HOLE_D / 2, "ref")
    v.label(d.W / 2, 26.0, "PCB (reference)", fill=REF, size=2.0)
    v.leader(0, 0, "PCB origin (0, 0)", -4, 11, fill=REF, size=2.0)
    # --- across the top: from the USB-C wall's outside face (on the right) ---
    t1, t2, t3, t4 = d.OUT_Y0 - 7.0, d.OUT_Y0 - 12.0, d.OUT_Y0 - 17.0, d.OUT_Y0 - 22.0
    v.dim(d.OUT_X0, d.OUT_Y0, d.OUT_X1, d.OUT_Y0, "u", t4)
    v.dim(d.OUT_X0, d.OUT_Y0, d.W / 2, d.OUT_Y0, "u", t3, text=f"{fmt(d.W / 2 - d.OUT_X0)} notch centre")
    v.dim(xs0, d.CAV_Y0, xs1, d.CAV_Y0, "u", t2, text=f"{fmt(xs1 - xs0)} between the skirt faces")
    v.dim(xs1, d.CAV_Y0, d.OUT_X1, d.OUT_Y0, "u", t2, at="p1", text=f"{fmt(d.SKIRT_T)} skirt")
    v.dim(d.OUT_X0, d.OUT_Y0, d.HOLE_IN, d.HOLE_IN, "u", t1, at="in")
    v.dim(d.HOLE_IN, d.HOLE_IN, d.W - d.HOLE_IN, d.HOLE_IN, "u", t1)
    v.dim(d.W - d.HOLE_IN, d.HOLE_IN, d.OUT_X1, d.OUT_Y0, "u", t1, at="p1")
    v.dim(d.NOTCH_X0, d.CAV_Y0 - d.REBATE, d.NOTCH_X1, d.CAV_Y0 - d.REBATE, "u", 15.0, at="in", text=f"{fmt(d.NOTCH_W)} notch, {fmt(d.NOTCH_DEPTH)} deep")
    # --- down the right (the USB-C wall): the window ---
    r1, r2 = d.OUT_X0 - 7.0, d.OUT_X0 - 12.5
    v.dim(d.OUT_X0, d.OUT_Y0, d.OUT_X0, d.OUT_Y1, "v", r2)
    v.dim(d.OUT_X0, d.OUT_Y0, d.OUT_X0, d.USB_WIN_Y, "v", r1, text=f"{fmt(d.USB_WIN_Y - d.OUT_Y0)} window centre")
    v.dim(d.OUT_X0, d.USB_WIN_Y - d.USB_WIN_W / 2, d.OUT_X0, d.USB_WIN_Y + d.USB_WIN_W / 2, "v", d.OUT_X0 - 2.5, at="in")
    # --- down the left: bosses and grooves from the near outside face ---
    l1, l2 = d.OUT_X1 + 7.0, d.OUT_X1 + 12.5
    v.dim(d.OUT_X1, d.OUT_Y0, d.W - d.HOLE_IN, d.HOLE_IN, "v", l1, at="in")
    v.dim(d.W - d.HOLE_IN, d.HOLE_IN, d.W - d.HOLE_IN, d.H - d.HOLE_IN, "v", l1)
    v.dim(d.W - d.HOLE_IN, d.H - d.HOLE_IN, d.OUT_X1, d.OUT_Y1, "v", l1, at="p1")
    v.dim(d.OUT_X1, d.OUT_Y0, d.OUT_X1, d.TAB_Y[0], "v", l2, text=f"{fmt(d.TAB_Y[0] - d.OUT_Y0)} groove centre")
    v.dim(d.OUT_X1, d.TAB_Y[0], d.OUT_X1, d.TAB_Y[1], "v", l2)
    gl = d.TAB_W + 2 * d.GROOVE_Y_OVER
    v.dim(xs1, d.TAB_Y[1] - gl / 2, xs1, d.TAB_Y[1] + gl / 2, "v", d.OUT_X1 + 2.5, at="in", text=f"{fmt(gl)} groove")
    # --- along the bottom: the antenna axis ---
    b1 = d.OUT_Y1 + 7.0
    v.dim(d.OUT_X0, d.OUT_Y1, d.SOCKET_MID_X, d.OUT_Y1, "u", b1, text=f"{fmt(d.SOCKET_MID_X - d.OUT_X0)} antenna axis")
    v.dim(d.SOCKET_MID_X, d.OUT_Y1, d.OUT_X1, d.OUT_Y1, "u", b1)
    # --- leaders ---
    sbx, sby, sbd, _ = d.BOSS_AT[2]
    v.leader(d.W - d.HOLE_IN - 1.5, d.HOLE_IN + 1.6, f"boss Ø{fmt(d.BOSS_D)}, bore Ø{fmt(d.BOSS_BORE_D)} (3 places)", 8, 12)
    v.leader(sbx - sbd / 2 * 0.7, sby + sbd / 2 * 0.7, [f"solid boss Ø{fmt(sbd)} at ({sbx:g}, {sby:g}):", f"{fmt(sbx - d.OUT_X0)} / {fmt(sby - d.OUT_Y0)} from the outside faces"], -10, 9)
    v.leader(d.OUT_X0 - 0.6, d.OUT_Y0 + 0.6, f"R{fmt(d.CORNER_R)} (4 corners)", -8, -5)
    v.leader(xs0, 56.0, f"rebate {fmt(d.REBATE)} deep, {fmt(d.SKIRT_H)} tall", -8, 6)
    v.leader(xs1 + d.GROOVE_R, d.TAB_Y[1] - 3.0, f"groove R{fmt(d.GROOVE_R)}, centre {fmt(d.BUMP_Z)} above the seam", 8, 8)
    v.leader(d.CAV_X0, d.USB_WIN_Y - 2.0, f"USB-C window {fmt(d.USB_WIN_W)} x {fmt(d.USB_WIN_H)}, hidden", -8, 12)
    v.leader(d.SOCKET_MID_X + d.ANT_HOLE_D / 2, d.OUT_Y1 - 0.8, f"Ø{fmt(d.ANT_HOLE_D)} hole (hidden)", -10, 5)
    v.leader(d.SOCKET_MID_X - d.E07_POCKET / 2, d.CAV_Y1 + d.E07_POCKET_DEPTH, f"pocket {fmt(d.E07_POCKET)} sq, {fmt(d.E07_POCKET_DEPTH)} deep (hidden)", 10, 3)
    v.label(d.W / 2, d.OUT_Y0, "pry notch", dy=-3.0, size=2.0)
    sh.frame_and_title("top half", "Plan from below: skirt and rebate, grooves, bosses, window, antenna hole", "2:1", "2 of 6", COMMON_NOTES)
    sh.write(OUT / "case-top-plan.svg")


def section_antenna() -> None:
    """Section A-A: the plane x = SOCKET_MID_X, both halves closed, viewed
    from +x, laid out like the plan: y runs down the sheet and z to the right."""
    sh = Sheet(210, 252)
    k = 2.0
    v = View(sh, 78.0, 66.0, k)  # u = z, v = y
    sh.caption(4, 8, f"SECTION A-A on the antenna axis (x = {d.SOCKET_MID_X:g}), case closed, viewed from +x, 2:1")
    sh.note(4, 13.5, "Laid out like the plan: y runs down the sheet, z to the right (floor on the left, ceiling on the right). Bottom half hatched 45°, top 135°;")
    sh.note(4, 17.5, "the standoffs and bosses at x = 2.4 / 2.2 lie behind the cut and are drawn unhatched; the PCB and the E07's SMA jack in green for reference.")
    reb = d.REBATE
    hz0, hz1 = d.ANT_Z - d.ANT_HOLE_D / 2, d.ANT_Z + d.ANT_HOLE_D / 2
    pk_y1, pk_z1 = d.CAV_Y1 + d.E07_POCKET_DEPTH, d.ANT_Z + d.E07_POCKET / 2
    zy = lambda pts: [(z, y) for y, z in pts]  # noqa: E731  the polygons are easier to write as (y, z)
    bottom = [
        (d.OUT_Y0, d.OUT_Z0), (d.OUT_Y1, d.OUT_Z0), (d.OUT_Y1, d.PART_Z), (d.CAV_Y1, d.PART_Z), (d.CAV_Y1, d.CAV_Z0),
        (d.CAV_Y0, d.CAV_Z0), (d.CAV_Y0, d.PART_Z + d.LIP_H), (d.LIP_Y0, d.PART_Z + d.LIP_H), (d.LIP_Y0, d.PART_Z), (d.OUT_Y0, d.PART_Z),
    ]
    v.section(zy(bottom), 45)
    top = [
        (d.OUT_Y0, d.OUT_Z1), (d.OUT_Y1, d.OUT_Z1), (d.OUT_Y1, hz1), (pk_y1, hz1), (pk_y1, pk_z1), (d.CAV_Y1, pk_z1), (d.CAV_Y1, d.CAV_Z1),
        (d.CAV_Y0, d.CAV_Z1), (d.CAV_Y0, d.PART_Z + d.SKIRT_H), (d.CAV_Y0 - reb, d.PART_Z + d.SKIRT_H), (d.CAV_Y0 - reb, d.PART_Z + d.NOTCH_DEPTH),
        (d.OUT_Y0, d.PART_Z + d.NOTCH_DEPTH),
    ]
    v.section(zy(top), 135)
    v.section(zy([(d.CAV_Y1 + reb, d.PART_Z), (d.OUT_Y1, d.PART_Z), (d.OUT_Y1, hz0), (d.CAV_Y1 + reb, hz0)]), 135)  # the wall under the hole
    # behind the cut: standoffs, pegs and bosses, and the PCB
    for hx, hy in (d.HOLES[0], d.HOLES[2]):
        v.rect(d.STANDOFF_Z0, hy - d.STANDOFF_D / 2, d.STANDOFF_Z1, hy + d.STANDOFF_D / 2, "thin")
        top_z = 0.0 if (hx, hy) == d.FLUSH_PEG else d.PEG_Z1
        r, ch = d.PEG_D / 2, d.PEG_CHAMFER
        v.poly(zy([(hy - r, d.STANDOFF_Z1), (hy - r, top_z - ch), (hy - r + ch, top_z), (hy + r - ch, top_z), (hy + r, top_z - ch), (hy + r, d.STANDOFF_Z1)]), "thin", close=False)
    for bx, by, dia, bored in (d.BOSS_AT[0], d.BOSS_AT[2]):
        v.rect(d.BOSS_Z0, by - dia / 2, d.BOSS_Z1, by + dia / 2, "thin")
        if bored:
            v.rect(d.BOSS_Z0, by - d.BOSS_BORE_D / 2, d.BOSS_Z0 + d.BOSS_BORE_DEPTH, by + d.BOSS_BORE_D / 2, "hidden")
    v.rect(-d.BOARD_T, 0, 0, d.H, "ref")
    v.label(-d.BOARD_T / 2, d.H / 2, "PCB (ref.)", fill=REF, size=1.9, angle=-90)
    jy0 = d.E07_JACK_Y1 - 3.0
    v.rect(d.ANT_Z - 3.2, jy0, d.ANT_Z + 3.2, d.E07_JACK_Y1, "ref")
    v.rect(d.ANT_Z - 6.35 / 2, d.E07_JACK_Y1, d.ANT_Z + 6.35 / 2, d.E07_JACK_Y1 + 6.5, "ref")
    v.label(d.ANT_Z, jy0 + 1.5, "E07 jack", fill=REF, size=1.8)
    v.centre_line(d.ANT_Z, d.CAV_Y1 - 4.0, d.ANT_Z, d.OUT_Y1 + 9.0)
    v.line(d.PART_Z, d.OUT_Y0 - 2.5, d.PART_Z, d.OUT_Y0 - 0.2, "centre")
    v.label(d.PART_Z, d.OUT_Y0 - 1.5, "seam", dx=-1.2, size=1.9, anchor="end")
    # --- across the top: heights (z) from the outside bottom face ---
    t1, t2, t3, t4 = d.OUT_Y0 - 4.0, d.OUT_Y0 - 8.5, d.OUT_Y0 - 13.0, d.OUT_Y0 - 17.5
    v.dim(d.OUT_Z0, d.OUT_Y0, d.OUT_Z1, d.OUT_Y0, "u", t4, text=f"{fmt(d.OUT_Z1 - d.OUT_Z0)} overall height")
    v.dim(d.OUT_Z0, d.OUT_Y0, d.PART_Z, d.OUT_Y0, "u", t3, at="in", text=f"{fmt(d.PART_Z - d.OUT_Z0)} bottom")
    v.dim(d.PART_Z, d.OUT_Y0, d.OUT_Z1, d.OUT_Y0, "u", t3, at="in", text=f"{fmt(d.OUT_Z1 - d.PART_Z)} top")
    v.dim(d.OUT_Z0, d.OUT_Y0, d.CAV_Z0, d.CAV_Y0, "u", t2, at="p0", text=f"{fmt(d.FLOOR)} floor")
    v.dim(d.CAV_Z0, d.CAV_Y0, d.PART_Z, d.CAV_Y0, "u", t2, at="in")
    v.dim(d.PART_Z, d.CAV_Y0, d.CAV_Z1, d.CAV_Y0, "u", t2, at="in")
    v.dim(d.CAV_Z1, d.CAV_Y0, d.OUT_Z1, d.OUT_Y0, "u", t2, at="p1", text=f"{fmt(d.TOP_T)} ceiling")
    v.dim(d.PART_Z, d.LIP_Y0, d.PART_Z + d.LIP_H, d.LIP_Y0, "u", t1, at="p1", text=f"{fmt(d.LIP_H)} lip")
    # --- down the left: lengths (y) from the y = 0 end ---
    c1, c2, c3, c4 = d.OUT_Z0 - 4.0, d.OUT_Z0 - 8.5, d.OUT_Z0 - 13.0, d.OUT_Z0 - 17.5
    v.dim(d.OUT_Z0, d.OUT_Y0, d.OUT_Z0, d.OUT_Y1, "v", c4)
    v.dim(d.OUT_Z0, d.OUT_Y0, d.CAV_Z0, d.CAV_Y0, "v", c3, at="p0", text=f"{fmt(d.WALL)} wall")
    v.dim(d.CAV_Z0, d.CAV_Y0, d.CAV_Z0, d.CAV_Y1, "v", c3, text=f"{fmt(d.CAV_Y1 - d.CAV_Y0)} cavity")
    v.dim(d.CAV_Z0, d.CAV_Y1, d.OUT_Z0, d.OUT_Y1, "v", c3, at="p1", text=f"{fmt(d.ANT_WALL_T)} antenna wall")
    v.dim(d.OUT_Z0, d.OUT_Y0, -d.BOARD_T, 0, "v", c2, at="p0", text=f"{fmt(0 - d.OUT_Y0)} to the PCB edge", fill=REF)
    v.dim(-d.BOARD_T, 0, -d.BOARD_T, d.H, "v", c2, text=f"{fmt(d.H)} PCB", fill=REF)
    v.dim(d.OUT_Z0, d.OUT_Y0, d.STANDOFF_Z0, d.HOLES[0][1], "v", c1, at="in", text=f"{fmt(d.HOLES[0][1] - d.OUT_Y0)}")
    v.dim(d.STANDOFF_Z0, d.HOLES[0][1], d.STANDOFF_Z0, d.HOLES[2][1], "v", c1, text=f"{fmt(d.HOLES[2][1] - d.HOLES[0][1])} standoff pitch")
    # --- along the bottom: the antenna hole's height ---
    b1, b2 = d.OUT_Y1 + 4.0, d.OUT_Y1 + 8.5
    v.dim(d.OUT_Z0, d.OUT_Y1, d.ANT_Z, d.OUT_Y1, "u", b2, text=f"{fmt(d.ANT_Z - d.OUT_Z0)} hole centre")
    v.dim(d.PART_Z, d.OUT_Y1, d.ANT_Z, d.OUT_Y1, "u", b1, at="p0", text=f"{fmt(d.ANT_Z - d.PART_Z)} above the seam")
    v.dim(hz1, d.OUT_Y1, d.OUT_Z1, d.OUT_Y1, "u", b1, at="p1", text=f"{fmt(d.OUT_Z1 - hz1)} above the hole")
    # --- on the right: leaders ---
    v.leader(hz1, d.OUT_Y1 - 1.0, f"Ø{fmt(d.ANT_HOLE_D)} hole, centre z = {d.ANT_Z:g}", 10, 2)
    v.leader(pk_z1, d.CAV_Y1 + 0.3, [f"pocket {fmt(d.E07_POCKET)} square, {fmt(d.E07_POCKET_DEPTH)} deep", f"(z {fmt(d.ANT_Z - d.E07_POCKET / 2)} to {fmt(pk_z1)})"], 10, -10)
    v.leader(d.BOSS_Z1 - 1.0, d.HOLES[0][1] + d.BOSS_D / 2, f"boss Ø{fmt(d.BOSS_D)}, {fmt(d.BOSS_GAP)} above the PCB", 10, 3)
    v.leader(d.PEG_Z1, d.HOLES[0][1] + 0.5, f"peg tip {fmt(d.PEG_Z1)} above the PCB", 22, 20)
    v.leader(d.STANDOFF_Z1 - 0.5, d.HOLES[2][1] + d.STANDOFF_D / 2, f"standoff {fmt(d.STANDOFF_Z1 - d.STANDOFF_Z0)} tall, Ø{fmt(d.STANDOFF_D)}", 30, 4)
    v.leader(d.BOSS_Z0 + 2.0, d.BOSS_AT[2][1] + 1.5, f"solid boss Ø{fmt(d.BOSS_AT[2][2])}", 30, 12)
    v.leader(d.PART_Z + d.NOTCH_DEPTH, d.CAV_Y0 - reb / 2, f"pry notch {fmt(d.NOTCH_DEPTH)} up from the seam", 22, -3)
    v.leader(d.PART_Z + d.SKIRT_H, d.CAV_Y0 - reb / 2, f"rebate {fmt(d.REBATE)} x {fmt(d.SKIRT_H)} (sheet 5)", 22, 3)
    v.leader(d.CAV_Z1, 20.0, f"{fmt(d.CAV_Z1)} PCB top to ceiling", 12, 4)
    sh.frame_and_title("both halves", "Section A-A on the antenna axis, closed: floor, seam, standoffs, hole and pocket", "2:1", "3 of 6", COMMON_NOTES)
    sh.write(OUT / "case-section-antenna.svg")


def end_elevations() -> None:
    sh = Sheet(210, 225)
    k = 2.0
    # (a) the USB-C wall from outside (-x): y runs to the LEFT, z up
    va = View(sh, 40.0 + k * d.OUT_Y1, 42.0 + k * d.OUT_Z1, k, flip_u=True, flip_v=True)
    sh.caption(4, 8, "USB-C WALL from outside (viewed from -x): the antenna end on the left, 2:1")
    va.rect(d.OUT_Y0, d.OUT_Z0, d.OUT_Y1, d.OUT_Z1)
    va.line(d.OUT_Y0, d.PART_Z, d.OUT_Y1, d.PART_Z, "thin")
    va.rect(d.USB_WIN_Y - d.USB_WIN_W / 2, d.USB_WIN_Z - d.USB_WIN_H / 2, d.USB_WIN_Y + d.USB_WIN_W / 2, d.USB_WIN_Z + d.USB_WIN_H / 2)
    va.centre_line(d.USB_WIN_Y, d.USB_WIN_Z - 6.0, d.USB_WIN_Y, d.USB_WIN_Z + 6.0)
    va.centre_line(d.USB_WIN_Y - 9.5, d.USB_WIN_Z, d.USB_WIN_Y + 9.5, d.USB_WIN_Z)
    for ty in d.TAB_Y:  # the tabs behind the skirt
        va.rect(ty - d.TAB_W / 2, d.PART_Z, ty + d.TAB_W / 2, d.PART_Z + d.TAB_H, "hidden")
    va.label(d.TAB_Y[1], d.PART_Z + d.TAB_H, "snap tabs behind the skirt (hidden)", dy=-2.4, size=1.9)
    va.label(d.OUT_Y1, d.PART_Z, "seam", dx=-2.0, size=1.9, anchor="end")
    va.label(d.OUT_Y0 - 0.5, d.OUT_Z0, "y = 0 end (J4)", dy=3.0, size=1.9, anchor="end")
    va.label(d.OUT_Y1 + 0.5, d.OUT_Z0, "antenna end", dy=3.0, size=1.9, anchor="start")
    va.dim(d.OUT_Y0, d.OUT_Z0, d.OUT_Y1, d.OUT_Z0, "u", d.OUT_Z0 - 4.5)
    va.dim(d.OUT_Y0, d.OUT_Z1, d.USB_WIN_Y, d.USB_WIN_Z + d.USB_WIN_H / 2, "u", d.OUT_Z1 + 7.5, text=f"{fmt(d.USB_WIN_Y - d.OUT_Y0)} window centre")
    va.dim(d.USB_WIN_Y - d.USB_WIN_W / 2, d.USB_WIN_Z + d.USB_WIN_H / 2, d.USB_WIN_Y + d.USB_WIN_W / 2, d.USB_WIN_Z + d.USB_WIN_H / 2, "u", d.OUT_Z1 + 3.0)
    va.dim(d.OUT_Y1, d.OUT_Z0, d.OUT_Y1, d.OUT_Z1, "v", d.OUT_Y1 + 3.0)
    va.dim(d.OUT_Y1, d.OUT_Z0, d.USB_WIN_Y + d.USB_WIN_W / 2, d.USB_WIN_Z, "v", d.OUT_Y1 + 7.5, text=f"{fmt(d.USB_WIN_Z - d.OUT_Z0)} window centre")
    va.dim(d.OUT_Y1, d.OUT_Z0, d.OUT_Y1, d.PART_Z, "v", d.OUT_Y1 + 12.0, at="in", text=f"{fmt(d.PART_Z - d.OUT_Z0)} seam")
    va.dim(d.USB_WIN_Y - d.USB_WIN_W / 2, d.USB_WIN_Z - d.USB_WIN_H / 2, d.USB_WIN_Y - d.USB_WIN_W / 2, d.USB_WIN_Z + d.USB_WIN_H / 2, "v", d.USB_WIN_Y - d.USB_WIN_W / 2 - 2.0, at="in")
    va.dim(d.OUT_Y0, d.PART_Z, d.USB_WIN_Y + d.USB_WIN_W / 2, d.USB_WIN_Z - d.USB_WIN_H / 2, "v", d.OUT_Y0 - 3.0, at="p1", text=f"{fmt(d.USB_WIN_Z - d.USB_WIN_H / 2 - d.PART_Z)} seam to sill")
    # (b) the antenna wall from outside (+y): x runs to the LEFT, z up
    vb = View(sh, 40.0 + k * d.OUT_X1, 140.0 + k * d.OUT_Z1, k, flip_u=True, flip_v=True)
    sh.caption(4, 108, "ANTENNA WALL from outside (viewed from +y): the USB-C wall on the right, 2:1")
    vb.rect(d.OUT_X0, d.OUT_Z0, d.OUT_X1, d.OUT_Z1)
    vb.line(d.OUT_X0, d.PART_Z, d.OUT_X1, d.PART_Z, "thin")
    vb.circle(d.SOCKET_MID_X, d.ANT_Z, d.ANT_HOLE_D / 2)
    vb.rect(d.SOCKET_MID_X - d.E07_POCKET / 2, d.ANT_Z - d.E07_POCKET / 2, d.SOCKET_MID_X + d.E07_POCKET / 2, d.ANT_Z + d.E07_POCKET / 2, "hidden")
    vb.centre_mark(d.SOCKET_MID_X, d.ANT_Z, d.ANT_HOLE_D / 2, over=3.0)
    vb.label(d.SOCKET_MID_X, d.ANT_Z + d.E07_POCKET / 2, f"pocket {fmt(d.E07_POCKET)} sq inside, hidden", dy=-2.2, size=1.8)
    vb.label(d.OUT_X1, d.PART_Z, "seam", dx=-2.0, size=1.9, anchor="end")
    vb.label(d.OUT_X0 - 0.5, d.OUT_Z0, "USB-C wall side", dy=3.0, size=1.9, anchor="end")
    vb.dim(d.OUT_X0, d.OUT_Z0, d.OUT_X1, d.OUT_Z0, "u", d.OUT_Z0 - 4.5)
    vb.dim(d.OUT_X0, d.OUT_Z1, d.SOCKET_MID_X, d.ANT_Z + d.ANT_HOLE_D / 2, "u", d.OUT_Z1 + 3.0, text=f"{fmt(d.SOCKET_MID_X - d.OUT_X0)} hole centre")
    vb.dim(d.SOCKET_MID_X, d.ANT_Z + d.ANT_HOLE_D / 2, d.OUT_X1, d.OUT_Z1, "u", d.OUT_Z1 + 3.0, text=f"{fmt(d.OUT_X1 - d.SOCKET_MID_X)}")
    vb.dim(d.OUT_X1, d.OUT_Z0, d.SOCKET_MID_X + d.ANT_HOLE_D / 2, d.ANT_Z, "v", d.OUT_X1 + 3.0, text=f"{fmt(d.ANT_Z - d.OUT_Z0)} hole centre")
    vb.dim(d.OUT_X1, d.PART_Z, d.SOCKET_MID_X + d.ANT_HOLE_D / 2, d.ANT_Z, "v", d.OUT_X1 + 8.0, at="p1", text=f"{fmt(d.ANT_Z - d.PART_Z)} above the seam")
    vb.leader(d.SOCKET_MID_X - d.ANT_HOLE_D / 2 * 0.7, d.ANT_Z - d.ANT_HOLE_D / 2 * 0.7, f"Ø{fmt(d.ANT_HOLE_D)} thru", 8, 9)
    sh.frame_and_title("top half", "End elevations from outside: the USB-C window and the antenna hole", "2:1", "4 of 6", COMMON_NOTES)
    sh.write(OUT / "case-end-elevations.svg")


def snap_detail() -> None:
    sh = Sheet(210, 222)
    k = 10.0
    xo, xl, xc = d.OUT_X0, d.LIP_X0, d.CAV_X0  # the left wall's outer face, the lip/tab's outer face, the cavity
    xs = d.CAV_X0 - d.REBATE  # the skirt's inner face
    bz = d.PART_Z + d.BUMP_Z
    z_lo, z_hi = d.PART_Z - 1.6, d.PART_Z + d.SKIRT_H + 1.6  # the shown range
    # (a) Section C-C through a tab, closed, 10:1, viewed from -y so x runs right
    v = View(sh, 50.0 - k * xo, 22.0 + k * z_hi, k, flip_v=True)
    sh.caption(4, 8, f"SECTION C-C: a snap tab (y = {d.TAB_Y[0]:g}), left wall, closed, 10:1")
    sh.note(4, 13.5, "Bottom half hatched 45°, top half 135°; the wall continues past the breaks to the floor and the ceiling.")
    v.section([(xo, z_lo), (xc, z_lo), (xc, d.PART_Z), (xo, d.PART_Z)], 45)
    bump = v.arc_pts(xl, bz, d.BUMP_R, 90, 270)  # over the top of the bump, round its outside, to its underside
    v.section([(xl, d.PART_Z)] + bump + [(xl, d.PART_Z + d.TAB_H), (xc, d.PART_Z + d.TAB_H), (xc, d.PART_Z)], 45)
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
    v.dim(xo, z_hi, xc, z_hi, "u", z_hi + 0.3, text=f"{fmt(d.WALL)} wall")
    v.dim(xs, d.PART_Z + d.SKIRT_H + 1.0, xc, d.PART_Z + d.SKIRT_H + 1.0, "u", d.PART_Z + d.SKIRT_H + 1.0, at="p1", text=f"{fmt(d.REBATE)} rebate")
    v.dim(xl, d.PART_Z + 2.6, xc, d.PART_Z + 2.6, "u", d.PART_Z + 2.6, at="in", text=f"{fmt(d.LIP_T)}")
    v.dim(xs, d.PART_Z + 2.0, xl, d.PART_Z + 2.0, "u", d.PART_Z + 2.0, at="p0", text=f"{fmt(d.FIT)} clearance")
    v.dim(xo, d.PART_Z + 1.0, xs, d.PART_Z + 1.0, "u", d.PART_Z + 1.0, at="in", text=f"{fmt(d.SKIRT_T)} skirt")
    v.dim(xo, z_lo, xc, z_lo, "u", z_lo - 0.3, text=f"{fmt(d.WALL)} wall")
    v.label(xl + d.LIP_T / 2, d.PART_Z + 3.4, "tab", size=1.9)
    # heights on the cavity side, from the seam
    c1, c2, c3 = xc + 0.55, xc + 1.15, xc + 1.75
    v.dim(xc, d.PART_Z, xc, d.PART_Z + d.TAB_H, "v", c1, text=f"{fmt(d.TAB_H)} tab")
    v.dim(xc, d.PART_Z, xc, d.PART_Z + d.SKIRT_H, "v", c2, text=f"{fmt(d.SKIRT_H)} rebate")
    v.dim(xl - d.BUMP_R, d.PART_Z, xl - d.BUMP_R, bz, "v", c3, text=f"{fmt(d.BUMP_Z)} bump and groove centre")
    v.leader(xl + d.LIP_T / 2, d.PART_Z + d.TAB_H + (d.SKIRT_H - d.TAB_H) / 2, f"{fmt(d.SKIRT_H - d.TAB_H)} over the tab", 8, -9)
    # the bump and groove, leaders to the outside
    v.leader(xs - d.GROOVE_R, bz, [f"groove R{fmt(d.GROOVE_R)} in the skirt,", "centred on its inner face"], -8, -16)
    v.dim(xs - d.GROOVE_R, bz - 1.0, xl - d.BUMP_R, bz - 1.0, "u", bz - 1.0, at="p0", text=f"{fmt(d.GROOVE_R - d.BUMP_PROUD)} to the groove bottom")
    v.leader(xl - d.BUMP_R, bz, [f"bump R{fmt(d.BUMP_R)} across the tab,", f"stands {fmt(d.BUMP_PROUD)} past the skirt face"], -8, 16)
    # (b) Section D-D through the plain lip, closed, 10:1
    vb = View(sh, 128.0 - k * xo, 22.0 + k * z_hi, k, flip_v=True)
    sh.caption(112, 8, "SECTION D-D: the plain lip (y = 44), 10:1")
    vb.section([(xo, z_lo), (xc, z_lo), (xc, d.PART_Z + d.LIP_H), (xl, d.PART_Z + d.LIP_H), (xl, d.PART_Z), (xo, d.PART_Z)], 45)
    vb.section([(xo, d.PART_Z), (xs, d.PART_Z), (xs, d.PART_Z + d.SKIRT_H), (xc, d.PART_Z + d.SKIRT_H), (xc, z_hi), (xo, z_hi)], 135)
    vb.break_line(xo, z_lo, xc, z_lo)
    vb.break_line(xo, z_hi, xc, z_hi)
    vb.line(xo, d.PART_Z, xo - 0.5, d.PART_Z, "centre")
    vb.label(xo - 0.5, d.PART_Z, "seam", dx=-1.0, size=2.0, anchor="end")
    vb.dim(xl, d.PART_Z + d.LIP_H, xc, d.PART_Z + d.LIP_H, "u", d.PART_Z + d.LIP_H + 0.5, at="p0", text=f"{fmt(d.LIP_T)} lip")
    vb.dim(xs, d.PART_Z + 0.7, xl, d.PART_Z + 0.7, "u", d.PART_Z + 0.7, at="p1", text=f"{fmt(d.FIT)}")
    vb.dim(xc, d.PART_Z, xc, d.PART_Z + d.LIP_H, "v", xc + 0.55, text=f"{fmt(d.LIP_H)} lip")
    vb.dim(xc, d.PART_Z + d.LIP_H, xc, d.PART_Z + d.SKIRT_H, "v", xc + 0.55, at="p1", text=f"{fmt(d.SKIRT_H - d.LIP_H)} above the lip")
    vb.dim(xo, z_hi, xc, z_hi, "u", z_hi + 0.3, text=f"{fmt(d.WALL)} wall")
    vb.dim(xo, d.PART_Z + 2.6, xs, d.PART_Z + 2.6, "u", d.PART_Z + 2.6, at="in", text=f"{fmt(d.SKIRT_T)} skirt")
    vb.label(xc, d.PART_Z + 4.5, "cavity", dx=2.5, size=2.0, anchor="start")
    vb.label(xo, d.PART_Z + 4.5, "outside", dx=-2.5, size=2.0, anchor="end")
    # (c) a tab from outside (viewed from -x), 5:1: y runs to the left, z up
    k3 = 5.0
    ty = d.TAB_Y[0]
    vc = View(sh, 100.0 + k3 * ty, 142.0 + k3 * d.TAB_H, k3, flip_u=True, flip_v=True)
    sh.caption(4, 132, f"A SNAP TAB from outside (viewed from -x, the left wall at y = {ty:g}), 5:1")
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
    vc.label(y0, d.PART_Z, "seam", dx=2.0, size=1.9, anchor="start")
    vc.dim(ty - d.TAB_W / 2, d.PART_Z + d.TAB_H, ty + d.TAB_W / 2, d.PART_Z + d.TAB_H, "u", d.PART_Z + d.TAB_H + 1.2, text=f"{fmt(d.TAB_W)} tab")
    vc.dim(s[0][0], d.PART_Z + d.LIP_H, s[0][1], d.PART_Z + d.LIP_H, "u", d.PART_Z + d.TAB_H + 1.2, at="p0", text=f"{fmt(d.SLOT)} slot (both sides)")
    vc.dim(ty - gl / 2, bz - d.GROOVE_R, ty + gl / 2, bz - d.GROOVE_R, "u", d.PART_Z - 1.0, at="in", text=f"{fmt(gl)} groove (hidden)")
    vc.dim(ty + d.TAB_W / 2, d.PART_Z, ty + d.TAB_W / 2, d.PART_Z + d.TAB_H, "v", ty + d.TAB_W / 2 + 3.0, text=f"{fmt(d.TAB_H)} tab")
    vc.dim(ty + d.TAB_W / 2, d.PART_Z, ty + d.TAB_W / 2, bz, "v", ty + d.TAB_W / 2 + 4.6, at="in", text=f"{fmt(d.BUMP_Z)}")
    vc.dim(y0, d.PART_Z, y0, d.PART_Z + d.LIP_H, "v", y0 - 0.8, at="p1", text=f"{fmt(d.LIP_H)} lip")
    notes = COMMON_NOTES[:4] + [
        f"Snap: a {d.LIP_T:g} x {d.TAB_H:g} PLA cantilever deflecting {d.BUMP_PROUD:g} mm (about 1 % strain); another material or wall changes the retention.",
        "A living hinge or side-action tab changes only this sheet: the lip, rebate and clearance stay as drawn.",
    ]
    sh.frame_and_title("both halves", "Snap joint: lip and rebate, tab, bump and groove, engagement", "10:1 and 5:1", "5 of 6", notes)
    sh.write(OUT / "case-snap-detail.svg")


def peg_detail() -> None:
    sh = Sheet(210, 196)
    k = 5.0
    r_s, r_p, r_b, r_bore = d.STANDOFF_D / 2, d.PEG_D / 2, d.BOSS_D / 2, d.BOSS_BORE_D / 2
    ch = d.PEG_CHAMFER
    # (a) Section B-B (x = 2.4) at H1: the standoff, peg, PCB and bored boss; y runs right, z up
    hx, hy = d.HOLES[0]
    y_lo, y_hi = hy - 5.0, hy + 5.0
    v = View(sh, 60.0 - k * y_lo, 24.0 + k * d.OUT_Z1, k, flip_v=True)
    sh.caption(4, 8, f"SECTION B-B (x = {hx:g}) at hole H1: standoff, peg, PCB, boss, 5:1")
    sh.note(4, 13.5, "Bottom half hatched 45°, top half 135°, PCB green (reference). Heights at the left run from the outside bottom face.", size=1.9)
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
    for a, b in ((y_lo, hy - d.HOLE_D / 2), (hy + d.HOLE_D / 2, y_hi)):
        v.rect(a, -d.BOARD_T, b, 0, "ref")
    v.label(hy + 3.7, -d.BOARD_T / 2, "PCB", fill=REF, size=1.9)
    v.centre_line(hy, d.OUT_Z0 - 1.5, hy, d.OUT_Z1 + 1.5)
    v.line(y_hi + 0.2, d.PART_Z, y_hi + 1.2, d.PART_Z, "centre")
    v.label(y_hi + 1.3, d.PART_Z, "seam", dx=1.0, size=1.9, anchor="start")
    # the stack from the outside bottom face, on the left
    xl = y_lo - 1.0
    for z, s in ((d.CAV_Z0, "floor top"), (d.STANDOFF_Z1, "standoff top"), (0.0, "PCB top"), (d.PEG_Z1, "peg tip"), (d.BOSS_Z0, "boss face"), (d.CAV_Z1, "ceiling"), (d.OUT_Z1, "top face")):
        v.dim(y_lo, d.OUT_Z0, y_lo, z, "v", xl, text=f"{fmt(z - d.OUT_Z0)} {s}")
        xl -= 1.0
    # the local sizes, on the right
    xr = y_hi + 1.6
    v.dim(y_hi, d.OUT_Z0, y_hi, d.CAV_Z0, "v", xr, at="p0", text=f"{fmt(d.FLOOR)} floor")
    v.dim(hy + r_s, d.STANDOFF_Z0, hy + r_s, d.STANDOFF_Z1, "v", xr, text=f"{fmt(d.STANDOFF_Z1 - d.STANDOFF_Z0)} standoff")
    v.dim(hy + r_p, d.STANDOFF_Z1, hy + r_p, d.PEG_Z1, "v", xr, at="p1", text=f"{fmt(d.PEG_H)} peg")
    v.dim(hy + r_b, d.BOSS_Z0, hy + r_b, d.CAV_Z1, "v", xr, text=f"{fmt(d.BOSS_Z1 - d.BOSS_Z0)} boss")
    v.dim(y_hi, d.CAV_Z1, y_hi, d.OUT_Z1, "v", xr, at="in", text=f"{fmt(d.TOP_T)}")
    v.dim(hy + r_bore, d.BOSS_Z0, hy + r_bore, d.BOSS_Z0 + d.BOSS_BORE_DEPTH, "v", xr + 2.4, at="in", text=f"{fmt(d.BOSS_BORE_DEPTH)} bore")
    v.dim(hy + d.HOLE_D / 2, -d.BOARD_T, hy + d.HOLE_D / 2, 0, "v", xr + 2.4, at="p0", text=f"{fmt(d.BOARD_T)} PCB", fill=REF)
    v.dim(hy - r_p, 0, hy - r_p, d.PEG_Z1, "v", hy - r_p - 0.5, at="p1", text=f"{fmt(d.PEG_Z1)} proud")
    v.dim(hy - r_b, 0, hy - r_b, d.BOSS_Z0, "v", hy - r_b - 0.5, at="p0", text=f"{fmt(d.BOSS_GAP)} gap")
    # diameters
    v.dim(hy - r_s, d.CAV_Z0, hy + r_s, d.CAV_Z0, "u", d.OUT_Z0 - 1.0, text=f"Ø{fmt(d.STANDOFF_D)} standoff")
    v.dim(hy - r_p, d.STANDOFF_Z1, hy + r_p, d.STANDOFF_Z1, "u", d.STANDOFF_Z1 - 3.0, text=f"Ø{fmt(d.PEG_D)} peg")
    v.dim(hy - d.HOLE_D / 2, 0, hy + d.HOLE_D / 2, 0, "u", d.PEG_Z1 + 0.8, at="p1", text=f"Ø{fmt(d.HOLE_D)} hole", fill=REF)
    v.dim(hy - r_bore, d.BOSS_Z0 + d.BOSS_BORE_DEPTH, hy + r_bore, d.BOSS_Z0 + d.BOSS_BORE_DEPTH, "u", d.BOSS_Z0 + d.BOSS_BORE_DEPTH + 2.8, at="p1", text=f"Ø{fmt(d.BOSS_BORE_D)} bore")
    v.dim(hy - r_b, d.CAV_Z1, hy + r_b, d.CAV_Z1, "u", d.OUT_Z1 + 1.0, text=f"Ø{fmt(d.BOSS_D)} boss")
    v.leader(hy + r_p - ch / 2, d.PEG_Z1 - ch / 2, f"chamfer {fmt(ch)} x 45°", 4, 14, size=2.3)
    # (b) the flush peg at H3 with the solid boss beside it, the same section plane, 5:1
    fx, fy = d.FLUSH_PEG
    sbx, sby, sbd, _ = d.BOSS_AT[2]
    y_lo2, y_hi2 = fy - 4.0, fy + 4.5
    vb = View(sh, 150.0 - k * y_lo2, 24.0 + k * d.OUT_Z1, k, flip_v=True)
    sh.caption(122, 8, f"Section B-B at hole H3 ({fx:g}, {fy:g}): flush peg, 5:1")
    sh.note(122, 13.5, f"The solid boss beside it is centred at ({sbx:g}, {sby:g}), 0.2 off the plane.", size=1.9)
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
        vb.rect(a, -d.BOARD_T, b, 0, "ref")
    vb.centre_line(fy, d.OUT_Z0 - 1.5, fy, d.OUT_Z1 + 1.5)
    vb.centre_line(sby, d.BOSS_Z0 - 2.0, sby, d.OUT_Z1 + 1.5)
    vb.dim(fy + r_p, d.STANDOFF_Z1, fy + r_p, 0.0, "v", y_hi2 + 1.2, at="in", text=f"{fmt(d.BOARD_T)} peg")
    vb.dim(fy, d.OUT_Z1 + 0.6, sby, d.OUT_Z1 + 0.6, "u", d.OUT_Z1 + 1.0, at="p1", text=f"{fmt(sby - fy)} boss offset")
    vb.dim(sby - sbd / 2, d.BOSS_Z0 + 3.0, sby + sbd / 2, d.BOSS_Z0 + 3.0, "u", d.BOSS_Z0 + 3.0, at="p0", text=f"Ø{fmt(sbd)} solid boss")
    vb.dim(sby + sbd / 2, 0, sby + sbd / 2, d.BOSS_Z0, "v", sby + sbd / 2 + 0.5, at="p0", text=f"{fmt(d.BOSS_GAP)} gap")
    vb.dim(fy - r_p, d.STANDOFF_Z1, fy + r_p, d.STANDOFF_Z1, "u", d.STANDOFF_Z1 - 3.0, text=f"Ø{fmt(d.PEG_D)} peg")
    vb.dim(y_lo2, d.OUT_Z0, y_lo2, 0.0, "v", y_lo2 - 1.0, text=f"{fmt(0.0 - d.OUT_Z0)} peg tip = PCB top")
    vb.label(fy + 0.25, d.OUT_Z0 - 2.6, "the peg stops at the PCB top: a jumper cap on JP1", size=1.8)
    vb.label(fy + 0.25, d.OUT_Z0 - 2.6, "and the Ra-02 breakout's overhang sit above it", dy=2.3, size=1.8)
    vb.label(fy + 0.25, d.OUT_Z0 - 2.6, f"(standoff Ø{fmt(d.STANDOFF_D)} and floor as at H1)", dy=4.6, size=1.8)
    notes = COMMON_NOTES[:3] + [COMMON_NOTES[4], "Bosses on 2 mm plates: core them or thin to ~60 % of the plate for moulding; machine the Ø2.6 bore with a flat end mill.", COMMON_NOTES[5]]
    sh.frame_and_title("both halves", "Peg, PCB and boss stack at H1 and at the flush peg H3", "5:1", "6 of 6", notes)
    sh.write(OUT / "case-peg-detail.svg")


SHEETS = [bottom_plan, top_plan, section_antenna, end_elevations, snap_detail, peg_detail]


# ---------------------------------------------------------------------------
# --check: measure the solids against the numbers on the sheets
# ---------------------------------------------------------------------------
def check() -> int:
    try:
        import cadquery  # noqa: F401
    except ImportError:
        print("re-running under uv with CadQuery", file=sys.stderr)
        os.execvp("uv", ["uv", "run", "--with", "cadquery>=2.4", __file__, "--check"])
    import build_case as bc
    from build_3d import box

    bottom, top = bc.build_bottom(), bc.build_top()
    rows: list[tuple[str, float, float, float]] = []

    def bb(shape):
        b = shape.val().BoundingBox()
        return {"x": (b.xmin, b.xmax), "y": (-b.ymax, -b.ymin), "z": (b.zmin, b.zmax)}  # board frame: y = -model y

    def spans(shape, axis, x0, y0, x1, y1, z0, z1):
        """The intervals of solid material along `axis` inside a probe box (board frame)."""
        hit = shape.intersect(box(x0, y0, x1, y1, z0, z1))
        out = [bb(hit.newObject([s]))[axis] for s in hit.solids().vals()]
        return sorted(out)

    def rod(shape, axis, u, w, lo=-30.0, hi=80.0, t=0.05):
        """A thin rod along `axis` through the point with the other two coordinates (u, w) in x, y, z order."""
        if axis == "x":
            return spans(shape, axis, lo, u - t, hi, u + t, w - t, w + t)
        if axis == "y":
            return spans(shape, axis, u - t, lo, u + t, hi, w - t, w + t)
        return spans(shape, axis, u - t, w - t, u + t, w + t, lo, hi)

    def gap(sp, i=0):
        return sp[i + 1][0] - sp[i][1]

    def row(name, expected, measured, tol=0.02):
        rows.append((name, expected, measured, tol))

    b, t = bb(bottom), bb(top)
    row("bottom: outside x", d.OUT_X1 - d.OUT_X0, b["x"][1] - b["x"][0])
    row("bottom: outside y", d.OUT_Y1 - d.OUT_Y0, b["y"][1] - b["y"][0])
    row("bottom: lowest z (outside bottom face)", d.OUT_Z0, b["z"][0])
    row("bottom: highest z (tab tips)", d.PART_Z + d.TAB_H, b["z"][1])
    row("top: outside x", d.OUT_X1 - d.OUT_X0, t["x"][1] - t["x"][0])
    row("top: outside y", d.OUT_Y1 - d.OUT_Y0, t["y"][1] - t["y"][0])
    row("top: lowest z (skirt bottom = seam)", d.PART_Z, t["z"][0])
    row("top: highest z (outside top face)", d.OUT_Z1, t["z"][1])
    row("closed: overall height", d.OUT_Z1 - d.OUT_Z0, t["z"][1] - b["z"][0])
    row("bottom: height of the wall to the seam", d.PART_Z - d.OUT_Z0, rod(bottom, "z", -3.9, 40.0)[0][1] - d.OUT_Z0)
    s = rod(top, "x", 40.0, 7.5)  # through both long walls at y = 40, above the rebate
    row("top: wall thickness", d.WALL, s[0][1] - s[0][0])
    row("top: cavity width", d.CAV_X1 - d.CAV_X0, gap(s))
    s = rod(bottom, "y", 12.0, -4.0)  # through the end walls under the seam
    row("bottom: near wall thickness", d.WALL, s[0][1] - s[0][0])
    row("bottom: antenna wall thickness", d.ANT_WALL_T, s[-1][1] - s[-1][0])
    row("bottom: cavity length", d.CAV_Y1 - d.CAV_Y0, gap(s))
    s = rod(bottom, "z", 12.0, 20.0)
    row("bottom: floor thickness", d.FLOOR, s[0][1] - s[0][0])
    s = rod(top, "z", 12.0, 20.0)
    row("top: ceiling thickness", d.TOP_T, s[-1][1] - s[-1][0])
    hx, hy = d.HOLES[0]
    s = rod(bottom, "z", hx + 1.5, hy)
    row("standoff: top (PCB underside)", d.STANDOFF_Z1, s[0][1])
    row("standoff: height above the floor", d.STANDOFF_Z1 - d.STANDOFF_Z0, s[0][1] - d.CAV_Z0)
    s = spans(bottom, "x", hx - 3, hy - 0.05, hx + 3, hy + 0.05, -4.0, -3.9)
    row("standoff: diameter", d.STANDOFF_D, s[0][1] - s[0][0])
    row("peg: tip height (H1)", d.PEG_Z1, rod(bottom, "z", hx, hy)[0][1])
    row("peg: tip height (H3, flush)", 0.0, rod(bottom, "z", *d.FLUSH_PEG)[0][1])
    s = spans(bottom, "x", hx - 3, hy - 0.05, hx + 3, hy + 0.05, -1.0, -0.9)
    row("peg: diameter", d.PEG_D, s[0][1] - s[0][0])
    s = spans(bottom, "x", hx - 3, hy - 0.05, hx + 3, hy + 0.05, d.PEG_Z1 - 0.25, d.PEG_Z1 - 0.15)  # in the chamfer, 0.25 below the tip
    row("peg: diameter 0.25 below the tip (chamfer 0.40 x 45)", d.PEG_D - 2 * (d.PEG_CHAMFER - 0.25), s[0][1] - s[0][0])
    s = rod(top, "z", hx + 1.75, hy)
    row("boss: face above the PCB (H1)", d.BOSS_Z0, s[0][0])
    row("boss: length", d.BOSS_Z1 - d.BOSS_Z0, d.CAV_Z1 - s[0][0])
    row("boss: bore depth (H1)", d.BOSS_BORE_DEPTH, rod(top, "z", hx, hy)[0][0] - d.BOSS_Z0)
    s = spans(top, "x", hx - 3, hy - 0.05, hx + 3, hy + 0.05, 1.0, 1.1)  # through the bored part of the boss
    row("boss: diameter", d.BOSS_D, s[-1][1] - s[0][0])
    row("boss: bore diameter", d.BOSS_BORE_D, gap(s))
    sbx, sby, sbd, _ = d.BOSS_AT[2]
    s = spans(top, "x", sbx - 3, sby - 0.05, sbx + 3, sby + 0.05, 5.0, 5.1)
    row("solid boss: diameter", sbd, s[0][1] - s[0][0])
    row("solid boss: face above the PCB", d.BOSS_Z0, rod(top, "z", sbx, sby)[0][0])
    s = spans(top, "x", 0, 62.5, 25, 63.5, d.ANT_Z - 0.05, d.ANT_Z + 0.05)
    row("antenna hole: diameter (x)", d.ANT_HOLE_D, gap(s))
    row("antenna hole: centre x", d.SOCKET_MID_X, (s[0][1] + s[1][0]) / 2)
    s = spans(top, "z", d.SOCKET_MID_X - 0.05, 62.5, d.SOCKET_MID_X + 0.05, 63.5, -5, 15)
    row("antenna hole: diameter (z)", d.ANT_HOLE_D, gap(s))
    row("antenna hole: centre z", d.ANT_Z, (s[0][1] + s[1][0]) / 2)
    s = rod(top, "y", d.SOCKET_MID_X, d.ANT_Z + d.ANT_HOLE_D / 2 + 0.2, lo=55, hi=70)  # just above the hole: the pocket's back
    row("E07 pocket: depth into the wall", d.E07_POCKET_DEPTH, s[0][0] - d.CAV_Y1)
    s = spans(top, "x", 0, d.CAV_Y1 + 0.3, 25, d.CAV_Y1 + 0.4, d.ANT_Z + d.ANT_HOLE_D / 2 + 0.15, d.ANT_Z + d.ANT_HOLE_D / 2 + 0.25)
    row("E07 pocket: width", d.E07_POCKET, gap(s))
    s = rod(top, "z", -3.5, d.USB_WIN_Y)
    row("USB-C window: height", d.USB_WIN_H, gap(s))
    row("USB-C window: centre z", d.USB_WIN_Z, (s[0][1] + s[1][0]) / 2)
    s = rod(top, "y", -3.5, d.USB_WIN_Z)
    row("USB-C window: width", d.USB_WIN_W, gap(s))
    row("USB-C window: centre y", d.USB_WIN_Y, (s[0][1] + s[1][0]) / 2)
    row("lip: height above the seam", d.LIP_H, rod(bottom, "z", -2.7, 41.0)[0][1] - d.PART_Z)
    s = rod(bottom, "x", 41.0, 0.5)
    row("lip: thickness", d.LIP_T, s[0][1] - s[0][0])
    row("lip: outer face x", d.LIP_X0, s[0][0])
    row("tab: height above the seam", d.TAB_H, rod(bottom, "z", -2.7, d.TAB_Y[0])[0][1] - d.PART_Z)
    s = rod(bottom, "x", d.TAB_Y[0], d.PART_Z + d.BUMP_Z)
    row("tab: outer face at the bump (lip face - bump R)", d.LIP_X0 - d.BUMP_R, s[0][0])
    row("tab: thickness at the bump", d.LIP_T + d.BUMP_R, s[0][1] - s[0][0])
    s = rod(bottom, "y", -2.7, 3.0)  # above the lip: only the tabs
    row("tab: count on the left wall", len(d.TAB_Y), len(s))
    row("tab: width (first tab)", d.TAB_W, s[0][1] - s[0][0])
    row("tab: centre y (first)", d.TAB_Y[0], (s[0][0] + s[0][1]) / 2)
    row("tab: centre y (second)", d.TAB_Y[1], (s[1][0] + s[1][1]) / 2)
    s = rod(bottom, "y", -2.7, 0.5)  # through the lip: the slots either side of the first tab
    i = next(i for i, (a, b_) in enumerate(s) if abs((a + b_) / 2 - d.TAB_Y[0]) < 0.1)
    row("slot: width before the first tab", d.SLOT, gap(s, i - 1))
    row("slot: width after the first tab", d.SLOT, gap(s, i))
    s = rod(top, "x", 41.0, 3.0)
    row("skirt: thickness", d.SKIRT_T, s[0][1] - s[0][0])
    row("skirt: inner face x (rebate)", d.CAV_X0 - d.REBATE, s[0][1])
    row("rebate: height above the seam", d.SKIRT_H, rod(top, "z", -2.8, 41.0)[0][0] - d.PART_Z)
    s = rod(top, "x", d.TAB_Y[0], d.PART_Z + d.BUMP_Z, t=0.01)
    row("groove: bottom x (skirt face - groove R)", d.CAV_X0 - d.REBATE - d.GROOVE_R, s[0][1])
    s = rod(top, "y", d.CAV_X0 - d.REBATE - 0.25, d.PART_Z + d.BUMP_Z)  # just inside the skirt face: the grooves and the window
    gaps = [(s[i][1], s[i + 1][0]) for i in range(len(s) - 1)]
    g = next(g for g in gaps if abs((g[0] + g[1]) / 2 - d.TAB_Y[0]) < 0.1)
    row("groove: length", d.TAB_W + 2 * d.GROOVE_Y_OVER, g[1] - g[0])
    row("groove: centre y (first)", d.TAB_Y[0], (g[0] + g[1]) / 2)
    row("groove: centre y (second)", d.TAB_Y[1], next((a + b_) / 2 for a, b_ in gaps if abs((a + b_) / 2 - d.TAB_Y[1]) < 0.1))
    s = rod(top, "z", d.W / 2, -2.0)
    row("pry notch: depth above the seam", d.NOTCH_DEPTH, s[0][0] - d.PART_Z)
    s = rod(top, "x", -2.0, 0.0)
    row("pry notch: width", d.NOTCH_W, gap(s))
    s = spans(bottom, "x", -10, d.OUT_Y0 + 0.2, 0, d.OUT_Y0 + 0.3, -5.05, -4.95)  # 0.2 to 0.3 in from the end face, where the R2 corner pulls the wall in
    row("corner: R2 (wall face x, 0.3 in from the end face)", d.OUT_X0 + d.CORNER_R - math.sqrt(d.CORNER_R**2 - (d.CORNER_R - 0.3) ** 2), s[0][0])

    bad = 0
    print(f"{'dimension':58s} {'expected':>9s} {'measured':>9s} {'diff':>7s}")
    for name, exp, meas, tol in rows:
        ok = abs(exp - meas) <= tol
        bad += not ok
        print(f"{name:58s} {exp:9.3f} {meas:9.3f} {meas - exp:+7.3f}{'' if ok else '  MISMATCH'}")
    print(f"{len(rows)} dimensions checked against the solids, {bad} mismatch(es)")
    return 1 if bad else 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="rebuild the solids with CadQuery and measure the quoted dimensions on them")
    args = ap.parse_args()
    if args.check:
        sys.exit(check())
    OUT.mkdir(parents=True, exist_ok=True)
    for sheet in SHEETS:
        sheet()


if __name__ == "__main__":
    main()

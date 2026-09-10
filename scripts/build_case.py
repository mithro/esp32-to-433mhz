#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["cadquery>=2.4"]
# ///
"""Build a 3D-printable case for the socket adapter with either radio in it.

Two halves that snap together, printed without supports (each open side
up).  Dimensions come from the adapter generator and from the assembly
table in docs/3d-models.md; everything is in the adapter's board frame (x
right, y down, origin at the board's top-left corner) with z up from the
board's top surface, converted to KiCad's model frame on export.

  bottom  floor and the walls up to the parting line, 0.5 mm below the
          board's top surface; four standoffs under the adapter's corner
          holes, each with a chamfered 2.15 mm peg that the board's 2.2 mm
          hole presses onto (no screws); round the top a 0.8 mm lip that
          locates the other half, and on each long wall two 6 mm cantilever
          snap tabs with a rounded bump near the tip.
  top     the rest of the walls and the ceiling; its skirt is rebated to sit
          over the lip and has grooves the bumps click into; four bosses come
          down to 0.2 mm above the board, so it cannot lift off the pegs
          once the halves are snapped shut; a window in the
          left wall for the SuperMini's USB-C plug; a 6.6 mm hole in the far
          wall on the antenna axis, which takes the E07-M1101D's SMA jack
          through it or clamps the Ra-02's U.FL-to-SMA bulkhead pigtail by
          its nut, with a shallow pocket inside for the E07 jack's square
          body; a notch at the parting line to lever the halves apart.

Written as hardware/3d/esp32c3-radio-adapter-case-{bottom,top}.step (KiCad
models with their origin at mounting hole H1, so the adapter's 3D view and
the assembly renders can show the case) and as hardware/case/*.stl for
printing.
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys

import cadquery as cq

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import generate_adapters as ga  # noqa: E402
from build_3d import box, cyl, save  # noqa: E402
# Every dimension is a named constant in case_dims.py (pure Python), shared
# with draw_case.py and export_case.py; the derived values (REBATE, PEG_Z1,
# the window centre, ...) are computed there, once, and used here as they are.
from case_dims import (  # noqa: E402
    ANT_HOLE_D, ANT_HOLE_Z1, ANT_WALL_T, ANT_WALL_Y0, ANT_Z, BOARD_T, BOSS_AT, BOSS_BORE_D,
    BOSS_BORE_DEPTH, BOSS_GAP, BOSS_Z0, BOSS_Z1, BUMP_PROUD, BUMP_R, BUMP_Z, CAV_X0, CAV_X1,
    CAV_Y0, CAV_Y1, CAV_Z0, CAV_Z1, CORNER_R, E07_BARREL_LEN, E07_JACK_BODY, E07_JACK_LEN,
    E07_JACK_Y1, E07_POCKET, E07_POCKET_DEPTH, FLOOR, FLUSH_PEG, GROOVE_R, GROOVE_Y_OVER, H,
    HIGHEST, HOLES, HOLE_D, HOLE_IN, LIP_GAP_X0, LIP_GAP_X1, LIP_H, LIP_T, LIP_X0, LIP_X1, LIP_Y1,
    NOTCH_DEPTH, NOTCH_W, NOTCH_X, NOTCH_X0, NOTCH_X1, OUT_X0, OUT_X1, OUT_Y0, OUT_Y1, OUT_Z0,
    OUT_Z1, PART_Z, PEG_CHAMFER, PEG_D, PEG_H, PEG_Z1, PIGTAIL_BARREL_LEN, PIGTAIL_FLANGE_T,
    PIGTAIL_HEX_AF, PIGTAIL_NUT_T, PIN_TIPS, POCKET_Z0, POCKET_Z1, REBATE, SKIRT_H, SKIRT_T, SLOT,
    SMA_BARREL_D, SOCKET_MID_X, SOLID_BOSS, STANDOFF_D, STANDOFF_Z0, STANDOFF_Z1, TAB_H, TAB_W,
    TAB_Y, TOP_T, USB_WIN_H, USB_WIN_W, USB_WIN_Y, USB_WIN_Z, USB_X0, USB_Y0, USB_Y1, USB_Z0,
    USB_Z1, W, WALL, slots,
)

ROOT = pathlib.Path(__file__).resolve().parent.parent
MEASURED = ROOT / "hardware" / "case" / "esp32c3-radio-adapter-case-measured.json"
STL_OUT = ROOT / "hardware" / "case"
# Two shades of the same light filament, so the seam and which half a feature
# belongs to read in the renders: the top half a touch darker and warmer.
CASE_BOTTOM, CASE_TOP = cq.Color(0.86, 0.86, 0.82), cq.Color(0.76, 0.73, 0.67)



def rounded_box(x0: float, y0: float, x1: float, y1: float, z0: float, z1: float, r: float) -> cq.Workplane:
    return box(x0, y0, x1, y1, z0, z1).edges("|Z").fillet(r)


def ring(inset: float, z0: float, z1: float) -> cq.Workplane:
    """The band of wall between the cavity boundary and `inset` outside it."""
    return box(CAV_X0 - inset, CAV_Y0 - inset, CAV_X1 + inset, CAV_Y1 + inset, z0, z1).cut(box(CAV_X0, CAV_Y0, CAV_X1, CAV_Y1, z0 - 1, z1 + 1))


def along_y_at(profile: cq.Workplane, x: float, y0: float, length: float, z: float) -> cq.Workplane:
    """A 2D profile on the XZ workplane extruded along board +y from y0 (the
    XZ workplane's normal is model -Y, i.e. board +y)."""
    return profile.extrude(length).translate((x, -y0, z))


def build_bottom() -> cq.Workplane:
    b = rounded_box(OUT_X0, OUT_Y0, OUT_X1, OUT_Y1, OUT_Z0, PART_Z, CORNER_R)
    b = b.cut(box(CAV_X0, CAV_Y0, CAV_X1, CAV_Y1, CAV_Z0, PART_Z + 1))
    # Standoffs under the corner holes, each with a press-fit peg.
    for hx, hy in HOLES:
        b = b.union(cyl(hx, hy, STANDOFF_D / 2, STANDOFF_Z0, STANDOFF_Z1))
        top_z = 0.0 if (hx, hy) == FLUSH_PEG else PEG_Z1
        peg = cyl(hx, hy, PEG_D / 2, STANDOFF_Z1 - 0.1, top_z).faces(">Z").chamfer(PEG_CHAMFER)
        b = b.union(peg)
    # The lip, gapped where the antenna connectors pass through the far
    # wall (the E07's jack body and the pigtail's flange sit right on the
    # parting line there), and the snap tabs cut free of it.
    lip = ring(LIP_T, PART_Z, PART_Z + LIP_H)
    lip = lip.cut(box(LIP_GAP_X0, CAV_Y1 - 0.1, LIP_GAP_X1, LIP_Y1 + 0.1, PART_Z - 0.1, PART_Z + LIP_H + 0.1))
    for ty in TAB_Y:
        for x_in, side in ((CAV_X0, -1), (CAV_X1, +1)):  # left wall (tab faces -x), right wall (+x)
            x_out = x_in + side * LIP_T
            tab = box(min(x_in, x_out), ty - TAB_W / 2, max(x_in, x_out), ty + TAB_W / 2, PART_Z, PART_Z + TAB_H)
            bump = along_y_at(cq.Workplane("XZ").circle(BUMP_R), x_out, ty - TAB_W / 2, TAB_W, PART_Z + BUMP_Z)
            tab = tab.union(bump).cut(box(CAV_X0, CAV_Y0, CAV_X1, CAV_Y1, PART_Z - 1, PART_Z + TAB_H + 1))  # nothing inside the cavity
            for sy0, sy1 in slots(ty):
                lip = lip.cut(box(min(x_in, x_out) - 0.1, sy0, max(x_in, x_out) + 0.1, sy1, PART_Z - 0.1, PART_Z + LIP_H + 1))
            lip = lip.union(tab)
    return b.union(lip)


def build_top() -> cq.Workplane:
    b = rounded_box(OUT_X0, OUT_Y0, OUT_X1, OUT_Y1, PART_Z, OUT_Z1, CORNER_R)
    b = b.cut(box(CAV_X0, CAV_Y0, CAV_X1, CAV_Y1, PART_Z - 1, CAV_Z1))
    b = b.cut(ring(REBATE, PART_Z - 1, PART_Z + SKIRT_H))  # the rebate the lip and tabs sit in
    # Grooves for the bumps, in the skirt's inner face.
    for ty in TAB_Y:
        for x_in, side in ((CAV_X0, -1), (CAV_X1, +1)):
            face = x_in + side * REBATE
            b = b.cut(along_y_at(cq.Workplane("XZ").circle(GROOVE_R), face, ty - TAB_W / 2 - GROOVE_Y_OVER, TAB_W + 2 * GROOVE_Y_OVER, PART_Z + BUMP_Z))
    # Bosses from the ceiling down to just above the board, holding it on the pegs.
    for bx_, by_, d, bored in BOSS_AT:
        boss = cyl(bx_, by_, d / 2, BOSS_Z0, BOSS_Z1 + 0.1)
        if bored:
            boss = boss.cut(cyl(bx_, by_, BOSS_BORE_D / 2, BOSS_Z0 - 0.1, BOSS_Z0 + BOSS_BORE_DEPTH))
        b = b.union(boss)
    # USB-C window in the left wall, centred on the receptacle.
    b = b.cut(box(OUT_X0 - 1, USB_WIN_Y - USB_WIN_W / 2, CAV_X0 + 0.1, USB_WIN_Y + USB_WIN_W / 2, USB_WIN_Z - USB_WIN_H / 2, USB_WIN_Z + USB_WIN_H / 2))
    # Antenna hole through the far wall, and the pocket for the E07's jack body.
    b = b.cut(along_y_at(cq.Workplane("XZ").circle(ANT_HOLE_D / 2), SOCKET_MID_X, CAV_Y1 - 1, OUT_Y1 - CAV_Y1 + 2, ANT_Z))
    b = b.cut(box(SOCKET_MID_X - E07_POCKET / 2, CAV_Y1 - 0.1, SOCKET_MID_X + E07_POCKET / 2, CAV_Y1 + E07_POCKET_DEPTH, POCKET_Z0, POCKET_Z1))
    # Pry notch in the skirt's bottom edge at the near (J4) end.
    b = b.cut(box(NOTCH_X0, OUT_Y0 - 1, NOTCH_X1, CAV_Y0 - REBATE - 0.01, PART_Z - 1, PART_Z + NOTCH_DEPTH))
    return b


def obstacles() -> dict[str, cq.Workplane]:
    """Everything inside the case, as solids in the board frame: the assembly
    table in docs/3d-models.md plus the pins and back-side parts."""
    mx, az = SOCKET_MID_X, ANT_Z
    hexp = lambda: cq.Workplane("XZ").polygon(6, PIGTAIL_HEX_AF / 0.8660254)  # noqa: E731  across flats to across corners
    circ = lambda r: cq.Workplane("XZ").circle(r)  # noqa: E731
    sm_pins = [(ga.Carrier.px(i), y) for i in range(1, 9) for y in (ga.CC_TOP_Y, ga.CC_BOT_Y)]
    sock = [(ga.CC_S1[0] - c * ga.SM_PITCH, ga.SOCKET_Y + r * ga.SM_PITCH) for c in range(4) for r in range(2)]
    j4 = [(ga.EXP_X1 + i * ga.SM_PITCH, ga.EXP_Y) for i in range(len(ga.EXP_PINS))]
    j5 = [(ga.J5_X + i * ga.SM_PITCH, ga.J5_Y) for i in range(2)]
    jp1 = [(ga.JP1_X, ga.JP1_Y + i * ga.SM_PITCH) for i in range(2)]

    def pins(pts: list[tuple[float, float]], z0: float) -> cq.Workplane:
        s = None
        for x, y in pts:
            b = box(x - 0.4, y - 0.4, x + 0.4, y + 0.4, z0, -BOARD_T)
            s = b if s is None else s.union(b)
        return s

    board = box(0, 0, W, H, -BOARD_T, 0)
    for hx, hy in HOLES:
        board = board.cut(cyl(hx, hy, HOLE_D / 2, -BOARD_T - 1, 1))
    cavity = box(CAV_X0 + 0.01, CAV_Y0 + 0.01, CAV_X1 - 0.01, CAV_Y1 - 0.01, PART_Z + 0.01, CAV_Z1 - 0.01)
    for hx, hy in HOLES:  # the peg tips
        cavity = cavity.cut(cyl(hx, hy, PEG_D / 2 + 0.1, PART_Z - 1, PEG_Z1 + 0.1))
    for bx_, by_, d, _ in BOSS_AT:  # the bosses
        cavity = cavity.cut(cyl(bx_, by_, d / 2 + 0.1, BOSS_Z0 - 0.1, BOSS_Z1 + 1))
    return {
        "adapter board": board,
        "jumper cap on JP1": box(ga.JP1_X - 1.25, ga.JP1_Y - 1.27, ga.JP1_X + 1.25, ga.JP1_Y + ga.SM_PITCH + 1.27, ga.HEADER_BODY, ga.HEADER_BODY + 6.0),
        "J4 header body and pins": box(ga.EXP_X1 - 1.27, ga.EXP_Y - 1.27, ga.EXP_X1 + 6 * ga.SM_PITCH + 1.27, ga.EXP_Y + 1.27, 0, HIGHEST),
        "J5 header body and pins": box(ga.J5_X - 1.27, ga.J5_Y - 1.27, ga.J5_X + ga.SM_PITCH + 1.27, ga.J5_Y + 1.27, 0, HIGHEST),
        "module header pins under the board": pins(sm_pins + sock, PIN_TIPS),
        "J4, J5 and JP1 pins under the board": pins(j4 + j5 + jp1, -3.0),
        "R1 on the back": box(ga.R1_X - 0.7, ga.R1_Y - 2.0, ga.R1_X + 0.7, ga.R1_Y + 2.0, -BOARD_T - 0.6, -BOARD_T),
        "R4 on the back": box(ga.R4_X - 0.7, ga.R4_Y - 1.6, ga.R4_X + 0.7, ga.R4_Y + 1.6, -BOARD_T - 0.6, -BOARD_T),
        "SuperMini PCB": box(-0.5, 5.6, 22.0, 23.6, 2.5, 3.5),
        "USB-C receptacle": box(USB_X0, USB_Y0, 5.4, USB_Y1, USB_Z0, USB_Z1),
        "USB-C plug overmoulding outside the wall": box(OUT_X0 - 30, USB_WIN_Y - 6.0, USB_X0, USB_WIN_Y + 6.0, USB_WIN_Z - 3.25, USB_WIN_Z + 3.25),
        "cavity above the board, which the lip and tabs must stay out of": cavity,
        "E07-M1101D PCB": box(mx - ga.E07_W / 2, ga.SOCKET_Y - ga.E07_ROW_IN, mx + ga.E07_W / 2, ga.SOCKET_Y - ga.E07_ROW_IN + ga.E07_H, ga.HEADER_BODY, ga.HEADER_BODY + 1.6),
        "E07 SMA jack body": box(mx - E07_JACK_BODY / 2, E07_JACK_Y1 - E07_JACK_LEN, mx + E07_JACK_BODY / 2, E07_JACK_Y1, az - E07_JACK_BODY / 2, az + E07_JACK_BODY / 2),
        "E07 SMA barrel": along_y_at(circ(SMA_BARREL_D / 2), mx, E07_JACK_Y1, E07_BARREL_LEN, az),
        "Ra-02 breakout PCB": box(mx - ga.RA02_W / 2, ga.SOCKET_Y - ga.RA02_ROW_IN, mx + ga.RA02_W / 2, ga.SOCKET_Y - ga.RA02_ROW_IN + ga.RA02_H, ga.HEADER_BODY, ga.HEADER_BODY + 1.6),
        "Ra-02 shield can and U.FL plug": box(mx - ga.RA02_W / 2 + 0.5, ga.SOCKET_Y, mx + ga.RA02_W / 2 - 0.5, ga.SOCKET_Y - ga.RA02_ROW_IN + ga.RA02_H - 0.5, ga.HEADER_BODY + 1.6, 7.9),
        "pigtail hex flange inside the wall": along_y_at(hexp(), mx, ANT_WALL_Y0 - PIGTAIL_FLANGE_T, PIGTAIL_FLANGE_T, az),
        "pigtail barrel through the wall": along_y_at(circ(SMA_BARREL_D / 2), mx, ANT_WALL_Y0, PIGTAIL_BARREL_LEN, az),
        "pigtail nut outside the wall": along_y_at(hexp(), mx, OUT_Y1, PIGTAIL_NUT_T, az),
    }


def check(bottom: cq.Workplane, top: cq.Workplane) -> None:
    """Refuse to write a case that collides with anything it has to house,
    or whose two halves collide with each other when closed."""
    bad = []
    for name, part in {**obstacles(), "the other half (closed)": top}.items():
        for label, shape in (("bottom", bottom), ("top", top)):
            if part is top and shape is top:
                continue
            hit = shape.intersect(part)
            vol = hit.val().Volume() if hit.vals() else 0.0
            if vol > 1e-6:
                bad.append(f"{label} collides with the {name}: {vol:.2f} mm^3")
    if bad:
        raise SystemExit("case check failed:\n  " + "\n  ".join(bad))
    print(f"case check: clear of all {len(obstacles())} parts")


def measure(bottom: cq.Workplane, top: cq.Workplane) -> dict[str, dict]:
    """Probe the finished solids and compare what the case measures with what
    case_dims says it should, so every rebuild proves the STL files match
    the constants (and the drawings, which draw_case.py --check reads
    against the JSON this returns).  Each probe is a thin rod or slab
    intersected with a half; the spans of solid material along it give
    faces, gaps and centres in the board frame.  Round features are probed
    with a 0.02 mm rod: the bounding box of a curved slice is that of its
    edges, i.e. a chord, and a 0.1 mm rod would read a 6.6 hole as 6.599.
    Returns {key: {"what", "expected", "measured"}} and stops on a mismatch."""
    rows: dict[str, dict] = {}
    bad: list[str] = []

    def bb(shape):
        b = shape.val().BoundingBox()
        return {"x": (b.xmin, b.xmax), "y": (-b.ymax, -b.ymin), "z": (b.zmin, b.zmax)}  # board frame: y = -model y

    def spans(shape, axis, x0, y0, x1, y1, z0, z1):
        """The intervals of solid material along `axis` inside a probe box (board frame)."""
        hit = shape.intersect(box(x0, y0, x1, y1, z0, z1))
        return sorted(bb(hit.newObject([s]))[axis] for s in hit.solids().vals())

    def rod(shape, axis, u, w, lo=-30.0, hi=80.0, t=0.01):
        """A thin rod along `axis` through the point with the other two coordinates (u, w), in x, y, z order."""
        if axis == "x":
            return spans(shape, axis, lo, u - t, hi, u + t, w - t, w + t)
        if axis == "y":
            return spans(shape, axis, u - t, lo, u + t, hi, w - t, w + t)
        return spans(shape, axis, u - t, w - t, u + t, w + t, lo, hi)

    def gap(sp, i=0):
        return sp[i + 1][0] - sp[i][1]

    def mid(sp):
        return (sp[0] + sp[1]) / 2

    def row(key, what, expected, measured, tol=0.02):
        rows[key] = {"what": what, "expected": round(expected, 4), "measured": round(measured, 4)}
        if abs(expected - measured) > tol:
            bad.append(f"{key}: expected {expected:.3f}, measured {measured:.3f} ({what})")
        return measured

    def corner_radius(shape, z):
        """The vertical corner radius, from where the USB-C wall's face has
        moved in at 0.3 mm from the back face: for a fillet R the offset there
        is R - sqrt(R^2 - (R - 0.3)^2), which inverts to R = (o + 0.3) + sqrt(0.6 o)."""
        e = 0.3
        face = spans(shape, "x", -10, OUT_Y0 + e - 0.1, 0, OUT_Y0 + e, z - 0.05, z + 0.05)[0][0]
        o = face - OUT_X0
        return (o + e) + math.sqrt(2 * o * e)

    b, t = bb(bottom), bb(top)
    x0 = row("out_x0", "USB-C wall outside face x", OUT_X0, b["x"][0])
    x1 = row("out_x1", "plain wall outside face x", OUT_X1, b["x"][1])
    y0 = row("out_y0", "back (J4 end) outside face y", OUT_Y0, b["y"][0])
    y1 = row("out_y1", "front (antenna) outside face y", OUT_Y1, b["y"][1])
    z0 = row("out_z0", "outside bottom face z", OUT_Z0, b["z"][0])
    z1 = row("out_z1", "outside top face z", OUT_Z1, t["z"][1])
    row("out_x", "outside width, bottom half", OUT_X1 - OUT_X0, x1 - x0)
    row("out_y", "outside length, bottom half", OUT_Y1 - OUT_Y0, y1 - y0)
    row("out_x_top", "outside width, top half", OUT_X1 - OUT_X0, t["x"][1] - t["x"][0])
    row("out_y_top", "outside length, top half", OUT_Y1 - OUT_Y0, t["y"][1] - t["y"][0])
    row("tab_tips_z", "highest point of the bottom half (tab tips)", PART_Z + TAB_H, b["z"][1])
    seam = row("seam_z", "the seam: the bottom half's wall top and the top half's skirt edge", PART_Z, rod(bottom, "z", -3.9, 41.0)[0][1])
    row("seam_z_top", "the top half's lowest point (skirt edge)", PART_Z, t["z"][0])
    row("bottom_h", "bottom half, outside bottom face to the seam", PART_Z - OUT_Z0, seam - z0)
    row("top_h", "top half, seam to the outside top face", OUT_Z1 - PART_Z, z1 - seam)
    row("overall_h", "closed case height", OUT_Z1 - OUT_Z0, z1 - z0)
    s = rod(top, "x", 41.0, 7.5)  # through both long walls above the rebate
    row("wall", "long wall thickness (top half, above the rebate)", WALL, s[0][1] - s[0][0])
    cav_x0 = s[0][1]
    row("cav_x", "cavity width", CAV_X1 - CAV_X0, gap(s))
    s = rod(bottom, "y", 12.0, -4.0)  # through both end walls below the seam
    row("back_wall", "back wall thickness", WALL, s[0][1] - s[0][0])
    row("front_wall", "front (antenna) wall thickness", ANT_WALL_T, s[-1][1] - s[-1][0])
    row("cav_y", "cavity length", CAV_Y1 - CAV_Y0, gap(s))
    row("pcb_edge_from_usb_face", "PCB x = 0 from the USB-C wall's outside face", 0 - OUT_X0, 0 - x0)
    row("pcb_edge_from_back_face", "PCB y = 0 from the back outside face", 0 - OUT_Y0, 0 - y0)
    s = rod(bottom, "z", 12.0, 20.0)
    floor_top = row("floor_top_z", "floor top z", CAV_Z0, s[0][1])
    row("floor", "floor thickness", FLOOR, floor_top - z0)
    row("floor_top_from_bottom", "floor top above the outside bottom face", CAV_Z0 - OUT_Z0, floor_top - z0)
    row("floor_below_seam", "floor top below the seam", PART_Z - CAV_Z0, seam - floor_top)
    s = rod(top, "z", 12.0, 20.0)
    ceiling = row("ceiling_z", "ceiling underside z", CAV_Z1, s[-1][0])
    row("ceiling", "ceiling thickness", TOP_T, z1 - ceiling)
    row("ceiling_from_bottom", "ceiling underside above the outside bottom face", CAV_Z1 - OUT_Z0, ceiling - z0)
    row("ceiling_above_seam", "ceiling underside above the seam", CAV_Z1 - PART_Z, ceiling - seam)
    row("ceiling_above_pcb", "ceiling underside above the PCB top (z = 0)", CAV_Z1, ceiling)
    row("top_face_from_bottom", "outside top face above the outside bottom face", OUT_Z1 - OUT_Z0, z1 - z0)
    # standoffs and pegs at the four holes
    sx, sy, tips = [], [], []
    for i, (hx, hy) in enumerate(HOLES, 1):
        s = spans(bottom, "x", hx - 2.3, hy - 0.01, hx + 2.3, hy + 0.01, -4.01, -3.99)  # clear of the walls
        sx.append(row(f"standoff_x_H{i}", f"standoff H{i} centre x", hx, mid(s[0])))
        row(f"standoff_d_H{i}", f"standoff H{i} diameter", STANDOFF_D, s[0][1] - s[0][0])
        s = spans(bottom, "y", hx - 0.01, hy - 2.3, hx + 0.01, hy + 2.3, -4.01, -3.99)
        sy.append(row(f"standoff_y_H{i}", f"standoff H{i} centre y", hy, mid(s[0])))
        s = rod(bottom, "z", hx + 1.5, hy)
        row(f"standoff_top_H{i}", f"standoff H{i} top z (PCB underside)", STANDOFF_Z1, s[0][1])
        tips.append(row(f"peg_tip_H{i}", f"peg H{i} tip z", 0.0 if (hx, hy) == FLUSH_PEG else PEG_Z1, rod(bottom, "z", hx, hy)[0][1]))
    standoff_top = rows["standoff_top_H1"]["measured"]
    row("standoff_h", "standoff height above the floor", STANDOFF_Z1 - STANDOFF_Z0, standoff_top - floor_top)
    row("standoff_top_from_bottom", "standoff top above the outside bottom face", STANDOFF_Z1 - OUT_Z0, standoff_top - z0)
    row("standoff_top_below_seam", "standoff top below the seam", PART_Z - STANDOFF_Z1, seam - standoff_top)
    row("hole_pitch_x", "standoff pitch across", W - 2 * HOLE_IN, sx[1] - sx[0])
    row("hole_pitch_y", "standoff pitch along", H - 2 * HOLE_IN, sy[2] - sy[0])
    row("hole_H1_from_usb_face", "H1 from the USB-C wall's outside face", HOLE_IN - OUT_X0, sx[0] - x0)
    row("hole_H2_from_plain_face", "H2 from the plain wall's outside face", OUT_X1 - (W - HOLE_IN), x1 - sx[1])
    row("hole_H1_from_back_face", "H1 from the back outside face", HOLE_IN - OUT_Y0, sy[0] - y0)
    row("hole_H3_from_front_face", "H3 from the front outside face", OUT_Y1 - (H - HOLE_IN), y1 - sy[2])
    s = spans(bottom, "x", HOLES[0][0] - 3, HOLES[0][1] - 0.01, HOLES[0][0] + 3, HOLES[0][1] + 0.01, -1.01, -0.99)
    row("peg_d", "peg diameter below the chamfer", PEG_D, s[0][1] - s[0][0])
    s = spans(bottom, "x", HOLES[0][0] - 3, HOLES[0][1] - 0.01, HOLES[0][0] + 3, HOLES[0][1] + 0.01, PEG_Z1 - 0.25, PEG_Z1 - 0.24)
    row("peg_chamfer_d", "peg diameter 0.25 below the tip, in the chamfer", PEG_D - 2 * (PEG_CHAMFER - 0.25), s[0][1] - s[0][0])
    row("peg_h", "peg above the standoff (H1)", PEG_H, tips[0] - standoff_top)
    row("peg_h_H3", "peg above the standoff (H3, flush with the PCB)", BOARD_T, tips[2] - standoff_top)
    row("peg_proud", "peg tip above the PCB top (H1)", PEG_Z1, tips[0])
    row("peg_tip_from_bottom", "peg tip above the outside bottom face (H1)", PEG_Z1 - OUT_Z0, tips[0] - z0)
    row("peg_tip_H3_from_bottom", "peg tip above the outside bottom face (H3)", 0.0 - OUT_Z0, tips[2] - z0)
    # the lip, its gap, and the tabs on both long walls
    s = rod(bottom, "x", 41.0, 0.5)
    row("lip_t", "lip thickness", LIP_T, s[0][1] - s[0][0])
    row("lip_h", "lip height above the seam", LIP_H, rod(bottom, "z", -2.7, 41.0)[0][1] - seam)
    s = rod(bottom, "x", LIP_Y1 - 0.4, 0.5)  # along the front wall's lip
    row("lip_gap_w", "lip gap in the front wall", LIP_GAP_X1 - LIP_GAP_X0, gap(s))
    row("lip_gap_from_usb_face", "lip gap centre from the USB-C wall's outside face", SOCKET_MID_X - OUT_X0, (s[0][1] + s[1][0]) / 2 - x0)
    for side, xr, xb in (("l", CAV_X0 - 0.4, LIP_X0 - BUMP_R / 2), ("r", CAV_X1 + 0.4, LIP_X1 + BUMP_R / 2)):
        s = rod(bottom, "y", xr, 3.0)  # above the lip: only the tabs
        row(f"tab_count_{side}", f"tabs on the {'USB-C' if side == 'l' else 'plain'} wall", len(TAB_Y), len(s))
        for i, ty in enumerate(TAB_Y, 1):
            row(f"tab_w_{side}{i}", f"tab {side}{i} width", TAB_W, s[i - 1][1] - s[i - 1][0])
            row(f"tab_y_{side}{i}", f"tab {side}{i} centre y", ty, mid(s[i - 1]))
            row(f"tab_{side}{i}_from_back_face", f"tab {side}{i} centre from the back outside face", ty - OUT_Y0, mid(s[i - 1]) - y0)
        row(f"tab_pitch_{side}", f"tab pitch, {side}", TAB_Y[1] - TAB_Y[0], mid(s[1]) - mid(s[0]))
        row(f"tab_h_{side}", f"tab height above the seam, {side}", TAB_H, rod(bottom, "z", xr, TAB_Y[0])[0][1] - seam)
        s2 = rod(bottom, "y", xr, 0.5)  # through the lip: the slots either side of the first tab
        i = next(i for i, (a, b_) in enumerate(s2) if abs((a + b_) / 2 - TAB_Y[0]) < 0.1)
        row(f"slot_before_{side}1", f"slot before tab {side}1", SLOT, gap(s2, i - 1))
        row(f"slot_after_{side}1", f"slot after tab {side}1", SLOT, gap(s2, i))
        s3 = rod(bottom, "x", TAB_Y[0], PART_Z + BUMP_Z, lo=-10 if side == "l" else 25, hi=0 if side == "l" else 40)
        row(f"tab_t_at_bump_{side}", f"tab thickness through the bump, {side}", LIP_T + BUMP_R, s3[0][1] - s3[0][0])
        s4 = rod(bottom, "z", xb, TAB_Y[0])  # the wall below the seam, then the bump
        row(f"bump_z_{side}", f"bump centre above the seam, {side}", BUMP_Z, mid(s4[-1]) - seam)
    # the top half: skirt, rebate, grooves on both walls
    s = rod(top, "x", 41.0, 3.0)
    row("skirt_t", "skirt thickness", SKIRT_T, s[0][1] - s[0][0])
    row("skirt_faces", "between the skirt's inner faces", CAV_X1 - CAV_X0 + 2 * REBATE, gap(s))
    row("rebate", "rebate depth (skirt face to cavity wall)", REBATE, cav_x0 - s[0][1])
    row("rebate_h", "rebate height above the seam", SKIRT_H, rod(top, "z", -2.8, 41.0)[0][0] - seam)
    row("rebate_over_tab", "rebate ceiling above the tab tips", SKIRT_H - TAB_H, rod(top, "z", -2.8, 41.0)[0][0] - b["z"][1])
    row("rebate_over_lip", "rebate ceiling above the lip", SKIRT_H - LIP_H, rod(top, "z", -2.8, 41.0)[0][0] - rod(bottom, "z", -2.7, 41.0)[0][1])
    for side, xf, lo, hi in (("l", CAV_X0 - REBATE, -10, 0), ("r", CAV_X1 + REBATE, 25, 40)):
        s = rod(top, "x", TAB_Y[0], PART_Z + BUMP_Z, lo=lo, hi=hi)
        face = s[0][1] if side == "l" else s[0][0]
        row(f"groove_depth_{side}", f"groove depth into the skirt face, {side}", GROOVE_R, abs(face - xf))
        s = rod(top, "y", xf - 0.25 if side == "l" else xf + 0.25, PART_Z + BUMP_Z)  # just inside the skirt face
        gaps = [(s[i][1], s[i + 1][0]) for i in range(len(s) - 1)]
        for i, ty in enumerate(TAB_Y, 1):
            g = next(g for g in gaps if abs((g[0] + g[1]) / 2 - ty) < 0.1)
            row(f"groove_len_{side}{i}", f"groove {side}{i} length", TAB_W + 2 * GROOVE_Y_OVER, g[1] - g[0])
            row(f"groove_y_{side}{i}", f"groove {side}{i} centre y", ty, (g[0] + g[1]) / 2)
            row(f"groove_{side}{i}_from_back_face", f"groove {side}{i} centre from the back outside face", ty - OUT_Y0, (g[0] + g[1]) / 2 - y0)
        s = rod(top, "z", xf - 0.25 if side == "l" else xf + 0.25, TAB_Y[0])
        row(f"groove_z_{side}", f"groove centre above the seam, {side}", BUMP_Z, (s[0][1] + s[1][0]) / 2 - seam)
    row("bump_past_skirt", "bump standing past the skirt face (tab deflection)", BUMP_PROUD, rows["tab_t_at_bump_l"]["measured"] - rows["rebate"]["measured"])
    row("groove_bottom_clear", "bump tip to the groove bottom", GROOVE_R - BUMP_PROUD, rows["groove_depth_l"]["measured"] - rows["bump_past_skirt"]["measured"])
    # bosses
    for i, (bx_, by_, dia, bored) in enumerate(BOSS_AT, 1):
        s = spans(top, "x", bx_ - 3, by_ - 0.01, bx_ + 3, by_ + 0.01, 4.99, 5.01)
        row(f"boss_x_{i}", f"boss {i} centre x", bx_, (s[0][0] + s[-1][1]) / 2)
        row(f"boss_d_{i}", f"boss {i} diameter", dia, s[-1][1] - s[0][0])
        s = spans(top, "y", bx_ - 0.01, by_ - 3, bx_ + 0.01, by_ + 3, 4.99, 5.01)
        row(f"boss_y_{i}", f"boss {i} centre y", by_, (s[0][0] + s[-1][1]) / 2)
        face = rod(top, "z", bx_ + dia / 2 - 0.3, by_)[0][0]
        row(f"boss_face_{i}", f"boss {i} face z", BOSS_Z0, face)
        if bored:
            s = spans(top, "x", bx_ - 3, by_ - 0.01, bx_ + 3, by_ + 0.01, 0.99, 1.01)
            row(f"bore_d_{i}", f"boss {i} bore diameter", BOSS_BORE_D, gap(s))
            row(f"bore_depth_{i}", f"boss {i} bore depth", BOSS_BORE_DEPTH, rod(top, "z", bx_, by_)[0][0] - face)
    face = rows["boss_face_1"]["measured"]
    row("boss_gap", "boss face above the PCB top (z = 0)", BOSS_GAP, face)
    row("boss_len", "boss length, ceiling to face", BOSS_Z1 - BOSS_Z0, ceiling - face)
    row("boss_face_from_bottom", "boss face above the outside bottom face", BOSS_Z0 - OUT_Z0, face - z0)
    row("boss_face_below_seam", "boss face below the skirt edge (seam)", BOSS_Z0 - PART_Z, face - seam)
    sbx, sby, sbd, _ = SOLID_BOSS
    row("solid_boss_from_usb_face", "solid boss centre from the USB-C wall's outside face", sbx - OUT_X0, rows["boss_x_3"]["measured"] - x0)
    row("solid_boss_from_back_face", "solid boss centre from the back outside face", sby - OUT_Y0, rows["boss_y_3"]["measured"] - y0)
    row("solid_boss_offset", "solid boss centre from H3 along y", sby - HOLES[2][1], rows["boss_y_3"]["measured"] - sy[2])
    # the USB-C window
    s = rod(top, "z", -3.5, USB_WIN_Y)
    row("window_h", "USB-C window height", USB_WIN_H, gap(s))
    wz = row("window_z", "USB-C window centre z", USB_WIN_Z, (s[0][1] + s[1][0]) / 2)
    sill = s[0][1]
    s = rod(top, "y", -3.5, USB_WIN_Z)
    row("window_w", "USB-C window width", USB_WIN_W, gap(s))
    wy = row("window_y", "USB-C window centre y", USB_WIN_Y, (s[0][1] + s[1][0]) / 2)
    row("window_from_back_face", "window centre from the back outside face", USB_WIN_Y - OUT_Y0, wy - y0)
    row("window_z_from_bottom", "window centre above the outside bottom face", USB_WIN_Z - OUT_Z0, wz - z0)
    row("window_sill_from_seam", "window sill above the seam", USB_WIN_Z - USB_WIN_H / 2 - PART_Z, sill - seam)
    # the antenna hole and the E07 pocket
    s = spans(top, "x", 0, 62.5, 25, 63.5, ANT_Z - 0.01, ANT_Z + 0.01)
    row("hole_d", "antenna hole diameter (across)", ANT_HOLE_D, gap(s))
    hx_ = row("hole_x", "antenna hole centre x", SOCKET_MID_X, (s[0][1] + s[1][0]) / 2)
    s = spans(top, "z", SOCKET_MID_X - 0.01, 62.5, SOCKET_MID_X + 0.01, 63.5, -5, 15)
    row("hole_d_z", "antenna hole diameter (up)", ANT_HOLE_D, gap(s))
    hz = row("hole_z", "antenna hole centre z", ANT_Z, (s[0][1] + s[1][0]) / 2)
    row("hole_from_usb_face", "hole centre from the USB-C wall's outside face", SOCKET_MID_X - OUT_X0, hx_ - x0)
    row("hole_from_plain_face", "hole centre from the plain wall's outside face", OUT_X1 - SOCKET_MID_X, x1 - hx_)
    row("hole_z_from_bottom", "hole centre above the outside bottom face", ANT_Z - OUT_Z0, hz - z0)
    row("hole_z_from_seam", "hole centre above the seam", ANT_Z - PART_Z, hz - seam)
    row("above_hole", "top of the hole to the outside top face", OUT_Z1 - ANT_HOLE_Z1, z1 - s[1][0])
    s = rod(top, "y", SOCKET_MID_X, ANT_HOLE_Z1 + 0.2, lo=55, hi=70)  # just above the hole: the pocket's back
    row("pocket_depth", "E07 pocket depth into the front wall", E07_POCKET_DEPTH, s[0][0] - CAV_Y1)
    s = spans(top, "x", 0, CAV_Y1 + 0.3, 25, CAV_Y1 + 0.32, ANT_HOLE_Z1 + 0.15, ANT_HOLE_Z1 + 0.17)
    row("pocket_w", "E07 pocket width", E07_POCKET, gap(s))
    # The pocket's floor (z -0.4) lies inside the rebate band, which is empty
    # below the rebate ceiling anyway, so only its top is a face of the part.
    row("pocket_z1", "E07 pocket top z", POCKET_Z1, rod(top, "z", SOCKET_MID_X, CAV_Y1 + 0.3)[0][0])
    # the pry notch and the corners
    s = rod(top, "z", NOTCH_X, -2.0)
    row("notch_depth", "pry notch height above the seam", NOTCH_DEPTH, s[0][0] - seam)
    s = rod(top, "x", -2.0, 0.0)
    row("notch_w", "pry notch width", NOTCH_W, gap(s))
    row("notch_from_usb_face", "pry notch centre from the USB-C wall's outside face", NOTCH_X - OUT_X0, (s[0][1] + s[1][0]) / 2 - x0)
    row("corner_r", "vertical corner radius, bottom half", CORNER_R, corner_radius(bottom, -5.0))
    row("corner_r_top", "vertical corner radius, top half", CORNER_R, corner_radius(top, 8.0))
    if bad:
        raise SystemExit("case measurement failed:\n  " + "\n  ".join(bad))
    print(f"case measurement: {len(rows)} dimensions match case_dims")
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stl", type=pathlib.Path, default=STL_OUT, help="directory for the printable STL files")
    args = ap.parse_args()
    bottom, top = build_bottom(), build_top()
    check(bottom, top)
    measured = measure(bottom, top)
    MEASURED.write_text(json.dumps(measured, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {MEASURED.relative_to(ROOT)} ({len(measured)} dimensions)")
    h1 = HOLES[0]
    save("esp32c3-radio-adapter-case-bottom", [("case_bottom", bottom, CASE_BOTTOM)], *h1)
    save("esp32c3-radio-adapter-case-top", [("case_top", top, CASE_TOP)], *h1)
    args.stl.mkdir(parents=True, exist_ok=True)
    # Print orientation: each half open side up (the top half turned over).
    for name, shape in (("bottom", bottom), ("top", top.rotate((0, 0, 0), (1, 0, 0), 180))):
        path = args.stl / f"esp32c3-radio-adapter-case-{name}.stl"
        cq.exporters.export(shape, str(path), tolerance=0.02, angularTolerance=0.2)
        print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size // 1024} kB)")
    print(f"case outside {OUT_X1 - OUT_X0:.1f} x {OUT_Y1 - OUT_Y0:.1f} x {OUT_Z1 - OUT_Z0:.1f} mm; cavity {CAV_X1 - CAV_X0:.1f} x {CAV_Y1 - CAV_Y0:.1f} x {CAV_Z1 - CAV_Z0:.1f} mm")


if __name__ == "__main__":
    main()

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
import pathlib
import sys

import cadquery as cq

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import generate_adapters as ga  # noqa: E402
from build_3d import box, cyl, save  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
STL_OUT = ROOT / "hardware" / "case"
# Two shades of the same light filament, so the seam and which half a feature
# belongs to read in the renders: the top half a touch darker and warmer.
CASE_BOTTOM, CASE_TOP = cq.Color(0.86, 0.86, 0.82), cq.Color(0.76, 0.73, 0.67)

# Every dimension is a named constant in case_dims.py (pure Python), shared
# with draw_case.py so the drawings cannot drift from the model.
from case_dims import (  # noqa: E402
    ANT_HOLE_D, ANT_WALL_Y0, ANT_Z, BOARD_T, BOSS_AT, BOSS_BORE_D, BOSS_GAP, BUMP_R, BUMP_Z,
    CAV_X0, CAV_X1, CAV_Y0, CAV_Y1, CAV_Z0, CAV_Z1, CORNER_R, E07_JACK_Y1, E07_POCKET,
    E07_POCKET_DEPTH, FIT, FLUSH_PEG, GROOVE_R, H, HIGHEST, HOLE_D, HOLES, LIP_H, LIP_T,
    NOTCH_DEPTH, NOTCH_W, OUT_X0, OUT_X1, OUT_Y0, OUT_Y1, OUT_Z0, OUT_Z1, PART_Z, PEG_CHAMFER,
    PEG_D, PEG_H, PIN_TIPS, SKIRT_H, SLOT, SOCKET_MID_X, STANDOFF_D, TAB_H, TAB_W, TAB_Y,
    USB_WIN_H, USB_WIN_W, USB_X0, USB_Y0, USB_Y1, USB_Z0, USB_Z1, W,
)


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
        b = b.union(cyl(hx, hy, STANDOFF_D / 2, CAV_Z0, -BOARD_T))
        top_z = -BOARD_T + (BOARD_T if (hx, hy) == FLUSH_PEG else PEG_H)
        peg = cyl(hx, hy, PEG_D / 2, -BOARD_T - 0.1, top_z).faces(">Z").chamfer(PEG_CHAMFER)
        b = b.union(peg)
    # The lip, gapped where the antenna connectors pass through the far
    # wall (the E07's jack body and the pigtail's flange sit right on the
    # parting line there), and the snap tabs cut free of it.
    lip = ring(LIP_T, PART_Z, PART_Z + LIP_H)
    lip = lip.cut(box(SOCKET_MID_X - E07_POCKET / 2 - 0.5, CAV_Y1 - 0.1, SOCKET_MID_X + E07_POCKET / 2 + 0.5, CAV_Y1 + LIP_T + 0.1, PART_Z - 0.1, PART_Z + LIP_H + 0.1))
    for ty in TAB_Y:
        for x_in, side in ((CAV_X0, -1), (CAV_X1, +1)):  # left wall (tab faces -x), right wall (+x)
            x_out = x_in + side * LIP_T
            tab = box(min(x_in, x_out), ty - TAB_W / 2, max(x_in, x_out), ty + TAB_W / 2, PART_Z, PART_Z + TAB_H)
            bump = along_y_at(cq.Workplane("XZ").circle(BUMP_R), x_out, ty - TAB_W / 2, TAB_W, PART_Z + BUMP_Z)
            tab = tab.union(bump).cut(box(CAV_X0, CAV_Y0, CAV_X1, CAV_Y1, PART_Z - 1, PART_Z + TAB_H + 1))  # nothing inside the cavity
            for sy in (ty - TAB_W / 2 - SLOT, ty + TAB_W / 2):
                lip = lip.cut(box(min(x_in, x_out) - 0.1, sy, max(x_in, x_out) + 0.1, sy + SLOT, PART_Z - 0.1, PART_Z + LIP_H + 1))
            lip = lip.union(tab)
    return b.union(lip)


def build_top() -> cq.Workplane:
    b = rounded_box(OUT_X0, OUT_Y0, OUT_X1, OUT_Y1, PART_Z, OUT_Z1, CORNER_R)
    b = b.cut(box(CAV_X0, CAV_Y0, CAV_X1, CAV_Y1, PART_Z - 1, CAV_Z1))
    b = b.cut(ring(LIP_T + FIT, PART_Z - 1, PART_Z + SKIRT_H))  # the rebate the lip and tabs sit in
    # Grooves for the bumps, in the skirt's inner face.
    for ty in TAB_Y:
        for x_in, side in ((CAV_X0, -1), (CAV_X1, +1)):
            face = x_in + side * (LIP_T + FIT)
            b = b.cut(along_y_at(cq.Workplane("XZ").circle(GROOVE_R), face, ty - TAB_W / 2 - 0.5, TAB_W + 1.0, PART_Z + BUMP_Z))
    # Bosses from the ceiling down to just above the board, holding it on the pegs.
    for bx_, by_, d, bored in BOSS_AT:
        boss = cyl(bx_, by_, d / 2, BOSS_GAP, CAV_Z1 + 0.1)
        if bored:
            boss = boss.cut(cyl(bx_, by_, BOSS_BORE_D / 2, BOSS_GAP - 0.1, BOSS_GAP + PEG_H))
        b = b.union(boss)
    # USB-C window in the left wall, centred on the receptacle.
    uy, uz = (USB_Y0 + USB_Y1) / 2, (USB_Z0 + USB_Z1) / 2
    b = b.cut(box(OUT_X0 - 1, uy - USB_WIN_W / 2, CAV_X0 + 0.1, uy + USB_WIN_W / 2, uz - USB_WIN_H / 2, uz + USB_WIN_H / 2))
    # Antenna hole through the far wall, and the pocket for the E07's jack body.
    b = b.cut(along_y_at(cq.Workplane("XZ").circle(ANT_HOLE_D / 2), SOCKET_MID_X, CAV_Y1 - 1, OUT_Y1 - CAV_Y1 + 2, ANT_Z))
    b = b.cut(box(SOCKET_MID_X - E07_POCKET / 2, CAV_Y1 - 0.1, SOCKET_MID_X + E07_POCKET / 2, CAV_Y1 + E07_POCKET_DEPTH, ANT_Z - E07_POCKET / 2, ANT_Z + E07_POCKET / 2))
    # Pry notch in the skirt's bottom edge at the near (J4) end.
    b = b.cut(box(W / 2 - NOTCH_W / 2, OUT_Y0 - 1, W / 2 + NOTCH_W / 2, CAV_Y0 - LIP_T - FIT - 0.01, PART_Z - 1, PART_Z + NOTCH_DEPTH))
    return b


def obstacles() -> dict[str, cq.Workplane]:
    """Everything inside the case, as solids in the board frame: the assembly
    table in docs/3d-models.md plus the pins and back-side parts."""
    mx, az = SOCKET_MID_X, ANT_Z
    hexp = lambda: cq.Workplane("XZ").polygon(6, 8.0 / 0.8660254)  # noqa: E731  8 mm across flats
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
        cavity = cavity.cut(cyl(hx, hy, PEG_D / 2 + 0.1, PART_Z - 1, PEG_H))
    for bx_, by_, d, _ in BOSS_AT:  # the bosses
        cavity = cavity.cut(cyl(bx_, by_, d / 2 + 0.1, BOSS_GAP - 0.1, CAV_Z1 + 1))
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
        "USB-C plug overmoulding outside the wall": box(OUT_X0 - 30, (USB_Y0 + USB_Y1) / 2 - 6.0, USB_X0, (USB_Y0 + USB_Y1) / 2 + 6.0, (USB_Z0 + USB_Z1) / 2 - 3.25, (USB_Z0 + USB_Z1) / 2 + 3.25),
        "cavity above the board, which the lip and tabs must stay out of": cavity,
        "E07-M1101D PCB": box(mx - ga.E07_W / 2, ga.SOCKET_Y - ga.E07_ROW_IN, mx + ga.E07_W / 2, ga.SOCKET_Y - ga.E07_ROW_IN + ga.E07_H, ga.HEADER_BODY, ga.HEADER_BODY + 1.6),
        "E07 SMA jack body": box(mx - 3.2, E07_JACK_Y1 - 3.0, mx + 3.2, E07_JACK_Y1, az - 3.2, az + 3.2),
        "E07 SMA barrel": along_y_at(circ(6.35 / 2), mx, E07_JACK_Y1, 6.5, az),
        "Ra-02 breakout PCB": box(mx - ga.RA02_W / 2, ga.SOCKET_Y - ga.RA02_ROW_IN, mx + ga.RA02_W / 2, ga.SOCKET_Y - ga.RA02_ROW_IN + ga.RA02_H, ga.HEADER_BODY, ga.HEADER_BODY + 1.6),
        "Ra-02 shield can and U.FL plug": box(mx - ga.RA02_W / 2 + 0.5, ga.SOCKET_Y, mx + ga.RA02_W / 2 - 0.5, ga.SOCKET_Y - ga.RA02_ROW_IN + ga.RA02_H - 0.5, ga.HEADER_BODY + 1.6, 7.9),
        "pigtail hex flange inside the wall": along_y_at(hexp(), mx, ANT_WALL_Y0 - 2.5, 2.5, az),
        "pigtail barrel through the wall": along_y_at(circ(6.35 / 2), mx, ANT_WALL_Y0, 9.5, az),
        "pigtail nut outside the wall": along_y_at(hexp(), mx, OUT_Y1, 2.4, az),
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


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stl", type=pathlib.Path, default=STL_OUT, help="directory for the printable STL files")
    args = ap.parse_args()
    bottom, top = build_bottom(), build_top()
    check(bottom, top)
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

#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["cadquery>=2.4"]
# ///
"""Build a 3D-printable case for the socket adapter with either radio in it.

Two parts, printed without supports: a base (open side up) and a flat lid
(printed top face down).  Dimensions come from the adapter generator and
from the assembly table in docs/3d-models.md; everything is in the adapter's
board frame (x right, y down, origin at the board's top-left corner) with z
up from the board's top surface, converted to KiCad's model frame on export.

  base   walls 2 mm, floor 2 mm; four M2 standoffs under the adapter's corner
         holes (self-tapping M2 x 6 screws through the board); a window in the
         left wall for the SuperMini's USB-C plug; a 6.6 mm hole in the far
         wall on the antenna axis, which takes the E07-M1101D's SMA jack
         through it or clamps the Ra-02's U.FL-to-SMA bulkhead pigtail by its
         nut, with a shallow pocket inside for the E07 jack's square body; a
         rebate round the top for the lid and a fingernail notch to lift it.
  lid    a plate that drops into the rebate, flush with the rim.

Written as hardware/3d/esp32c3-radio-adapter-case-{base,lid}.step (KiCad
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
CASE = cq.Color(0.86, 0.86, 0.82)

# --- the things the case has to clear (board frame, z from the board's top) ---
W, H = ga.CC_W, ga.CC_H  # 29 x 38
HOLE_IN, HOLE_D = ga.CC_HOLE_IN, ga.CC_HOLE_D  # M2 holes 2.4 in from each corner
HOLES = [(HOLE_IN, HOLE_IN), (W - HOLE_IN, HOLE_IN), (HOLE_IN, H - HOLE_IN), (W - HOLE_IN, H - HOLE_IN)]
BOARD_T = 1.6
USB_X0, USB_Y0, USB_Y1, USB_Z0, USB_Z1 = -2.0, 10.1, 19.1, 3.5, 6.7  # the SuperMini's USB-C receptacle
PIN_TIPS = -6.0  # the module headers' pins under the board (J4/JP1/J5 reach -3.0)
HIGHEST = 8.5  # J4/J5 pins and a jumper on JP1
SOCKET_MID_X = (ga.CC_S1[0] + ga.CC_S1[0] - 3 * ga.SM_PITCH) / 2  # 12.67: the antenna axis, both radios
ANT_Z = ga.HEADER_BODY + 0.8  # 3.3: the plugged-in radio board's mid-plane
E07_JACK_Y1 = ga.SOCKET_Y - ga.E07_ROW_IN + ga.E07_H + 3.0  # 61.9: the far face of the E07's square SMA body
ANT_WALL_Y0 = 61.5  # inner face of the antenna wall: the pigtail's flange seats here (see build_3d.build_pigtail)

# --- case geometry ---
WALL, FLOOR, LID_T = 2.0, 2.0, 2.0
CLEAR = 0.3  # cavity to the parts it wraps
CAV_X0, CAV_X1 = USB_X0 - CLEAR, W + 0.5  # the USB-C receptacle's face is the leftmost thing
CAV_Y0, CAV_Y1 = -0.5, ANT_WALL_Y0
CAV_Z0, CAV_Z1 = PIN_TIPS - 1.0, HIGHEST + 1.1  # -7.0 .. 9.6
OUT_X0, OUT_X1 = CAV_X0 - WALL, CAV_X1 + WALL
OUT_Y0, OUT_Y1 = CAV_Y0 - WALL, CAV_Y1 + 2.5  # the antenna wall is 2.5 thick: an SMA nut's worth
OUT_Z0, OUT_Z1 = CAV_Z0 - FLOOR, CAV_Z1 + LID_T  # -9.0 .. 11.6: the lid sits flush with the rim
STANDOFF_D, SCREW_D, SCREW_DEPTH = 4.0, 1.8, 4.5  # 4 mm keeps clear of JP1's pin beside the bottom-left hole
LID_CLEAR = 0.15
USB_WIN_W, USB_WIN_H = 13.0, 7.5  # a USB-C plug's overmoulding, so the plug can seat fully
ANT_HOLE_D = 6.6  # SMA barrel 6.35
E07_POCKET, E07_POCKET_DEPTH = 7.4, E07_JACK_Y1 - ANT_WALL_Y0 + 0.2  # 0.6: the jack body reaches 0.4 into the wall
NOTCH_W, NOTCH_DEPTH = 10.0, 1.2
CORNER_R = 2.0


def rounded_box(x0: float, y0: float, x1: float, y1: float, z0: float, z1: float, r: float) -> cq.Workplane:
    return box(x0, y0, x1, y1, z0, z1).edges("|Z").fillet(r)


def build_base() -> cq.Workplane:
    b = rounded_box(OUT_X0, OUT_Y0, OUT_X1, OUT_Y1, OUT_Z0, OUT_Z1, CORNER_R)
    # The cavity, and above it the rebate for the lid: the outer half of the
    # wall carries on up to the rim, the inner half stops at the cavity top.
    b = b.cut(box(CAV_X0, CAV_Y0, CAV_X1, CAV_Y1, CAV_Z0, CAV_Z1))
    b = b.cut(box(CAV_X0 - WALL / 2, CAV_Y0 - WALL / 2, CAV_X1 + WALL / 2, CAV_Y1 + WALL / 2, CAV_Z1, OUT_Z1 + 1))
    # Standoffs under the corner holes, with holes for self-tapping M2 screws.
    for hx, hy in HOLES:
        b = b.union(cyl(hx, hy, STANDOFF_D / 2, CAV_Z0, -BOARD_T))
        b = b.cut(cyl(hx, hy, SCREW_D / 2, -BOARD_T - SCREW_DEPTH, -BOARD_T + 0.1))
    # USB-C window in the left wall, centred on the receptacle.
    uy, uz = (USB_Y0 + USB_Y1) / 2, (USB_Z0 + USB_Z1) / 2
    b = b.cut(box(OUT_X0 - 1, uy - USB_WIN_W / 2, CAV_X0 + 0.1, uy + USB_WIN_W / 2, uz - USB_WIN_H / 2, uz + USB_WIN_H / 2))
    # Antenna hole through the far wall, and the pocket for the E07's jack body.
    # (the XZ workplane's normal is model -Y, i.e. board +y, so a positive extrude runs outward)
    hole = cq.Workplane("XZ").circle(ANT_HOLE_D / 2).extrude(OUT_Y1 - CAV_Y1 + 2).translate((SOCKET_MID_X, -(CAV_Y1 - 1), ANT_Z))
    b = b.cut(hole)
    b = b.cut(box(SOCKET_MID_X - E07_POCKET / 2, CAV_Y1 - 0.1, SOCKET_MID_X + E07_POCKET / 2, CAV_Y1 + E07_POCKET_DEPTH, ANT_Z - E07_POCKET / 2, ANT_Z + E07_POCKET / 2))
    # Fingernail notch in the rim at the near (J4) end.
    b = b.cut(box(W / 2 - NOTCH_W / 2, OUT_Y0 - 1, W / 2 + NOTCH_W / 2, CAV_Y0, OUT_Z1 - NOTCH_DEPTH, OUT_Z1 + 1))
    return b


def build_lid() -> cq.Workplane:
    c = LID_CLEAR
    return rounded_box(CAV_X0 - WALL / 2 + c, CAV_Y0 - WALL / 2 + c, CAV_X1 + WALL / 2 - c, CAV_Y1 + WALL / 2 - c, CAV_Z1, OUT_Z1, CORNER_R - WALL / 2)


def along_y(profile: cq.Workplane, x: float, y0: float, length: float, z: float) -> cq.Workplane:
    """A 2D profile on the XZ workplane extruded along board +y from y0."""
    return profile.extrude(length).translate((x, -y0, z))


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

    return {
        "adapter board": box(0, 0, W, H, -BOARD_T, 0),
        "module header pins under the board": pins(sm_pins + sock, PIN_TIPS),
        "J4, J5 and JP1 pins under the board": pins(j4 + j5 + jp1, -3.0),
        "R1 on the back": box(ga.R1_X - 0.7, ga.R1_Y - 2.0, ga.R1_X + 0.7, ga.R1_Y + 2.0, -BOARD_T - 0.6, -BOARD_T),
        "R4 on the back": box(ga.R4_X - 0.7, ga.R4_Y - 1.6, ga.R4_X + 0.7, ga.R4_Y + 1.6, -BOARD_T - 0.6, -BOARD_T),
        "parts on top, to the highest": box(0, 0, W, H, 0, HIGHEST),
        "SuperMini PCB": box(-0.5, 5.6, 22.0, 23.6, 2.5, 3.5),
        "USB-C receptacle": box(USB_X0, USB_Y0, 5.4, USB_Y1, USB_Z0, USB_Z1),
        "USB-C plug overmoulding outside the wall": box(OUT_X0 - 30, (USB_Y0 + USB_Y1) / 2 - 6.0, USB_X0, (USB_Y0 + USB_Y1) / 2 + 6.0, (USB_Z0 + USB_Z1) / 2 - 3.25, (USB_Z0 + USB_Z1) / 2 + 3.25),
        "E07-M1101D PCB": box(mx - ga.E07_W / 2, ga.SOCKET_Y - ga.E07_ROW_IN, mx + ga.E07_W / 2, ga.SOCKET_Y - ga.E07_ROW_IN + ga.E07_H, ga.HEADER_BODY, ga.HEADER_BODY + 1.6),
        "E07 SMA jack body": box(mx - 3.2, E07_JACK_Y1 - 3.0, mx + 3.2, E07_JACK_Y1, az - 3.2, az + 3.2),
        "E07 SMA barrel": along_y(circ(6.35 / 2), mx, E07_JACK_Y1, 6.5, az),
        "Ra-02 breakout PCB": box(mx - ga.RA02_W / 2, ga.SOCKET_Y - ga.RA02_ROW_IN, mx + ga.RA02_W / 2, ga.SOCKET_Y - ga.RA02_ROW_IN + ga.RA02_H, ga.HEADER_BODY, ga.HEADER_BODY + 1.6),
        "Ra-02 shield can and U.FL plug": box(mx - ga.RA02_W / 2 + 0.5, ga.SOCKET_Y, mx + ga.RA02_W / 2 - 0.5, ga.SOCKET_Y - ga.RA02_ROW_IN + ga.RA02_H - 0.5, ga.HEADER_BODY + 1.6, 7.9),
        "pigtail hex flange inside the wall": along_y(hexp(), mx, ANT_WALL_Y0 - 2.5, 2.5, az),
        "pigtail barrel through the wall": along_y(circ(6.35 / 2), mx, ANT_WALL_Y0, 9.5, az),
        "pigtail nut outside the wall": along_y(hexp(), mx, OUT_Y1, 2.4, az),
    }


def check(base: cq.Workplane, lid: cq.Workplane) -> None:
    """Refuse to write a case that collides with anything it has to house."""
    bad = []
    for name, part in obstacles().items():
        for label, shape in (("base", base), ("lid", lid)):
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
    base, lid = build_base(), build_lid()
    check(base, lid)
    h1 = HOLES[0]
    save("esp32c3-radio-adapter-case-base", [("case_base", base, CASE)], *h1)
    save("esp32c3-radio-adapter-case-lid", [("case_lid", lid, CASE)], *h1)
    args.stl.mkdir(parents=True, exist_ok=True)
    # Print orientation: the base as it is (open side up), the lid on its top face.
    for name, shape in (("base", base), ("lid", lid.rotate((0, 0, 0), (1, 0, 0), 180))):
        path = args.stl / f"esp32c3-radio-adapter-case-{name}.stl"
        cq.exporters.export(shape, str(path), tolerance=0.02, angularTolerance=0.2)
        print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size // 1024} kB)")
    print(f"case outside {OUT_X1 - OUT_X0:.1f} x {OUT_Y1 - OUT_Y0:.1f} x {OUT_Z1 - OUT_Z0:.1f} mm; cavity {CAV_X1 - CAV_X0:.1f} x {CAV_Y1 - CAV_Y0:.1f} x {CAV_Z1 - CAV_Z0:.1f} mm")


if __name__ == "__main__":
    main()

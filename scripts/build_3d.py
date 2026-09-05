#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["cadquery>=2.4"]
# ///
"""Build the STEP models under hardware/3d/ with CadQuery.

Every model is written in KiCad's footprint-model frame: X to the right, Y
up (the opposite of board y), Z out of the front of the board, millimetres,
with the origin at the footprint the model is attached to.  Positions below
are given in board coordinates (y down) and converted by the helpers.

Real products, each as a full board (PCB + parts + pin header) for plugging
into an adapter, and as a "-components" model (everything but the PCB) for
the reference board that reproduces it under hardware/parts/:

  esp32-c3-supermini      origin: left column pin 1 (GPIO5)
  cc1101-e07-m1101d       origin: header pin 1 (GND, right of the outer row)
  cc1101-dsun             origin: header pin 1 (GND, right of the outer row)
  sx1278-ra02-breakout    origin: header pin 1 (MISO, left of the outer row)
  sx1278-lora-module      origin: the module's top-left corner (12-pad edge on the left)

Plus the small parts the adapters use: pin headers, a jumper cap, an 0805
resistor, the edge-mount SMA jack, and the U.FL-to-SMA bulkhead pigtail for
the Ra-02 (drawn in the breakout's frame).

Pin headers are the usual 2.54 mm males: 2.5 mm plastic body, 0.64 mm square
pins, 3 mm on the short side and 6 mm on the long side.  A module's header
has its body against the module's back with the long pins pointing down
into the adapter, so two boards joined by one are 2.5 mm apart and 4.4 mm of
pin stands out under a 1.6 mm adapter.  The adapter's own headers have their
body on top with the long pins up.

Dimensions come from the generators of the reference boards (outline, pin
positions, holes) and from datasheets / measurements for the parts on them;
parts whose size only matters for clearance (chips, crystals, the shield
cans) are boxes.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

import cadquery as cq

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import generate_cc1101 as e07  # noqa: E402
import generate_dsun as dsun  # noqa: E402
import generate_ra02_breakout as rb  # noqa: E402
import generate_supermini as sm  # noqa: E402
import generate_sx1278 as sx  # noqa: E402

OUT = pathlib.Path(__file__).resolve().parent.parent / "hardware" / "3d"

# Colours (RGB 0..1)
PCB_GREEN = cq.Color(0.10, 0.40, 0.22)
PCB_BLUE = cq.Color(0.12, 0.30, 0.55)
PCB_BLACK = cq.Color(0.12, 0.12, 0.12)
PLASTIC = cq.Color(0.08, 0.08, 0.08)
METAL = cq.Color(0.75, 0.76, 0.78)
GOLD = cq.Color(0.80, 0.65, 0.25)
CHIP = cq.Color(0.15, 0.15, 0.17)
CERAMIC = cq.Color(0.85, 0.82, 0.75)
CABLE = cq.Color(0.20, 0.20, 0.22)

PITCH = 2.54
HDR_BODY, PIN_SHORT, PIN_LONG, PIN_SQ = 2.5, 3.0, 6.0, 0.64


# ---------------------------------------------------------------------------
# helpers (board coordinates in, model frame out)
# ---------------------------------------------------------------------------
def box(x0: float, y0: float, x1: float, y1: float, z0: float, z1: float) -> cq.Workplane:
    """Axis-aligned box from board-frame corners (y down) and z range."""
    return cq.Workplane("XY").box(abs(x1 - x0), abs(y1 - y0), abs(z1 - z0)).translate(((x0 + x1) / 2, -(y0 + y1) / 2, (z0 + z1) / 2))


def cyl(x: float, y: float, r: float, z0: float, z1: float) -> cq.Workplane:
    return cq.Workplane("XY").circle(r).extrude(z1 - z0).translate((x, -y, z0))


def hexagon(x: float, y: float, across_flats: float, z0: float, z1: float) -> cq.Workplane:
    return cq.Workplane("XY").polygon(6, across_flats / 0.8660254).extrude(z1 - z0).translate((x, -y, z0))


def shift(shape: cq.Workplane, dx: float, dy: float, dz: float = 0.0) -> cq.Workplane:
    """Move a shape by a board-frame (x, y) offset."""
    return shape.translate((dx, -dy, dz))


def pin_header(pins: list[tuple[float, float]], body_z0: float, up: float, down: float) -> list[tuple[str, cq.Workplane, cq.Color]]:
    """Male header: one 2.54 mm cube of body per pin (z from body_z0), pins
    reaching `up` above the body and `down` below it."""
    body = None
    for x, y in pins:
        b = box(x - PITCH / 2, y - PITCH / 2, x + PITCH / 2, y + PITCH / 2, body_z0, body_z0 + HDR_BODY)
        body = b if body is None else body.union(b)
    pin = None
    for x, y in pins:
        p = box(x - PIN_SQ / 2, y - PIN_SQ / 2, x + PIN_SQ / 2, y + PIN_SQ / 2, body_z0 - down, body_z0 + HDR_BODY + up)
        pin = p if pin is None else pin.union(p)
    return [("body", body, PLASTIC), ("pins", pin, METAL)]


def module_header(pins: list[tuple[float, float]]) -> list[tuple[str, cq.Workplane, cq.Color]]:
    """Header soldered to a module's back: body under the PCB, long pins down."""
    return pin_header(pins, -HDR_BODY, PIN_SHORT, PIN_LONG)


def pcb(w: float, h: float, t: float, colour: cq.Color, holes: list[tuple[float, float, float]] = ()) -> tuple[str, cq.Workplane, cq.Color]:
    """Board w x h (from the top-left corner in board coordinates), thickness t, round holes (x, y, diameter)."""
    b = box(0, 0, w, h, 0, t)
    for x, y, d in holes:
        b = b.cut(cyl(x, y, d / 2, -1, t + 1))
    return ("pcb", b, colour)


def castellations(b: cq.Workplane, pins: list[tuple[float, float]], edge_x: float, d: float, t: float) -> cq.Workplane:
    """Cut a hole at each pin plus a slot from it to the edge (a keyhole castellation)."""
    for x, y in pins:
        b = b.cut(cyl(x, y, d / 2, -1, t + 1))
        b = b.cut(box(min(x, edge_x), y - d / 2, max(x, edge_x), y + d / 2, -1, t + 1))
    return b


def save(name: str, parts: list[tuple[str, cq.Workplane, cq.Color]], dx: float = 0.0, dy: float = 0.0, dz: float = 0.0) -> None:
    """Write an assembly; (dx, dy) is the board-frame point that becomes the origin."""
    asm = cq.Assembly(name=name)
    for i, (label, shape, colour) in enumerate(parts):
        asm.add(shift(shape, -dx, -dy, dz), name=f"{label}_{i}", color=colour)
    path = OUT / f"{name}.step"
    asm.export(str(path))
    print(f"wrote {path.relative_to(OUT.parents[1])} ({path.stat().st_size // 1024} kB)")


# ---------------------------------------------------------------------------
# parts
# ---------------------------------------------------------------------------
def sma_edge_jack(x: float, y_edge: float, mid_z: float) -> list[tuple[str, cq.Workplane, cq.Color]]:
    """Edge-mount SMA jack on a board edge at y_edge (jack pointing +y),
    centre pin at x, straddling the board around z = mid_z: a 6.4 mm square
    block over the edge, then the threaded barrel to 9.5 mm from the edge."""
    parts = []
    body = box(x - 3.2, y_edge, x + 3.2, y_edge + 3.0, mid_z - 3.2, mid_z + 3.2)
    # extrude along +Z, then rotate +90 deg about X so +Z becomes -Y (board +y)
    barrel = cq.Workplane("XY").circle(6.35 / 2).extrude(6.5).rotate((0, 0, 0), (1, 0, 0), 90).translate((x, -(y_edge + 3.0), mid_z))
    bore = cq.Workplane("XY").circle(2.05).extrude(6.0).rotate((0, 0, 0), (1, 0, 0), 90).translate((x, -(y_edge + 3.5), mid_z))
    pin = cq.Workplane("XY").circle(0.64).extrude(6.0).rotate((0, 0, 0), (1, 0, 0), 90).translate((x, -(y_edge + 3.5), mid_z))
    parts.append(("sma_body", body.union(barrel).cut(bore), GOLD))
    parts.append(("sma_pin", pin, GOLD))
    # legs on both faces of the board, and the centre pin on top
    for lx in (x - e07.SMA_GND_OFFSET, x + e07.SMA_GND_OFFSET):
        parts.append(("sma_leg", box(lx - 0.6, y_edge - e07.SMA_PAD_L, lx + 0.6, y_edge, mid_z + 0.8, mid_z + 1.2), GOLD))
        parts.append(("sma_leg", box(lx - 0.6, y_edge - e07.SMA_PAD_L, lx + 0.6, y_edge, mid_z - 1.2, mid_z - 0.8), GOLD))
    parts.append(("sma_leg", box(x - 0.6, y_edge - e07.SMA_PAD_L, x + 0.6, y_edge, mid_z + 0.8, mid_z + 1.1), GOLD))
    return parts


def supermini_components(pins_l: list[tuple[float, float]], pins_r: list[tuple[float, float]]) -> list[tuple[str, cq.Workplane, cq.Color]]:
    """Parts on top of the SuperMini (z from its 1.0 mm PCB top): USB-C
    hanging 1.5 mm over the edge, two tactile buttons, the ESP32-C3 chip,
    crystal, regulator, LEDs and the ceramic antenna at the far end."""
    W, H, t = sm.BOARD_W, sm.BOARD_H, 1.0
    parts = []
    usb_w = 9.0
    parts.append(("usb_c", box((W - usb_w) / 2, -1.5, (W + usb_w) / 2, 5.85, t, t + 3.16).edges("|Y").fillet(1.2), METAL))
    for dx in (-2.95, 2.95):
        bx = W / 2 + dx
        parts.append(("button", box(bx - 1.5, 8.84 - 1.3, bx + 1.5, 8.84 + 1.3, t, t + 1.5), METAL))
        parts.append(("button_cap", cyl(bx, 8.84, 0.8, t + 1.5, t + 2.0), PLASTIC))
    parts.append(("esp32c3", box(W / 2 - 2.5, 10.5, W / 2 + 2.5, 15.5, t, t + 0.9), CHIP))
    parts.append(("crystal", box(W / 2 - 1.6, 16.1, W / 2 + 1.6, 18.6, t, t + 0.8), METAL))
    parts.append(("ldo", box(2.7, 11.5, 4.3, 14.4, t, t + 1.1), CHIP))
    parts.append(("led", box(13.8, 12.6, 15.4, 13.4, t, t + 0.6), CERAMIC))
    parts.append(("led", box(13.8, 14.6, 15.4, 15.4, t, t + 0.6), CERAMIC))
    parts.append(("antenna", box(5.5, H - 2.6, 12.5, H, t, t + 1.0), CERAMIC))
    return parts


def build_supermini() -> None:
    W, H, t = sm.BOARD_W, sm.BOARD_H, 1.0
    pins_l = [(sm.PIN_EDGE_X, sm.PIN_TOP_Y + i * PITCH) for i in range(8)]
    pins_r = [(W - sm.PIN_EDGE_X, sm.PIN_TOP_Y + i * PITCH) for i in range(8)]
    origin = pins_l[0]
    comps = supermini_components(pins_l, pins_r)
    save("esp32-c3-supermini-components", comps, *origin)
    board = pcb(W, H, t, PCB_BLACK)
    b = castellations(board[1], pins_l, 0, sm.DRILL, t)
    b = castellations(b, pins_r, W, sm.DRILL, t)
    save("esp32-c3-supermini", [("pcb", b, PCB_BLACK)] + comps + module_header(pins_l + pins_r), *origin)


def build_e07() -> None:
    W, H, t = e07.BOARD_W, e07.BOARD_H, 1.6
    hole_y = H - e07.HOLE_FROM_ANT_EDGE
    pins = [(W - e07.HDR_COL_X - ((n - 1) // 2) * PITCH, e07.HDR_ROW_Y + ((n - 1) % 2) * PITCH) for n in range(1, 9)]
    origin = pins[0]
    comps = [
        ("cc1101", box(W / 2 - 2.0, 10.5, W / 2 + 2.0, 14.5, t, t + 0.9), CHIP),
        ("crystal", box(W / 2 - 1.6, 6.6, W / 2 + 1.6, 9.1, t, t + 0.8), METAL),
        ("balun", box(W / 2 - 0.8, 16.0, W / 2 + 0.8, 17.6, t, t + 0.9), CHIP),
    ]
    for (x, y) in ((3.5, 11.0), (3.5, 12.6), (11.5, 11.0), (11.5, 12.6), (5.0, 16.5), (10.0, 16.5)):
        comps.append(("passive", box(x - 0.8, y - 0.4, x + 0.8, y + 0.4, t, t + 0.5), CERAMIC))
    comps += sma_edge_jack(W / 2, H, t / 2)
    comps += module_header(pins)
    save("cc1101-e07-m1101d-components", comps, *origin)
    board = pcb(W, H, t, PCB_BLUE, [(e07.HOLE_X, hole_y, e07.HOLE_D), (W - e07.HOLE_X, hole_y, e07.HOLE_D)])
    save("cc1101-e07-m1101d", [board] + comps, *origin)


def build_dsun() -> None:
    """The green D-Sun CC1101 board: 14.4 x 30, two 1.8 mm holes beside the
    SMA jack, crystal against the left edge, CC1101 mid-board."""
    W, H, t = dsun.BOARD_W, dsun.BOARD_H, 1.6
    hole_y = H - dsun.HOLE_FROM_ANT_EDGE
    pins = [(W - dsun.HDR_COL_X - ((n - 1) // 2) * PITCH, dsun.HDR_ROW_Y + ((n - 1) % 2) * PITCH) for n in range(1, 9)]
    origin = pins[0]
    comps = [
        ("cc1101", box(3.5, 13.8, 7.5, 17.8, t, t + 0.9), CHIP),
        ("crystal", box(0.1, 13.9, 2.6, 17.1, t, t + 0.8), METAL),
    ]
    for (x, y) in ((9.5, 9.0), (9.5, 11.0), (11.5, 9.0), (11.5, 11.0), (3.0, 19.5), (4.6, 19.5), (6.2, 19.5), (9.0, 15.5), (10.6, 15.5), (12.2, 15.5), (11.0, 21.0), (5.0, 24.0)):
        comps.append(("passive", box(x - 0.8, y - 0.5, x + 0.8, y + 0.5, t, t + 0.5), CERAMIC))
    comps += sma_edge_jack(W / 2, H, t / 2)
    comps += module_header(pins)
    save("cc1101-dsun-components", comps, *origin)
    board = pcb(W, H, t, PCB_GREEN, [(dsun.HOLE_X, hole_y, dsun.HOLE_D), (W - dsun.HOLE_X, hole_y, dsun.HOLE_D)])
    save("cc1101-dsun", [board] + comps, *origin)


def ra02_module(x0: float, y0: float, z0: float) -> list[tuple[str, cq.Workplane, cq.Color]]:
    """Ai-Thinker Ra-02 as mounted on the breakout: 16 x 17 (x by y) with the
    castellated 17 mm edges left and right, 0.8 mm PCB plus a 2.4 mm shield
    can (3.2 mm overall), IPEX socket in the far right corner."""
    mw, mh = rb.MOD_W, rb.MOD_H
    parts = [("ra02_pcb", box(x0, y0, x0 + mw, y0 + mh, z0, z0 + 0.8), PCB_GREEN)]
    parts.append(("ra02_can", box(x0 + 0.7, y0 + 0.5, x0 + mw - 0.7, y0 + mh - 2.8, z0 + 0.8, z0 + 3.2), METAL))
    ix, iy = x0 + rb.IPEX[0], y0 + rb.IPEX[1]
    parts.append(("ipex", box(ix - 1.3, iy - 1.3, ix + 1.3, iy + 1.3, z0 + 0.8, z0 + 1.4), CERAMIC))
    parts.append(("ipex", cyl(ix, iy, 1.0, z0 + 1.4, z0 + 2.05), GOLD))
    return parts


def build_ra02_breakout() -> None:
    W, H, t = rb.BOARD_W, rb.BOARD_H, 1.6
    pins = [(rb.hdr_x(n), rb.hdr_y(n)) for n in range(1, 9)]
    origin = pins[0]
    comps = ra02_module(rb.MOD_X, rb.MOD_Y, t) + module_header(pins)
    save("sx1278-ra02-breakout-components", comps, *origin)
    save("sx1278-ra02-breakout", [pcb(W, H, t, PCB_BLUE)] + comps, *origin)
    build_pigtail(origin, (rb.MOD_X + rb.IPEX[0], rb.MOD_Y + rb.IPEX[1], t + 2.05))


def build_pigtail(origin: tuple[float, float], ipex: tuple[float, float, float]) -> None:
    """U.FL plug on the Ra-02's IPEX, 1.13 mm cable and an SMA bulkhead jack
    placed on the same axis the E07-M1101D's SMA jack has when either board
    is in the socket adapter: the breakout's centre line at its mid-plane,
    pointing away from the header edge.  Its barrel starts 31 mm past the
    header row, so one case wall and antenna hole suit both radios."""
    ix, iy, iz = ipex
    ax = rb.BOARD_W / 2  # jack axis x (board frame)
    az = 0.8  # jack axis z: the breakout's mid-plane
    y_crimp, y_flange, y_barrel0, y_barrel1 = 24.5, 28.5, 31.0, 40.5  # board y along the axis
    parts = [("ufl_plug", cyl(ix, iy, 1.6, iz, iz + 1.7), METAL)]
    # cable: leaves the plug sideways at its mid height, sweeps round and
    # arrives on the jack axis heading along +y
    p0 = cq.Vector(ix, -iy, iz + 0.9)
    p1 = cq.Vector(ax, -y_crimp, az)
    pts = [p0, cq.Vector(ix - 3.5, -iy, iz + 0.8), cq.Vector(ax + 0.5, -(iy + 1.5), az + 1.2), p1]
    path = cq.Workplane("XY").spline([(v.x, v.y, v.z) for v in pts], tangents=[(-1, 0, 0), (0, -1, 0)], includeCurrent=False)
    cable = cq.Workplane(cq.Plane(origin=(p0.x, p0.y, p0.z), normal=(-1, 0, 0))).circle(0.565).sweep(path, isFrenet=True)
    parts.append(("cable", cable, CABLE))

    def along_y(shape: cq.Workplane, y_from: float) -> cq.Workplane:
        """A part extruded along +Z from z=0 becomes one pointing along board +y from y_from."""
        return shape.rotate((0, 0, 0), (1, 0, 0), 90).translate((ax, -y_from, az))

    crimp = along_y(cq.Workplane("XY").circle(1.8).extrude(y_flange - y_crimp), y_crimp)
    flange = along_y(cq.Workplane("XY").polygon(6, 8.0 / 0.8660254).extrude(y_barrel0 - y_flange), y_flange)
    barrel = along_y(cq.Workplane("XY").circle(6.35 / 2).extrude(y_barrel1 - y_barrel0), y_barrel0)
    bore = along_y(cq.Workplane("XY").circle(2.05).extrude(6.0), y_barrel1 - 6.0)
    pin = along_y(cq.Workplane("XY").circle(0.64).extrude(6.0), y_barrel1 - 6.0)
    nut = along_y(cq.Workplane("XY").polygon(6, 8.0 / 0.8660254).extrude(2.4).cut(cq.Workplane("XY").circle(3.2).extrude(2.4)), y_barrel0 + 2.5)
    parts += [("sma_bulkhead", crimp.union(flange).union(barrel).cut(bore), GOLD), ("sma_pin", pin, GOLD), ("sma_nut", nut, METAL)]
    save("sx1278-ra02-pigtail", parts, *origin)


def build_sx1278_module() -> None:
    W, H, t = sx.BOARD_W, sx.BOARD_H, 1.0
    can = ("can", box(2.4, 1.2, W - 0.6, H - 1.2, t, t + 2.2), METAL)
    save("sx1278-lora-module-components", [can])
    board = pcb(W, H, t, PCB_GREEN)
    left = [(sx.ROW_HOLE_IN, sx.LEFT_FIRST_Y + i * sx.PITCH) for i in range(sx.N_LEFT)]
    b = castellations(board[1], left, 0, sx.HOLE, t)
    right = [(W - sx.RIGHT_HOLE_IN, y) for y in sx.RIGHT_PAD_Y.values()]
    b = castellations(b, right, W, sx.HOLE, t)
    save("sx1278-lora-module", [("pcb", b, PCB_GREEN), can])


def build_small_parts() -> None:
    # Adapter headers: body on top, long pins up; pins stepping along +x or +y (board).
    save("pin-header-1x07", pin_header([(i * PITCH, 0) for i in range(7)], 0, PIN_LONG, PIN_SHORT))
    save("pin-header-1x02", pin_header([(0, i * PITCH) for i in range(2)], 0, PIN_LONG, PIN_SHORT))
    # Jumper cap on a 1x2 header (pins along +y), seated on the header body.
    cap = box(-1.25, -1.27, 1.25, PITCH + 1.27, HDR_BODY, HDR_BODY + 6.0)
    save("jumper-cap", [("cap", cap, PLASTIC)])
    # 0805 chip resistor on its pads (pads 2.0 mm apart along +y).
    r = [("r_body", box(-0.65, -1.0, 0.65, 1.0, 0.0, 0.45), CHIP), ("r_end", box(-0.65, -1.0, 0.65, -0.6, 0.0, 0.46), METAL), ("r_end", box(-0.65, 0.6, 0.65, 1.0, 0.0, 0.46), METAL)]
    save("r0805", r)
    # Edge-mount SMA jack: origin at the board edge on the centre pin, board 1.6 mm, jack pointing +y.
    save("sma-edge-jack", sma_edge_jack(0.0, 0.0, 0.8))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=pathlib.Path, default=OUT)
    args = ap.parse_args()
    globals()["OUT"] = args.out
    args.out.mkdir(parents=True, exist_ok=True)
    build_supermini()
    build_e07()
    build_dsun()
    build_ra02_breakout()
    build_sx1278_module()
    build_small_parts()


if __name__ == "__main__":
    main()

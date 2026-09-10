#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Every dimension of the socket adapter's printed case, as named constants.

scripts/build_case.py builds the solids from these (with CadQuery) and
scripts/draw_case.py draws the mechanical drawings from them (standard
library only), so the drawings cannot drift from the model.  Everything is
in the adapter's board frame: x right, y down from the board's top-left
corner, z up from the board's top surface.  The STEP models move the origin
to mounting hole H1 (2.4, 2.4) when they are written.

Run the module to print every constant with its value.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import generate_adapters as ga  # noqa: E402

# --- the things the case has to clear (board frame, z from the board's top) ---
W, H = ga.CC_W, ga.CC_H  # 29 x 38
HOLE_IN, HOLE_D = ga.CC_HOLE_IN, ga.CC_HOLE_D  # M2 holes 2.4 in from each corner
HOLES = [(HOLE_IN, HOLE_IN), (W - HOLE_IN, HOLE_IN), (HOLE_IN, H - HOLE_IN), (W - HOLE_IN, H - HOLE_IN)]
BOARD_T = 1.6
# The SuperMini is either soldered flat by its castellations (PCB z 0..1.0)
# or on its 2.5 mm pin headers (2.5..3.5); the case takes both, so its USB-C
# receptacle (3.2 mm tall, 9 mm wide, 2.0 mm past the board's left edge) can
# sit at either of two heights.
SM_PCB_T, SM_FLAT_Z0, SM_HDR_Z0 = 1.0, 0.0, ga.HEADER_BODY
USB_X0, USB_Y0, USB_Y1, USB_H = -2.0, 10.1, 19.1, 3.2  # the SuperMini's USB-C receptacle: face past the board edge, its y span, its height
USB_W = USB_Y1 - USB_Y0  # 9.0
USB_FLAT_Z0, USB_HDR_Z0 = SM_FLAT_Z0 + SM_PCB_T, SM_HDR_Z0 + SM_PCB_T  # 1.0 / 3.5: the receptacle's underside
USB_Z0, USB_Z1 = USB_FLAT_Z0, USB_HDR_Z0 + USB_H  # 1.0 .. 6.7: the receptacle is somewhere in this band
PLUG_W, PLUG_H, PLUG_SHELL_W, PLUG_SHELL_H = 12.0, 6.5, 8.4, 2.6  # a USB-C cable plug: its overmoulding, and the metal shell
PIN_STUBS = -1.0  # every through-hole pin is trimmed under the board; this much of stub and solder is left
HIGHEST = 8.5  # J4/J5 pins and a jumper on JP1
SOCKET_MID_X = (ga.CC_S1[0] + ga.CC_S1[0] - 3 * ga.SM_PITCH) / 2  # 12.67: the antenna axis, both radios
ANT_Z = ga.HEADER_BODY + 0.8  # 3.3: the plugged-in radio board's mid-plane
E07_JACK_BODY, E07_JACK_LEN = 6.4, 3.0  # the E07's square SMA jack body: across, and along y past the board edge
E07_JACK_Y1 = ga.SOCKET_Y - ga.E07_ROW_IN + ga.E07_H + E07_JACK_LEN  # 61.9: the far face of the E07's square SMA body
SMA_BARREL_D, E07_BARREL_LEN = 6.35, 6.5  # the threaded SMA barrel (jack and pigtail bulkhead), and the E07's length of it
PIGTAIL_HEX_AF, PIGTAIL_FLANGE_T, PIGTAIL_BARREL_LEN, PIGTAIL_NUT_T = 8.0, 2.5, 9.5, 2.4  # the U.FL-to-SMA bulkhead (see build_3d.build_pigtail)
ANT_WALL_Y0 = 61.5  # inner face of the antenna wall: the pigtail's flange seats here (see build_3d.build_pigtail)

# --- case geometry ---
WALL, FLOOR, TOP_T = 2.2, 2.0, 2.0
CLEAR = 0.3  # cavity to the parts it wraps
CAV_X0, CAV_X1 = USB_X0 - CLEAR, W + 0.5  # the USB-C receptacle's face is the leftmost thing
CAV_Y0, CAV_Y1 = -0.5, ANT_WALL_Y0
CAV_Z0, CAV_Z1 = -2.6, HIGHEST + 1.1  # -2.6 .. 9.6: under the pin stubs (-1.0) and the back-side 0805s (-2.2), over the header pins
OUT_X0, OUT_X1 = CAV_X0 - WALL, CAV_X1 + WALL
ANT_WALL_T = 2.5  # the antenna wall: an SMA nut's worth
OUT_Y0, OUT_Y1 = CAV_Y0 - WALL, CAV_Y1 + ANT_WALL_T
OUT_Z0, OUT_Z1 = CAV_Z0 - FLOOR, CAV_Z1 + TOP_T  # -4.6 .. 11.6
# The parting line is on the antenna axis, so the antenna hole and the USB-C
# window are each half in one half: the connectors sit in the bottom half's
# cut-outs and the top half closes over them.
PART_Z = ANT_Z  # 3.3
STANDOFF_D = 4.0  # 4 mm keeps clear of JP1's pin beside the bottom-left hole
PEG_D, PEG_H, PEG_CHAMFER = 2.15, BOARD_T + 0.4, 0.4  # a light press fit in the 2.2 mm holes (FDM pegs print a touch oversize)
# Bosses from the ceiling hold the board down on the pegs, bored to clear the
# peg tips.  The bottom-left corner is crowded (a jumper cap on JP1, the Ra-02
# breakout's overhang), so there the peg is flush with the board and a small
# solid boss presses beside the hole, into the corner.
BOSS_D, BOSS_BORE_D, BOSS_GAP = 4.4, 2.6, 0.2
BOSS_AT = [(HOLE_IN, HOLE_IN, BOSS_D, True), (W - HOLE_IN, HOLE_IN, BOSS_D, True), (2.2, H - 1.4, 3.0, False), (W - HOLE_IN, H - HOLE_IN, BOSS_D, True)]  # x, y, diameter, bored
FLUSH_PEG = HOLES[2]
# Snap fit.  The bottom half's lip (the inner LIP_T of the wall) rises LIP_H
# above the parting line into a rebate in the top half's skirt, FIT clear.
# On each long wall two tabs, TAB_W wide and TAB_H tall, are cut free of the
# lip by SLOT-wide slots so each is a cantilever LIP_T thick; a half-round
# bump of radius BUMP_R across its outer face near the tip clicks into a
# groove of radius GROOVE_R in the skirt.  The bump stands BUMP_R - FIT proud
# of the skirt's face, so that is what the tab deflects: about 1% strain over
# the tab's height, gentle enough for PLA.
LIP_T, LIP_H, FIT = 0.8, 1.5, 0.15
TAB_W, TAB_H, SLOT = 8.0, 5.0, 1.0
BUMP_R, GROOVE_R, BUMP_Z = 0.35, 0.42, 4.3  # bump/groove centre height above the parting line
SKIRT_H = TAB_H + 0.3  # the rebate reaches this far above the parting line
TAB_Y = (32.0, 50.0)  # tab centres along the long walls: clear of the USB-C window and the corners
# USB-C window: the shell's width plus room, tall enough for the receptacle
# at either height; split by the seam, so the bottom half's U cradles a
# flat-mounted receptacle.  Outside, a recess the plug's overmoulding sits
# in thins the wall there so the plug's shell reaches the receptacle.
USB_WIN_W, USB_WIN_Z0, USB_WIN_Z1 = USB_W + 1.0, USB_Z0 - 0.3, USB_Z1 + 0.3  # 10.0 wide, z 0.7 .. 7.0
USB_RECESS_W, USB_RECESS_Z0, USB_RECESS_Z1, USB_RECESS_DEPTH = PLUG_W + 1.0, USB_FLAT_Z0 + USB_H / 2 - PLUG_H / 2 - 0.5, USB_HDR_Z0 + USB_H / 2 + PLUG_H / 2 + 0.5, 1.0
ANT_HOLE_D = 6.6  # clears the SMA barrel
E07_POCKET, E07_POCKET_DEPTH = 7.4, E07_JACK_Y1 - ANT_WALL_Y0 + 0.2  # 0.6: the jack body reaches 0.4 into the wall
LIP_GAP_OVER = 0.5  # the lip's gap in the antenna wall runs this far past the pocket on each side
NOTCH_W, NOTCH_DEPTH = 10.0, 1.2  # pry notch in the top half's skirt, on the near (J4) end
CORNER_R = 2.0
# Optional slot in the ceiling over J4, the spare-GPIO header, for jumper
# wires out of the closed case: a second top half is written with it.
SLOT_OVER = 0.5  # past the header's plastic body on every side
J4_SLOT_X0, J4_SLOT_X1 = ga.EXP_X1 - ga.SM_PITCH / 2 - SLOT_OVER, ga.EXP_X1 + (len(ga.EXP_PINS) - 0.5) * ga.SM_PITCH + SLOT_OVER  # 5.11 .. 23.89
J4_SLOT_Y0, J4_SLOT_Y1 = ga.EXP_Y - ga.SM_PITCH / 2 - SLOT_OVER, ga.EXP_Y + ga.SM_PITCH / 2 + SLOT_OVER  # 0.78 .. 4.32

# --- derived, for the drawings and the checks: the arithmetic build_case does, named ---
USB_WIN_Y, USB_WIN_H = (USB_Y0 + USB_Y1) / 2, USB_WIN_Z1 - USB_WIN_Z0  # 14.6: the window's centre; 6.3 tall
USB_WIN_Z = (USB_WIN_Z0 + USB_WIN_Z1) / 2  # 3.85: the window's centre height
USB_RECESS_H = USB_RECESS_Z1 - USB_RECESS_Z0
USB_RECESS_X = OUT_X0 + USB_RECESS_DEPTH  # the recess floor: what is left of the wall there is USB_RECESS_X - CAV_X0
STANDOFF_Z0, STANDOFF_Z1 = CAV_Z0, -BOARD_T  # 1.0 tall, floor to the board's underside
PEG_Z1 = -BOARD_T + PEG_H  # 0.4: proud of the board's top (the flush peg stops at 0.0)
BOSS_Z0, BOSS_Z1 = BOSS_GAP, CAV_Z1  # ceiling to 0.2 above the board
BOSS_BORE_DEPTH = PEG_H  # the bore clears the peg tip
LIP_X0, LIP_X1 = CAV_X0 - LIP_T, CAV_X1 + LIP_T  # the lip's outer faces
LIP_Y0, LIP_Y1 = CAV_Y0 - LIP_T, CAV_Y1 + LIP_T
REBATE = LIP_T + FIT  # 0.95: the rebate's depth into the top half's wall, from the cavity boundary
SKIRT_T = WALL - REBATE  # 1.25: what is left of the top half's wall beside the lip
LIP_GAP_X0, LIP_GAP_X1 = SOCKET_MID_X - E07_POCKET / 2 - LIP_GAP_OVER, SOCKET_MID_X + E07_POCKET / 2 + LIP_GAP_OVER  # the lip's gap in the antenna wall
BUMP_PROUD = BUMP_R - FIT  # 0.2: how far the bump stands past the skirt's face, i.e. the tab's deflection
GROOVE_Y_OVER = 0.5  # the groove runs this far past each end of the tab
NOTCH_X, NOTCH_X0, NOTCH_X1 = W / 2, W / 2 - NOTCH_W / 2, W / 2 + NOTCH_W / 2  # centred on the PCB
SOLID_BOSS = BOSS_AT[2]  # (x, y, diameter, bored): the small solid boss beside H3
SECTION_CC_Y, SECTION_DD_Y = TAB_Y[0], 44.0  # the drawings' section planes through a tab and through the plain lip
POCKET_Z0, POCKET_Z1 = ANT_Z - E07_POCKET / 2, ANT_Z + E07_POCKET / 2  # the E07 pocket's z span
ANT_HOLE_Z0, ANT_HOLE_Z1 = ANT_Z - ANT_HOLE_D / 2, ANT_Z + ANT_HOLE_D / 2
# At the USB-C wall the plug recess would leave only 0.25 mm of skirt beside
# the rebate, so over the recess's width there is no lip and no rebate: the
# top half's wall stays full (recessed) thickness and closes on the bottom
# half's wall top.
LIP_GAP_USB_Y0, LIP_GAP_USB_Y1 = USB_WIN_Y - USB_RECESS_W / 2, USB_WIN_Y + USB_RECESS_W / 2


def slots(ty: float) -> list[tuple[float, float]]:
    """The y ranges of the two slots that free the tab centred at ty."""
    return [(ty - TAB_W / 2 - SLOT, ty - TAB_W / 2), (ty + TAB_W / 2, ty + TAB_W / 2 + SLOT)]


if __name__ == "__main__":
    for name, value in sorted(globals().items()):
        if name.isupper() and not name.startswith("_"):
            print(f"{name} = {value}")

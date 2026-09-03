#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Generate two small carrier boards that connect an ESP32-C3 SuperMini to a
433 MHz radio module:

* hardware/esp32c3-sx1278-adapter  - SuperMini + the 16-pin castellated
  SX1278 LoRa module (soldered onto SMD land pads) + a hole for the spring
  antenna wire.  Two-layer; the SuperMini sits at the top with its USB-C
  pointing off the top edge and its pins in 1.0 mm through-holes.
* hardware/esp32c3-cc1101-adapter  - SuperMini + a 2x4 socket for the Ebyte
  E07-M1101D-SMA CC1101 board.  Single-sided (every track on B.Cu), silk on
  both sides, M2 holes in the corners.  The SuperMini lies on its side with
  its USB-C hanging off the left edge; its pins land on keyhole pads (1.0 mm
  hole plus copper extended past the SuperMini's edge) so it can be fitted
  with header pins or soldered flat by its castellations.

Both use the same GPIO assignment (see PINMAP) so firmware can share the SPI
setup.  Routing is done by hand in this file and checked by DRC
(scripts/verify_boards.py).

GPIO choice: GPIO2/8/9 are ESP32-C3 strapping pins and GPIO8 also drives the
SuperMini LED, so radio outputs (DIO/GDO) are kept off them; the radio RESET
input is driven from GPIO8, which is safe.  GPIO20/21 (UART) are left free.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from kicadgen import Design, Footprint, Pad, Part, SymbolRef, Track, Via, fp_circle, fp_rect, fp_text, gr_line, gr_rect, gr_text  # noqa: E402

# ---------------------------------------------------------------------------
# Shared: GPIO assignment and SuperMini geometry
# ---------------------------------------------------------------------------
PINMAP = {
    "MOSI": "GPIO5",
    "SCK": "GPIO6",
    "NSS": "GPIO7",  # CSN on the CC1101
    "RESET": "GPIO8",  # SX1278 only
    "DIO0": "GPIO10",  # GDO0 on the CC1101
    "MISO": "GPIO4",
    "DIO1": "GPIO3",  # GDO2 on the CC1101
}

SM_PITCH = 2.54
SM_LEFT_X = 4.0  # left header column
SM_RIGHT_X = SM_LEFT_X + 15.24  # 19.24
SM_PIN1_Y = 4.0
SM_BODY = (SM_LEFT_X - 1.38, SM_PIN1_Y - 1.74, SM_RIGHT_X + 1.38, SM_PIN1_Y - 1.74 + 22.52)  # 2.62,2.26 .. 20.62,24.78
SM_LEFT_GPIO = ["GPIO5", "GPIO6", "GPIO7", "GPIO8", "GPIO9", "GPIO10", "GPIO20", "GPIO21"]
SM_RIGHT_GPIO = ["+5V", "GND", "+3V3", "GPIO4", "GPIO3", "GPIO2", "GPIO1", "GPIO0"]
SM_LEFT_SILK = ["5", "6", "7", "8", "9", "10", "20", "21"]  # as printed on the SuperMini
SM_RIGHT_SILK = ["5V", "G", "3.3", "4", "3", "2", "1", "0"]
SM_PAD = 1.6
SM_DRILL = 1.0
TRACK = 0.25
BOARD_W = 24.0

CONN8 = SymbolRef("Connector_Generic.kicad_sym", "Connector_Generic", "Conn_01x08")
CONN16 = SymbolRef("Connector_Generic.kicad_sym", "Connector_Generic", "Conn_01x16")
CONN1 = SymbolRef("Connector_Generic.kicad_sym", "Connector_Generic", "Conn_01x01")
CONN2X4 = SymbolRef("Connector_Generic.kicad_sym", "Connector_Generic", "Conn_02x04_Odd_Even")



def supermini_header_fp() -> Footprint:
    """1x8 row for one side of the SuperMini, pins stepping along +y, pin 1 at the origin."""
    pads = [Pad(str(i + 1), (0, i * SM_PITCH), (SM_PAD, SM_PAD), "thru_hole", "rect" if i == 0 else "circle", SM_DRILL) for i in range(8)]
    return Footprint(
        name="SuperMini_Header_1x08_P2.54mm_THT",
        descr="1x8 2.54 mm through-hole row for one side of an ESP32-C3 SuperMini (1.0 mm holes, 1.6 mm pads); pin 1 square",
        tags="ESP32-C3 SuperMini header 2.54mm",
        pads=pads,
        ref_pos=(0, -2.0, 0),
        value_pos=(0, 7 * SM_PITCH + 2.0),
    )


def sm_y(pin: int) -> float:
    return SM_PIN1_Y + (pin - 1) * SM_PITCH


def signal_net(name: str, gpio: str) -> str:
    """Net name for a SuperMini pin: the radio signal name when mapped, else the GPIO."""
    return name if name else gpio


def supermini_parts(d: Design, left_nets: dict[str, str], right_nets: dict[str, str]) -> None:
    """Add J1 (left row) and J2 (right row) of the SuperMini plus outline/silk."""
    bx, by = d.bx, d.by
    fp = supermini_header_fp()
    d.parts.append(Part("J1", fp, (bx + SM_LEFT_X, by + SM_PIN1_Y), CONN8, "Conn_01x08", left_nets, (76.2, 101.6), "ESP32-C3 SuperMini left row"))
    d.parts.append(Part("J2", fp, (bx + SM_RIGHT_X, by + SM_PIN1_Y), CONN8, "Conn_01x08", right_nets, (101.6, 101.6), "ESP32-C3 SuperMini right row"))
    x0, y0, x1, y1 = SM_BODY
    # Outline on F.Fab (the pin-name silk sits between the pads and the outline).
    d.graphics.append(gr_rect("sm_outline", bx + x0, by + y0, bx + x1, by + y1, "F.Fab", 0.12))
    d.graphics.append(gr_rect("sm_usb", bx + (x0 + x1) / 2 - 4.5, by + y0 - 1.5, bx + (x0 + x1) / 2 + 4.5, by + y0 + 5.85, "F.Fab", 0.1, "dash"))
    d.graphics.append(gr_text("sm_title", "ESP32-C3 SuperMini", bx + (x0 + x1) / 2, by + y1 - 1.2, "F.SilkS", 0.7))
    d.graphics.append(gr_text("sm_usb", "USB-C", bx + (x0 + x1) / 2, by + y0 + 1.0, "F.SilkS", 0.6))
    # ESP32 pin names (as printed on the SuperMini) outside each header row,
    # radio signal names inside it.
    for pin, gpio in enumerate(SM_LEFT_GPIO, 1):
        d.graphics.append(gr_text(f"esp_l{pin}", SM_LEFT_SILK[pin - 1], bx + SM_LEFT_X - 1.2, by + sm_y(pin), "F.SilkS", 0.6, "right"))
        net = left_nets[str(pin)]
        if net != gpio:
            d.graphics.append(gr_text(f"lbl_l{pin}", net, bx + SM_LEFT_X + 1.2, by + sm_y(pin), "F.SilkS", 0.6, "left"))
    for pin, gpio in enumerate(SM_RIGHT_GPIO, 1):
        d.graphics.append(gr_text(f"esp_r{pin}", SM_RIGHT_SILK[pin - 1], bx + SM_RIGHT_X + 1.2, by + sm_y(pin), "F.SilkS", 0.6, "left"))
        net = right_nets[str(pin)]
        if net != gpio:
            d.graphics.append(gr_text(f"lbl_r{pin}", net, bx + SM_RIGHT_X - 1.2, by + sm_y(pin), "F.SilkS", 0.6, "right"))


def supermini_nets(mapping: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """mapping: signal -> GPIO.  Returns (left pad nets, right pad nets)."""
    inv = {g: s for s, g in mapping.items()}
    left = {str(i + 1): inv.get(g, g) for i, g in enumerate(SM_LEFT_GPIO)}
    right = {str(i + 1): inv.get(g, g) for i, g in enumerate(SM_RIGHT_GPIO)}
    return left, right


# ---------------------------------------------------------------------------
# Adapter A: SuperMini + SX1278 castellated module
# ---------------------------------------------------------------------------
MOD_W, MOD_H = 16.5, 17.0  # module rotated 90 deg CW: pad row on top, ANT on the bottom edge
MOD_L, MOD_T = 3.75, 31.5
MOD_R, MOD_B = MOD_L + MOD_W, MOD_T + MOD_H
ROW_PITCH = 1.27
ROW_FIRST = 1.2  # pin 1 from the module's right edge (its top corner before rotation)
LAND = (1.0, 3.0)  # row / bottom land pads: width along the edge x length across it
NOTCH_LAND = (2.0, 0.8)
VIA_Y = MOD_T - 2.1  # 29.4: via row just above the land pads
GND_TRUNK_Y = MOD_T - 1.3  # 30.2 on B.Cu
ANT_HOLE_Y = MOD_B + 3.5

SX_PINS = ["GND", "DIO1", "DIO2", "DIO3", "+3V3", "MISO", "MOSI", "SCK", "NSS", "DIO0", "RESET", "GND", "DIO4", "DIO5", "GND", "ANT"]


def row_x(pin: int) -> float:
    """Absolute-from-board x of row pad for module pin 1..12."""
    return MOD_R - ROW_FIRST - (pin - 1) * ROW_PITCH


def sx1278_land_fp() -> Footprint:
    """Land pattern for the module in its rotated orientation, origin at the
    module's top-left corner on the carrier."""
    pads = []
    for pin in range(1, 13):
        pads.append(Pad(str(pin), (row_x(pin) - MOD_L, 0), LAND, "smd", "rect"))
    pads.append(Pad("13", (-0.5, 1.25), NOTCH_LAND, "smd", "rect"))
    pads.append(Pad("14", (-0.5, 2.7), NOTCH_LAND, "smd", "rect"))
    pads.append(Pad("15", (MOD_W - 2.8, MOD_H), LAND, "smd", "rect"))
    pads.append(Pad("16", (MOD_W - 1.4, MOD_H), LAND, "smd", "rect"))
    extra = [
        fp_rect("sx:outline", 0, 0, MOD_W, MOD_H, "F.Fab", 0.1),
        fp_text("sx:label", "SX1278 module", MOD_W / 2, MOD_H / 2, "F.Fab", 0.8),
        fp_text("sx:pin1", "1", MOD_W - ROW_FIRST + 1.0, -2.0, "F.SilkS", 0.6),
        fp_text("sx:pin12", "12", MOD_W - ROW_FIRST - 11 * ROW_PITCH - 1.4, -2.0, "F.SilkS", 0.6),
    ]
    return Footprint(
        name="SX1278_Module_16pin_Land",
        descr="Land pattern for the 16-pin castellated PXL1276-D01 style SX1278 module, rotated so the 12-pad row is along the top edge (pin 1 at the right) and ANT/GND on the bottom edge; pads extend 1.5 mm outside the module edge for soldering",
        tags="SX1278 LoRa module land pattern castellated",
        pads=pads,
        extra=extra,
        attr="smd",
        ref_pos=(MOD_W / 2, MOD_H / 2 + 1.5, 0),
        value_pos=(MOD_W / 2, MOD_H / 2 + 3.0),
    )


def antenna_hole_fp() -> Footprint:
    return Footprint(
        name="Antenna_Wire_Hole_1.0mm",
        descr="Through-hole for a spring / wire antenna, 1.0 mm drill, 2.0 mm pad",
        tags="antenna wire hole",
        pads=[Pad("1", (0, 0), (2.0, 2.0), "thru_hole", "circle", 1.0)],
        ref_pos=(0, -1.8, 0),
        value_pos=(0, 1.8),
    )


def build_sx1278() -> Design:
    d = Design(
        project="esp32c3-sx1278-adapter",
        title="ESP32-C3 SuperMini to SX1278 LoRa module adapter",
        comment="Carrier joining an ESP32-C3 SuperMini to a 16-pin castellated SX1278 433MHz module",
        fp_lib="Adapter",
        width=BOARD_W,
        height=55.0,
        thickness=1.6,
        sch_note="ESP32-C3 SuperMini (J1 left row, J2 right row) driving an SX1278 LoRa module (U2).\\nSPI: MOSI=GPIO5 SCK=GPIO6 NSS=GPIO7 MISO=GPIO4; RESET=GPIO8 DIO0=GPIO10 DIO1=GPIO3.\\nJ3 is the spring antenna wire hole.",
    )
    bx, by = d.bx, d.by
    left, right = supermini_nets(PINMAP)
    supermini_parts(d, left, right)
    d.parts.append(Part("U2", sx1278_land_fp(), (bx + MOD_L, by + MOD_T), CONN16, "SX1278_module", {str(i + 1): n for i, n in enumerate(SX_PINS)}, (127.0, 101.6), "SX1278 LoRa module"))
    d.parts.append(Part("J3", antenna_hole_fp(), (bx + MOD_R - 1.4, by + ANT_HOLE_Y), CONN1, "Antenna", {"1": "ANT"}, (152.4, 101.6), "Spring antenna"))

    T = d.tracks
    V = d.vias
    F, B = "F.Cu", "B.Cu"
    pad_in = MOD_T + 0.5  # end tracks just inside the land pads (which span MOD_T -1.5 .. +1.5)

    def left_bus(pin: int, bus_x: float, lane_y: float, target_x: float, net: str) -> None:
        T.append(Track(net, F, TRACK, [(bx + SM_LEFT_X, by + sm_y(pin)), (bx + bus_x, by + sm_y(pin)), (bx + bus_x, by + lane_y), (bx + target_x, by + lane_y), (bx + target_x, by + pad_in)]))

    # F.Cu signal lanes: upper header pins take the outer bus and the outer
    # lane; each net's pad lies further left than the pads of the nets below
    # it, so drops never cross another lane.
    left_bus(1, 6.7, 26.0, row_x(7), "MOSI")  # GPIO5 -> MOSI pad 7 (11.43)
    left_bus(2, 6.2, 26.5, row_x(8), "SCK")  # GPIO6 -> SCK pad 8 (10.16)
    left_bus(3, 5.7, 27.0, row_x(9), "NSS")  # GPIO7 -> NSS pad 9 (8.89)
    left_bus(6, 5.2, 27.5, row_x(10), "DIO0")  # GPIO10 -> DIO0 pad 10 (7.62)
    # Right column signals on F.Cu (their lanes stay right of x = 12.7).
    T.append(Track("MISO", F, TRACK, [(bx + SM_RIGHT_X, by + sm_y(4)), (bx + 17.3, by + sm_y(4)), (bx + 17.3, by + 26.0), (bx + row_x(6), by + 26.0), (bx + row_x(6), by + pad_in)]))
    T.append(Track("DIO1", F, TRACK, [(bx + SM_RIGHT_X, by + sm_y(5)), (bx + 17.8, by + sm_y(5)), (bx + row_x(2), by + pad_in)]))

    # B.Cu: power and reset, with vias just above the land pads.
    def via_to_pad(net: str, x: float) -> None:
        V.append(Via(net, (bx + x, by + VIA_Y)))
        T.append(Track(net, F, TRACK, [(bx + x, by + VIA_Y), (bx + x, by + pad_in)]))

    T.append(Track("+3V3", B, 0.4, [(bx + SM_RIGHT_X, by + sm_y(3)), (bx + 16.5, by + sm_y(3)), (bx + 16.5, by + VIA_Y), (bx + row_x(5), by + VIA_Y)]))
    via_to_pad("+3V3", row_x(5))
    T.append(Track("RESET", B, TRACK, [(bx + SM_LEFT_X, by + sm_y(4)), (bx + row_x(11), by + sm_y(4)), (bx + row_x(11), by + VIA_Y)]))
    via_to_pad("RESET", row_x(11))
    # GND: down the right edge of the board, then a trunk under the land pads.
    T.append(Track("GND", B, 0.4, [(bx + SM_RIGHT_X, by + sm_y(2)), (bx + 21.5, by + sm_y(2)), (bx + 21.5, by + GND_TRUNK_Y), (bx + row_x(12), by + GND_TRUNK_Y)]))
    for x in (row_x(1), row_x(12)):
        T.append(Track("GND", B, 0.4, [(bx + x, by + GND_TRUNK_Y), (bx + x, by + VIA_Y)]))
        via_to_pad("GND", x)
    gnd_bot_x = MOD_R - 2.8
    T.append(Track("GND", B, 0.4, [(bx + gnd_bot_x, by + GND_TRUNK_Y), (bx + gnd_bot_x, by + MOD_B - 2.3)]))
    V.append(Via("GND", (bx + gnd_bot_x, by + MOD_B - 2.3)))
    T.append(Track("GND", F, TRACK, [(bx + gnd_bot_x, by + MOD_B - 2.3), (bx + gnd_bot_x, by + MOD_B + 0.5)]))
    # Antenna: short trace from the module ANT pad to the wire hole.
    T.append(Track("ANT", F, 0.5, [(bx + MOD_R - 1.4, by + MOD_B + 0.5), (bx + MOD_R - 1.4, by + ANT_HOLE_Y)]))

    g = d.graphics
    g.append(gr_text("ant", "ANT", bx + MOD_R - 1.4 - 1.6, by + ANT_HOLE_Y, "F.SilkS", 0.6, "right"))
    g.append(gr_text("title", "ESP32-C3 + SX1278 433MHz", bx + BOARD_W / 2, by + 53.5, "F.SilkS", 0.7))
    return d


# ---------------------------------------------------------------------------
# Adapter B: SuperMini + 2x4 socket for the E07-M1101D CC1101 board
# ---------------------------------------------------------------------------
E07_PINS = {"1": "GND", "2": "+3V3", "3": "DIO0", "4": "NSS", "5": "SCK", "6": "MOSI", "7": "MISO", "8": "DIO1"}
E07_LABELS = {"1": "GND", "2": "VCC", "3": "GDO0", "4": "CSN", "5": "SCK", "6": "MOSI", "7": "MISO", "8": "GDO2"}
E07_NAMES = {"NSS": "CSN", "DIO0": "GDO0", "DIO1": "GDO2"}  # net name -> name printed on the CC1101 board

# Board geometry (mm from the board's top-left corner).
CC_W, CC_H = 27.0, 36.5
CC_OVER = 0.5  # the SuperMini body overhangs the left edge by this much, so its USB-C is clear of the board
CC_PX1 = 1.74 - CC_OVER  # x of SuperMini pin 1 in both rows (1.74 = SuperMini edge to first pin)
CC_TOP_Y = 7.0  # power row (the SuperMini's right column); its castellations face the top edge
CC_BOT_Y = CC_TOP_Y + 15.24  # GPIO row (left column)
CC_S1 = (16.48, 28.5)  # socket pin 1 (outer row, rightmost column); columns step -2.54
CC_HOLE_IN = 2.4  # mounting hole centres from the edges
CC_HOLE_D = 2.2  # M2 clearance hole
CAST_LEN, CAST_OFF = 3.4, 0.9  # keyhole pad: oval length and copper offset outboard (copper reaches 2.6 mm from the hole)
SM_EDGE = 1.38  # SuperMini pin centre to its castellated edge


def supermini_castellated_row_fp(outboard: int) -> Footprint:
    """1x8 row along +x, pin 1 at the origin, for one edge of a SuperMini that may
    either be pinned through the holes or soldered flat by its castellations.
    Each pad is a keyhole: a 1.0 mm hole at the pin with 1.6 mm wide copper
    extended outboard (outboard = -1 toward -y, +1 toward +y) to 2.6 mm from the
    hole, i.e. 1.2 mm past the SuperMini's edge, so the half-hole castellation
    lands on copper."""
    side = "Up" if outboard < 0 else "Down"
    pads = [
        Pad(str(i + 1), (i * SM_PITCH, 0), (SM_PAD, CAST_LEN), "thru_hole", "rect" if i == 0 else "oval", SM_DRILL, offset=(0, outboard * CAST_OFF))
        for i in range(8)
    ]
    return Footprint(
        name=f"SuperMini_Row_1x08_P2.54mm_THT_Castellated_{side}",
        descr=f"1x8 2.54 mm row for one edge of an ESP32-C3 SuperMini: 1.0 mm holes for header pins, 1.6 x {CAST_LEN} mm oval copper extended {side.lower()} to 2.6 mm from the hole so the SuperMini can also be soldered flat by its castellations; pin 1 square",
        tags="ESP32-C3 SuperMini castellated header 2.54mm",
        pads=pads,
        ref_pos=(-2.0, 0, 90),
        value_pos=(7 * SM_PITCH + 2.0, 0),
    )


def mounting_hole_fp() -> Footprint:
    return Footprint(
        name=f"MountingHole_{CC_HOLE_D}mm_M2",
        descr=f"M2 mounting hole, {CC_HOLE_D} mm, not plated",
        tags="mounting hole M2",
        pads=[Pad("1", (0, 0), (CC_HOLE_D, CC_HOLE_D), "np_thru_hole", "circle", CC_HOLE_D)],
        extra=[fp_circle("hole:fab", 0, 0, CC_HOLE_D / 2, "F.Fab", 0.1), fp_circle("hole:bfab", 0, 0, CC_HOLE_D / 2, "B.Fab", 0.1)],
        ref_pos=(0, -2.0, 0),
        value_pos=(0, 2.0),
    )


def e07_socket_fp() -> Footprint:
    pads = []
    for n in range(1, 9):
        col, row = (n - 1) // 2, (n - 1) % 2
        pads.append(Pad(str(n), (-col * SM_PITCH, row * SM_PITCH), (1.6, 1.6), "thru_hole", "rect" if n == 1 else "circle", 1.0))
    return Footprint(
        name="PinSocket_2x04_P2.54mm_E07",
        descr="2x4 2.54 mm socket matching the Ebyte E07-M1101D header: pin 1 square, pin 2 below it, odd pins in the outer row, columns stepping to -x",
        tags="pin socket 2.54mm 2x04 E07-M1101D",
        pads=pads,
        ref_pos=(-3 * SM_PITCH - 1.8, SM_PITCH / 2, 90),
        value_pos=(-1.5 * SM_PITCH, SM_PITCH + 2.0),
    )


def build_cc1101() -> Design:
    """Single-sided carrier with the SuperMini on its side (USB-C off the left
    edge): its right column becomes the top row (5V at the left) and its left
    column the bottom row (GPIO5 at the left), 15.24 mm apart.  The 2x4 socket
    sits below, shifted right so the plugged-in E07 board clears the bottom-left
    mounting screw.  All tracks are on B.Cu; F.Cu carries only the pad copper.

    Routing (see the constants below): MOSI, SCK and CSN drop from the GPIO row
    into three lanes and enter the socket from above; GDO0 goes straight down;
    GND and 3V3 run between the SuperMini rows, drop through gaps in the GPIO
    row and enter pin 1/2 from the right; MISO and GDO2 (radio outputs on the
    power row) go over the top of the power row, down the right of the
    SuperMini and under the socket to its left column."""
    d = Design(
        project="esp32c3-cc1101-adapter",
        title="ESP32-C3 SuperMini to CC1101 E07-M1101D adapter (single-sided)",
        comment="Single-sided carrier joining an ESP32-C3 SuperMini to an Ebyte E07-M1101D-SMA CC1101 433MHz board via a 2x4 socket",
        fp_lib="Adapter",
        width=CC_W,
        height=CC_H,
        thickness=1.6,
        sch_note="ESP32-C3 SuperMini (J1 = GPIO row, J2 = power row; through-hole or castellated) driving a CC1101 E07-M1101D board in socket J3.\\nSPI: MOSI=GPIO5 SCK=GPIO6 CSN=GPIO7 MISO=GPIO4; GDO0=GPIO10 GDO2=GPIO3.\\nH1-H4: M2 mounting holes.  Single-sided board: all tracks on B.Cu.",
    )
    bx, by = d.bx, d.by
    X = lambda v: bx + v  # noqa: E731
    Y = lambda v: by + v  # noqa: E731
    TOP, BOT = CC_TOP_Y, CC_BOT_Y
    px = lambda pin: CC_PX1 + (pin - 1) * SM_PITCH  # noqa: E731  x of SuperMini pin along a row
    sx = lambda pin: CC_S1[0] - ((pin - 1) // 2) * SM_PITCH  # noqa: E731
    sy = lambda pin: CC_S1[1] + ((pin - 1) % 2) * SM_PITCH  # noqa: E731
    SY0, SY1 = sy(1), sy(2)  # socket outer / inner row
    gap = lambda a, b: (a + b) / 2  # noqa: E731

    mapping = {k: v for k, v in PINMAP.items() if k != "RESET"}
    left, right = supermini_nets(mapping)
    d.parts.append(Part("J1", supermini_castellated_row_fp(+1), (X(px(1)), Y(BOT)), CONN8, "Conn_01x08", left, (76.2, 101.6), "ESP32-C3 SuperMini GPIO row (left column)"))
    d.parts.append(Part("J2", supermini_castellated_row_fp(-1), (X(px(1)), Y(TOP)), CONN8, "Conn_01x08", right, (101.6, 101.6), "ESP32-C3 SuperMini power row (right column)"))
    d.parts.append(Part("J3", e07_socket_fp(), (X(CC_S1[0]), Y(CC_S1[1])), CONN2X4, "E07-M1101D", E07_PINS, (127.0, 101.6), "CC1101 E07-M1101D socket"))
    hole_fp = mounting_hole_fp()
    hole_sym = SymbolRef("Mechanical.kicad_sym", "Mechanical", "MountingHole")
    corners = [(CC_HOLE_IN, CC_HOLE_IN), (CC_W - CC_HOLE_IN, CC_HOLE_IN), (CC_HOLE_IN, CC_H - CC_HOLE_IN), (CC_W - CC_HOLE_IN, CC_H - CC_HOLE_IN)]
    for i, (hx, hy) in enumerate(corners, 1):
        d.parts.append(Part(f"H{i}", hole_fp, (X(hx), Y(hy)), hole_sym, "MountingHole", {}, (152.4 + (i - 1) * 12.7, 101.6), "M2 mounting hole"))

    def track(net: str, width: float, pts: list[tuple[float, float]]) -> None:
        d.tracks.append(Track(net, "B.Cu", width, [(X(x), Y(y)) for x, y in pts]))

    # Keyhole copper reaches 2.6 mm outboard of each row, so lanes below the
    # GPIO row start at BOT + 3.05 and lanes above the power row end at TOP - 3.0.
    LANE_CSN, LANE_SCK, LANE_MOSI = BOT + 3.05, BOT + 3.55, BOT + 4.05
    track("NSS", TRACK, [(px(3), BOT), (px(3), LANE_CSN), (gap(sx(5), sx(3)), LANE_CSN), (gap(sx(5), sx(3)), SY1), (sx(4), SY1)])
    track("SCK", TRACK, [(px(2), BOT), (px(2), LANE_SCK), (sx(5), LANE_SCK), (sx(5), SY0)])
    track("MOSI", TRACK, [(px(1), BOT), (px(1), LANE_MOSI), (gap(sx(7), sx(5)), LANE_MOSI), (gap(sx(7), sx(5)), SY1), (sx(6), SY1)])
    assert abs(px(6) - sx(3)) < 1e-9, "GDO0 drops straight into socket pin 3"
    track("DIO0", TRACK, [(px(6), BOT), (sx(3), SY0)])
    # Power: between the rows, then down through the gaps right of GPIO10.
    GND_Y, V33_Y = TOP + 2.0, TOP + 1.3
    track("GND", 0.4, [(px(2), TOP), (px(2), GND_Y), (gap(px(6), px(7)), GND_Y), (gap(px(6), px(7)), SY0), (sx(1), SY0)])
    track("+3V3", 0.4, [(px(3), TOP), (px(3), V33_Y), (gap(px(7), px(8)), V33_Y), (gap(px(7), px(8)), SY1), (sx(2), SY1)])
    # Radio outputs: over the top, down the right, under the socket, into its left column.
    OVER_GDO2, OVER_MISO = TOP - 3.0, TOP - 3.5
    RIGHT_GDO2, RIGHT_MISO = px(8) + 1.18, px(8) + 1.63
    UNDER_GDO2, UNDER_MISO = SY1 + 1.3, SY1 + 1.8
    MISO_UP_X = sx(7) - 1.3
    track("DIO1", TRACK, [(px(5), TOP), (px(5), OVER_GDO2), (RIGHT_GDO2, OVER_GDO2), (RIGHT_GDO2, UNDER_GDO2), (sx(8), UNDER_GDO2), (sx(8), SY1)])
    track("MISO", TRACK, [(px(4), TOP), (px(4), OVER_MISO), (RIGHT_MISO, OVER_MISO), (RIGHT_MISO, UNDER_MISO), (MISO_UP_X, UNDER_MISO), (MISO_UP_X, SY0), (sx(7), SY0)])

    # -- silkscreen, front and back ------------------------------------------
    g = d.graphics
    MIRROR = {None: "mirror", "left": "right mirror", "right": "left mirror"}

    def silk(key: str, text: str, x: float, y: float, size: float, justify: str | None = None, angle: float = 0) -> None:
        """Text on both silk layers; the back copy is mirrored about its anchor
        so it reads correctly from the back and keeps its side of the anchor."""
        g.append(gr_text(f"{key}:f", text, X(x), Y(y), "F.SilkS", size, justify, angle))
        g.append(gr_text(f"{key}:b", text, X(x), Y(y), "B.SilkS", size, MIRROR[justify], (-angle) % 360))

    def both(fn, key: str, coords: tuple[float, ...], width: float, layers: tuple[str, str] = ("F.SilkS", "B.SilkS"), **kw) -> None:
        """A gr_line / gr_rect on a pair of layers (front and back)."""
        for suffix, layer in zip("fb", layers):
            g.append(fn(f"{key}:{suffix}", *(X(v) if i % 2 == 0 else Y(v) for i, v in enumerate(coords)), layer, width, **kw))

    # SuperMini body: full outline on the fab layers; on silk only the right end
    # (the long edges would cross the keyhole pads).
    x0, y0, x1, y1 = px(1) - 1.74, TOP - SM_EDGE, px(1) - 1.74 + 22.52, BOT + SM_EDGE
    both(gr_line, "sm_top", (0.0, y0, x1, y0), 0.1, layers=("F.Fab", "B.Fab"))
    both(gr_line, "sm_bot", (0.0, y1, x1, y1), 0.1, layers=("F.Fab", "B.Fab"))
    both(gr_line, "sm_right", (x1, y0, x1, y1), 0.1, layers=("F.Fab", "B.Fab"))
    both(gr_rect, "sm_usb", (0.2, (y0 + y1) / 2 - 4.5, x0 + 5.85, (y0 + y1) / 2 + 4.5), 0.1, layers=("F.Fab", "B.Fab"), stype="dash")
    both(gr_line, "sm_silk_right", (x1, y0, x1, y1), 0.12)
    both(gr_line, "sm_silk_tr", (px(8) + 1.05, y0, x1, y0), 0.12)
    both(gr_line, "sm_silk_br", (px(8) + 1.05, y1, x1, y1), 0.12)
    silk("sm_title", "ESP32-C3 SuperMini", (x0 + x1) / 2, (y0 + y1) / 2, 0.7)
    silk("sm_usb", "USB-C", x0 + 2.2, (y0 + y1) / 2 + 1.2, 0.6)
    # ESP32 pin names (as printed on the SuperMini) outside each row, beyond the
    # keyhole copper; radio signal names inside the rows.
    for pin in range(1, 9):
        silk(f"esp_t{pin}", SM_RIGHT_SILK[pin - 1], px(pin), TOP - 3.1, 0.5)
        silk(f"esp_b{pin}", SM_LEFT_SILK[pin - 1], px(pin), BOT + 3.1, 0.5)
        if right[str(pin)] != SM_RIGHT_GPIO[pin - 1]:
            silk(f"sig_t{pin}", E07_NAMES.get(right[str(pin)], right[str(pin)]), px(pin), TOP + 2.7, 0.5, None, 90)
        if left[str(pin)] != SM_LEFT_GPIO[pin - 1]:
            silk(f"sig_b{pin}", E07_NAMES.get(left[str(pin)], left[str(pin)]), px(pin), BOT - 2.7, 0.5, None, 90)
    # Socket.
    both(gr_rect, "sockbox", (sx(7) - 1.3, SY0 - 1.3, sx(1) + 1.3, SY1 + 1.3), 0.12)
    silk("sock1", "1", sx(1) + 1.9, SY0, 0.6, "left")
    silk("sock2", "2", sx(1) + 1.9, SY1, 0.6, "left")
    for n, lab in E07_LABELS.items():
        pin = int(n)
        silk(f"socklbl{n}", lab, sx(pin), SY0 - 2.0 if pin % 2 else SY1 + 2.0, 0.5)
    silk("sockname", "CC1101 E07-M1101D", gap(sx(7), sx(1)), CC_H - 1.3, 0.7)
    # Board title in the strip right of the SuperMini.
    silk("title", "ESP32-C3 + CC1101 433MHz", CC_W - 2.8, CC_H / 2, 0.7, None, 90)
    g.append(gr_text("ss:f", "single-sided: copper on back", X(CC_W - 1.3), Y(CC_H / 2), "F.SilkS", 0.5, None, 90))
    g.append(gr_text("ss:b", "single-sided: copper this side", X(CC_W - 1.3), Y(CC_H / 2), "B.SilkS", 0.5, "mirror", 270))
    return d


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=pathlib.Path, default=pathlib.Path(__file__).resolve().parent.parent / "hardware")
    args = ap.parse_args()
    for d in (build_sx1278(), build_cc1101()):
        d.write(args.out / d.project)


if __name__ == "__main__":
    main()

#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Generate two small carrier boards that connect an ESP32-C3 SuperMini to a
433 MHz radio module:

* hardware/esp32c3-sx1278-adapter  - SuperMini + the 16-pin castellated
  SX1278 LoRa module (soldered onto SMD land pads) + a hole for the spring
  antenna wire.
* hardware/esp32c3-cc1101-adapter  - SuperMini + a 2x4 socket for the Ebyte
  E07-M1101D-SMA CC1101 board (which stands upright in the socket).  This
  board is single-sided: every track is on the back (B.Cu; the front carries
  only the through-hole pad rings), and the SuperMini lies sideways (USB-C
  off the left edge) so that its GPIO row sits directly above the socket and
  its power row behind it, which is what makes the eight nets routable on
  one layer.

Both use the same GPIO assignment (see PINMAP) so firmware can share the SPI
setup.  The SuperMini sits at the top of each board with its USB-C connector
pointing off the top edge; its pins go into 1.0 mm through-holes so it can be
soldered directly or fitted with headers.

Routing is done by hand in this file: signal nets run on F.Cu in horizontal
lanes below the SuperMini's antenna, power runs on B.Cu, and vias join B.Cu
nets to the SMD module pads.  DRC (scripts/verify_boards.py) checks the
result.

GPIO choice: GPIO2/8/9 are ESP32-C3 strapping pins and GPIO8 also drives the
SuperMini LED, so radio outputs (DIO/GDO) are kept off them; the radio RESET
input is driven from GPIO8, which is safe.  GPIO20/21 (UART) are left free.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from kicadgen import Design, Footprint, Pad, Part, SymbolRef, Track, Via, fp_rect, fp_text, gr_rect, gr_text  # noqa: E402

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


BACK_ONLY = ("B.Cu", "B.Mask")  # pad layers for a single-sided board (copper on the solder side)


def supermini_header_fp(along: str = "y", layers: tuple[str, ...] | None = None) -> Footprint:
    """1x8 row for one side of the SuperMini; pins step along +y (SuperMini
    upright) or +x (SuperMini on its side); pin 1 at the origin."""
    step = (0, SM_PITCH) if along == "y" else (SM_PITCH, 0)
    pads = [Pad(str(i + 1), (i * step[0], i * step[1]), (SM_PAD, SM_PAD), "thru_hole", "rect" if i == 0 else "circle", SM_DRILL, layers=layers) for i in range(8)]
    suffix = ("_Row" if along == "x" else "") + ("_SingleSided" if layers else "")
    return Footprint(
        name=f"SuperMini_Header_1x08_P2.54mm_THT{suffix}",
        descr="1x8 2.54 mm through-hole row for one side of an ESP32-C3 SuperMini (1.0 mm holes, 1.6 mm pads); pin 1 square"
        + ("; copper on B.Cu only (single-sided board)" if layers else ""),
        tags="ESP32-C3 SuperMini header 2.54mm",
        pads=pads,
        ref_pos=(0, -2.0, 0) if along == "y" else (-2.0, 0, 90),
        value_pos=(0, 7 * SM_PITCH + 2.0) if along == "y" else (7 * SM_PITCH + 2.0, 0),
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
E07_PIN1 = (15.81, 30.0)  # socket pin 1; odd pins in the row at y=30, even pins 2.54 below
E07_PINS = {"1": "GND", "2": "+3V3", "3": "DIO0", "4": "NSS", "5": "SCK", "6": "MOSI", "7": "MISO", "8": "DIO1"}
E07_LABELS = {"1": "GND", "2": "VCC", "3": "GDO0", "4": "CSN", "5": "SCK", "6": "MOSI", "7": "MISO", "8": "GDO2"}


def e07_socket_fp(layers: tuple[str, ...] | None = None) -> Footprint:
    pads = []
    for n in range(1, 9):
        col, row = (n - 1) // 2, (n - 1) % 2
        pads.append(Pad(str(n), (-col * SM_PITCH, row * SM_PITCH), (1.6, 1.6), "thru_hole", "rect" if n == 1 else "circle", 1.0, layers=layers))
    return Footprint(
        name="PinSocket_2x04_P2.54mm_E07" + ("_SingleSided" if layers else ""),
        descr="2x4 2.54 mm socket matching the Ebyte E07-M1101D header: pin 1 square, pin 2 below it, odd pins in the outer row, columns stepping to -x"
        + ("; copper on B.Cu only (single-sided board)" if layers else ""),
        tags="pin socket 2.54mm 2x04 E07-M1101D",
        pads=pads,
        ref_pos=(-3 * SM_PITCH - 1.8, SM_PITCH / 2, 90),
        value_pos=(-1.5 * SM_PITCH, SM_PITCH + 2.0),
    )


def e07_x(pin: int) -> float:
    return E07_PIN1[0] - ((pin - 1) // 2) * SM_PITCH


def e07_y(pin: int) -> float:
    return E07_PIN1[1] + ((pin - 1) % 2) * SM_PITCH


def build_cc1101() -> Design:
    """Single-sided carrier.  The SuperMini lies on its side with USB-C off
    the left edge: its right column becomes the top row (5V at the left) and
    its left column the bottom row (GPIO5 at the left), 15.24 mm apart.  The
    2x4 socket sits below with pin 7 (MISO) under GPIO5.  All tracks are on
    B.Cu; F.Cu carries only the through-hole pad rings, so the board can be
    made single-sided from the B.Cu artwork alone."""
    d = Design(
        project="esp32c3-cc1101-adapter",
        title="ESP32-C3 SuperMini to CC1101 E07-M1101D adapter (single-sided)",
        comment="Single-sided carrier joining an ESP32-C3 SuperMini to an Ebyte E07-M1101D-SMA CC1101 433MHz board via a 2x4 socket",
        fp_lib="Adapter",
        width=30.0,
        height=38.0,
        thickness=1.6,
        sch_note="ESP32-C3 SuperMini (J1 = GPIO row, J2 = power row) driving a CC1101 E07-M1101D board in socket J3.\\nSPI: MOSI=GPIO5 SCK=GPIO6 CSN=GPIO7 MISO=GPIO4; GDO0=GPIO10 GDO2=GPIO3.\\nSingle-sided board: all copper on B.Cu.",
    )
    bx, by = d.bx, d.by
    XO = 2.0  # everything shifted right so the standing CC1101 board stays inside the outline
    X = lambda v: bx + XO + v  # noqa: E731
    Y = lambda v: by + v  # noqa: E731
    TOP_Y, BOT_Y = 4.0, 4.0 + 15.24  # SuperMini rows: right column on top, left column below
    px = lambda pin: 4.0 + (pin - 1) * SM_PITCH  # noqa: E731  x of SuperMini pin along a row
    mapping = {k: v for k, v in PINMAP.items() if k != "RESET"}
    left, right = supermini_nets(mapping)
    fp = supermini_header_fp("x")
    d.parts.append(Part("J1", fp, (X(px(1)), Y(BOT_Y)), CONN8, "Conn_01x08", left, (76.2, 101.6), "ESP32-C3 SuperMini GPIO row (left column)"))
    d.parts.append(Part("J2", fp, (X(px(1)), Y(TOP_Y)), CONN8, "Conn_01x08", right, (101.6, 101.6), "ESP32-C3 SuperMini power row (right column)"))
    # Socket: pin 7 under GPIO5 (x = 4.0), pin 1 at x = 11.62; outer row y = 30.
    S1 = (11.62, 30.0)
    d.parts.append(Part("J3", e07_socket_fp(), (X(S1[0]), Y(S1[1])), CONN2X4, "E07-M1101D", E07_PINS, (127.0, 101.6), "CC1101 E07-M1101D socket"))
    sx = lambda pin: S1[0] - ((pin - 1) // 2) * SM_PITCH  # noqa: E731
    sy = lambda pin: S1[1] + ((pin - 1) % 2) * SM_PITCH  # noqa: E731

    def track(net: str, width: float, pts: list[tuple[float, float]]) -> None:
        d.tracks.append(Track(net, "B.Cu", width, [(X(x), Y(y)) for x, y in pts]))

    # GPIO row (y = 19.24) straight down into the socket; inner-row pads are
    # reached through the gaps between the outer-row pads.
    track("SCK", TRACK, [(px(2), BOT_Y), (sx(5), sy(5))])
    track("MOSI", TRACK, [(px(1), BOT_Y), (px(1), 24.0), (5.27, 24.0), (5.27, sy(6)), (sx(6), sy(6))])
    track("NSS", TRACK, [(px(3), BOT_Y), (px(3), 24.5), (7.81, 24.5), (7.81, sy(4)), (sx(4), sy(4))])
    track("DIO0", TRACK, [(px(6), BOT_Y), (px(6), 25.0), (sx(3), 25.0), (sx(3), sy(3))])
    # Power row (y = 4.0): GND and 3V3 run between the rows, drop through gaps
    # in the GPIO row right of the signals, and enter pads 1 / 2 from the right.
    track("GND", 0.4, [(px(2), TOP_Y), (px(2), 6.0), (17.97, 6.0), (17.97, sy(1)), (sx(1), sy(1))])
    track("+3V3", 0.4, [(px(3), TOP_Y), (px(3), 5.3), (20.51, 5.3), (20.51, sy(2)), (sx(2), sy(2))])
    # MISO and GDO2 (radio outputs) go over the top of the power row and down
    # the left edge to the socket's left column.
    track("MISO", TRACK, [(px(4), TOP_Y), (px(4), 2.2), (2.2 - XO + 1.6, 2.2), (2.2 - XO + 1.6, sy(7)), (sx(7), sy(7))])
    track("DIO1", TRACK, [(px(5), TOP_Y), (px(5), 1.6), (1.6 - XO + 1.0, 1.6), (1.6 - XO + 1.0, sy(8)), (sx(8), sy(8))])

    g = d.graphics
    x0, y0, x1, y1 = px(1) - 1.74, TOP_Y - 1.38, px(1) - 1.74 + 22.52, BOT_Y + 1.38
    g.append(gr_rect("sm_outline", X(x0), Y(y0), X(x1), Y(y1), "F.SilkS", 0.12))
    g.append(gr_rect("sm_usb", X(x0) - 1.5, Y((y0 + y1) / 2 - 4.5), X(x0) + 5.85, Y((y0 + y1) / 2 + 4.5), "F.Fab", 0.1, "dash"))
    g.append(gr_text("sm_title", "ESP32-C3 SuperMini", X((x0 + x1) / 2), Y((y0 + y1) / 2), "F.SilkS", 0.7))
    g.append(gr_text("sm_usb", "USB-C", X(x0) + 2.2, Y((y0 + y1) / 2 + 1.2), "F.SilkS", 0.6))
    for pin in range(1, 9):
        g.append(gr_text(f"esp_t{pin}", SM_RIGHT_SILK[pin - 1], X(px(pin)), Y(TOP_Y - 2.0), "F.SilkS", 0.5))
        g.append(gr_text(f"esp_b{pin}", SM_LEFT_SILK[pin - 1], X(px(pin)), Y(BOT_Y + 2.0), "F.SilkS", 0.5))
        if right[str(pin)] != SM_RIGHT_GPIO[pin - 1]:
            g.append(gr_text(f"sig_t{pin}", right[str(pin)], X(px(pin)), Y(TOP_Y + 2.7), "F.SilkS", 0.5, None, 90))
        if left[str(pin)] != SM_LEFT_GPIO[pin - 1]:
            g.append(gr_text(f"sig_b{pin}", left[str(pin)], X(px(pin)), Y(BOT_Y - 2.7), "F.SilkS", 0.5, None, 90))
    g.append(gr_rect("sockbox", X(sx(7) - 1.3), Y(sy(1) - 1.3), X(sx(1) + 1.3), Y(sy(2) + 1.3), "F.SilkS", 0.12))
    g.append(gr_text("sock1", "1", X(sx(1) + 1.9), Y(sy(1)), "F.SilkS", 0.6, "left"))
    g.append(gr_text("sock2", "2", X(sx(1) + 1.9), Y(sy(2)), "F.SilkS", 0.6, "left"))
    for n, lab in E07_LABELS.items():
        pin = int(n)
        g.append(gr_text(f"socklbl{n}", lab, X(sx(pin)), Y(sy(1) - 2.0 if pin % 2 else sy(2) + 2.0), "F.SilkS", 0.5))
    g.append(gr_text("sockname", "CC1101 E07-M1101D", X(sx(4)), Y(36.6), "F.SilkS", 0.7))
    legend = ["GPIO5  MOSI", "GPIO6  SCK", "GPIO7  CSN", "GPIO10 GDO0", "GPIO4  MISO", "GPIO3  GDO2"]
    for i, line in enumerate(legend):
        g.append(gr_text(f"legend{i}", line, X(16.0), Y(27.5 + i * 1.3), "F.SilkS", 0.6, "left"))
    g.append(gr_text("ss", "single-sided: copper on back", X(16.0), Y(35.6), "F.SilkS", 0.5, "left"))
    return d


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=pathlib.Path, default=pathlib.Path(__file__).resolve().parent.parent / "hardware")
    args = ap.parse_args()
    for d in (build_sx1278(), build_cc1101()):
        d.write(args.out / d.project)


if __name__ == "__main__":
    main()

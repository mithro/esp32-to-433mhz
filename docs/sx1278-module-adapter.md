# SX1278 castellated module and its adapter

A second carrier, `hardware/esp32c3-sx1278-adapter`, takes the 16-pin
castellated SX1278 module (PXL1276-D01) instead of a socketed board. It uses
the socket adapter's GPIOs, with MOSI and SCK swapped so that its bottom
copper routes.  Its signals also keep clear of the boot straps: NSS, DIO0
and RESET moved off GPIO9/GPIO10/GPIO8 to GPIO10/GPIO20/GPIO21 (GPIO8 and
GPIO9 are left unused), for the same reset-into-download reason as the
socket adapter:

| Signal | ESP32-C3 GPIO | SX1278 module pin |
| --- | --- | --- |
| MOSI | GPIO3 | 7 MOSI |
| SCK | GPIO4 | 8 SCK |
| Chip select | GPIO10 | 9 NSS |
| MISO | GPIO7 | 6 MISO |
| IRQ / packet | GPIO20 | 10 DIO0 |
| Second IRQ | GPIO6 | 2 DIO1 |
| Reset | GPIO21 | 11 RESET |
| 3.3 V | 3V3 | 5 VCC |
| GND | GND | 1, 12, 15 GND |
| Radio-type strap | GPIO5 | tied to 3V3 (reads high) |

This adapter is two-layer: the GPIO-column signals (DIO1, MISO, NSS, DIO0,
RESET) run on the top copper in nested horizontal lanes below the SuperMini
(the GPIO order matches the module's pad order, so no lane crosses another),
while power, MOSI and SCK run on the bottom copper, with vias to the SMD
module pads. GPIO5 is hard-wired to 3V3 (silk "ID=3V3") so the
[radio-type strap](design-notes.md#radio-type-strap-jp1-r1) reads high here.
Its manufacturing packages are built alongside the pin-header adapter's.

## The adapter board

| 3D render, top | 3D render, bottom | Layout (copper, silk, fab, outline) |
| --- | --- | --- |
| ![3D render of the top side](images/esp32c3-sx1278-adapter-3d-top.png) | ![3D render of the bottom side](images/esp32c3-sx1278-adapter-3d-bottom.png) | ![2D layout plot](images/esp32c3-sx1278-adapter-layout.png) |

`hardware/esp32c3-sx1278-adapter`, 24 x 58 mm. The SuperMini sits at the top
with its USB-C pointing off the top edge. The
[SX1278 module](component-boards.md#sx1278-lora-module-castellated) is soldered onto SMD land pads that
reproduce its castellations (1.0 x 3.0 mm pads extending 1.5 mm outside the
module edge), rotated so its 12-pad row faces the SuperMini and its ANT pad
faces the bottom edge. The antenna trace runs to a 1.0 mm hole for a spring
antenna wire (J3) and on to pads for an optional edge-mount SMA jack on the
bottom edge (J4, same footprint as the E07-M1101D's jack); fit one or the
other. DIO2-5 are landed but not connected -- including DIO2, the pin the
raw bitstream leaves the chip on, which the socket adapter reaches through
[J5](design-notes.md#the-dio2-fly-wire-header). This adapter's pin allocation is to be
brought into line with the socket adapter's, and DIO2 routed, in a separate
pass; its GPIOs currently differ from the socket adapter's in every signal
but MISO (GPIO7) and the radio-type strap (GPIO5).

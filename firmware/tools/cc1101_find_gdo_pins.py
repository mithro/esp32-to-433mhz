#!/usr/bin/env python3
"""Find which Raspberry Pi GPIOs the CC1101's GDO0 / GDO2 pins are wired to.

Runs ON rpi5-433mhz with the system python3 (python3-spidev + python3-libgpiod
are Debian packages there). Deploy next to cc1101.py:

    scp hardware/devices/tools/cc1101.py hardware/devices/esp32c3-cc1101-node/tools/cc1101_find_gdo_pins.py rpi5-433mhz:~/cc1101-node/
    ssh rpi5-433mhz 'cd ~/cc1101-node && python3 cc1101_find_gdo_pins.py'

Method (non-invasive): the CC1101 can drive each GDO pin to a constant level
from its IOCFGx register (GDOx_CFG 0x2F = hard-wired 0; 0x6F = the same with
the invert bit = hard-wired 1). We set GDO2 high / GDO0 low, sample every free
header GPIO as an input, then swap the levels and sample again. The GPIO that
follows GDO2's level is GDO2's pin, the one that follows GDO0's level is GDO0's
pin; anything else is not connected to a GDO. Nothing is driven by the Pi.
"""
import glob
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cc1101 import CC1101, IOCFG2, IOCFG0   # noqa: E402
import gpiod                                 # noqa: E402
from gpiod.line import Direction             # noqa: E402

HW_LOW, HW_HIGH = 0x2F, 0x6F
# J8 GPIOs that are NOT SPI0 (8,9,10,11 are the CC1101 SPI lines, held by spidev)
CANDIDATES = [2, 3, 4, 5, 6, 7, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27]
GPIO_PIN = {2: 3, 3: 5, 4: 7, 5: 29, 6: 31, 7: 26, 12: 32, 13: 33, 14: 8, 15: 10, 16: 36, 17: 11, 18: 12,
            19: 35, 20: 38, 21: 40, 22: 15, 23: 16, 24: 18, 25: 22, 26: 37, 27: 13}


def find_rp1_chip():
    for path in sorted(glob.glob("/dev/gpiochip*")):
        with gpiod.Chip(path) as chip:
            if chip.get_info().label == "pinctrl-rp1":
                return path
    raise SystemExit("no pinctrl-rp1 gpiochip found - is this a Pi 5?")


def sample(chip, offsets):
    """Read each candidate as an input; skip lines the kernel already owns."""
    out = {}
    for off in offsets:
        try:
            with gpiod.request_lines(chip, consumer="cc1101-find-gdo",
                                     config={off: gpiod.LineSettings(direction=Direction.INPUT)}) as req:
                out[off] = int(req.get_value(off).value)
        except OSError as e:
            out[off] = "busy(%s)" % e.errno
    return out


def main():
    c = CC1101(bus=0, device=0, spi_hz=500_000)
    c.reset()
    partnum, version = c.identify()
    print("CC1101 partnum=0x%02X version=0x%02X" % (partnum, version))
    if partnum != 0x00:
        raise SystemExit("CC1101 not detected")
    chip = find_rp1_chip()
    results = {}
    for label, gdo2, gdo0 in (("A: GDO2=1 GDO0=0", HW_HIGH, HW_LOW), ("B: GDO2=0 GDO0=1", HW_LOW, HW_HIGH)):
        c.write_reg(IOCFG2, gdo2)
        c.write_reg(IOCFG0, gdo0)
        time.sleep(0.01)
        results[label] = sample(chip, CANDIDATES)
        print(label, " ".join("GPIO%d=%s" % (k, v) for k, v in results[label].items()))
    a, b = results["A: GDO2=1 GDO0=0"], results["B: GDO2=0 GDO0=1"]
    gdo2 = [g for g in CANDIDATES if a[g] == 1 and b[g] == 0]
    gdo0 = [g for g in CANDIDATES if a[g] == 0 and b[g] == 1]
    # restore the defaults the drivers expect (GDO2=CHIP_RDY, GDO0=high-Z)
    c.write_reg(IOCFG2, 0x29)
    c.write_reg(IOCFG0, 0x2E)
    print()
    print("GDO2 -> %s" % (", ".join("GPIO%d (header pin %d)" % (g, GPIO_PIN[g]) for g in gdo2) or "NOT FOUND"))
    print("GDO0 -> %s" % (", ".join("GPIO%d (header pin %d)" % (g, GPIO_PIN[g]) for g in gdo0) or "NOT FOUND"))
    floating = [g for g in CANDIDATES if a[g] != b[g] and g not in gdo2 + gdo0]
    if floating:
        print("note: these GPIOs changed between samples but not in step with a GDO (floating?): %s" % floating)


if __name__ == "__main__":
    main()

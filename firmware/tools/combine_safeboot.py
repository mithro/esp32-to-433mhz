#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# ///
"""Merge the main CC1101-node firmware and the stock Tasmota safeboot image into a
single flashable factory image for the ESP32-C3.

SPDX-License-Identifier: Apache-2.0

    uv run firmware/tools/combine_safeboot.py

Why a combined image: the node's partition table (esp32_partition_app2880k_fs320k.csv)
reserves three app-relevant slots -- `otadata`, a `safeboot` factory slot (0x10000), and
`app0`/ota_0 (0xE0000). The plain `.factory.bin` populates only app0 and leaves the
safeboot slot blank, so there is no fallback if app0 is ever bad. This tool writes BOTH
slots plus an otadata that boots app0 by default, so a single `esptool write_flash 0x0`
lays down a node that self-recovers over WiFi (Tasmota safeboot) from a failed OTA, a
corrupt app0, or an invalid otadata -- no BOOT button needed for those cases. See
firmware/docs/bootloader-recovery.md for the full recovery matrix.

The merge is a pure-Python flat-image build (identical result to `esptool merge_bin`):
each component is placed at its flash offset in a 0xFF-filled buffer. Offsets for the
safeboot/app0/otadata slots are read from the built partitions.bin (the source of truth),
not hardcoded, so a future partition-table change is picked up automatically or fails loudly.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.dirname(HERE)                       # firmware/
CLONE = os.path.join(FW, "build", "Tasmota")
PIO = os.path.join(CLONE, ".pio", "build")
DIST = os.path.join(FW, "dist")

BOOTLOADER_OFFSET = 0x0                           # esp32c3: bootloader lives at 0x0
PARTTABLE_OFFSET = 0x8000                         # CONFIG_PARTITION_TABLE_OFFSET
APP_MAGIC = 0xE9                                  # esp-idf app/bootloader image first byte

PART_MAGIC = 0x50AA
PART_TYPE_APP = 0x00
PART_TYPE_DATA = 0x01
SUBTYPE_FACTORY = 0x00                            # app,factory -> the safeboot slot
SUBTYPE_OTA_0 = 0x10                              # app,ota_0   -> the main app slot (app0)
SUBTYPE_DATA_OTA = 0x00                           # data,ota    -> otadata


def parse_partitions(path):
    """Return {label: (type, subtype, offset, size)} from a built partitions.bin."""
    data = open(path, "rb").read()
    out = {}
    for i in range(0, len(data), 32):
        entry = data[i:i + 32]
        if len(entry) < 32:
            break
        magic = struct.unpack("<H", entry[0:2])[0]
        if magic != PART_MAGIC:
            break                                # MD5 entry (0xEBEB) or 0xFF padding -> end
        ptype, subtype = entry[2], entry[3]
        offset, size = struct.unpack("<II", entry[4:12])
        label = entry[12:28].split(b"\x00", 1)[0].decode("ascii", "replace")
        out[label] = (ptype, subtype, offset, size)
    return out


def find_by_subtype(parts, ptype, subtype):
    for label, (t, s, off, size) in parts.items():
        if t == ptype and s == subtype:
            return label, off, size
    return None


def find_boot_app0():
    """Locate the framework's boot_app0.bin (otadata content that selects ota_0)."""
    root = os.path.expanduser("~/.platformio/packages")
    for base, _dirs, files in os.walk(root):
        if "framework-arduinoespressif32" in base and "boot_app0.bin" in files:
            return os.path.join(base, "boot_app0.bin")
    return None


def read_app(path, what):
    if not os.path.exists(path):
        sys.exit("missing %s: %s" % (what, path))
    blob = open(path, "rb").read()
    if not blob or blob[0] != APP_MAGIC:
        sys.exit("%s (%s) does not start with the esp-idf image magic 0xE9" % (what, path))
    return blob


def place(buf, written, offset, blob, slot_size, name):
    """Write blob at offset into buf (0xFF-padded), refusing to overlap a prior write.

    Overlap is tracked by explicit written intervals, not by inspecting bytes: 0xFF and 0x00
    are both legal image content, so content inspection cannot tell padding from real data.
    """
    end = offset + len(blob)
    if slot_size is not None and len(blob) > slot_size:
        sys.exit("%s is %d bytes, does not fit its %d-byte slot at 0x%X"
                 % (name, len(blob), slot_size, offset))
    for w_start, w_end, w_name in written:
        if offset < w_end and end > w_start:
            sys.exit("overlap: %s [0x%X,0x%X) collides with %s [0x%X,0x%X)"
                     % (name, offset, end, w_name, w_start, w_end))
    if end > len(buf):
        buf.extend(b"\xff" * (end - len(buf)))
    buf[offset:end] = blob
    written.append((offset, end, name))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--main-env", default="tasmota32c3-cc1101")
    ap.add_argument("--safeboot-env", default="tasmota32c3-safeboot")
    ap.add_argument("--out", default=os.path.join(DIST, "tasmota32c3-cc1101-combined.factory.bin"))
    args = ap.parse_args()

    main_dir = os.path.join(PIO, args.main_env)
    sb_dir = os.path.join(PIO, args.safeboot_env)

    parts = parse_partitions(os.path.join(main_dir, "partitions.bin"))
    factory = find_by_subtype(parts, PART_TYPE_APP, SUBTYPE_FACTORY)     # safeboot slot
    ota0 = find_by_subtype(parts, PART_TYPE_APP, SUBTYPE_OTA_0)          # main app slot
    otadata = find_by_subtype(parts, PART_TYPE_DATA, SUBTYPE_DATA_OTA)
    if not (factory and ota0 and otadata):
        sys.exit("partition table missing a required slot (factory/ota_0/otadata): %r" % (parts,))
    _, factory_off, factory_size = factory
    _, ota0_off, ota0_size = ota0
    _, otadata_off, otadata_size = otadata

    bootloader = read_app(os.path.join(main_dir, "bootloader.bin"), "bootloader")
    parttable = open(os.path.join(main_dir, "partitions.bin"), "rb").read()
    boot_app0_path = find_boot_app0()
    if not boot_app0_path:
        sys.exit("could not find framework boot_app0.bin (otadata initialiser)")
    boot_app0 = open(boot_app0_path, "rb").read()
    safeboot = read_app(os.path.join(sb_dir, "firmware.bin"), "safeboot app")
    mainapp = read_app(os.path.join(main_dir, "firmware.bin"), "main app")

    buf = bytearray()
    written = []
    place(buf, written, BOOTLOADER_OFFSET, bootloader, None, "bootloader")
    place(buf, written, PARTTABLE_OFFSET, parttable, 0x1000, "partition-table")
    place(buf, written, otadata_off, boot_app0, otadata_size, "otadata(boot_app0->ota_0)")
    place(buf, written, factory_off, safeboot, factory_size, "safeboot(factory)")
    place(buf, written, ota0_off, mainapp, ota0_size, "main(app0/ota_0)")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    open(args.out, "wb").write(buf)
    sha = hashlib.sha256(buf).hexdigest()

    print("combined factory image: %s" % args.out)
    print("  size            : %d bytes (0x%X)" % (len(buf), len(buf)))
    print("  sha256          : %s" % sha)
    print("  bootloader      @ 0x%06X (%d B)" % (BOOTLOADER_OFFSET, len(bootloader)))
    print("  partition-table @ 0x%06X (%d B)" % (PARTTABLE_OFFSET, len(parttable)))
    print("  otadata         @ 0x%06X -> boots ota_0 (app0)" % otadata_off)
    print("  safeboot        @ 0x%06X (%d / %d B slot)" % (factory_off, len(safeboot), factory_size))
    print("  main app        @ 0x%06X (%d / %d B slot)" % (ota0_off, len(mainapp), ota0_size))


if __name__ == "__main__":
    main()

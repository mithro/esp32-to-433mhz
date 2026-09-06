#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# ///
"""Produce a factory image whose safeboot slot holds OUR locally-built, pinned safeboot.

SPDX-License-Identifier: Apache-2.0

    uv run firmware/tools/combine_safeboot.py

Context (source-verified 2026-09-06): Tasmota's own build step (pio-tools/post_esp32.py)
ALREADY merges a safeboot image into the `factory` slot of every `<env>.factory.bin` -- so the
stock `tasmota32c3-cc1101.factory.bin` already self-recovers over WiFi (Tasmota safeboot) from a
failed OTA / invalid otadata without the BOOT button. See firmware/docs/bootloader-recovery.md
for the honest recovery matrix and its limits (no in-place-corrupt-app0 fallback under
CONFIG_BOOTLOADER_SKIP_VALIDATE_ALWAYS; no IDF anti-rollback on the pinned framework).

The ONE thing this tool adds: the stock factory.bin's safeboot is FETCHED from
ota.tasmota.com/release at build time (an unpinned network binary). This tool swaps that for our
own `tasmota32c3-safeboot` image, built from the SAME pinned Tasmota SHA -- reproducible,
offline-buildable, and audited from source rather than trusting a downloaded blob. That is a
boot-safety/reproducibility improvement consistent with the rest of this pinned build; it does NOT
add a recovery path the stock image lacks.

Implementation: operate purely on the reliably-built dist artifacts (the `.factory.bin` and the
safeboot `.bin`), NOT on `.pio` build intermediates (which do not exist on a clean CI runner --
that was the CI Build failure this replaces). The safeboot slot offset/size are read from the
partition table embedded in the factory image itself, so a partition-table change is picked up or
fails loudly.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.dirname(HERE)                       # firmware/
DIST = os.path.join(FW, "dist")

PARTTABLE_OFFSET = 0x8000                         # CONFIG_PARTITION_TABLE_OFFSET
APP_MAGIC = 0xE9                                  # esp-idf app image first byte
PART_MAGIC = 0x50AA
PART_TYPE_APP = 0x00
SUBTYPE_FACTORY = 0x00                            # app,factory -> the safeboot slot
SUBTYPE_OTA_0 = 0x10                              # app,ota_0   -> the main app slot


def parse_partitions(blob, offset=PARTTABLE_OFFSET):
    """Parse the partition table embedded in a flash image at `offset`."""
    out = {}
    for i in range(offset, len(blob), 32):
        entry = blob[i:i + 32]
        if len(entry) < 32 or struct.unpack("<H", entry[0:2])[0] != PART_MAGIC:
            break                                # MD5 entry (0xEBEB) or padding -> end
        ptype, subtype = entry[2], entry[3]
        off, size = struct.unpack("<II", entry[4:12])
        label = entry[12:28].split(b"\x00", 1)[0].decode("ascii", "replace")
        out[label] = (ptype, subtype, off, size)
    return out


def find_by_subtype(parts, ptype, subtype):
    for _label, (t, s, off, size) in parts.items():
        if t == ptype and s == subtype:
            return off, size
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--main-factory", default=os.path.join(DIST, "tasmota32c3-cc1101.factory.bin"))
    ap.add_argument("--safeboot", default=os.path.join(DIST, "tasmota32c3-safeboot.bin"))
    ap.add_argument("--out", default=os.path.join(DIST, "tasmota32c3-cc1101-combined.factory.bin"))
    args = ap.parse_args()

    for p, what in ((args.main_factory, "main factory image"), (args.safeboot, "safeboot .bin")):
        if not os.path.exists(p):
            sys.exit("missing %s: %s (build both envs first: build.py, then build.py --env tasmota32c3-safeboot)" % (what, p))

    factory = bytearray(open(args.main_factory, "rb").read())
    safeboot = open(args.safeboot, "rb").read()

    parts = parse_partitions(factory)
    fac = find_by_subtype(parts, PART_TYPE_APP, SUBTYPE_FACTORY)
    ota0 = find_by_subtype(parts, PART_TYPE_APP, SUBTYPE_OTA_0)
    if not (fac and ota0):
        sys.exit("factory image has no factory(safeboot)/ota_0 partition: %r" % (parts,))
    fac_off, fac_size = fac
    ota0_off, _ota0_size = ota0

    if not safeboot or safeboot[0] != APP_MAGIC:
        sys.exit("safeboot .bin does not start with the esp-idf image magic 0xE9")
    if len(safeboot) > fac_size:
        sys.exit("safeboot is %d bytes, does not fit its %d-byte factory slot" % (len(safeboot), fac_size))
    if fac_off + fac_size > len(factory) or factory[ota0_off] != APP_MAGIC:
        sys.exit("factory image malformed: safeboot slot beyond EOF or no app at ota_0")

    # Replace the whole safeboot slot with our locally-built safeboot (0xFF-pad the remainder).
    factory[fac_off:fac_off + fac_size] = b"\xff" * fac_size
    factory[fac_off:fac_off + len(safeboot)] = safeboot

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    open(args.out, "wb").write(factory)
    sha = hashlib.sha256(factory).hexdigest()

    print("combined factory image: %s" % args.out)
    print("  size            : %d bytes (0x%X)" % (len(factory), len(factory)))
    print("  sha256          : %s" % sha)
    print("  safeboot slot   @ 0x%06X: our local safeboot, %d / %d B (was fetched-release safeboot)"
          % (fac_off, len(safeboot), fac_size))
    print("  main app        @ 0x%06X: unchanged (app image magic present)" % ota0_off)


if __name__ == "__main__":
    main()

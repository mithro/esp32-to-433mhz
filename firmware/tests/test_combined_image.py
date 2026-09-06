"""Structural verification of the combined safeboot + main factory image.

The combined image (firmware/dist/tasmota32c3-cc1101-combined.factory.bin, produced by
firmware/tools/combine_safeboot.py) must populate BOTH app slots so the node self-recovers
over WiFi without the BOOT button. This test parses the image's own partition table and
asserts every slot that the recovery story depends on is actually filled -- the exact thing
that was NOT true of the plain .factory.bin (safeboot slot left blank).

Skipped (not failed) when the combined image has not been built, so the host-tests CI job
-- which does not build firmware -- stays green; the build CI job builds + combines first,
then runs this. See firmware/docs/bootloader-recovery.md for the recovery matrix.
"""
import struct
from pathlib import Path

import pytest

IMAGE = Path(__file__).resolve().parents[1] / "dist" / "tasmota32c3-cc1101-combined.factory.bin"

PART_MAGIC = 0x50AA
PARTTABLE_OFFSET = 0x8000
APP_MAGIC = 0xE9                 # first byte of an esp-idf app/bootloader image
PART_TYPE_APP, PART_TYPE_DATA = 0x00, 0x01
SUBTYPE_FACTORY, SUBTYPE_OTA_0, SUBTYPE_DATA_OTA = 0x00, 0x10, 0x00


def _parse_partitions(blob, offset=PARTTABLE_OFFSET):
    parts = {}
    for i in range(offset, len(blob), 32):
        entry = blob[i:i + 32]
        if len(entry) < 32 or struct.unpack("<H", entry[0:2])[0] != PART_MAGIC:
            break
        ptype, subtype = entry[2], entry[3]
        off, size = struct.unpack("<II", entry[4:12])
        label = entry[12:28].split(b"\x00", 1)[0].decode("ascii", "replace")
        parts[label] = (ptype, subtype, off, size)
    return parts


def _find(parts, ptype, subtype):
    for _label, (t, s, off, size) in parts.items():
        if t == ptype and s == subtype:
            return off, size
    return None


@pytest.fixture(scope="module")
def image():
    if not IMAGE.exists():
        pytest.skip("combined image not built (run firmware/tools/combine_safeboot.py)")
    return IMAGE.read_bytes()


def test_bootloader_present(image):
    assert image[0] == APP_MAGIC, "no bootloader image magic at flash offset 0x0"


def test_partition_table_has_all_slots(image):
    parts = _parse_partitions(image)
    assert _find(parts, PART_TYPE_APP, SUBTYPE_FACTORY), "no factory(safeboot) app partition"
    assert _find(parts, PART_TYPE_APP, SUBTYPE_OTA_0), "no ota_0(app0) app partition"
    assert _find(parts, PART_TYPE_DATA, SUBTYPE_DATA_OTA), "no otadata partition"


def test_safeboot_slot_is_populated(image):
    """The whole point: the factory(safeboot) slot must contain a real app, not blank flash."""
    off, size = _find(_parse_partitions(image), PART_TYPE_APP, SUBTYPE_FACTORY)
    assert off + 1 <= len(image), "image shorter than the safeboot slot offset"
    assert image[off] == APP_MAGIC, "safeboot slot is blank/invalid (no app image magic)"
    # sanity: the safeboot app must fit inside its slot
    assert size >= 0x40000, "safeboot slot unexpectedly small"


def test_main_slot_is_populated(image):
    off, _size = _find(_parse_partitions(image), PART_TYPE_APP, SUBTYPE_OTA_0)
    assert image[off] == APP_MAGIC, "main app slot (ota_0) is blank/invalid"


def test_otadata_selects_an_app(image):
    """otadata must be written (boot_app0), not left blank -- blank would boot factory(safeboot)
    every time instead of the main app."""
    off, size = _find(_parse_partitions(image), PART_TYPE_DATA, SUBTYPE_DATA_OTA)
    region = image[off:off + size]
    assert any(b != 0xFF for b in region), "otadata is blank -- node would always boot safeboot"

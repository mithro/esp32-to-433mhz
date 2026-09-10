#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Package the printable case for the socket adapter, for the release:

  <out>/esp32c3-radio-adapter-case-<rev>.zip
  <out>/esp32c3-radio-adapter-case-{bottom,top}.stl   (loose copies)
  <out>/SHA256SUMS      (the new files' lines added, or the file created)
  <out>/RELEASE_NOTES.md (a "Printable case" section added, or the file created)

The zip holds the two STL files from hardware/case/ (print orientation, open
side up, as written by scripts/build_case.py), the two case STEP models from
hardware/3d/ (KiCad model frame, origin at mounting hole H1) and a README.txt
of what the parts are, their sizes, FDM print settings and how to order them
from a 3D-printing service.  The revision is `git describe --tags --dirty`,
as for the manufacturing packages, and the zip depends only on the commit:
its members carry the commit's date (UTC, to the zip format's 2 s) and mode
0644, so the same commit gives a byte-identical zip whenever it is built.

The case files are committed as built by CadQuery and are not rebuilt here:
this script needs only the standard library, so it runs in CI's KiCad
container.  Before packing it checks that every file exists and is not
empty, that each STL parses (binary or ASCII) with a sane triangle count,
and that each STEP file carries the ISO-10303-21 header, and it measures
the parts from the STL triangles for the README and checks them against
the case's design numbers (scripts/case_dims.py).  Running it again over
an existing <out> replaces its own files and lines, leaving the others alone.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import pathlib
import re
import shutil
import struct
import subprocess
import sys
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import case_dims as cd  # noqa: E402
from export_manufacturing import git_describe  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
NAME = "esp32c3-radio-adapter-case"
HALVES = ("bottom", "top", "top-slot")  # the top half comes plain or with the slot over J4: print one of the two
STL_DIR = ROOT / "hardware" / "case"
STEP_DIR = ROOT / "hardware" / "3d"
MIN_TRIANGLES, MAX_TRIANGLES = 100, 5_000_000  # each half is a few thousand
SECTION = "## Printable case"  # heading of this script's section in RELEASE_NOTES.md
SECTION_END = "<!-- end printable case -->"  # so a re-run replaces exactly the section
# The case's design numbers, from scripts/case_dims.py (the constants
# build_case.py builds the solids from; plain Python, so importable without
# CadQuery).  Keyed by the expression there.  What can be measured from the
# STL files is measured, and checked against these, in measure().
CASE = {k: round(v, 4) for k, v in {
    "OUT_X1 - OUT_X0": cd.OUT_X1 - cd.OUT_X0,  # footprint across the board
    "OUT_Y1 - OUT_Y0": cd.OUT_Y1 - cd.OUT_Y0,  # footprint along the board
    "PART_Z - OUT_Z0": cd.PART_Z - cd.OUT_Z0,  # the bottom half's wall, floor to parting line
    "OUT_Z1 - PART_Z": cd.OUT_Z1 - cd.PART_Z,  # the top half's wall, seam to ceiling
    "OUT_Z1 - BOSS_Z0": cd.OUT_Z1 - cd.BOSS_Z0,  # the top half overall: its bosses reach below the seam
    "WALL": cd.WALL,
    "OUT_Y1 - CAV_Y1": cd.ANT_WALL_T,  # the antenna wall
    "FLOOR": cd.FLOOR,
    "TOP_T": cd.TOP_T,
    "PEG_D": cd.PEG_D,
    "HOLE_D": cd.HOLE_D,  # generate_adapters.CC_HOLE_D, the board's M2 holes
    "TAB_W": cd.TAB_W,
    "TAB_H": cd.TAB_H,
    "LIP_T": cd.LIP_T,  # the tabs' thickness
    "SLOT": cd.SLOT,
    "BUMP_R": cd.BUMP_R,
    "GROOVE_R": cd.GROOVE_R,
    "BUMP_R - FIT": cd.BUMP_PROUD,  # how far the bump stands proud of the skirt's face
    "ANT_HOLE_D": cd.ANT_HOLE_D,
    "OUT_Z0": cd.OUT_Z0,  # the bottom half's floor, in the STL's z
    "PIN_STUBS": cd.PIN_STUBS,  # what is left of a trimmed pin under the board
    "J4_SLOT_X1 - J4_SLOT_X0": cd.J4_SLOT_X1 - cd.J4_SLOT_X0,  # the optional slot over J4
    "J4_SLOT_Y1 - J4_SLOT_Y0": cd.J4_SLOT_Y1 - cd.J4_SLOT_Y0,
}.items()}


# ---------------------------------------------------------------------------
# checks and measurements
# ---------------------------------------------------------------------------

Bounds = tuple[float, float, float, float, float, float]
FLOAT = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"


def check_count(path: pathlib.Path, n: int) -> None:
    if not MIN_TRIANGLES <= n <= MAX_TRIANGLES:
        raise SystemExit(f"{path}: {n} triangles is outside the sane range {MIN_TRIANGLES}..{MAX_TRIANGLES}")


def stl_bounds(path: pathlib.Path) -> tuple[str, int, Bounds]:
    """Parse a binary or ASCII STL: (kind, triangles, (x0, y0, z0, x1, y1, z1)).
    Raises SystemExit with the reason if the file is not a usable STL."""
    data = path.read_bytes()
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    kind = ""
    # Binary: 80-byte header, uint32 count, 50 bytes per triangle (normal,
    # three vertices, attribute count).  A binary file may well start with
    # the word "solid", so the size test decides.
    if len(data) >= 84:
        n = struct.unpack_from("<I", data, 80)[0]
        if len(data) == 84 + 50 * n:
            check_count(path, n)
            for rec in struct.iter_unpack("<12fH", memoryview(data)[84:]):
                for k in range(3):
                    lo[k] = min(lo[k], rec[3 + k], rec[6 + k], rec[9 + k])
                    hi[k] = max(hi[k], rec[3 + k], rec[6 + k], rec[9 + k])
            kind = "binary"
    if not kind:
        try:
            text = data.decode("ascii")
        except UnicodeDecodeError:
            raise SystemExit(f"{path}: neither a binary STL (size does not match its triangle count) nor ASCII")
        if not text.lstrip().startswith("solid"):
            raise SystemExit(f"{path}: not an STL file (no binary size match, no 'solid' header)")
        n = len(re.findall(r"^\s*facet normal\b", text, re.M))
        check_count(path, n)
        verts = re.findall(rf"^\s*vertex\s+({FLOAT})\s+({FLOAT})\s+({FLOAT})\s*$", text, re.M)
        if len(verts) != 3 * n or "endsolid" not in text:
            raise SystemExit(f"{path}: malformed ASCII STL ({n} facets, {len(verts)} well-formed vertices)")
        try:
            for v in verts:
                for k in range(3):
                    x = float(v[k])
                    lo[k] = min(lo[k], x)
                    hi[k] = max(hi[k], x)
        except ValueError as e:
            raise SystemExit(f"{path}: bad vertex coordinate in ASCII STL: {e}")
        kind = "ASCII"
    bounds = (*lo, *hi)
    if any(b != b for b in bounds) or any(b - a > 1000 or b < a for a, b in zip(lo, hi)):
        raise SystemExit(f"{path}: implausible extents {bounds}")
    return kind, n, bounds


def check_step(path: pathlib.Path) -> None:
    data = path.read_bytes()
    if not data.lstrip().startswith(b"ISO-10303-21;"):
        raise SystemExit(f"{path}: does not start with the ISO-10303-21 STEP header")
    if b"HEADER;" not in data[:4096]:
        raise SystemExit(f"{path}: STEP file without a HEADER section")
    if b"END-ISO-10303-21;" not in data[-256:]:
        raise SystemExit(f"{path}: STEP file is truncated (no END-ISO-10303-21)")


def check_exists(path: pathlib.Path) -> None:
    if not path.is_file():
        raise SystemExit(f"{path}: missing; build it with scripts/build_case.py (CadQuery) and commit it")
    if path.stat().st_size == 0:
        raise SystemExit(f"{path}: empty file")


def measure() -> dict[str, dict]:
    """Check the four case files, measure each half from its STL and check
    the measurements against the design numbers in CASE."""
    parts = {}
    for half in HALVES:
        stl = STL_DIR / f"{NAME}-{half}.stl"
        step = STEP_DIR / f"{NAME}-{half}.step"
        check_exists(stl)
        check_exists(step)
        kind, count, (x0, y0, z0, x1, y1, z1) = stl_bounds(stl)
        check_step(step)
        parts[half] = {"stl": stl, "step": step, "kind": kind, "triangles": count, "size": (x1 - x0, y1 - y0, z1 - z0), "z0": z0}
        print(f"checked {stl.relative_to(ROOT)}: {kind} STL, {count} triangles, {x1 - x0:.1f} x {y1 - y0:.1f} x {z1 - z0:.1f} mm")
        print(f"checked {step.relative_to(ROOT)}: STEP")
    expected = {
        "bottom": (CASE["OUT_X1 - OUT_X0"], CASE["OUT_Y1 - OUT_Y0"], CASE["PART_Z - OUT_Z0"] + CASE["TAB_H"]),
        "top": (CASE["OUT_X1 - OUT_X0"], CASE["OUT_Y1 - OUT_Y0"], CASE["OUT_Z1 - BOSS_Z0"]),
        "top-slot": (CASE["OUT_X1 - OUT_X0"], CASE["OUT_Y1 - OUT_Y0"], CASE["OUT_Z1 - BOSS_Z0"]),
    }
    for half, exp in expected.items():
        got = parts[half]["size"]
        if any(abs(g - e) > 0.05 for g, e in zip(got, exp)):
            raise SystemExit(f"{parts[half]['stl']}: measures {got[0]:.2f} x {got[1]:.2f} x {got[2]:.2f} mm, but build_case.py's numbers give "
                             f"{exp[0]:.2f} x {exp[1]:.2f} x {exp[2]:.2f}; update CASE in {pathlib.Path(__file__).name} or rebuild the case")
    if abs(parts["bottom"]["z0"] - CASE["OUT_Z0"]) > 0.05:
        raise SystemExit(f"{parts['bottom']['stl']}: floor at z = {parts['bottom']['z0']:.2f}, expected {CASE['OUT_Z0']}")
    return parts


# ---------------------------------------------------------------------------
# text
# ---------------------------------------------------------------------------

def size_mm(parts: dict[str, dict], half: str) -> str:
    return "{:.1f} x {:.1f} x {:.1f}".format(*parts[half]["size"])


def readme_text(rev: str, parts: dict[str, dict]) -> str:
    c = CASE
    closed = c["PART_Z - OUT_Z0"] + c["OUT_Z1 - PART_Z"]
    kind = {h: f"{parts[h]['kind']} STL" for h in HALVES}
    return f"""Printable case for the ESP32-C3 radio socket adapter
======================================================

Quick start
-----------
Print or upload the bottom .stl and one of the two top .stl files (plain,
or with the slot over J4), at 100 % in millimetres,
as supplied (open side up), no supports.
Home FDM: PLA or PETG, 0.2 mm layers, 3 perimeters.
Service: MJF in PA12 nylon ("PA12-HP" at JLC3DP as of 2026-09), not
standard resin.  The .step files are not needed for printing.

Package:      {NAME}-{rev}.zip
Revision:     {rev}  (git describe)
Units:        millimetres, in every file

What it is
----------
A two-part case for the esp32c3-radio-adapter board (the 29 x 38 mm carrier
that takes an ESP32-C3 SuperMini and a 2x4-header 433 MHz radio board).  It
was designed around the two radios the case's collision check models: the
Ebyte E07-M1101D, whose SMA jack pokes through the hole in the far wall,
and the Ai-Thinker Ra-02 breakout, whose U.FL-to-SMA bulkhead pigtail is
clamped in the same hole by its nut.  The SuperMini's USB-C plug goes
through a window in the left wall.  The case parts along the connectors'
axis: the antenna hole and the USB-C window are each half in one half, so
the connectors sit in the bottom half's cut-outs and the top half closes
over them.  The SuperMini may be on its pin headers or soldered flat by its
castellations; the window takes its USB-C at either height.  Every
through-hole pin is assumed trimmed under the board to about {-c['PIN_STUBS']:.0f} mm, which
is what lets the case be only {closed:.1f} mm tall.  It is not water-tight and does
not try to be.

The two halves snap together; there are no screws.  The board presses onto
four {c['PEG_D']} mm pegs in the bottom half (they take the board's {c['HOLE_D']} mm M2
corner holes), bosses in the top half hold it down once the case is shut,
and four cantilever snap tabs on the bottom half click into grooves inside
the top half's skirt.  A notch at the seam on the end away from the antenna
takes a fingernail or a small screwdriver to open it.

Parts
-----
Print one of each:

  bottom   {NAME}-bottom.stl     1 off   {size_mm(parts, 'bottom')} mm
  top      {NAME}-top.stl        1 off   {size_mm(parts, 'top')} mm
     or    {NAME}-top-slot.stl   the same top half with a slot in the
                                                   ceiling over the spare-GPIO header
                                                   J4, for jumper wires out of the
                                                   closed case; print one or the other

Sizes are the overall bounding box of each STL, measured from its
triangles; the bottom half's includes the {c['TAB_H']:.0f} mm snap tabs standing above
its {c['PART_Z - OUT_Z0']} mm wall, and the top half's the bosses that reach {c['OUT_Z1 - BOSS_Z0'] - c['OUT_Z1 - PART_Z']:.1f} mm below
its {c['OUT_Z1 - PART_Z']} mm skirt.  The case is {c['OUT_X1 - OUT_X0']} x {c['OUT_Y1 - OUT_Y0']} mm outside and {closed:.1f} mm tall when
closed, with {c['WALL']} mm walls ({c['OUT_Y1 - CAV_Y1']} mm at the antenna end) and a {c['FLOOR']} mm
floor and ceiling.

After uploading, the preview should report the long side as about {c['OUT_Y1 - OUT_Y0']:.0f} mm;
if it shows {c['OUT_Y1 - OUT_Y0'] / 25.4:.1f} or {c['OUT_Y1 - OUT_Y0'] * 10:.0f}, the units were misread.

Files
-----
  {NAME}-bottom.stl    {kind['bottom']}, print orientation (open side up)
  {NAME}-top.stl       {kind['top']}, print orientation (open side up,
                                           i.e. upside down compared with
                                           how it sits on the board)
  {NAME}-top-slot.stl  {kind['top-slot']}, the top half with the J4 slot
  {NAME}-bottom.step   STEP AP214, as modelled (see below)
  {NAME}-top.step      STEP AP214, as modelled
  {NAME}-top-slot.step STEP AP214, as modelled

The STL files are the ones to print or upload: each half already lies the
way it prints, open side up, so no support is needed.  Their coordinates
are not zeroed to the build plate (the bottom half's floor is at
z = {c['OUT_Z0']:.1f}); slicers put a part on the plate when they import it, so this
needs no attention unless a tool complains.

You do not need the STEP files to print.  They are the KiCad 3D models of
the case, both halves in their assembled position on the board, in KiCad's
model frame: origin at the adapter's mounting hole H1 (the corner hole on
the USB-C side, at the end away from the antenna), X across the board from
the USB-C wall towards the opposite long wall, Y along the board away from
the antenna wall, Z out of the board's component face (docs/3d-models.md
has the frame and the dimensions).  Use them to modify the case in a CAD
tool or to check it against the adapter assembly STEP files on the same
release; if you print from them, turn the top half over first.

Printing it at home (FDM)
-------------------------
  Material         PLA or PETG
  Layer height     0.2 mm
  Perimeters       3 (the {c['WALL']} mm walls are then mostly perimeter)
  Infill           any; there is little of it
  Supports         none; print each half as supplied, open side up
  Orientation      as supplied; do not rotate the parts
  Scale            100 %; everything is dimensioned for the real board

What to look at after printing:

  * The four snap tabs on the bottom half: {c['TAB_W']:.0f} mm wide, {c['TAB_H']:.0f} mm tall and {c['LIP_T']} mm
    thick, two on each long wall, each with a small rounded bump near its
    tip.  They should be printed cleanly, without stringing across the {c['SLOT']:.0f} mm
    slots beside them, and they flex across the layer lines, so good layer
    adhesion matters more than usual.  The bump stands {c['BUMP_R - FIT']} mm proud of the
    skirt's face inside the top half and gives about 1 % strain over the
    tab, which is gentle for PLA.
  * The four pegs on the bottom half's standoffs, {c['PEG_D']} mm in diameter with
    a chamfered tip, which the board's {c['HOLE_D']} mm holes press onto.  This is a
    light press fit that relies on FDM printing round pegs slightly
    oversize, so how tight it is depends on the printer's calibration
    (flow, extrusion width, hole and peg compensation).  If the board will
    not go on, scrape or sand the pegs a touch, or open the board's holes
    with a 2.2 or 2.3 mm drill; if it is loose, the top half's bosses
    still hold the board once the case is shut, or use a drop of glue.
    One peg, the one at the antenna end on the USB-C side (beside JP1),
    is flush with the board's top instead of standing proud; that is by
    design, to leave room for a jumper cap on JP1.
  * The antenna hole ({c['ANT_HOLE_D']} mm) and the USB-C window are U-shaped cut-outs in
    each half, so they print unsupported; clean any stringing from their
    edges with a knife.  If you print the slotted top, the {c['J4_SLOT_X1 - J4_SLOT_X0']:.1f} x {c['J4_SLOT_Y1 - J4_SLOT_Y0']:.1f} mm slot
    is a plain hole in the ceiling.

To assemble: trim every pin under the board to about {-c['PIN_STUBS']:.0f} mm, press the
board onto the pegs (SuperMini's USB-C into the window side, radio's
antenna connector into the cut-out in the far wall), lay the pigtail's
bulkhead in the same cut-out if it is the Ra-02, and press the top half
on until the four tabs click; its nut goes on outside afterwards.

Ordering from a 3D-printing service (JLCPCB / JLC3DP)
----------------------------------------------------
JLCPCB's 3D-printing service is at https://jlc3dp.com/ (jlcpcb.com/3d-printing
redirects there).  Upload the two STL files as two parts, quantity 1 of
each, and pick the process and material for both:

  * MJF (multi jet fusion) in PA12 nylon, listed there as "PA12-HP": the
    recommended choice.  Nylon is tough and slightly flexible, which suits
    the snap tabs and the pegs, and the powder process needs no supports,
    so there are no witness marks in the grooves and slots.  MJF PA12
    arrives grey with a matte, slightly grainy powder texture unless you
    order it dyed.
  * SLA resin: usually the cheapest option and the finest surface, but do
    not order the standard grey or black resins for this case; they are
    brittle and the {c['LIP_T']} mm snap tabs are likely to crack the first time
    the case is opened.  If you must use resin, treat the case as
    close-once.  SLA parts also
    carry support witness marks, which may land in the grooves and slots.
  * FDM (PLA, ABS or ASA) is offered too and gives what a home printer
    gives, with the notes above; the peg fit then depends on their
    machines' calibration rather than yours.

In MJF or resin the pegs will probably be a slip fit rather than a press
fit; that is fine, the top half's bosses hold the board once the case is
shut.

Read the service's design guideline before ordering
(https://jlc3dp.com/help/article/3D-Printing-Design-Guideline).  As of
2026-09 it gives 1.0 to 2.0 mm as the minimum wall for MJF nylon depending
on part size (1.5 mm at 50 x 50 mm, the nearest row to this part) and says
"the recommended minimum wall thickness for structures such as protrusion,
positioning, snaps and fasteners is more than 1.5mm".  The case's walls are
{c['WALL']} mm, but its snap tabs are {c['LIP_T']} mm thick and the bumps and grooves are
{c['BUMP_R']} and {c['GROOVE_R']} mm in radius, because the case was drawn for FDM at home.
If the order review flags the {c['LIP_T']} mm tabs, confirm "print as designed":
PA12 at that thickness should print intact and come out softer than
PLA, so the snap should still engage.  This case has not been printed
in any material yet; the tabs and pegs are the two things to check on
the first print, and reports are welcome.
Thicker tabs mean regenerating the case with a larger LIP_T in
scripts/build_case.py, which also changes the rebate in the top half.  The
process and material names above are as sold in 2026; check the current
catalogue, because services rename and replace materials.  No
post-processing (dyeing, polishing) is needed.

Generated by scripts/export_case.py from the case built with
scripts/build_case.py (CadQuery); see docs/3d-models.md in
https://github.com/mithro/esp32-to-433mhz
"""


def notes_text(rev: str, zip_name: str, parts: dict[str, dict]) -> str:
    return "\n".join([
        SECTION,
        "",
        "The printable case for the socket adapter, two snap-together halves with no screws (the board presses",
        "onto pegs; the E07-M1101D's SMA jack or the Ra-02's pigtail bulkhead goes through the hole in the far",
        f"wall), is `{zip_name}`. It holds the STL files in print orientation (open side up,",
        "no supports), the STEP models (KiCad frame, origin at mounting hole H1) and a README.txt with the",
        "sizes, FDM print settings and how to order it from a 3D-printing service. The same `.stl` files are",
        "also attached loose, for dropping straight into a slicer. In short: at home, PLA or PETG, no supports,",
        "as supplied; at a service, MJF PA12 nylon, not standard resin; details in the zip's README.txt. See",
        "docs/3d-models.md.",
        "",
        "| Package | Parts (1 each) | Size (mm) | Files |",
        "| --- | --- | --- | --- |",
        f"| `{zip_name}` | `{NAME}-bottom.stl`, `{NAME}-top.stl` (or `{NAME}-top-slot.stl`, with a slot over J4) | {size_mm(parts, 'bottom')}, {size_mm(parts, 'top')} | 3 STL, 3 STEP, README.txt |",
        "",
        SECTION_END,
        "",
    ])


# ---------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------

def commit_time() -> tuple[int, int, int, int, int, int]:
    """The HEAD commit's date, in UTC, as a zipfile date_time."""
    r = subprocess.run(["git", "-C", str(ROOT), "log", "-1", "--format=%cI"], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"git log failed: {r.stderr}")
    t = datetime.datetime.fromisoformat(r.stdout.strip()).astimezone(datetime.timezone.utc)
    return (t.year, t.month, t.day, t.hour, t.minute, t.second)


def write_zip(zip_path: pathlib.Path, members: list[tuple[str, bytes]]) -> None:
    """A zip that depends only on its members' names and bytes: every entry
    gets the commit's date and mode 0644, so a rebuild of the same commit
    is byte-identical."""
    when = commit_time()
    with zipfile.ZipFile(zip_path, "w") as z:
        for name, data in members:
            info = zipfile.ZipInfo(name, date_time=when)
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)


def update_sums(sums: pathlib.Path, files: list[pathlib.Path]) -> None:
    """Add the files' sha256 lines, replacing any earlier line for the same
    name and dropping the lines of any earlier case zip."""
    names = {f.name for f in files}
    stale = re.compile(rf"^{re.escape(NAME)}-.*\.zip$")
    kept = []
    if sums.exists():
        for line in sums.read_text().splitlines():
            name = line.split("  ", 1)[-1]
            if name not in names and not stale.match(name):
                kept.append(line)
    new = [f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}" for f in files]
    sums.write_text("".join(line + "\n" for line in kept + new))


def update_notes(notes: pathlib.Path, text: str) -> None:
    """Append the case section, or replace an earlier one: from its heading
    to its end marker, or to the next `## ` heading if the marker is
    missing.  A blank line separates it from whatever follows."""
    old = notes.read_text() if notes.exists() else ""
    m = re.search(rf"^{re.escape(SECTION)}\n.*?(?:^{re.escape(SECTION_END)}\n|(?=^## )|\Z)", old, re.M | re.S)
    if m:
        before, after = old[: m.start()], old[m.end():]
    else:
        before, after = old, ""
    if before and not before.endswith("\n\n"):
        before = before.rstrip("\n") + "\n\n"
    after = after.lstrip("\n")
    notes.write_text(before + text + ("\n" + after if after else ""))


def rel(path: pathlib.Path) -> pathlib.Path:
    return path.relative_to(ROOT) if path.is_relative_to(ROOT) else path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=pathlib.Path, default=ROOT / "dist")
    args = ap.parse_args()
    parts = measure()
    rev = git_describe()
    args.out.mkdir(parents=True, exist_ok=True)

    zip_path = args.out / f"{NAME}-{rev}.zip"
    for stale in sorted(args.out.glob(f"{NAME}-*.zip")):  # an earlier run at another revision
        if stale != zip_path:
            stale.unlink()
            print(f"removed stale {rel(stale)}")
    members = [("README.txt", readme_text(rev, parts).encode())]
    members += [(parts[h]["stl"].name, parts[h]["stl"].read_bytes()) for h in HALVES]
    members += [(parts[h]["step"].name, parts[h]["step"].read_bytes()) for h in HALVES]
    write_zip(zip_path, members)
    print(f"wrote {rel(zip_path)} ({zip_path.stat().st_size // 1024} kB)")

    loose = []
    for half in HALVES:
        dst = args.out / parts[half]["stl"].name
        shutil.copyfile(parts[half]["stl"], dst)
        loose.append(dst)
        print(f"wrote {rel(dst)}")

    sums = args.out / "SHA256SUMS"
    update_sums(sums, [zip_path, *loose])
    print(f"updated {rel(sums)}")
    notes = args.out / "RELEASE_NOTES.md"
    update_notes(notes, notes_text(rev, zip_path.name, parts))
    print(f"updated {rel(notes)}")


if __name__ == "__main__":
    main()

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
as for the manufacturing packages.

The case files are committed as built by CadQuery and are not rebuilt here:
this script needs only the standard library, so it runs in CI's KiCad
container.  Before packing it checks that every file exists and is not
empty, that each STL parses (binary or ASCII) with a sane triangle count,
and that each STEP file carries the ISO-10303-21 header, and it measures
the parts from the STL triangles for the README.  Running it again over an
existing <out> replaces its own files and lines, leaving the others alone.
"""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import re
import struct
import subprocess
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
NAME = "esp32c3-radio-adapter-case"
HALVES = ("bottom", "top")
STL_DIR = ROOT / "hardware" / "case"
STEP_DIR = ROOT / "hardware" / "3d"
MIN_TRIANGLES, MAX_TRIANGLES = 100, 5_000_000  # each half is a few thousand
SECTION = "## Printable case"  # heading of this script's section in RELEASE_NOTES.md


def git_describe() -> str:
    r = subprocess.run(["git", "-C", str(ROOT), "describe", "--tags", "--dirty", "--always", "--match", "v[0-9]*"], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"git describe failed: {r.stderr}")
    return r.stdout.strip()


# ---------------------------------------------------------------------------
# checks and measurements
# ---------------------------------------------------------------------------

def stl_bounds(path: pathlib.Path) -> tuple[str, int, tuple[float, float, float, float, float, float]]:
    """Parse a binary or ASCII STL: (kind, triangles, (x0, y0, z0, x1, y1, z1)).
    Raises SystemExit with the reason if the file is not a usable STL."""
    data = path.read_bytes()
    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []
    # Binary: 80-byte header, uint32 count, 50 bytes per triangle.  A binary
    # file may well start with the word "solid", so the size test decides.
    if len(data) >= 84:
        n = struct.unpack_from("<I", data, 80)[0]
        if len(data) == 84 + 50 * n:
            for i in range(n):
                v = struct.unpack_from("<12f", data, 84 + 50 * i)  # normal, then three vertices
                xs.extend(v[3::3])
                ys.extend(v[4::3])
                zs.extend(v[5::3])
            kind, count = "binary", n
        else:
            kind, count = "", 0
    else:
        kind, count = "", 0
    if not kind:
        try:
            text = data.decode("ascii")
        except UnicodeDecodeError:
            raise SystemExit(f"{path}: neither a binary STL (size does not match its triangle count) nor ASCII")
        if not text.lstrip().startswith("solid"):
            raise SystemExit(f"{path}: not an STL file (no binary size match, no 'solid' header)")
        verts = re.findall(r"^\s*vertex\s+([-+\dEe.]+)\s+([-+\dEe.]+)\s+([-+\dEe.]+)\s*$", text, re.M)
        facets = len(re.findall(r"^\s*facet normal\b", text, re.M))
        if facets == 0 or len(verts) != 3 * facets or "endsolid" not in text:
            raise SystemExit(f"{path}: malformed ASCII STL ({facets} facets, {len(verts)} vertices)")
        xs = [float(v[0]) for v in verts]
        ys = [float(v[1]) for v in verts]
        zs = [float(v[2]) for v in verts]
        kind, count = "ascii", facets
    if not MIN_TRIANGLES <= count <= MAX_TRIANGLES:
        raise SystemExit(f"{path}: {count} triangles is outside the sane range {MIN_TRIANGLES}..{MAX_TRIANGLES}")
    bounds = (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))
    if any(b != b for b in bounds) or max(b - a for a, b in zip(bounds[:3], bounds[3:])) > 1000:
        raise SystemExit(f"{path}: implausible extents {bounds}")
    return kind, count, bounds


def check_step(path: pathlib.Path) -> None:
    head = path.read_bytes()[:4096]
    if not head.lstrip().startswith(b"ISO-10303-21;"):
        raise SystemExit(f"{path}: does not start with the ISO-10303-21 STEP header")
    if b"HEADER;" not in head:
        raise SystemExit(f"{path}: STEP file without a HEADER section")
    tail = path.read_bytes()[-256:]
    if b"END-ISO-10303-21;" not in tail:
        raise SystemExit(f"{path}: STEP file is truncated (no END-ISO-10303-21)")


def check_exists(path: pathlib.Path) -> None:
    if not path.is_file():
        raise SystemExit(f"{path}: missing; build it with scripts/build_case.py (CadQuery) and commit it")
    if path.stat().st_size == 0:
        raise SystemExit(f"{path}: empty file")


def measure() -> dict[str, dict]:
    """Check the four case files and measure each half from its STL."""
    parts = {}
    for half in HALVES:
        stl = STL_DIR / f"{NAME}-{half}.stl"
        step = STEP_DIR / f"{NAME}-{half}.step"
        check_exists(stl)
        check_exists(step)
        kind, count, (x0, y0, z0, x1, y1, z1) = stl_bounds(stl)
        check_step(step)
        parts[half] = {"stl": stl, "step": step, "kind": kind, "triangles": count, "size": (x1 - x0, y1 - y0, z1 - z0)}
        print(f"checked {stl.relative_to(ROOT)}: {kind} STL, {count} triangles, {x1 - x0:.1f} x {y1 - y0:.1f} x {z1 - z0:.1f} mm")
        print(f"checked {step.relative_to(ROOT)}: STEP")
    return parts


# ---------------------------------------------------------------------------
# text
# ---------------------------------------------------------------------------

def readme_text(rev: str, parts: dict[str, dict]) -> str:
    size = lambda h: "{:.1f} x {:.1f} x {:.1f} mm".format(*parts[h]["size"])  # noqa: E731
    return f"""Printable case for the ESP32-C3 radio socket adapter
======================================================

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
through a window in the left wall.

The two halves snap together; there are no screws.  The board presses onto
four 2.15 mm pegs in the bottom half (they take the board's 2.2 mm corner
holes), bosses in the top half hold it down once the case is shut, and four
cantilever snap tabs on the bottom half click into grooves inside the top
half's skirt.  A notch at the seam on the end away from the antenna takes a
fingernail or a small screwdriver to open it.

Parts
-----
Print one of each:

  bottom   {NAME}-bottom.stl   1 off   {size('bottom')}
  top      {NAME}-top.stl      1 off   {size('top')}

Sizes are the overall bounding box of each STL, measured from its
triangles; the bottom half's includes the 6 mm snap tabs standing above
its 8.5 mm wall.  The case is 36.2 x 66.7 mm outside and 20.6 mm tall when
closed, with 2.2 mm walls and a 2.0 mm floor and ceiling.

Files
-----
  {NAME}-bottom.stl    binary STL, print orientation (open side up)
  {NAME}-top.stl       binary STL, print orientation (open side up,
                                           i.e. turned over)
  {NAME}-bottom.step   STEP AP214, as modelled (see below)
  {NAME}-top.step      STEP AP214, as modelled

The STL files are the ones to print or upload: each half already lies the
way it prints, open side up, so no support is needed.  Their coordinates
are not zeroed to the build plate (the bottom half's floor is at z = -9);
slicers put a part on the plate when they import it, so this needs no
attention unless a tool complains.

The STEP files are the KiCad 3D models of the case, so they are in KiCad's
model frame, both halves in their assembled position on the board: the
origin is at the adapter's mounting hole H1 (the corner hole on the USB-C
side of the board, at the end away from the antenna), X runs across the
board towards the radio's side, Y runs along the board away from the
antenna wall, Z points out of the board's component face.  Use them to
modify the case in a CAD tool, or to check it against the adapter assembly
STEP files on the same release; if you print from them, turn the top half
over first.

Printing it at home (FDM)
-------------------------
  Material         PLA or PETG
  Layer height     0.2 mm
  Perimeters       3 (the 2.2 mm walls are then mostly perimeter)
  Infill           any; there is little of it
  Supports         none; print each half as supplied, open side up
  Orientation      as supplied; do not rotate the parts
  Scale            100 %; everything is dimensioned for the real board

What to look at after printing:

  * The four snap tabs on the bottom half: 8 mm wide, 6 mm tall and 0.8 mm
    thick, two on each long wall, each with a small rounded bump near its
    tip.  They should be printed cleanly, without stringing across the 1 mm
    slots beside them, and they flex across the layer lines, so good layer
    adhesion matters more than usual.  The bump stands 0.2 mm proud of the
    skirt's face inside the top half and gives about 1 % strain over the
    tab, which is gentle for PLA.
  * The four pegs on the bottom half's standoffs, 2.15 mm in diameter with
    a chamfered tip, which the board's 2.2 mm holes press onto.  This is a
    light press fit that relies on FDM printing round pegs slightly
    oversize, so how tight it is depends on the printer's calibration
    (flow, extrusion width, hole and peg compensation).  If the board will
    not go on, scrape or sand the pegs a touch, or open the board's holes
    with a 2.2 or 2.3 mm drill; if it is loose, the top half's bosses
    still hold the board once the case is shut, or use a drop of glue.
    One peg, the one at the antenna end on the USB-C side (beside JP1),
    is flush with the board's top instead of standing proud; that is by
    design, to leave room for a jumper cap on JP1.
  * The hole in the antenna wall (6.6 mm) and the USB-C window in the left
    wall of the top half print unsupported; clean any sag from their upper
    edges with a knife.

To assemble: press the board onto the pegs (SuperMini's USB-C into the
window side, radio's antenna connector towards the hole in the far wall),
fit the antenna connector or pigtail bulkhead through the hole, and press
the top half on until the four tabs click.

Ordering from a 3D-printing service (JLCPCB / JLC3DP)
----------------------------------------------------
JLCPCB's 3D-printing service is at https://jlc3dp.com/ (jlcpcb.com/3d-printing
redirects there).  Upload the two STL files as two parts, quantity 1 of
each, and pick the process and material for both:

  * MJF (multi jet fusion) in PA12 nylon, listed there as "PA12-HP": the
    recommended choice.  Nylon is tough and slightly flexible, which suits
    the snap tabs and the press-fit pegs, and the powder process needs no
    supports, so there are no witness marks in the grooves and slots.
  * SLA resin (the standard grey or black resins): usually the cheapest
    option and the finest surface, but standard resins are brittle, so the
    0.8 mm snap tabs may crack when the case is opened and closed.  If you
    choose resin, treat the case as close-once, or pick a resin the service
    describes as tough or ABS-like.
  * FDM (PLA, ABS or ASA) is offered too and gives what a home printer
    gives, with the notes above; the peg fit then depends on their
    machines' calibration rather than yours.

Read the service's design guideline before ordering.  As of 2026-09 it
gives 1.0 mm as the minimum wall for MJF nylon and recommends "more than
1.5mm" for "snaps and fasteners"; the case's walls are 2.2 mm, but its snap
tabs are 0.8 mm thick and the bumps and grooves are 0.35 and 0.42 mm in
radius, because the case was drawn for FDM at home.  The service may flag
the tabs or print them as they are; in MJF nylon such thin features
generally print but are more flexible than in PLA.  The process and
material names above are as sold in 2026; check the current catalogue,
because services rename and replace materials.  No post-processing
(dyeing, polishing) is needed.

Generated by scripts/export_case.py from the case built with
scripts/build_case.py (CadQuery); see docs/3d-models.md in
https://github.com/mithro/esp32-to-433mhz
"""


def notes_text(rev: str, zip_name: str, parts: dict[str, dict]) -> str:
    size = lambda h: "{:.1f} x {:.1f} x {:.1f}".format(*parts[h]["size"])  # noqa: E731
    return "\n".join([
        SECTION,
        "",
        "The printable case for the socket adapter, two snap-together halves with no screws (the board presses",
        "onto pegs; the E07-M1101D's SMA jack or the Ra-02's pigtail bulkhead goes through the hole in the far",
        f"wall), is `{zip_name}`. It holds the two STL files in print orientation (open side up,",
        "no supports), the two STEP models (KiCad frame, origin at mounting hole H1) and a README.txt with the",
        "sizes, FDM print settings and how to order it from a 3D-printing service. The same two `.stl` files are",
        "also attached loose, for dropping straight into a slicer. See docs/3d-models.md.",
        "",
        "| Package | Parts (1 each) | Size (mm) | Files |",
        "| --- | --- | --- | --- |",
        f"| `{zip_name}` | `{NAME}-bottom.stl`, `{NAME}-top.stl` | {size('bottom')}, {size('top')} | 2 STL, 2 STEP, README.txt |",
        "",
    ])


# ---------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------

def update_sums(sums: pathlib.Path, files: list[pathlib.Path], drop: set[str]) -> None:
    """Add the files' sha256 lines, replacing any earlier line for the same
    name and dropping the lines of the names in `drop`."""
    names = {f.name for f in files} | drop
    kept = []
    if sums.exists():
        kept = [line for line in sums.read_text().splitlines() if line.split("  ", 1)[-1] not in names]
    new = [f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}" for f in files]
    sums.write_text("".join(line + "\n" for line in kept + new))


def update_notes(notes: pathlib.Path, text: str) -> None:
    """Append the case section, replacing an earlier one (up to the next heading or the end)."""
    old = notes.read_text() if notes.exists() else ""
    m = re.search(rf"^{re.escape(SECTION)}\n.*?(?=^## |\Z)", old, re.M | re.S)
    if m:
        new = old[: m.start()] + text + old[m.end():]
    else:
        new = old + ("\n" if old and not old.endswith("\n\n") else "") + text
    notes.write_text(new)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=pathlib.Path, default=ROOT / "dist")
    args = ap.parse_args()
    parts = measure()
    rev = git_describe()
    args.out.mkdir(parents=True, exist_ok=True)
    rel = lambda p: p.relative_to(ROOT) if p.is_relative_to(ROOT) else p  # noqa: E731

    zip_path = args.out / f"{NAME}-{rev}.zip"
    stale = [p for p in sorted(args.out.glob(f"{NAME}-*.zip")) if p != zip_path]  # an earlier run at another revision
    for p in stale:
        p.unlink()
        print(f"removed stale {rel(p)}")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.txt", readme_text(rev, parts))
        for half in HALVES:
            z.write(parts[half]["stl"], parts[half]["stl"].name)
        for half in HALVES:
            z.write(parts[half]["step"], parts[half]["step"].name)
    print(f"wrote {rel(zip_path)} ({zip_path.stat().st_size // 1024} kB)")

    loose = []
    for half in HALVES:
        dst = args.out / parts[half]["stl"].name
        dst.write_bytes(parts[half]["stl"].read_bytes())
        loose.append(dst)
        print(f"wrote {rel(dst)}")

    sums = args.out / "SHA256SUMS"
    update_sums(sums, [zip_path, *loose], {p.name for p in stale})
    print(f"updated {rel(sums)}")
    notes = args.out / "RELEASE_NOTES.md"
    update_notes(notes, notes_text(rev, zip_path.name, parts))
    print(f"updated {rel(notes)}")


if __name__ == "__main__":
    main()

#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow"]
# ///
"""Render and export the adapters with their modules plugged in.

Each assembly is a variant of an adapter board with the 3D models from
hardware/3d/ on its footprints (the committed boards carry the E07-M1101D
in the socket adapter; the Ra-02 variant is generated here):

  radio-e07    socket adapter + SuperMini + E07-M1101D (CC1101, SMA jack)
  radio-ra02   socket adapter + SuperMini + Ra-02 breakout + U.FL-to-SMA pigtail, JP1 jumper fitted
  radio-e07-case-closed, radio-ra02-case-closed
               the same in the printed case (scripts/build_case.py), both halves snapped together
  radio-e07-case-open, radio-ra02-case-open
               in the bottom half of the case only, the boards in view
  radio-e07-case-exploded, radio-ra02-case-exploded
               both halves, the top half lifted clear (an isometric view only)
  case-bottom, case-top
               each half of the case by itself: the bottom from above (pegs,
               lip, snap tabs), the top from below (bosses, grooves, notch)
  sx1278       SX1278 module adapter + SuperMini + module + SMA jack

Each is rendered (kicad-cli pcb render) from its views: iso, top and side
for the bare assemblies, iso and all six orthographic sides (top, bottom,
front, back, left, right) for the case.  The closed and open cases come
out as one labelled sheet each, docs/images/<adapter>-assembly-<variant>-sheet.png,
composed from the seven renders; every other view, and the open case's top
view, is written as docs/images/<adapter>-assembly-<variant>-<view>.png.
With --export DIR the bare assemblies and the closed cases also go to
DIR/<adapter>-assembly-<variant>.step and .glb (kicad-cli pcb export step /
glb) for case design.

The reference boards under hardware/parts/ carry the "-components" model of
the product they reproduce; `parts` renders each of those as
docs/images/<name>-model-iso.png.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import pathlib
import shutil
import subprocess
import sys
import hashlib
import tempfile
from typing import Callable, NamedTuple

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import generate_adapters as ga  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
MODELS = ROOT / "hardware" / "3d"
IMAGES = ROOT / "docs" / "images"
# kicad-cli's argument parser takes a leading '-' in the rotation as an option,
# unless the value is wrapped in literal quotes, which it then strips.
# The assemblies stick out well past the adapter (the radio board and its
# antenna jack hang off the bottom edge), so the camera pivots about a point
# 1.5 cm down the board from its centre and zooms out.
VIEWS = {  # name -> (extra kicad-cli render args, width, height)
    "iso": (["--perspective", "--rotate", "'-55,0,28'", "--zoom", "0.5", "--pivot", "'0,-1.5,0'"], 1800, 1300),
    "top": (["--side", "top", "--zoom", "0.55", "--pivot", "'0,-1.5,0'"], 1400, 1800),
    "side": (["--side", "left", "--zoom", "0.8", "--pivot", "'0,-1.5,0'"], 2400, 700),
}
# The case (36 x 67 x 21 mm, its centre 1.2 cm down the board from the board's)
# from every side.  The renderer's floor shadow is the trouble: from the side
# lights' default 60 degree elevation it runs some 60 mm out from the case and
# fills the frame of the top and bottom views, so those raise the lights to
# 80 degrees and get a drop shadow that stays under the case.  The wall views
# see the floor edge-on, but the side lights throw the antenna connector's
# shadow across the wall as a big X, so they are lit by the camera with the
# side lights turned down and steep: a flat wall, and just enough shading
# to show the recesses (the pry notch, the USB-C window).
CASE_PIVOT = ["--pivot", "'0,-1.2,0'"]
DROP_SHADOW = ["--light-side-elevation", "80"]
FLAT_WALL = ["--light-side", "0.15", "--light-side-elevation", "80", "--light-camera", "0.85"]
CASE_VIEWS = {
    "iso": (["--perspective", "--rotate", "'-55,0,28'", "--zoom", "0.45", "--light-side", "0.35", "--light-camera", "0.5", *CASE_PIVOT], 1800, 1400),
    "top": (["--side", "top", "--zoom", "0.45", *DROP_SHADOW, *CASE_PIVOT], 1000, 1600),
    "bottom": (["--side", "bottom", "--zoom", "0.45", *DROP_SHADOW, *CASE_PIVOT], 1000, 1600),
    "front": (["--side", "front", "--zoom", "1.3", *FLAT_WALL, *CASE_PIVOT], 1200, 800),
    "back": (["--side", "back", "--zoom", "1.3", *FLAT_WALL, *CASE_PIVOT], 1200, 800),
    "left": (["--side", "left", "--zoom", "1.15", *FLAT_WALL, *CASE_PIVOT], 1800, 700),
    "right": (["--side", "right", "--zoom", "1.15", *FLAT_WALL, *CASE_PIVOT], 1800, 700),
}
# The exploded case is taller (the top half floats CASE_LIFT above the bottom), so it zooms out and pivots a little higher.
EXPLODED_VIEWS = {
    "iso": (["--perspective", "--rotate", "'-55,0,28'", "--zoom", "0.42", "--pivot", "'0,-1.5,0.6'"], 1800, 1500),
}
# The halves alone: the bottom from the usual isometric, the top turned over
# (the camera 125 degrees round the x axis: looking up into it from below).
BOTTOM_ALONE_VIEWS = {"iso": (["--perspective", "--rotate", "'-55,0,28'", "--zoom", "0.5", *CASE_PIVOT], 1800, 1400)}
TOP_ALONE_VIEWS = {"underside": (["--perspective", "--rotate", "'125,0,28'", "--zoom", "0.5", *CASE_PIVOT], 1800, 1400)}
# The sheets' panels, in order, with their labels: the first three make the
# top row (isometric large, then the plan views), the walls the row below.
CLOSED_SHEET = {"iso": "isometric", "top": "top", "bottom": "bottom", "front": "front (antenna)", "back": "back (pry notch)", "left": "left (USB-C)", "right": "right"}
OPEN_SHEET = {"iso": "isometric", "top": "top", "bottom": "bottom", "front": "front (antenna)", "back": "back (SuperMini end)", "left": "left (USB-C)", "right": "right"}


class Variant(NamedTuple):
    project: str  # the adapter project under hardware/
    build: Callable[[], ga.Design]
    suffix: str  # file name part after "<project>-assembly-"
    views: dict[str, tuple[list[str], int, int]]  # name -> (extra kicad-cli render args, width, height)
    export: bool = False  # written as STEP/GLB with --export
    sheet: dict[str, str] | None = None  # views composed into one labelled sheet, view -> label
    keep: tuple[str, ...] | None = None  # views written as separate PNGs (None: all of them)


RADIO = "esp32c3-radio-adapter"
VARIANTS = {
    "radio-e07": Variant(RADIO, lambda: ga.build_radio("e07"), "e07", VIEWS, export=True),
    "radio-ra02": Variant(RADIO, lambda: ga.build_radio("ra02"), "ra02", VIEWS, export=True),
    "radio-e07-case-closed": Variant(RADIO, lambda: ga.build_radio("e07", case="closed"), "e07-case-closed", CASE_VIEWS, export=True, sheet=CLOSED_SHEET, keep=()),
    "radio-ra02-case-closed": Variant(RADIO, lambda: ga.build_radio("ra02", case="closed"), "ra02-case-closed", CASE_VIEWS, export=True, sheet=CLOSED_SHEET, keep=()),
    "radio-e07-case-open": Variant(RADIO, lambda: ga.build_radio("e07", case="open"), "e07-case-open", CASE_VIEWS, sheet=OPEN_SHEET, keep=("top",)),
    "radio-ra02-case-open": Variant(RADIO, lambda: ga.build_radio("ra02", case="open"), "ra02-case-open", CASE_VIEWS, sheet=OPEN_SHEET, keep=("top",)),
    "radio-e07-case-exploded": Variant(RADIO, lambda: ga.build_radio("e07", case="exploded"), "e07-case-exploded", EXPLODED_VIEWS),
    "radio-ra02-case-exploded": Variant(RADIO, lambda: ga.build_radio("ra02", case="exploded"), "ra02-case-exploded", EXPLODED_VIEWS),
    "case-bottom": Variant(RADIO, lambda: ga.build_radio("none", case="bottom"), "case-bottom", BOTTOM_ALONE_VIEWS),
    "case-top": Variant(RADIO, lambda: ga.build_radio("none", case="top"), "case-top", TOP_ALONE_VIEWS),
    "sx1278": Variant("esp32c3-sx1278-adapter", ga.build_sx1278, "module", VIEWS, export=True),
}


def kicad_cli() -> str:
    for c in ("kicad-cli", "/snap/bin/kicad.kicad-cli"):
        if shutil.which(c):
            return c
    raise SystemExit("kicad-cli not found")


def run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"command failed ({r.returncode}): {' '.join(cmd)}\n{r.stdout}{r.stderr}")


def trim(png: pathlib.Path, margin: int = 24) -> None:
    """Crop a transparent-background render to its content plus a margin and put it on white."""
    from PIL import Image  # only the renders need it; CI exports STEP without pillow

    im = Image.open(png).convert("RGBA")
    bbox = im.getchannel("A").getbbox()
    if bbox:
        x0, y0, x1, y1 = bbox
        im = im.crop((max(0, x0 - margin), max(0, y0 - margin), min(im.width, x1 + margin), min(im.height, y1 + margin)))
    white = Image.new("RGBA", im.size, (255, 255, 255, 255))
    Image.alpha_composite(white, im).convert("RGB").save(png)


def compose_sheet(png: pathlib.Path, panels: list[tuple[str, pathlib.Path]], width: int = 2400, gap: int = 48, label_h: int = 56) -> None:
    """One white sheet of labelled renders: the first three panels across the
    top (the isometric view and the two plan views), the rest in a row below,
    each row scaled to a common height so it spans the sheet's width."""
    from PIL import Image, ImageDraw, ImageFont

    rows = [panels[:3], panels[3:]]
    font = ImageFont.load_default(size=label_h * 2 // 3)
    scaled: list[list[tuple[str, Image.Image]]] = []
    for row in rows:
        ims = [(label, Image.open(path).convert("RGB")) for label, path in row]
        h = round((width - gap * (len(ims) + 1)) / sum(im.width / im.height for _, im in ims))
        scaled.append([(label, im.resize((round(im.width * h / im.height), h), Image.LANCZOS)) for label, im in ims])
    height = gap + sum(gap + label_h + row[0][1].height for row in scaled)
    sheet = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    y = gap
    for row in scaled:
        x = gap
        for label, im in row:
            draw.text((x + 8, y + (label_h - font.size) // 2), label, fill=(60, 60, 60), font=font)
            sheet.paste(im, (x, y + label_h))
            x += im.width + gap
        y += label_h + row[0][1].height + gap
    sheet.save(png)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--export", type=pathlib.Path, help="also write STEP and GLB assemblies into this directory")
    ap.add_argument("--no-render", action="store_true", help="skip the PNG renders")
    ap.add_argument("variants", nargs="*", default=list(VARIANTS) + ["parts"], help=f"default: {' '.join(VARIANTS)} parts")
    args = ap.parse_args()
    cli = kicad_cli()
    IMAGES.mkdir(parents=True, exist_ok=True)
    if args.export:
        args.export.mkdir(parents=True, exist_ok=True)
    for variant in args.variants:
        if variant == "parts":
            if args.no_render:
                continue
            for pcb in sorted((ROOT / "hardware" / "parts").glob("*/*.kicad_pcb")):
                png = IMAGES / f"{pcb.stem}-model-iso.png"
                run([cli, "pcb", "render", "--output", str(png), "--width", "1200", "--height", "1000", "--quality", "high",
                     "--background", "transparent", "--define-var", "GIT_DESCRIBE=model", "--perspective", "--rotate", "'-55,0,28'", "--zoom", "0.65", str(pcb)])
                trim(png)
                print(f"wrote {png.relative_to(ROOT)}")
            continue
        v = VARIANTS[variant]
        adapter, export = v.project, args.export and v.export
        if args.no_render and not export:
            continue
        design = v.build()
        design.model_root = str(MODELS)  # the copy lives outside the project tree
        with tempfile.TemporaryDirectory(prefix="asm-", dir=ROOT) as tmp:
            out = pathlib.Path(tmp) / adapter
            with contextlib.redirect_stdout(io.StringIO()):  # Design.write lists every file
                design.write(out)
            pcb = out / f"{adapter}.kicad_pcb"
            define = ["--define-var", "GIT_DESCRIBE=assembly"]
            if not args.no_render:
                rendered: dict[str, pathlib.Path] = {}
                for view, (extra, w, h) in v.views.items():
                    name = f"{adapter}-assembly-{v.suffix}-{view}.png"
                    png = IMAGES / name if v.keep is None or view in v.keep else pathlib.Path(tmp) / name
                    run([cli, "pcb", "render", "--output", str(png), "--width", str(w), "--height", str(h),
                         "--quality", "high", "--background", "transparent", *define, *extra, str(pcb)])
                    trim(png)
                    rendered[view] = png
                    if png.is_relative_to(IMAGES):
                        print(f"wrote {png.relative_to(ROOT)}")
                if v.sheet:
                    png = IMAGES / f"{adapter}-assembly-{v.suffix}-sheet.png"
                    compose_sheet(png, [(label, rendered[view]) for view, label in v.sheet.items()])
                    print(f"wrote {png.relative_to(ROOT)}")
            if export:
                for fmt in ("step", "glb"):
                    dst = args.export / f"{adapter}-assembly-{v.suffix}.{fmt}"
                    run([cli, "pcb", "export", fmt, "--output", str(dst), "--no-dnp", "--include-tracks", "--include-zones",
                         "--subst-models", *define, str(pcb)])
                    print(f"wrote {dst if not dst.is_relative_to(ROOT) else dst.relative_to(ROOT)} ({dst.stat().st_size // 1024} kB)")
                    sums = args.export / "SHA256SUMS"
                    if sums.exists():  # alongside the manufacturing packages
                        with sums.open("a") as f:
                            f.write(f"{hashlib.sha256(dst.read_bytes()).hexdigest()}  {dst.name}\n")


if __name__ == "__main__":
    main()

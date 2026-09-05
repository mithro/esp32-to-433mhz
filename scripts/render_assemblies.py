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
  sx1278       SX1278 module adapter + SuperMini + module + SMA jack

For each it writes docs/images/<adapter>-assembly-<variant>-{iso,top,side}.png
(kicad-cli pcb render) and, with --export DIR, DIR/<adapter>-assembly-<variant>.step
and .glb (kicad-cli pcb export step / glb) for case design.

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

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import generate_adapters as ga  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
MODELS = ROOT / "hardware" / "3d"
IMAGES = ROOT / "docs" / "images"
VARIANTS = {  # name -> (adapter project, builder, file suffix)
    "radio-e07": ("esp32c3-radio-adapter", lambda: ga.build_radio("e07"), "e07"),
    "radio-ra02": ("esp32c3-radio-adapter", lambda: ga.build_radio("ra02"), "ra02"),
    "sx1278": ("esp32c3-sx1278-adapter", ga.build_sx1278, "module"),
}
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
            for pcb in sorted((ROOT / "hardware" / "parts").glob("*/*.kicad_pcb")):
                png = IMAGES / f"{pcb.stem}-model-iso.png"
                run([cli, "pcb", "render", "--output", str(png), "--width", "1200", "--height", "1000", "--quality", "high",
                     "--background", "transparent", "--define-var", "GIT_DESCRIBE=model", "--perspective", "--rotate", "'-55,0,28'", "--zoom", "0.65", str(pcb)])
                trim(png)
                print(f"wrote {png.relative_to(ROOT)}")
            continue
        adapter, build, suffix = VARIANTS[variant]
        design = build()
        design.model_root = str(MODELS)  # the copy lives outside the project tree
        with tempfile.TemporaryDirectory(prefix="asm-", dir=ROOT) as tmp:
            out = pathlib.Path(tmp) / adapter
            with contextlib.redirect_stdout(io.StringIO()):  # Design.write lists every file
                design.write(out)
            pcb = out / f"{adapter}.kicad_pcb"
            define = ["--define-var", "GIT_DESCRIBE=assembly"]
            if not args.no_render:
                for view, (extra, w, h) in VIEWS.items():
                    png = IMAGES / f"{adapter}-assembly-{suffix}-{view}.png"
                    run([cli, "pcb", "render", "--output", str(png), "--width", str(w), "--height", str(h),
                         "--quality", "high", "--background", "transparent", *define, *extra, str(pcb)])
                    trim(png)
                    print(f"wrote {png.relative_to(ROOT)}")
            if args.export:
                for fmt in ("step", "glb"):
                    dst = args.export / f"{adapter}-assembly-{suffix}.{fmt}"
                    run([cli, "pcb", "export", fmt, "--output", str(dst), "--no-dnp", "--include-tracks", "--include-zones",
                         "--subst-models", *define, str(pcb)])
                    print(f"wrote {dst if not dst.is_relative_to(ROOT) else dst.relative_to(ROOT)} ({dst.stat().st_size // 1024} kB)")
                    sums = args.export / "SHA256SUMS"
                    if sums.exists():  # alongside the manufacturing packages
                        with sums.open("a") as f:
                            f.write(f"{hashlib.sha256(dst.read_bytes()).hexdigest()}  {dst.name}\n")


if __name__ == "__main__":
    main()

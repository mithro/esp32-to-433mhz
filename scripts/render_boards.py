#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow", "numpy"]
# ///
"""Render every board under hardware/ to PNG images for the README.

For each project <name> this writes, in docs/images/:
  * <name>-3d-top.png     3D raytraced render of the top side (kicad-cli pcb render)
  * <name>-3d-bottom.png  3D raytraced render of the bottom side
  * <name>-layout.png     2D plot of B.Cu, F.Cu, F.SilkS, F.Fab and Edge.Cuts
                          (kicad-cli pcb export svg, rasterised with inkscape)

All three images of a board have the same pixel size and the same scale:
the frame is the board outline plus MARGIN_MM on every side at SCALE px/mm,
so the 3D renders and the layout plot line up side by side.

The 3D renders are of the bare board: the footprints' 3D models (the
plugged-in modules, headers and so on) are stripped from a temporary copy
first.  scripts/render_assemblies.py renders the boards with their models.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import shutil
import subprocess
import tempfile

import numpy as np
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "images"
SCALE = 36.0  # px per mm
MARGIN_MM = 1.5
# KiCad's default plot colours suit a dark editor background; remap the
# light ones so the layout plot reads on white.
SVG_COLOURS = {
    "#F2EDA1": "#1A1A8C",  # F.SilkS: pale yellow -> dark blue
    "#AFAFAF": "#6E6E6E",  # F.Fab: light grey -> mid grey
    "#D0D2CD": "#000000",  # Edge.Cuts: light grey -> black
}


def find_kicad_cli(explicit: str | None) -> str:
    for candidate in ([explicit] if explicit else []) + ["kicad-cli", "/snap/bin/kicad.kicad-cli"]:
        if candidate and shutil.which(candidate):
            return candidate
    raise SystemExit("kicad-cli not found; pass --kicad-cli")


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def board_rect(pcb: pathlib.Path) -> tuple[float, float, float, float]:
    """(x0, y0, x1, y1) in mm of the Edge.Cuts rectangle written by kicadgen."""
    txt = pcb.read_text()
    m = re.search(r"\(gr_rect\s*\n\s*\(start ([-\d.]+) ([-\d.]+)\)\s*\n\s*\(end ([-\d.]+) ([-\d.]+)\)[\s\S]*?\(layer \"Edge\.Cuts\"\)", txt)
    if not m:
        raise SystemExit(f"{pcb}: no Edge.Cuts gr_rect found")
    x0, y0, x1, y1 = map(float, m.groups())
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def board_px(png: pathlib.Path) -> tuple[int, int]:
    """Pixel width/height of the green solder-mask area in a 3D render."""
    im = np.array(Image.open(png).convert("RGB")).astype(int)
    r, g, b = im[..., 0], im[..., 1], im[..., 2]
    ys, xs = np.where((g - r > 8) & (g - b > 8))
    if len(xs) == 0:
        raise SystemExit(f"{png}: no board found in render")
    return int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)


def fit_canvas(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Centre img on a white canvas of the given size (crop or pad as needed)."""
    canvas = Image.new("RGB", size, "white")
    x = (size[0] - img.width) // 2
    y = (size[1] - img.height) // 2
    canvas.paste(img.convert("RGB"), (x, y))
    return canvas


MODEL_BLOCK = re.compile(r'\n\t\t\(model "[^"]*"\n.*?\n\t\t\)', re.S)


def strip_models(text: str) -> str:
    """Board file text without the footprints' (model ...) blocks."""
    return MODEL_BLOCK.sub("", text)


def render(kicad: str, inkscape: str, pcb: pathlib.Path) -> None:
    name = pcb.stem
    x0, y0, x1, y1 = board_rect(pcb)
    bw, bh = x1 - x0, y1 - y0
    fw, fh = bw + 2 * MARGIN_MM, bh + 2 * MARGIN_MM
    size = (round(fw * SCALE), round(fh * SCALE))

    # The renderer's zoom is relative to its own board fit, so calibrate: render
    # once at zoom 1, measure the board in pixels, then render at the zoom that
    # puts the board at exactly SCALE px/mm (the same scale as the layout plot).
    with tempfile.TemporaryDirectory(prefix="render-", dir=OUT) as tmp:
        tmpdir = pathlib.Path(tmp)
        bare = tmpdir / pcb.name
        bare.write_text(strip_models(pcb.read_text()))

        def render3d(side: str, zoom: float, out: pathlib.Path) -> None:
            run([kicad, "pcb", "render", "--output", str(out), "--side", side,
                 "--width", str(size[0]), "--height", str(size[1]),
                 "--zoom", f"{zoom:.4f}", "--quality", "high", "--background", "opaque", str(bare)])

        probe = tmpdir / "probe.png"
        render3d("top", 1.0, probe)
        pw, ph = board_px(probe)
        zoom = (bw * SCALE / pw + bh * SCALE / ph) / 2
        for side in ("top", "bottom"):
            raw = tmpdir / f"{side}.png"
            render3d(side, zoom, raw)
            fit_canvas(Image.open(raw), size).save(OUT / f"{name}-3d-{side}.png")
        w, h = board_px(OUT / f"{name}-3d-top.png")
        print(f"  {name}: board {bw}x{bh} mm -> {w}x{h} px in 3D ({w / bw:.1f} px/mm), target {SCALE} px/mm")

        # 2D plot on the full A4 page so the board position is known exactly,
        # then crop the board plus margin at the same scale.
        svg = tmpdir / "layout.svg"
        run([kicad, "pcb", "export", "svg", "--output", str(svg), "--layers", "B.Cu,F.Cu,F.SilkS,F.Fab,Edge.Cuts",
             "--page-size-mode", "0", "--exclude-drawing-sheet", "--mode-single", str(pcb)])
        text = svg.read_text()
        for src, dst in SVG_COLOURS.items():
            text = text.replace(src, dst).replace(src.lower(), dst)
        svg.write_text(text)
        page_w = float(re.search(r'width="([\d.]+)mm"', text[:2000]).group(1))
        page_png = tmpdir / "page.png"
        run([inkscape, "--export-type=png", f"--export-width={round(page_w * SCALE)}", "--export-background=white",
             f"--export-filename={page_png}", str(svg)])
        page = Image.open(page_png)
        px_per_mm = page.width / page_w
        box = tuple(round(v * px_per_mm) for v in (x0 - MARGIN_MM, y0 - MARGIN_MM, x1 + MARGIN_MM, y1 + MARGIN_MM))
        fit_canvas(page.crop(box), size).save(OUT / f"{name}-layout.png")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kicad-cli", default=None)
    ap.add_argument("--inkscape", default="inkscape")
    ap.add_argument("boards", nargs="*", help="project names to render (default: all under hardware/)")
    args = ap.parse_args()
    kicad = find_kicad_cli(args.kicad_cli)
    OUT.mkdir(parents=True, exist_ok=True)
    pcbs = sorted(ROOT.glob("hardware/**/*.kicad_pcb"))
    if args.boards:
        pcbs = [p for p in pcbs if p.stem in args.boards]
    for pcb in pcbs:
        render(kicad, args.inkscape, pcb)
    for p in sorted(OUT.glob("*.png")):
        with Image.open(p) as im:
            print(f"wrote {p.relative_to(ROOT)} {im.size[0]}x{im.size[1]}")


if __name__ == "__main__":
    main()

#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Render every board under hardware/ to PNG images for the README.

For each project <name> this writes, in docs/images/:
  * <name>-3d-top.png     3D raytraced render of the top side (kicad-cli pcb render)
  * <name>-3d-bottom.png  3D raytraced render of the bottom side
  * <name>-layout.png     2D plot of F.Cu, F.SilkS, F.Fab and Edge.Cuts
                          (kicad-cli pcb export svg, rasterised with inkscape)
"""

from __future__ import annotations

import argparse
import pathlib
import shutil
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "images"


def find_kicad_cli(explicit: str | None) -> str:
    for candidate in ([explicit] if explicit else []) + ["kicad-cli", "/snap/bin/kicad.kicad-cli"]:
        if candidate and shutil.which(candidate):
            return candidate
    raise SystemExit("kicad-cli not found; pass --kicad-cli")


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def render(kicad: str, inkscape: str, pcb: pathlib.Path) -> None:
    name = pcb.stem
    # Keep the pixel scale similar across boards: ~35 px/mm of board.
    # The renderer frames the board itself, so the image aspect follows the board.
    for side in ("top", "bottom"):
        run([kicad, "pcb", "render", "--output", str(OUT / f"{name}-3d-{side}.png"), "--side", side,
             "--width", "800", "--height", "1000", "--zoom", "0.85", "--quality", "high", str(pcb)])
    with tempfile.TemporaryDirectory(prefix="render-", dir=OUT) as tmp:
        svg = pathlib.Path(tmp) / "layout.svg"
        run([kicad, "pcb", "export", "svg", "--output", str(svg), "--layers", "F.Cu,F.SilkS,F.Fab,Edge.Cuts",
             "--page-size-mode", "2", "--exclude-drawing-sheet", "--mode-single", str(pcb)])
        run([inkscape, "--export-type=png", "--export-width=800", "--export-background=white",
             f"--export-filename={OUT / f'{name}-layout.png'}", str(svg)])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kicad-cli", default=None)
    ap.add_argument("--inkscape", default="inkscape")
    ap.add_argument("boards", nargs="*", help="project names to render (default: all under hardware/)")
    args = ap.parse_args()
    kicad = find_kicad_cli(args.kicad_cli)
    OUT.mkdir(parents=True, exist_ok=True)
    pcbs = sorted(ROOT.glob("hardware/*/*.kicad_pcb"))
    if args.boards:
        pcbs = [p for p in pcbs if p.stem in args.boards]
    for pcb in pcbs:
        render(kicad, args.inkscape, pcb)
    for p in sorted(OUT.glob("*.png")):
        print(f"wrote {p.relative_to(ROOT)} ({p.stat().st_size} bytes)")


if __name__ == "__main__":
    main()

#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Render the SuperMini form-factor board to PNG images for the README.

Produces, in docs/images/:
  * pcb-3d-top.png    3D raytraced render of the top side (kicad-cli pcb render)
  * pcb-3d-bottom.png 3D raytraced render of the bottom side
  * pcb-layout.png    2D plot of F.Cu, F.SilkS, F.Fab and Edge.Cuts
                      (kicad-cli pcb export svg, rasterised with inkscape)
"""

from __future__ import annotations

import argparse
import pathlib
import shutil
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
PCB = ROOT / "hardware" / "esp32-c3-supermini" / "esp32-c3-supermini.kicad_pcb"
OUT = ROOT / "docs" / "images"


def find_kicad_cli(explicit: str | None) -> str:
    for candidate in ([explicit] if explicit else []) + ["kicad-cli", "/snap/bin/kicad.kicad-cli"]:
        if candidate and shutil.which(candidate):
            return candidate
    raise SystemExit("kicad-cli not found; pass --kicad-cli")


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    # kicad-cli (snap) is chatty on stderr; only fail on a non-zero exit.
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kicad-cli", default=None)
    ap.add_argument("--inkscape", default="inkscape")
    args = ap.parse_args()
    kicad = find_kicad_cli(args.kicad_cli)
    OUT.mkdir(parents=True, exist_ok=True)

    for side in ("top", "bottom"):
        run([
            kicad, "pcb", "render",
            "--output", str(OUT / f"pcb-3d-{side}.png"),
            "--side", side, "--width", "800", "--height", "1000",
            "--zoom", "0.85", "--quality", "high",
            str(PCB),
        ])

    with tempfile.TemporaryDirectory(prefix="supermini-render-", dir=OUT) as tmp:
        svg = pathlib.Path(tmp) / "layout.svg"
        run([
            kicad, "pcb", "export", "svg",
            "--output", str(svg),
            "--layers", "F.Cu,F.SilkS,F.Fab,Edge.Cuts",
            "--page-size-mode", "2", "--exclude-drawing-sheet", "--mode-single",
            str(PCB),
        ])
        run([
            args.inkscape, "--export-type=png", "--export-width=800",
            "--export-background=white",
            f"--export-filename={OUT / 'pcb-layout.png'}", str(svg),
        ])
    for p in sorted(OUT.glob("*.png")):
        print(f"wrote {p.relative_to(ROOT)} ({p.stat().st_size} bytes)")


if __name__ == "__main__":
    main()

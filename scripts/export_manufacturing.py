#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Build manufacturing packages (Gerber + Excellon drill zips) for every board
under hardware/, one zip per board per fab, ready to upload for a quote:

  <out>/<board>-rev<N>-jlcpcb.zip
  <out>/<board>-rev<N>-nextpcb.zip
  <out>/SHA256SUMS
  <out>/RELEASE_NOTES.md

The revision N is read from the board's title block.  Each zip holds the
Gerbers (Protel extensions, RS-274X without X2 attributes, mask subtracted
from silk), the drill file(s) and a README.txt with the board's size, stack-up
and the options to pick when ordering (castellated holes where needed).

Fab differences (both follow the fabs' own KiCad guides):
  jlcpcb   PTH and NPTH in a single Excellon file, oval holes as routed slots
  nextpcb  separate PTH / NPTH Excellon files
"""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import re
import shutil
import subprocess
import tempfile
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
LAYERS = "F.Cu,B.Cu,F.Paste,B.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts"
FABS = {
    "jlcpcb": {"name": "JLCPCB", "drill": ["--excellon-oval-format", "route"]},
    "nextpcb": {"name": "NextPCB", "drill": ["--excellon-separate-th"]},
}
# Per-board ordering notes (keyed by project name).
NOTES = {
    "esp32-c3-supermini": "Castellated holes / edge plating REQUIRED (all 16 pins are half-holes on the long edges).",
    "sx1278-lora-module": "Castellated holes / edge plating REQUIRED (keyhole pads on the left and right edges, two castellation-only notches on the bottom edge).",
    "cc1101-e07-m1101d": "SMA jack pads reach the bottom board edge (edge-mount connector); no castellations otherwise.",
    "esp32c3-sx1278-adapter": "Optional SMA pads reach the bottom board edge (edge-mount connector). No castellations.",
    "esp32c3-cc1101-adapter": "All signal tracks are on the bottom copper; the top copper is a GND pour plus pads. No castellations.",
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


def board_info(pcb: pathlib.Path) -> dict:
    txt = pcb.read_text()
    m = re.search(r"\(gr_rect\s*\n\s*\(start ([-\d.]+) ([-\d.]+)\)\s*\n\s*\(end ([-\d.]+) ([-\d.]+)\)[\s\S]*?\(layer \"Edge\.Cuts\"\)", txt)
    x0, y0, x1, y1 = map(float, m.groups())
    return {
        "name": pcb.stem,
        "title": re.search(r'\(title "([^"]*)"', txt).group(1),
        "rev": re.search(r'\(rev "([^"]*)"', txt).group(1),
        "thickness": float(re.search(r"\(thickness ([\d.]+)\)", txt).group(1)),
        "w": abs(x1 - x0),
        "h": abs(y1 - y0),
        "layers": 2,
    }


def readme_text(info: dict, fab: str) -> str:
    return f"""{info['title']}
{'=' * len(info['title'])}

Board:        {info['name']}  rev {info['rev']}
Size:         {info['w']:.2f} x {info['h']:.2f} mm
Layers:       {info['layers']}
Thickness:    {info['thickness']:.1f} mm
Material:     FR-4
Copper:       1 oz (35 um) outer
Finish:       ENIG preferred (HASL acceptable)
Solder mask:  any colour; silkscreen both sides
Notes:        {NOTES.get(info['name'], '')}

Files (Gerber RS-274X, Protel extensions; Excellon drill, mm, absolute origin):
  .GTL .GBL        top / bottom copper
  .GTS .GBS        top / bottom solder mask
  .GTO .GBO        top / bottom silkscreen
  .GTP .GBP        top / bottom paste (stencil, optional)
  .GM1             board outline (Edge.Cuts)
  .DRL             drill{' (PTH and NPTH in one file)' if fab == 'jlcpcb' else ' (-PTH and -NPTH files)'}

Package generated for {FABS[fab]['name']} by scripts/export_manufacturing.py
from https://github.com/mithro/esp32-to-433mhz
"""


def export(cli: str, pcb: pathlib.Path, fab: str, out_zip: pathlib.Path, info: dict) -> None:
    with tempfile.TemporaryDirectory(prefix="mfg-", dir=out_zip.parent) as tmp:
        d = pathlib.Path(tmp)
        run([cli, "pcb", "export", "gerbers", "--output", str(d) + "/", "--layers", LAYERS,
             "--no-x2", "--no-netlist", "--subtract-soldermask", "--exclude-value", str(pcb)])
        run([cli, "pcb", "export", "drill", "--output", str(d) + "/", "--format", "excellon", "--excellon-units", "mm",
             "--excellon-zeros-format", "decimal", "--drill-origin", "absolute", *FABS[fab]["drill"], str(pcb)])
        for job in d.glob("*.gbrjob"):
            job.unlink()
        (d / "README.txt").write_text(readme_text(info, fab))
        with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(d.iterdir()):
                z.write(f, f.name)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=pathlib.Path, default=ROOT / "dist")
    ap.add_argument("boards", nargs="*", help="project names (default: all under hardware/)")
    args = ap.parse_args()
    cli = kicad_cli()
    args.out.mkdir(parents=True, exist_ok=True)
    pcbs = sorted(ROOT.glob("hardware/*/*.kicad_pcb"))
    if args.boards:
        pcbs = [p for p in pcbs if p.stem in args.boards]
    rows = []
    zips = []
    for pcb in pcbs:
        info = board_info(pcb)
        names = {}
        for fab in FABS:
            z = args.out / f"{info['name']}-rev{info['rev']}-{fab}.zip"
            export(cli, pcb, fab, z, info)
            zips.append(z)
            names[fab] = z.name
            print(f"wrote {z.relative_to(ROOT) if z.is_relative_to(ROOT) else z}")
        rows.append(f"| `{info['name']}` | {info['w']:.1f} x {info['h']:.1f} | {info['rev']} | `{names['jlcpcb']}` | `{names['nextpcb']}` |")
    sums = "".join(f"{hashlib.sha256(z.read_bytes()).hexdigest()}  {z.name}\n" for z in zips)
    (args.out / "SHA256SUMS").write_text(sums)
    notes = "\n".join([
        "Manufacturing packages (Gerber + Excellon drill), one zip per board and fab, generated by CI",
        "from the committed KiCad files after ERC/DRC passed. Each zip contains a README.txt with the",
        "board size, stack-up and ordering notes (castellated holes are required for the two module boards).",
        "",
        "| Board | Size (mm) | Rev | JLCPCB | NextPCB |",
        "| --- | --- | --- | --- | --- |",
        *rows,
        "",
    ])
    (args.out / "RELEASE_NOTES.md").write_text(notes)


if __name__ == "__main__":
    main()

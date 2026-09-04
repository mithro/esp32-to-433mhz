#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Fill the copper zones of generated boards in place with KiCad's own zone
filler, so the committed .kicad_pcb files carry their (filled_polygon ...)
data for rendering, Gerber export and DRC.

Usage: fill_zones.py [board.kicad_pcb ...]   (default: every board under hardware/)

The generators write zones without fills; this script loads each board with
the pcbnew Python module, fills, saves KiCad's copy to a temporary file and
copies just the filled_polygon blocks (matched by zone UUID) into the
generated file, leaving everything else byte-identical.  Boards without
copper zones are left untouched.

pcbnew must be importable: it is in KiCad's Docker images and Linux
packages; with the KiCad snap this script re-runs itself inside
``snap run --shell kicad.kicad-cli``, whose Python can load the module.
"""

from __future__ import annotations

import os
import pathlib
import shlex
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
SNAP_SITE = "/snap/kicad/current/usr/lib/python3/dist-packages"


def blocks(text: str, head: str) -> list[tuple[int, int]]:
    """(start, end) of every balanced S-expression starting with `head` at any depth."""
    out = []
    i = 0
    while True:
        i = text.find(head, i)
        if i < 0:
            return out
        depth = 0
        for j in range(i, len(text)):
            if text[j] == "(":
                depth += 1
            elif text[j] == ")":
                depth -= 1
                if depth == 0:
                    out.append((i, j + 1))
                    break
        i = j + 1


def zone_uuid(zone_text: str) -> str:
    k = zone_text.index('(uuid "') + len('(uuid "')
    return zone_text[k : zone_text.index('"', k)]


def fills_by_uuid(text: str) -> dict[str, str]:
    """uuid -> concatenated top-level filled_polygon blocks of each zone."""
    out = {}
    for a, b in blocks(text, "(zone\n"):
        z = text[a:b]
        polys = [z[c:d] for c, d in blocks(z, "(filled_polygon")]
        out[zone_uuid(z)] = "".join("\t\t" + p + "\n" for p in polys)
    return out


def splice(generated: str, fills: dict[str, str]) -> str:
    out = []
    pos = 0
    for a, b in blocks(generated, "(zone\n"):
        z = generated[a:b]
        # strip any existing fills
        for c, d in reversed(blocks(z, "(filled_polygon")):
            line_start = z.rfind("\n", 0, c) + 1
            line_end = z.index("\n", d) + 1
            z = z[:line_start] + z[line_end:]
        new = fills.get(zone_uuid(z), "")
        close = z.rfind("\n", 0, z.rindex(")")) + 1  # start of the zone's closing-paren line
        z = z[:close] + new + z[close:]
        out.append(generated[pos:a])
        out.append(z)
        pos = b
    out.append(generated[pos:])
    return "".join(out)


def fill_board(pcbnew, pcb: pathlib.Path) -> bool:
    text = pcb.read_text()
    if "(zone\n" not in text:
        return False
    board = pcbnew.LoadBoard(str(pcb))
    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(board.Zones())
    with tempfile.TemporaryDirectory(prefix="fill-", dir=pcb.parent) as tmp:
        saved = pathlib.Path(tmp) / pcb.name
        pcbnew.SaveBoard(str(saved), board)
        fills = fills_by_uuid(saved.read_text())
    new = splice(text, fills)
    changed = new != text
    if changed:
        pcb.write_text(new)
    return changed


def main() -> None:
    args = [pathlib.Path(a).resolve() for a in sys.argv[1:]]
    pcbs = args or sorted(ROOT.glob("hardware/**/*.kicad_pcb"))
    try:
        import pcbnew  # type: ignore
    except ImportError:
        pcbnew = None
    if pcbnew is None:
        if os.environ.get("FILL_ZONES_REEXEC") or not shutil.which("snap"):
            raise SystemExit("fill_zones.py: the pcbnew Python module is not importable")
        cmd = "export FILL_ZONES_REEXEC=1 PYTHONPATH=" + SNAP_SITE + "; exec python3 " + " ".join(shlex.quote(str(p)) for p in [pathlib.Path(__file__).resolve(), *pcbs])
        r = subprocess.run(["snap", "run", "--shell", "kicad.kicad-cli"], input=cmd, text=True)
        sys.exit(r.returncode)
    for pcb in pcbs:
        changed = fill_board(pcbnew, pcb)
        print(f"{pcb.relative_to(ROOT) if pcb.is_relative_to(ROOT) else pcb}: {'filled' if changed else 'unchanged'}")


if __name__ == "__main__":
    main()

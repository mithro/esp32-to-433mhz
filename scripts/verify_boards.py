#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Run KiCad ERC and DRC (with schematic parity) on every project under hardware/.

Exits non-zero if any ERC error or any DRC violation is reported.  ERC
warnings about single global labels are expected (each pin carries one label)
and are only counted.  The boards' title-block revision is the GIT_DESCRIBE
text variable, defined here (as in export_manufacturing.py) from git describe.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent


def kicad_cli() -> str:
    for c in ("kicad-cli", "/snap/bin/kicad.kicad-cli"):
        if shutil.which(c):
            return c
    raise SystemExit("kicad-cli not found")


def run(cmd: list[str]) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.stdout + r.stderr


def git_describe() -> str:
    r = subprocess.run(["git", "-C", str(ROOT), "describe", "--tags", "--dirty", "--always", "--match", "v[0-9]*"], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else "unknown"


def main() -> None:
    cli = kicad_cli()
    define = ["--define-var", f"GIT_DESCRIBE={git_describe()}"]
    failed = False
    with tempfile.TemporaryDirectory(prefix="kicad-verify-", dir=ROOT) as tmp:
        for proj in sorted(ROOT.glob("hardware/**/*.kicad_pro")):
            name = proj.stem
            sch, pcb = proj.with_suffix(".kicad_sch"), proj.with_suffix(".kicad_pcb")
            erc = pathlib.Path(tmp) / f"{name}.erc.rpt"
            drc = pathlib.Path(tmp) / f"{name}.drc.rpt"
            run([cli, "sch", "erc", "--format", "report", "--severity-all", *define, "--output", str(erc), str(sch)])
            run([cli, "pcb", "drc", "--format", "report", "--severity-all", "--schematic-parity", *define, "--output", str(drc), str(pcb)])
            if not erc.exists() or not drc.exists():
                print(f"{name}: FAILED to produce reports (file did not load?)")
                failed = True
                continue
            e, d = erc.read_text(), drc.read_text()
            m = re.search(r"ERC messages: (\d+)\s+Errors (\d+)\s+Warnings (\d+)", e)
            erc_err, erc_warn = int(m.group(2)), int(m.group(3))
            warn_kinds = sorted(set(re.findall(r"^\[(\w+)\]", e, re.M)))
            viol = int(re.search(r"Found (\d+) DRC violations", d).group(1))
            unconn = int(re.search(r"Found (\d+) unconnected pads", d).group(1))
            fperr = int(re.search(r"Found (\d+) Footprint errors", d).group(1))
            ok = erc_err == 0 and viol == 0 and unconn == 0 and fperr == 0 and set(warn_kinds) <= {"global_label_dangling"}
            failed |= not ok
            print(f"{name}: ERC errors={erc_err} warnings={erc_warn} {warn_kinds} | DRC violations={viol} unconnected={unconn} footprint_errors={fperr} -> {'OK' if ok else 'FAIL'}")
            if not ok:
                print(textwrap_indent(e) + textwrap_indent(d))
    sys.exit(1 if failed else 0)


def textwrap_indent(s: str) -> str:
    return "".join("    " + line + "\n" for line in s.splitlines() if line.strip())


if __name__ == "__main__":
    main()

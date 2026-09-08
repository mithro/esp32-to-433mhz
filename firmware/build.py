#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# ///
"""Build the ESP32-C3 + CC1101 Tasmota firmware as an overlay on pinned upstream Tasmota.

SPDX-License-Identifier: Apache-2.0

    uv run firmware/build.py                                                    # clone (first time), overlay, compile
    uv run firmware/build.py --overlay-only                                           # just refresh the overlay files
    uv run firmware/build.py --clean                                                  # wipe .pio build dir first

Upstream is NEVER modified: only files are added (driver .ino, tasmota/cc1101_node/,
tasmota/user_config_override.h, platformio_override.ini). The script refuses to build
if the checkout is not at TASMOTA_SHA or if any tracked upstream file is dirty.
PlatformIO is invoked as `uv tool run --from platformio pio` (install once with
`uv tool install platformio`).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import datetime

TASMOTA_REPO = "https://github.com/arendst/Tasmota.git"
TASMOTA_TAG = "v15.5.0"
TASMOTA_SHA = "4561b51993c873e712db83814cb4b669dd3dbd73"
ENV = "tasmota32c3-cc1101"

HERE = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.join(HERE, "build")
CLONE = os.path.join(BUILD, "Tasmota")
DIST = os.path.join(HERE, "dist")

# (source relative to HERE, destination relative to CLONE)
OVERLAY = [
    (os.path.join(HERE, "overlay", "user_config_override.h"), "tasmota/user_config_override.h"),
    (os.path.join(HERE, "overlay", "platformio_override.ini"), "platformio_override.ini"),
    (os.path.join(HERE, "src", "xdrv_95_cc1101.ino"), "tasmota/tasmota_xdrv_driver/xdrv_95_cc1101.ino"),
]
OVERLAY_DIRS = [
    (os.path.join(HERE, "src", "cc1101_node"), "tasmota/cc1101_node"),
    (os.path.join(HERE, "decoders"), "tasmota/cc1101_node/decoders"),
]
OWNED_PATHS = ["tasmota/user_config_override.h", "platformio_override.ini",
               "tasmota/tasmota_xdrv_driver/xdrv_95_cc1101.ino", "tasmota/cc1101_node/"]


def run(cmd, cwd=None, check=True):
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=cwd, check=check)


def ensure_clone():
    if not os.path.isdir(os.path.join(CLONE, ".git")):
        os.makedirs(BUILD, exist_ok=True)
        run(["git", "clone", "--branch", TASMOTA_TAG, "--depth", "1", TASMOTA_REPO, CLONE])
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=CLONE, text=True).strip()
    if sha != TASMOTA_SHA:
        sys.exit("Tasmota checkout is %s, expected %s (%s). Delete %s to re-clone." % (sha, TASMOTA_SHA, TASMOTA_TAG, CLONE))


def assert_upstream_clean():
    out = subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=all"], cwd=CLONE, text=True)
    bad = []
    for line in out.splitlines():
        status, path = line[:2], line[3:]
        if status.strip() in ("??", "A") and any(path.startswith(p) for p in OWNED_PATHS):
            continue                                  # our additions
        bad.append(line)
    if bad:
        sys.exit("Upstream tree has unexpected changes (overlay must only ADD files):\n" + "\n".join(bad))


def apply_overlay():
    for src, rel in OVERLAY:
        dst = os.path.join(CLONE, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
    for src_dir, rel in OVERLAY_DIRS:
        dst = os.path.join(CLONE, rel)
        if os.path.isdir(dst):
            shutil.rmtree(dst)
        shutil.copytree(src_dir, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "build", "tests"))
    print("overlay applied")


def pio(args, jobs):
    cmd = ["uv", "tool", "run", "--from", "platformio", "pio"] + args
    if jobs:
        cmd += ["-j", str(jobs)]
    run(cmd, cwd=CLONE)


def collect(env):
    os.makedirs(DIST, exist_ok=True)
    src = os.path.join(CLONE, ".pio", "build", env)
    info = {"tasmota_tag": TASMOTA_TAG, "tasmota_sha": TASMOTA_SHA, "env": env,
            "built": datetime.datetime.now().astimezone().isoformat(timespec="seconds"), "artefacts": {}}
    for name in ("firmware.bin", "firmware.factory.bin", "firmware.elf", "firmware.map"):
        p = os.path.join(src, name)
        if os.path.exists(p):
            dst = os.path.join(DIST, name.replace("firmware", env))
            shutil.copy2(p, dst)
            info["artefacts"][os.path.basename(dst)] = os.path.getsize(dst)
    # Per-env manifest (so a safeboot build does not clobber the main build's record),
    # plus build-info.json kept as an alias for the default env for backward compatibility
    # (docs/ci.md uploads build-info.json as the firmware artifact).
    with open(os.path.join(DIST, "build-info-%s.json" % env), "w") as f:
        json.dump(info, f, indent=2)
    if env == ENV:
        with open(os.path.join(DIST, "build-info.json"), "w") as f:
            json.dump(info, f, indent=2)
    print(json.dumps(info, indent=2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default=ENV)
    ap.add_argument("--overlay-only", action="store_true")
    ap.add_argument("--clean", action="store_true")
    ap.add_argument("--jobs", type=int, default=0)
    args = ap.parse_args()
    ensure_clone()
    apply_overlay()
    assert_upstream_clean()
    if args.overlay_only:
        return
    if args.clean:
        shutil.rmtree(os.path.join(CLONE, ".pio", "build", args.env), ignore_errors=True)
    pio(["run", "-e", args.env], args.jobs)
    collect(args.env)


if __name__ == "__main__":
    main()

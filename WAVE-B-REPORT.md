# Wave B Report — float-JSON fix + Renode-based CI

Two non-hardware tasks on the `add-tasmota-firmware` branch of
`mithro/esp32-to-433mhz`, done entirely on `desktop.buddy.mithis.com` in the
`~/esp32-to-433mhz-fw` worktree. Both commits are pushed.

```
3df3a62 cc1101-node: add Renode-based firmware CI workflow
4c85365 cc1101-node: render weather-JSON floats without %f (picolibc integer printf)
```

---

## Task 1 — the float-JSON bug

### What it was

The weather decoders formatted their decimal fields (`temperature_C`,
`pressure_hPa`, `wind_avg_m_s`, `wind_max_m_s`, `rain_mm`, `light_lux`,
`supercap_V`, and WH51 `battery_ok`) with `%.1f`/`%.2f` through
`rf_json_append()` → `vsnprintf`. On-target those rendered as the literal
string `*float*`, corrupting the CC1101 and SX1278 weather MQTT payloads.

### The prescribed fix did not apply — and why (honest finding)

The task asked for the newlib-nano remedy `-u _printf_float`. I tried it and it
does **not** work here, because **this toolchain links picolibc, not
newlib-nano**. Evidence gathered from the built ELF and the linked archives:

- The build links `.../picolibc/riscv32-esp-elf/lib/.../libc.a` (map file).
- `vfprintf` resolves to `__i_vfprintf` — picolibc tinystdio's **integer-only**
  formatter. No `__d_vfprintf`/dtoa is pulled in.
- The `*float*` placeholder string is present in the ELF (picolibc emits it for
  `%f` when the float variant is not linked).
- `_printf_float` is **undefined** in the image — picolibc has no such symbol.

Two concrete attempts, both confirmed ineffective:

1. A bare `-u _printf_float` in `build_flags` is **mis-parsed by
   PlatformIO/SCons** — `_printf_float` becomes a `-l` library
   (`cannot find -l.../_printf_float`) and the link fails.
2. The gcc-driver form `-Wl,-u,_printf_float` links, but leaves `_printf_float`
   undefined and `*float*` still in the image (the `-u` finds no definition to
   pull, because picolibc has none). No effect.

picolibc's float printf is selected when the (precompiled Arduino) framework is
built (an sdkconfig/tinystdio choice), and `vsnprintf` calls the integer
formatter statically inside picolibc — a public-`vfprintf` `--defsym` would not
redirect it. So there is no simple, robust app-level build-flag fix.

### The fallback that was applied

Per the task's fallback path, the decimals are now formatted in the decoder
with integer conversions. New helper `rf_ftoa()` in
`firmware/decoders/decode_common.c` (declared in `decode_common.h`) splits the
rounded, scaled value into whole and fractional parts and prints them with
`%d`. `decode_fineoffset.c` now calls `rf_ftoa()` at every former `%f` site.

- **JSON schema is unchanged**: the fields are still emitted as real numbers
  (`13.1`, `1013.25`, `0.3`, `1.0`), so rtl_433 / Home Assistant compatibility
  is preserved and **no host test needed changing**.
- Rounds half away from zero, matching the previous `%.Nf` output for these
  vectors.
- Fixed-width conversions keep gcc `-Werror=format-truncation` happy (an early
  `%0*ld` variable-width version tripped it; fixed).

### Verification

- **Build: SUCCESS** (`tasmota32c3-cc1101`, Tasmota v15.5.0 pinned).
- **RAM: 25.1 %** (82360 / 327680 bytes) — unchanged.
- **Flash: 72.9 %** (2150136 / 2949120 bytes) — +326 bytes vs the pre-fix
  baseline; fits comfortably.
- **Host tests: 120 passed.** These build the decoders as a native `.so` and
  assert the exact JSON values (`temperature_C == 13.1`,
  `pressure_hPa == 1013.25`, `wind_avg_m_s == 0.3`, WH51
  `battery_ok == 1.0 / 0.9`, …) on the same decoder sources the firmware uses.

**On-target render verification is deferred to the hardware batch** — the
CC1101 nodes are power-cycle-blocked and the RA-02 must not be churned. The
host tests are the strongest available evidence short of a live radio.

---

## Task 2 — Renode-based CI

### Emulation branch pushed

`git -C ~/renode-espemu-air push -u origin feature/renode-433-air` succeeded.
Confirmed on GitHub: `refs/heads/feature/renode-433-air` at `fceefc0`
(`git ls-remote origin feature/renode-433-air`).

### Workflow added

`.github/workflows/firmware.yml` — three jobs on push/PR. The existing
`ci.yml` (KiCad board / manufacturing job) is untouched.

| Job | Does | Dry-run on buddy |
|-----|------|------------------|
| `build` | installs uv, `python3 firmware/build.py`, uploads bin/elf/map | ✅ build SUCCESS (full `build.py` run, incl. Tasmota clone already warm) |
| `host-tests` | installs uv, `uv run --with pytest pytest firmware/tests` | ✅ 120 passed |
| `renode` | checkout `mithro/renode-espemu@feature/renode-433-air`; install Renode + ESP-IDF v5.4.1 + robotframework + ROM ELF; build 6 idf.py firmwares; `renode-test` over 7 suites; upload robot_output.xml/log.html/report.html | ⚠️ partially — see below |

The `renode` job mirrors renode-espemu's own `.github/workflows/test.yml`
(Renode portable install, ROM-ELF download, robotframework pin, artifact
upload) plus the WAVE3-REPORT.md CI recipe (the `. export.sh` + six `idf.py`
builds + the single 7-suite `renode-test` invocation).

### What was dry-run on buddy vs. what still needs a live Actions run

Dry-run and **passing** on `desktop.buddy.mithis.com`:

- `python3 firmware/build.py` → build SUCCESS.
- `uv run --with pytest pytest firmware/tests` → 120 passed.
- `idf.py -C peripherals/cc1101_rx/firmware set-target esp32c3 && … build`
  (representative of the six-firmware loop) → build complete.
- `renode-test --variable BASE:$PWD --variable ROM_ELF:… peripherals/cc1101_rx/test.robot`
  → 2/2 OK, produced `robot_output.xml` / `log.html` / `report.html` at the
  repo root (the artifact paths the workflow uploads).

The YAML was structured to match those exact working commands, and it parses
(`yaml.safe_load`: 3 jobs, renode job has 8 steps).

**A live GitHub Actions run is still required** to confirm end-to-end. Not
reproducible from buddy:

- The `Install ESP-IDF v5.4.1` step (`git clone` + `install.sh esp32c3`) — buddy
  already has ESP-IDF installed, so the from-scratch install on a hosted runner
  is untested here.
- Network fetches on a hosted runner (Renode portable tarball, ESP-IDF, the ROM
  ELF release, PlatformIO/Tasmota for the build job).
- Overall runner behaviour/timeouts.

**Runtime / cost note:** the `renode` job is heavy — ESP-IDF install + six
`idf.py` builds + Renode startup dominate; the `build` job's `firmware.build.py`
first run (PlatformIO toolchains + Tasmota clone + full compile) is ~15–20 min.
The renode job is bounded at `timeout-minutes: 120`, the build job at 60.

### Docs

`firmware/docs/ci.md` documents what each job tests and how to run all three
locally, and repeats the dry-run-vs-live caveat.

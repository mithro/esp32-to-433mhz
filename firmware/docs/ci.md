# Firmware CI

`.github/workflows/firmware.yml` runs on every push and pull request. It is
separate from `ci.yml` (which verifies the KiCad boards and builds the
manufacturing packages); the two do not share jobs.

## What it tests

The workflow has three independent jobs:

### `build` — compile the node firmware
Installs `uv`, then runs `python3 firmware/build.py`. `build.py` fetches
PlatformIO, clones the pinned upstream Tasmota (`v15.5.0`,
SHA `4561b519…`), applies the overlay in `firmware/overlay/` +
`firmware/src/` + `firmware/decoders/`, and compiles the
`tasmota32c3-cc1101` environment. The resulting `.bin`/`.elf`/`.map` and
`build-info.json` are uploaded as the `cc1101-node-firmware` artifact.

### `host-tests` — native decoder / firmware tests
Installs `uv`, then `uv run --with pytest pytest firmware/tests`. These build
the decoders and the radio firmware as native shared objects (host `cc`) and
exercise them without hardware: OOK/PWM and Fine Offset (WH24/WS69/WS85/WH51)
decoding, CC1101/SX1278 register presets, the fake-SPI-bus radio drivers, the
aggregate runner, and the capture-format conversion. 120 tests.

### `renode` — instruction-level emulation tests
Checks out `mithro/renode-espemu` at ref `feature/renode-433-air`, installs
Renode (portable), robotframework, the ESP32-C3 ROM ELF, and ESP-IDF
`v5.4.1`. It then builds the six ESP-IDF test firmwares
(`spi2`, `gpio`, `cc1101`, `sx1278`, `cc1101_rx`, `sx1278_rx`; `hello_world`
ships prebuilt binaries) and runs `renode-test` over all seven Robot suites.
These run the real ESP-IDF `spi_master` / GPIO / interrupt path against
emulated CC1101 and SX1278 register models on a shared virtual 433 MHz "air"
medium: an injected FSK frame lands in the radio's RX FIFO and raises the
packet-ready interrupt into the firmware ISR — end to end, no hardware.
`robot_output.xml`, `log.html` and `report.html` are uploaded as the
`renode-test-results` artifact. Any Robot failure fails the job.

## Run it locally

Firmware build and host tests (this repo):

```bash
export PATH="$HOME/.local/bin:$PATH"          # where the uv installer puts uv
python3 firmware/build.py                      # ~15-20 min the first time
uv run --with pytest pytest firmware/tests     # 120 tests, ~20-30 s
```

Renode suites (in a `mithro/renode-espemu` checkout on
`feature/renode-433-air`, with Renode + ESP-IDF v5.4.1 + robotframework
installed):

```bash
. "$HOME/esp/esp-idf/export.sh"
for p in spi2 gpio cc1101 sx1278 cc1101_rx sx1278_rx; do
  idf.py -C peripherals/$p/firmware set-target esp32c3
  idf.py -C peripherals/$p/firmware build
done
renode-test \
  --variable "BASE:$PWD" \
  --variable "ROM_ELF:$HOME/esp/esp-rom-elfs/esp32c3_rev3_rom.elf" \
  peripherals/spi2/test.robot peripherals/gpio/test.robot hello_world/test.robot \
  peripherals/cc1101/test.robot peripherals/sx1278/test.robot \
  peripherals/cc1101_rx/test.robot peripherals/sx1278_rx/test.robot
```

## Notes and caveats

- The `renode` job is heavy: the ESP-IDF install plus six `idf.py` builds plus
  Renode startup dominate its runtime. It is generously bounded
  (`timeout-minutes: 120`).
- The individual commands in every job were dry-run on
  `desktop.buddy.mithis.com` (firmware build, the 120 host tests, an `idf.py`
  test-firmware build, and a `renode-test` suite all pass there). A live
  GitHub Actions run is still needed to confirm the end-to-end workflow —
  especially the ESP-IDF install step and network fetches on a hosted runner.
- The emulation covers packet/FSK RX; OOK-edge RX and the TX path are not yet
  modelled (see `renode-espemu` WAVE3-REPORT.md).

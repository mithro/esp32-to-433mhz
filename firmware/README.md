# Firmware build (Plan B)

Tasmota **v15.5.0** + our overlay (driver `xdrv_95_cc1101.ino`, `tasmota/cc1101_node/`, config/env files). Nothing upstream is edited — see `build.py`'s `assert_upstream_clean()`, which refuses to build if the Tasmota checkout has any tracked-file change outside the overlay's own additions.

    uv tool install platformio                 # once
    uv run firmware/build.py

First run clones Tasmota into `firmware/build/Tasmota/` (git-ignored) and PlatformIO downloads the
ESP32 platform (~1 GB). Artefacts land in `firmware/dist/`:

| File | Use |
|---|---|
| `tasmota32c3-cc1101.factory.bin` | first flash, at offset `0x0`, over native USB with `esptool.py` |
| `tasmota32c3-cc1101.bin` | later updates, uploaded through the Tasmota web UI (Firmware Upgrade) |
| `tasmota32c3-cc1101.elf` / `.map` | debugging (symbols, section sizes) |
| `build-info.json` | Tasmota tag/SHA, build timestamp, artefact sizes |

`build.py --overlay-only` just refreshes the copied-in overlay files without compiling;
`build.py --clean` wipes the PlatformIO `.pio/build` dir first (use after changing build flags,
not needed for ordinary `.ino`/decoder edits).

## First flash (native USB, factory image)

The ESP32-C3 SuperMini's USB-C port is native USB (no separate USB-serial chip). To reach the
ROM download mode the first time (board is blank or running something else):

1. Hold the **BOOT** button (GPIO9).
2. Plug the USB-C cable in (or press RESET) while still holding BOOT, then release.
3. The board enumerates as `303a:1001`. On the deployment host a udev rule symlinks it to
   a stable `/dev/radio-cc1101-node-<serial>` name (see `docs/esp32c3-cc1101-node.md` for the
   USB mapping story).
4. Flash the **factory** image at offset `0x0` (it includes the bootloader + partition table, so
   it is the only image that works on a blank/foreign chip):

       esptool.py --chip esp32c3 --port /dev/radio-cc1101-node-<serial> write_flash 0x0 \
           firmware/dist/tasmota32c3-cc1101.factory.bin

5. Reset (unplug/replug, no BOOT held this time) and it boots into Tasmota's captive-portal WiFi
   setup (`tasmota-XXXX` AP) or the console over the same USB-CDC port at 115200 baud.

If reflashing a board that is already running our firmware (BOOT-button access is always there —
see `RECOVERY.md`), the factory image still works and is the simplest path; it just re-lays the
whole flash including settings, so back up `/cc1101.cfg` first if you care about the persisted
Security+ id/counter (§ below).

## Later updates (OTA / web UI)

`OTA_URL` is intentionally blanked in `overlay/user_config_override.h` — the stock Tasmota
`Upgrade`/`OtaUrl` commands would otherwise pull a **generic** `tasmota32c3` image from
`ota.tasmota.com` and silently drop this driver. Updates are manual instead:

1. Web UI → **Firmware Upgrade** → **Upload** → pick `tasmota32c3-cc1101.bin` (not the
   `.factory.bin`, which duplicates the bootloader/partition table already on the device) → Start.
2. Or `curl -F file=@tasmota32c3-cc1101.bin http://<node-ip>/u2` (Tasmota's upload endpoint).

Either path keeps NVS settings (WiFi, `/cc1101.cfg`, etc.) intact.

## Commissioning a node

See `docs/esp32c3-cc1101-node.md` → *Runbooks → Commission a node* for the full
sequence (template + `Module 0`, `Hostname`/`Topic`, `MqttHost`, `CcMode`, verification). Summary
of the parts specific to this driver:

- Template — apply this **raw template** then `Module 0` (verified on real ESP32-C3 hardware, 2026-08-24):
  ```
  Template {"NAME":"CC1101node","GPIO":[0,0,0,4544,736,672,704,768,0,0,4576,0,0,0,0,0,0,0,0,0,0,0],"FLAG":0,"BASE":1}
  Module 0
  ```
  This assigns GPIO3=`CC1101 GDO0`, GPIO4=`SPI CLK`, GPIO5=`SPI MISO`, GPIO6=`SPI MOSI`, GPIO7=`SPI CS`, GPIO10=`CC1101 GDO2`. **Do not** use the per-pin `GPIO3 CC1101 GDO0` command or the web dropdown for the GDO pins: the `CC1101 GDO0`/`GDO2` template functions are gated behind `#ifdef USE_KEELOQ` upstream, and this build `#undef`s `USE_KEELOQ` (its KeeLoq driver claims the same pins), so those functions are not offered/accepted interactively — only the raw `Template` array assigns them. The CS line is plain `SPI CS` (not a `CC1101 CS` function) — the driver reuses Tasmota's stock `GPIO_SPI_CS`/`USE_SPI` plumbing (ruling R5; see the spec §3.2 note).
- `CcMode weather|remotes` picks the node's role (persisted to `/cc1101.cfg`); a CC1101 cannot do FSK and OOK at once.
- `CcStatus` after commissioning should show `"Present":1`, `"PARTNUM":"0x00"`, `"VERSION":"0x14"`.

## Radio selection and SX1278 (RA-02) support

This build drives **two** radio families over the shared SPI bus and chooses one at boot.

- **`Radio auto|cc1101|sx1278`** (persisted to `/cc1101.cfg`) selects the radio. `auto` reads the
  **GPIO5 board-type strap**, sampled with an internal pulldown then an internal pullup: a
  *floating* pin (reads 0 then 1) means a **CC1101** board; a pin *tied low* (reads 0 both times)
  means an **SX1278 (RA-02)** board.
- For **CC1101**, bring-up **SPI-probes** the known per-board pin maps and keeps whichever answers
  with `PARTNUM 0x00` and `VERSION` in `{0x04, 0x14}`. For **SX1278**, bring-up uses the RA-02 map
  and confirms `RegVersion (0x42) == 0x12`.

Verified per-board pin maps (ESP32-C3 GPIO numbers):

| Board | SCK | MOSI | MISO | CS/NSS | GDO0/RST | GDO2/DIO0 |
|---|---|---|---|---|---|---|
| CC1101 blue (E07) | 3 | 4 | 7 | 9 | GDO0 = 10 | GDO2 = 6 |
| CC1101 green (D-Sun) | 9 | 10 | 3 | 6 | GDO0 = 7 | GDO2 = 4 |
| SX1278 RA-02 | 3 | 4 | 7 | NSS = 9 | RST = 10 | DIO0 = 6 |

> The legacy Tasmota template map (GPIO4 = CLK, 5 = MISO, 6 = MOSI, 7 = CS, 3 = GDO0, 10 = GDO2)
> is also probed first when that template is commissioned, so previously-templated CC1101 nodes
> keep working.

**Foundation scope (this increment):** SX1278 support is currently **reset / identify /
register-I/O + selection only** — no FSK/OOK/LoRa RX/TX yet. The staged roadmap
(FSK-RX -> FSK-TX -> OOK-RX -> OOK-TX -> LoRa) is documented in
`src/cc1101_node/sx1278_radio.cpp`; note OOK-continuous RX will additionally need a **DIO2** wire
the current RA-02 adapter does not route.

SX1278 / selection commands (over MQTT and the USB/web console, like the `Cc*` commands):

| Command | Syntax | Example | Response |
|---|---|---|---|
| `Radio` | `Radio [auto\|cc1101\|sx1278]` | `Radio sx1278` | `{"Radio":{"Config":"sx1278","Active":"sx1278"}}` (setting it re-runs bring-up) |
| `SxStatus` | `SxStatus` | `SxStatus` | `{"SxStatus":{"Present":1,"VERSION":"0x12","Active":1}}` |
| `SxReg` | `SxReg <addr 0x00-0x7F> [val]` (SX1278 must be the active radio) | `SxReg 0x42` | `{"SxReg":{"Addr":"0x42","Value":"0x12"}}` (value read back after any write) |
| `SxReset` | `SxReset` | `SxReset` | `{"SxReset":{"Present":1,"VERSION":"0x12"}}` (pulses RST, then re-identifies) |

## Command reference

All commands work identically over MQTT (`cmnd/<topic>/<Command> <payload>` → response on
`stat/<topic>/RESULT`) and the USB/web console. Examples below show the console form (bare
command + argument) and the JSON the driver responds with.

| Command | Syntax | Example | Response |
|---|---|---|---|
| `CcMode` | `CcMode [remotes\|weather]` | `CcMode weather` | `"weather"` (plain string; `auto` is accepted syntactically but replies `"auto not implemented (spec follow-on)"` and does not change mode — spec §5.3 follow-on) |
| `CcPreset` | `CcPreset [name]` (debug: loads a preset and enters RX with it, overriding `CcMode` until the next `CcMode`/reinit) | `CcPreset fineoffset-fsk` | `"fineoffset-fsk"`; unknown name or no radio present → `"fineoffset-fsk\|ook-433\|ook-tx-100k\|ook-tx-4k"` |
| `CcReg` | `CcReg <addr 0x00-0x3F> [val]` (hex or decimal); writing `addr` in `0x30-0x3D` issues a command **strobe** instead of a register write | `CcReg 0x02 0x0D` | `{"CcReg":{"Addr":"0x02","Value":"0x0D"}}` (`Value` is always read back after any write); no args / no radio → `"addr 0x00-0x3F [val]"` |
| `CcStatus` | `CcStatus` | `CcStatus` | `{"CcStatus":{"Present":1,"PARTNUM":"0x00","VERSION":"0x14","MARCSTATE":"0x0D","Mode":"remotes","Preset":"ook-433","RSSI":-84,"Rx":1234,"Decoded":412,"Tx":3,"Reinit":0,"Overflow":0,"Repeats":57,"Raw":0,"SecplusId":0,"Rolling":0}}` |
| `CcRaw` | `CcRaw <0\|1>` | `CcRaw 1` | `1` (plain number; then every captured OOK frame also publishes `tele/<topic>/CCRAW`, and every undecoded FSK packet too — see MQTT topics below) |
| `CcRfSend` | `CcRfSend {"Data":"0x..","Bits":8-32,"Protocol":1,"Pulse":100-2000,"Repeat":n}` (or a bare decimal/hex `Data` value using the defaults `Bits:24 Protocol:1 Pulse:350 Repeat:10`) — named `CcRfSend`, **not** `RfSend`: see note below | `CcRfSend {"Data":"0x00AABB","Bits":24,"Pulse":350,"Repeat":5}` | `"Done"` / `"Failed"` / `"no radio"` / `"rate limited"` / `"only Protocol 1, Bits 8..32, Pulse 100..2000"`; before transmitting it announces on `rtl_433/nodes/<host>/tx` (see below) |
| `SecplusId` | `SecplusId [id]` (36-bit id, masked to `0xF0FFFFFFFF`) | `SecplusId 12345` | `{"SecplusId":12345}` |
| `SecplusCounter` | `SecplusCounter [n]` (28-bit rolling counter, masked to `0x0FFFFFFF`) | `SecplusCounter` | `0` (plain number; normally left alone — `SecplusSend` increments and persists it itself) |
| `SecplusFreq` | `SecplusFreq [MHz[,MHz[,MHz]]]` (up to 3 legs; each is parsed as a float and kept only if it falls in `(300,1000)`; parsing stops at the first unparseable token, so leading valid legs are accepted and a trailing junk token is dropped; if no leg parses at all, the stored value is left unchanged) | `SecplusFreq 433.30,433.92,434.54` | `{"SecplusFreq":[433.30,433.92,434.54]}`; default (no config yet) is a single leg, `{"SecplusFreq":[433.92]}` |
| `SecplusSend` | `SecplusSend <button 0-15>` | `SecplusSend 1` | `"Done"` / `"Failed"` / `"no radio"` / `"set SecplusId first"` (no `SecplusId` configured yet) / `"rate limited"`; announces on `rtl_433/nodes/<host>/tx`, persists the incremented rolling counter **before** keying the radio (never re-uses a counter value even if the transmit itself fails), then transmits on each configured `SecplusFreq` leg in turn |

Notes:

- **Why `CcRfSend` and not `RfSend`:** this build also compiles in Tasmota's stock `xdrv_17_rcswitch.ino` (`USE_RC_SWITCH`), which already owns the `RfSend`/`CmndRfSend` name — defining another `RfSend` would collide at link time. `CcRfSend` is the CC1101 node's equivalent (same `{"Data":..,"Bits":..,"Protocol":..,"Pulse":..}` shape as the Sonoff-bridge-compatible command described in the design spec's §5.5, just under a different name).
- All `Cc*`/`Secplus*` commands are rate-limited together: at most 10 transmits per rolling 10 s window (`CcTxAllowed()`); once the limit is hit, further transmit commands return `"rate limited"` until the window rolls over.
- `CcReg`/`CcPreset` are debugging aids (mirroring `tools/cc1101.py`), not part of normal commissioning.

## MQTT topics

| Direction | Topic | Example payload |
|---|---|---|
| decoded events (per receiver) | `rtl_433/nodes/<host>/events` | OOK-PWM: `{"time":"2026-08-24T10:15:03","receiver":"cc1101-welland-carport","rssi":-61,"model":"OOK-PWM",...}` (decoder-specific fields follow `rssi`); Security+: `{"time":"...","receiver":"...","rssi":-70,"model":"Secplus-v2","id":12345,"button":1,"rolling":842}`; Fineoffset weather in `weather` mode: `{"time":"...","receiver":"...","rssi":-84,"model":"Fineoffset-WS69","id":174,"temperature_C":13.1,"humidity":82,...}` |
| Tasmota-style remote result (per receiver) | `tele/<topic>/RESULT` | `{"RfReceived":{"Data":"0x00AABB","Bits":25,"Protocol":1,"Pulse":350,"RSSI":-61}}` — published only for the OOK-PWM (`remotes`-mode) decode path, alongside the `events` publish for the same frame |
| raw capture (bench, `CcRaw 1`) | `tele/<topic>/CCRAW` | OOK: `{"Pulses":[350,-1050,700,-700,...]}` (positive = mark, negative = space, in µs); FSK undecoded packet: `{"Packet":"24AE5D8213...","RSSI":-84,"LQI":37}` |
| TX announcement (before keying, ~50 ms lead) | `rtl_433/nodes/<host>/tx` | `CcRfSend`: `{"Data":"0x00AABB","Bits":24,"Protocol":1,"Pulse":350,"model":"OOK-PWM","code":"00aabb"}`; `SecplusSend`: `{"model":"Secplus-v2","id":12345,"button":1,"rolling":843,"fixed":...}` |
| Tasmota teleperiod status | `tele/<topic>/SENSOR` | `...,"CC1101":{"Mode":"remotes","Preset":"ook-433","RSSI":-84,"Rx":1234,"Decoded":412,"Tx":3,"Reinit":0,"SecplusId":12345,"Rolling":843}` (appended to Tasmota's normal `SENSOR` payload via `FUNC_JSON_APPEND`, on the standard `TelePeriod`) |
| commands | `cmnd/<topic>/<Command> <payload>` → `stat/<topic>/RESULT` | see Command reference above |

**`<host>` vs `<topic>` — these are two different Tasmota settings and must both be set at
commissioning time:** `rtl_433/nodes/<host>/...` uses Tasmota's **`Hostname`**
(`NetworkHostname()`); `tele/<topic>/...` and `cmnd/<topic>/...` use Tasmota's **`Topic`**. The
commissioning runbook sets both to the same `cc1101-<site>-<place>` value, but nothing in the
firmware enforces that — if they diverge, the `rtl_433/nodes/...` name and the `tele/...` name for
the same node will not match, which will confuse the aggregator's per-node bookkeeping.

## `/cc1101.cfg` — persisted config

Stored on the Tasmota LittleFS filesystem (`USE_UFILESYS`) as a fixed-size binary struct, loaded
at boot and re-saved whenever a setting changes:

| Field | Type | Meaning |
|---|---|---|
| `magic` | `uint32_t` | `0xCC110101` — file-format sentinel; a file that doesn't match this (or isn't exactly `sizeof(CcConfig)` bytes) is ignored and defaults are used instead (`CcCfgLoad()` requires an exact-size match to avoid reading stack garbage from a truncated file) |
| `version` | `uint8_t` | config struct version, currently `1` |
| `mode` | `uint8_t` | `0` = `remotes`, `1` = `weather` (`CcMode`) |
| `raw` | `uint8_t` | `CcRaw` flag (0/1) |
| `secplus_id` | `uint64_t` | this node's Security+ 2.0 transmitter identity (`SecplusId`), masked to 36 bits |
| `rolling` | `uint32_t` | Security+ rolling counter (`SecplusCounter`), masked to 28 bits |
| `tx_count` | `uint32_t` | lifetime transmit count (mirrors `CcStatus`'s `Tx`, but persisted) |
| `secplus_freq[3]` | `double[3]` | configured Security+ TX frequency legs, MHz (`SecplusFreq`) |
| `secplus_nfreq` | `uint8_t` | how many of `secplus_freq[0..2]` are in use (default `1`, `secplus_freq[0] = 433.92`) |

Defaults (`CcCfgDefaults()`): `mode = remotes`, `raw = 0`, `secplus_id = 0`, `rolling = 0`,
`secplus_freq = [433.92, 0, 0]`, `secplus_nfreq = 1`. See `RECOVERY.md` for restoring/backing up
this file.

## Host tests

    uv run --with pytest pytest firmware/tests -v

Compiles the pure-C/C++ decoder and radio-logic sources into a small host harness
(`tests/radio_host.cpp`) and exercises them against fixtures — no ESP32 hardware needed. This is
what CI/local checks run before anything goes near the bench; it does **not** exercise the Tasmota
glue in `xdrv_95_cc1101.ino` itself (that only builds inside the full PlatformIO/Tasmota tree via
`build.py`).

## See also

- `RECOVERY.md` — reflashing a bricked/misbehaving board, `Reset 5`/`Reset 6`, restoring
  `/cc1101.cfg`.
- `docs/esp32c3-cc1101-node.md` — wiring, BOM, commissioning runbook, bench verification log.
- `docs/HWTEST-RESULTS-cc1101.md` — on-hardware validation log (CC1101 blue/green, SX1278 RA-02).
- The full design spec and numbered rulings (R1-R8) referenced above live in the project repo
  (github.com/mithro/433mhz, `docs/.../2026-08-20-esp32c3-cc1101-tasmota-design.md`).

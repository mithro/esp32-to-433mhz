# Reflash & recovery — ESP32-C3 + CC1101 Tasmota node

How to (re)flash this board, reset Tasmota settings, and restore `/cc1101.cfg`. This node is a
much easier recovery story than the bare-MCU boards in this repo ([ATmega48 bridge](../../atmega-cc1101-firmware/RECOVERY.md),
[E22 EFM8](../../e22-sx1268-firmware/RECOVERY.md)): the ESP32-C3's **ROM bootloader** is the
unbrickable backstop, reachable over the same USB-C port with just a button press — no C2/HVPP
adapter, no case-opening.

## The two kinds of "recovery"

| Failure | Symptom | Fix |
|---|---|---|
| **Bad settings/config** — wrong template, wrong WiFi/MQTT, corrupt `/cc1101.cfg` | boots, radio may misbehave or driver disables itself, but Tasmota itself runs | `Reset 5`/`Reset 6` (console/MQTT command) for Tasmota settings; delete/re-upload `/cc1101.cfg` via the web file manager |
| **Bad flash** — wrong/corrupt firmware image, or a device that isn't running our firmware at all | doesn't boot, or boots into something else entirely | **Hold BOOT, reflash over native USB with `esptool.py`** — always works; the ROM bootloader is independent of whatever is (or isn't) in app flash |

## USB BOOT-button reflash (the backstop)

The ESP32-C3's **ROM bootloader** lives in mask ROM — it cannot be erased, corrupted, or
overwritten by any application flash. Holding **BOOT** (GPIO9) low at reset forces the chip to
run the ROM bootloader instead of whatever is in flash, and it always accepts a new image over the
same native-USB port used for the normal console. This is true no matter how badly the current
flash contents are broken (bad firmware, half-written OTA, wrong chip target, completely blank
flash) — the same reason C2 is unbrickable for the EFM8 boards and HVPP for the ATmega48.

```
# 1. Hold BOOT, plug in USB-C (or press RESET while still holding BOOT), then release.
# 2. Board re-enumerates as 303a:1001 -> /dev/radio-cc1101-node-<serial> (udev rule).
esptool.py --chip esp32c3 --port /dev/radio-cc1101-node-<serial> write_flash 0x0 \
    firmware/dist/tasmota32c3-cc1101-combined.factory.bin
# 3. Unplug/replug WITHOUT holding BOOT -> boots the freshly flashed firmware.
```

Both `.factory.bin`s already lay down the main firmware **and** a Tasmota safeboot image in the
reserved factory slot (Tasmota's build merges a safeboot into every `.factory.bin`), so after this
one BOOT-button flash, later recoveries from a failed OTA happen **over WiFi with no button** (see
[`docs/bootloader-recovery.md`](docs/bootloader-recovery.md) → "Safeboot fallback" for the full
recovery matrix and its limits). Prefer `tasmota32c3-cc1101-combined.factory.bin`: its safeboot is
our own pinned build rather than the network-fetched release one — same recovery behaviour,
reproducible.

Always flash a **`.factory.bin`** here, not the OTA `.bin` — the factory image includes the
bootloader and partition table, so it is the only one guaranteed to boot a device in an unknown
state (wrong partition table, foreign firmware, blank chip). Because it re-lays the whole flash,
this also wipes NVS/settings and the LittleFS filesystem (including `/cc1101.cfg`) — back those up
first if reachable (see below) and they matter.

If `esptool.py` can't find the port or reports sync errors, double-check BOOT was actually held
through the plug-in/power-up moment (a press *after* enumeration is too late) and that no other
process has the port open (`fuser` / close any open console session first).

## Tasmota settings reset (`Reset`)

Standard stock Tasmota command, run from the console or `cmnd/<topic>/Reset`:

| Command | Effect |
|---|---|
| `Reset 1` | Erase Tasmota settings (WiFi/MQTT/GPIO template/etc.), keep current firmware |
| `Reset 5` | Erase Tasmota settings, **keep the saved WiFi SSID/password** so the node rejoins the same network |
| `Reset 6` | Same as `Reset 5`, and also keep the saved MQTT host/user/password/topic |

`Reset 5`/`6` erase the NVS `main`/`qpc` namespaces and delete Tasmota's own `/.settings` file —
they do **not** touch other files on the LittleFS filesystem, so **`/cc1101.cfg` survives a
`Reset 5`/`6`** (verified against Tasmota's `SettingsErase()`/`type==2` path in
`tasmota_support/support_esp32.ino`). After a `Reset 5`/`6` you will need to re-run the template +
`Module 0` + `CcMode` steps from the commissioning runbook (`docs/esp32c3-cc1101-node.md`),
but the node's Security+ id/rolling counter and mode survive if `/cc1101.cfg` wasn't itself the
thing you were trying to reset.

To also clear `/cc1101.cfg` (e.g. to force fresh Security+ pairing), delete it explicitly — see
below; `Reset` alone will not do it.

## Restoring / clearing `/cc1101.cfg`

`/cc1101.cfg` lives on the Tasmota LittleFS filesystem (`USE_UFILESYS`), which has its own web UI
page independent of the firmware-upgrade page: **Consoles → Manage File system** (or
`http://<node-ip>/ufsd`). From there you can:

- **Back up before any risky operation:** download `/cc1101.cfg` to your machine.
- **Restore:** upload a previously downloaded `/cc1101.cfg` back to the same path. The driver
  validates it on the next boot (`magic == 0xCC110101`, `version == 1`, and an exact byte-size
  match — see `firmware/README.md`'s config table); a file that fails validation is silently
  ignored and the node falls back to defaults, it will not crash or refuse to boot.
- **Clear / force defaults:** delete `/cc1101.cfg` from the same page (or just don't restore one
  after a full factory reflash). On the next boot the driver finds no file and loads
  `CcCfgDefaults()`: `mode = remotes`, `raw = 0`, `secplus_id = 0`, `rolling = 0`,
  `secplus_freq = [433.92]`. This is the right move if you want a garage-transmitter node to start
  a *fresh* Security+ pairing (new `SecplusId`, rolling counter back at 0) rather than resuming an
  old identity.

There is no console command to erase just this one file — the file manager page is the only path
(short of the full BOOT-button reflash, which wipes the whole filesystem along with it).

## OTA gone wrong

`OTA_URL` is blanked in this build (see `firmware/README.md`), so the stock `Upgrade`/`OtaUrl`
commands have nowhere to pull from — an accidental `Upgrade 1` fails safely rather than replacing
this firmware with stock `tasmota32c3`. A **manual** web-UI/`curl` upload of the wrong `.bin` (e.g.
another node's build, or `tasmota32c3-cc1101.factory.bin` instead of the OTA image) can still
leave the device in a bad state.

Either `.factory.bin` populates the safeboot slot, so an interrupted or failed main-app OTA does
**not** need the BOOT button: Tasmota performs the main-app OTA from safeboot and erases otadata to
get there, so a failed flash boots back into safeboot (reachable over WiFi) to retry. Re-upload the
main app over WiFi from the safeboot web UI. (Note: this build sets
`CONFIG_BOOTLOADER_SKIP_VALIDATE_ALWAYS`, so the bootloader does **not** validate `app0` — a
corrupt-in-place app is not auto-rejected; it only recovers itself if it crash-loops fast enough to
trip Tasmota's boot-loop→safeboot counter, otherwise it needs the BOOT button.) A full USB brick
always needs the BOOT-button reflash above. See
[`docs/bootloader-recovery.md`](docs/bootloader-recovery.md) → "Safeboot fallback" for the full,
source-verified recovery matrix and its limitations.

## Recovery decision tree

```
Device misbehaving?
├─ Web UI/console reachable, wrong config/template/mode
│   └─ fix directly (template, CcMode, ...), or `Reset 5`/`Reset 6` (keeps /cc1101.cfg) then
│      re-run commissioning.
├─ Web UI/console reachable, want a clean Security+ identity
│   └─ Manage File system -> delete /cc1101.cfg -> reboot -> re-pair.
├─ Bad/interrupted main-app OTA (either .factory.bin has safeboot)
│   └─ node comes up in safeboot (WiFi) -> re-upload the main app over WiFi. No button.
├─ Web UI/console NOT reachable (blank chip, foreign firmware, corrupt-in-place app0, dark node)
│   └─ hold BOOT, reflash tasmota32c3-cc1101-combined.factory.bin over native USB. Always works.
└─ Want to preserve /cc1101.cfg across a factory reflash
    └─ back it up via Manage File system BEFORE reflashing (a factory image wipes the
       filesystem); restore it the same way afterwards.
```

## See also

- [`README.md`](README.md) — build, first flash, OTA, command/MQTT reference, `/cc1101.cfg` fields.
- [`../../esp32c3-cc1101-node.md`](../../esp32c3-cc1101-node.md) — commissioning runbook, wiring, USB
  device mapping.
- [ATmega RECOVERY.md](../../atmega-cc1101-firmware/RECOVERY.md) / [E22 RECOVERY.md](../../e22-sx1268-firmware/RECOVERY.md) —
  the bare-MCU boards' recovery stories, for contrast (this node's ROM bootloader plays the same
  role as their C2/HVPP: an unbrickable backstop independent of app flash content).

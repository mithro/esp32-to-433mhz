# Bootloader / USB recovery and boot-safety hardening — ESP32-C3 + CC1101 node

Three field nodes went dark (presented **no USB** at all) after abrupt power cuts. This document
is the "it's our code, not the hardware" audit: it records why the firmware **cannot** prevent the
ESP32-C3 from bringing up USB or entering ROM download mode on power-on, the safeguards added to
keep it that way, and the exact procedure to recover a dark node once it is physically reachable.

> **Status: UNVERIFIED ON HARDWARE.** All three nodes are currently bricked/dark and none is
> reachable. The changes here are code-level and build-verified only; the recovery procedure and
> the safeguards have **not** been confirmed against a real board. Re-verify on the first node
> recovered (checklist at the bottom).

## Why the app firmware essentially cannot brick USB

On the ESP32-C3 the **mask-ROM bootloader** runs first on every power-on and reset, before a single
byte of application flash executes. It samples the strapping pins and, when **GPIO9 (BOOT)** is low
at reset, enters **ROM download mode** and enumerates the **USB-Serial-JTAG** peripheral (USB
`303a:1001`) for `esptool`. Nothing in application flash can erase, patch, or out-vote the ROM.

There are only two ways software can actually remove that backstop, and **both are one-way eFuse
burns that this project never performs**:

1. **Disabling ROM download mode** (`CONFIG_SECURE_DISABLE_ROM_DL_MODE` /
   `CONFIG_SECURE_UART_ROM_DL_MODE`).
2. **Secure boot / flash encryption** (`CONFIG_SECURE_BOOT`, `CONFIG_SECURE_FLASH_ENC_ENABLED`),
   which gate what the ROM will accept.

Everything else an app can do — reconfigure GPIOs, disable a peripheral at runtime, crash, hang,
half-write flash — is undone by the next reset, because the ROM re-initialises the USB-Serial-JTAG
block from scratch. So a node that presents **no USB even with BOOT held low** is almost certainly a
**hardware** fault (USB connector, 3V3 rail, the chip itself) or a burned eFuse — not our flash.
The safeguards below make the eFuse case impossible to reach by accident from this repo.

## Audit result (config + source, with the safeguards added)

Verified against the pinned build (Tasmota `v15.5.0` @ `4561b519`, platform
`platform-espressif32 2026.05.50`, board `esp32c3`) and the effective Arduino-framework
`sdkconfig` (`framework-arduinoespressif32/.../esp32c3/sdkconfig`):

| # | Concern | Finding | Safeguard added |
|---|---------|---------|-----------------|
| 1 | USB-Serial-JTAG stays the console | `boards/esp32c3.json` sets `-DARDUINO_USB_MODE=1 -DUSE_USB_CDC_CONSOLE`; the Tasmota console is the native USB-Serial-JTAG (HWCDC). In the IDF `sdkconfig` the JTAG block is enabled (`CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG_ENABLED=y`, secondary console). Nothing in the driver disables it at runtime. **OK.** | `#error` in `user_config_override.h` if `USE_USB_CDC_CONSOLE` is ever undefined (e.g. a switch to the UART-only `esp32c3ser` board), plus a warning banner in `platformio_override.ini`. |
| 2 | ROM download mode not disabled | Framework `sdkconfig`: `CONFIG_SECURE_ROM_DL_MODE_ENABLED=y`, and `CONFIG_SECURE_BOOT`, `CONFIG_SECURE_FLASH_ENC_ENABLED`, `CONFIG_FLASH_ENCRYPTION_ENABLED` are all **not set**. The overlay adds no secure/eFuse flags. **OK.** | `#error` guards in `user_config_override.h` that fail the build if secure boot, flash encryption, or ROM-DL-disable are ever set. |
| 3 | GPIO18/19 (USB D-/D+) never used | No template, pin map, or code assigns or drives GPIO18/19 (maps use GPIO3/4/5/6/7/9/10 only). No `gpio_hold`/deep-sleep hold anywhere. **OK — no change needed.** | Documented in the driver strap-safety comment. |
| 4 | Strap pins GPIO2/8/9 not driven low early | Maps never touch GPIO2/GPIO8. GPIO9 is only the blue CSN / green SCK, driven exclusively by the SPI bring-up at **FUNC_INIT** (well after the ROM sampled the straps and USB came up). `ArduinoSpiBus::begin()` idles CS **HIGH**; every SPI op ends `deselect()` (CS HIGH), so GPIO9 rests HIGH. No `FUNC_PRE_INIT` hook, so the driver does no pin I/O before init. **OK.** | Strap-safety comment added at the pin-map/`CC_STRAP_PIN` block in `xdrv_95_cc1101.ino`. |
| 5 | A crash reboots cleanly, never wedges USB | Framework defaults: interrupt WDT (`CONFIG_ESP_INT_WDT`, 300 ms), task WDT with panic (`CONFIG_ESP_TASK_WDT_EN`/`_INIT`/`_PANIC`, 5 s) → a hang panics and reboots (USB re-enumerates). Brownout detector on (`CONFIG_ESP_BROWNOUT_DET`, level 7) with `CONFIG_SPI_FLASH_BROWNOUT_RESET` — the mechanism that protects flash during the abrupt power cuts that started this. The driver's `reset()` handshake is bounded (100 × 1 ms), `identify()` has no loop, and bring-up probes at most three maps, so `FUNC_INIT` cannot spin forever. **OK.** | `#error` if the task WDT is present but auto-init is dropped. |
| 6 | No pin holds persist across reset | No `gpio_hold_en` / `gpio_deep_sleep_hold_en` / `rtc_gpio_hold` / deep-sleep / light-sleep anywhere in `src/` or `overlay/`. **OK — no change needed.** | Stated in the driver strap-safety comment. |

Net: the pre-existing firmware already could not block USB/ROM recovery; the added `#error`
guardrails convert "currently safe" into "a future regression is a **build error**, not a field
brick."

## Recovering a dark node (BOOT-button + esptool over USB-Serial-JTAG)

This is the backstop that works regardless of flash contents. It needs only the USB-C cable — no
JTAG probe, no case opening.

1. **Force ROM download mode.** With the board unpowered, hold **BOOT (GPIO9)** low, then apply
   power (plug in USB-C), then release BOOT. (On a board with a RESET button you can instead hold
   BOOT, tap RESET, release BOOT.) The BOOT press must bridge the power-up/reset instant — a press
   *after* enumeration is too late.
2. **Confirm enumeration.** The chip should appear as USB `303a:1001`. On the lab hosts the udev
   rule maps it to `/dev/radio-cc1101-node-<serial>`; otherwise it is a `/dev/ttyACM*`. Check with
   `esptool.py --chip esp32c3 --port <port> --before no_reset --after no_reset chip_id` (or
   `flash_id`). `--before no_reset` tells esptool the board is *already* in download mode, so it
   does **not** try its own reset dance (which the SuperMini's minimal auto-reset wiring may not
   support).
3. **Reflash the factory image.** Always a `.factory.bin` (bootloader + partition table + app),
   never the OTA `.bin`, because a dark node's flash/partitions are in an unknown state. Prefer the
   **combined** image, which additionally populates the safeboot fallback slot (see the next
   section) so subsequent recoveries need no BOOT button:
   ```
   esptool.py --chip esp32c3 --port <port> --before no_reset --after hard_reset \
       write_flash 0x0 firmware/dist/tasmota32c3-cc1101-combined.factory.bin
   ```
   (`tasmota32c3-cc1101.factory.bin` — main app only, blank safeboot slot — also boots, but leaves
   no button-free fallback; use it only if the combined image is unavailable.)
   If sync still fails, first prove the ROM is alive with a full erase
   (`esptool.py --chip esp32c3 --port <port> --before no_reset erase_flash`), then write again.
   `--after hard_reset` reboots into the freshly flashed firmware; if the board has no auto-reset
   circuit, just unplug/replug **without** holding BOOT.
4. **If even step 2 shows no USB device at all:** BOOT was likely not held through power-up (retry),
   or the port is held open by another process (`fuser -k <port>`, close any console), or — if it
   still never enumerates in download mode — it is a **hardware** fault (USB connector / 3V3 rail /
   chip), not recoverable in software. See `firmware/RECOVERY.md` for the settings-level (`Reset
   5/6`) and filesystem (`/cc1101.cfg`) recovery paths once the node boots again.

### Normal (non-dark) reflash

If the node still boots and enumerates normally, no BOOT press is needed — `esptool.py` with the
default `--before default_reset` will reset it into the bootloader over the same USB port. The
BOOT-button dance above is only for a node that is dark or running unknown/foreign firmware.

## Safeboot fallback — making the button-press the last one

The BOOT-button path above always works, but it needs a human at the board. To remove the button
from every recovery *except* a full USB brick, the node ships a **combined factory image**
(`firmware/tools/combine_safeboot.py` → `tasmota32c3-cc1101-combined.factory.bin`) that populates
two app slots at once:

| Partition | Offset | Contents | Role |
|---|---|---|---|
| `otadata` | `0x0E000` | boot_app0 (→ ota_0) | selects the main app by default |
| `safeboot` (factory) | `0x10000` | stock Tasmota safeboot | minimal WiFi + web-OTA recovery image |
| `app0` (ota_0) | `0xE0000` | CC1101-node firmware | the normal firmware |

The stock safeboot image is built from the **same pinned Tasmota tree** (env `tasmota32c3-safeboot`,
no OTA_URL dependency) — its only job is to bring up WiFi and accept an OTA of the main app. CI
builds it, merges it, and asserts both slots are populated (`test_combined_image.py`).

**Honest recovery matrix** for a node flashed with the combined image:

| Failure | Recovers without the BOOT button? | How |
|---|---|---|
| Failed / interrupted OTA of the main app | **Yes** | Tasmota does the main-app OTA *from* safeboot; an interrupted flash leaves otadata pointing at safeboot, so the node comes back up in safeboot → re-upload over WiFi. |
| Corrupt `app0` image (bad magic/checksum) | **Yes** | The IDF bootloader rejects an invalid selected app and falls back to the `factory` (safeboot) partition → recover over WiFi. |
| Blank `app0` / invalid `otadata` | **Yes** | Bootloader boots the `factory` (safeboot) partition. |
| Main app boots "valid" but then misbehaves in a loop | **Partial** | Tasmota's fast-power-cycle recovery (RTC `fast_reboot_count`; power-cycle several times) resets settings. There is **no automatic revert of a bootloader-valid image** — see the limitation below. |
| Node dark / presents no USB (the power-cut brick) | **No** | Below the safeboot layer entirely — needs the BOOT button + ROM loader above. FIX-BOOTSAFE is the mitigation for *causing* this. |

**Limitation — no IDF anti-rollback.** True bootloader auto-rollback
(`CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE`, which would auto-revert a bootlooping *valid* image)
lives inside the **precompiled** Arduino-framework second-stage bootloader, where it ships
**disabled** (`# CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE is not set`). Enabling it would require
rebuilding the framework/bootloader, which conflicts with the pinned-framework boot-safety
constraint above and would not have prevented the power-cut brick anyway (that is below this layer).
Safeboot therefore covers the *bad-OTA* and *corrupt-image* cases button-free, but not a
valid-but-crashing image; for that, use the fast-power-cycle reset or the BOOT-button reflash.

## Files touched by this hardening

- `firmware/overlay/user_config_override.h` — `#error` guardrails for items 1, 2, 5.
- `firmware/overlay/platformio_override.ini` — boot-safety banner (keep board `esp32c3`; no
  secure/DL-disable flags).
- `firmware/src/xdrv_95_cc1101.ino` — strap-pin safety comment (items 3, 4, 6).
- `firmware/docs/bootloader-recovery.md` — this document.

See also `firmware/RECOVERY.md` (reflash/settings/`/cc1101.cfg` recovery) and
`firmware/docs/esp32c3-cc1101-node.md` (wiring, strap pins, USB device mapping).

## On-hardware re-verification checklist (do on the first node recovered)

- [ ] With BOOT held at power-up, the board enumerates as `303a:1001` and `esptool ... --before
      no_reset chip_id` succeeds.
- [ ] `write_flash 0x0 ...factory.bin` completes and the node boots Tasmota with a working USB
      console.
- [ ] After a normal boot, the USB console is present without any BOOT press (item 1 holds live).
- [ ] `esptool.py --chip esp32c3 --port <port> get_security_info` (or `summary` via `espefuse.py`)
      shows secure boot / flash encryption / download-mode-disable all **off** (item 2 holds live).

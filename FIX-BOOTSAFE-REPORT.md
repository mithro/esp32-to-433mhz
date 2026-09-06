# FIX-BOOTSAFE — ESP32-C3 USB/ROM-download recovery hardening

Goal: make the firmware unable to prevent the ESP32-C3 from bringing up USB or entering ROM
download (bootloader) mode on power-on, after three nodes went dark following abrupt power cuts.

Host: desktop.buddy.mithis.com, worktree `~/esp32-to-433mhz-fw`, branch `add-tasmota-firmware`.
Pinned build: Tasmota v15.5.0 @ 4561b519, platform-espressif32 2026.05.50, board `esp32c3`,
framework-arduinoespressif32 3.3.8.

> **UNVERIFIED ON HARDWARE.** All three nodes are bricked/dark and unreachable. Everything below is
> code-level + build-verified only. The recovery procedure and the added safeguards have NOT been
> confirmed against a live board. Re-verify with the checklist in `firmware/docs/bootloader-recovery.md`
> on the first node physically recovered.

## Audit findings (file:line)

Verified against the overlay, the driver source, and the effective Arduino-framework sdkconfig
(`~/.platformio/packages/framework-arduinoespressif32/tools/esp32-arduino-libs/esp32c3/sdkconfig`).

| # | Item | Result | Evidence (file:line) |
|---|------|--------|----------------------|
| 1 | USB-Serial-JTAG stays the console | **OK** (guard added) | `build/Tasmota/boards/esp32c3.json` extra_flags `-DARDUINO_USB_MODE=1 -DUSE_USB_CDC_CONSOLE`; env `platformio_tasmota_env32.ini:349-351` uses `board = esp32c3`. Framework sdkconfig: `CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG_ENABLED=y`, `CONFIG_USJ_ENABLE_USB_SERIAL_JTAG=y` (JTAG block enabled; Arduino HWCDC is the console). No runtime disable in `src/`. Nuance: the IDF *primary* console is UART0 with USB-Serial-JTAG as the enabled secondary — expected for Arduino-on-C3, where `ARDUINO_USB_MODE=1` routes the console to the JTAG HWCDC anyway. |
| 2 | ROM download mode not disabled | **OK** (guard added) | Framework sdkconfig: `CONFIG_SECURE_ROM_DL_MODE_ENABLED=y`; `# CONFIG_SECURE_BOOT is not set`, `# CONFIG_SECURE_FLASH_ENC_ENABLED is not set`, `# CONFIG_FLASH_ENCRYPTION_ENABLED is not set`. No secure/eFuse flags anywhere in `overlay/` or `build.py`. |
| 3 | GPIO18/19 (USB D-/D+) never used/driven/held | **OK — no change** | No template/pin-map/code assigns GPIO18/19 (maps use GPIO3/4/5/6/7/9/10 only — `src/xdrv_95_cc1101.ino:100-102`). No `gpio_hold`/`deep_sleep_hold` anywhere (grep clean in `src/`, `overlay/`). Documented at `src/xdrv_95_cc1101.ino:104`. |
| 4 | Strap pins GPIO2/8/9 not driven low early | **OK — comment added** | Maps never touch GPIO2/GPIO8. GPIO9 is only blue CSN / green SCK (`src/xdrv_95_cc1101.ino:100-101`), driven only by SPI bring-up at **FUNC_INIT** (`Cc1101NodeInit`->`CcRadioBringUp`, `src/xdrv_95_cc1101.ino:633-635,414-419`), i.e. after the ROM sampled the straps and USB came up. CS idles HIGH: `ArduinoSpiBus::begin()` `pinMode(cs,OUTPUT); digitalWrite(cs,HIGH)` (`:70`), every op ends `deselect()`->HIGH (`:77`). No `FUNC_PRE_INIT` hook (`Xdrv95`, `:638-669`). New comment at `:104-112`. |
| 5 | Crash reboots cleanly, never wedges USB | **OK — guard added** | Framework sdkconfig: `CONFIG_ESP_INT_WDT=y` (300 ms), `CONFIG_ESP_TASK_WDT_EN=y`/`_INIT=y`/`_PANIC=y` (5 s -> panic+reboot), `CONFIG_ESP_BROWNOUT_DET=y` (lvl 7) + `CONFIG_SPI_FLASH_BROWNOUT_RESET=y` (protects flash on the abrupt cuts that started this). Driver init is bounded: `CC1101Radio::reset()` loops <=100x1 ms then returns (`src/cc1101_node/cc1101_radio.cpp:4-9`), `identify()` has no loop (`:10-14`), bring-up probes <=3 maps — so `FUNC_INIT` cannot spin forever. |
| 6 | No pin holds persist across reset | **OK — no change** | No `gpio_hold_en`/`gpio_deep_sleep_hold_en`/`rtc_gpio_hold`/deep-sleep/light-sleep in `src/` or `overlay/` (grep clean). Stated in the driver comment (`:104-112`). |

Net: the pre-existing firmware already could not block USB/ROM recovery (that requires an eFuse
burn this project never performs). The change converts "currently safe" into "a future regression
is a build error, not a field brick," and documents the recovery path.

## Safeguards added (the fixes)

- **`firmware/overlay/user_config_override.h`** — `#error` guardrails for items 1, 2, 5. Item 1 is
  gated on `defined(ESP32C3)` so it fires for any real C3 build that drops `USE_USB_CDC_CONSOLE`
  (e.g. a switch to the UART-only `esp32c3ser` board — confirmed that board defines `-DESP32C3` but
  not `-DUSE_USB_CDC_CONSOLE`) while being skipped in Tasmota's berry dump-defines pre-pass (stub
  sdkconfig, board extra_flags absent). Items 2/5 reference `CONFIG_*` that are simply undefined
  unless someone actively enables them, so they never false-trip.
- **`firmware/overlay/platformio_override.ini`** — boot-safety banner: keep extending
  `env:tasmota32c3` (board `esp32c3`); never `esp32c3ser`; no secure-boot/flash-enc/ROM-DL-disable
  flags.
- **`firmware/src/xdrv_95_cc1101.ino`** — strap-pin boot-safety comment (items 3, 4, 6).
- **`firmware/docs/bootloader-recovery.md`** — the audit write-up + BOOT-button/esptool recovery
  procedure + on-hardware re-verification checklist.

A pitfall found and fixed during build: the first guardrail comment contained the literal
`CONFIG_*/USE_*`, whose `*/` prematurely closed the C comment and broke the real compile
(`'USE_' does not name a type`). Reworded to `USE_ and CONFIG_` — no `*/` in running text.

## Diffs

### firmware/overlay/user_config_override.h
```
+#if defined(ESP32C3) && !defined(USE_USB_CDC_CONSOLE)
+#error "cc1101-node: USB-Serial-JTAG CDC console must stay enabled ... See firmware/docs/bootloader-recovery.md."
+#endif
+#if defined(CONFIG_ESP_CONSOLE_NONE)
+#error "cc1101-node: CONFIG_ESP_CONSOLE_NONE disables the IDF console -- not allowed ..."
+#endif
+#if defined(CONFIG_SECURE_BOOT) || defined(CONFIG_SECURE_FLASH_ENC_ENABLED) || defined(CONFIG_FLASH_ENCRYPTION_ENABLED)
+#error "cc1101-node: secure boot / flash encryption burn eFuses and can permanently block esptool recovery ..."
+#endif
+#if defined(CONFIG_SECURE_DISABLE_ROM_DL_MODE) || defined(CONFIG_SECURE_UART_ROM_DL_MODE)
+#error "cc1101-node: disabling ROM download mode burns an eFuse and permanently removes the BOOT-button USB recovery path ..."
+#endif
+#if defined(CONFIG_ESP_TASK_WDT_EN) && !defined(CONFIG_ESP_TASK_WDT_INIT)
+#error "cc1101-node: task watchdog present but not auto-initialised -- a hung task would not reboot. Keep CONFIG_ESP_TASK_WDT_INIT."
+#endif
```

### firmware/overlay/platformio_override.ini
```
+; BOOT-SAFETY (see firmware/docs/bootloader-recovery.md): this env MUST keep extending
+; env:tasmota32c3, whose board = esp32c3 selects the native USB-Serial-JTAG console. Do NOT
+; switch to tasmota32c3ser / board esp32c3ser (UART-only) ... Do NOT add secure-boot,
+; flash-encryption, or ROM-download-disable build flags/eFuse steps here ...
+; user_config_override.h carries #error guards that fail the build if any of these regress.
```

### firmware/src/xdrv_95_cc1101.ino (after `#define CC_STRAP_PIN 5`)
```
+/* Boot-strap safety ...: no pin map above touches GPIO2 or GPIO8 (strapping) or GPIO18/19
+ * (USB D-/D+). GPIO9 (BOOT strap) is only blue CSN / green SCK, driven solely by the SPI
+ * bring-up at FUNC_INIT ... CS idles HIGH ... No gpio_hold / RTC / deep-sleep hold, so no
+ * pin state persists across a reset to change boot mode; no pin I/O before FUNC_INIT. */
```

Full diffs: commit range `eeea6f7..2dd76f4` on branch `add-tasmota-firmware`.

## Build + test results

- **Build:** `PATH=$HOME/.local/bin:$PATH python3 firmware/build.py` -> **SUCCESS** in 163 s.
  Flash 72.9% (2,150,478 / 2,949,120), RAM 25.1%. Artefacts in `firmware/dist/`:
  `tasmota32c3-cc1101.factory.bin` (3,068,688 B), `.bin` (2,151,184 B), `.elf`, `.map`.
  The berry dump-defines pre-pass now completes with no `#error` (ESP32C3 gate works).
- **Host tests:** `uv run --with pytest pytest firmware/tests` -> **129 passed** in ~51 s.

## Commits (pushed)

```
2dd76f4 cc1101-node: add bootloader / USB recovery + boot-safety doc
1ff7b98 cc1101-node: document strap-pin boot safety in the driver
e5efb31 cc1101-node: build-time boot-safety guardrails for USB/ROM recovery
```
Pushed to `origin/add-tasmota-firmware` (`eeea6f7..2dd76f4`) after a rebase pull from origin
(already up to date).

## Recovery procedure (summary; full version in firmware/docs/bootloader-recovery.md)

1. Unpowered, **hold BOOT (GPIO9) low**, apply USB-C power, release BOOT -> forces ROM download mode.
2. Confirm it enumerates as USB `303a:1001` (lab: `/dev/radio-cc1101-node-<serial>`), then
   `esptool.py --chip esp32c3 --port <port> --before no_reset --after no_reset chip_id`.
3. `esptool.py --chip esp32c3 --port <port> --before no_reset --after hard_reset write_flash 0x0
   firmware/dist/tasmota32c3-cc1101.factory.bin` (erase_flash first if sync fails).
4. If it never enumerates even with BOOT held -> hardware fault (USB connector / 3V3 / chip), not
   software-recoverable.

## Explicit status

**This hardening is UNVERIFIED ON HARDWARE.** No physical node is reachable (all three dark, awaiting
physical recovery). Changes are build-verified and host-tested only. On-hardware confirmation of the
recovery path and the live safeguards is pending, per the checklist in
`firmware/docs/bootloader-recovery.md`.

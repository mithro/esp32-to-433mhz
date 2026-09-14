/* user_config_override.h — ESP32-C3 + CC1101 Tasmota node (firmware/, github.com/mithro/esp32-to-433mhz)
 * SPDX-License-Identifier: GPL-3.0-or-later
 * Copied into tasmota/ by build.py. Only #define/#undef here; no code. */
#ifndef _USER_CONFIG_OVERRIDE_H_
#define _USER_CONFIG_OVERRIDE_H_

#define USE_CC1101_NODE                 // our driver (xdrv_95_cc1101.ino)
#ifndef USE_SPI
#define USE_SPI                         // hardware SPI (SPI CLK/MISO/MOSI + SPI CS template functions)
#endif
#ifndef USE_UFILESYS
#define USE_UFILESYS                    // /cc1101.cfg persistence via TfsSaveFile/TfsLoadFile
#endif
#undef  USE_KEELOQ                      // keeloq's vendored cc1101 lib must not be pulled in
#undef  USE_SPI_LORA                    // keep the SPI bus to ourselves on the node

#undef  PROJECT
#define PROJECT             "cc1101-node"
#undef  FRIENDLY_NAME
#define FRIENDLY_NAME       "CC1101 node"
#undef  OTA_URL
#define OTA_URL             ""          // blank the stock OTA URL: a stock tasmota32c3 OTA would drop this driver
#undef  APP_TIMEZONE
#define APP_TIMEZONE        99          // use TimeZone/TimeDst/TimeStd settings (Adelaide set at commissioning)

/* ---------- boot-safety guardrails (see firmware/docs/bootloader-recovery.md) ----------
 * Three nodes went dark (presented no USB) after abrupt power cuts. These #error guards make a
 * FUTURE config change that would compromise USB / ROM-download recovery a BUILD ERROR here,
 * instead of a silently-unrecoverable node in the field. They change NO runtime behaviour: under
 * the pinned config (board esp32c3, framework defaults) none of them trip.
 *
 * The USE_ and CONFIG_ macros referenced below reach this header because sdkconfig.h and the
 * board -D flags are force-included ahead of it in the real build. The item (1) check is gated on
 * ESP32C3 so it is skipped in Tasmota's berry dump-defines pre-pass (which compiles this header
 * with a stub sdkconfig and without the board extra_flags), while still firing for a real C3 build
 * that dropped the USB console. Do not remove without reading the recovery-path notes. */

// (1) USB-Serial-JTAG CDC console must stay the console. -DUSE_USB_CDC_CONSOLE comes from
//     boards/esp32c3.json; the UART-only board (esp32c3ser) omits it and would leave a dark node
//     with no USB console at all. Keep the env extending tasmota32c3 (board esp32c3).
#if defined(ESP32C3) && !defined(USE_USB_CDC_CONSOLE)
#error "cc1101-node: USB-Serial-JTAG CDC console must stay enabled (build env must use board esp32c3, never the UART-only esp32c3ser) -- without it a dark node cannot be recovered over USB. See firmware/docs/bootloader-recovery.md."
#endif
#if defined(CONFIG_ESP_CONSOLE_NONE)
#error "cc1101-node: CONFIG_ESP_CONSOLE_NONE disables the IDF console -- not allowed for these nodes."
#endif

// (2) ROM download mode must stay reachable. Secure boot / flash encryption / ROM-DL-disable all
//     burn eFuses and can PERMANENTLY remove the BOOT-button esptool recovery path. Never enable.
#if defined(CONFIG_SECURE_BOOT) || defined(CONFIG_SECURE_FLASH_ENC_ENABLED) || defined(CONFIG_FLASH_ENCRYPTION_ENABLED)
#error "cc1101-node: secure boot / flash encryption burn eFuses and can permanently block esptool recovery -- must NOT be enabled. See firmware/docs/bootloader-recovery.md."
#endif
#if defined(CONFIG_SECURE_DISABLE_ROM_DL_MODE) || defined(CONFIG_SECURE_UART_ROM_DL_MODE)
#error "cc1101-node: disabling ROM download mode burns an eFuse and permanently removes the BOOT-button USB recovery path -- must NOT be set. See firmware/docs/bootloader-recovery.md."
#endif

// (5) A crash MUST reboot cleanly (USB re-enumerates each boot) rather than hang. The framework
//     defaults leave the interrupt + task watchdogs enabled with panic-on-timeout and the brownout
//     detector on; this node's config must not silently drop the task watchdog auto-init.
#if defined(CONFIG_ESP_TASK_WDT_EN) && !defined(CONFIG_ESP_TASK_WDT_INIT)
#error "cc1101-node: task watchdog present but not auto-initialised -- a hung task would not reboot. Keep CONFIG_ESP_TASK_WDT_INIT."
#endif

#endif  // _USER_CONFIG_OVERRIDE_H_

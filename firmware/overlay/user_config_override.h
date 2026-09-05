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

#endif  // _USER_CONFIG_OVERRIDE_H_

# Final on-hardware validation runbook (closes criteria b & e)

Everything code-side is done, hardened, and CI-green. This runbook is the turnkey sequence to finish (b) real-hardware validation and (e) live HA MQTT once the three ESP32 nodes are physically recovered. Do it per node; the blue CC1101 is the priority (proves CC1101 on-radio weather/moisture decode), then green, then the RA-02 re-check.

Hosts: build/git on `desktop.buddy.mithis.com` (`~/esp32-to-433mhz-fw`, branch `add-tasmota-firmware`). Flash/console on `rpi5-433mhz` (`ssh tim@ipv4.eth0.rpi5-433mhz.iot.welland.mithis.com`). Firmware image: `firmware/dist/tasmota32c3-cc1101.factory.bin` (rebuild with `python3 firmware/build.py` if stale).

## 0. Recover a dark node (see firmware/docs/bootloader-recovery.md)
The three nodes present no USB after abrupt power cuts (flash wedge — the firmware is confirmed NOT to block bootloader). To recover one:
1. Hold the **BOOT** button on the ESP32-C3 SuperMini.
2. While holding BOOT, apply power to that node — PoE-cycle rpi5 (graceful shutdown → `set_poe gsm7252ps-s1 port 13 off` via `backend=http` → 30 s → on) **or** simply unplug/replug that node's USB.
3. Release BOOT. The C3 is now in ROM download mode and enumerates its USB-Serial-JTAG.
4. Confirm: `ls /dev/serial/by-id/ | grep -i JTAG` shows the node (per-MAC name).

## 1. Flash
`scp firmware/dist/tasmota32c3-cc1101.factory.bin` to rpi5, then:
`esptool --chip esp32c3 --port <dev> --before default_reset --after hard_reset write_flash 0x0 tasmota32c3-cc1101.factory.bin`
Confirm boot over USB-CDC console (persistent pyserial, `dtr=False rts=False`): `Version 15.5.0(cc1101-node)`.

## 2. Commission (per board — verified templates)
- **Blue E07 (CC1101):** `Template {"NAME":"CC1101blue","GPIO":[0,0,0,736,704,0,4576,672,0,768,4544,0,0,0,0,0,0,0,0,0,0,0],"FLAG":0,"BASE":1}` → `Module 0` → `Radio cc1101` → `CcMode weather`.
- **Green D-Sun (CC1101):** `Template {"NAME":"CC1101dsun","GPIO":[0,0,0,672,4576,0,768,4544,0,736,704,0,0,0,0,0,0,0,0,0,0,0],"FLAG":0,"BASE":1}` → `Module 0` → `Radio cc1101` → `CcMode weather`.
- **RA-02 (SX1278):** `Radio sx1278` → `CcMode weather` (SPI pins as blue).

## 3. Validate (b) — CC1101 on-radio decode (the open item)
- `CcStatus` → `Present:1 PARTNUM:0x00 VERSION:0x14`; `CcReg 0x08` → `0x02` (infinite-length FSK RX active).
- Capture the console several minutes → confirm decoded **Fineoffset-WS69 id 174** (valid float temperature_C/wind/rain) and **Fineoffset-WH51** (a live id, moisture/battery). No `*float*`.
- Cross-check the same window against rpi5 `~/wh51-watch/lilygo.hits.jsonl` + `cc1101.hits.jsonl` (always-on reference receivers): same ids/values. This closes (b) for CC1101; SX1278 already proven (WAVE-A2/FIX-A), and both CC1101 boards share one template-driven binary.

## 4. Pluto cross-check (b) — user decision
The Pluto (`rpi-sdr-pluto`) is a single tuner shared with GPS-SDR and is currently deaf on 433 (0 decodes/20 min even free) — needs a VDD power-cycle. Either: coordinate with the "ten64 gps setup" session + get user approval to power-cycle the Pluto, run `rtl_433 -d driver=plutosdr -f 433.92M -s 1024k -g 73 -M level -M time:iso -F json` for ~30 min to catch a WS69, and cross-check vs rpi5; **or** accept the byte-identical rpi5 LilyGo/CC1101 cross-check as (b)'s "other 433 MHz receivers" and note the Pluto's known poor broadband 433 sensitivity.

## 5. Close (e) — live HA MQTT (see firmware/docs/mqtt-home-assistant.md)
- WiFi: `SSID1 ansells-iot`, `Password1 <PSK>` — read the PSK on rpi5: `sudo nmcli -s -g 802-11-wireless-security.psk connection show netplan-wlan0-ansells-iot`. Confirm the node joins (`Status 5` → gets an IP).
- MQTT creds: generate/deploy via `gdoc2netcfg` (locate it via the "gdoc2netcfg" session/host — not on rpi5). Set `MqttHost ha.welland.mithis.com`, `MqttUser`/`MqttPassword`, `Topic cc1101-welland-bench`, and `CcHass 1` (publishes on `rtl_433/<host>/events`, which HA's rtl433-autodiscovery add-on matches via `rtl_433/+/events`).
- Verify PUBLISH: `mosquitto_sub -h ha.welland.mithis.com -t 'rtl_433/#'` (or HA) shows a decoded WS69/WH51 event from the node; confirm HA auto-creates the entity.
- Verify RECEIVE: `mosquitto_pub` a `cmnd/<topic>/CcStatus` → `stat/<topic>/RESULT` returns the JSON. This closes (e).

## 6. Final adversarial confirmation review
Once (b) + (e) are green on hardware, dispatch multiple independent adversarial reviewers to verify all of (a)-(e) are complete to a very high quality (per the goal), fix any residuals, then mark PR #1 **ready for review** (undraft).

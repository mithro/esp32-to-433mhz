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

## 4. Pluto cross-check (b) — status + user decision
The Pluto (`rpi-sdr-pluto`) is a single tuner shared with the GPS-SDR session. Its RX hardware is **proven good** (2026-09-06): after a genuine VDD mains power-cycle, (i) the GPS session acquired 6 satellites through it, and (ii) a wide-IQ FFT (`pluto_fdiag.py`, SoapySDR, staged on `rpi-sdr-pluto`) shows the 433.92 MHz Fine Offset weather/moisture carrier at **~44 dB over noise** — reception is not the problem.

However, `rtl_433` on the Pluto produces **zero output across every tuning/gain tried** (433.92 and offset centres, 250k–1024k, gain 55–73) despite that strong signal. The "no pulses at all with a 44 dB signal present" pattern points to an rtl_433↔Pluto **IQ-scaling / CS16-threshold integration issue** (SoapySDR samples arriving below rtl_433's pulse-detector threshold) — not hardware, antenna, TCXO, or DC offset. It is a software integration bug to fix, not a hardware fault.

Two ways to satisfy (b)'s Pluto clause:
- **Fix the rtl_433/Pluto integration** (sample scaling) or write a small custom FSK demod on the raw IQ (the firmware's `decode_fineoffset.c` can parse the resulting frame), then cross-check a decoded WS69/WH51 against the rpi5 references; **or**
- **Accept the rpi5 LilyGo SX1276 + CC1101 receivers** as (b)'s independent "other 433 MHz receivers" cross-check — they catch WS69+WH51 abundantly (246 WS69 + ~200 WH51 frames in a 10-min window) and SX1278 already cross-checked byte-identical against them.

## 5. Close (e) — live HA MQTT (see firmware/docs/mqtt-home-assistant.md)
Confirmed procedure from the gdoc2netcfg session (verify against its CLAUDE.md "Per-device MQTT broker credentials", ~line 620). gdoc2netcfg runs on **ten64 (welland)** from `/opt/gdoc2netcfg` as root via `.venv/bin/gdoc2netcfg` (NOT `uv run`). Creds are *derived*, not stored: user `tas-<hostname_with_underscores>`, password from `[tasmota] mqtt_secret` in `gdoc2netcfg.toml` — so the device must exist in inventory first.

Prerequisite chain (do per node, once its WiFi MAC is known from the recovered node):
1. **Inventory:** add a row to the "iot.welland - IoT Devices" tab of the "Tim's Home Network IP addresses" sheet — Machine (hostname, e.g. `cc1101-welland-bench`), MAC Address (**required**; the node's WiFi STA MAC), IP (`10.X.90.N`). (Do WITH the user — editing the sheet + DNS is home-network admin, not to be done unattended.)
2. **DNS/DHCP reservation:** on ten64, `sudo .venv/bin/gdoc2netcfg fetch` then `sudo make deploy-dns`.
3. **WiFi on the node:** `SSID1 ansells-iot`, `Password1 <PSK>` — read the PSK on rpi5: `sudo nmcli -s -g 802-11-wireless-security.psk connection show netplan-wlan0-ansells-iot`. Confirm `Status 5` → node joins and gets its reserved IP.
4. **Discover:** on ten64, `sudo .venv/bin/gdoc2netcfg tasmota scan` (finds the node at its IoT IP).
5. **Broker login:** `sudo .venv/bin/gdoc2netcfg tasmota register-broker` (dry-run first) — merges the `tas-*` login into the HA core_mosquitto add-on.
6. **Push creds:** `sudo .venv/bin/gdoc2netcfg tasmota configure <hostname>` (dry-run first) — pushes MqttHost/MqttUser/MqttPassword over the device HTTP API. Then set `Topic <hostname>` and `CcHass 1` (publishes on `rtl_433/<host>/events`, which HA's rtl433-autodiscovery add-on matches via `rtl_433/+/events`). No topic ACL is managed by gdoc2netcfg (the add-on grants full pub/sub unless a custom ACL is set — check add-on config if a publish is refused).
- Verify PUBLISH: `mosquitto_sub -h ha.welland.mithis.com -t 'rtl_433/#'` (or HA UI) shows a decoded WS69/WH51 event from the node; confirm HA auto-creates the entity.
- Verify RECEIVE: `mosquitto_pub` a `cmnd/<topic>/CcStatus` → `stat/<topic>/RESULT` returns the JSON. This closes (e).

## 6. Final adversarial confirmation review
Once (b) + (e) are green on hardware, dispatch multiple independent adversarial reviewers to verify all of (a)-(e) are complete to a very high quality (per the goal), fix any residuals, then mark PR #1 **ready for review** (undraft).

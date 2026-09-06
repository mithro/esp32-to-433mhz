# Wave C — Home Assistant MQTT integration

Goal criterion (e): *correctly publishing and receiving messages with the Home
Assistant MQTT setup.* Done on `desktop.buddy.mithis.com`, worktree
`~/esp32-to-433mhz-fw`, branch `add-tasmota-firmware`. No subagents used.

**Bottom line:** the firmware now publishes decoded RF as rtl_433-shaped JSON on
a topic that Home Assistant's `rtl433-mqtt-autodiscovery` add-on discovers, and
receives its `Cc*/Sx*/Radio/CcRfSend/Secplus*` commands over Tasmota's native
`cmnd/` MQTT. Code + docs + host tests are complete and green. **The live
publish/subscribe against the real broker (`ha.welland.mithis.com:1883`) and HA
is UNVERIFIED — blocked on WiFi + Mosquitto credentials.**

## 1. Audit — what the firmware already did

- Decoded events were already published as rtl_433-shaped JSON to
  `rtl_433/nodes/<host>/events` (`CcPublishEvent` + `CcWrapEvent`), wrapping each
  decoder's JSON with `{"time","receiver","rssi",<decoder fields>}`. Covers
  WS69/WH65B/WS85 (weather), WH51 (moisture), OOK-PWM (remotes), Secplus-v2.
- OOK frames additionally emit Tasmota `RfReceived` on `tele/<topic>/RESULT`;
  raw captures on `tele/<topic>/CCRAW` (`CcRaw 1`); driver status appended to
  `tele/<topic>/SENSOR`; TX announced on `rtl_433/nodes/<host>/tx`.
- Receive side already worked: all commands run through `FUNC_COMMAND`, so
  Tasmota serves them natively on `cmnd/<topic>/<Command>` → `stat/<topic>/RESULT`.
- Float JSON: decoders route decimals through `rf_ftoa` (fixed-point), so
  `temperature_C` etc. are valid JSON numbers. The `*float*` note in the
  2026-09-05 SX1278 HWTEST row **predates** the `rf_ftoa` fix (commit `4c85365`,
  21:23; the HWTEST note commit was 17:26 the same day) and is stale.

**Gap found:** the HA add-on subscribes to `rtl_433/+/events`. MQTT `+` is
single-level, so it matches `rtl_433/<host>/events` but **not** the four-level
`rtl_433/nodes/<host>/events`. So the default topic is HA-discoverable only via
the site aggregator's republish to `rtl_433/<site>/events`; a standalone node had
no directly-discoverable option.

## 2. Design + code added

**Topic/payload design (unchanged JSON shape, selectable topic):**
- Aggregator (default): `rtl_433/nodes/<host>/events` → aggregator →
  `rtl_433/<site>/events` → HA add-on.
- Direct: `rtl_433/<host>/events` → HA add-on (`rtl_433/+/events`) directly.

Chose to **leverage the existing add-on** (not emit `homeassistant/.../config`
from the node): the estate already runs the add-on; duplicating discovery in
firmware would be redundant and un-Tasmota-idiomatic. Justified in the doc.

**Code:**
- `firmware/src/cc1101_node/cc1101_mqtt.{c,h}` — pure-C `cc_events_topic()`,
  `cc_node_topic()`, `cc_wrap_event()`. No Arduino deps → host-testable.
- `firmware/src/xdrv_95_cc1101.ino`:
  - `CcNodeTopic`/`CcPublishEvent`/`CcWrapEvent` now call the pure-C helpers.
  - New persisted `CcHass 0|1` command; `hass` byte carved from `CcConfig`'s
    reserved padding — `sizeof` unchanged, old `/cc1101.cfg` loads with `hass=0`,
    no version bump. `Hass` added to `CcStatus`.

## 3. Receive side — verified (documented)

All commands are Tasmota `FUNC_COMMAND` handlers, reachable over
`cmnd/<topic>/<Command>` with the reply on `stat/<topic>/RESULT`: `CcMode`,
`CcPreset`, `CcReg`, `CcStatus`, `CcRaw`, `CcHass`, `CcRfSend`, `SecplusId/
Counter/Freq/Send`, `SxStatus/Reg/Reset`, `Radio`. `mosquitto_pub`/`sub`
examples documented. (Native Tasmota MQTT-command plumbing; on-broker exercise is
part of the pending live test.)

## 4. Documentation written

- **`firmware/docs/mqtt-home-assistant.md`** (new) — architecture + both
  topologies, topic table, **full per-field JSON schema for every device**, the
  HA autodiscovery setup, receive-over-MQTT with `mosquitto_pub` examples, node
  WiFi/`MqttHost`/`MqttUser`/`MqttPassword`/`Topic`/`Hostname`/`CcHass` config,
  the live-validation procedure, and the host-test summary.
- `firmware/README.md` — `CcHass` command row, `Hass` in the `CcStatus` example
  and `/cc1101.cfg` table, `CcHass`-selectable events topic in *MQTT topics*,
  link to the new doc.
- `firmware/docs/esp32c3-cc1101-node.md` — MQTT section points to the new doc.

## 5. Host tests

`firmware/tests/test_mqtt_shape.py` (8 tests) builds the pure-C helpers into
`libfirmware.so` and asserts: both topic strings byte-exact; direct topic matches
`rtl_433/+/events` and aggregator topic does not (and the inverse for
`rtl_433/nodes/+/events`); tx topic; wrapped event from a **real WH51 decode** is
valid JSON with the envelope + decoder fields intact; a WS69 float stays numeric
(not `*float*`); topic/JSON truncation returns an error.

**Result: `128 passed` (was 120).** Firmware **builds clean**
(`python3 firmware/build.py` → `tasmota32c3-cc1101 SUCCESS`, exit 0);
`cc1101_mqtt.c` confirmed compiled into the image.

## 6. Git

```
07364ff cc1101-node: HA-consumable MQTT — CcHass topic option + host-tested shaping
2ceb3f2 cc1101-node: WAVE-B report (float-JSON fix + Renode CI)
3df3a62 cc1101-node: add Renode-based firmware CI workflow
4c85365 cc1101-node: render weather-JSON floats without %f (picolibc integer printf)
```
Pushed: `2ceb3f2..07364ff  add-tasmota-firmware -> add-tasmota-firmware`.

## 7. Live validation — STILL BLOCKED (UNVERIFIED)

Publishing to / subscribing from the real HA broker has **not** been run.

**Credentials needed:**
1. **WiFi** SSID + passphrase for the deployment network.
2. **Mosquitto** username + password on `ha.welland.mithis.com:1883` (confirm
   anonymous access is off; allocate a node account).

**Exact steps (also in `docs/mqtt-home-assistant.md`):**
1. Commission: `SSID1/Password1`, `MqttHost ha.welland.mithis.com`, `MqttPort
   1883`, `MqttUser/MqttPassword`, `Topic`/`Hostname cc1101-welland-carport`,
   `CcMode weather`, `CcHass 1`.
2. Broker connect: `mosquitto_sub -h ha.welland.mithis.com -u <u> -P <p> -v -t
   'tele/cc1101-welland-carport/LWT'` → expect `Online`.
3. Publish: trigger a WH51/WS69; `mosquitto_sub ... -t 'rtl_433/#'` → expect
   `rtl_433/cc1101-welland-carport/events {"time":...,"model":"Fineoffset-WH51",...}`.
4. HA: add-on log shows a discovery config for the model+id; HA Entities shows the
   moisture + battery sensors updating.
5. Receive: `mosquitto_pub ... -t 'cmnd/cc1101-welland-carport/CcStatus' -n` →
   `stat/.../RESULT {"CcStatus":{...,"Hass":1,...}}`.

Record the outcome in `docs/HWTEST-RESULTS-cc1101.md` once run.

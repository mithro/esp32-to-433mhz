# MQTT integration and Home Assistant

How a CC1101/SX1278 node publishes decoded 433 MHz traffic to MQTT, how Home
Assistant turns that into entities, and how to receive commands back over MQTT.
This is the reference for goal criterion (e) — *"correctly publishing and
receiving messages with the Home Assistant MQTT setup"*.

> **Status (2026-09-05).** Code + host tests are done and green
> (`firmware/tests/test_mqtt_shape.py`, part of the 128-test suite). The
> **live** publish/subscribe against the real broker at
> `ha.welland.mithis.com:1883` is **UNVERIFIED** — it is blocked on the WiFi
> SSID/pass and a Mosquitto username/password, which were not available when
> this was written. The exact live procedure is in
> [Live validation (pending credentials)](#live-validation-pending-credentials);
> run it once the credentials exist and record the result in
> [`HWTEST-RESULTS-cc1101.md`](HWTEST-RESULTS-cc1101.md).

## Architecture

The node runs stock Tasmota's MQTT client (built in — no custom networking). Two
things flow over MQTT:

- **Publish** — every decoded RF frame is emitted as **rtl_433-shaped JSON**, the
  same field names rtl_433 uses, so the standard Home Assistant rtl_433
  autodiscovery tooling recognises it without any per-device configuration.
- **Receive** — the node is driven by Tasmota commands (`Cc*`, `Sx*`, `Radio`,
  `CcRfSend`, `Secplus*`) which Tasmota accepts natively on `cmnd/<topic>/<Command>`
  and answers on `stat/<topic>/RESULT`.

There are two supported publish topologies, selected by the `CcHass` command:

```
  (A) aggregator-fronted (default, CcHass 0)
      node ── rtl_433/nodes/<host>/events ──▶ aggregator ── rtl_433/<site>/events ──▶ HA add-on (rtl_433/+/events)

  (B) direct to Home Assistant (CcHass 1)
      node ── rtl_433/<host>/events ─────────────────────────────────────────────▶ HA add-on (rtl_433/+/events)
```

The Home Assistant `rtl433-mqtt-autodiscovery` add-on subscribes to
`rtl_433/+/events`. MQTT's `+` matches **exactly one** topic level, so it matches
`rtl_433/<host>/events` (topology B) but **not** the four-level
`rtl_433/nodes/<host>/events` (topology A) — which is why topology A relies on the
site aggregator republishing each node's events to the three-level
`rtl_433/<site>/events`. Pick:

- **A (`CcHass 0`, default)** when the site already runs the project aggregator
  (it dedups/namespaces multiple nodes and republishes to HA). Preserves the
  original topic and the aggregator's per-node bookkeeping.
- **B (`CcHass 1`)** for a standalone node talking straight to HA's Mosquitto
  with no aggregator in between. The node's events are then discovered directly.

`CcHass` is persisted to `/cc1101.cfg` and changes only the **events** topic; the
tx-announce topic stays `rtl_433/nodes/<host>/tx` (it is not consumed by HA
autodiscovery). The exact topic string for the current setting is echoed back:

```
CcHass 1  ->  {"CcHass":1,"EventsTopic":"rtl_433/cc1101-welland-carport/events"}
CcHass    ->  {"CcHass":0,"EventsTopic":"rtl_433/nodes/cc1101-welland-carport/events"}
```

## Topic structure

`<host>` is Tasmota's **`Hostname`** (`NetworkHostname()`); `<topic>` is Tasmota's
**`Topic`**. Commission both to the same `cc1101-<site>-<place>` value (see
[Configuring a node](#configuring-a-node)).

| Direction | Topic (`CcHass 0` / `1`) | Payload |
|---|---|---|
| decoded events | `rtl_433/nodes/<host>/events` / `rtl_433/<host>/events` | rtl_433-shaped JSON — see [message schema](#decoded-event-message-schema) |
| tx announce (before keying, ~50 ms lead) | `rtl_433/nodes/<host>/tx` | `CcRfSend`/`SecplusSend` echo — see schema below |
| Tasmota remote result (OOK `remotes` decode) | `tele/<topic>/RESULT` | `{"RfReceived":{"Data":"0x00AABB","Bits":25,"Protocol":1,"Pulse":350,"RSSI":-61}}` |
| raw capture (`CcRaw 1`, bench only) | `tele/<topic>/CCRAW` | OOK: `{"Pulses":[350,-1050,...]}`; FSK undecoded: `{"Packet":"24AE...","RSSI":-84}` |
| driver status at TelePeriod | `tele/<topic>/SENSOR` | Tasmota SENSOR JSON with `"CC1101":{...}` appended |
| commands in | `cmnd/<topic>/<Command> <payload>` | see [Receiving commands](#receiving-commands-over-mqtt) |
| command replies | `stat/<topic>/RESULT` | JSON or plain reply per command |
| Tasmota availability | `tele/<topic>/LWT` | `Online` / `Offline` (retained; MQTT last-will) |

## Decoded event message schema

Every decoded frame is published to the events topic as one JSON object. The
driver wraps each decoder's output with three envelope fields, then the
decoder-specific fields follow verbatim:

| Envelope field | Type | Meaning |
|---|---|---|
| `time` | string | node local time, `YYYY-MM-DDTHH:MM:SS` (`GetDateAndTime(DT_LOCAL)`) |
| `receiver` | string | the node's `Hostname` — which node heard it |
| `rssi` | int | received signal strength, dBm |

Floating-point fields are rendered as real JSON numbers by `rf_ftoa` (fixed-point
integer formatting): the ESP32-C3 image links picolibc's integer-only `printf`,
which would otherwise render `%f` as the literal `*float*` and make the JSON
invalid. All decoders route their decimals through `rf_ftoa`, so
`temperature_C`, `wind_avg_m_s`, `rain_mm`, etc. arrive as `13.1`, not `*float*`.
(This is host-asserted in `test_mqtt_shape.py::test_wrap_event_float_field_is_numeric_not_star_float`.
The `*float*` note in the 2026-09-05 SX1278 row of `HWTEST-RESULTS-cc1101.md`
predates this fix — commit `4c85365`, later the same day — and is stale. A fresh on-air SX1278
capture was subsequently run (FIX-A, commit `eeea6f7`) and confirmed the
decimals render as real JSON numbers, not `*float*`.)

### Fineoffset WS69 / WH65B (weather station, family byte `0x24`)

`model` is `Fineoffset-WS69` for a 25-byte frame (with the pressure/UV/light
tail) or `Fineoffset-WH65B` for the 17-byte frame. Fields present only when the
sensor reports a valid value are marked *(if valid)*.

| Field | Type | Unit / notes |
|---|---|---|
| `model` | string | `Fineoffset-WS69` or `Fineoffset-WH65B` |
| `id` | int | 8-bit sensor id |
| `battery_ok` | int | 1 = OK, 0 = low |
| `temperature_C` | float (1 dp) | °C *(if valid)* |
| `humidity` | int | % RH *(if valid)* |
| `pressure_hPa` | float (2 dp) | hPa, WS69 tail only, if a barometer is fitted *(if valid; not yet cross-checked against a real barometer frame)* |
| `wind_dir_deg` | int | degrees *(if valid)* |
| `wind_avg_m_s` | float (1 dp) | m/s *(if valid)* |
| `wind_max_m_s` | float (1 dp) | m/s gust *(if valid)* |
| `rain_mm` | float (1 dp) | mm cumulative |
| `uv` | int | raw UV *(if valid)* |
| `uvi` | int | UV index 0–12 *(if valid)* |
| `light_lux` | float (1 dp) | lux *(if valid)* |
| `mic` | string | `CRC` — integrity check passed (CRC-8 poly 0x31 + additive sum) |

### Fineoffset WS85 (weather station, family byte `0x85`)

| Field | Type | Unit / notes |
|---|---|---|
| `model` | string | `Fineoffset-WS85` |
| `id` | int | 24-bit sensor id |
| `battery_ok` | int | 1 if battery > 2400 mV |
| `battery_pct` | int | 0–100 % |
| `battery_mV` | int | mV |
| `wind_dir_deg` | int | degrees *(if valid)* |
| `wind_avg_m_s` | float (1 dp) | m/s *(if valid)* |
| `wind_max_m_s` | float (1 dp) | m/s gust *(if valid)* |
| `flags` | int | raw status flags byte |
| `rain_mm` | float (1 dp) | mm |
| `rain_start` | int | rain-start flag |
| `supercap_V` | float (1 dp) | supercapacitor volts |
| `firmware` | int | sensor firmware byte |
| `mic` | string | `CRC` |

> WS85 is not audible at Welland (its frame is longer than the CC1101's 25-byte
> fixed packet), so on the CC1101 path this branch is validated by the decoder
> host test only; the SX1278 path (30-byte packet) can receive it. See the
> node doc's *Fine Offset FSK* sections.

### Fineoffset WH51 (soil moisture, family byte `0x51`)

| Field | Type | Unit / notes |
|---|---|---|
| `model` | string | `Fineoffset-WH51` |
| `id` | string | 24-bit id, lowercase hex e.g. `"0f5c54"` |
| `battery_ok` | float (1 dp) | rtl_433 coarse level 0.0–1.0 (alkaline-AA ladder), **not** a 0/1 flag |
| `battery_mV` | int | mV (5-bit reading × 100) |
| `moisture` | int | % |
| `boost` | int | TX-period boost bits |
| `ad_raw` | int | 9-bit raw ADC behind the moisture % |
| `mic` | string | `CRC` |

### OOK-PWM remotes (`remotes` mode)

| Field | Type | Notes |
|---|---|---|
| `model` | string | `OOK-PWM` |
| `family` | string | timing family: `standard` or `fixed-period` |
| `bits` | int | decoded bit count |
| `code` | string | packed code, hex |
| `short_us` | int | measured short mark, µs |
| `long_us` | int | measured long mark, µs |
| `gap_us` | int | inter-packet gap, µs |

The same OOK frame is **also** published as a Tasmota `RfReceived` result on
`tele/<topic>/RESULT` (Sonoff-bridge-compatible `Data`/`Bits`/`Protocol`/`Pulse`/`RSSI`).
See the "known limitation" on the reported bit count for RCSwitch-1 remotes in
[`../README.md`](../README.md) → *MQTT topics* and the driver comment on
`CcPublishRfReceived`.

### Security+ 2.0 (`Secplus-v2`)

| Field | Type | Notes |
|---|---|---|
| `model` | string | `Secplus-v2` |
| `id` | int | 36-bit transmitter id (masked `0xF0FFFFFFFF`) |
| `button` | int | 0–15 |
| `rolling` | int | rolling counter |
| `fixed` | int | full 40-bit fixed field |
| `data` | int | present only for the 64-bit frame type |

### tx-announce payloads

Published to `rtl_433/nodes/<host>/tx` ~50 ms before the radio keys:

- `CcRfSend`: `{"Data":"0x00AABB","Bits":24,"Protocol":1,"Pulse":350,"model":"OOK-PWM","code":"00aabb"}`
- `SecplusSend`: `{"model":"Secplus-v2","id":12345,"button":1,"rolling":843,"fixed":...}`

## Home Assistant setup (rtl_433 autodiscovery)

The estate ingests RF via the **`rtl433-mqtt-autodiscovery`** Home Assistant
add-on (the rtl_433 project's `rtl_433_mqtt_hass.py`), pointed at the Mosquitto
broker HA runs at `ha.welland.mithis.com:1883`. It:

1. subscribes to `rtl_433/+/events`;
2. reads each JSON event and, keyed by `model` + `id` (+ `channel` if present),
   publishes Home Assistant **MQTT discovery** config messages under
   `homeassistant/…/config`;
3. HA then auto-creates entities and binds them to the incoming values —
   temperature/humidity/pressure/wind/rain/UV/light for WS69, moisture + battery
   for WH51, wind/rain/battery for WS85, etc. `battery_ok` becomes a battery
   diagnostic. No per-device YAML is needed.

Because the node already emits the exact rtl_433 field names and a valid JSON
envelope, **no custom HA discovery code lives in the firmware** — this is
deliberately the "leverage the existing add-on" path the design calls for, rather
than the node publishing `homeassistant/.../config` itself. (A node with **no**
aggregator and **no** add-on could instead be given `CcHass 1` and paired with
the add-on directly; publishing raw HA discovery messages from the node was
considered and rejected as duplicating the add-on the estate already runs.)

To make a node discoverable:

- **Topology A (aggregator present):** leave `CcHass 0`. Ensure the aggregator is
  subscribed to `rtl_433/nodes/+/events` and republishing to `rtl_433/<site>/events`
  (the add-on's `rtl_433/+/events` then sees it). No node-side change.
- **Topology B (direct):** set `CcHass 1`. The add-on discovers
  `rtl_433/<host>/events` directly.

## Receiving commands over MQTT

Every driver command works identically over MQTT and the USB/web console. Over
MQTT: publish to `cmnd/<topic>/<Command>` with the argument as the payload; the
reply arrives on `stat/<topic>/RESULT`. Examples (`mosquitto_pub`):

```bash
# query the radio
mosquitto_pub -h ha.welland.mithis.com -u <user> -P <pass> \
  -t 'cmnd/cc1101-welland-carport/CcStatus' -n
#   -> stat/cc1101-welland-carport/RESULT  {"CcStatus":{"Present":1,...,"Hass":0,...}}

# set the node's role
mosquitto_pub ... -t 'cmnd/cc1101-welland-carport/CcMode' -m 'weather'

# switch to direct-HA events topic
mosquitto_pub ... -t 'cmnd/cc1101-welland-carport/CcHass' -m '1'

# transmit an OOK remote code
mosquitto_pub ... -t 'cmnd/cc1101-welland-carport/CcRfSend' \
  -m '{"Data":"0x00AABB","Bits":24,"Pulse":350,"Repeat":5}'

# radio selection / SX1278 register read
mosquitto_pub ... -t 'cmnd/cc1101-welland-carport/Radio' -m 'sx1278'
mosquitto_pub ... -t 'cmnd/cc1101-welland-carport/SxReg'  -m '0x42'
```

Full command syntax and replies are in [`../README.md`](../README.md) →
*Command reference* and *Radio selection*. The complete command set reachable
over `cmnd/`: `CcMode`, `CcPreset`, `CcReg`, `CcStatus`, `CcRaw`, `CcHass`,
`CcRfSend`, `SecplusId`, `SecplusCounter`, `SecplusFreq`, `SecplusSend`,
`SxStatus`, `SxReg`, `SxReset`, `Radio` (plus all stock Tasmota commands).

## Configuring a node

Set these once at commissioning (over the USB/web console, or later over MQTT):

| Setting | Command | Example |
|---|---|---|
| WiFi | `Backlog SSID1 <ssid>; Password1 <pass>` (or the captive portal) | — |
| Broker host/port | `MqttHost` / `MqttPort` | `MqttHost ha.welland.mithis.com` |
| Broker user/pass | `MqttUser` / `MqttPassword` | `MqttUser cc1101-node` |
| MQTT topic (drives `cmnd/tele/stat`) | `Topic` | `Topic cc1101-welland-carport` |
| Hostname (drives `rtl_433/.../events`) | `Hostname` | `Hostname cc1101-welland-carport` |
| Radio role | `CcMode` | `CcMode weather` |
| Events topology | `CcHass` | `CcHass 1` (direct) or `0` (aggregator, default) |

Set `Topic` and `Hostname` to the **same** value — the driver does not enforce it,
and if they diverge the `rtl_433/.../events` name and the `tele/…` name for the
same node will not match, confusing the aggregator's per-node bookkeeping (see
[`../README.md`](../README.md) → *MQTT topics*).

Confirm the broker connection: `tele/<topic>/LWT` should read `Online`
(retained), and `MqttHost` / `Status 6` echo the configured broker.

## Live validation (pending credentials)

**UNRUN — blocked on credentials.** Publishing to and subscribing from the real
HA broker has not been performed. To run it you need:

1. **WiFi** — SSID + passphrase for the network the node will join at the
   deployment site.
2. **MQTT broker credentials** — a Mosquitto username + password on
   `ha.welland.mithis.com:1883` (the broker HA uses). Confirm anonymous access is
   off and obtain/allocate an account for the node.

Once you have them, on a flashed node with a working radio:

```bash
# 1. Commission (USB/web console)
Backlog SSID1 <ssid>; Password1 <wifi-pass>
Backlog MqttHost ha.welland.mithis.com; MqttPort 1883; MqttUser <user>; MqttPassword <pass>
Backlog Topic cc1101-welland-carport; Hostname cc1101-welland-carport
CcMode weather        # or: remotes
CcHass 1              # direct-to-HA topic, so rtl_433/+/events sees it

# 2. Confirm the broker connection (from any host with mosquitto-clients)
mosquitto_sub -h ha.welland.mithis.com -u <user> -P <pass> -v \
  -t 'tele/cc1101-welland-carport/LWT'
#   expect: tele/cc1101-welland-carport/LWT Online

# 3. Watch the node publish a decoded event (trigger a real WH51/WS69 nearby,
#    or bench a sensor). Expect an rtl_433-shaped JSON line:
mosquitto_sub -h ha.welland.mithis.com -u <user> -P <pass> -v -t 'rtl_433/#'
#   expect e.g.:
#   rtl_433/cc1101-welland-carport/events {"time":"...","receiver":"cc1101-welland-carport","rssi":-84,"model":"Fineoffset-WH51","id":"0f5c54","battery_ok":1.0,"battery_mV":1600,"moisture":40,"boost":0,"ad_raw":208,"mic":"CRC"}

# 4. Confirm Home Assistant auto-created the entities:
#    - the rtl433-mqtt-autodiscovery add-on log shows a discovery config for
#      model=Fineoffset-WH51 id=0f5c54 (and WS69 etc.);
#    - HA Settings -> Devices & Services -> Entities shows a moisture sensor and
#      a battery sensor for that id, updating as events arrive.

# 5. Confirm the RECEIVE path (command over MQTT):
mosquitto_pub -h ha.welland.mithis.com -u <user> -P <pass> -n \
  -t 'cmnd/cc1101-welland-carport/CcStatus'
mosquitto_sub -h ha.welland.mithis.com -u <user> -P <pass> -v \
  -t 'stat/cc1101-welland-carport/RESULT'
#   expect: stat/.../RESULT {"CcStatus":{"Present":1,...,"Hass":1,...}}
```

Record the outcome (broker connect, an events publish seen on
`rtl_433/#`, the HA entity created, and a `cmnd`→`stat` round-trip) in
[`HWTEST-RESULTS-cc1101.md`](HWTEST-RESULTS-cc1101.md).

## Host tests

`firmware/tests/test_mqtt_shape.py` builds the pure-C shaping helpers into
`libfirmware.so` and asserts, off-target:

- both events topics (aggregator + direct) are byte-exact;
- the direct topic matches `rtl_433/+/events` while the aggregator topic does not
  (and vice-versa for `rtl_433/nodes/+/events`);
- the tx topic string;
- a wrapped event built from a **real** WH51 decode is valid JSON with the
  `time`/`receiver`/`rssi` envelope and the decoder fields intact;
- a WS69 float field survives as a numeric value (not `*float*`);
- topic/JSON buffer truncation is reported as an error, not a silent partial.

These do **not** exercise the Tasmota glue (`MqttPublishPayload`, `Hostname`) —
that only compiles inside the full PlatformIO build (`firmware/build.py`) and is
covered by the live procedure above.

## See also

- [`../README.md`](../README.md) — command reference, MQTT topics, `/cc1101.cfg`.
- [`esp32c3-cc1101-node.md`](esp32c3-cc1101-node.md) — wiring, decoders, FSK config.
- [`HWTEST-RESULTS-cc1101.md`](HWTEST-RESULTS-cc1101.md) — on-hardware log (record the live MQTT result here).

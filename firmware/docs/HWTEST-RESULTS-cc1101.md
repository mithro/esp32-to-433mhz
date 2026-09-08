# On-hardware bench validation — Plan B Tasmota firmware

## Real production broker (ha.welland) + native HA discovery — 2026-09-09

Criterion (e) closed on the **real** production broker (this supersedes the isolated-broker
round-trip recorded further below, which stood in before credentials/WiFi were available).

- **blue** (CC1101, `esp32-433mhz-cc1101-blue`, `10.1.90.183`) and **sx** (SX1278,
  `esp32-433mhz-sx1278`, `10.1.90.71`) commissioned onto `ansells-iot` + `ha.welland.mithis.com:1883`
  with per-device `tas-<node_id>` logins (via `gdoc2netcfg tasmota register-broker`/`configure`).
  Both connect: `Status 6` shows `MqttHost:ha.welland.mithis.com`, `MqttCount:1`, and a retained
  `tele/<host>/LWT = Online`.
- **Live weather + moisture on the broker.** Subscribing to the broker (as the node's own login)
  captured both nodes publishing `rtl_433/nodes/<host>/events` — the same Fine Offset WS69 (id 174:
  12.4 °C, 72 %RH, wind, rain) and WH51 (soil moisture, `mic:CRC`) frames, decoded to **identical
  values on both radios**, cross-validating each other on-air.
- **Native HA MQTT Discovery → entities auto-created.** With `CcHassDisc` on (default), the nodes
  self-published `homeassistant/sensor/.../config` + per-field state; **Home Assistant auto-created
  14 sensor entities**, confirmed by querying the HA states API: `sensor.fineoffset_ws69_174_{temperature,
  humidity, wind_speed, wind_gust, wind_direction, rain, battery_ok}` and, for two soil sensors,
  `sensor.fineoffset_wh51_0f4b37_{moisture, battery_voltage, battery_ok}` +
  `sensor.fineoffset_wh51_0f5d7f_{…}`. HA unit-converted wind m/s → km/h from the `wind_speed`
  device_class (proof the discovery metadata is semantically correct). Tasmota's own device
  discovery (`SetOption19`) additionally surfaced each node as a device (14 entities/node).
- **RECEIVE round-trip** on the same broker: `cmnd/<topic>/CcStatus` → `stat/<topic>/RESULT` returned
  the driver JSON.
- **CI (PR #1)**: Build + Host tests + **Renode emulation** jobs all green on this branch head.

Boot-mode note for green: green is byte-identical firmware to blue but its ESP32-C3 board boots
ROM download on power-on — JTAG-proven a GPIO9 reset-edge strap decision (`GPIO_STRAP_REG` = 0x5
download on green vs 0xd flash on blue), decided in mask ROM before any firmware runs, so it is not
a firmware defect (see [`esp32c3-cc1101-node.md`](esp32c3-cc1101-node.md) and the adapter GPIO9
pull-up on `main`).

## Pluto SDR cross-check (criterion b) — investigation and status (2026-09-09)

The `rpi-sdr-pluto` PlutoSDR is the fourth, independent cross-check receiver. Current state:
**the Pluto's decode path works and its antenna receives 433 MHz**, but the *real* ambient
weather/moisture sensors are not arriving there strongly enough to decode. (An earlier revision of
this note wrongly blamed a "GPS-tuned antenna that can't pass 433" — that was disproven below and
is retracted.)

- **The Pluto DOES receive 433 MHz — proven.** Running `rtl_433` live on the Pluto
  (`rtl_433 -d driver=plutosdr -H 8 -f 433.92M -f 434.0M -f 434.1M -s 2048000`) decoded **21
  valid-CRC Fine Offset frames** from `sx`'s `SxFskTx` transmitter (id `0f5c54`, moisture 40,
  battery 1600 mV — matching the transmitted fixture), at `freq1` 433.98–434.10 MHz. So the
  antenna, tuning, and decode path are all good, and the firmware's TX is cross-validated by the
  Pluto's independent decode.
- **Three self-caused bugs found and fixed** (the reason it looked like a hardware/antenna problem):
  (1) I ran `rtl_433 -r` on my own `iio_readdev` `.cs16` captures, which have a format/scaling bug
  and never decode even a known frame — the fix is `rtl_433` **live** driving the Pluto; (2) I tuned
  to 433.92 MHz, but Fine Offset crystals sit ~+100 kHz off (decodes land at 434.0–434.1) so the
  receiver must scan/hop; (3) I passed `-g 73`, but the gain range is `[-3 1 71]` — out of range.
- **Sensitivity verified maxed:** `hardwaregain = 71 dB, manual` confirmed live during a run;
  full-band coverage (2 MHz spans 433–435); rtl_433's minimum-SNR gate lowered (`-Y minmax
  -Y minsnr=3`); fresh Pluto reboot. Under all of these, the **real ambient WS69/WH51 give 0
  pulses**, while `sx`'s strong co-located TX decodes — and a prior session's rtl_433-on-Pluto
  config (`pluto_capture.sh`, 433.92 MHz / 60 dB) also decoded 0 real sensors. So the real sensors
  arrive at the Pluto weaker than `sx`'s transmitter, consistently, even though blue (sitting at the
  sensors) decodes them.
- **The RX front-end has no unset "receive amplifier" lever — enumerated in full (2026-09-09).**
  A complete read-only dump of the AD9361 attributes (`iio_attr -u ip:192.168.2.1 -c ad9361-phy
  voltage0` and `-D ad9361-phy`) shows the receive amplifier *is* the internal gain block, and it
  is at its ceiling:
  - `hardwaregain_available` = `[-3 1 71]` — max 71 dB, which the captures use.
  - `rf_port_select` = `A_BALANCED` (the Pluto's antenna port); the other options are single-ended
    / TX-monitor ports, not the antenna.
  - all external-LNA controls are structurally zero/disabled — `adi,elna-gain-mdB` = 0,
    `adi,elna-bypass-loss-mdB` = 0, `adi,elna-rx1-gpo0-control-enable` = 0 — i.e. **this stock
    Pluto has no external LNA to switch in.** (On a board that has one, `elna-gain-mdB` carries its
    dB value.)
  - `rf_bandwidth` is adjustable down to 200 kHz and `sampling_frequency` down to ~520 kSa/s, both
    already well inside the captured settings.
  There is therefore no additional amplifier, port, or sensitivity setting left to enable: with an
  external reference decoder (`rtl_433`) confirming the chain works on `sx`'s strong signal but
  seeing **zero signal transients** from the ambient sensors, the limit is signal *arrival* at the
  Pluto's antenna, not any driving/config value.

**To complete this cross-check:** every software/driving lever is now exhausted and proven
(gain at the 71 dB ceiling, correct antenna port, no external LNA, reference decoder confirms the
chain), so the one remaining variable is physical: the Pluto (or an antenna on it) has to sit close
enough to the weather station / moisture sensors for their frames to arrive above its noise floor —
the same proximity that lets `blue` and the co-located `sx` decode them. Once that placement holds,
`python3 pluto_real.py` (rtl_433 live at 434.0 MHz, 71 dB — frees GPS, decodes, restores GPS) closes
it in one run with no further tuning. Independently of the Pluto, the firmware's real-sensor decodes
are already cross-validated three ways: blue (CC1101) ↔ sx (SX1278) byte-identical on-air, the
rpi5-SPI CC1101 `~/wh51-watch` (a different chip + decoder), and Home Assistant ingestion; and the
Pluto independently decoded the firmware's own Fine Offset frames (the 21 `sx` frames above), so the
firmware↔Pluto protocol cross-check itself is done.

---

## On-hardware bench validation (2026-09-05)

Validates the CC1101 Tasmota firmware overlay (`firmware/src/xdrv_95_cc1101.ino`, built from
`firmware/build.py` against pinned Tasmota v15.5.0) on two
real CC1101 boards wired to two ESP32-C3 SuperMinis on `rpi5-433mhz`, driven entirely over the
native USB-CDC console (no WiFi/MQTT broker involved for this session — commands sent directly,
JSON replies read back). This is the first time the Tasmota driver has run **with a CC1101
actually attached** (the 2026-08-24 bare-board test in `esp32c3-cc1101-node.md` (in this docs/ dir) had no radio
wired and only exercised the graceful-absence path).

Boards under test (both had previously run a throwaway `radio_pin_probe` firmware that
independently confirmed SPI+CS silicon detection and GDO pin mapping — see its boot log captured
below — before being overwritten with the real Tasmota image for this test):
- **blue** E07-M1101D CC1101 -> `/dev/radio-cc1101-blue`. Pin map SCK=3 MOSI=4 MISO=7 CSN=9
  GDO0=10 GDO2=6.
- **dsun** (green) D-SUN CC1101 -> `/dev/radio-cc1101-dsun`. Pin map SCK=9 MOSI=10 MISO=3 CSN=6
  GDO0=7 GDO2=4.

Build: `python3 build.py` on the pinned Tasmota v15.5.0 (SHA `4561b51993c873e712db83814cb4b669dd3dbd73`)
overlay tree — **compiled clean**, produced `dist/tasmota32c3-cc1101.factory.bin` (3,063,024 bytes).
Flashed to rpi5 as `~/tasmota-hwtest.factory.bin` (a deliberately non-default filename, since a
concurrent session was building/flashing the same artefact name at the same time) with:

```
esptool --chip esp32c3 --port /dev/radio-cc1101-<blue|dsun> --before default_reset --after hard_reset \
    write_flash 0x0 ~/tasmota-hwtest.factory.bin
```

Both flashes completed in ~7s, hash-verified, no errors.

## Bench tooling note (not a firmware bug)

The ESP32-C3 SuperMini uses **native USB-CDC**, not a separate USB-serial chip. The console is
already known (per `read_probe.py`'s docstring) to reset the C3 unless the serial port is opened
with `dtr=False, rts=False` held throughout. This session found that detail is necessary but not
sufficient: **repeatedly opening and closing** a `dtr=False/rts=False` connection (e.g. one
`ssh ... python3 cc_console.py ...` invocation per command) still causes an intermittent reset —
visible as Tasmota's `QPC: Reset` log line and RAM counters (`Rx`/`Tx`/`Reinit`/etc. in
`CcStatus`) dropping back to 0 with no corresponding `Version`/boot-banner text (i.e. a warm
reset, not a fresh flash). Config (`/cc1101.cfg`, `Mode`, pin template) survives because it's on
LittleFS, but in-RAM stats don't. Once a **single persistent connection** was used to send a whole
batch of commands (helper `cc_batch.py`/`cc_watch.py`, written for this session), the resets
stopped and register writes read back correctly. This is a bench-harness gotcha, not a driver bug —
recorded here so a future bench session doesn't waste time chasing "the radio keeps losing its
config" (it doesn't; only RAM counters reset, and only when the console is repeatedly
reopened/reclosed).

## Stage 1 — Blue node (E07-M1101D): flash, commission, `CcStatus`, `CcReg`

**Boot banner** (`read_probe.py`, immediately after flashing, before commissioning):
```
00:00:01.197 Project cc1101-node - CC1101 node Version 15.5.0(cc1101-node)-3.3.8(2026-09-05T16:02:40)
```
**PASS** — Tasmota boots, `Version 15.5.0(cc1101-node)` confirms `XDRV_95`'s Project-name override
is compiled in (see `overlay/user_config_override.h`), native USB-CDC console responsive.

**Commissioning** — raw `Template` + `Module 0` (console):
```
Template {"NAME":"CC1101blue","GPIO":[0,0,0,736,704,0,4576,672,0,768,4544,0,0,0,0,0,0,0,0,0,0,0],"FLAG":0,"BASE":1}
Module 0
```
Reply: `{"NAME":"CC1101blue",...}` then, after the `Module 0` restart:
```
00:00:00.023 SPI: Bus1 using GPIO03(CLK), GPIO04(MOSI) and GPIO07(MISO)
00:00:00.132 CC1: CC1101 PARTNUM 0x00 VERSION 0x14, CS=9 GDO0=10 GDO2=6
00:00:00.136 CC1: mode remotes preset ook-433
```
**PASS** — SPI Bus1 initialises on exactly the mapped pins (GPIO3/4/7); `CS=9 GDO0=10 GDO2=6`
matches the blue pin map; driver activates automatically (`FUNC_INIT`) with no further commands.

**`CcStatus`**:
```
{"CcStatus":{"Present":1,"PARTNUM":"0x00","VERSION":"0x14","MARCSTATE":"0x0D","Mode":"remotes",
"Preset":"ook-433","RSSI":-87,"Rx":1,"Decoded":0,"Tx":0,"Reinit":0,"Overflow":0,"Repeats":0,
"Raw":0,"SecplusId":0,"Rolling":0}}
```
**PASS** — `Present:1`, `PARTNUM:0x00`, `VERSION:0x14` over real SPI (matches the design spec's
expected CC1101 identity and the earlier bare-SPI `radio_pin_probe` result on the same board).

**`CcReg`** (persistent connection, `cc_batch.py`):
| Command | Result |
|---|---|
| `CcReg 0x31` (VERSION status reg, no value → read-only) | `{"Addr":"0x31","Value":"0x14"}` — matches `CcStatus` |
| `CcReg 0x09` (ADDR config reg, before) | `{"Addr":"0x09","Value":"0x00"}` |
| `CcReg 0x09 0xA5` (write) | `{"Addr":"0x09","Value":"0xA5"}` (write-then-read-back in one command) |
| `CcReg 0x09` (separate command, same connection) | `{"Addr":"0x09","Value":"0xA5"}` — **persisted across commands** |
| `CcReg 0x09 0x00` (restore) | `{"Addr":"0x09","Value":"0x00"}` |

**PASS** — status-register read and config-register write+read-back both correct; the register
value survives independently of the write command (i.e. it's a real chip register, not just an
echo). (First attempt, using one-shot connections per command, showed a scratch write "reverting"
to 0x00 on the next read — that was the reset-on-reopen tooling artefact above, not a register
bug; the persistent-connection retest is the one recorded here.)

## Stage 2 — Blue node: `CcMode` / `CcPreset`, OOK RX path, edge-capture liveness

| Command | Result |
|---|---|
| `CcMode` | `"remotes"` (default) |
| `CcMode weather` | `"weather"`; log: `CC1: mode weather preset fineoffset-fsk`; `CcStatus` → `MARCSTATE:"0x0D"`, `Preset:"fineoffset-fsk"` |
| `CcMode remotes` | `"remotes"`; log: `CC1: mode remotes preset ook-433` |
| `CcPreset fineoffset-fsk` | `"fineoffset-fsk"` (debug override, `CcCfg.mode` unchanged) |
| `CcPreset ook-433` | `"ook-433"` |
| `CcPreset bogus` | `"fineoffset-fsk\|ook-433\|ook-tx-100k\|ook-tx-4k"` (correct usage-string fallback) |

**PASS** — `CcMode` and `CcPreset` both work; in every case `CcStatus`'s `MARCSTATE` reads `0x0D`
(`MARC_RX`), i.e. the CC1101 is confirmed actually in the RX state for both the OOK and FSK
presets, not just nominally "not erroring".

**Edge-capture / ISR liveness** (no remote pressed, ambient RF only), `cc_watch.py` polling
`CcStatus` every ~4 s for 20 s in `remotes` mode:
```
t=0s   Rx:0
t=4s   Rx:1
t=8s   Rx:2
t=12s  Rx:2
t=16s  Rx:2
```
and, in a separate longer run interleaved with the `CcMode`/`CcPreset` tests above, `Rx` climbed
1→2→3→4 over ~20 s of mixed commands. `Decoded` stayed `0` throughout (no full valid OOK-PWM
frame — expected with no remote pressed). **PASS** for the stated criterion ("edge count
increments even with no live remote pressed") — `Rx` (a closed, ≥2×`OOKPWM_MIN_BITS`-pulse frame
having reached `CcProcessFrame()`) is driven purely by the GDO2 ISR → `edges_to_pulses()` →
frame-gap-close pipeline, so its non-zero, monotonically-increasing count is direct proof that
pipeline is live end to end on real hardware, picking up ambient 433 MHz noise as short/garbage
frames. (There is no raw per-edge counter exposed by `CcStatus` — only this closed-frame count —
see "Notes / follow-ups" below.)

## Stage 3 — Green node (D-SUN): flash, commission, `CcStatus`, `CcReg` — different pin map

Same `tasmota-hwtest.factory.bin`, same commissioning sequence, **different** template:
```
Template {"NAME":"CC1101dsun","GPIO":[0,0,0,672,4576,0,768,4544,0,736,704,0,0,0,0,0,0,0,0,0,0,0],"FLAG":0,"BASE":1}
Module 0
```
Boot log after `Module 0`:
```
00:00:00.024 SPI: Bus1 using GPIO09(CLK), GPIO10(MOSI) and GPIO03(MISO)
00:00:01.268 CC1: CC1101 PARTNUM 0x00 VERSION 0x14, CS=6 GDO0=7 GDO2=4
00:00:01.272 CC1: mode remotes preset ook-433
```
**PASS** — SPI/GDO pins match the dsun pin map exactly (SCK=9 MOSI=10 MISO=3 CSN=6 GDO0=7 GDO2=4),
distinct from blue's, using the **same** compiled driver — confirms the driver's pin assignment is
fully template-driven, not hardcoded.

`CcStatus`: `{"Present":1,"PARTNUM":"0x00","VERSION":"0x14","MARCSTATE":"0x0D",...}` — **PASS**,
identical identity/RX-state result to blue.

`CcReg` (persistent connection): `CcReg 0x31` → `0x14` (VERSION, matches); `CcReg 0x09` write
`0x5A` → read back `0x5A` on a later command, then restored to `0x00`. **PASS**.

`CcMode weather` / `CcMode remotes` round-trip: both transition correctly, `MARCSTATE` stays
`0x0D` in each. **PASS**.

Edge-capture liveness (`cc_watch.py`, `CcStatus` every ~4 s for 20 s, no remote pressed):
```
t=0s   Rx:0
t=4s   Rx:1
t=8s   Rx:2
t=12s  Rx:4
t=16s  Rx:5
```
**PASS** — same live, monotonically-increasing `Rx` behaviour as blue, on the second board/pin map.

Both nodes were left in their default `remotes` mode, `Present:1`, at the end of the session.

## Summary

| # | Deliverable | Verdict |
|---|---|---|
| 1 | Build + flash blue; boot; `Version`/`XDRV_95`/SPI bring-up | **PASS** |
| 2 | `CcStatus` (Present/PARTNUM/VERSION); `CcReg` read+write/read-back; `CcMode`/`CcPreset` | **PASS** |
| 3 | OOK RX path: preset selects RX, MARCSTATE 0x0D, GDO2 edge-capture/ISR live (no remote) | **PASS** (via `Rx` closed-frame counter; see follow-up below re: a raw edge counter) |
| 4 | Repeat commission + `CcStatus` on green D-SUN, different template | **PASS** |
| 5 | This document; small bugs fixed inline; larger gaps flagged below | done |

**No firmware bugs found.** Everything specified in the driver's command reference
(`firmware/README.md`) behaved exactly as documented, on two different real CC1101 boards with two
different pin maps, using one compiled binary. The only surprise (repeated-serial-reopen causing a
warm reset) is bench-tooling behaviour, not the driver, and is now documented above for future
sessions.

## Notes / follow-ups (not blocking, not done this session)

- **No raw GDO2 edge counter in `CcStatus`.** The deliverable asked to confirm "edge count
  increments"; the closest existing field is `Rx` (frames that closed with ≥2×`OOKPWM_MIN_BITS`
  pulses), which does increment live and is the evidence used above. A draft patch adding a true
  per-ISR-call `Edges` counter to `CcStatus` was written and tested-compiled during this session,
  then **reverted** before commit because (a) `Rx` already gave unambiguous proof of ISR liveness
  and (b) the tested `.factory.bin` for this report was built *before* that patch, so keeping it in
  the tree would leave committed source ahead of what was actually flashed/verified. Worth
  revisiting as a small enhancement in a future firmware change, with its own build+flash+test
  cycle.
- **Still pending** (unchanged from `esp32c3-cc1101-node.md`'s bench runbook, out of scope for this
  session): a real remote/Merlin/WS85 capture (needs a human to press hardware remotes and/or a
  WS85 sensor in range), the R7 (RCSwitch 25-vs-24-bit) and R8 (WS85 frame length) rulings, a
  register-dump comparison against `cc1101-fulldump.py`, an actual FSK TX carrier test seen on a
  second receiver, and the 48 h soak/OTA stage. This session's scope was the driver/command layer
  and real CC1101 register I/O/RX-state on hardware, which is now confirmed on two boards.

## Raw pin-probe boot log (blue, before reflashing — for reference)

```
Project name:     radio_pin_probe
[CC1101 try blue E07-M1101D  SCK=3 MOSI=4 MISO=7 CS=9] PARTNUM=0x00 VERSION=0x14
  => CC1101 DETECTED on 'blue E07-M1101D' map (SPI+CS verified on real silicon)
  GDO0 -> GPIO10 (doc expects 10) [MATCH]
  GDO2 -> GPIO6  (doc expects  6) [MATCH]
  RESULT: blue E07-M1101D CC1101 map FULLY VERIFIED
```

## See also

- [`firmware/README.md`](firmware/README.md) — command reference, build/flash instructions.
- [`esp32c3-cc1101-node.md`](esp32c3-cc1101-node.md) — wiring, commissioning runbook, bench
  bring-up plan (stages 2–4/6 still pending real remotes/WS85/soak).


---

# On-hardware decode validation & RX-bandwidth fix (2026-09-06)

This session ran on the **rewired** boards (the position-4 SPI signal moved off the GPIO9 BOOT
strap to GPIO1 — see `bootloader-recovery.md`). Pin maps in effect:
- **blue** `3E:B8` CC1101: SCK=3 MISO=7 MOSI=4 CS=1 GDO0=10 GDO2=6
- **green** `4F:D8` CC1101: SCK=1 MISO=3 MOSI=10 CS=6 GDO0=7 GDO2=4

Reference receivers on `rpi5-433mhz`, all decoding the same live sensors concurrently:
- SPI CC1101 (`~/cc1101-rx`, `~/wh51-watch/cc1101_watch.py`) — 26 MHz, 101 kHz BW, WH51/WS69 at ~-72 dBm.
- LilyGo SX1276 (`lilygo_watch.py`) — WH51/WS69 at ~-58..-75 dBm.

## Bug: CC1101 `Rx>0, Decoded=0`

The blue CC1101 node counted RX frames (`Rx` climbing ~0.25/s) but decoded none (`Decoded=0`),
while the SX1278 node and both reference receivers decoded the same frames cleanly. A raw-mode
capture (`CcRaw 1`) showed every drained packet was high-entropy noise with no family byte
(0x24/0x51/0x85) at the head.

## Root cause: RX bandwidth too narrow for the crystal offset

Verified by direct register readback (`CcReg`) that **every** CC1101 register on blue — frequency,
data rate, deviation, sync word, AGC, front-end, TEST — was identical to the bench-proven
reference; SPI, the `SCAL` calibration in `enter_rx()`, and the eFuses were all correct. A fine
frequency sweep at the narrow 101 kHz bandwidth decoded **only** at a +40 kHz center offset (zero
at nominal and every other point): blue's crystal is ~92 ppm high. The CC1101 frequency-offset
compensation only pulls in ±BW/4, so at 101 kHz (±25 kHz) the +40 kHz frame fell outside the
passband and the receiver could only false-sync on noise. This is not an antenna/hardware fault
(the antenna hears -70 dBm cleanly once tuned) — it is the preset choosing too narrow a filter for
real-world crystal spread.

## Fix: `MDMCFG4` `0xC9` -> `0x59` (101 kHz -> 325 kHz)

Bandwidth sweep on blue (45 s each): 101 kHz = 0 decodes, 203 kHz = 2, 406 kHz = 4, 812 kHz = 1.
325 kHz (FOC ±81 kHz) covers blue's +40 kHz with margin and worst-case cheap-module crystal spread
(~±90 ppm) across boards, at a ~5 dB noise-floor cost negligible for the local -70 dBm sensors.
Validated on blue at 325 kHz (90 s): **Decoded=10, Rx=14**, byte-exact with the references:

| model | id | reading | node RSSI |
|-------|----|---------|-----------|
| Fineoffset-WS69 | 174 | 12.3 °C, 86% RH | -68..-71 dBm |
| Fineoffset-WH51 | 0f4b37 | moisture 24%, ad_raw 150 | -76 dBm |
| Fineoffset-WH51 | 0f5d66 | moisture 38%, ad_raw 194 | -79 dBm |
| Fineoffset-WH51 | 0f5d7f | moisture 38%, ad_raw 198 | -75 dBm |

Committed in `cc1101_presets.c`; `test_presets.py` passes 325 kHz into the reference math so the
preset still matches `cc1101.py` register-for-register outside PKTCTRL0. The full host suite passes (146 tests; the ~36 preset/decoder/weather tests are the directly affected subset).

Known refinement (raised by adversarial review): FSCTRL1 (IF ≈ 152 kHz) was left unchanged, so with the wider 325 kHz filter the IF now sits just below BW/2. It decodes cleanly on hardware (10/10 above), but TI SmartRF guidance raises FREQ_IF when the channel filter is widened this far — a future pass could bump it for extra low-frequency margin.

## SX1278 status

Contrary to earlier "foundation only" notes, the SX1278 node **decodes Fine Offset FSK on
hardware**: WS69 and WH51 received and decoded byte-exact against the LilyGo and CC1101 reference
loggers (moisture / ad_raw / battery all matching). The SX1278 uses fixed-length FSK RX and did not
exhibit the CC1101 bandwidth issue (its crystal offset is within its passband).

## Remaining (updated 2026-09-08 — see next section)
- **blue**: DONE — baked-in 325 kHz image validated from a cold boot (Decoded=11).
- **Home Assistant MQTT publish/subscribe round-trip**: DONE — isolated broker, both directions.
- **green** (`4F:D8`): characterised as a board-level power-on boot-strap trait (byte-identical
  firmware to blue; blue boots and green does not on the same VDD cycle; eFuses default). Not a
  firmware defect — details in the next section.
- **Pluto SDR**: reception confirmed by correlation; byte-level software demod still open (not
  required for firmware correctness).

# MQTT round-trip, cross-receiver check, and green boot characterisation (2026-09-08)

Follows the 2026-09-06 RX-bandwidth fix. Blue was reflashed with the baked-in 325 kHz
image and validated from a cold boot; the isolated Home Assistant MQTT round-trip, an
inter-receiver cross-check, and a definitive characterisation of the green board's boot
behaviour were completed. All work is on real hardware on `rpi5-433mhz`.

## Blue: baked-in fix confirmed from cold boot

After `sudo reboot` of `rpi5-433mhz`, blue (`E8:3D:C1:8C:3E:B8`) came up `boot:0xd
(SPI_FAST_FLASH_BOOT)` on the baked-in image and decoded live over 120 s: `Decoded=11`
(WS69 `id174` 9.6 °C / 95 %RH; WH51 `0f5d66`/`0f5d7f` 38 %; RSSI -63..-77). The runtime
override is now a shipped default, not a manual poke.

## Isolated Home Assistant MQTT round-trip (criterion e) — SUPERSEDED

> **Superseded** by the real ha.welland verification at the top of this file (2026-09-09).
> The section below is the earlier isolated-broker stand-in, kept for the record; where it
> says "not the literal ha.welland", that gap is now closed on the real broker.

To exercise MQTT without touching the production broker, `rpi5-433mhz`'s `wlan0` was turned
into a NAT hotspot (`cc1101-test`, 2.4 GHz, `ipv4.method=shared`, gateway `10.42.0.1`) and a
local `mosquitto 2.0.21` broker was run on it (same broker software as the HA add-on). Blue
joined at `10.42.0.99` and was pointed at `10.42.0.1:1883`. Captured with
`mosquitto_sub -v -t '#'`.

**Publish** (device -> broker):
- `rtl_433/nodes/cc1101-node-8C3EB8-7864/events` — decoded sensor JSON (WS69 & WH51), the
  rtl_433-shaped envelope the HA path consumes.
- `tele/cc1101-node_8C3EB8/SENSOR` (with the `CC1101` status block), `STATE`, retained
  `LWT = Online`, `INFO1..3`.
- `tasmota/discovery/E83DC18C3EB8/config` — this is Tasmota's **native device** discovery
  (it surfaces the Tasmota node itself), **not** the weather/moisture sensor entities. The
  sensor entities are created by the rtl_433 add-on, proven separately below. (An earlier
  draft of this section wrongly implied `SetOption19`/`tasmota/discovery` was the HA sensor
  integration and that `SetOption19 1` was set; the capture in fact showed `SetOption19 0`.
  The two discovery systems are unrelated; corrected here.)

**End-to-end HA sensor autodiscovery (topology A).** The full path was then run in isolation
with the project aggregator and the real rtl_433 add-on script: blue (`CcHass 0`) ->
`rtl_433/nodes/<host>/events` -> `rf433_aggregate.py` (site `test`) -> `rtl_433/test/events`
-> `rtl_433_mqtt_hass.py` (subscribed `rtl_433/+/events`) -> **22 `homeassistant/sensor/.../config`
entity configs** were created — WS69 `id174` (temperature, humidity, wind dir/speed/gust, rain,
UV, UV-index, lux, battery, rssi) and WH51 `0f5d7f` (moisture, battery, mV, rssi). These are
exactly the HA entities the estate's `rtl433-mqtt-autodiscovery` add-on would create in
production.

**Receive** (broker -> device):
- read-only query: `cmnd/cc1101-node_8C3EB8/CcStatus` -> `stat/cc1101-node_8C3EB8/RESULT`
  with the full `CcStatus` JSON (live counters matching concurrent telemetry, so the handler
  genuinely ran); `cmnd/.../Status` -> `stat/.../STATUS`.
- **state-changing** command: `cmnd/cc1101-node_8C3EB8/CcHass 1` ->
  `stat/.../RESULT {"CcHass":1,"EventsTopic":"rtl_433/cc1101-node-8C3EB8-7864/events"}`; events
  then flowed on the direct 3-level topic (topology B), which `rtl_433/+/events` sees directly.

This proves the firmware publishes the exact message shapes HA consumes, drives real HA entity
creation through the standard add-on, and acts on both query and mutating commands delivered
over MQTT.

**Scope / what is NOT yet proven:** this used a **local** mosquitto broker on an isolated
hotspot, not the literal `ha.welland.mithis.com` instance, and no Home Assistant server was in
the loop (the add-on script stands in for it). The real broker was confirmed reachable
(TCP `1883` open) from the boards' NAT path. Connecting a node to the real broker — device on
`ansells-iot`, per-device `tas-<node_id>` credential via `gdoc2netcfg tasmota configure` +
`register-broker` — is the production rollout step (documented in `mqtt-home-assistant.md`),
deliberately not performed here to avoid unilateral changes to the production sheet/broker.

## Inter-receiver cross-check (criterion b)

Blue (CC1101) and the SX1278 (RA-02) node were captured simultaneously over ~90 s. Four WS69
`id174` frames were **byte-for-byte identical across every decoded field on both radios**
(e.g. `wind_dir_deg 97, wind_avg 1.1, wind_max 1.5, uv 2619, light_lux 87635.0, hum 47,
temp 18.9`), differing only in RSSI (blue ~-68..-70 dBm, SX ~-88..-90 dBm) — two different RF
front-ends agreeing. The SX1278 additionally decoded four distinct WH51 moisture probes
(`0f5c54` 36 %, `0f5d66` 37 %, `0f5d7f` 35 %, `0f4b37` 24 %), demonstrating multi-sensor
reception.

**Honest limits of this cross-check** (raised by adversarial review):
- It is **self-referential for the decoder**: both nodes compile the *same* `decode_fineoffset.c`,
  so identical output validates the RF front-ends + SPI/driver, **not** the decoder's
  correctness (a decoder bug would produce identical wrong output on both). An independent
  oracle — rtl_433 on an RTL-SDR, a Pluto byte-decode, or the site's own rtl_433 pipeline —
  is not part of this evidence. (The decoder itself is separately checked in host tests against
  real captured frames with CRC, but that is not an on-air cross-receiver check.)
- The WH51 moisture readings were decoded by the **SX node only** in this window; blue logged
  no WH51 in the same span (it is capable — `fineoffset-fsk` mode, non-zero `Decoded`), so the
  moisture sensors are received but **not inter-receiver cross-checked** here.
- **Pluto** reception of the WH51 transmissions was confirmed by energy/SNR correlation
  (SNR 34-39 dB) but **not** by byte-level decode; a software demod from Pluto IQ remains an
  open DSP item. Criterion (b)'s "cross-check against the pluto SDR" is therefore only partially
  met (reception, not decode).

## Green board: boot characterisation (a power-on strap problem, not the application image)

Green (`E8:3D:C1:8C:4F:D8`, D-SUN CC1101) does **not** run its application after a clean VDD
power-on; it lands in ROM download (`boot:0x5`). The evidence points to the GPIO9/BOOT strap
being sampled low at the reset edge — a decision the ROM makes **before any firmware runs**, so
the application code cannot be the cause:

- **The load-bearing argument:** boot mode (flash-boot vs download) is chosen by the ROM from
  the GPIO9 strap at the reset edge, before the app is even read from flash. No application
  code can change that outcome.
- **Discriminating test:** on one true VDD power cycle (RP1 GPIO42 VBUS cut, 8 s), on the same
  USB hub, **blue's app runs and associates to the AP at t+0 s while green never associates in
  45 s.** Same firmware image, same power event, opposite result — isolating a *per-unit*
  difference, not a firmware difference.
- Green's flash is byte-identical to blue's working image (`esptool verify_flash 0x0 … ->
  verify OK (digest matched)`). Note this only rules out a *corrupt/divergent application
  image*; it does not itself bear on download-mode entry (which is decided before flash is
  read). It is listed as corroboration, not as the primary argument.
- Green's eFuses are all default (`DIS_FORCE_DOWNLOAD`, `DIS_DOWNLOAD_MODE`,
  `DIS_USB_SERIAL_JTAG_DOWNLOAD_MODE` all `False`) — nothing forces download.
- GPIO9 reads high in the ROM stub; a controlled DTR-held/RTS-pulsed app-boot reset still
  lands in download.

**Reconciling the earlier (2026-09-05) green PASS:** Stage 3 above shows green booting and
running the app repeatedly — but those were **USB-host-mediated resets** (`rst:0x15`, triggered
by opening the CDC port / esptool), where the DTR/RTS line state at the reset edge differs from
a true cold power-on (`rst:0x1`). Green's failure is specifically on the **cold power-on** path;
it can be coaxed into the app via host-driven resets, which is why the earlier stage passed.

**Open question / limit of this analysis:** what is firmly established is that the cause is
**upstream of firmware** — the ROM decides download vs flash-boot from the GPIO9 strap before
any application code runs, so no code change can alter it. The *specific* mechanism was **not
determined this session** and needs physical inspection I cannot do remotely: green's
position-4 wiring was not re-measured, so it is unknown whether green still routes its
position-4 radio signal to GPIO9 (in which case green needs the same GPIO9->GPIO1 rewire that
blue received — a wiring step the firmware pin-map change in commit `3dca9ff` assumes) or
whether a slow-rising BOOT line on that unit is responsible. Either way it is not an
application-firmware defect, but the outstanding action is to **verify/redo green's position-4
GPIO9->GPIO1 rewire and re-test a cold boot** (and, if still failing, scope GPIO9 during
power-up) — not to change firmware. The overlay guardrails deliberately forbid the eFuse burns
(disable-ROM-download) that could mask a strap problem, at the cost of USB recoverability. The
CC1101 functional path is fully proven on blue, which runs the identical image; green is a
second CC1101 board pending that rewire check.

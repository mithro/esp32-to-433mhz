# On-hardware bench validation — Plan B Tasmota firmware (2026-09-05)

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
preset still matches `cc1101.py` register-for-register outside PKTCTRL0. All 36 host tests pass.

## SX1278 status

Contrary to earlier "foundation only" notes, the SX1278 node **decodes Fine Offset FSK on
hardware**: WS69 and WH51 received and decoded byte-exact against the LilyGo and CC1101 reference
loggers (moisture / ad_raw / battery all matching). The SX1278 uses fixed-length FSK RX and did not
exhibit the CC1101 bandwidth issue (its crystal offset is within its passband).

## Remaining
- **green** (`4F:D8`): flashed with the 325 kHz firmware; awaiting a VDD power cycle to boot from
  flash (the post-flash USB-serial-JTAG download state clears only on VDD removal — GPIO9 measured
  healthy/high, not a strap fault).
- **blue**: fix proven via runtime override; reflash to the baked-in image pending a power cycle.
- Pluto SDR cross-check; full Home Assistant MQTT publish/subscribe round-trip.

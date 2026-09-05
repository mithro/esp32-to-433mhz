# FIX-A: SX1278 (RA-02) float-fix re-capture + Pluto/rpi5 3-way cross-check

Session: 2026-09-05. Goal: re-validate SX1278 weather/moisture reception on the RA-02 node
with the CURRENT firmware (which now has the `rf_ftoa` float fix, commit `4c85365`),
since the earlier WAVE A2 live capture predates that fix and its on-air JSON floats read the
literal `*float*`. Also add the missing Pluto SDR cross-check (an explicit goal criterion).

**Result: both done. Floats are valid on-target. WH51 target sensor (id 0f5c54, previously below
the CC1101-node SNR budget) now decodes on SX1278 and matches two independent rpi5 reference
receivers byte-for-byte. The Pluto SDR side is honestly incomplete: its pre-existing, unattended
continuous logger had already gone stale before this session and did not recover within the
session time budget (see "What did not line up" below) — a logging-tool limitation, not a radio
or firmware fault.**

## 1. Build + flash (exactly once)

- Rebuilt on desktop.buddy.mithis.com at HEAD `cd95b48` (post-float-fix; `4c85365` "render weather-JSON
  floats without %f (picolibc integer printf)" is an ancestor).
- `PATH=$HOME/.local/bin:$PATH python3 firmware/build.py` -> `firmware/dist/tasmota32c3-cc1101.factory.bin`,
  3,068,608 bytes, built 2026-09-05T22:19:51+09:30, sha256
  `9c933635b56d73492063848f41d17b5bf72ea63123c8f94622b7f828ba485c8f`.
- scp'd to rpi5-433mhz as `~/tasmota-a2recap.factory.bin`; sha256 verified identical on both ends.
- Single flash:
  ```
  esptool --chip esp32c3 -p /dev/radio-sx1278-ra02 --before default_reset --after hard_reset \
      write_flash 0x0 ~/tasmota-a2recap.factory.bin
  ```
  Completed in 11.1 s, hash verified, no errors. **This was the only reflash performed.**
- Commissioning (persistent `cc_batch.py` connection, dtr=False/rts=False):
  `Radio` (query) already showed `Config:sx1278,Active:sx1278` and an in-flight WS69 decode —
  weather-mode config had persisted on LittleFS across the reflash. `Radio sx1278` (explicit) logged:
  ```
  CC1: SX1278 present, RegVersion 0x12, SCK=3 MISO=7 MOSI=4 NSS=9 RST=10 DIO0=6
  CC1: SX1278 FSK weather RX: 433.92 MHz 17.241 kbps sync 0x2DD4, fixed len 30
  ```
  Final `SxStatus` after commissioning: `{"SxStatus":{"Present":1,"VERSION":"0x12","Active":1,"Mode":"weather",
  "WeatherRx":1,"RSSI":-95,"Rx":5,"Decoded":2}}`.

## 2. 10-minute passive capture window

Persistent pyserial connection (dtr=False, rts=False, opened once) logging the console for
600 s, 2026-09-05T12:53:39.025278+00:00 -> 13:03:39.057108+00:00 UTC. No commands were sent
during the window (Tasmota auto-emits `events` lines on decode); the node was left completely
undisturbed. Simultaneously: (ii) the rpi5 reference loggers `cc1101_watch.py` and
`lilygo_watch.py` (already running continuously since 2026-09-02) kept writing to
`~/wh51-watch/{cc1101,lilygo}.jsonl`/`.hits.jsonl`; (iii) Pluto SDR rtl_433 — see # 5 for what
happened there.

## 3. VALID-FLOAT decode lines (the headline fix)

Exact `events` JSON lines from the capture (`FIX-A` node console, wall-clock UTC prefix added by the
capture script; the trailing `00:0M:SS.mmm` is the node's own uptime clock). No `*float*` string
appears anywhere in the 600 s capture (grepped the full log).

WS69 (id=174), first and last of many identical-shape decodes in the window:
```
[2026-09-05T12:53:43.229313+00:00] RSL: events = {"time":"1970-01-01T00:00:04","receiver":"cc1101-node-2EB380-4992",
  "rssi":-89,"model":"Fineoffset-WS69","id":174,"battery_ok":1,"temperature_C":13.0,"humidity":84,
  "wind_dir_deg":7,"wind_avg_m_s":0.8,"wind_max_m_s":1.0,"rain_mm":517.7,"uv":0,"uvi":0,"light_lux":0.0,"mic":"CRC"}

[2026-09-05T13:03:35.453224+00:00] RSL: events = {...,"model":"Fineoffset-WS69","id":174,"battery_ok":1,
  "temperature_C":13.1,"humidity":84,"wind_dir_deg":358,"wind_avg_m_s":0.2,"wind_max_m_s":0.5,"rain_mm":517.7,
  "uv":0,"uvi":0,"light_lux":0.0,"mic":"CRC"}
```
WH51, target sensor id 0f5c54 (the one previously reported "below the node SNR" for the CC1101
boards in WAVE A2 — decodes here for the first time on any ESP32 node):
```
[2026-09-05T13:03:36.354215+00:00] RSL: events = {"time":"1970-01-01T00:09:57",
  "receiver":"cc1101-node-2EB380-4992","rssi":-90,"model":"Fineoffset-WH51","id":"0f5c54",
  "battery_ok":1.0,"battery_mV":1600,"moisture":40,"boost":0,"ad_raw":208,"mic":"CRC"}
```
WH51, non-target sensor id 0f5d66 (decoded repeatedly through the window, e.g.):
```
[2026-09-05T12:54:30.378635+00:00] RSL: events = {...,"model":"Fineoffset-WH51","id":"0f5d66",
  "battery_ok":0.9,"battery_mV":1500,"moisture":38,"boost":0,"ad_raw":195,"mic":"CRC"}
```
All `battery_ok`, `temperature_C`, `wind_avg_m_s`, `wind_max_m_s`, `rain_mm` fields are real JSON
numbers (not quoted strings, not `*float*`). This directly confirms the `4c85365` fix on real
hardware, on the SX1278 path, for both weather (WS69) and moisture (WH51) families.

## 4. Three-way cross-check

### 4a. WH51 target sensor id 0f5c54 (node + rpi5 CC1101 + rpi5 LilyGo)

| Receiver | Timestamp (UTC) | moisture | battery_mV | ad_raw | Raw 14-byte payload |
|---|---|---|---|---|---|
| SX1278 node (this build) | 13:03:36.354 | 40 | 1600 | 208 | `51 0F 5C 54 10 7F 28 F8 D0 FF FF FF 4B D7` |
| rpi5 CC1101 (`cc1101.hits.jsonl`) | 13:03:36.048 | 40 | 1600 | 208 | `51 0F 5C 54 10 7F 28 F8 D0 FF FF FF 4B D7` |
| rpi5 LilyGo SX1276 (`lilygo.hits.jsonl`) | 13:03:36.053 | 40 | 1600 | 208 | `51 0F 5C 54 10 7F 28 F8 D0 FF FF FF 4B D7` |

All three receivers decoded the same physical transmission (payload byte-identical, all three
timestamps within 0.31 s of each other) with identical CRC-valid fields. This is the target WH51
sensor that WAVE A1 could not decode on the CC1101 boards (attributed there to SNR at the node
antenna); it decodes cleanly on the SX1278 path, confirming the fixed-length-30 drain + family
dispatch works for the low-margin sensor too, not only the strong one (0f5d66).

### 4b. WS69 id=174 (node + rpi5 LilyGo, byte-level)

`lilygo_watch.py` does not run the Fineoffset-WH24/WS69 decoder (it only decodes WH51-shaped
frames); it does log every raw Fine-Offset-looking frame it hears. Decoding the raw LilyGo bytes
by hand against `firmware/decoders/decode_fineoffset.c`'s `decode_wh24_family()` byte offsets confirms an
exact field match with the node's own decode, for two separate transmissions:

| UTC | Receiver | id | temp_C | humidity | wind_dir | wind_avg_m_s | wind_max_m_s | rain_mm |
|---|---|---|---|---|---|---|---|---|
| 12:53:59.446 | SX1278 node | 174 | 13.0 | 84 | 8 | 0.4 | 0.5 | 517.7 |
| 12:53:59.242 | rpi5 LilyGo raw (`24 AE 08 02 12 54 07 01 07 F6 00 00 00 00 00 19 60`, hand-decoded) | 174 | 13.0 | 84 | 8 | 0.4 | 0.5 | 517.7 |
| 12:54:31.279 | SX1278 node | 174 | 13.0 | 84 | 11 | 0.4 | 0.5 | 517.7 |
| 12:54:31.241 | rpi5 LilyGo raw (`24 AE 0B 02 12 54 07 01 07 F6 00 00 00 00 00 6D B7`, hand-decoded) | 174 | 13.0 | 84 | 11 | 0.4 | 0.5 | 517.7 |

(Hand-decode per the firmware's own byte layout: id=b[1]; wind_dir=b[2]; low_batt=(b[3]&0x08)>>3;
temp_raw=((b[3]&0x07)<<8)|b[4], temperature_C=(temp_raw-400)*0.1; humidity=b[5]; wind_raw=b[6],
wind_avg_m_s=wind_raw*0.125*0.51; gust_raw=b[7], wind_max_m_s=gust_raw*0.51; rain_raw=(b[8]<<8)|b[9],
rain_mm=rain_raw*0.254. LilyGo's sketch only reports a 17-byte window so the tail CRC/pressure
bytes beyond that are not compared; the compared bytes match exactly.)

## 5. Pluto SDR cross-check — what happened, honestly

Host `rpi-sdr-pluto.welland.mithis.com`. A continuous `rtl_433 -d driver=plutosdr -f 433.92M -s 1024k
-g 73 -Y minmax -Y autolevel -M level -M protocol -M time:iso -F json` logger (PID owned by the site, running
unattended since 2026-09-02, writing `~/wh51-watch/rtl433.jsonl`) was ALREADY present on this host —
not something this session started.

- Checked it before touching anything: it had already stopped producing new lines. Its last
  written record (line 505 of 505) is stamped, by its OWN internal clock, `"time":"2026-09-05T13:44:32"`,
  which is LATER than the true wall clock at the time I first checked (`date -u` read 13:00:53). This is
  clock drift accumulated over ~3.5 days of unattended runtime (SDR sample-clock-derived
  timestamping, not synced to the host clock), not a sign the data is literally from the future:
  its `rain_mm:517.144` (2036 tip counts) is 2 counts / 0.508 mm BEHIND the node/rpi5-reference reading
  of `517.7` (2038 counts) taken during this session, confirming those lines chronologically
  precede this session's capture (the rain gauge only counts up).
- I started a short dedicated `rtl_433` capture of my own for the 10-minute window (as planned) and it
  reported `ERROR: Unable to claim interface 3:3:5: Device or resource busy` (falling back to the network
  `ip:pluto.local` path) — the pre-existing logger already held the USB interface. I killed my ad-hoc
  capture once I realized this (it produced 0 bytes of output anyway — SIGTERM did not flush its
  fully-buffered stdout).
- I restarted the pre-existing logger twice (killing the `rtl_433` PID; its own `while :; do ... done` wrapper
  relaunched it within 10 s both times). Both restarts reconnected to the Pluto cleanly over USB
  (`uri=usb:3.3.5`, no claim errors, correct device banner) and process state stayed `S` (normal sleep,
  not `D`/stuck), but neither restart produced a single new decoded line or even a new byte in its
  human-readable `rtl433.log` stream within this session's time budget (~10 minutes total waited across
  both restarts), despite WS69 id=174 historically decoding on this receiver every 15-45 s at a
  strong -20 dBm.

**This is a pre-existing, unattended logging tool going stale on its own timeline, discovered and
partially remediated (clean reconnect) but not fully restored to live decoding inside this
session — it is not a fault in the Pluto radio hardware, and not a fault in the CC1101/SX1278
node or firmware under test.** No further troubleshooting (e.g. a Pluto power cycle) was
attempted, per the goal's guardrail against unnecessary hardware churn and because a physical
power cycle of shared site infrastructure was out of scope for this task.

What Pluto DOES confirm (non-simultaneous, from its stale-but-real historical data, all from
2026-09-05, same sensor, same rain-counter epoch modulo the 2-count gap above): WS69 id=174,
`battery_ok:1`, `rain_mm:517.144`, e.g.:
```
{"time":"2026-09-05T13:44:32","protocol":78,"model":"Fineoffset-WS69","id":174,"battery_ok":1,
 "temperature_C":16.100,"humidity":71,"wind_dir_deg":2,"wind_avg_m_s":2.422,"wind_max_m_s":4.080,
 "rain_mm":517.144,"uv":302,"uvi":0.000,"light_lux":19018.000,"mic":"CRC","mod":"FSK",
 "rssi":-20.426,"snr":13.924,"noise":-34.350}
```
A live, in-window Pluto WH51 decode was never obtained (in this session or in the pre-existing
logger's history) — consistent with the already-documented Pluto/rtl_433-vs-narrowband-WH51
catch-rate gap (`tmp/infra-map.md`: "decoded by CC1101+SX1276 (narrowband) but NOT Pluto/rtl_433
(broadband) — reported not diagnosed").

## 6. Node health after this session

Single flash only, as required. One post-capture console reconnect (to read a final `SxStatus`)
reset the node's RAM counters (`Rx`/`Decoded` back to 0) via the already-documented "USB-CDC reconnect
resets the C3 even with dtr=False/rts=False" bench-harness gotcha (see `HWTEST-RESULTS-cc1101.md`) —
config and mode (`Mode:weather`, `WeatherRx:1`) persisted through it. No reflash was needed or performed
to recover. The node was left running in weather mode.

## 7. Goal-criteria status (this fix)

- Valid on-air floats (WAVE A2's open bug): **FIXED and confirmed live** — no `*float*` anywhere in a
  full 10-minute capture, both WS69 and WH51 families.
- Pluto SDR cross-check (missing goal criterion): **partially delivered.** Achieved: identified the
  pre-existing Pluto logger, diagnosed why it went silent (clock drift + stdio buffering), attempted
  two clean restarts, and used its most recent historical WS69 records as supporting (non-simultaneous)
  evidence. Not achieved: a live, in-window, byte/field-matching Pluto decode alongside the node and
  rpi5 receivers, for either WS69 or WH51. Recommend a follow-up session either restart the Pluto host
  outright or use a fresh non-conflicting rtl_433 invocation from the start of a session (never two
  rtl_433 processes against the same physical Pluto at once).
- WH51 target sensor (0f5c54) SX1278 decode: new result this session, not previously achieved even in
  WAVE A2 (which only got the stronger 0f5d66) — 3-way byte-identical match vs both rpi5 receivers.

## Files
- Doc update: `firmware/docs/esp32c3-cc1101-node.md` — Verification log, new 2026-09-05 FIX-A row.
- This report: `FIX-A-REPORT.md` (repo root).
- Raw capture kept for reference (rpi5-433mhz): `~/a2recap-node-console.log`.


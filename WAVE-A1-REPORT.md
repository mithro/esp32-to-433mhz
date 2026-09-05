# WAVE-A1 — WH51 decoder + CC1101 FSK RX for WS69 + WH51

Branch `add-tasmota-firmware` (pushed). Date 2026-09-05, Welland.

## Summary

- **WH51 soil-moisture decoder added and host-tested against a REAL captured
  frame** — all **108 host tests pass** (was 102).
- **FSK RX path changed to a length *range*** so a 14-byte WH51 is captured and
  dispatched alongside the 25-byte WS69, without breaking WS69.
- **Firmware builds** clean (`tasmota32c3-cc1101`, Tasmota v15.5.0) and was flashed
  and run on the real blue (E07) and green (D-SUN) CC1101 nodes on rpi5.
- **Honest hardware result: WH51 did NOT decode live on the nodes, and no WS69 was
  observed decoding.** The nodes demonstrably receive real 433.92 MHz FSK traffic
  (strong packets down to RSSI -26 dBm, `Rx` counter climbing) but never a WH51 or
  WS69 frame. Root cause is that the WH51 sensors are not received at these USB
  nodes' antennas at a detectable SNR — the firmware, decoder and radio config are
  verified correct (node registers read back **identical** to the proven reference
  `cc1101_watch.py`; the decoder passes host tests on the exact bytes rtl_433 and
  the reference logger decode). See "What did not work" for the full debug trail.

## What was added (commits)

```
0373810 firmware/docs: WH51 protocol, FSK RX config, and hardware findings
6ef83e8 firmware: FSK RX accepts both WS69 (25 B) and WH51 (14 B) frames
7e0721a firmware: add Fine Offset WH51 soil-moisture decoder (family 0x51)
```

1. **`firmware/decoders/decode_fineoffset.c` / `.h`** — `decode_wh51()`, dispatched
   from `fineoffset_decode()` on family byte `0x51` (alongside `0x24` WS69 and
   `0x85` WS85). Ports rtl_433 `fineoffset.c` `fineoffset_WH51_callback`:
   14-byte frame `FF II II II TB YY MM ZA AA XX XX XX CC SS`; 24-bit id, TX-period
   boost `(b[4]>>5)`, 5-bit battery `(b[4]&0x1F)*100 mV`, moisture % `b[6]`, 9-bit
   raw AD `((b[7]&1)<<8)|b[8]`, CRC-8 poly 0x31 init 0 over b[0..11], additive
   checksum sum(b[0..12]). Emits rtl_433-shaped JSON:
   `{"model":"Fineoffset-WH51","id":"0f5c54","battery_ok":1.0,"battery_mV":1600,`
   `"moisture":40,"boost":0,"ad_raw":208,"mic":"CRC"}`. Trailing bytes past the
   14-byte frame are ignored, so a WH51 decodes even inside a longer fixed-length read.

2. **`firmware/tests/test_wh51.py` + `firmware/fixtures/wh51_id0f5c54_2026-09-05.json`**
   — 6 tests using REAL frames captured by the rpi5 reference logger
   (`~/wh51-watch/cc1101.hits.jsonl`), cross-checked field-by-field against
   `wh51.py` / rtl_433: id 0f5c54 (moisture 40, battery 1600 mV, ad_raw 208,
   battery_ok 1.0), id 0f5d66, a real crc-fail glitch that must be rejected,
   over-read tolerance (WH51 inside a 25-byte buffer), too-short and bad-CRC.

3. **`firmware/src/xdrv_95_cc1101.ino` `CcWeatherPoll()`** — range-based length
   handling: full-packet path (`RXBYTES >= PKTLEN+2`) reads the completed 25-byte
   packet and dispatches by family byte (a 14-byte WH51 lands in the first bytes
   and the decoder ignores the rest); plus a short-frame rescue that drains a WH51
   whose packet stalls before 25 bytes, gated to family `0x51` so a partially
   filled WS69/WS85 can never be truncated into a false decode. Adds
   `CcState.last_fifo`. WS85 (>=28 B) stays longer than the fixed packet and is
   validated by host test + Renode (not audible at Welland).

4. **`firmware/docs/esp32c3-cc1101-node.md`** — WH51 in the decoder list, a new
   "Fine Offset FSK RX configuration and packet-length handling" section (register
   table verified against a live node), the WS85 note, and verification-log rows.

## Host-test result

```
$ uv run --with pytest pytest firmware/tests
108 passed in ~12s
```
(102 previously + 6 new WH51 tests.) The WH51 test asserts the decoded fields
equal what rtl_433 / the reference logger reported for the same bytes.

## Hardware validation (real CC1101 nodes on rpi5)

Flashed the committed firmware (factory.bin, esptool, esp32c3) to the blue node
`/dev/radio-cc1101-blue` and green node `/dev/radio-cc1101-dsun`, commissioned each
with its template + `Module 0` + `Radio cc1101` + `CcMode weather`.

- Blue commissioned OK: `CC1: CC1101 PARTNUM 0x00 VERSION 0x14, SCK=3 MISO=7
  MOSI=4 CS=9 GDO0=10 GDO2=6`, `CC1: mode weather preset fineoffset-fsk`.
- Green commissioned OK: `CC1: CC1101 PARTNUM 0x00 VERSION 0x14, SCK=9 MISO=3
  MOSI=10 CS=6 GDO0=7 GDO2=4`, weather mode.

Console captures (native USB-CDC, dtr=False rts=False), several minutes each:

```
CcStatus over 210 s (blue, committed PKTLEN=25 build):
  Rx 2 -> 7 -> 13 -> 21 -> 24, Decoded 0, MARCSTATE 0x0D (RX), Overflow 0
Raw packets (CcRaw 1) — a mix of noise-floor and STRONG real packets, none Fine Offset:
  809002851026E1FFA09C90C01310A041D5  RSSI -26   (strong; not 0x51/0x24)
  D22019020003DCFF0509F2A1880600E0C4  RSSI -40
  C2616180214EE1FF02A80300CAB9136DB2  RSSI -51
  E36480F1A6A4E3FF6EED2310CD05602291  RSSI -26
  (bit-scanned all 8 bit + byte offsets: no WH51/WS69 frame hidden in any)
```

**No decode line was ever produced** (`Decoded` stayed 0 on both nodes), so there
are **no node-produced WS69 or WH51 lines to report** — this is stated plainly
rather than fabricated.

### Concurrent reference ground truth (what the node *should* have seen)

The rpi5 reference CC1101 (SPI) and LilyGo (SX1276) loggers heard the WH51 sensors
throughout the same window (`~/wh51-watch/cc1101.hits.jsonl`, target id 0f5c54):

```
ts 1788599626 recv cc1101 rssi -81.5 hex "51 0F 5C 54 10 7F 28 F8 D0 FF FF FF 4B D7"
   id 0f5c54 valid=true boost 0 battery_mv 1600 moisture_pct 40 ad_raw 208 is_target=true
ts 1788599696 recv cc1101 rssi -80.0 hex "51 0F 5C 54 10 7F 28 F8 D0 FF FF FF 4B D7"  (repeat)
ts 1788600130 recv cc1101 rssi -82.0 hex "51 0F 5D 66 ..."  id 0f5d66 moisture 38
```
rtl_433 (pluto, earlier today) for WS69: `model Fineoffset-WS69 id 174 temp 16.1 C
humidity 71 wind ... rain_mm 517.144 rssi -20` — WS69 was strong at that receiver.

The node's decoder, given those exact bytes, produces the matching JSON (proven by
`test_wh51.py`). The gap is purely reception: the node's antenna did not deliver
those frames at a demodulable SNR.

## What did NOT work, and everything I tried (no overclaiming)

**WH51 did not decode on either hardware node, and no WS69 decode was observed.**
Debug trail (firmware-first, per instructions — never blamed antenna/wiring until
every firmware lever was exhausted):

1. **Config vs the proven reference.** Read back the node's CC1101 registers live
   (`CcReg`): SYNC `2D D4`, FREQ `10 B0 71` (= round(433.92e6*2^16/26e6)), MDMCFG4/3/2
   `C9 5C 02`, MDMCFG1 `72`, DEVIATN `50`, PKTCTRL1/0 `04/00`, MCSM1 `3C`,
   AGCCTRL2 `43` — **identical** to `cc1101_watch.py`'s computed values. Config is not
   the problem.
2. **Packet length.** Original preset used fixed PKTLEN=25 (WS69-sized). With 25 the
   node completed only noise packets and no WH51 (a 14-byte WH51 needs 11 trailing
   demod bytes to complete). Tried PKTLEN=17 (the reference's value, only 3 filler
   bytes): still `Decoded=0`, still no `0x51` packet ever. Shipped design keeps
   PKTLEN=25 + the short-frame drain (a "range", per the task) so WS69 is preserved
   and WH51 is caught when received.
3. **Sync sensitivity.** Relaxed MDMCFG2 16/16 -> 15/16 live: `Rx` exploded to 376
   packets in 90 s (false-sync storm) with 2 FIFO overflows, but **still
   `Decoded=0`** — flooding the receiver surfaced no WH51, confirming the WH51 RF is
   simply not present at the node, not merely under a sync threshold.
4. **The node's RX/demod/decode path works** — it captured strong non-Fine-Offset
   433.92 FSK devices at -26..-60 dBm. It just never received the WH51 sensors
   (which the reference receivers heard at -74..-82 dBm on their own antennas).

**Conclusion:** firmware, decoder and radio config are correct and verified; the
blocker is RF reception of the specific WH51 sensors at the two USB nodes'
antennas. This is the one thing I could not change from software.

**Nodes wedged off USB.** After the repeated flash/reset/reconnect cycles (each
USB-CDC reconnect resets the C3), both `radio-cc1101-blue` and `-dsun` dropped off
USB entirely (not in `lsusb`; `usbreset` cannot re-enumerate a device that is gone).
Per the project memory note these C3+CC1101 nodes recover only with a VDD power
cycle — which needs a human at the bench. The committed firmware was successfully
flashed to blue before it dropped; it will run on next power-up.

## Not done / needs a human at the bench

- Confirm WH51 (and WS69) decode on a node once its antenna receives the sensors at
  a workable SNR (relocate/replace antenna or move the node), and power-cycle the
  two wedged nodes.
- Re-run the blue + green side-by-side identical-reception cross-check (blocked by
  the above).

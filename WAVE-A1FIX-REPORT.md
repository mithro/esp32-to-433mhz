# WAVE-A1FIX — Fine Offset FSK RX: one config for all frame lengths

Branch `add-tasmota-firmware`. Fixes the CC1101 Fine Offset FSK receive path so a
single RX config receives **all** Fine Offset frame lengths: WH51 (14 B), WS69
(~25 B), WS85 (~28 B).

## Root cause (ours, not the hardware)

The `fineoffset-fsk` preset programmed the CC1101 in **fixed** packet-length mode
(`PKTCTRL0 = 0x00`, `PKTLEN = 0x19 = 25`). In fixed-length mode the radio only
completes a packet after exactly 25 bytes follow the sync word, so a 14-byte WH51
frame never completes and is never decoded; a short WS69 could stall too. The prior
firmware papered over this with a family-0x51-gated "short-frame rescue" hack. One
fixed length cannot receive three different frame lengths.

The antenna / radio was never at fault.

## The fix

Switch Fine Offset RX to CC1101 **infinite** packet-length mode and drain a fixed
byte count, then dispatch in software by the family byte (the decoder already does
this: `0x24`→WS69, `0x51`→WH51, `0x85`→WS85, ignoring trailing bytes per family).

Because the RX FIFO only starts filling after the `0x2DD4` sync match, a whole frame
always sits at the FIFO head with demodulated noise behind it. We drain a fixed
`CC_FSK_DRAIN_LEN = 30` bytes (≥ the longest WS85 frame, < the 64-byte FIFO), decode,
then flush + re-enter RX to re-arm sync detection. RX-FIFO overflow is handled: the
CC1101 keeps the first 64 bytes on overflow, so the head frame is still recovered,
then SFRX + re-enter RX.

All modem/RF parameters (dev 50 kHz / BW 101 kHz / 17.241 kbps / 2-FSK / sync
`0x2DD4` / `IOCFG2=0x29` / `IOCFG0=0x06` / `FIFOTHR=0x47` …) are unchanged and still
match the bench-proven `cc1101.py` reference; only the length strategy changed.

### Code change — length mode (firmware/src/cc1101_node/cc1101_presets.c)

Before:
```c
{0x00, 0x29}, {0x02, 0x06}, {0x03, 0x47}, {0x04, 0x2D}, {0x05, 0xD4}, {0x06, 0x19}, {0x07, 0x04}, {0x08, 0x00},
                                                                                      /* PKTCTRL0 = 0x00 fixed length */
```
After:
```c
{0x00, 0x29}, {0x02, 0x06}, {0x03, 0x47}, {0x04, 0x2D}, {0x05, 0xD4}, {0x06, 0x19}, {0x07, 0x04}, {0x08, 0x02},
                                                                                      /* PKTCTRL0 = 0x02 INFINITE length */
```
`PKTLEN` (0x06) is ignored in infinite mode; left at `0x19` to match the reference.

### Code change — FIFO drain + dispatch (new firmware/src/cc1101_node/cc1101_weather.cpp)

Shared verbatim by the firmware driver and the host harness so the host test
exercises the identical logic:

```c
int cc_weather_drain(CC1101Radio& radio, uint8_t* raw, size_t raw_cap,
                     size_t* out_n, int* out_rssi, char* json, size_t json_len) {
  bool overflow = false;
  uint8_t n = radio.rxbytes(&overflow);
  bool ovf = overflow || (radio.marcstate() == MARC_RXFIFO_OVERFLOW);

  if (n < CC_FSK_DRAIN_LEN && !ovf) return CC_WX_IDLE;       // frame still arriving

  size_t take = n < CC_FSK_DRAIN_LEN ? n : CC_FSK_DRAIN_LEN;
  if (take > raw_cap) take = raw_cap;
  if (take < CC_FSK_MIN_FRAME) { radio.flush_rx(); radio.enter_rx(); return CC_WX_OVERFLOW; }

  radio.read_fifo(raw, take);                                // head frame intact even after overflow
  int rssi = radio.rssi_dbm();
  radio.flush_rx(); radio.enter_rx();                        // SFRX + re-enter RX: re-arm sync
  *out_n = take; *out_rssi = rssi;
  int rc = fineoffset_decode(raw, take, json, json_len);
  return (rc > 0) ? CC_WX_DECODED : CC_WX_RAW;
}
```

### Code change — RX poll (firmware/src/xdrv_95_cc1101.ino)

`CcWeatherPoll()` was ~50 lines of fixed-length packet handling plus the family-0x51
rescue hack. It is now a thin caller of `cc_weather_drain()` that publishes the event
(or, in raw mode, the undecodable hex), and the stale `CcState.last_fifo` field was
removed.

## Host-test result

`uv run --with pytest pytest firmware/tests` → **114 passed** (108 prior + 6 new).

New file `firmware/tests/test_weather_rx.py` drives the real `cc_weather_drain()`
through the `radio_host` harness with a scripted RX FIFO (frame at the head + trailing
noise) and proves:

- WH51 (14 B) drained + dispatched → `Fineoffset-WH51` id `0f5c54`
- WS69 (25 B) drained + dispatched → `Fineoffset-WS69` id `174`
- WS85 (28 B) drained + dispatched → `Fineoffset-WS85` id `0x0028EB`
- all three decode via the one drain path (the core claim of the fix)
- a partial frame (< drain length, no overflow) returns IDLE (not drained)
- an overflowed FIFO still recovers the head frame

`test_presets.py` updated to assert the deliberate divergence: every register matches
`cc1101.py` **except** `PKTCTRL0` (firmware `0x02` infinite vs reference `0x00` fixed).

## Build result

`uv run firmware/build.py` → **SUCCESS** (exit 0), overlay on pinned Tasmota
`v15.5.0` (`4561b51`), env `tasmota32c3-cc1101`. `cc1101_weather.cpp` compiled and
linked. `RAM 25.1% (82344 / 327680)`, `Flash 72.9% (2148564 / 2949120)`. Artefacts in
`firmware/dist/`: `tasmota32c3-cc1101.bin`, `.factory.bin`, `.elf`, `.map`
(built 2026-09-05T20:12).

## Honesty / status

- The RX framing fix is **proven at host level only**. It is **unproven on radio**:
  the blue+green CC1101 nodes are currently OFF-USB (wedged, awaiting a human power-
  cycle), so no on-hardware flash/validation was possible. No hardware results are
  claimed here.
- Infinite-length mode means the RX FIFO fills continuously after a sync match, so an
  RX-FIFO overflow between 50 ms polls is the *normal* case and is handled (head frame
  recovered, then flushed). Watch that the overflow counter climbing is benign, not an
  error, during hardware revalidation.
- `RXBYTES` is read once (not the datasheet double-read); safe here because we drain a
  fixed count well below the actual fill, but noted for the on-radio check.

## HARDWARE-REVALIDATION checklist (run when blue+green return to USB)

Preconditions: blue + green CC1101 nodes power-cycled (VDD removed/restored — SRES is
not enough per the power-cycle-recovery note) and re-enumerated on USB.

1. Flash both nodes with the freshly built firmware:
   - artefact: `~/esp32-to-433mhz-fw/firmware/dist/tasmota32c3-cc1101.factory.bin`
   - `esptool.py --chip esp32c3 -p <port> write_flash 0x0 firmware/dist/tasmota32c3-cc1101.factory.bin`
     (or OTA the `tasmota32c3-cc1101.bin`). Confirm boot banner shows `CODE_IMAGE = cc1101-node`.
2. Commission each node (serial/console): set Wi-Fi + MQTT, confirm
   `CcStatus` shows `Present:1`, a valid `PARTNUM 0x00` and `VERSION 0x14`/`0x04`.
3. Put each node into weather RX: console `CcMode weather`; confirm
   `{"CcMode":"weather"}` and `CcStatus` shows `Preset:"fineoffset-fsk"` and
   `MARCSTATE 0x0D` (RX) — or `0x11` (overflow, benign).
4. Confirm the preset actually programmed infinite length on the radio:
   console `CcReg 0x08` → expect `"Value":"0x02"`.
5. Watch decoded events (MQTT topic `rtl_433/nodes/<host>/events`, or console):
   - Expect **WS69 id 174** lines: `{"model":"Fineoffset-WS69","id":174,...}`.
   - Expect **WH51 id 0f5c54** lines: `{"model":"Fineoffset-WH51","id":"0f5c54",...}`
     (and the second Welland sensor, id `0f5d66`, if in range).
   - WS85 is not audible at Welland — do not expect it live; host tests cover it.
6. Cross-check against the rpi5 reference logger over the same window:
   - `ssh rpi5-433mhz` (mind the stale-DNS note: it also resolves to a dead .237;
     retry if ssh hangs), then compare `~/wh51-watch/*.jsonl` /
     `~/wh51-watch/cc1101.hits.jsonl` timestamps + ids against the node's events.
     The same WH51 ids (`0f5c54`, `0f5d66`) and WS69 id 174 should appear on both.
7. Confirm `CcStatus` `Decoded` increments and `Rx` climbs; `Overflow` climbing is
   expected/benign as long as `Decoded` tracks real frames. If `Decoded` stays 0 while
   `Rx` climbs, capture a few `CcRaw 1` `CCRAW` hex packets and compare the family byte
   / frame bytes against the rpi5 reference before concluding.

Only after steps 5–6 show matching WS69 id 174 + WH51 id 0f5c54 decodes on the node,
cross-checked against rpi5, is the RX fix proven on radio.

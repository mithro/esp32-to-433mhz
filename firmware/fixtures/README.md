# Fixtures

Real RF captures used by the host-side decoder tests and by Plan B's firmware
tests. Two JSON formats:

## `rf433-packets-v1` — FSK packet-mode bytes (CC1101 FIFO)

```json
{"format": "rf433-packets-v1",
 "source": "rpi5-433mhz CC1101 spidev0.0, cc1101_ws69_rx.py --packet-len 25",
 "captured": "2026-08-20T20:57:00+09:30", "freq_hz": 433920000,
 "packets": [{"hex": "24AE...", "rssi_dbm": -85.5, "lqi": 127, "crc_ok": true, "note": "WS69 id 174"}]}
```

`crc_ok` is the CC1101's own appended status bit for its packet CRC (not the
Fineoffset CRC); Fineoffset frames have no CC1101 CRC so it is informational.

## `rf433-pulses-v1` — OOK pulse trains (async-serial mode, GDO2 edges)

```json
{"format": "rf433-pulses-v1",
 "source": "rpi5-433mhz CC1101 async GDO2 -> GPIO24 via gpiod",
 "captured": "2026-08-21T10:00:00+09:30", "freq_hz": 433920000,
 "device": "Grey Power Remote 5, On button, 3 presses",
 "trains": [{"t0_us": 0, "us": [730, 200, 200, 730, "..."]}]}
```

`us` alternates mark (carrier on), space (off), … starting with a mark, in
microseconds. A train ends at a space longer than the capture tool's
`--burst-gap-us` (default 15000). Every fixture can be exported to rtl_433's
`.ook` text format with `tools/cc1101_ook_capture.py --export-ook`.

"""Minimal CC1101 driver — just enough for FSK receive at user-specified params.

Datasheet reference: TI CC1101 SWRS061I.
Designed to run on the Raspberry Pi 5 over /dev/spidev0.0.
"""
from __future__ import annotations

import spidev
import time

# ── Command strobes (single-byte writes, no data follows) ────────────
SRES   = 0x30  # Reset chip
SFSTXON = 0x31 # Enable + calibrate frequency synth
SCAL   = 0x33  # Calibrate frequency synth and turn off
SRX    = 0x34  # Enable RX
STX    = 0x35  # Enable TX
SIDLE  = 0x36  # Exit RX/TX, turn off frequency synth
SFRX   = 0x3A  # Flush RX FIFO (only in IDLE / RXFIFO_OVERFLOW)
SFTX   = 0x3B  # Flush TX FIFO (only in IDLE / TXFIFO_UNDERFLOW)
SNOP   = 0x3D  # No-op (read status byte)

# ── Status registers (read with READ | BURST) ────────────────────────
PARTNUM    = 0x30
VERSION    = 0x31
RXBYTES    = 0x3B   # bit 7: RXFIFO_OVERFLOW; bits 6-0: byte count
MARCSTATE  = 0x35   # bits 4-0: state machine ID

# ── Config registers (subset used) ────────────────────────────────────
IOCFG2, IOCFG1, IOCFG0 = 0x00, 0x01, 0x02
FIFOTHR                 = 0x03
SYNC1, SYNC0            = 0x04, 0x05
PKTLEN, PKTCTRL1, PKTCTRL0 = 0x06, 0x07, 0x08
ADDR, CHANNR            = 0x09, 0x0A
FSCTRL1, FSCTRL0        = 0x0B, 0x0C
FREQ2, FREQ1, FREQ0     = 0x0D, 0x0E, 0x0F
MDMCFG4, MDMCFG3, MDMCFG2, MDMCFG1, MDMCFG0 = 0x10, 0x11, 0x12, 0x13, 0x14
DEVIATN                 = 0x15
MCSM2, MCSM1, MCSM0     = 0x16, 0x17, 0x18
FOCCFG, BSCFG           = 0x19, 0x1A
AGCCTRL2, AGCCTRL1, AGCCTRL0 = 0x1B, 0x1C, 0x1D
FREND1, FREND0          = 0x21, 0x22
FSCAL3, FSCAL2, FSCAL1, FSCAL0 = 0x23, 0x24, 0x25, 0x26
TEST2, TEST1, TEST0     = 0x2C, 0x2D, 0x2E
PATABLE                 = 0x3E    # power amplifier table (single-byte access)

# ── FIFO ──────────────────────────────────────────────────────────────
FIFO_ADDR = 0x3F          # FIFO_W = 0x3F; FIFO_R = 0xFF (READ|BURST|0x3F)

# ── SPI access flags ──────────────────────────────────────────────────
READ  = 0x80
BURST = 0x40

# ── MARCSTATE values (just the few we care about) ────────────────────
MARC_IDLE     = 0x01
MARC_RX       = 0x0D
MARC_RXFIFO_OVERFLOW = 0x11


class CC1101:
    def __init__(self, bus: int = 0, device: int = 0, spi_hz: int = 500_000):
        self.spi = spidev.SpiDev()
        self.spi.open(bus, device)
        self.spi.max_speed_hz = spi_hz
        self.spi.mode = 0
        self._last_status = 0

    # ── Low-level SPI ops ────────────────────────────────────────────
    def strobe(self, cmd: int) -> int:
        self._last_status = self.spi.xfer2([cmd])[0]
        return self._last_status

    def write_reg(self, addr: int, value: int) -> None:
        self.spi.xfer2([addr & 0x3F, value & 0xFF])

    def write_burst(self, addr: int, values: list[int]) -> None:
        self.spi.xfer2([(addr & 0x3F) | BURST] + list(values))

    def read_reg(self, addr: int) -> int:
        # Config registers (< 0x30) are read with READ bit only
        return self.spi.xfer2([(addr & 0x3F) | READ, 0x00])[1]

    def read_status(self, addr: int) -> int:
        # Status registers (≥ 0x30) require READ | BURST or you get the
        # config register at the same address instead.
        return self.spi.xfer2([(addr & 0x3F) | READ | BURST, 0x00])[1]

    def read_burst(self, addr: int, n: int) -> list[int]:
        return self.spi.xfer2([(addr & 0x3F) | READ | BURST] + [0] * n)[1:]

    def read_fifo(self, n: int) -> list[int]:
        # FIFO reads use single-byte access for n=1, burst for n>1.
        return self.spi.xfer2([FIFO_ADDR | READ | BURST] + [0] * n)[1:]

    # ── High-level helpers ───────────────────────────────────────────
    def reset(self) -> None:
        self.strobe(SRES)
        time.sleep(0.05)
        # After reset, wait until CHIP_RDY (status byte bit 7 = 0)
        for _ in range(100):
            s = self.strobe(SNOP)
            if not (s & 0x80):
                return
            time.sleep(0.001)
        raise RuntimeError("CC1101 chip never became ready after reset")

    def get_marcstate(self) -> int:
        return self.read_status(MARCSTATE) & 0x1F

    def get_rxbytes(self) -> tuple[int, bool]:
        v = self.read_status(RXBYTES)
        return v & 0x7F, bool(v & 0x80)  # (count, overflow_flag)

    def enable_rx(self) -> None:
        self.strobe(SIDLE)
        self.strobe(SFRX)         # flush RX FIFO
        self.strobe(SCAL)
        time.sleep(0.01)          # calibration ~720 µs
        self.strobe(SRX)

    def transmit(self, payload: bytes) -> None:
        """Transmit a fixed-length payload using current configuration.

        After STX, the chip walks CALIBRATE → SETTLING → TX → (back to RX if
        MCSM1 TXOFF_MODE=3, which is what configure_fineoffset_fsk_rx sets).
        Polls MARCSTATE until we leave TX.
        """
        # Make sure we're not mid-RX
        self.strobe(SIDLE)
        # Flush TX FIFO (only valid in IDLE / TXFIFO_UNDERFLOW)
        self.strobe(SFTX)
        # Burst-write the payload bytes to the TX FIFO
        self.write_burst(FIFO_ADDR, list(payload))
        # Strobe TX
        self.strobe(STX)
        # Wait until the chip has left TX state
        deadline = time.monotonic() + 0.5
        prev = -1
        while time.monotonic() < deadline:
            marc = self.get_marcstate()
            if marc != prev:
                prev = marc
            # 0x13 = TX state. Anything else means we've completed or aborted.
            if marc != 0x13 and marc != 0x14 and marc != 0x15:  # TX, TX_END, RXTX_SWITCH
                return
            time.sleep(0.001)
        raise RuntimeError(f"TX timeout, last MARCSTATE=0x{prev:02X}")

    def set_tx_power_433mhz(self, pa_value: int = 0x60) -> None:
        """Set CC1101 PA table[0] for 433 MHz output.

        Common values (datasheet § 24): 0x60 ≈ 10 dBm (max for 433 MHz),
        0x50 ≈ 7 dBm, 0x30 ≈ 0 dBm, 0x12 ≈ -10 dBm. FREND0 register selects
        which PATABLE index is used; default index 0 is what we want.
        """
        self.write_reg(PATABLE, pa_value)

    def identify(self) -> tuple[int, int]:
        return self.read_status(PARTNUM), self.read_status(VERSION)


def configure_fineoffset_fsk_rx(c: CC1101,
                                 freq_hz: float = 433.92e6,
                                 bit_rate: float = 17_241,
                                 deviation_hz: float = 50_000,
                                 chan_bw_hz: float = 101_000,
                                 sync_word: int = 0x2DD4,
                                 packet_length: int = 17) -> dict:
    """Program CC1101 for receiving Fineoffset-style FSK packets.

    Values are calculated from the CC1101 datasheet (rev SWRS061I) formulas,
    not hand-rolled magic numbers. Returns the computed register values for
    transparency.
    """
    XOSC = 26_000_000

    # ── Carrier frequency ────────────────────────────────────────────
    # FREQ register = round(f_carrier * 2^16 / f_xosc)
    f_word = int(round(freq_hz * (1 << 16) / XOSC))
    f2, f1, f0 = (f_word >> 16) & 0xFF, (f_word >> 8) & 0xFF, f_word & 0xFF

    # ── Bit rate ────────────────────────────────────────────────────
    # R = ((256 + DRATE_M) * 2^DRATE_E / 2^28) * f_xosc
    # Solve for DRATE_E that puts (256+M) in [256..511]
    drate_e = 0
    for e in range(16):
        m_plus = bit_rate * (1 << 28) / ((1 << e) * XOSC)
        if 256 <= m_plus < 512:
            drate_e = e
            drate_m = int(round(m_plus)) - 256
            break
    else:
        raise ValueError(f"bit rate {bit_rate} outside CC1101 range")
    drate_m = max(0, min(255, drate_m))

    # ── Channel bandwidth ────────────────────────────────────────────
    # BW = f_xosc / (8 * (4 + CHANBW_M) * 2^CHANBW_E)
    # Try (E,M) combos and pick the one closest to requested BW.
    best = None
    for e in range(4):
        for m in range(4):
            bw = XOSC / (8 * (4 + m) * (1 << e))
            err = abs(bw - chan_bw_hz)
            if best is None or err < best[0]:
                best = (err, e, m, bw)
    _, cbw_e, cbw_m, actual_bw = best

    # MDMCFG4 = CHANBW_E<<6 | CHANBW_M<<4 | DRATE_E
    mdmcfg4 = (cbw_e << 6) | (cbw_m << 4) | drate_e

    # ── Frequency deviation ──────────────────────────────────────────
    # f_dev = (f_xosc / 2^17) * (8 + DEVIATION_M) * 2^DEVIATION_E
    dev_lsb = XOSC / (1 << 17)
    best = None
    for e in range(8):
        for m in range(8):
            d = dev_lsb * (8 + m) * (1 << e)
            err = abs(d - deviation_hz)
            if best is None or err < best[0]:
                best = (err, e, m, d)
    _, dev_e, dev_m, actual_dev = best
    deviatn = (dev_e << 4) | dev_m

    # ── Sync word, packet length, control ────────────────────────────
    sync1, sync0 = (sync_word >> 8) & 0xFF, sync_word & 0xFF

    # ── Program all registers ────────────────────────────────────────
    c.write_reg(IOCFG2, 0x29)   # GDO2 = CHIP_RDY
    c.write_reg(IOCFG0, 0x06)   # GDO0 = asserts on sync, deasserts at end of packet
    c.write_reg(FIFOTHR, 0x47)
    c.write_reg(SYNC1, sync1)
    c.write_reg(SYNC0, sync0)
    c.write_reg(PKTLEN, packet_length)
    c.write_reg(PKTCTRL1, 0x04) # APPEND_STATUS, no address check
    c.write_reg(PKTCTRL0, 0x00) # fixed length, no CRC autoflush, no whitening
    c.write_reg(CHANNR, 0)
    c.write_reg(FSCTRL1, 0x06)  # IF ≈ 152 kHz
    c.write_reg(FSCTRL0, 0x00)
    c.write_reg(FREQ2, f2); c.write_reg(FREQ1, f1); c.write_reg(FREQ0, f0)
    c.write_reg(MDMCFG4, mdmcfg4)
    c.write_reg(MDMCFG3, drate_m)
    # MDMCFG2 bits 6:4: 000 = 2-FSK, 001 = GFSK, 011 = ASK/OOK, 100 = 4-FSK,
    # 111 = MSK. RadioLib SX127x beginFSK() ACTUALLY defaults to
    # ModulationShaping=NONE on the SX1276 (verified by register dump in
    # 2026-05). So use plain 2-FSK here, not GFSK, to match the LilyGo's
    # RX matched filter envelope.
    c.write_reg(MDMCFG2, 0x02)  # 2-FSK, 16/16 sync, no Manchester
    # MDMCFG1 NUM_PREAMBLE (bits 6:4): 111b = 24 bytes of 0xAA preamble.
    # Long preamble lets SX127x's preamble-tracker fully bit-sync before
    # our sync word; necessary for reliable CC1101→SX127x decoding.
    c.write_reg(MDMCFG1, 0x72)  # 24-byte preamble, CHANSPC_E=2
    c.write_reg(MDMCFG0, 0xF8)
    c.write_reg(DEVIATN, deviatn)
    c.write_reg(MCSM1, 0x3C)    # CCA=on, RXOFF=stay in RX, TXOFF=IDLE
    c.write_reg(MCSM0, 0x18)    # auto-cal on IDLE->RX/TX
    c.write_reg(FOCCFG, 0x16)
    c.write_reg(BSCFG, 0x6C)
    c.write_reg(AGCCTRL2, 0x43)
    c.write_reg(AGCCTRL1, 0x40)
    c.write_reg(AGCCTRL0, 0x91)
    c.write_reg(FREND1, 0x56)
    c.write_reg(FREND0, 0x10)
    c.write_reg(FSCAL3, 0xE9)
    c.write_reg(FSCAL2, 0x2A)
    c.write_reg(FSCAL1, 0x00)
    c.write_reg(FSCAL0, 0x1F)
    c.write_reg(TEST2, 0x81)
    c.write_reg(TEST1, 0x35)
    c.write_reg(TEST0, 0x09)

    return {
        "carrier_hz": f_word * XOSC / (1 << 16),
        "bit_rate_bps": (256 + drate_m) * (1 << drate_e) / (1 << 28) * XOSC,
        "deviation_hz": actual_dev,
        "channel_bw_hz": actual_bw,
        "sync_word": f"0x{sync_word:04X}",
        "packet_length": packet_length,
        "registers": {
            "FREQ2/1/0": f"{f2:02X} {f1:02X} {f0:02X}",
            "MDMCFG4/3": f"{mdmcfg4:02X} {drate_m:02X}",
            "DEVIATN": f"{deviatn:02X}",
        },
    }


# ═══════════════════════════════════════════════════════════════════════
# OOK / arbitrary-waveform TX extensions (2026-08-19)
# The CC1101 (unlike the E22's SX1268) does OOK/ASK, so it can transmit raw
# on/off waveforms — replay the OOK-PWM remotes, or synthesise any 433 signal.
# In OOK the TX FIFO bits ARE the waveform: 1 chip = 1 bit, 1=carrier on
# (PATABLE[1]), 0=carrier off (PATABLE[0]=0). No preamble/sync/CRC added.
# ═══════════════════════════════════════════════════════════════════════
TXBYTES = 0x3A   # status reg: bit7 underflow, bits6-0 count


def configure_ook_tx(c, freq_hz=433.92e6, chip_rate=100_000, pa_on=0xC0):
    """Configure the CC1101 for raw OOK transmit at `chip_rate` chips/second.

    Returns the actual chip rate. After this, feed a chip bitstream to
    transmit_bitstream() / transmit_ook_timing(). pa_on is PATABLE[1] (0xC0
    ≈ max at 433 MHz).
    """
    XOSC = 26_000_000
    c.strobe(SIDLE)
    fw = int(round(freq_hz * (1 << 16) / XOSC))
    c.write_reg(FREQ2, (fw >> 16) & 0xFF)
    c.write_reg(FREQ1, (fw >> 8) & 0xFF)
    c.write_reg(FREQ0, fw & 0xFF)
    # chip (data) rate -> DRATE_E/M
    drate_e = drate_m = None
    for e in range(16):
        mp = chip_rate * (1 << 28) / ((1 << e) * XOSC)
        if 256 <= mp < 512:
            drate_e, drate_m = e, int(round(mp)) - 256
            break
    if drate_e is None:
        raise ValueError("chip_rate out of range")
    c.write_reg(MDMCFG4, drate_e)          # BW bits don't matter for TX
    c.write_reg(MDMCFG3, drate_m)
    c.write_reg(MDMCFG2, 0x30)             # ASK/OOK, no manchester, NO sync
    c.write_reg(MDMCFG1, 0x00)             # 0-byte preamble, CHANSPC_E=0
    c.write_reg(MDMCFG0, 0x00)
    c.write_reg(PKTCTRL1, 0x00)
    c.write_reg(PKTCTRL0, 0x00)            # fixed length, no whitening/CRC
    c.write_reg(FSCTRL1, 0x06)
    c.write_reg(FREND0, 0x11)              # OOK: PA_POWER=1 -> use PATABLE[0]/[1]
    c.write_reg(MCSM0, 0x18)               # auto-cal IDLE->TX
    c.write_reg(FSCAL3, 0xE9); c.write_reg(FSCAL2, 0x2A)
    c.write_reg(FSCAL1, 0x00); c.write_reg(FSCAL0, 0x1F)
    c.write_reg(TEST2, 0x81); c.write_reg(TEST1, 0x35); c.write_reg(TEST0, 0x09)
    c.spi.xfer2([PATABLE | BURST, 0x00, pa_on])   # [0]=off, [1]=on
    return (256 + drate_m) * (1 << drate_e) / (1 << 28) * XOSC


def configure_ook_async_rx(c, freq_hz=433.92e6, data_rate=10_000, chan_bw_hz=232_000):
    """Asynchronous-serial OOK RX: the CC1101 demodulates and puts raw bits on
    GDO2 (IOCFG2=0x0D, "serial data output"); no packet engine, no FIFO.
    Timing of the marks/spaces is then measured by the host on the GDO2 pin.

    data_rate sets the demodulator's bit-timing/filter, not a framing: pick
    about 2x the shortest expected pulse rate (190 us -> ~5 kbps -> 10 kbps).
    Returns actual carrier/bandwidth for the log.
    """
    XOSC = 26_000_000
    c.strobe(SIDLE)
    fw = int(round(freq_hz * (1 << 16) / XOSC))
    c.write_reg(FREQ2, (fw >> 16) & 0xFF)
    c.write_reg(FREQ1, (fw >> 8) & 0xFF)
    c.write_reg(FREQ0, fw & 0xFF)
    drate_e = drate_m = None
    for e in range(16):
        mp = data_rate * (1 << 28) / ((1 << e) * XOSC)
        if 256 <= mp < 512:
            drate_e, drate_m = e, int(round(mp)) - 256
            break
    if drate_e is None:
        raise ValueError("data_rate out of range")
    best = None
    for e in range(4):
        for m in range(4):
            bw = XOSC / (8 * (4 + m) * (1 << e))
            err = abs(bw - chan_bw_hz)
            if best is None or err < best[0]:
                best = (err, e, m, bw)
    _, cbw_e, cbw_m, actual_bw = best
    c.write_reg(IOCFG2, 0x0D)              # GDO2 = async serial data OUT
    c.write_reg(IOCFG0, 0x2E)              # GDO0 = high-Z (it is the data IN pin in async TX)
    c.write_reg(FIFOTHR, 0x47)
    c.write_reg(PKTCTRL1, 0x00)
    c.write_reg(PKTCTRL0, 0x32)            # PKT_FORMAT=11 async serial, LENGTH_CONFIG=10 infinite
    c.write_reg(FSCTRL1, 0x06)
    c.write_reg(FSCTRL0, 0x00)
    c.write_reg(MDMCFG4, (cbw_e << 6) | (cbw_m << 4) | drate_e)
    c.write_reg(MDMCFG3, drate_m)
    c.write_reg(MDMCFG2, 0x30)             # ASK/OOK, no Manchester, SYNC_MODE=000 (none)
    c.write_reg(MDMCFG1, 0x00)
    c.write_reg(MDMCFG0, 0xF8)
    c.write_reg(MCSM1, 0x3C)               # stay in RX
    c.write_reg(MCSM0, 0x18)               # auto-cal IDLE->RX
    c.write_reg(FOCCFG, 0x16)
    c.write_reg(BSCFG, 0x6C)
    c.write_reg(AGCCTRL2, 0x03)            # OOK: MAGN_TARGET 33 dB, full LNA/DVGA range
    c.write_reg(AGCCTRL1, 0x00)
    c.write_reg(AGCCTRL0, 0x91)
    c.write_reg(FREND1, 0x56)
    c.write_reg(FREND0, 0x11)
    c.write_reg(FSCAL3, 0xE9); c.write_reg(FSCAL2, 0x2A)
    c.write_reg(FSCAL1, 0x00); c.write_reg(FSCAL0, 0x1F)
    c.write_reg(TEST2, 0x81); c.write_reg(TEST1, 0x35); c.write_reg(TEST0, 0x09)
    c.strobe(SCAL)
    time.sleep(0.01)
    c.strobe(SRX)
    return {"carrier_hz": fw * XOSC / (1 << 16), "channel_bw_hz": actual_bw,
            "data_rate_bps": (256 + drate_m) * (1 << drate_e) / (1 << 28) * XOSC}


def _bits_to_bytes(chips):
    """Pack a list of 0/1 chips into bytes, MSB-first (padded with 0)."""
    out = bytearray()
    acc = nbits = 0
    for b in chips:
        acc = (acc << 1) | (b & 1)
        nbits += 1
        if nbits == 8:
            out.append(acc); acc = nbits = 0
    if nbits:
        out.append(acc << (8 - nbits))
    return bytes(out)


def _wait_tx_done(c, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        m = c.get_marcstate()
        if m not in (0x13, 0x14, 0x15):    # TX / TX_END / RXTX_SWITCH
            return
        time.sleep(0.0005)
    c.strobe(SIDLE)
    raise RuntimeError("OOK TX timeout")


def transmit_bitstream(c, chips, repeats=1, gap_s=0.02):
    """Transmit a chip bitstream (list of 0/1) as OOK, `repeats` times.

    Uses fixed-length packet mode when it fits the 64-byte FIFO, else the
    CC1101 infinite-length technique (refill FIFO while transmitting, then
    switch to fixed length so it stops cleanly).
    """
    data = _bits_to_bytes(chips)
    n = len(data)
    for _ in range(repeats):
        c.strobe(SIDLE); c.strobe(SFTX)
        if n <= 64:
            c.write_reg(PKTCTRL0, 0x00)
            c.write_reg(PKTLEN, n & 0xFF)
            c.write_burst(FIFO_ADDR, list(data))
            c.strobe(STX)
            _wait_tx_done(c)
        else:
            c.write_reg(PKTLEN, n & 0xFF)          # low byte of total length
            c.write_reg(PKTCTRL0, 0x02)            # infinite length
            c.write_burst(FIFO_ADDR, list(data[:64]))
            idx = 64
            c.strobe(STX)
            switched = False
            if n < 256:
                c.write_reg(PKTCTRL0, 0x00); switched = True
            while idx < n:
                txb = c.read_status(TXBYTES) & 0x7F
                if txb >= 62:
                    time.sleep(0.0003); continue
                if not switched and (n - idx) < 256:
                    c.write_reg(PKTCTRL0, 0x00); switched = True
                space = 64 - txb
                chunk = data[idx:idx + min(space, n - idx)]
                c.write_burst(FIFO_ADDR, list(chunk)); idx += len(chunk)
            _wait_tx_done(c)
        time.sleep(gap_s)


def timing_to_chips(pulses, chip_us):
    """Convert [(high_us, low_us), ...] pulse pairs to a chip bitstream at
    `chip_us` per chip. Use for replaying a captured OOK waveform."""
    chips = []
    for high_us, low_us in pulses:
        chips += [1] * max(1, round(high_us / chip_us))
        chips += [0] * max(0, round(low_us / chip_us))
    return chips


def transmit_ook_timing(c, pulses, chip_us, repeats=1, gap_s=0.02):
    """Transmit an OOK waveform given as (high_us, low_us) pulses. Assumes
    configure_ook_tx() was called with chip_rate ≈ 1e6/chip_us."""
    transmit_bitstream(c, timing_to_chips(pulses, chip_us), repeats, gap_s)


def pwm_code_to_pulses(bits, short_us, long_us, gap_us, sync_gap_us=None):
    """OOK-PWM (each bit = a short or long HIGH pulse + a fixed LOW gap).
    '1' -> long HIGH, '0' -> short HIGH; trailing sync_gap after the code.
    Matches the grey-power/doorbell family (see ook-pwm-remotes.md)."""
    pulses = [((long_us if b else short_us), gap_us) for b in bits]
    if sync_gap_us:
        h, _ = pulses[-1]; pulses[-1] = (h, sync_gap_us)
    return pulses

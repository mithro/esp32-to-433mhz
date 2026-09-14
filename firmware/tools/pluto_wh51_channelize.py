#!/usr/bin/env python3
"""Memory-safe narrowband channelizing WH51/WS69 decoder for a raw cs16 IQ capture.

Designed to run on desktop.buddy (the intensive-ops host), reading a capture file scp'd from the
Pluto — NOT on the little rpi-sdr-pluto Pi (whose 8 GB OOM-wedged under the earlier whole-file
approach). Channelization is done in streaming chunks with persistent FIR filter state, so peak
memory is ~one chunk + the decimated stream, never the whole 2 Msps file at once.

Method (replicates what the narrowband CC1101 does, which decodes these fine):
  for each candidate RF centre (Fine Offset crystals cluster ~434.0 MHz):
    mix centre->DC, low-pass ~60 kHz, decimate to ~256 kSa/s  (isolates ONE sensor from the
    ~100 overlapping transmitters in the 2 MHz capture), then FSK-discriminator-demod and apply
    the proven Fine Offset frame-check (CRC-8 poly 0x31 + additive checksum).
A decoded id that matches one the rpi5 reference is currently logging IS the Pluto cross-check.

Why a custom channelizer and not rtl_433: on this host rtl_433's live plutosdr stream produces no
output, and rtl_433 offline on the raw capture cannot slice the FSK because the 2 MHz capture is
swamped by 100+ overlapping transmitters (it reports each burst as "Single pulse ... FSK"). The
narrowband CC1101 decodes these fine precisely because it filters to one ~60-100 kHz channel; this
tool does the same in software. The FSK slicer thresholds at the constant mark/space-cluster
midpoint (rtl_433 "minmax" idea) so it does not droop on WH51's FF FF FF (24-mark) run.

Usage: pluto_wh51_channelize.py <capture.cs16> <LO_Hz> [fs_Hz=2048000] [centers_MHz_csv] [decims_csv]
  centers_MHz_csv : optional explicit candidate RF centres (e.g. "434.00,434.02"); default sweeps
                    433.86..434.16 in 20 kHz steps.
  decims_csv      : optional decimation factors (e.g. "8"); default "8,16".
"""
import sys, numpy as np, scipy.signal as ss

CAP = sys.argv[1]
LO = float(sys.argv[2])
FS = float(sys.argv[3]) if len(sys.argv) > 3 else 2048000.0
CENTERS = [float(x) for x in sys.argv[4].split(",")] if len(sys.argv) > 4 and sys.argv[4] else None
DECIMS = [int(x) for x in sys.argv[5].split(",")] if len(sys.argv) > 5 and sys.argv[5] else [8, 16]
BR = 17241.0
FULLSCALE = 2048.0                 # AD9361 12-bit

def crc8(d, poly=0x31, init=0):
    r = init
    for x in d:
        r ^= x
        for _ in range(8):
            r = ((r << 1) ^ poly) & 0xff if (r & 0x80) else (r << 1) & 0xff
    return r

def decode_bits(bs):
    p = bs.find("0010110111010100")          # Fine Offset preamble/sync 0x2dd4
    if p < 0:
        return None
    b = [int(bs[i:i + 8], 2) for i in range(p + 16, len(bs) - 7, 8)]
    if len(b) >= 14 and b[0] == 0x51 and crc8(b[0:12]) == b[12] and (sum(b[0:13]) & 0xff) == b[13]:
        return ("WH51", bytes(b[0:14]).hex(), bytes(b[1:4]).hex().upper(), b[6])
    if len(b) >= 17 and b[0] == 0x24 and crc8(b[0:16]) == 0 and (sum(b[0:16]) & 0xff) == b[16]:
        return ("WS69", bytes(b[0:17]).hex(), bytes(b[1:4]).hex().upper(), None)
    return None

def channelize(cap, fc, decim):
    """Stream cap.cs16 in chunks: mix (fc->DC), anti-alias FIR (stateful), decimate. Returns the
    decimated complex stream and its sample rate. Peak memory ~ one chunk."""
    fs_d = FS / decim
    taps = ss.firwin(129, 0.9 * (fs_d / 2), fs=FS).astype(np.float32)
    zi = np.zeros(len(taps) - 1, dtype=np.complex64)
    dphi = -2j * np.pi * (fc - LO) / FS
    out = []
    base = 0                           # global index of first sample in the current chunk
    next_g = 0                         # global index of the next output (decimated) sample
    CH = 8 * 1024 * 1024               # complex samples per chunk
    with open(cap, "rb") as f:
        while True:
            raw = np.fromfile(f, dtype="<i2", count=2 * CH)
            if raw.size < 2:
                break
            m = raw.size // 2
            iq = (raw[0:2 * m:2].astype(np.float32) + 1j * raw[1:2 * m:2].astype(np.float32)) / FULLSCALE
            k = np.arange(base, base + m, dtype=np.float64)
            iq *= np.exp(dphi * k).astype(np.complex64)
            filt, zi = ss.lfilter(taps, 1.0, iq, zi=zi)
            start = next_g - base                       # local index of the next output sample
            if start < m:
                idx = np.arange(start, m, decim)
                out.append(filt[idx].astype(np.complex64))
                next_g = base + int(idx[-1]) + decim
            base += m
    if not out:
        return np.zeros(0, np.complex64), fs_d
    return np.concatenate(out), fs_d

def demod_decode(y, fs):
    """burst-detect on the narrowband stream, FSK-discriminator-demod, slice, decode."""
    if len(y) < 200:
        return {}
    mag = np.abs(y)
    W = max(8, int(fs / 4000))
    env = mag[:len(mag) // W * W].reshape(-1, W).mean(1)
    floor = np.median(env) + 1e-9
    thr = floor * 3
    regs, i = [], 0
    while i < len(env):
        if env[i] > thr:
            j = i
            while j < len(env) and env[j] > thr * 0.5:
                j += 1
            if (j - i) * W > int(0.004 * fs):
                regs.append((i * W, j * W))
            i = j
        else:
            i += 1
    sps = fs / BR
    found = {}
    for (a, b) in regs:
        seg = y[max(0, a - int(0.003 * fs)):b + int(0.003 * fs)]
        if len(seg) < 200:
            continue
        inst = np.angle(seg[1:] * np.conj(seg[:-1])) * fs / (2 * np.pi)
        m = np.abs(seg[1:])
        on = m > m.max() * 0.3
        if on.sum() < 40:
            continue
        # Threshold at the constant midpoint between the mark and space frequency clusters
        # (rtl_433 minmax idea). A sliding-average DC removal droops on long same-symbol runs
        # like WH51's FF FF FF (24 mark bits); a constant midpoint does not. The 0xAA preamble
        # guarantees both clusters are well populated, so the 12/88 percentiles bracket them.
        inst_on = inst[on]
        thr = 0.5 * (np.percentile(inst_on, 12) + np.percentile(inst_on, 88))
        inst = inst - thr
        i0 = int(np.argmax(on)); i1 = len(on) - int(np.argmax(on[::-1]))
        # try a few fractional start offsets and both polarities
        for frac in np.linspace(0, sps, 6, endpoint=False):
            idx = (i0 + frac + np.arange(0, (i1 - i0) / sps) * sps).astype(int)
            idx = idx[idx < len(inst)]
            if len(idx) < 40:
                continue
            for pol in (1, -1):
                r = decode_bits(''.join('1' if v else '0' for v in (pol * inst[idx] > 0)))
                if r:
                    found[r[0] + "/" + r[2]] = r
    return found

def main():
    allf = {}
    centers = CENTERS if CENTERS is not None else list(np.arange(433.86, 434.16, 0.02))
    for decim in DECIMS:
        for fc_mhz in centers:
            y, fs = channelize(CAP, fc_mhz * 1e6, decim)
            res = demod_decode(y, fs)
            for k, v in res.items():
                allf[k] = v
            if res:
                print("decim=%d fc=%.3f -> %s" % (decim, fc_mhz, {k: (v[2], v[3]) for k, v in res.items()}), flush=True)
    print("=== distinct Fine Offset frames decoded from Pluto IQ: %d ===" % len(allf))
    for k, v in sorted(allf.items()):
        print("  %-14s id=%s moisture=%s hex=%s" % (k, v[2], v[3], v[1]))

if __name__ == "__main__":
    main()

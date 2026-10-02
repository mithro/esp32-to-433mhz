#!/usr/bin/env python3
"""Annotate the SX1278 Ra-02 breakout photos with the DIO2 solder point.

Four cells, the three photo panels drawn on committed photos of the real board:

  A  the module map    -- component side, every one of the Ra-02's 16
                          castellations named, pin 7 (DIO2) ringed.
  C  the solder point  -- pins 3-8 close up: where the iron goes, and which pads
                          sit either side of the target.
  B  the 2x4 header    -- the carrier's back: its silkscreen is the board's whole
                          interface, and DIO2 is not on it.
  N  notes             -- what the ring colours mean, and the shape of the
                          on-node check that proves the wire landed on the pad.

Pin names and numbering: Ai-Thinker "Ra-01/Ra-02 LoRa Module User Manual"
section 2.2 -- 1 GND, 2 GND, 3 3.3V, 4 RESET, 5 DIO0, 6 DIO1, 7 DIO2, 8 DIO3,
9 GND, 10 DIO4, 11 DIO5, 12 SCK, 13 MISO, 14 MOSI, 15 NSS, 16 GND; pins 1-8 down
one 17 mm edge and 9-16 back up the other, counter-clockwise seen from the
component side, with the IPEX antenna connector at the pin-1 corner.

Which of those the carrier routes to its header is read straight off the header
silkscreen in panel B (MISO/DIO0/SCK/MOSI/RST/NSS/GND/3V3): module pins 3, 4, 5,
12, 13, 14, 15 and a GND.  DIO1, DIO2, DIO3, DIO4 and DIO5 go nowhere, which is
why DIO2 needs a wire soldered to the module pad itself.

Pad positions are not measured pad by pad: the Ra-02 specification fixes the row
(2.0 mm pitch, first pad centre 1.5 mm from the end of a 17 mm edge), so each row
is interpolated between its first and last pad -- the four ROW_* pixel positions
below are the only per-photo calibration.  They are not a rotation of one
another: the photo has enough perspective that each row is calibrated on its own.

Panel widths are measured from the text rather than guessed, so editing a label
cannot silently push it off the edge.

The diagram is rendered at full photo resolution and then downscaled to
OUT_WIDTH and saved as JPEG: the panels are photographs, so PNG stores it at
3.8 MB against 320 kB here, and the labels stay legible well below this width.

Regenerate with `uv run --with pillow scripts/draw_dio2_wire.py`.

SPDX-License-Identifier: Apache-2.0
"""
from __future__ import annotations

import pathlib

from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent.parent
PART = ROOT / "hardware" / "parts" / "sx1278-ra02-breakout"
FRONT = PART / "photos" / "ra02-front.jpg"
HEADER = PART / "photos" / "ra02-header.jpg"
OUT = PART / "images" / "dio2-wire.jpg"

OUT_WIDTH = 1400        # downscale target; the labels survive to about 620 px
OUT_QUALITY = 88

# ---- front photo: first and last pad centre of each castellation row ----
ROW_A = ((458, 905), (482, 2005))     # module pins 1 -> 8, down the antenna-side edge
ROW_B = ((1644, 950), (1668, 2050))   # module pins 16 -> 9, up the far edge
IPEX = (620, 930)                     # antenna connector centre: the pin-1 landmark
HDR = (650, 2150, 1480, 2500)         # the carrier's 2x4 header, seen from the front
CROP_A = (330, 700, 1830, 2560)       # whole assembly
CROP_C = (330, 1090, 740, 2130)       # pins 3-8, close up

# ---- header photo: rotated -90 so the silkscreen reads upright, then cropped ----
CROP_H = (330, 330, 1800, 2400)       # in the ORIGINAL photo, before rotating
CROP_B = (540, 140, 1370, 1220)       # in the ROTATED image

NAMES = ["GND", "GND", "3.3V", "RESET", "DIO0", "DIO1", "DIO2", "DIO3",
         "GND", "DIO4", "DIO5", "SCK", "MISO", "MOSI", "NSS", "GND"]
ON_HEADER = {1, 2, 3, 4, 5, 9, 12, 13, 14, 15, 16}   # routed to the 2x4 header
TARGET = 7                                            # DIO2
HEADER_PINS = ["MISO", "DIO0", "SCK", "MOSI", "RST", "NSS", "GND", "3V3"]

INK = (240, 242, 246)
DIM = (152, 160, 170)
BG = (20, 22, 26)
PANEL = (32, 35, 40)
RULE = (58, 62, 70)
ROUTED = (96, 170, 235)     # pad the carrier routes to the 2x4 header
DEAD = (250, 190, 70)       # castellation that goes nowhere
HOT = (255, 76, 76)         # DIO2 -- the one the wire goes to

CHECKS = [
    "force DIO2 from the node's console: SxReg drives it low, then high",
    "read GPIO_IN_REG (0x6000403C) over the built-in USB-JTAG in both states",
    "the bit that flips names the GPIO the wire landed on — expect bit 20",
]

SCRATCH = ImageDraw.Draw(Image.new("RGB", (1, 1)))


def font(sz, bold=True):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(f"/usr/share/fonts/truetype/dejavu/{name}", sz)
    except OSError:
        return ImageFont.load_default()


def tw(s, f):
    return SCRATCH.textbbox((0, 0), s, font=f)[2]


def wrap(text, f, maxw):
    lines, cur = [], ""
    for word in text.split(" "):
        trial = f"{cur} {word}".strip()
        if cur and tw(trial, f) > maxw:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    return lines + ([cur] if cur else [])


def lerp(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def pad_xy(pin):
    """Front-photo pixel centre of module pin 1..16."""
    if pin <= 8:
        return lerp(ROW_A[0], ROW_A[1], (pin - 1) / 7)
    return lerp(ROW_B[0], ROW_B[1], (16 - pin) / 7)


def photo_panel(src, crop, scale, ml, mr, mt, mb, minw=0):
    """Blank panel with a scaled crop pasted in, plus its coordinate transform."""
    x0, y0 = crop[0], crop[1]
    im = src.crop(crop)
    im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
    p = Image.new("RGB", (max(im.width + ml + mr, minw), im.height + mt + mb), PANEL)
    p.paste(im, (ml, mt))
    return p, (lambda xy: (ml + (xy[0] - x0) * scale, mt + (xy[1] - y0) * scale))


def ring(d, xy, col, r, w):
    d.ellipse((xy[0] - r, xy[1] - r, xy[0] + r, xy[1] + r), outline=col, width=w)


def leader(d, xy, r, to_x, col, w, label, f, ink, left):
    d.line((xy[0] + (-r if left else r), xy[1], to_x, xy[1]), fill=col, width=w)
    x = to_x - tw(label, f) - 16 if left else to_x + 16
    d.text((x, xy[1] - f.size * 0.66), label, font=f, fill=ink)


def label_of(pin):
    return f"{pin}  {NAMES[pin - 1]}"


def panel_a(src):
    f, fh, fc = font(34), font(40), font(26, False)
    gut = max(tw(label_of(p), fh if p == TARGET else f) for p in range(1, 17)) + 70
    p, tc = photo_panel(src, CROP_A, 0.66, gut, gut, 100, 40)
    d = ImageDraw.Draw(p)

    ax, ay = tc(IPEX)
    ring(d, (ax, ay), DIM, 66, 5)
    d.line((ax, ay - 66, ax, 66), fill=DIM, width=3)
    cap = "antenna connector — marks the pin 1 corner"
    d.text((ax - tw(cap, fc) / 2, 26), cap, font=fc, fill=DIM)

    hx0, hy0 = tc((HDR[0], HDR[1]))
    hx1, hy1 = tc((HDR[2], HDR[3]))
    d.rectangle((hx0, hy0, hx1, hy1), outline=DIM, width=4)
    d.line((hx1, (hy0 + hy1) / 2, p.width - gut + 12, (hy0 + hy1) / 2), fill=DIM, width=3)
    d.text((p.width - gut + 26, (hy0 + hy1) / 2 - 18), "2×4 header", font=fc, fill=DIM)

    for pin in range(1, 17):
        xy = tc(pad_xy(pin))
        left, hot = pin <= 8, pin == TARGET
        col = HOT if hot else (ROUTED if pin in ON_HEADER else DEAD)
        r = 46 if hot else 26
        ring(d, xy, col, r, 9 if hot else 5)
        leader(d, xy, r, gut - 44 if left else p.width - gut + 44, col, 8 if hot else 3,
               label_of(pin), fh if hot else f, col if hot else INK, left)
    return p


def panel_c(src):
    f, fh = font(34), font(38)
    hot_label = label_of(TARGET) + "   ← wire goes here"
    gut = max(max(tw(label_of(p), f) for p in range(3, 9)), tw(hot_label, fh)) + 100
    p, tc = photo_panel(src, CROP_C, 1.24, 56, gut, 88, 44)
    d = ImageDraw.Draw(p)
    d.text((56, 22), "Where the iron goes", font=font(34), fill=INK)
    for pin in range(3, 9):
        xy = tc(pad_xy(pin))
        hot = pin == TARGET
        col = HOT if hot else (ROUTED if pin in ON_HEADER else DEAD)
        r = 52 if hot else 30
        ring(d, xy, col, r, 10 if hot else 5)
        leader(d, xy, r, p.width - gut + 36, col, 9 if hot else 3,
               hot_label if hot else label_of(pin), fh if hot else f,
               col if hot else INK, False)
    return p


def panel_b(src, minw):
    rot = src.crop(CROP_H).rotate(-90, expand=True)
    p, _ = photo_panel(rot, CROP_B, 0.74, 44, 44, 88, 76, minw=minw)
    d = ImageDraw.Draw(p)
    f = font(34, False)
    d.text((44, 22), "The carrier's entire interface", font=font(38), fill=INK)
    d.text((44, p.height - 62), "no DIO1–DIO5 anywhere on it", font=font(34), fill=HOT)

    x = 44 + round((CROP_B[2] - CROP_B[0]) * 0.74) + 60
    if x + 300 < p.width:
        d.text((x, 110), "Eight pins, and that is all:", font=f, fill=INK)
        for i, name in enumerate(HEADER_PINS):
            d.text((x + 16, 180 + i * 50), "· " + name, font=f, fill=DIM)
    return p


def notes_layout(w, d=None):
    """Draw the notes cell (or just measure it, when d is None); returns its height."""
    f, fh = font(34, False), font(38)
    x, y = 46, 26
    if d:
        d.text((x, y), "Reading the rings", font=fh, fill=INK)
    y += 66
    for col, txt in [(HOT, "DIO2 (pin 7) — the pad the wire goes to"),
                     (DEAD, "castellation the carrier routes nowhere"),
                     (ROUTED, "pad routed to the 2×4 header")]:
        if d:
            ring(d, (x + 19, y + 18), col, 17, 6)
            d.text((x + 56, y), txt, font=f, fill=INK)
        y += 56

    y += 30
    if d:
        d.line((x, y, w - 46, y), fill=RULE, width=3)
    y += 32
    if d:
        d.text((x, y), "Verify it with the node plugged in", font=fh, fill=INK)
    y += 66
    for txt in CHECKS:
        lines = wrap(txt, f, w - x - 90)
        if d:
            d.text((x + 8, y), "•", font=f, fill=DIM)
            for j, line in enumerate(lines):
                d.text((x + 46, y + j * 44), line, font=f, fill=DIM)
        y += 44 * len(lines) + 20
    return y + 30


def panel_notes(w, h):
    p = Image.new("RGB", (w, h), PANEL)
    notes_layout(w, ImageDraw.Draw(p))
    return p


def main():
    front = Image.open(FRONT).convert("RGB")
    header = Image.open(HEADER).convert("RGB")
    a, c = panel_a(front), panel_c(front)
    col1, col2 = a.width, c.width
    b = panel_b(header, col1)
    n = panel_notes(col2, max(b.height, notes_layout(col2)))

    gap, top, foot = 34, 218, 84
    row1, row2 = max(a.height, c.height), max(b.height, n.height)
    W = gap + col1 + gap + col2 + gap
    H = top + row1 + gap + row2 + foot
    img = Image.new("RGB", (W, H), BG)
    img.paste(a, (gap, top))
    img.paste(c, (gap + col1 + gap, top))
    img.paste(b, (gap, top + row1 + gap))
    img.paste(n, (gap + col1 + gap, top + row1 + gap))
    d = ImageDraw.Draw(img)

    d.text((gap + 6, 30), "Ra-02 (SX1278) breakout — where the DIO2 wire attaches",
           font=font(66), fill=INK)
    d.text((gap + 10, 112),
           "module pin 7: the 7th castellation counting from the antenna-connector corner",
           font=font(38, False), fill=DIM)
    d.text((gap + 10, 162),
           "the far end is the adapter's J5 pin 2 — GPIO20 on the ESP32-C3",
           font=font(32, False), fill=DIM)
    d.text((gap + 10, H - 50),
           "Photos: the boards themselves.  Pin numbering: Ai-Thinker Ra-01/Ra-02 LoRa Module "
           "User Manual §2.2.  Header nets: read off the silkscreen in the header panel.",
           font=font(28, False), fill=DIM)

    out = img.resize((OUT_WIDTH, round(img.height * OUT_WIDTH / img.width)), Image.LANCZOS)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.save(OUT, quality=OUT_QUALITY, optimize=True, progressive=True)
    print("wrote", OUT.relative_to(ROOT), out.size, f"{OUT.stat().st_size / 1024:.0f} kB")


if __name__ == "__main__":
    main()

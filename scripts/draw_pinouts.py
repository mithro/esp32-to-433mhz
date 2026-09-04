#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Draw one pinout diagram (SVG) of the two socketed radio boards, as seen
from the carrier: component side up with the header edge at the top.  The
front views share the first row and the mirrored back views the second,
one column per board.  Writes docs/images/pinout-radio-boards.svg.
Geometry comes from the generators and the photo measurements recorded
there.
"""

from __future__ import annotations

import pathlib
import sys
import textwrap

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import generate_cc1101 as cc  # noqa: E402
import generate_ra02_breakout as rb  # noqa: E402

OUT = pathlib.Path(__file__).resolve().parent.parent / "docs" / "images"
S = 11.0  # px per mm
PAD = 14.0  # mm of margin around each board view (room for labels)
INK = "#1a1a2e"
BOARD = "#1c6b9c"
BOARD_EDGE = "#0d3f5e"
PIN = "#f2c94c"
GHOST = "#7fb3d5"


class View:
    """One board view; x/y in mm from the board's top-left, `mirror` flips x."""

    def __init__(self, w: float, h: float, mirror: bool):
        self.w, self.h, self.mirror = w, h, mirror
        self.items: list[str] = []

    def X(self, x: float) -> float:
        return (self.w - x if self.mirror else x) * S

    def Y(self, y: float) -> float:
        return y * S

    def rect(self, x0, y0, x1, y1, fill="none", stroke=INK, width=0.15, dash=None, rx=0.0):
        xa, xb = sorted((self.X(x0), self.X(x1)))
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.items.append(f'<rect x="{xa:.1f}" y="{self.Y(y0):.1f}" width="{xb - xa:.1f}" height="{(y1 - y0) * S:.1f}" rx="{rx * S:.1f}" fill="{fill}" stroke="{stroke}" stroke-width="{width * S:.2f}"{d}/>')

    def line(self, x0, y0, x1, y1, stroke=INK, width=0.15):
        self.items.append(f'<line x1="{self.X(x0):.1f}" y1="{self.Y(y0):.1f}" x2="{self.X(x1):.1f}" y2="{self.Y(y1):.1f}" stroke="{stroke}" stroke-width="{width * S:.2f}"/>')

    def circle(self, x, y, r, fill="none", stroke=INK, width=0.15):
        self.items.append(f'<circle cx="{self.X(x):.1f}" cy="{self.Y(y):.1f}" r="{r * S:.1f}" fill="{fill}" stroke="{stroke}" stroke-width="{width * S:.2f}"/>')

    def text(self, x, y, s, size=1.4, anchor="middle", angle=0, weight="normal", fill=INK, family="Helvetica, Arial, sans-serif", halo=False):
        t = f' transform="rotate({angle} {self.X(x):.1f} {self.Y(y):.1f})"' if angle else ""
        h = f' stroke="#ffffff" stroke-width="{0.35 * S:.1f}" paint-order="stroke" stroke-linejoin="round"' if halo else ""
        self.items.append(f'<text x="{self.X(x):.1f}" y="{self.Y(y):.1f}" font-size="{size * S:.1f}" font-family="{family}" font-weight="{weight}" fill="{fill}" text-anchor="{anchor}" dominant-baseline="middle"{t}{h}>{s}</text>')

    def pin(self, x, y, number, label, square=False, label_dir=-1):
        """Header pin: pad ring with the number inside, signal name rotated
        above (label_dir=-1) or below (+1)."""
        if square:
            self.rect(x - 0.8, y - 0.8, x + 0.8, y + 0.8, fill=PIN, stroke=INK, width=0.12)
        else:
            self.circle(x, y, 0.8, fill=PIN, stroke=INK, width=0.12)
        self.circle(x, y, 0.45, fill="#ffffff", stroke=INK, width=0.08)
        self.text(x, y, number, size=0.75, weight="bold")
        ly = y + label_dir * 1.5
        # Rotated text reads bottom-to-top; anchor so it grows away from the pin.
        anchor = "start" if label_dir < 0 else "end"
        self.text(x, ly, label, size=1.05, anchor=anchor, angle=-90, weight="bold", halo=True)

    def svg_group(self, ox: float, oy: float, caption: str, cap_rise: float, cap_size: float) -> str:
        w, h = self.w * S, self.h * S
        cap = f'<text x="{w / 2:.1f}" y="{-cap_rise * S:.1f}" font-size="{cap_size * S:.1f}" font-family="Helvetica, Arial, sans-serif" font-weight="bold" fill="{INK}" text-anchor="middle">{caption}</text>'
        return f'<g transform="translate({ox:.1f} {oy:.1f})">{cap}\n' + "\n".join(self.items) + "\n</g>"


def board_base(v: View, w: float, h: float) -> None:
    v.rect(0, 0, w, h, fill=BOARD, stroke=BOARD_EDGE, width=0.25, rx=0.6)
    v.text(w / 2, h + 3.0, f"{w:g} x {h:g} mm", size=1.2, fill=INK)


def sma_plan(v: View, x: float, edge_y: float, centre_pin: bool) -> None:
    """Edge-mount SMA jack seen from above: legs soldered on the board's pads
    (ground legs 4.25 mm either side on both faces; the centre pin only on the
    component side), a square body straddling the edge and the threaded barrel
    pointing away from the board."""
    legs = (-cc.SMA_GND_OFFSET, cc.SMA_GND_OFFSET) + ((0.0,) if centre_pin else ())
    for dx in legs:
        v.rect(x + dx - cc.SMA_PAD_W / 2, edge_y - cc.SMA_PAD_L, x + dx + cc.SMA_PAD_W / 2, edge_y, fill="#c9c9c9", stroke=INK, width=0.1)
    body, barrel, body_len, total = 3.2, 2.9, 2.6, 9.5
    v.rect(x - body, edge_y - 0.4, x + body, edge_y + body_len, fill="#b8b8b8", stroke=INK, width=0.12, rx=0.2)
    v.rect(x - barrel, edge_y + body_len, x + barrel, edge_y + total, fill="#dedede", stroke=INK, width=0.12)
    y = edge_y + body_len + 0.7
    while y < edge_y + total - 0.3:
        v.line(x - barrel, y, x + barrel, y, width=0.08)
        y += 0.7


def e07_views() -> tuple[View, View]:
    W, H = cc.BOARD_W, cc.BOARD_H
    labels = cc.PIN_NAMES
    views = []
    for mirror in (False, True):
        v = View(W, H, mirror)
        board_base(v, W, H)
        # header: pin 1 at (11.30, 1.60), columns to -x, even pins 2.54 below
        for n in range(1, 9):
            col, row = (n - 1) // 2, (n - 1) % 2
            x = W - cc.HDR_COL_X - col * cc.PITCH
            y = cc.HDR_ROW_Y + row * cc.PITCH
            v.pin(x, y, str(n), labels[str(n)], square=(n == 1), label_dir=-1 if row == 0 else +1)
        for hx in (cc.HOLE_X, W - cc.HOLE_X):
            hy = H - cc.HOLE_FROM_ANT_EDGE
            v.circle(hx, hy, cc.HOLE_PAD / 2, fill=PIN, stroke=INK, width=0.1)
            v.circle(hx, hy, cc.HOLE_D / 2, fill="#ffffff", stroke=INK, width=0.08)
        # CC1101 + crystal region (component side only), SMA at the bottom edge
        if not mirror:
            v.rect(3.0, 9.5, 12.0, 15.5, fill=GHOST, stroke=INK, width=0.1, dash="1 1")
            v.text(7.5, 12.5, "CC1101", size=1.3, weight="bold")
        sma_plan(v, W / 2, H, centre_pin=not mirror)
        v.text(W / 2, H + 11.3, "SMA jack", size=1.1)
        v.text(W / 2, H - cc.SMA_PAD_L - 1.4, "433M" if not mirror else "E07-M1101D V2.0", size=1.1, fill="#ffffff")
        views.append(v)
    return views[0], views[1]


def ra02_views() -> tuple[View, View]:
    W, H = rb.BOARD_W, rb.BOARD_H
    views = []
    for mirror in (False, True):
        v = View(W, H, mirror)
        board_base(v, W, H)
        cx = W / 2
        if not mirror:
            # Ra-02 module (17 x 16, castellations along its right edge), IPEX at the far corner
            v.rect(0.2, 5.5, 16.2, 22.3, fill=GHOST, stroke=INK, width=0.12)
            v.rect(0.8, 6.1, 15.6, 18.4, fill="#c9ced6", stroke=INK, width=0.1, rx=0.3)
            v.text(8.2, 11.5, "Ra-02", size=1.6, weight="bold")
            v.text(8.2, 13.6, "SX1278, shield can", size=1.0)
            for i in range(8):
                v.rect(16.2, 6.4 + i * 2.0, 17.2, 7.4 + i * 2.0, fill=PIN, stroke=INK, width=0.08)
            v.rect(12.0, 19.0, 15.6, 22.0, fill="#ffffff", stroke=INK, width=0.1)
            v.circle(13.8, 20.5, 0.9, fill="#e0b040", stroke=INK, width=0.1)
            v.text(9.5, 20.5, "IPEX", size=1.0, anchor="end")
        else:
            v.text(cx - 1.2, 15.0, "SX1278 LoRa", size=1.4, fill="#ffffff", angle=-90, anchor="middle")
            v.text(cx + 1.0, 15.0, "433MHz v4.0", size=1.2, fill="#ffffff", angle=-90, anchor="middle")
        for n in range(1, 9):
            col, row = (n - 1) // 2, (n - 1) % 2
            x = rb.hdr_x(n)
            y = rb.hdr_y(n)
            v.pin(x, y, str(n), rb.HDR_LABELS[str(n)], square=(n == 1), label_dir=-1 if row == 0 else +1)
        views.append(v)
    return views[0], views[1]


def text_w(chars: int, size: float) -> float:
    """Rough width in mm of a Helvetica string."""
    return chars * size * 0.55


def write_svg(path: pathlib.Path, title: str, boards: list[tuple[list[str], View, View, float, list[str]]]) -> None:
    """boards: (subtitle lines, front view, back view, mm hanging below the
    board drawing, footnote lines) per board.  Layout is a compact grid: one
    column per board, front views in the first row, back views in the
    second."""
    margin, col_gap = 5.0, 6.0
    sub_size, cap_size, note_size, title_size = 1.5, 1.3, 1.0, 1.8
    label_rise = 5.0  # rotated pin names reach this far above a board's top edge
    col_w = [max(f.w, b.w, *(text_w(len(line), sub_size) for line in sub)) for sub, f, b, _, _ in boards]
    notes = [line for *_, ns in boards for n in ns for line in textwrap.wrap(n, 78)]
    n_sub = max(len(sub) for sub, *_ in boards)
    # vertical stack (mm): title, subtitles, [labels + caption] board, hang, [labels + caption] board, hang, notes
    y_title = 1.6
    y_sub0 = y_title + 2.6
    y_front = y_sub0 + (n_sub - 1) * 2.0 + 2.0 + label_rise + 1.5
    hang = max(h for *_, h, _ in boards)
    row1_h = max(f.h for _, f, *_ in boards)
    y_back = y_front + row1_h + hang + label_rise + 2.5
    row2_h = max(b.h for _, _, b, *_ in boards)
    y_notes0 = y_back + row2_h + hang + 1.5
    total_w = (margin * 2 + sum(col_w) + col_gap * (len(boards) - 1)) * S
    total_w = max(total_w, (text_w(len(title), title_size) + 2 * margin) * S, *((text_w(len(n), note_size) + 2 * margin) * S for n in notes))
    total_h = (y_notes0 + 1.5 * len(notes) + 0.5) * S
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_w:.0f}" height="{total_h:.0f}" viewBox="0 0 {total_w:.0f} {total_h:.0f}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{total_w / 2:.1f}" y="{y_title * S:.1f}" font-size="{title_size * S:.1f}" font-family="Helvetica, Arial, sans-serif" font-weight="bold" fill="{INK}" text-anchor="middle" dominant-baseline="middle">{title}</text>',
    ]
    x = (total_w / S - (sum(col_w) + col_gap * (len(boards) - 1))) / 2  # centre the columns under the title
    for (sub, front, back, _, _), w in zip(boards, col_w):
        for i, line in enumerate(sub):
            parts.append(f'<text x="{(x + w / 2) * S:.1f}" y="{(y_sub0 + i * 2.0) * S:.1f}" font-size="{sub_size * S:.1f}" font-family="Helvetica, Arial, sans-serif" font-weight="bold" fill="{INK}" text-anchor="middle" dominant-baseline="middle">{line}</text>')
        parts.append(front.svg_group((x + (w - front.w) / 2) * S, y_front * S, "Front (component side)", label_rise + 1.0, cap_size))
        parts.append(back.svg_group((x + (w - back.w) / 2) * S, y_back * S, "Back (mirrored)", label_rise + 1.0, cap_size))
        x += w + col_gap
    for i, n in enumerate(notes):
        parts.append(f'<text x="{total_w / 2:.1f}" y="{(y_notes0 + 1.5 * i) * S:.1f}" font-size="{note_size * S:.1f}" font-family="Helvetica, Arial, sans-serif" fill="{INK}" text-anchor="middle" dominant-baseline="middle">{n}</text>')
    parts.append("</svg>")
    path.write_text("\n".join(parts) + "\n")
    print(f"wrote {path.relative_to(path.parents[2])}")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    e07 = (["Ebyte E07-M1101D-SMA", "(CC1101)"], *e07_views(), 12.5,
           ["The front view is what the carrier sees. E07-M1101D: pins 1.60 / 4.14 mm from the header edge, columns 3.70 mm from the long edges; pin 1 square. Dimensions from the Ebyte manual."])
    ra02 = (["SX1278 LoRa 433MHz v4.0 breakout", "(Ai-Thinker Ra-02)"], *ra02_views(), 4.0,
            ["Ra-02 breakout: the header is on the back, so the front view sees it through the board. Numbering is this repository's (odd pins outer row, pin 1 left).",
             "Breakout size and offsets measured from photos, +/- 0.3 mm; the Ra-02 module itself from Ai-Thinker's Ra-02 Specifications V1.0."])
    write_svg(OUT / "pinout-radio-boards.svg", "Radio board header pinouts (header edge at the top)", [e07, ra02])


if __name__ == "__main__":
    main()

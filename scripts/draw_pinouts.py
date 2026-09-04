#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Draw pinout diagrams (SVG) of the two socketed radio boards, as seen from
the carrier: component side up with the header edge at the top, plus the
mirrored back view.  Writes docs/images/pinout-e07-m1101d.svg and
docs/images/pinout-ra02-breakout.svg.  Geometry comes from the generators
and the photo measurements recorded there.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import generate_adapters as ga  # noqa: E402
import generate_cc1101 as cc  # noqa: E402

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

    def svg_group(self, ox: float, oy: float, caption: str) -> str:
        w, h = self.w * S, self.h * S
        cap = f'<text x="{w / 2:.1f}" y="{-6.8 * S:.1f}" font-size="{1.4 * S:.1f}" font-family="Helvetica, Arial, sans-serif" font-weight="bold" fill="{INK}" text-anchor="middle">{caption}</text>'
        return f'<g transform="translate({ox:.1f} {oy:.1f})">{cap}\n' + "\n".join(self.items) + "\n</g>"


def board_base(v: View, w: float, h: float) -> None:
    v.rect(0, 0, w, h, fill=BOARD, stroke=BOARD_EDGE, width=0.25, rx=0.6)
    v.text(w / 2, h + 3.0, f"{w:g} x {h:g} mm", size=1.2, fill=INK)


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
        v.rect(W / 2 - 3.2, H, W / 2 + 3.2, H + 6.5, fill="#d9d9d9", stroke=INK, width=0.12, rx=0.5)
        v.circle(W / 2, H + 3.2, 1.6, fill="#ffffff", stroke=INK, width=0.12)
        v.circle(W / 2, H + 3.2, 0.5, fill=PIN, stroke=INK, width=0.08)
        v.text(W / 2, H + 8.0, "SMA jack", size=1.1)
        v.text(W / 2, H - 4.0 if not mirror else H - 4.0, "433M" if not mirror else "E07-M1101D V2.0", size=1.1, fill="#ffffff")
        views.append(v)
    return views[0], views[1]


def ra02_views() -> tuple[View, View]:
    W, H = ga.RA02_W, ga.RA02_H
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
            x = cx - 3 * ga.SM_PITCH / 2 + col * ga.SM_PITCH
            y = ga.RA02_ROW_IN + row * ga.SM_PITCH
            v.pin(x, y, str(n), ga.RA02_LABELS[str(n)], square=(n == 1), label_dir=-1 if row == 0 else +1)
        views.append(v)
    return views[0], views[1]


def write_svg(path: pathlib.Path, title: str, front: View, back: View, notes: list[str]) -> None:
    gap = 10.0  # mm between views
    total_w = (PAD + front.w + gap + back.w + PAD) * S
    total_h = (PAD + max(front.h, back.h) + 11 + 1.6 * len(notes)) * S
    note_svg = "".join(
        f'<text x="{total_w / 2:.1f}" y="{total_h - (1.0 + 1.6 * (len(notes) - 1 - i)) * S:.1f}" font-size="{1.05 * S:.1f}" font-family="Helvetica, Arial, sans-serif" fill="{INK}" text-anchor="middle" dominant-baseline="middle">{n}</text>'
        for i, n in enumerate(notes)
    )
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_w:.0f}" height="{total_h:.0f}" viewBox="0 0 {total_w:.0f} {total_h:.0f}">',
        f'<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{total_w / 2:.1f}" y="{1.2 * S:.1f}" font-size="{1.9 * S:.1f}" font-family="Helvetica, Arial, sans-serif" font-weight="bold" fill="{INK}" text-anchor="middle" dominant-baseline="middle">{title}</text>',
        front.svg_group(PAD * S, PAD * S, "Front (component side)"),
        back.svg_group((PAD + front.w + gap) * S, PAD * S, "Back (mirrored)"),
        note_svg,
        "</svg>",
    ]
    path.write_text("\n".join(parts) + "\n")
    print(f"wrote {path.relative_to(path.parents[2])}")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    f, b = e07_views()
    write_svg(OUT / "pinout-e07-m1101d.svg", "Ebyte E07-M1101D-SMA (CC1101) header pinout", f, b,
              ["Header edge at the top in both views; the front view is what the carrier sees.",
               "Pins 1.60 / 4.14 mm from that edge, columns 3.70 mm from the long edges; pin 1 square."])
    f, b = ra02_views()
    write_svg(OUT / "pinout-ra02-breakout.svg", "SX1278 LoRa 433MHz v4.0 breakout (Ai-Thinker Ra-02) header pinout", f, b,
              ["Header edge at the top in both views; the header itself is on the back, so the front view sees it through the board.",
               "Numbering is this repository's (odd pins outer row, pin 1 left). Size and offsets measured from photos, +/- 0.3 mm."])


if __name__ == "__main__":
    main()

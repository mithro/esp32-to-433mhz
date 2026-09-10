# Case drawings

Mechanical drawings of the printed case for the socket adapter
(`hardware/case/`), for checking a printed part with calipers and as the
starting point for an injection-moulded or machined version. They are
drawn by `scripts/draw_case.py` from `scripts/case_dims.py`, the same
constants `scripts/build_case.py` builds the solids from, so the numbers on
the sheets cannot drift from the model; `uv run scripts/draw_case.py
--check` rebuilds the solids with CadQuery and measures 63 of the quoted
dimensions on them (see [Development](development.md)).

Every sheet is in the adapter's frame: x right, y down from the PCB's
top-left corner, z up from the PCB's top face; the PCB is drawn in green
for reference. The sheets are sized in millimetres (2:1 for the views,
5:1 and 10:1 for the details), so printed at 100 % they lay on the part.
No draft angles are modelled, and the only radii are the R2 vertical
outside corners; each sheet carries a short note block of what a moulding
or machining engineer has to add or decide.

## Sheet 1: bottom half, plan from above

The cavity, the wall and the lip round its top, the four standoffs with
their press-fit pegs (the H3 peg is flush with the PCB), and the two snap
tabs on each long wall with their slots. Hole positions are given from the
outside faces and (green) from the PCB's origin; the section marks A-A,
B-B, C-C and D-D locate the other sheets.

![Bottom half, plan from above](images/case-bottom-plan.svg)

## Sheet 2: top half, plan from below

The top half turned over about its long axis, so +x runs to the left: the
skirt and its rebate, the grooves the bumps click into, the three bored
hold-down bosses over the pegs and the solid one beside H3, the pry notch,
and (hidden) the USB-C window, the antenna hole and the E07 pocket.

![Top half, plan from below](images/case-top-plan.svg)

## Sheet 3: section A-A on the antenna axis

Both halves closed, cut at x = 12.67 (the antenna axis) and laid out like
the plan with z to the right: the floor, seam and ceiling, the halves'
heights, the standoff / peg / boss stack behind the cut, the lip and the
pry notch at the near wall, and the antenna hole and the E07 pocket in the
far wall.

![Section A-A on the antenna axis](images/case-section-antenna.svg)

## Sheet 4: end elevations

The USB-C wall from outside with the window dimensioned from the y = 0
end, the bottom face and the seam, and the antenna wall from outside with
the hole's centre from the USB-C wall face, the bottom face and the seam.

![End elevations: the USB-C wall and the antenna wall](images/case-end-elevations.svg)

## Sheet 5: the snap joint

Section C-C through a tab with the case closed at 10:1 (skirt, rebate,
clearance, tab, bump and groove, and how far the bump stands past the
skirt face), section D-D through the plain lip, and a tab seen from
outside at 5:1 with its slots and the hidden groove behind it.

![Snap joint details](images/case-snap-detail.svg)

## Sheet 6: the peg, PCB and boss stack

Section B-B through hole H1 at 5:1 with every height from the outside
bottom face (floor top, standoff top, PCB top, peg tip, boss face, ceiling,
top face) and the local sizes (standoff, peg and chamfer, PCB hole, bore,
boss, gap), and the same section at H3 where the peg is flush and the
solid boss sits 1 mm beside the hole.

![Peg, PCB and boss stack](images/case-peg-detail.svg)

## How to check a printed part

Measure in this order with 0.01 mm calipers (a depth gauge for the
heights); the expected values are the model's, the tolerance is what a
well-tuned FDM printer holds. Anything outside it points at the printer
(first-layer squish, over-extrusion, shrinkage) before it points at the
model.

| # | Measurement | Expected | Tolerance |
| --- | --- | --- | --- |
| 1 | Each half outside, width x length | 36.20 x 66.70 | +/-0.20 |
| 2 | Bottom half height, bottom face to the seam rim | 8.50 | +/-0.15 |
| 3 | Top half height, top face to the skirt's edge | 12.10 | +/-0.15 |
| 4 | Long wall thickness (bottom half, below the lip) | 2.20 | +/-0.15 |
| 5 | Floor and ceiling (depth gauge from the rim, minus 2 and 3) | 2.00 | +/-0.15 |
| 6 | Cavity, width x length (bottom half, below the lip) | 31.80 x 62.00 | +/-0.20 |
| 7 | Standoff pitch, hole centre to hole centre | 24.20 x 33.20 | +/-0.15 |
| 8 | Standoff height above the floor (depth gauge from the rim: floor 6.50, standoff top 1.10) | 5.40 | +/-0.10 |
| 9 | Peg diameter, below the chamfer | 2.15 | +0.10 / -0.05 |
| 10 | Peg above the standoff (H1, H2, H4); H3 is 1.60 | 2.00 | +/-0.10 |
| 11 | Lip thickness and height above the rim | 0.80 x 1.50 | +/-0.10 |
| 12 | Tab width and height above the rim; pitch between the two tabs | 8.00 x 6.00; 18.00 | +/-0.15 |
| 13 | Tab thickness at the bump (0.80 tab + 0.35 bump) | 1.15 | +/-0.10 |
| 14 | Tab centre from the y = 0 outside face | 34.70 | +/-0.20 |
| 15 | Skirt thickness (top half, at its edge) and between the skirt faces | 1.25; 33.70 | +/-0.10 / +/-0.20 |
| 16 | Rebate depth from the skirt's edge (depth gauge to the step) | 6.30 | +/-0.10 |
| 17 | Groove centre from the y = 0 outside face; groove length | 34.70, 52.70; 9.00 | +/-0.20 |
| 18 | Boss face below the skirt's edge (depth gauge: ceiling 10.10, boss face 0.70) | 0.70 | +/-0.10 |
| 19 | Boss diameter, bore diameter, bore depth | 4.40, 2.60, 2.00 | +/-0.10 |
| 20 | USB-C window, width x height; centre from the y = 0 face; sill above the skirt's edge | 13.00 x 7.50; 17.30; 1.85 | +/-0.20 |
| 21 | Antenna hole diameter; centre from the USB-C wall face; centre above the skirt's edge | 6.60; 17.17; 3.80 | +0.10 / -0.20; +/-0.20 |
| 22 | E07 pocket, square and depth | 7.40; 0.60 | +/-0.15 |
| 23 | Pry notch, width and depth into the skirt | 10.00 x 1.20 | +/-0.20 |
| 24 | Function: the PCB presses onto the pegs by hand and sits flat on the standoffs; the halves close with no gap at the seam and all four tabs click; the E07's jack, or the pigtail's bulkhead, passes the hole | - | - |

The snap fit (bump 0.35 into a 0.42 groove with 0.15 clearance) cannot be
measured with calipers; if the halves rattle or will not click, check 11,
13 and 16 first. FDM holes print small and pegs print large, which is why
the peg is drawn at 2.15 for a 2.20 hole: if the pegs will not go in, a
touch with a 2.2 mm drill in the PCB is better than shaving the peg.

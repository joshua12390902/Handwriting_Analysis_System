# Jetson Nano + C922 Adjustable Mount

Modular 3D-printable mount for:
- Jetson Nano Developer Kit board
- Rear mast behind the Nano
- Stackable height-adjustable mast
- Flat camera platform for a Logitech C922 clip

## Current Design

- Mast outer profile: `65 x 30 mm`
- Mast segment height: `50 mm`
- Nano tray usable area: `102 x 82 mm`
- Open rear cable channel in `mast_base` and `mast_segment_50mm`
- `camera_head` with recessed C922 clip channel and tail notch

## Joinery

This version tightened the mast joinery and reduced the base-foot footprint.

- Peg: `48 x 19 x 12 mm`
- Socket inner size: `49 x 20 x 12 mm`
- Effective clearance: `0.5 mm` per side

This is tighter than the previous version and should fit better for FDM printing.

## Assembly Footprint Change

- Rear pad on `jetson_nano_base`: `99 x 38 mm`
- `mast_base` foot: `97 x 36 mm`

This leaves about `1 mm` margin per side so the base seats more easily and is less sensitive to elephant foot.

## STL Files

- `jetson_nano_base.stl`
- `mast_base.stl`
- `mast_segment_50mm.stl`
- `camera_head.stl`

## Verified STL Extents

- `jetson_nano_base.stl`: `126 x 136 x 28 mm`
- `mast_base.stl`: `97 x 36 x 36 mm`
- `mast_segment_50mm.stl`: `65 x 30 x 50 mm`
- `camera_head.stl`: `65 x 150 x 26 mm`

All four STLs were regenerated and checked as watertight.

## Nano Tray

The tray is sized around a `100 x 80 mm` Jetson Nano Developer Kit board envelope with about `2 mm` total clearance in each direction.

- Board envelope: `100 x 80 mm`
- Tray usable area: `102 x 82 mm`

Low ledges lift the board so underside components do not scrape the tray.

## Printing Notes

Recommended starting profile for structural parts:

- Material: `PETG`
- Layer height: `0.20 mm`
- First layer: `0.20 mm`
- Walls: `4`
- Top / bottom layers: `5`
- Infill: `30%`

Support is mainly needed for `camera_head.stl`.

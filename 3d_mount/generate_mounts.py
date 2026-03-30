#!/usr/bin/env python3
"""
Generate printable STL parts for a modular Jetson Nano + Logitech C922 rig.

Parts:
- jetson_nano_base.stl
- mast_base.stl
- mast_segment_50mm.stl
- camera_head.stl

The mast is height-adjustable by stacking more mast_segment_50mm parts.
"""
from __future__ import annotations

import math
import struct
from pathlib import Path
from typing import Set, Tuple


STEP = 0.5  # mm grid

Voxel = Tuple[int, int, int]
Box = Tuple[int, int, int, int, int, int]

# Shared joinery dimensions. These are used consistently across:
# jetson_nano_base -> mast_base -> mast_segment -> camera_head
# Current fit target is about 0.5 mm clearance per side.
PEG_X = 48
PEG_Y = 19
PEG_H = 12

SOCKET_INNER_X = 49
SOCKET_INNER_Y = 20
SOCKET_H = 12

PROFILE_X = 65
PROFILE_Y = 30

SEGMENT_TOTAL_H = 50
SEGMENT_BODY_H = SEGMENT_TOTAL_H - SOCKET_H - PEG_H

TRAY_INNER_X = 102
TRAY_INNER_Y = 82
WALL_THICK = 4          # frame wall thickness around the tray
WALL_H = 6              # wall height above tray floor
TRAY_FLOOR = 3          # tray floor thickness
REAR_GAP = 4


def _check_step(v: int) -> int:
    steps = round(v / STEP)
    if abs((steps * STEP) - v) > 1e-9:
        raise ValueError(f"value {v} must be a multiple of {STEP}")
    return int(steps)


def add_box(occ: Set[Voxel], box: Box) -> None:
    x0, y0, z0, x1, y1, z1 = box
    gx0, gy0, gz0 = _check_step(x0), _check_step(y0), _check_step(z0)
    gx1, gy1, gz1 = _check_step(x1), _check_step(y1), _check_step(z1)
    for x in range(gx0, gx1):
        for y in range(gy0, gy1):
            for z in range(gz0, gz1):
                occ.add((x, y, z))


def remove_box(occ: Set[Voxel], box: Box) -> None:
    x0, y0, z0, x1, y1, z1 = box
    gx0, gy0, gz0 = _check_step(x0), _check_step(y0), _check_step(z0)
    gx1, gy1, gz1 = _check_step(x1), _check_step(y1), _check_step(z1)
    for x in range(gx0, gx1):
        for y in range(gy0, gy1):
            for z in range(gz0, gz1):
                occ.discard((x, y, z))


def add_socket_walls(
    occ: Set[Voxel],
    x0: int,
    y0: int,
    z0: int,
    outer_x: int,
    outer_y: int,
    h: int,
    inner_x: int,
    inner_y: int,
) -> None:
    wall_x = (outer_x - inner_x) / 2
    wall_y = (outer_y - inner_y) / 2
    add_box(occ, (x0, y0, z0, x0 + outer_x, y0 + wall_y, z0 + h))
    add_box(occ, (x0, y0 + outer_y - wall_y, z0, x0 + outer_x, y0 + outer_y, z0 + h))
    add_box(occ, (x0, y0 + wall_y, z0, x0 + wall_x, y0 + outer_y - wall_y, z0 + h))
    add_box(occ, (x0 + outer_x - wall_x, y0 + wall_y, z0, x0 + outer_x, y0 + outer_y - wall_y, z0 + h))


def add_mast_peg(occ: Set[Voxel], x0: int, y0: int, z0: int) -> None:
    add_box(occ, (x0, y0, z0, x0 + PEG_X, y0 + PEG_Y, z0 + PEG_H))


def add_mast_socket(occ: Set[Voxel], x0: int, y0: int, z0: int) -> None:
    add_socket_walls(
        occ,
        x0,
        y0,
        z0,
        outer_x=PROFILE_X,
        outer_y=PROFILE_Y,
        h=SOCKET_H,
        inner_x=SOCKET_INNER_X,
        inner_y=SOCKET_INNER_Y,
    )


def centered_peg_xy(outer_x: int, outer_y: int) -> tuple[int, int]:
    return ((outer_x - PEG_X) / 2, (outer_y - PEG_Y) / 2)


def centered_socket_xy(outer_x: int, outer_y: int) -> tuple[int, int]:
    return ((outer_x - PROFILE_X) / 2, (outer_y - PROFILE_Y) / 2)


def centered_socket_cavity_xy(outer_x: int, outer_y: int) -> tuple[int, int]:
    return ((outer_x - SOCKET_INNER_X) / 2, (outer_y - SOCKET_INNER_Y) / 2)


def carve_mast_socket(occ: Set[Voxel], x0: int, y0: int, z0: int) -> None:
    remove_box(occ, (x0, y0, z0, x0 + SOCKET_INNER_X, y0 + SOCKET_INNER_Y, z0 + SOCKET_H))


def carve_cable_channel(
    occ: Set[Voxel],
    outer_x: int,
    outer_y: int,
    z0: int,
    z1: int,
    channel_w: int = 10,
    channel_d: int = 8,
    x_offset: int = 0,
    y_offset: int = 0,
) -> None:
    """Open-backed wire channel running along the mast body."""
    cx0 = (outer_x - channel_w) / 2
    cx1 = cx0 + channel_w
    cy0 = outer_y - channel_d
    remove_box(occ, (x_offset + cx0, y_offset + cy0, z0, x_offset + cx1, y_offset + outer_y, z1))


def build_nano_base() -> Set[Voxel]:
    occ: Set[Voxel] = set()

    # Overall outer dimensions: inner tray + walls on each side
    SKIRT = 2  # bottom plate extends this much beyond walls on each side
    base_x = TRAY_INNER_X + WALL_THICK * 2       # 102 + 8 = 110
    base_y_tray = TRAY_INNER_Y + WALL_THICK * 2  # 82 + 8 = 90
    total_wall_h = TRAY_FLOOR + WALL_H            # 3 + 6 = 9

    # Rear pad for mast connection (behind tray)
    pad_x = 99
    pad_y = 38
    base_y = base_y_tray + REAR_GAP + pad_y  # 90 + 4 + 38 = 132

    # 1) Bottom plate — slightly larger than frame (skirt)
    floor_x = base_x + SKIRT * 2   # 114
    floor_y = base_y + SKIRT * 2   # 136
    add_box(occ, (-SKIRT, -SKIRT, 0, base_x + SKIRT, base_y + SKIRT, TRAY_FLOOR))

    # 2) Walls around the tray (outer frame, from floor to total_wall_h)
    tray_x0 = WALL_THICK                        # 4
    tray_x1 = WALL_THICK + TRAY_INNER_X         # 106
    tray_y0 = WALL_THICK                         # 4
    tray_y1 = WALL_THICK + TRAY_INNER_Y         # 86

    # Build walls: left, right, rear (no full front wall — leave open for wiring)
    # Left wall
    add_box(occ, (0, 0, TRAY_FLOOR, tray_x0, base_y_tray, total_wall_h))
    # Right wall
    add_box(occ, (tray_x1, 0, TRAY_FLOOR, base_x, base_y_tray, total_wall_h))
    # Rear wall
    add_box(occ, (tray_x0, tray_y1, TRAY_FLOOR, tray_x1, base_y_tray, total_wall_h))

    # Front: two small tabs (10mm wide x 0.5mm deep x 1mm tall)
    tab_w = 10
    tab_d = 0.5
    tab_h = 1
    # Left tab
    add_box(occ, (tray_x0, 0, TRAY_FLOOR, tray_x0 + tab_w, tab_d, TRAY_FLOOR + tab_h))
    # Right tab
    add_box(occ, (tray_x1 - tab_w, 0, TRAY_FLOOR, tray_x1, tab_d, TRAY_FLOOR + tab_h))

    # 3) Raised rear pad for mast base peg (centered behind tray area)
    pad_x0 = (base_x - pad_x) / 2
    pad_y0 = base_y_tray + REAR_GAP
    pad_z0 = total_wall_h
    add_box(occ, (pad_x0, pad_y0, TRAY_FLOOR, pad_x0 + pad_x, pad_y0 + pad_y, pad_z0 + 8))

    # 4) Male tenon for the mast base
    peg_x, peg_y = centered_peg_xy(pad_x, pad_y)
    add_mast_peg(occ, pad_x0 + peg_x, pad_y0 + peg_y, pad_z0 + 8)

    return occ


def build_mast_base() -> Set[Voxel]:
    occ: Set[Voxel] = set()

    # Keep the foot slightly smaller than the rear pad on jetson_nano_base
    # so it seats cleanly even with a little elephant foot from printing.
    foot_x = 97
    foot_y = 36
    foot_h = SOCKET_H
    peg_z0 = 24
    brace_z1 = peg_z0 + PEG_H

    add_box(occ, (0, 0, 0, foot_x, foot_y, foot_h))

    # Bottom mortise that matches the male tenon on jetson_nano_base.
    socket_x, socket_y = centered_socket_cavity_xy(foot_x, foot_y)
    carve_mast_socket(occ, socket_x, socket_y, 0)

    # Pedestal body.
    body_x0 = (foot_x - PROFILE_X) / 2
    body_x1 = body_x0 + PROFILE_X
    add_box(occ, (body_x0, 0, foot_h, body_x1, foot_y, peg_z0))
    add_box(occ, (body_x0 - 4, 0, foot_h, body_x1 + 4, 6, brace_z1))
    add_box(occ, (body_x0 - 4, foot_y - 6, foot_h, body_x1 + 4, foot_y, brace_z1))

    # Open-backed cable channel.
    carve_cable_channel(occ, PROFILE_X, foot_y, foot_h + STEP, brace_z1, x_offset=body_x0, y_offset=0)

    # Top tenon for the first mast segment — center peg in PROFILE footprint
    # so it aligns with mast_segment's socket (centered in PROFILE_X x PROFILE_Y).
    peg_x, peg_y = centered_peg_xy(PROFILE_X, PROFILE_Y)
    body_y0 = (foot_y - PROFILE_Y) / 2
    add_mast_peg(occ, body_x0 + peg_x, body_y0 + peg_y, peg_z0)
    return occ


def build_mast_segment() -> Set[Voxel]:
    occ: Set[Voxel] = set()

    # Solid outer body.
    add_box(occ, (0, 0, 0, PROFILE_X, PROFILE_Y, SOCKET_H + SEGMENT_BODY_H))

    # Lower female socket.
    socket_x, socket_y = centered_socket_cavity_xy(PROFILE_X, PROFILE_Y)
    carve_mast_socket(occ, socket_x, socket_y, 0)

    # Upper male peg.
    peg_x, peg_y = centered_peg_xy(PROFILE_X, PROFILE_Y)
    add_mast_peg(occ, peg_x, peg_y, SOCKET_H + SEGMENT_BODY_H)

    # Open-backed cable channel through the body section.
    carve_cable_channel(occ, PROFILE_X, PROFILE_Y, SOCKET_H, SOCKET_H + SEGMENT_BODY_H)

    return occ


def build_camera_head() -> Set[Voxel]:
    occ: Set[Voxel] = set()

    # C922 clip-arm dimensions (user-measured, converted to mm).
    CLIP_LEN = 51      # 2 in
    CLIP_W = 42         # 1.65 in
    BUMP_H = 6.5        # 0.25 in protrusion

    clearance = 1       # mm per side

    # Heights.
    body_top = SOCKET_H + 10   # 22
    boom_top = SOCKET_H + 14   # 26

    # Socket + body block.
    add_box(occ, (0, 0, 0, PROFILE_X, PROFILE_Y, body_top))
    socket_x, socket_y = centered_socket_cavity_xy(PROFILE_X, PROFILE_Y)
    carve_mast_socket(occ, socket_x, socket_y, 0)

    # Boom extending in +Y (away from the Nano board).
    boom_ext = 67
    boom_y1 = PROFILE_Y + boom_ext  # 105
    add_box(occ, (0, 0, SOCKET_H, PROFILE_X, boom_y1, boom_top))

    # Camera platform (full profile width; raised edges guide the clip arm).
    plat_len = CLIP_LEN + clearance * 2  # 53
    plat_y0 = boom_y1                    # 105
    plat_y1 = plat_y0 + plat_len         # 158
    add_box(occ, (0, plat_y0, SOCKET_H, PROFILE_X, plat_y1, boom_top))

    # Recessed channel for the folded clip arm.
    recess_w = CLIP_W + clearance * 2  # 44
    recess_depth = 3
    channel_x0 = (PROFILE_X - recess_w) / 2  # 10.5
    remove_box(occ, (channel_x0, plat_y0, boom_top - recess_depth,
                      channel_x0 + recess_w, plat_y1, boom_top))

    # Notch for rubber bump near the boom end (clip arm folds back from
    # the far edge where the camera body hangs).
    # Same X center as the recess channel for perfect alignment.
    notch_w = 44        # match recess width
    notch_len = 3       # ~0.12 in – tight snap fit
    notch_y0 = plat_y0 + clearance
    remove_box(occ, (channel_x0, notch_y0, boom_top - recess_depth - BUMP_H,
                      channel_x0 + notch_w, notch_y0 + notch_len, boom_top - recess_depth))

    return occ


def _face_tris(x: float, y: float, z: float, dx: float, dy: float, dz: float):
    return {
        "+x": [
            ((x + dx, y, z), (x + dx, y + dy, z), (x + dx, y + dy, z + dz)),
            ((x + dx, y, z), (x + dx, y + dy, z + dz), (x + dx, y, z + dz)),
        ],
        "-x": [
            ((x, y, z), (x, y, z + dz), (x, y + dy, z + dz)),
            ((x, y, z), (x, y + dy, z + dz), (x, y + dy, z)),
        ],
        "+y": [
            ((x, y + dy, z), (x, y + dy, z + dz), (x + dx, y + dy, z + dz)),
            ((x, y + dy, z), (x + dx, y + dy, z + dz), (x + dx, y + dy, z)),
        ],
        "-y": [
            ((x, y, z), (x + dx, y, z), (x + dx, y, z + dz)),
            ((x, y, z), (x + dx, y, z + dz), (x, y, z + dz)),
        ],
        "+z": [
            ((x, y, z + dz), (x + dx, y, z + dz), (x + dx, y + dy, z + dz)),
            ((x, y, z + dz), (x + dx, y + dy, z + dz), (x, y + dy, z + dz)),
        ],
        "-z": [
            ((x, y, z), (x, y + dy, z), (x + dx, y + dy, z)),
            ((x, y, z), (x + dx, y + dy, z), (x + dx, y, z)),
        ],
    }


def _normal(a, b, c):
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    nx = uy * vz - uz * vy
    ny = uz * vx - ux * vz
    nz = ux * vy - uy * vx
    length = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
    return (nx / length, ny / length, nz / length)


def write_binary_stl(occ: Set[Voxel], path: Path) -> None:
    triangles = []
    for x, y, z in occ:
        px, py, pz = x * STEP, y * STEP, z * STEP
        neighbors = {
            "+x": (x + 1, y, z),
            "-x": (x - 1, y, z),
            "+y": (x, y + 1, z),
            "-y": (x, y - 1, z),
            "+z": (x, y, z + 1),
            "-z": (x, y, z - 1),
        }
        for face, neighbor in neighbors.items():
            if neighbor in occ:
                continue
            for tri in _face_tris(px, py, pz, STEP, STEP, STEP)[face]:
                triangles.append(tri)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        header = b"Jetson Nano + C922 modular mount".ljust(80, b"\0")
        f.write(header)
        f.write(struct.pack("<I", len(triangles)))
        for a, b, c in triangles:
            n = _normal(a, b, c)
            f.write(struct.pack("<3f", *n))
            f.write(struct.pack("<3f", *a))
            f.write(struct.pack("<3f", *b))
            f.write(struct.pack("<3f", *c))
            f.write(struct.pack("<H", 0))


def main() -> None:
    out_dir = Path(__file__).resolve().parent
    parts = {
        "jetson_nano_base.stl": build_nano_base(),
        "mast_base.stl": build_mast_base(),
        "mast_segment_50mm.stl": build_mast_segment(),
        "camera_head.stl": build_camera_head(),
    }
    for name, occ in parts.items():
        write_binary_stl(occ, out_dir / name)
        print(f"Wrote {name}")


if __name__ == "__main__":
    main()

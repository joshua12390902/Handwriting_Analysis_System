#!/usr/bin/env python3
"""
Generate printable STL parts for a modular Jetson Nano + Logitech C922 rig.

Parts:
- jetson_nano_base.stl
- mast_segment_80mm.stl
- camera_head.stl

The mast is height-adjustable by stacking more mast_segment_80mm parts.

Geometry engine: axis-aligned box CSG with adaptive coordinate grid.
Instead of filling millions of tiny voxels, we record box add/remove
operations and resolve them on a coarse grid at STL-export time.
"""
from __future__ import annotations

import bisect
import math
import struct
from pathlib import Path
from typing import List, Tuple

Box = Tuple[float, float, float, float, float, float]
Ops = List[Tuple[Box, bool]]

# Shared joinery dimensions. These are used consistently across:
# jetson_nano_base -> mast_segment -> camera_head.
PEG_X = 48.8
PEG_Y = 19.8
PEG_H = 16

SOCKET_INNER_X = 49.0
SOCKET_INNER_Y = 20.0
SOCKET_H = 17
SOCKET_Z_RELIEF = 0.5
SOCKET_ENTRY_EXTRA = 1.0
SOCKET_ENTRY_H = 1.0

PROFILE_X = 66
PROFILE_Y = 30

CHANNEL_W = 10
CHANNEL_D = 8
# Cable clip dimensions.
CLIP_WALL_T = 2.0
CLIP_ARM_LEN = 10.0
CLIP_GAP = 5.0
CLIP_LIP_INWARD = 2.0
CLIP_WIDTH = 8.0
CLIP_EDGE_MARGIN = 2.0

SEGMENT_TOTAL_H = 80
SEGMENT_BODY_H = SEGMENT_TOTAL_H - SOCKET_H - PEG_H

TRAY_INNER_X = 102
TRAY_INNER_Y = 82
WALL_THICK = 4          # frame wall thickness around the tray
WALL_H = 10             # wall height above tray floor
TRAY_FLOOR = 3          # tray floor thickness
REAR_GAP = 4


# ---------------------------------------------------------------------------
# CSG primitives — record operations, don't fill voxels
# ---------------------------------------------------------------------------

def add_box(occ: Ops, box: Box) -> None:
    x0, y0, z0, x1, y1, z1 = box
    occ.append(((x0, y0, z0, x1, y1, z1), True))


def remove_box(occ: Ops, box: Box) -> None:
    x0, y0, z0, x1, y1, z1 = box
    occ.append(((x0, y0, z0, x1, y1, z1), False))


# ---------------------------------------------------------------------------
# Geometry helpers (unchanged logic, updated type hints)
# ---------------------------------------------------------------------------

def add_socket_walls(
    occ: Ops,
    x0: float,
    y0: float,
    z0: float,
    outer_x: float,
    outer_y: float,
    h: float,
    inner_x: float,
    inner_y: float,
) -> None:
    wall_x = (outer_x - inner_x) / 2
    wall_y = (outer_y - inner_y) / 2
    add_box(occ, (x0, y0, z0, x0 + outer_x, y0 + wall_y, z0 + h))
    add_box(occ, (x0, y0 + outer_y - wall_y, z0, x0 + outer_x, y0 + outer_y, z0 + h))
    add_box(occ, (x0, y0 + wall_y, z0, x0 + wall_x, y0 + outer_y - wall_y, z0 + h))
    add_box(occ, (x0 + outer_x - wall_x, y0 + wall_y, z0, x0 + outer_x, y0 + outer_y - wall_y, z0 + h))


def add_mast_peg(occ: Ops, x0: float, y0: float, z0: float) -> None:
    add_box(occ, (x0, y0, z0, x0 + PEG_X, y0 + PEG_Y, z0 + PEG_H))


def add_mast_socket(occ: Ops, x0: float, y0: float, z0: float) -> None:
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


def centered_peg_xy(outer_x: float, outer_y: float) -> tuple[float, float]:
    return ((outer_x - PEG_X) / 2, (outer_y - PEG_Y) / 2)


def centered_socket_xy(outer_x: float, outer_y: float) -> tuple[float, float]:
    return ((outer_x - PROFILE_X) / 2, (outer_y - PROFILE_Y) / 2)


def centered_socket_cavity_xy(outer_x: float, outer_y: float) -> tuple[float, float]:
    return ((outer_x - SOCKET_INNER_X) / 2, (outer_y - SOCKET_INNER_Y) / 2)


def carve_mast_socket(occ: Ops, x0: float, y0: float, z0: float) -> None:
    remove_box(
        occ,
        (
            x0,
            y0,
            z0,
            x0 + SOCKET_INNER_X,
            y0 + SOCKET_INNER_Y,
            z0 + SOCKET_H + SOCKET_Z_RELIEF,
        ),
    )
    relief_x0 = x0 - (SOCKET_ENTRY_EXTRA / 2)
    relief_y0 = y0 - (SOCKET_ENTRY_EXTRA / 2)
    remove_box(
        occ,
        (
            relief_x0,
            relief_y0,
            z0,
            relief_x0 + SOCKET_INNER_X + SOCKET_ENTRY_EXTRA,
            relief_y0 + SOCKET_INNER_Y + SOCKET_ENTRY_EXTRA,
            z0 + SOCKET_ENTRY_H,
        ),
    )


def carve_peg_cable_notch(
    occ: Ops,
    x0: float,
    y0: float,
    z0: float,
    channel_w: float = CHANNEL_W,
    channel_d: float = CHANNEL_D,
) -> None:
    """Open a rear notch through the peg so cable routing survives stacked joints."""
    cx0 = x0 + ((PEG_X - channel_w) / 2)
    cy0 = y0 + PEG_Y - channel_d
    remove_box(occ, (cx0, cy0, z0, cx0 + channel_w, y0 + PEG_Y, z0 + PEG_H))


def carve_cable_channel(
    occ: Ops,
    outer_x: float,
    outer_y: float,
    z0: float,
    z1: float,
    channel_w: float = CHANNEL_W,
    channel_d: float = CHANNEL_D,
    x_offset: float = 0,
    y_offset: float = 0,
) -> None:
    """Open-backed wire channel running along the mast body, from z0 to z1."""
    cx0 = (outer_x - channel_w) / 2
    cx1 = cx0 + channel_w
    cy0 = outer_y - channel_d
    remove_box(occ, (x_offset + cx0, y_offset + cy0, z0, x_offset + cx1, y_offset + outer_y, z1))


def carve_socket_cable_slot(
    occ: Ops,
    outer_x: float,
    outer_y: float,
    z0: float,
    channel_w: float = CHANNEL_W,
) -> None:
    """Cut a slot through the rear wall of a socket so cables can pass through."""
    cx0 = (outer_x - channel_w) / 2
    cx1 = cx0 + channel_w
    wall_y = (outer_y - SOCKET_INNER_Y) / 2
    remove_box(occ, (cx0, outer_y - wall_y, z0, cx1, outer_y, z0 + SOCKET_H + SOCKET_Z_RELIEF))


def add_cable_clip(
    occ: Ops,
    outer_x: float,
    outer_y: float,
    z0: float,
    x_offset: float = 0,
    y_offset: float = 0,
) -> None:
    """Add a side-mounted cable clip on the right wall of the body."""
    clip_z0 = z0
    clip_z1 = z0 + CLIP_WIDTH
    total_y = CLIP_WALL_T + CLIP_GAP + CLIP_WALL_T

    clip_y1 = y_offset + outer_y - CLIP_EDGE_MARGIN
    clip_y0 = clip_y1 - total_y

    body_wall_x = x_offset + outer_x
    clip_x1 = body_wall_x + CLIP_ARM_LEN

    # Body-side spine on the right wall.
    add_box(occ, (body_wall_x, clip_y0, clip_z0,
                  body_wall_x + CLIP_WALL_T, clip_y1, clip_z1))

    # Lower arm.
    add_box(occ, (body_wall_x, clip_y0, clip_z0,
                  clip_x1, clip_y0 + CLIP_WALL_T, clip_z1))

    # Upper arm.
    add_box(occ, (body_wall_x, clip_y1 - CLIP_WALL_T, clip_z0,
                  clip_x1, clip_y1, clip_z1))

    # Retention lip on the outer tip.
    lip_x0 = clip_x1 - CLIP_WALL_T
    lip_y0 = clip_y1 - CLIP_WALL_T - CLIP_LIP_INWARD
    add_box(occ, (lip_x0, lip_y0, clip_z0,
                  clip_x1, clip_y1 - CLIP_WALL_T, clip_z1))


# ---------------------------------------------------------------------------
# Part builders (unchanged logic)
# ---------------------------------------------------------------------------

def build_nano_base() -> Ops:
    occ: Ops = []

    SKIRT = 2
    base_x = TRAY_INNER_X + WALL_THICK * 2
    base_y_tray = TRAY_INNER_Y + WALL_THICK * 2
    total_wall_h = TRAY_FLOOR + WALL_H

    pad_x = 100
    pad_y = 38
    base_y = base_y_tray + REAR_GAP + pad_y

    # 1) Bottom plate
    add_box(occ, (-SKIRT, -SKIRT, 0, base_x + SKIRT, base_y + SKIRT, TRAY_FLOOR))

    # 2) Walls around the tray
    tray_x0 = WALL_THICK
    tray_x1 = WALL_THICK + TRAY_INNER_X
    tray_y0 = WALL_THICK
    tray_y1 = WALL_THICK + TRAY_INNER_Y

    # Left wall
    add_box(occ, (0, 0, TRAY_FLOOR, tray_x0, base_y_tray, total_wall_h))
    # Right wall
    add_box(occ, (tray_x1, 0, TRAY_FLOOR, base_x, base_y_tray, total_wall_h))
    # Rear wall
    add_box(occ, (tray_x0, tray_y1, TRAY_FLOOR, tray_x1, base_y_tray, total_wall_h))

    # Front: two small tabs
    tab_w = 10
    tab_d = 0.5
    tab_h = 3
    add_box(occ, (tray_x0, 0, TRAY_FLOOR, tray_x0 + tab_w, tab_d, TRAY_FLOOR + tab_h))
    add_box(occ, (tray_x1 - tab_w, 0, TRAY_FLOOR, tray_x1, tab_d, TRAY_FLOOR + tab_h))

    # 3) Raised rear pad
    pad_x0 = (base_x - pad_x) / 2
    pad_y0 = base_y_tray + REAR_GAP
    pad_z0 = total_wall_h
    add_box(occ, (pad_x0, pad_y0, TRAY_FLOOR, pad_x0 + pad_x, pad_y0 + pad_y, pad_z0 + 8))

    # 4) Male tenon
    peg_x, peg_y = centered_peg_xy(pad_x, pad_y)
    peg_x0 = pad_x0 + peg_x
    peg_y0 = pad_y0 + peg_y
    peg_z0 = pad_z0 + 8
    add_mast_peg(occ, peg_x0, peg_y0, peg_z0)

    return occ


def _legacy_build_mast_base() -> Ops:
    occ: Ops = []

    foot_x = 98
    foot_y = 36
    foot_h = SOCKET_H
    pedestal_h = 12
    peg_z0 = foot_h + pedestal_h

    add_box(occ, (0, 0, 0, foot_x, foot_y, foot_h))

    socket_x, socket_y = centered_socket_cavity_xy(foot_x, foot_y)
    carve_mast_socket(occ, socket_x, socket_y, 0)
    body_x0 = (foot_x - PROFILE_X) / 2
    body_x1 = body_x0 + PROFILE_X
    body_y0 = (foot_y - PROFILE_Y) / 2
    body_y1 = body_y0 + PROFILE_Y
    add_box(occ, (body_x0, body_y0, foot_h, body_x1, body_y1, peg_z0))

    peg_x, peg_y = centered_peg_xy(PROFILE_X, PROFILE_Y)
    peg_x0 = body_x0 + peg_x
    peg_y0 = body_y0 + peg_y
    add_mast_peg(occ, peg_x0, peg_y0, peg_z0)
    return occ


def build_mast_segment() -> Ops:
    occ: Ops = []

    # Solid outer body.
    add_box(occ, (0, 0, 0, PROFILE_X, PROFILE_Y, SOCKET_H + SEGMENT_BODY_H))

    # Lower female socket.
    socket_x, socket_y = centered_socket_cavity_xy(PROFILE_X, PROFILE_Y)
    carve_mast_socket(occ, socket_x, socket_y, 0)

    # Upper male peg.
    peg_x, peg_y = centered_peg_xy(PROFILE_X, PROFILE_Y)
    peg_z0 = SOCKET_H + SEGMENT_BODY_H
    add_mast_peg(occ, peg_x, peg_y, peg_z0)

    # Back-mounted cable hooks.
    add_cable_clip(occ, PROFILE_X, PROFILE_Y, SOCKET_H + 4)
    add_cable_clip(occ, PROFILE_X, PROFILE_Y, SOCKET_H + 16)

    return occ


def build_camera_head() -> Ops:
    occ: Ops = []

    CLIP_LEN = 51
    CLIP_W = 42
    BUMP_H = 6.5

    clearance = 1

    body_top = SOCKET_H + 10
    boom_top = SOCKET_H + 14

    # Socket + body block.
    add_box(occ, (0, 0, 0, PROFILE_X, PROFILE_Y, body_top))
    socket_x, socket_y = centered_socket_cavity_xy(PROFILE_X, PROFILE_Y)
    carve_mast_socket(occ, socket_x, socket_y, 0)

    # Boom extending in +Y.
    boom_ext = 67
    boom_y1 = PROFILE_Y + boom_ext
    add_box(occ, (0, 0, SOCKET_H, PROFILE_X, boom_y1, boom_top))

    # Back-mounted cable hook on the boom body.
    add_cable_clip(occ, PROFILE_X, boom_y1, SOCKET_H + 2)

    # Camera platform.
    plat_len = CLIP_LEN + clearance * 2
    plat_y0 = boom_y1
    plat_y1 = plat_y0 + plat_len
    add_box(occ, (0, plat_y0, SOCKET_H, PROFILE_X, plat_y1, boom_top))

    # Recessed channel for the folded clip arm.
    recess_w = CLIP_W + clearance * 2
    recess_depth = 3
    channel_x0 = (PROFILE_X - recess_w) / 2
    remove_box(occ, (channel_x0, plat_y0, boom_top - recess_depth,
                      channel_x0 + recess_w, plat_y1, boom_top))

    # Notch for rubber bump.
    notch_w = 44
    notch_len = 3
    notch_y0 = plat_y0 + clearance
    remove_box(occ, (channel_x0, notch_y0, boom_top - recess_depth - BUMP_H,
                      channel_x0 + notch_w, notch_y0 + notch_len, boom_top - recess_depth))

    return occ


# ---------------------------------------------------------------------------
# STL generation — adaptive coordinate grid (replaces voxel approach)
# ---------------------------------------------------------------------------

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


def _round_coord(v: float) -> float:
    """Round to 4 decimal places to avoid floating-point dust."""
    return round(v, 4)


def write_binary_stl(occ: Ops, path: Path) -> None:
    if not occ:
        return

    # --- Step 1: Collect unique coordinates from all box boundaries ---
    xs_set: set[float] = set()
    ys_set: set[float] = set()
    zs_set: set[float] = set()
    for (x0, y0, z0, x1, y1, z1), _ in occ:
        xs_set.update((_round_coord(x0), _round_coord(x1)))
        ys_set.update((_round_coord(y0), _round_coord(y1)))
        zs_set.update((_round_coord(z0), _round_coord(z1)))
    xs = sorted(xs_set)
    ys = sorted(ys_set)
    zs = sorted(zs_set)

    nx, ny, nz = len(xs) - 1, len(ys) - 1, len(zs) - 1

    # --- Step 2: Build solid grid ---
    # grid[ix][iy][iz] = True if cell is solid
    grid = [[[False] * nz for _ in range(ny)] for _ in range(nx)]

    for (bx0, by0, bz0, bx1, by1, bz1), is_add in occ:
        bx0, by0, bz0 = _round_coord(bx0), _round_coord(by0), _round_coord(bz0)
        bx1, by1, bz1 = _round_coord(bx1), _round_coord(by1), _round_coord(bz1)
        ix0 = bisect.bisect_left(xs, bx0)
        ix1 = bisect.bisect_left(xs, bx1)
        iy0 = bisect.bisect_left(ys, by0)
        iy1 = bisect.bisect_left(ys, by1)
        iz0 = bisect.bisect_left(zs, bz0)
        iz1 = bisect.bisect_left(zs, bz1)
        for ix in range(ix0, ix1):
            for iy in range(iy0, iy1):
                for iz in range(iz0, iz1):
                    grid[ix][iy][iz] = is_add

    # --- Step 3: Extract surface triangles ---
    triangles: list[tuple] = []
    for ix in range(nx):
        for iy in range(ny):
            for iz in range(nz):
                if not grid[ix][iy][iz]:
                    continue
                cx0, cx1 = xs[ix], xs[ix + 1]
                cy0, cy1 = ys[iy], ys[iy + 1]
                cz0, cz1 = zs[iz], zs[iz + 1]
                faces = _face_tris(cx0, cy0, cz0,
                                   cx1 - cx0, cy1 - cy0, cz1 - cz0)

                if ix + 1 >= nx or not grid[ix + 1][iy][iz]:
                    triangles.extend(faces["+x"])
                if ix == 0 or not grid[ix - 1][iy][iz]:
                    triangles.extend(faces["-x"])
                if iy + 1 >= ny or not grid[ix][iy + 1][iz]:
                    triangles.extend(faces["+y"])
                if iy == 0 or not grid[ix][iy - 1][iz]:
                    triangles.extend(faces["-y"])
                if iz + 1 >= nz or not grid[ix][iy][iz + 1]:
                    triangles.extend(faces["+z"])
                if iz == 0 or not grid[ix][iy][iz - 1]:
                    triangles.extend(faces["-z"])

    # --- Step 4: Write binary STL ---
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
        "mast_segment_80mm.stl": build_mast_segment(),
        "camera_head.stl": build_camera_head(),
    }
    for name, occ in parts.items():
        write_binary_stl(occ, out_dir / name)
        print(f"Wrote {name}")


if __name__ == "__main__":
    main()

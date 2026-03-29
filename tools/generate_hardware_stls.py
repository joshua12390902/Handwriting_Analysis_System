from __future__ import annotations

from pathlib import Path

import trimesh
from trimesh.transformations import rotation_matrix


OUT_DIR = Path(__file__).resolve().parents[1] / "hardware_stl"


def box(size: tuple[float, float, float], center: tuple[float, float, float]) -> trimesh.Trimesh:
    mesh = trimesh.creation.box(extents=size)
    mesh.apply_translation(center)
    return mesh


def combine(parts: list[trimesh.Trimesh]) -> trimesh.Trimesh:
    try:
        merged = trimesh.boolean.union(parts, engine="manifold")
        if merged is not None:
            return merged
    except Exception:
        pass
    return trimesh.util.concatenate(parts)


def export(mesh: trimesh.Trimesh, filename: str) -> None:
    OUT_DIR.mkdir(exist_ok=True)
    mesh.export(OUT_DIR / filename)


def build_base() -> trimesh.Trimesh:
    parts: list[trimesh.Trimesh] = []

    # Main footprint: wide enough to counterweight the camera arm and hold Jetson Nano.
    parts.append(box((240, 200, 8), (120, 100, 4)))

    # Jetson Nano tray: generous fit for the developer kit + airflow gap.
    tray_x = 150
    tray_y = 60
    inner_x = 108
    inner_y = 88
    wall = 4
    wall_h = 14

    outer_x = inner_x + wall * 2
    outer_y = inner_y + wall * 2
    zc = 8 + wall_h / 2

    parts.append(box((outer_x, wall, wall_h), (tray_x, tray_y - outer_y / 2 + wall / 2, zc)))
    parts.append(box((outer_x, wall, wall_h), (tray_x, tray_y + outer_y / 2 - wall / 2, zc)))
    parts.append(box((wall, inner_y, wall_h), (tray_x - outer_x / 2 + wall / 2, tray_y, zc)))
    parts.append(box((wall, inner_y, wall_h), (tray_x + outer_x / 2 - wall / 2, tray_y, zc)))

    # Camera mast socket: open-top collar that receives the mast segment.
    socket_x = 36
    socket_y = 28
    socket_h = 28
    opening_x = 28.8
    opening_y = 20.8
    sx = 36
    sy = 150
    zc = 8 + socket_h / 2

    side_x = (socket_x - opening_x) / 2
    side_y = (socket_y - opening_y) / 2

    parts.append(box((socket_x, side_y, socket_h), (sx, sy - socket_y / 2 + side_y / 2, zc)))
    parts.append(box((socket_x, side_y, socket_h), (sx, sy + socket_y / 2 - side_y / 2, zc)))
    parts.append(box((side_x, opening_y, socket_h), (sx - socket_x / 2 + side_x / 2, sy, zc)))
    parts.append(box((side_x, opening_y, socket_h), (sx + socket_x / 2 - side_x / 2, sy, zc)))

    # Two reinforcement ribs behind and beside the socket.
    parts.append(box((14, socket_y, 18), (sx - 20, sy, 17)))
    parts.append(box((socket_x, 14, 18), (sx, sy + 18, 17)))

    return combine(parts)


def build_mast_segment() -> trimesh.Trimesh:
    return box((28, 20, 140), (14, 10, 70))


def build_joiner_sleeve() -> trimesh.Trimesh:
    parts: list[trimesh.Trimesh] = []
    outer_x = 38
    outer_y = 30
    outer_z = 40
    inner_x = 28.8
    inner_y = 20.8

    side_x = (outer_x - inner_x) / 2
    side_y = (outer_y - inner_y) / 2

    parts.append(box((outer_x, side_y, outer_z), (outer_x / 2, side_y / 2, outer_z / 2)))
    parts.append(box((outer_x, side_y, outer_z), (outer_x / 2, outer_y - side_y / 2, outer_z / 2)))
    parts.append(box((side_x, inner_y, outer_z), (side_x / 2, outer_y / 2, outer_z / 2)))
    parts.append(box((side_x, inner_y, outer_z), (outer_x - side_x / 2, outer_y / 2, outer_z / 2)))
    return combine(parts)


def build_camera_head() -> trimesh.Trimesh:
    parts: list[trimesh.Trimesh] = []

    # Mast collar.
    outer_x = 38
    outer_y = 30
    collar_h = 36
    inner_x = 28.8
    inner_y = 20.8
    side_x = (outer_x - inner_x) / 2
    side_y = (outer_y - inner_y) / 2
    zc = collar_h / 2

    parts.append(box((outer_x, side_y, collar_h), (outer_x / 2, side_y / 2, zc)))
    parts.append(box((outer_x, side_y, collar_h), (outer_x / 2, outer_y - side_y / 2, zc)))
    parts.append(box((side_x, inner_y, collar_h), (side_x / 2, outer_y / 2, zc)))
    parts.append(box((side_x, inner_y, collar_h), (outer_x - side_x / 2, outer_y / 2, zc)))

    # Horizontal arm.
    arm_len = 150
    arm_y = 20
    arm_z = 20
    arm_center = (outer_x + arm_len / 2, outer_y / 2, collar_h - arm_z / 2)
    parts.append(box((arm_len, arm_y, arm_z), arm_center))

    # Under-arm brace to stiffen the cantilever.
    brace = box((130, 8, 8), (94, outer_y / 2, 21))
    brace.apply_transform(rotation_matrix(-0.42, [0, 1, 0], point=[40, outer_y / 2, 12]))
    parts.append(brace)

    # Camera platform. Sized for the C922 clip in folded 90-degree mode.
    platform_len = 86
    platform_y = 72
    platform_z = 6
    platform_center = (outer_x + arm_len + platform_len / 2, outer_y / 2, collar_h + platform_z / 2)
    parts.append(box((platform_len, platform_y, platform_z), platform_center))

    # Front and rear lips to stop the webcam clip from sliding.
    lip_h = 12
    lip_t = 4
    lip_z = collar_h + platform_z + lip_h / 2
    platform_x0 = outer_x + arm_len
    platform_x1 = platform_x0 + platform_len
    platform_y0 = outer_y / 2 - platform_y / 2
    platform_y1 = outer_y / 2 + platform_y / 2

    parts.append(box((platform_len, lip_t, lip_h), ((platform_x0 + platform_x1) / 2, platform_y0 + lip_t / 2, lip_z)))
    parts.append(box((platform_len, lip_t, lip_h + 6), ((platform_x0 + platform_x1) / 2, platform_y1 - lip_t / 2, lip_z + 3)))

    # Side nibs help keep the folded camera clip centered.
    nib_w = 10
    nib_t = 4
    nib_h = 10
    nib_z = collar_h + platform_z + nib_h / 2
    parts.append(box((nib_w, nib_t, nib_h), (platform_x0 + 16, platform_y0 + 10, nib_z)))
    parts.append(box((nib_w, nib_t, nib_h), (platform_x0 + 16, platform_y1 - 10, nib_z)))

    return combine(parts)


def build_clip_shim() -> trimesh.Trimesh:
    return box((70, 24, 2), (35, 12, 1))


def main() -> None:
    export(build_base(), "01_jetson_base.stl")
    export(build_mast_segment(), "02_mast_segment.stl")
    export(build_joiner_sleeve(), "03_joiner_sleeve.stl")
    export(build_camera_head(), "04_camera_head_platform.stl")
    export(build_clip_shim(), "05_camera_clip_shim.stl")
    print(f"Generated STL files in {OUT_DIR}")


if __name__ == "__main__":
    main()

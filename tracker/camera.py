"""Camera selection helpers."""

from __future__ import annotations

import os
from typing import List, Optional, Tuple

import cv2

try:
    from pygrabber.dshow_graph import FilterGraph
except Exception:
    FilterGraph = None


def configure_capture(
    cap: cv2.VideoCapture,
    width: int = 640,
    height: int = 480,
) -> None:
    """Apply low-latency camera settings when supported by the backend."""
    try:
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception:
        pass

    if os.name != "nt":
        try:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        except Exception:
            pass

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    try:
        cap.set(cv2.CAP_PROP_FPS, 30)
    except Exception:
        pass

    # Log what V4L2 actually negotiated. If this prints YUYV / a low fps instead
    # of MJPG @ 30, that pixel-format fallback (not the app) is the fps bottleneck.
    try:
        fourcc_int = int(cap.get(cv2.CAP_PROP_FOURCC))
        fourcc = "".join(chr((fourcc_int >> (8 * i)) & 0xFF) for i in range(4))
        aw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        ah = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        afps = cap.get(cv2.CAP_PROP_FPS)
        print(f"[INFO] Camera negotiated: {aw}x{ah} @ {afps:.0f}fps fourcc={fourcc!r}")
    except Exception:
        pass


def detect_c922_index() -> Optional[int]:
    """Try to find a Logitech C922 device index on Windows."""
    if FilterGraph is None:
        return None
    try:
        devices = FilterGraph().get_input_devices()
        for idx, name in enumerate(devices):
            label = str(name).lower()
            if "c922" in label or "logitech" in label:
                return idx
    except Exception:
        pass
    return None


def build_camera_order(current_index: int = -1) -> List[int]:
    """Build a preferred camera probe order."""
    detected = detect_c922_index()
    if detected is not None:
        base = [detected] + [i for i in range(5) if i != detected]
    else:
        # Probe 0 first: on Jetson/Linux the C922 is /dev/video0, so the old
        # [1,2,3,4,0] order wasted seconds probing nonexistent indices and
        # printed scary V4L2 warnings before the real camera opened.
        base = [0, 1, 2, 3, 4]

    if current_index in base:
        pos = base.index(current_index)
        return base[pos + 1:] + base[: pos + 1]
    return base


def open_camera(
    camera_order: Optional[List[int]] = None,
    current_index: int = -1,
    width: int = 640,
    height: int = 480,
) -> Tuple[cv2.VideoCapture, int]:
    """Open the first working camera from the preferred order.

    The target resolution is applied BEFORE the first read: V4L2 locks the
    pixel format once a frame is grabbed, so setting width/height afterwards is
    silently ignored (the camera stays at whatever it first negotiated).
    """
    backends = [cv2.CAP_DSHOW, cv2.CAP_MSMF, None] if os.name == "nt" else [cv2.CAP_V4L2, None]
    if camera_order is None:
        camera_order = build_camera_order(current_index)

    print(f"[INFO] Camera probe order: {camera_order}")

    for cam_idx in camera_order:
        for backend in backends:
            cap = cv2.VideoCapture(cam_idx) if backend is None else cv2.VideoCapture(cam_idx, backend)
            if cap is not None:
                configure_capture(cap, width, height)
            if cap is not None and cap.isOpened():
                ok, _ = cap.read()
                if ok:
                    label = "default" if backend is None else str(backend)
                    print(f"[INFO] Camera opened: index={cam_idx}, backend={label}")
                    return cap, cam_idx
            if cap is not None:
                cap.release()

    raise RuntimeError("Unable to open any camera. Please check device permissions and cable connections.")

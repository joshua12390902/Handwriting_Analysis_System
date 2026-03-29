"""
tracker/camera.py — 相機偵測、開啟、切換

與 OpenCV VideoCapture 有關的所有邏輯集中在這裡。
"""
from typing import List, Optional

import cv2

try:
    from pygrabber.dshow_graph import FilterGraph
except Exception:
    FilterGraph = None


def detect_c922_index() -> Optional[int]:
    """嘗試找到 Logitech C922 的 DirectShow 裝置索引。"""
    if FilterGraph is None:
        return None
    try:
        devices = FilterGraph().get_input_devices()
        for idx, name in enumerate(devices):
            if "c922" in str(name).lower() or "logitech" in str(name).lower():
                return idx
    except Exception:
        pass
    return None


def build_camera_order(current_index: int = -1) -> List[int]:
    """
    建立掃描順序：
    - 若偵測到 C922，優先使用它
    - 若傳入 current_index，則從下一個開始（用於切換相機）
    """
    detected = detect_c922_index()
    base = [detected] + [i for i in range(5) if i != detected] if detected is not None else [1, 2, 3, 4, 0]

    if current_index in base:
        pos = base.index(current_index)
        return base[pos + 1:] + base[:pos + 1]
    return base


def open_camera(camera_order: Optional[List[int]] = None, current_index: int = -1):
    """
    按 camera_order 依序嘗試開啟相機。
    回傳 (VideoCapture, cam_index)。找不到時 raise RuntimeError。
    """
    import os
    backends = [cv2.CAP_DSHOW, cv2.CAP_MSMF, None] if os.name == "nt" else [cv2.CAP_V4L2, None]

    if camera_order is None:
        camera_order = build_camera_order(current_index)

    print(f"[INFO] 相機掃描順序: {camera_order}")

    for cam_idx in camera_order:
        for backend in backends:
            cap = cv2.VideoCapture(cam_idx) if backend is None else cv2.VideoCapture(cam_idx, backend)
            if cap is not None and cap.isOpened():
                ok, _ = cap.read()
                if ok:
                    label = "default" if backend is None else str(backend)
                    print(f"[INFO] 相機啟動成功，index={cam_idx}, backend={label}")
                    return cap, cam_idx
            if cap is not None:
                cap.release()

    raise RuntimeError("無法開啟相機。請確認攝影機已連接且未被其他程式占用。")

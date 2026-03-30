"""Paper-region calibration helpers."""

from __future__ import annotations

from typing import Optional, Tuple

import cv2
import numpy as np


def order_points(pts: np.ndarray) -> np.ndarray:
    """Return points ordered as top-left, top-right, bottom-right, bottom-left."""
    rect = np.zeros((4, 2), dtype=np.float32)
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).reshape(-1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    rect[1] = pts[np.argmin(d)]
    rect[3] = pts[np.argmax(d)]
    return rect


def auto_calibrate(
    frame: np.ndarray,
    roi: Tuple[int, int, int, int],
    save_path: str,
) -> Optional[np.ndarray]:
    """Detect a paper quadrilateral inside the ROI and save a homography."""
    x1, y1, x2, y2 = roi
    roi_area = (x2 - x1) * (y2 - y1)

    roi_img = frame[y1:y2, x1:x2]
    gray = cv2.cvtColor(roi_img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    _, bw = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8), iterations=2)

    cnts, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cnts = sorted(cnts, key=cv2.contourArea, reverse=True)

    quad = None
    for contour in cnts:
        if cv2.contourArea(contour) < roi_area * 0.35:
            continue
        peri = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.02 * peri, True)
        if len(approx) == 4:
            quad = approx.reshape(4, 2).astype(np.float32)
            break

    if quad is None:
        print("[WARN] Auto calibration failed: no paper quadrilateral found inside ROI.")
        return None

    src = order_points(quad)
    src[:, 0] += x1
    src[:, 1] += y1

    dst = np.array(
        [
            [float(x1), float(y1)],
            [float(x2), float(y1)],
            [float(x2), float(y2)],
            [float(x1), float(y2)],
        ],
        dtype=np.float32,
    )

    matrix = cv2.getPerspectiveTransform(src, dst)
    np.save(save_path, matrix)
    print(f"[INFO] Auto calibration saved to {save_path}")
    return matrix


def manual_calibrate(
    roi: Tuple[int, int, int, int],
    save_path: str,
) -> np.ndarray:
    """Use the current ROI corners directly as an identity-like homography."""
    x1, y1, x2, y2 = roi
    src = np.array(
        [
            [float(x1), float(y1)],
            [float(x2), float(y1)],
            [float(x2), float(y2)],
            [float(x1), float(y2)],
        ],
        dtype=np.float32,
    )
    dst = src.copy()

    matrix = cv2.getPerspectiveTransform(src, dst)
    np.save(save_path, matrix)
    print(f"[INFO] Manual calibration saved to {save_path}")
    return matrix

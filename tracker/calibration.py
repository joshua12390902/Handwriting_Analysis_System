"""
tracker/calibration.py — 透視校正 (Homography)

提供自動從畫面偵測紙張四角並計算 homography 矩陣的功能。
"""
import os
from typing import Optional, Tuple

import cv2
import numpy as np


def order_points(pts: np.ndarray) -> np.ndarray:
    """將四個角點排列為 [左上, 右上, 右下, 左下]。"""
    rect = np.zeros((4, 2), dtype=np.float32)
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).reshape(-1)
    rect[0] = pts[np.argmin(s)]   # 左上
    rect[2] = pts[np.argmax(s)]   # 右下
    rect[1] = pts[np.argmin(d)]   # 右上
    rect[3] = pts[np.argmax(d)]   # 左下
    return rect


def auto_calibrate(
    frame: np.ndarray,
    roi: Tuple[int, int, int, int],
    save_path: str,
) -> Optional[np.ndarray]:
    """
    從畫面中偵測紙張四角，計算並儲存 homography 矩陣。

    Parameters
    ----------
    frame       : 已翻轉的完整攝影機畫面
    roi         : (x1, y1, x2, y2) 綠框範圍
    save_path   : homography.npy 的儲存路徑

    Returns
    -------
    np.ndarray (3×3) 若成功，否則 None
    """
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
    for c in cnts:
        if cv2.contourArea(c) < roi_area * 0.35:
            continue
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) == 4:
            quad = approx.reshape(4, 2).astype(np.float32)
            break

    if quad is None:
        print("[WARN] 自動校正失敗：找不到紙張四角，請先把白紙完整放進綠框")
        return None

    src = order_points(quad)
    src[:, 0] += x1
    src[:, 1] += y1

    dst = np.array(
        [[float(x1), float(y1)],
         [float(x2), float(y1)],
         [float(x2), float(y2)],
         [float(x1), float(y2)]],
        dtype=np.float32,
    )

    M = cv2.getPerspectiveTransform(src, dst)
    np.save(save_path, M)
    print(f"[INFO] 自動校正成功，已更新 homography: {save_path}")
    return M


def manual_calibrate(
    roi: Tuple[int, int, int, int],
    save_path: str,
) -> np.ndarray:
    """
    手動使用 ROI 框框作為紙張四角，計算並儲存 homography 矩陣。

    Parameters
    ----------
    roi         : (x1, y1, x2, y2) 框框範圍，直接作為紙張四角
    save_path   : homography.npy 的儲存路徑

    Returns
    -------
    np.ndarray (3×3) homography 矩陣
    """
    x1, y1, x2, y2 = roi

    # 直接使用框框的四角作為源點
    src = np.array(
        [[float(x1), float(y1)],  # 左上
         [float(x2), float(y1)],  # 右上
         [float(x2), float(y2)],  # 右下
         [float(x1), float(y2)]], # 左下
        dtype=np.float32,
    )

    # 目標點也是相同的矩形
    dst = src.copy()

    M = cv2.getPerspectiveTransform(src, dst)
    np.save(save_path, M)
    print(f"[INFO] 手動校正成功，已更新 homography: {save_path}")
    return M

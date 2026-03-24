"""
web/viz.py — OpenCV 畫圖輔助函式

負責把標準筆畫、使用者筆畫繪製成圖片，
以及從評分結果中提取「哪幾筆錯了」。
"""
from typing import Any, Dict, List, Set, Tuple

import cv2
import numpy as np


def extract_wrong_stroke_set(result: Dict[str, Any], center_T: float = 0.18) -> Set[int]:
    """
    從 verify_character 結果中取出「位置偏離標準」的筆畫索引集合（0-based）。
    優先使用 center_dist_diag（對角線距離），退而使用 wrong_idx。
    """
    wrong: Set[int] = set()
    try:
        if result.get("correct") is True:
            return wrong

        details = result.get("reason", {}).get("details", {})

        # 優先：用對角線距離判斷（最準確）
        diag = details.get("center_dist_diag", [])
        if diag:
            for i, d in enumerate(diag):
                if float(d) > center_T:
                    wrong.add(i)
            return wrong

        # 退而求其次：swap 對
        swaps = details.get("suspected_swaps_1based", [])
        if swaps:
            for s in swaps:
                if isinstance(s, dict):
                    wrong.add(int(s.get("a", 0)) - 1)
                    wrong.add(int(s.get("b", 0)) - 1)
            return wrong

        # 最後：wrong_idx
        w_idx = result.get("wrong_idx", -1)
        if isinstance(w_idx, int) and w_idx >= 0:
            wrong.add(w_idx)
        elif isinstance(w_idx, list):
            for i in w_idx:
                wrong.add(int(i))
    except Exception:
        pass
    return wrong


def draw_standard_strokes(std_json: Dict[str, Any], wrong_set: Set[int], size: int = 320) -> np.ndarray:
    """
    將標準筆畫畫在黑色畫布上：
    - 錯誤筆畫 → 紅色粗線
    - 正確筆畫 → 綠色細線
    """
    canvas = np.zeros((size, size, 3), dtype=np.uint8)
    strokes = std_json.get("strokes") or std_json.get("medians")
    if not strokes:
        return canvas

    parsed: List[np.ndarray] = []
    pts_all: List[np.ndarray] = []
    for s in strokes:
        arr = np.array(s, dtype=np.float32).reshape(-1, 2)
        parsed.append(arr)
        if len(arr) > 0:
            pts_all.append(arr)

    if not pts_all:
        return canvas

    all_flat = np.vstack(pts_all)
    mn, mx = all_flat.min(axis=0), all_flat.max(axis=0)
    span = np.maximum(mx - mn, 1e-6)
    scale = (size - 40) / float(max(span))
    center = (mn + mx) / 2

    for i, arr in enumerate(parsed):
        if len(arr) < 2:
            continue
        q = (arr - center) * scale
        q[:, 1] = -q[:, 1]          # hanzi-writer y 軸朝上，翻轉到畫布座標
        pts = (q + [size / 2, size / 2]).astype(np.int32)

        color = (0, 0, 255) if i in wrong_set else (0, 255, 0)
        thickness = 4 if i in wrong_set else 2
        cv2.polylines(canvas, [pts], False, color, thickness, cv2.LINE_AA)
        cv2.putText(canvas, str(i + 1), tuple(pts[0]), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)

    return canvas


def draw_user_strokes(user_strokes: List[List[Tuple[float, float]]], size: int = 320) -> np.ndarray:
    """將使用者筆畫畫在黑色畫布上（橘黃色）。"""
    canvas = np.zeros((size, size, 3), dtype=np.uint8)
    if not user_strokes:
        return canvas

    parsed: List[np.ndarray] = []
    pts_all: List[np.ndarray] = []
    for stroke in user_strokes:
        arr = np.array(stroke, dtype=np.float32).reshape(-1, 2)
        if len(arr) >= 2:
            parsed.append(arr)
            pts_all.append(arr)

    if not pts_all:
        return canvas

    all_flat = np.vstack(pts_all)
    mn, mx = all_flat.min(axis=0), all_flat.max(axis=0)
    span = np.maximum(mx - mn, 1e-6)
    scale = (size - 40) / float(max(span))
    center = (mn + mx) / 2

    for i, arr in enumerate(parsed):
        q = (arr - center) * scale
        pts = (q + [size / 2, size / 2]).astype(np.int32)
        cv2.polylines(canvas, [pts], False, (255, 180, 0), 3, cv2.LINE_AA)
        cv2.putText(canvas, str(i + 1), tuple(pts[0]), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)

    return canvas

"""Visualization helpers for standard and user strokes."""

from __future__ import annotations

from typing import Any, Dict, List, Set, Tuple

import cv2
import numpy as np


def extract_wrong_stroke_set(result: Dict[str, Any], center_T: float = 0.18) -> Set[int]:
    """Infer which standard strokes should be highlighted as wrong."""
    wrong: Set[int] = set()
    try:
        if result.get("correct") is True:
            return wrong

        details = result.get("reason", {}).get("details", {})

        diag = details.get("center_dist_diag", [])
        if diag:
            for i, dist in enumerate(diag):
                if float(dist) > center_T:
                    wrong.add(i)
            return wrong

        swaps = details.get("suspected_swaps_1based", [])
        if swaps:
            for item in swaps:
                if isinstance(item, dict):
                    wrong.add(int(item.get("a", 0)) - 1)
                    wrong.add(int(item.get("b", 0)) - 1)
            return wrong

        wrong_idx = result.get("wrong_idx", -1)
        if isinstance(wrong_idx, int) and wrong_idx >= 0:
            wrong.add(wrong_idx)
        elif isinstance(wrong_idx, list):
            for idx in wrong_idx:
                wrong.add(int(idx))
    except Exception:
        pass
    return wrong


def draw_standard_strokes(std_json: Dict[str, Any], wrong_set: Set[int], size: int = 320) -> np.ndarray:
    """Draw standard strokes and highlight wrong ones in red."""
    canvas = np.zeros((size, size, 3), dtype=np.uint8)
    strokes = std_json.get("strokes") or std_json.get("medians")
    if not strokes:
        return canvas

    parsed: List[np.ndarray] = []
    pts_all: List[np.ndarray] = []
    for stroke in strokes:
        arr = np.array(stroke, dtype=np.float32).reshape(-1, 2)
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
        q[:, 1] = -q[:, 1]
        pts = (q + [size / 2, size / 2]).astype(np.int32)

        color = (0, 0, 255) if i in wrong_set else (0, 255, 0)
        thickness = 4 if i in wrong_set else 2
        cv2.polylines(canvas, [pts], False, color, thickness, cv2.LINE_AA)
        cv2.putText(canvas, str(i + 1), tuple(pts[0]), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)

    return canvas


def draw_user_strokes(user_strokes: List[List[Tuple[float, float]]], size: int = 320) -> np.ndarray:
    """Draw user strokes in normalized coordinates."""
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

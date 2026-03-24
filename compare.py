#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
compare.py (VERIFY-ONLY, strict order)

Usage:
  python compare.py --char_hex e698af --csv data/yes_wrong.csv

Key features:
- User specifies target character (verify only, no identify).
- Checks:
  1) Stroke count mismatch -> STROKE_COUNT_MISMATCH
  2) Order wrong (center-based swap rule) -> ORDER_WRONG with swap explanation
  3) Per-stroke mismatch (min score < t_min) -> ORDER_WRONG with wrong_idx
  4) Wrong character (final_score < T_char) -> WRONG_CHARACTER
  5) Otherwise -> OK

Notes:
- Standard strokes are loaded from standard_db/{char}.json via standard_loader.load_standard()
- This version uses normalized DTW distance (average cost) to avoid score collapse.
- Default: NO direction penalty (dir_w=0.0) to keep scores stable.
"""

import argparse
import json
import math
from typing import List, Tuple, Dict, Any

import numpy as np
import pandas as pd

import standard_loader  # must provide load_standard(char_id)


Point = Tuple[float, float]
Stroke = List[Point]
Strokes = List[Stroke]


# -----------------------------
# 1) CSV -> strokes segmentation
# -----------------------------
def segment_strokes(df: pd.DataFrame, gap_tolerance: int = 2, min_points: int = 10) -> Strokes:
    """
    Segment strokes from (x,y,pen_state) stream.
    pen_state == 1: pen down
    pen_state == 0: pen up
    """
    # Extract numpy arrays upfront — avoids per-row Series creation from iterrows()
    xs = df["x"].to_numpy(dtype=float)
    ys = df["y"].to_numpy(dtype=float)
    pens = df["pen_state"].to_numpy(dtype=int)

    strokes: Strokes = []
    current: Stroke = []
    in_stroke = False
    zero_run = 0

    for x, y, pen in zip(xs, ys, pens):
        if pen == 1:
            if not in_stroke:
                in_stroke = True
                current = []
                zero_run = 0
            current.append((x, y))
            zero_run = 0
        else:
            if in_stroke:
                zero_run += 1
                if zero_run > gap_tolerance:
                    in_stroke = False
                    zero_run = 0
                    if len(current) >= min_points:
                        strokes.append(current)
                    current = []

    if in_stroke and len(current) >= min_points:
        strokes.append(current)

    return strokes


def filter_outlier_strokes(strokes: Strokes, iqr_k: float = 1.5) -> Strokes:
    """
    Remove strokes whose center is spatially far from the main cluster.
    Uses Tukey IQR fence on distance-from-median-center.
    Handles accidental stray marks that are far outside the writing area.
    """
    if len(strokes) <= 2:
        return strokes
    centers = np.array(
        [[np.mean([p[0] for p in s]), np.mean([p[1] for p in s])] for s in strokes],
        dtype=np.float32,
    )
    median_c = np.median(centers, axis=0)
    dists = np.sqrt(((centers - median_c) ** 2).sum(axis=1))
    q25 = float(np.percentile(dists, 25))
    q75 = float(np.percentile(dists, 75))
    iqr = q75 - q25
    threshold = q75 + iqr_k * max(iqr, 1.0)
    kept = [s for s, d in zip(strokes, dists) if d <= threshold]
    return kept if kept else strokes  # 安全：永不回傳空列表


# -----------------------------
# 2) Geometry utils
# -----------------------------
def resample_stroke(stroke: Stroke, n: int = 64) -> np.ndarray:
    """
    Resample a stroke to n points by arc-length interpolation.
    Returns ndarray shape (n,2).
    """
    pts = np.array(stroke, dtype=np.float32)
    if len(pts) == 0:
        return np.zeros((n, 2), dtype=np.float32)
    if len(pts) == 1:
        return np.repeat(pts, n, axis=0)

    diffs = pts[1:] - pts[:-1]
    seg_lens = np.sqrt((diffs**2).sum(axis=1))
    s = np.concatenate([[0.0], np.cumsum(seg_lens)])
    total = float(s[-1])

    if total < 1e-6:
        return np.repeat(pts[:1], n, axis=0)

    t = np.linspace(0.0, total, n, dtype=np.float32)
    x = np.interp(t, s, pts[:, 0]).astype(np.float32)
    y = np.interp(t, s, pts[:, 1]).astype(np.float32)
    return np.stack([x, y], axis=1)


def normalize_character(strokes: Strokes) -> Strokes:
    """
    Whole-character normalization:
    - translate all points so global centroid at origin
    - scale by max range over x/y
    """
    if not strokes:
        return strokes

    lengths = [len(s) for s in strokes]
    all_pts = np.array([p for s in strokes for p in s], dtype=np.float32)
    if len(all_pts) == 0:
        return strokes

    center = all_pts.mean(axis=0)          # (2,)
    pts0 = all_pts - center                # centered, shape (N, 2)

    mn = pts0.min(axis=0)
    mx = pts0.max(axis=0)
    scale = float(max(mx[0] - mn[0], mx[1] - mn[1], 1e-6))

    # Normalize all points in one vectorized op, then split per stroke
    pts_norm = pts0 / scale
    result: Strokes = []
    idx = 0
    for length in lengths:
        chunk = pts_norm[idx: idx + length]
        result.append([tuple(p) for p in chunk.tolist()])
        idx += length
    return result


def stroke_center(stk: np.ndarray) -> np.ndarray:
    return stk.mean(axis=0)


# -----------------------------
# 3) DTW distance (NORMALIZED)
# -----------------------------
def dtw_distance(a: np.ndarray, b: np.ndarray) -> float:
    """
    DTW with L2 point distance. Returns NORMALIZED average-ish cost.
    Cost matrix is precomputed via numpy broadcasting to avoid per-cell linalg.norm overhead.
    """
    n, m = a.shape[0], b.shape[0]
    # Precompute full (n, m) pairwise L2 cost matrix in one vectorized call
    diff = a[:, None, :] - b[None, :, :]           # (n, m, 2)
    C = np.sqrt((diff * diff).sum(axis=-1))         # (n, m)

    dp = np.full((n + 1, m + 1), 1e18, dtype=np.float64)
    dp[0, 0] = 0.0

    for i in range(1, n + 1):
        prev = dp[i - 1]
        cur = dp[i]
        ci = C[i - 1]
        for j in range(1, m + 1):
            cur[j] = ci[j - 1] + min(prev[j], cur[j - 1], prev[j - 1])

    return float(dp[n, m]) / float(n + m)


# -----------------------------
# 4) Compare (scores + centers)
# -----------------------------
def compare_scores(
    user: Strokes,
    standard: Strokes,
    alpha: float = 0.35,
    dir_w: float = 0.0,
    resample_n: int = 64,
    flip_y: bool = True,
) -> Dict[str, Any]:
    """
    Compute:
    - final_score, stroke_scores, wrong_idx
    - centers_user, centers_std (in normalized space)
    - center_dist_diag: dist(center_user[i], center_std[i])
    - center_dist_matrix: full NxN

    flip_y=True (default): negate user y before normalization.
    Camera data uses screen coords (y↓), but hanzi-writer standard uses
    math coords (y↑). Without flipping, the dot stroke of e.g. 永 ends up
    at normalized y≈-0.49 (user) vs +0.45 (standard), causing artificially
    high DTW distance even when the stroke is correct.
    """
    if len(user) != len(standard) or len(user) == 0:
        return {
            "final_score": 0.0,
            "stroke_scores": [],
            "wrong_idx": -1,
            "centers_user": [],
            "centers_std": [],
            "center_dist_diag": [],
            "center_dist_matrix": [],
        }

    # Align coordinate systems: camera y is downward, standard y is upward
    if flip_y:
        user = [[(x, -y) for x, y in s] for s in user]

    user_n = normalize_character(user)
    std_n = normalize_character(standard)

    # Resample once for each stroke so we can compute centers consistently
    U = [resample_stroke(s, resample_n) for s in user_n]
    S = [resample_stroke(s, resample_n) for s in std_n]

    centers_user = [stroke_center(u) for u in U]
    centers_std = [stroke_center(s) for s in S]

    n = len(U)
    # Vectorized center distance matrix via broadcasting: O(n²) with no Python loop overhead
    c_u = np.array(centers_user, dtype=np.float32)   # (n, 2)
    c_s = np.array(centers_std, dtype=np.float32)    # (n, 2)
    diff_c = c_u[:, None, :] - c_s[None, :, :]       # (n, n, 2)
    center_dist_matrix = np.sqrt((diff_c * diff_c).sum(axis=-1)).astype(np.float32)  # (n, n)

    stroke_scores: List[float] = []
    for i in range(n):
        u = U[i]
        s = S[i]

        # optional direction penalty (default 0 to keep scores stable)
        if dir_w > 0:
            start_dist = float(np.linalg.norm(u[0] - s[0]))
            end_dist = float(np.linalg.norm(u[-1] - s[-1]))
            dir_penalty = dir_w * (start_dist + end_dist)
        else:
            dir_penalty = 0.0

        d = dtw_distance(u, s) + dir_penalty
        score = math.exp(-d / alpha)
        stroke_scores.append(float(score))

    final_score = float(sum(stroke_scores) / len(stroke_scores))
    wrong_idx = int(stroke_scores.index(min(stroke_scores))) if stroke_scores else -1
    center_dist_diag = [float(center_dist_matrix[i, i]) for i in range(n)]

    return {
        "final_score": final_score,
        "stroke_scores": stroke_scores,
        "wrong_idx": wrong_idx,
        "centers_user": [c.tolist() for c in centers_user],
        "centers_std": [c.tolist() for c in centers_std],
        "center_dist_diag": center_dist_diag,
        "center_dist_matrix": center_dist_matrix.tolist(),
    }


# -----------------------------
# 5) Center-based strict order rule
# -----------------------------
def detect_swaps_by_centers(
    center_dist_matrix: List[List[float]],
    center_T: float = 0.18,
    swap_margin: float = 0.04,
    stroke_scores: List[float] = None,
    score_gate: float = 0.40,
    top_pairs: int = 6,
) -> List[Dict[str, Any]]:
    """
    Detect suspected swaps (i <-> j) using center distances only.

    We consider a pair (i,j) a "swap candidate" if:
      - current diagonal assignment is "bad enough": max(Dii, Djj) > center_T
      - swapping improves total center cost by at least swap_margin:
            (Dii + Djj) - (Dij + Dji) >= swap_margin

        Returns list of dicts sorted by improvement desc.
    Indices are 0-based in the returned structure.

        Extra guard:
            if stroke_scores is provided, only keep pair(i,j) when BOTH
            stroke_scores[i] and stroke_scores[j] are <= score_gate.
            This avoids over-triggering swap on globally good strokes.
    """
    D = np.array(center_dist_matrix, dtype=np.float32)
    n = D.shape[0]
    swaps: List[Dict[str, Any]] = []

    for i in range(n):
        for j in range(i + 1, n):
            Dii = float(D[i, i])
            Djj = float(D[j, j])
            Dij = float(D[i, j])
            Dji = float(D[j, i])

            diag_bad = max(Dii, Djj) > center_T
            improve = (Dii + Djj) - (Dij + Dji)

            score_bad = True
            if stroke_scores is not None and len(stroke_scores) == n:
                score_bad = (
                    float(stroke_scores[i]) <= float(score_gate)
                    and float(stroke_scores[j]) <= float(score_gate)
                )

            if diag_bad and improve >= swap_margin and score_bad:
                swaps.append({
                    "i": i,
                    "j": j,
                    "diag_cost": float(Dii + Djj),
                    "swap_cost": float(Dij + Dji),
                    "improvement": float(improve),
                    "Dii": Dii, "Djj": Djj, "Dij": Dij, "Dji": Dji
                })

    swaps.sort(key=lambda x: x["improvement"], reverse=True)
    return swaps[:top_pairs]


# -----------------------------
# 6) User-facing message
# -----------------------------
def make_user_message_ok(char: str) -> str:
    return f"正確：你寫的「{char}」筆畫數與筆順都正確。"


def make_user_message_count(char: str, n_user: int, n_std: int) -> str:
    delta = n_user - n_std
    if delta > 0:
        return f"錯誤：你寫的「{char}」多寫了 {delta} 筆（應為 {n_std} 筆，你寫了 {n_user} 筆）。"
    return f"錯誤：你寫的「{char}」少寫了 {-delta} 筆（應為 {n_std} 筆，你寫了 {n_user} 筆）。"


def make_user_message_order_by_swaps(
    char: str,
    swaps: List[Dict[str, Any]],
    center_dist_diag: List[float] = None,
    center_T: float = 0.18,
) -> str:
    # Report strokes whose own diagonal distance is bad (position is off).
    # Fall back to union of swap pair indices if diag info is unavailable.
    if center_dist_diag:
        bad = sorted(
            i + 1
            for i, d in enumerate(center_dist_diag)
            if d > center_T
        )
    else:
        bad = sorted({s['i'] + 1 for s in swaps} | {s['j'] + 1 for s in swaps})
    strokes_txt = "、".join(f"第{n}筆" for n in bad)
    return f"錯誤：你寫的「{char}」{strokes_txt}位置或順序不正確，請重新確認筆順。"


def make_user_message_order_by_idx(char: str, wrong_idx: int, wrong_score: float, t_min: float) -> str:
    return (
        f"錯誤：你寫的「{char}」第 {wrong_idx + 1} 筆筆順/寫法不正確 "
    )


def make_user_message_wrong_char(char: str, final_score: float, T_char: float) -> str:
    return (
        f"錯誤：你寫的筆畫數與筆順看似合理，但整體不像「{char}」 "
        f"請重寫。"
    )


# -----------------------------
# 7) Verification with reasons
# -----------------------------
def verify_character(
    user_strokes: Strokes,
    std_strokes: Strokes,
    target_char: str,
    alpha: float = 0.35,
    T_char: float = 0.70,
    t_min: float = 0.40,
    dir_w: float = 0.0,
    center_T: float = 0.18,
    swap_margin: float = 0.04,
    swap_score_gate: float = 1.0,
    flip_y: bool = True,
    debug: bool = False,
) -> Dict[str, Any]:
    """
    Strict policy:
      - stroke count mismatch -> False
      - ORDER_WRONG if center-based swap evidence exists (hard rule)
      - ORDER_WRONG if any stroke score < t_min
      - WRONG_CHARACTER if final_score < T_char
      - OK otherwise
    """
    # 0) Remove spatial outlier strokes before any check
    user_strokes = filter_outlier_strokes(user_strokes)

    n_user = len(user_strokes)
    n_std = len(std_strokes)

    # 1) Count mismatch
    if n_user != n_std:
        return {
            "correct": False,
            "status": "STROKE_COUNT_MISMATCH",
            "message": make_user_message_count(target_char, n_user, n_std),
            "final_score": 0.0,
            "stroke_scores": [],
            "wrong_idx": -1,
            "reason": {
                "stroke_count_ok": False,
                "final_score_ok": None,
                "min_stroke_ok": None,
                "failed_rule": "STROKE_COUNT_MISMATCH",
                "details": {
                    "n_user_strokes": int(n_user),
                    "n_std_strokes": int(n_std),
                    "delta": int(n_user - n_std),
                },
            },
        }

    # 2) Compute scores + center distances
    comp = compare_scores(user_strokes, std_strokes, alpha=alpha, dir_w=dir_w, flip_y=flip_y)
    final_score = float(comp["final_score"])
    stroke_scores = comp["stroke_scores"]
    wrong_idx = int(comp["wrong_idx"])

    if debug:
        print(f"DEBUG: n_user={n_user} n_std={n_std} n_scores={len(stroke_scores)}")

    if not stroke_scores:
        return {
            "correct": False,
            "status": "NO_SCORES",
            "message": "錯誤：沒有有效筆畫資料（可能 min_points 設太高或資料格式異常）。",
            "final_score": final_score,
            "stroke_scores": [],
            "wrong_idx": -1,
            "reason": {
                "stroke_count_ok": True,
                "final_score_ok": False,
                "min_stroke_ok": False,
                "failed_rule": "NO_STROKE_SCORES",
                "details": {},
            },
        }

    # 3) HARD RULE: center-based swap detection (strict order)
    swaps = detect_swaps_by_centers(
        comp["center_dist_matrix"],
        center_T=center_T,
        swap_margin=swap_margin,
        stroke_scores=stroke_scores,
        score_gate=swap_score_gate,
        top_pairs=8,
    )

    if len(swaps) > 0:
        msg = make_user_message_order_by_swaps(
            target_char, swaps,
            center_dist_diag=comp["center_dist_diag"],
            center_T=center_T,
        )
        return {
            "correct": False,
            "status": "ORDER_WRONG",
            "message": msg,
            "final_score": final_score,
            "stroke_scores": [float(s) for s in stroke_scores],
            "wrong_idx": wrong_idx,
            "reason": {
                "stroke_count_ok": True,
                "final_score_ok": (final_score >= T_char),
                "min_stroke_ok": (min(stroke_scores) >= t_min),
                "failed_rule": "ORDER_WRONG_SWAP",
                "details": {
                    "center_T": float(center_T),
                    "swap_margin": float(swap_margin),
                    "swap_score_gate": float(swap_score_gate),
                    # provide human friendly swaps (1-based for UI)
                    "suspected_swaps_1based": [
                        {"a": s["i"] + 1, "b": s["j"] + 1, "improvement": s["improvement"]}
                        for s in swaps
                    ],
                    # raw swaps (0-based) for debugging
                    "suspected_swaps_0based": swaps,
                    "center_dist_diag": comp["center_dist_diag"],
                },
            },
        }

    # 4) Per-stroke minimum gate (order/shape mismatch)
    min_score = float(min(stroke_scores))
    if min_score < t_min:
        wrong_idx = int(stroke_scores.index(min_score))
        wrong_score = float(stroke_scores[wrong_idx])
        msg = make_user_message_order_by_idx(target_char, wrong_idx, wrong_score, t_min)
        return {
            "correct": False,
            "status": "ORDER_WRONG",
            "message": msg,
            "final_score": final_score,
            "stroke_scores": [float(s) for s in stroke_scores],
            "wrong_idx": wrong_idx,
            "reason": {
                "stroke_count_ok": True,
                "final_score_ok": (final_score >= T_char),
                "min_stroke_ok": False,
                "failed_rule": "ORDER_WRONG_MIN_SCORE",
                "details": {
                    "wrong_idx": int(wrong_idx),
                    "wrong_score": float(wrong_score),
                    "t_min": float(t_min),
                },
            },
        }

    # 5) Overall similarity gate (wrong character)
    if final_score < T_char:
        msg = make_user_message_wrong_char(target_char, final_score, T_char)
        return {
            "correct": False,
            "status": "WRONG_CHARACTER",
            "message": msg,
            "final_score": final_score,
            "stroke_scores": [float(s) for s in stroke_scores],
            "wrong_idx": wrong_idx,
            "reason": {
                "stroke_count_ok": True,
                "final_score_ok": False,
                "min_stroke_ok": True,
                "failed_rule": "WRONG_CHARACTER",
                "details": {
                    "final_score": float(final_score),
                    "T_char": float(T_char),
                },
            },
        }

    # 6) OK
    return {
        "correct": True,
        "status": "OK",
        "message": make_user_message_ok(target_char),
        "final_score": final_score,
        "stroke_scores": [float(s) for s in stroke_scores],
        "wrong_idx": wrong_idx,
        "reason": {
            "stroke_count_ok": True,
            "final_score_ok": True,
            "min_stroke_ok": True,
            "failed_rule": None,
            "details": {},
        },
    }


# -----------------------------
# 8) CLI entry
# -----------------------------
def parse_char(args) -> str:
    if args.char_hex:
        return bytes.fromhex(args.char_hex).decode("utf-8")
    if args.char:
        return args.char
    raise ValueError("You must provide --char_hex or --char")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True, help="user input csv (timestamp,x,y,pen_state)")
    parser.add_argument("--char", help="target character (may fail in some shells)")
    parser.add_argument("--char_hex", help="target character as UTF-8 hex, e.g. e698af for 是")

    parser.add_argument("--gap", type=int, default=2, help="pen-up tolerance for segmentation")
    parser.add_argument("--min_points", type=int, default=10, help="min points per stroke (filter noise)")

    parser.add_argument("--alpha", type=float, default=0.35, help="DTW score scale")
    parser.add_argument("--T_char", type=float, default=0.70, help="overall similarity threshold")
    parser.add_argument("--t_min", type=float, default=0.40, help="per-stroke minimum threshold")

    # Keep default dir penalty OFF to avoid score drift
    parser.add_argument("--dir_w", type=float, default=0.0, help="start/end penalty weight (default 0.0)")

    # Strict center-based order rule parameters
    parser.add_argument("--center_T", type=float, default=0.18, help="diag center distance threshold to consider mismatch")
    parser.add_argument("--swap_margin", type=float, default=0.04, help="required improvement to accept a swap hypothesis")

    parser.add_argument("--debug", action="store_true")

    args = parser.parse_args()
    char_id = parse_char(args)

    df = pd.read_csv(args.csv)
    required = {"timestamp", "x", "y", "pen_state"}
    if not required.issubset(df.columns):
        raise ValueError(f"CSV missing required columns {required}, got {set(df.columns)}")

    user_strokes = segment_strokes(df, gap_tolerance=args.gap, min_points=args.min_points)
    std_strokes = standard_loader.load_standard(char_id)

    result = verify_character(
        user_strokes,
        std_strokes,
        target_char=char_id,
        alpha=args.alpha,
        T_char=args.T_char,
        t_min=args.t_min,
        dir_w=args.dir_w,
        center_T=args.center_T,
        swap_margin=args.swap_margin,
        debug=args.debug,
    )

    payload = {
        "mode": "verify",
        "target_char": char_id,
        "n_user_strokes": int(len(user_strokes)),
        "n_std_strokes": int(len(std_strokes)),
        **result,
    }

    print("RESULT_JSON:", json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()

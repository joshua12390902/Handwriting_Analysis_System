import json
import os
from pathlib import Path

# 來源：你現在看到有 9580 個檔案的那個資料夾
SRC_DIR = Path("hanzi")
# 輸出：每個字一個檔案
OUT_DIR = Path("standard_db")

# 你們畫布大小
W, H = 800, 600

# HanziWriter/MakeMeAHanzi 座標系
X_MIN, X_RANGE = 0.0, 1024.0
Y_TOP, Y_RANGE = 900.0, 1024.0  # y: 900 到 -124

def to_canvas_xy(x, y):
    cx = (x - X_MIN) / X_RANGE * W
    cy = (Y_TOP - y) / Y_RANGE * H
    return [float(cx), float(cy)]

def convert_one(src_path: Path, out_path: Path):
    with src_path.open("r", encoding="utf-8") as f:
        obj = json.load(f)

    # 只用 medians（筆畫中心線），最適合 DTW
    medians = obj.get("medians", None)
    if not medians:
        return False

    strokes_canvas = []
    for stroke in medians:
        pts = [to_canvas_xy(p[0], p[1]) for p in stroke]
        strokes_canvas.append(pts)

    out_obj = {
        "char": src_path.stem,          # 檔名就是字
        "strokes": strokes_canvas,      # list of strokes, each stroke = list of [x,y]
        "source": "hanzi-writer-data",
        "canvas": {"w": W, "h": H},
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(out_obj, f, ensure_ascii=False)

    return True

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    json_files = sorted(SRC_DIR.glob("*.json"))
    if not json_files:
        raise RuntimeError(f"No .json files found in {SRC_DIR.resolve()}")

    ok = 0
    fail = 0

    # 先小跑一個 smoke test（前 50 個），避免你等很久才發現路徑錯
    for p in json_files[:50]:
        out = OUT_DIR / p.name
        if convert_one(p, out):
            ok += 1
        else:
            fail += 1

    print(f"[SMOKE] ok={ok}, fail={fail}, out_dir={OUT_DIR.resolve()}")

    # 正式全量跑
    ok = 0
    fail = 0
    for idx, p in enumerate(json_files, 1):
        out = OUT_DIR / p.name
        if convert_one(p, out):
            ok += 1
        else:
            fail += 1

        if idx % 500 == 0:
            print(f"[PROGRESS] {idx}/{len(json_files)} ok={ok} fail={fail}")

    print(f"[DONE] total={len(json_files)} ok={ok} fail={fail}")
    print("Example output files:", list(OUT_DIR.glob("*.json"))[:5])

if __name__ == "__main__":
    main()

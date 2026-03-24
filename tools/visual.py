import argparse
from pathlib import Path

import pandas as pd

# 無頭環境必備：用 Agg backend，才能存圖不需要視窗
import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt


def segment_strokes(df, gap_tolerance=2):
    strokes = []
    current = []
    in_stroke = False
    zero_run = 0

    for _, row in df.iterrows():
        x = float(row["x"])
        y = float(row["y"])
        pen = int(row["pen_state"])

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
                    strokes.append(current)
                    current = []
                    in_stroke = False

    if in_stroke and current:
        strokes.append(current)

    return strokes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True, help="input csv with timestamp,x,y,pen_state")
    parser.add_argument("--out", default=None, help="output image path, e.g. out.png")
    parser.add_argument("--gap", type=int, default=2)
    parser.add_argument("--show_points", action="store_true")
    parser.add_argument("--invert_y", action="store_true", help="invert y axis (optional)")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    out_path = Path(args.out) if args.out else csv_path.with_suffix(".png")

    df = pd.read_csv(csv_path)
    required = {"timestamp", "x", "y", "pen_state"}
    if not required.issubset(df.columns):
        raise ValueError(f"CSV 欄位錯誤，需要 {required}，但你的是 {set(df.columns)}")

    strokes = segment_strokes(df, gap_tolerance=args.gap)

    print("num_strokes =", len(strokes))
    print("points_per_stroke =", [len(s) for s in strokes])
    print("saving to:", out_path)

    fig = plt.figure(figsize=(6, 6))
    ax = plt.gca()
    ax.set_aspect("equal", adjustable="box")
    ax.set_title(f"{csv_path.name} (strokes={len(strokes)})")

    for i, stroke in enumerate(strokes):
        xs = [p[0] for p in stroke]
        ys = [p[1] for p in stroke]
        if args.invert_y:
            ys = [-y for y in ys]

        ax.plot(xs, ys, linewidth=2)
        ax.text(xs[0], ys[0], str(i), fontsize=12)

        if args.show_points:
            ax.scatter(xs, ys, s=8)

    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main()

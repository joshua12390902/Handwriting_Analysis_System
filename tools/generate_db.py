import json
import pandas as pd

CSV_PATH = "data/me_right.csv"   # 這裡放「標準寫法」那份 csv（寫得最標準的一次）
CHAR_ID = "我"            # 你說他們是寫「大」

GAP_TOLERANCE = 2
MIN_POINTS = 10

df = pd.read_csv(CSV_PATH)

strokes = []
current = []
in_stroke = False
zero_run = 0

for _, row in df.iterrows():
    x, y, pen = float(row["x"]), float(row["y"]), int(row["pen_state"])

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
            if zero_run <= GAP_TOLERANCE:
                continue
            in_stroke = False
            zero_run = 0
            if len(current) >= MIN_POINTS:
                strokes.append(current)
            current = []

if in_stroke and len(current) >= MIN_POINTS:
    strokes.append(current)

print("Extracted strokes:", len(strokes), "points:", [len(s) for s in strokes])

db = {
    CHAR_ID: {
        "strokes": [
            [[float(x), float(y)] for (x, y) in stroke]
            for stroke in strokes
        ]
    }
}

with open("standard_db.json", "w", encoding="utf-8") as f:
    json.dump(db, f, ensure_ascii=False, indent=2)

print("Saved standard_db.json")

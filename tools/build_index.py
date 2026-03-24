import json
from pathlib import Path

STD_DIR = Path("standard_db")
OUT = Path("standard_index.json")

index = {}  # char -> n_strokes
for p in STD_DIR.glob("*.json"):
    with p.open("r", encoding="utf-8") as f:
        obj = json.load(f)
    index[p.stem] = len(obj["strokes"])

with OUT.open("w", encoding="utf-8") as f:
    json.dump(index, f, ensure_ascii=False)

print("Saved", OUT, "num_chars =", len(index))

import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
STANDARD_DIR = BASE_DIR / "standard_db"
AGGREGATE_DB = BASE_DIR / "standard_db.json"
RAW_HANZI_DIR = BASE_DIR / "hanzi"


def load_standard_entry(char_id: str):
    path = STANDARD_DIR / f"{char_id}.json"
    if path.exists():
        try:
            if path.stat().st_size > 0:
                with path.open("r", encoding="utf-8") as f:
                    return json.load(f)
        except json.JSONDecodeError:
            pass

    # 直接從 hanzi/ 原始資料讀取
    raw_path = RAW_HANZI_DIR / f"{char_id}.json"
    if raw_path.exists():
        with raw_path.open("r", encoding="utf-8") as f:
            raw_obj = json.load(f)
        medians = raw_obj.get("medians")
        if medians:
            return {"strokes": medians}

    # 最後嘗試 aggregate DB（若存在）
    if AGGREGATE_DB.exists():
        with AGGREGATE_DB.open("r", encoding="utf-8") as f:
            all_data = json.load(f)
        if char_id in all_data:
            return all_data[char_id]

    raise FileNotFoundError(
        f"Standard data not found for '{char_id}': tried {raw_path.resolve()} and {AGGREGATE_DB.resolve()}"
    )

def load_standard(char_id: str):
    """
    回傳 strokes: List[List[(x,y)]]
    檔案格式來自你剛剛轉換出的 standard_db/{char}.json
    """
    obj = load_standard_entry(char_id)

    strokes = obj["strokes"]  # list of strokes, each stroke = list of [x,y]
    # 轉成 tuple 形式，方便你後面 DTW 用
    return [[(float(p[0]), float(p[1])) for p in stroke] for stroke in strokes]

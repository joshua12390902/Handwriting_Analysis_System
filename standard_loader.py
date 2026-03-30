"""Load standard stroke data for a target character."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

BASE_DIR = Path(__file__).resolve().parent
STANDARD_DIR = BASE_DIR / "standard_db"
AGGREGATE_DB = BASE_DIR / "standard_db.json"
RAW_HANZI_DIR = BASE_DIR / "hanzi"


def load_standard_entry(char_id: str) -> Dict[str, Any]:
    standard_path = STANDARD_DIR / f"{char_id}.json"
    if standard_path.exists():
        try:
            if standard_path.stat().st_size > 0:
                return json.loads(standard_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    raw_path = RAW_HANZI_DIR / f"{char_id}.json"
    if raw_path.exists():
        raw_obj = json.loads(raw_path.read_text(encoding="utf-8"))
        medians = raw_obj.get("medians")
        if medians:
            return {"strokes": medians}

    if AGGREGATE_DB.exists():
        all_data = json.loads(AGGREGATE_DB.read_text(encoding="utf-8"))
        if char_id in all_data:
            return all_data[char_id]

    raise FileNotFoundError(
        f"Standard data not found for '{char_id}': tried {raw_path.resolve()} and {AGGREGATE_DB.resolve()}"
    )


def load_standard(char_id: str) -> List[List[Tuple[float, float]]]:
    """Return strokes as `List[List[(x, y)]]`."""
    obj = load_standard_entry(char_id)
    strokes = obj["strokes"]
    return [[(float(p[0]), float(p[1])) for p in stroke] for stroke in strokes]

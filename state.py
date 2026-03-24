"""
state.py — 共用全域狀態與 threading lock

所有模組 import 這裡的物件，不直接在各模組宣告全域變數。
"""
import threading
import time
from typing import Any, Dict, Optional

import numpy as np

data_lock = threading.Lock()

global_frame: Optional[np.ndarray] = None
global_target_char: str = "永"
global_target_hex: str = "e6b0b8"
global_target_ts: int = int(time.time() * 1000)
global_std_json: Optional[Dict[str, Any]] = None

DEFAULT_RESULT: Dict[str, Any] = {
    "status": "WAIT",
    "message": "準備就緒",
    "correct": None,
    "result_ts": 0,
}
global_result: Dict[str, Any] = dict(DEFAULT_RESULT)

# 由 app.py 在 PenTracker 建立後設定
_tracker_ref = None

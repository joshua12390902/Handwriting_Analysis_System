"""
state.py — 共用執行期狀態

將原本散落的 module-level globals 收斂到單一 AppState 物件中，
方便追蹤跨執行緒資料流，也降低後續擴充時的維護成本。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import numpy as np


DEFAULT_RESULT: Dict[str, Any] = {
    "status": "WAIT",
    "message": "準備就緒",
    "correct": None,
    "result_ts": 0,
    "llm_feedback": "",
    "llm_loading": False,
}


@dataclass
class AppState:
    """Process-wide runtime state shared by Flask routes and the tracker loop."""

    lock: threading.Lock = field(default_factory=threading.Lock)
    frame: Optional[np.ndarray] = None
    target_char: str = "永"
    target_hex: str = "e6b0b8"
    target_ts: int = field(default_factory=lambda: int(time.time() * 1000))
    std_json: Optional[Dict[str, Any]] = None
    result: Dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_RESULT))
    requested_char: Optional[str] = None
    tracker_ref: Any = None

    def snapshot_target(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "target_char": self.target_char,
                "target_hex": self.target_hex,
                "ts": self.target_ts,
            }

    def snapshot_result(self) -> Dict[str, Any]:
        with self.lock:
            return dict(self.result)

    def frame_copy(self) -> Optional[np.ndarray]:
        with self.lock:
            return None if self.frame is None else self.frame.copy()

    def std_and_result(self) -> tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
        with self.lock:
            return self.std_json, dict(self.result)

    def set_tracker(self, tracker: Any) -> None:
        with self.lock:
            self.tracker_ref = tracker

    def get_tracker(self) -> Any:
        with self.lock:
            return self.tracker_ref

    def set_frame(self, frame: np.ndarray) -> None:
        with self.lock:
            self.frame = frame.copy()

    def set_requested_char(self, char: Optional[str]) -> None:
        with self.lock:
            self.requested_char = char

    def pop_requested_char(self) -> Optional[str]:
        with self.lock:
            requested = self.requested_char
            self.requested_char = None
            return requested

    def reset_result(self, status: str = "WAIT") -> None:
        with self.lock:
            self.result = {**DEFAULT_RESULT, "status": status}

    def update_result(self, **updates: Any) -> None:
        with self.lock:
            self.result.update(updates)

    def replace_result(self, result: Dict[str, Any]) -> None:
        with self.lock:
            self.result = dict(result)

    def set_target(self, char: str, char_hex: str, ts: int) -> None:
        with self.lock:
            self.target_char = char
            self.target_hex = char_hex
            self.target_ts = ts

    def current_target_char(self) -> str:
        with self.lock:
            return self.target_char

    def set_std_json(self, std_json: Optional[Dict[str, Any]]) -> None:
        with self.lock:
            self.std_json = std_json


app_state = AppState()

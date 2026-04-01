#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Chat and feedback helpers for the handwriting analysis system."""

from __future__ import annotations

import json
import os
import random
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import state

_BASE_DIR = Path(__file__).resolve().parent
_HANZI_DIR = _BASE_DIR / "hanzi"
_STD_DIR = _BASE_DIR / "standard_db"

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:14b")
MAX_TOKENS = 1024


_CHAT_SYSTEM = """你是一位耐心、友善的 AI 漢字書寫老師，同時也能閒聊。
規則：
1. 當使用者想練習某個特定字時，回覆自然的句子，並在最後附上【設定字：X】（X 是那個字）。例如：使用者說「我想練永」→ 回「好的，來練永吧！【設定字：永】」。
2. 如果使用者只是普通對話、問問題、閒聊，就正常回覆，**不要**附上【設定字】。
3. 如果使用者問自己寫得怎麼樣，根據提供的分析結果回答。如果還沒送出分析，告訴他還沒送出。
4. 如果使用者想隨機換字但沒指定（如「隨便」「都可以」「下一題」），回覆【隨機換字】。
5. 回覆以繁體中文為主，簡短清楚即可。
6. 你不知道就直接說不知道，不要編造。
7. **永遠以系統提供的「目前練習字」為準**，不要自己宣布切換到別的字。即使對話歷史中提到過其他字，當前練習字以系統資訊為準。"""

_FEEDBACK_SYSTEM = """你是一位鼓勵型書寫老師。請根據驗證結果，用繁體中文給 2 到 4 句短回饋：
1. 先指出這次主要問題或亮點。
2. 再給一個可執行的小建議。
3. 語氣鼓勵、自然，不要過度誇張。"""


def _load_char_data(char: str) -> Optional[Dict[str, Any]]:
    for path in (_HANZI_DIR / f"{char}.json", _STD_DIR / f"{char}.json"):
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return None
    return None


def _lookup_stroke_count(char: str) -> Optional[int]:
    data = _load_char_data(char)
    if not data:
        return None
    strokes = data.get("medians") or data.get("strokes") or []
    return len(strokes) if strokes else None


def _lookup_char_info(char: str) -> Optional[str]:
    count = _lookup_stroke_count(char)
    return None if count is None else f"共{count}筆"



def _pick_random_char(exclude: Optional[str] = None) -> Optional[str]:
    candidates = [path.stem for path in _HANZI_DIR.glob("*.json")]
    if exclude:
        candidates = [char for char in candidates if char != exclude]
    return random.choice(candidates) if candidates else None


def _extract_set_char_marker(reply: str) -> Optional[str]:
    match = re.search(r"【設定字：([\u4e00-\u9fff])】", reply)
    return match.group(1) if match else None



def _clean_llm_reply(reply: str) -> str:
    return re.sub(r"【設定字：[\u4e00-\u9fff]】", "", reply).strip()


def _strip_think_tags(text: str) -> str:
    """Remove qwen3 <think>...</think> reasoning blocks from the reply."""
    return re.sub(r"<think>[\s\S]*?</think>", "", text).strip()


def _call_ollama(messages: List[Dict[str, str]]) -> str:
    payload = json.dumps(
        {
            "model": OLLAMA_MODEL,
            "messages": messages,
            "stream": False,
            "options": {"num_predict": MAX_TOKENS},
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        f"{OLLAMA_HOST}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            data = json.loads(response.read().decode("utf-8"))
            raw = data["message"]["content"]
            return _strip_think_tags(raw)
    except urllib.error.URLError as exc:
        return f"LLM 連線失敗：{exc}"
    except Exception as exc:
        return f"LLM 發生錯誤：{exc}"


def _extract_random_marker(reply: str) -> bool:
    """Check if LLM replied with the random switch marker."""
    return "【隨機換字】" in reply


def chat(user_message: str, history: Optional[List[Dict[str, str]]] = None) -> Tuple[str, Optional[str]]:
    """Return `(reply_text, char_to_set_or_None)` for the chat UI."""
    user_message = user_message.strip()
    if not user_message:
        return "", None

    # ── 全部交給 LLM ──
    current_char = state.app_state.current_target_char()
    result = state.app_state.snapshot_result()
    result_status = result.get("status", "WAIT")

    # Build context about the latest writing result
    if result_status == "DONE":
        llm_fb = result.get("llm_feedback", "")
        score_info = f"最新分析結果：{result.get('message', '')}"
        if result.get("stroke_scores"):
            score_info += f"\n各筆得分：{', '.join(f'{s:.2f}' for s in result['stroke_scores'])}"
        if llm_fb:
            score_info += f"\n詳細回饋：{llm_fb}"
        result_context = f"\n使用者已送出分析。{score_info}"
    elif result_status == "ANALYZING":
        result_context = "\n使用者已送出，正在分析中。"
    else:
        result_context = "\n使用者尚未送出分析（還沒寫或還沒按送出）。"

    system_with_context = _CHAT_SYSTEM + f"\n目前練習字是「{current_char}」。{result_context}"
    messages = [{"role": "system", "content": system_with_context}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    raw_reply = _call_ollama(messages)
    if raw_reply.startswith("LLM "):
        return "LLM 目前無法連線，請稍後再試。", None

    # Handle random switch request from LLM
    if _extract_random_marker(raw_reply):
        random_char = _pick_random_char(exclude=current_char)
        if random_char:
            info = _lookup_char_info(random_char) or "可開始練習"
            return f"好的，幫你隨機換一個！已切換為「{random_char}」，{info}。", random_char
        return "目前沒有可用的字庫資料可以切換。", None

    # Handle specific char switch from LLM
    marker_char = _extract_set_char_marker(raw_reply)
    clean_reply = _clean_llm_reply(raw_reply)

    # Ignore if LLM echoes the same char that's already active
    if marker_char and marker_char == current_char:
        marker_char = None

    if marker_char:
        if not clean_reply:
            clean_reply = f"已切換為「{marker_char}」。"
        return clean_reply, marker_char

    return clean_reply, None


def _rule_feedback(result: Dict[str, Any]) -> str:
    char = result.get("target_char", "這個字")
    status = result.get("status", "")
    reason = result.get("reason", {})
    details = reason.get("details", {})

    if status == "OK":
        return f"「{char}」這次整體寫得不錯，筆順基本正確。接下來可以再放慢一點，讓每一筆更穩。"

    if status == "STROKE_COUNT_MISMATCH":
        n_user = details.get("n_user_strokes", "?")
        n_std = details.get("n_std_strokes", "?")
        return f"這次主要是筆畫數不一致。目標字「{char}」應該是 {n_std} 筆，你這次寫成了 {n_user} 筆，先把筆畫數對齊再試一次。"

    if status == "ORDER_WRONG":
        swaps = details.get("suspected_swaps_1based", [])
        if swaps:
            first_swap = swaps[0]
            return f"這次主要是筆順順序出了問題，像第 {first_swap.get('a')} 筆和第 {first_swap.get('b')} 筆可能對調了。先慢慢照順序寫一次會更穩。"
        wrong_idx = details.get("wrong_idx", None)
        if isinstance(wrong_idx, int) and wrong_idx >= 0:
            return f"這次主要是第 {wrong_idx + 1} 筆附近的順序或形狀不太對。先對照標準筆順，從前幾筆慢慢重寫一次。"
        return f"這次主要是筆順順序有誤。先對照標準筆順，一筆一筆慢慢寫會更容易修正。"

    if status == "WRONG_CHARACTER":
        score = result.get("final_score", 0.0)
        return f"這次整體字形和目標字「{char}」還有一些差距，目前相似度約 {score:.2f}。可以先專心把結構位置抓穩，再注意筆順。"

    return f"這次「{char}」還有一些地方可以再修正。先看紅色標示，再慢慢寫一次就好。"


def _summarize_strokes(strokes: List[List[tuple]]) -> str:
    """Build a concise text summary of user stroke coordinates for the LLM."""
    if not strokes:
        return "使用者未寫任何筆畫。"
    lines = []
    for i, stroke in enumerate(strokes, 1):
        if len(stroke) < 2:
            lines.append(f"第{i}筆：點 ({stroke[0][0]:.0f},{stroke[0][1]:.0f})")
            continue
        sx, sy = stroke[0]
        ex, ey = stroke[-1]
        dx, dy = ex - sx, ey - sy
        length = (dx**2 + dy**2) ** 0.5
        # determine rough direction
        if abs(dx) > abs(dy) * 2:
            direction = "→" if dx > 0 else "←"
        elif abs(dy) > abs(dx) * 2:
            direction = "↓" if dy > 0 else "↑"
        elif dx > 0 and dy > 0:
            direction = "↘"
        elif dx > 0 and dy < 0:
            direction = "↗"
        elif dx < 0 and dy > 0:
            direction = "↙"
        else:
            direction = "↖"
        lines.append(
            f"第{i}筆：({sx:.0f},{sy:.0f})→({ex:.0f},{ey:.0f}) "
            f"方向{direction} 長度{length:.0f}px 共{len(stroke)}點"
        )
    return "\n".join(lines)


def _summarize_std_strokes(std_strokes: List[List[tuple]]) -> str:
    """Build a concise text summary of standard stroke coordinates."""
    if not std_strokes:
        return ""
    lines = []
    for i, stroke in enumerate(std_strokes, 1):
        if len(stroke) < 2:
            lines.append(f"標準第{i}筆：點 ({stroke[0][0]:.0f},{stroke[0][1]:.0f})")
            continue
        sx, sy = stroke[0]
        ex, ey = stroke[-1]
        dx, dy = ex - sx, ey - sy
        length = (dx**2 + dy**2) ** 0.5
        if abs(dx) > abs(dy) * 2:
            direction = "→" if dx > 0 else "←"
        elif abs(dy) > abs(dx) * 2:
            direction = "↓" if dy > 0 else "↑"
        elif dx > 0 and dy > 0:
            direction = "↘"
        elif dx > 0 and dy < 0:
            direction = "↗"
        elif dx < 0 and dy > 0:
            direction = "↙"
        else:
            direction = "↖"
        lines.append(
            f"標準第{i}筆：({sx:.0f},{sy:.0f})→({ex:.0f},{ey:.0f}) 方向{direction} 長度{length:.0f}px"
        )
    return "\n".join(lines)


_FEEDBACK_SYSTEM_V2 = """你是一位鼓勵型書寫老師。你會收到：
1. 驗證結果（筆畫數、筆順正確性、各筆得分）
2. 使用者實際書寫的筆跡座標摘要（每筆的起點→終點、方向、長度）
3. 標準字的筆跡座標摘要（作為對照）

請根據這些資料，用繁體中文給 2 到 4 句短回饋：
1. 比對使用者筆跡與標準筆跡，指出具體差異（例如：某筆方向偏了、太短、位置偏移等）。
2. 給一個可執行的小建議。
3. 語氣鼓勵、自然，不要過度誇張。
4. 不要重複列出座標數字，用自然語言描述問題即可。"""


def get_feedback(
    result: Dict[str, Any],
    user_strokes: Optional[List[List[tuple]]] = None,
    std_strokes: Optional[List[List[tuple]]] = None,
) -> str:
    """Generate short encouraging feedback for the grading result."""
    char = result.get("target_char", "這個字")
    status = result.get("status", "")
    final_score = result.get("final_score", 0.0)
    stroke_scores = result.get("stroke_scores", [])
    reason = result.get("reason", {})
    details = reason.get("details", {})

    # No strokes written — skip LLM entirely
    if not user_strokes or len(user_strokes) == 0:
        n_std = details.get("n_std_strokes", "?")
        return f"你還沒有寫任何筆畫喔！「{char}」共 {n_std} 筆，先試著寫寫看吧。"

    lines = [f"目前練習字：{char}", f"驗證狀態：{status}"]

    if status == "OK":
        lines.append("本次筆順驗證通過。")
    elif status == "STROKE_COUNT_MISMATCH":
        lines.append(
            f"筆畫數不一致：標準 {details.get('n_std_strokes', '?')} 筆，使用者 {details.get('n_user_strokes', '?')} 筆。"
        )
    elif status == "ORDER_WRONG":
        swaps = details.get("suspected_swaps_1based", [])
        if swaps:
            swap_desc = "、".join(f"第{s['a']}筆和第{s['b']}筆" for s in swaps[:2] if isinstance(s, dict))
            lines.append(f"疑似筆順對調：{swap_desc}。")
        else:
            lines.append("筆順或個別筆畫順序有誤。")
    elif status == "WRONG_CHARACTER":
        lines.append(f"整體相似度不足，目前分數約 {final_score:.2f}。")

    if stroke_scores:
        lines.append("各筆得分：" + " / ".join(f"{score:.2f}" for score in stroke_scores))

    # Append stroke coordinate summaries for the LLM
    if user_strokes:
        lines.append("\n【使用者筆跡摘要】")
        lines.append(_summarize_strokes(user_strokes))
    if std_strokes:
        lines.append("\n【標準筆跡摘要】")
        lines.append(_summarize_std_strokes(std_strokes))

    system_prompt = _FEEDBACK_SYSTEM_V2 if user_strokes else _FEEDBACK_SYSTEM

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "\n".join(lines)},
    ]
    reply = _call_ollama(messages)
    if reply.startswith("LLM ") or not reply.strip():
        return _rule_feedback(result)
    return reply.strip()

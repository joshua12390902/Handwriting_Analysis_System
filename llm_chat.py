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
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")
MAX_TOKENS = 300

_CN_NUM = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "兩": 2,
}

_STOP_CHARS = {"這", "那", "個", "字", "題", "它", "他"}

_CHAT_SYSTEM = """你是一位耐心、簡潔的 AI 漢字老師。
規則：
1. 如果使用者明確要換字，回覆自然句子，並在最後附上【設定字：字】。
2. 如果使用者只是想問筆畫、筆順、提示或求助，不要亂切換題目。
3. 回覆以繁體中文為主，簡短清楚即可。
4. 你不知道就直接說不知道，不要編造。"""

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


def _classify_stroke(median: List[List[int]]) -> str:
    """Coarse stroke-name heuristic for simple tutoring replies."""
    if len(median) < 2:
        return "點"

    sx, sy = median[0]
    ex, ey = median[-1]
    dx, dy = ex - sx, ey - sy
    adx, ady = abs(dx), abs(dy)
    length = (adx**2 + ady**2) ** 0.5

    if length < 120:
        return "點"

    if len(median) >= 4:
        mid = len(median) // 2
        dx1, dy1 = median[mid][0] - sx, median[mid][1] - sy
        dx2, dy2 = ex - median[mid][0], ey - median[mid][1]
        if (dx1 * dx2 + dy1 * dy2) < 0 or (adx > 50 and ady > 50 and len(median) >= 6):
            if abs(dx1) > abs(dy1) and dy2 > abs(dx2):
                return "橫折"
            if abs(dy1) > abs(dx1) and abs(dx2) > abs(dy2):
                return "豎折"
            last_seg_dx = median[-1][0] - median[-3][0]
            if abs(dy1) > abs(dx1) and last_seg_dx < -30:
                return "豎鉤"
            return "彎鉤"

    if adx > ady * 2.5:
        if dy < 0 and ady > 30:
            return "提"
        return "橫"

    if ady > adx * 2.5:
        if len(median) >= 3:
            last_dx = median[-1][0] - median[-2][0]
            if last_dx < -30:
                return "豎鉤"
        return "豎"

    if dx < 0 and dy > 0:
        return "撇"
    if dx > 0 and dy > 0:
        return "捺"
    if dx > 0 and dy < 0:
        return "提"
    if dx < 0 and dy < 0:
        return "撇"
    return "點"


def _lookup_stroke_names(char: str) -> Optional[List[str]]:
    data = _load_char_data(char)
    if not data:
        return None
    medians = data.get("medians") or data.get("strokes") or []
    if not medians:
        return None
    try:
        return [_classify_stroke(median) for median in medians]
    except Exception:
        return None


def _parse_cn_num(s: str) -> Optional[int]:
    s = s.strip()
    if s.isdigit():
        return int(s)
    return _CN_NUM.get(s)


def _extract_quoted_char(msg: str) -> Optional[str]:
    match = re.search(r"[「『\"']([\u4e00-\u9fff])[」』\"']", msg)
    if match and match.group(1) not in _STOP_CHARS:
        return match.group(1)
    return None


def _extract_single_char_request(msg: str) -> Optional[str]:
    match = re.fullmatch(r"\s*[「『\"'\(\[]?([\u4e00-\u9fff])[」』\"'\)\]]?\s*[嗎呢呀啊哈喔哦]*\s*", msg)
    if match and match.group(1) not in _STOP_CHARS:
        return match.group(1)
    return None


def _extract_practice_char(msg: str) -> Optional[str]:
    quoted = _extract_quoted_char(msg)
    if quoted and re.search(r"練|學|換|改|切|設|來個|想要", msg):
        return quoted

    patterns = [
        r"(?:我想練|想練|要練|來練|練習|我要練|我想學|想學|要學|學習|換成|改成|切到|設成|幫我換成|幫我切到|我想寫|想寫)\s*([\u4e00-\u9fff])",
        r"(?:練|學|寫)\s*[「『\"']?([\u4e00-\u9fff])[」』\"']?",
    ]
    for pattern in patterns:
        match = re.search(pattern, msg)
        if match:
            char = match.group(1)
            if char not in _STOP_CHARS:
                return char
    return None


def _extract_char_from_question(msg: str) -> Optional[str]:
    quoted = _extract_quoted_char(msg)
    if quoted:
        return quoted

    patterns = [
        r"([\u4e00-\u9fff])\s*(?:幾筆|幾畫|幾劃|筆畫數|筆順|怎麼寫|怎麼念|第一筆|第[一二三四五六七八九十兩\d]+筆|前[一二三四五六七八九十兩\d]+筆)",
        r"(?:字|題)\s*[：:]\s*([\u4e00-\u9fff])",
    ]
    for pattern in patterns:
        match = re.search(pattern, msg)
        if match:
            char = match.group(1)
            if char not in _STOP_CHARS:
                return char

    candidates = [c for c in re.findall(r"[\u4e00-\u9fff]", msg) if c not in _STOP_CHARS]
    if len(candidates) == 1 and len(msg.strip()) <= 4:
        return candidates[0]
    return None


def _has_practice_intent_without_char(msg: str) -> bool:
    if _extract_practice_char(msg) is not None or _extract_single_char_request(msg) is not None:
        return False
    return bool(re.search(r"練|學|換成|改成|切到|設成", msg))


def _is_random_practice_request(msg: str) -> bool:
    patterns = [
        r"隨便換一個字",
        r"隨便來一題",
        r"隨機換一個字",
        r"隨機來一題",
        r"換下一題",
        r"下一題",
        r"換個字",
        r"隨便換字",
    ]
    return any(re.search(pattern, msg) for pattern in patterns)


def _pick_random_char(exclude: Optional[str] = None) -> Optional[str]:
    candidates = [path.stem for path in _HANZI_DIR.glob("*.json")]
    if exclude:
        candidates = [char for char in candidates if char != exclude]
    return random.choice(candidates) if candidates else None


def _detect_stroke_question(msg: str) -> Optional[Tuple[Optional[str], str]]:
    normalized = msg.replace("劃", "畫")
    char = _extract_char_from_question(normalized)

    match = re.search(r"前\s*([一二三四五六七八九十兩\d]+)\s*筆", normalized)
    if match:
        num = _parse_cn_num(match.group(1))
        if num:
            return char, f"first_n:{num}"

    match = re.search(r"第\s*([一二三四五六七八九十兩\d]+)\s*筆", normalized)
    if match:
        num = _parse_cn_num(match.group(1))
        if num:
            return char, f"nth:{num}"

    if re.search(r"幾筆|幾畫|筆畫數", normalized):
        return char, "count"

    if re.search(r"筆順|怎麼寫|怎麼下筆|先寫什麼|第一筆", normalized):
        return char, "stroke_order"

    if re.search(r"提示|給我提示|教我|好難|不會寫|怎麼練", normalized):
        return char, "hint"

    return None


def _answer_stroke_from_db(char: str, question_type: str) -> Optional[str]:
    count = _lookup_stroke_count(char)
    names = _lookup_stroke_names(char) or []
    if count is None:
        return None

    if question_type == "count":
        return f"「{char}」共{count}筆。"

    if question_type == "stroke_order":
        if names:
            return f"「{char}」共{count}筆：{'、'.join(names)}。"
        return f"「{char}」共{count}筆。"

    if question_type.startswith("first_n:"):
        num = min(int(question_type.split(':', 1)[1]), len(names))
        if not names:
            return f"「{char}」共{count}筆。"
        return f"「{char}」前 {num} 筆可以先記成：{'、'.join(names[:num])}。"

    if question_type.startswith("nth:"):
        num = int(question_type.split(':', 1)[1])
        if not names:
            return f"「{char}」共{count}筆。"
        if 1 <= num <= len(names):
            return f"「{char}」第 {num} 筆是「{names[num - 1]}」。"
        return f"「{char}」共{count}筆，沒有第 {num} 筆。"

    if question_type == "hint":
        if names:
            preview = "、".join(names[: min(3, len(names))])
            return f"「{char}」共{count}筆。你可以先記前幾筆：{preview}。"
        return f"「{char}」共{count}筆。"

    return None


def _is_current_char_reference(msg: str) -> bool:
    return bool(re.search(r"這個字|這字|這題|目前這題|目前這個字|現在這題|當前字", msg))


def _looks_like_current_char_help(msg: str) -> bool:
    return bool(re.search(r"教我|好難|不會寫|提示|怎麼寫|怎麼練|先寫什麼", msg))


def _answer_current_char_request(char: str, msg: str) -> Optional[str]:
    if not char:
        return None

    stroke_question = _detect_stroke_question(msg)
    if stroke_question:
        _, question_type = stroke_question
        answer = _answer_stroke_from_db(char, question_type)
        if answer:
            return answer

    count = _lookup_stroke_count(char)
    names = _lookup_stroke_names(char) or []

    if _looks_like_current_char_help(msg):
        if count is None:
            return f"目前練習字是「{char}」，但我暫時查不到它的資料。"
        if names:
            preview = "、".join(names[: min(3, len(names))])
            return f"「{char}」共{count}筆。先把前幾筆記成：{preview}，再慢慢補後面。"
        return f"「{char}」共{count}筆。你可以先放慢速度，一筆一筆照順序寫。"

    return None


def _answer_smalltalk(msg: str) -> Optional[str]:
    if re.search(r"你在幹嘛|你在做什麼|在幹嘛", msg):
        return "我在幫你練習漢字筆順。你可以直接說想練哪個字，或問我這個字幾筆。"
    if re.search(r"你好|哈囉|嗨|安安", msg):
        return "你好，我可以幫你換題目、查筆畫數，或提示目前這個字。"
    if re.search(r"謝謝|感謝", msg):
        return "不客氣，想練下一個字也可以直接跟我說。"
    return None


def _extract_set_char_marker(reply: str) -> Optional[str]:
    match = re.search(r"【設定字：([\u4e00-\u9fff])】", reply)
    return match.group(1) if match else None


def _has_set_char_intent(msg: str) -> bool:
    return (
        _extract_practice_char(msg) is not None
        or _extract_single_char_request(msg) is not None
        or _is_random_practice_request(msg)
    )


def _should_accept_set_char_marker(user_message: str, marker_char: Optional[str]) -> bool:
    return marker_char is not None and _has_set_char_intent(user_message)


def _clean_llm_reply(reply: str) -> str:
    return re.sub(r"【設定字：[\u4e00-\u9fff]】", "", reply).strip()


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
        with urllib.request.urlopen(request, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
            return data["message"]["content"]
    except urllib.error.URLError as exc:
        return f"LLM 連線失敗：{exc}"
    except Exception as exc:
        return f"LLM 發生錯誤：{exc}"


def chat(user_message: str, history: Optional[List[Dict[str, str]]] = None) -> Tuple[str, Optional[str]]:
    """Return `(reply_text, char_to_set_or_None)` for the chat UI."""
    user_message = user_message.strip()
    if not user_message:
        return "", None

    char_to_set = _extract_practice_char(user_message)
    if char_to_set:
        info = _lookup_char_info(char_to_set)
        if info:
            return f"已切換為「{char_to_set}」，{info}。", char_to_set
        return f"找不到「{char_to_set}」的筆畫資料，你可以換別的字試試看。", None

    single_char = _extract_single_char_request(user_message)
    if single_char:
        info = _lookup_char_info(single_char)
        if info:
            return f"已切換為「{single_char}」，{info}。", single_char
        return f"找不到「{single_char}」的筆畫資料，你可以換別的字試試看。", None

    if _has_practice_intent_without_char(user_message):
        return "你想練哪個字？例如：我想練「永」。", None

    if _is_random_practice_request(user_message):
        current_char = state.app_state.current_target_char()
        random_char = _pick_random_char(exclude=current_char)
        if not random_char:
            return "目前沒有可用的字庫資料可以切換。", None
        info = _lookup_char_info(random_char) or "可開始練習"
        return f"已切換為「{random_char}」，{info}。", random_char

    stroke_question = _detect_stroke_question(user_message)
    if stroke_question:
        char_q, question_type = stroke_question
        if char_q is None or char_q in _STOP_CHARS:
            char_q = state.app_state.current_target_char()
        if char_q:
            db_answer = _answer_stroke_from_db(char_q, question_type)
            if db_answer:
                return db_answer, None
            if _extract_char_from_question(user_message):
                return f"找不到「{char_q}」的筆畫資料。", None

    if _is_current_char_reference(user_message) or _looks_like_current_char_help(user_message):
        current_char = state.app_state.current_target_char()
        current_answer = _answer_current_char_request(current_char, user_message)
        if current_answer:
            return current_answer, None

    smalltalk = _answer_smalltalk(user_message)
    if smalltalk:
        return smalltalk, None

    current_char = state.app_state.current_target_char()
    system_with_context = _CHAT_SYSTEM + f"\n目前練習字是「{current_char}」。"
    messages = [{"role": "system", "content": system_with_context}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    raw_reply = _call_ollama(messages)
    if raw_reply.startswith("LLM "):
        return "我可以幫你換字、查筆畫，或提示目前這題。", None

    marker_char = _extract_set_char_marker(raw_reply)
    if not _should_accept_set_char_marker(user_message, marker_char):
        marker_char = None

    clean_reply = _clean_llm_reply(raw_reply)
    if marker_char and not clean_reply:
        clean_reply = f"已切換為「{marker_char}」。"
    return clean_reply, marker_char


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


def get_feedback(result: Dict[str, Any]) -> str:
    """Generate short encouraging feedback for the grading result."""
    char = result.get("target_char", "這個字")
    status = result.get("status", "")
    final_score = result.get("final_score", 0.0)
    stroke_scores = result.get("stroke_scores", [])
    reason = result.get("reason", {})
    details = reason.get("details", {})

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

    messages = [
        {"role": "system", "content": _FEEDBACK_SYSTEM},
        {"role": "user", "content": "\n".join(lines)},
    ]
    reply = _call_ollama(messages)
    if reply.startswith("LLM ") or not reply.strip():
        return _rule_feedback(result)
    return reply.strip()

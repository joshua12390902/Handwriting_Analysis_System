#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
llm_chat.py — LLM 整合模組（Handwriting_Analysis_System 用）

環境變數：
  LLM_BACKEND=ollama        本機 Ollama（預設）
  OLLAMA_MODEL=qwen2.5:3b   Ollama 模型（預設）
  OLLAMA_HOST=http://localhost:11434
"""

import json
import os
import re
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 資料庫路徑（與 standard_loader 相同）
_BASE_DIR    = Path(__file__).resolve().parent
_HANZI_DIR   = _BASE_DIR / "hanzi"
_STD_DIR     = _BASE_DIR / "standard_db"


def _classify_stroke(median: List[List[int]]) -> str:
    """
    根據 median 座標推斷筆畫名稱。
    HanziWriter 座標系：左上原點，X 向右增，Y 向下增。
    """
    if len(median) < 2:
        return "點"
    sx, sy = median[0]
    ex, ey = median[-1]
    dx, dy = ex - sx, ey - sy
    adx, ady = abs(dx), abs(dy)
    length = (adx**2 + ady**2) ** 0.5

    # 很短的筆畫 → 點
    if length < 120:
        return "點"

    # 檢查有無明顯方向變化（折）
    if len(median) >= 4:
        # 計算前半和後半的方向
        mid = len(median) // 2
        dx1, dy1 = median[mid][0] - sx, median[mid][1] - sy
        dx2, dy2 = ex - median[mid][0], ey - median[mid][1]
        # 方向變化大 → 折類
        if (dx1 * dx2 + dy1 * dy2) < 0 or (adx > 50 and ady > 50 and len(median) >= 6):
            # 先橫後豎
            if abs(dx1) > abs(dy1) and dy2 > abs(dx2):
                return "橫折"
            # 先豎後橫
            if abs(dy1) > abs(dx1) and abs(dx2) > abs(dy2):
                return "豎折"
            # 有末端鉤
            last_seg_dx = median[-1][0] - median[-3][0]
            last_seg_dy = median[-1][1] - median[-3][1]
            if abs(dy1) > abs(dx1) and last_seg_dx < -30:
                return "豎鉤"
            if len(median) >= 6:
                return "折"

    # 主要水平 → 橫 或 提
    if adx > ady * 2.5:
        if dy < 0 and ady > 30:
            return "提"  # 往右上且有明顯斜度
        return "橫"

    # 主要垂直 → 豎
    if ady > adx * 2.5:
        # 末端有鉤
        if len(median) >= 3:
            last_dx = median[-1][0] - median[-2][0]
            if last_dx < -30:
                return "豎鉤"
        return "豎"

    # 斜線（dy>0 往下，dy<0 往上）
    if dx < 0 and dy > 0:
        return "撇"
    if dx > 0 and dy > 0:
        return "捺"
    if dx > 0 and dy < 0:
        return "提"
    if dx < 0 and dy < 0:
        return "撇"

    return "點"


def _lookup_char_info(char: str) -> Optional[str]:
    """
    從 hanzi/ 或 standard_db/ 查出某字的實際筆畫數。
    回傳描述字串，例如「5筆」；找不到則回 None。
    """
    for path in [_HANZI_DIR / f"{char}.json", _STD_DIR / f"{char}.json"]:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                strokes = data.get("medians") or data.get("strokes") or []
                n = len(strokes)
                return f"{n}筆"
            except Exception:
                pass
    return None


def _lookup_stroke_names(char: str) -> Optional[List[str]]:
    """從資料庫取得每一筆的名稱列表。"""
    for path in [_HANZI_DIR / f"{char}.json", _STD_DIR / f"{char}.json"]:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                medians = data.get("medians", [])
                if medians:
                    return [_classify_stroke(m) for m in medians]
            except Exception:
                pass
    return None


_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _parse_cn_num(s: str) -> Optional[int]:
    """解析中文或阿拉伯數字。"""
    s = s.strip()
    if s.isdigit():
        return int(s)
    return _CN_NUM.get(s)


def _extract_char_from_msg(msg: str) -> Optional[str]:
    """從訊息中提取使用者指的漢字，排除虛詞。"""
    _STOP_CHARS = set("的是在了嗎呢吧啊哦喔麼什這那怎個也都不有可以字題")
    # 1. 引號包住的字
    m = re.search(r'[「「]([\u4e00-\u9fff])[」」]', msg)
    if m and m.group(1) not in _STOP_CHARS:
        return m.group(1)
    # 2.「X的筆順」「X字筆畫」「X的第N筆」格式
    m = re.search(r'([\u4e00-\u9fff])[的字].{0,3}(?:筆|畫|順|寫)', msg)
    if m and m.group(1) not in _STOP_CHARS:
        return m.group(1)
    # 3. 關鍵字後面的單字（如「筆順 永」）
    m = re.search(r'(?:筆順|筆畫|筆畫數|幾筆|幾畫|怎麼寫)\s*([\u4e00-\u9fff])', msg)
    if m and m.group(1) not in _STOP_CHARS:
        return m.group(1)
    # 4. 關鍵字前面的單字（如「永 筆順」「永幾筆」）
    m = re.search(r'([\u4e00-\u9fff])\s*(?:筆順|筆畫|筆畫數|有幾筆|幾筆|幾畫|怎麼寫)', msg)
    if m and m.group(1) not in _STOP_CHARS:
        return m.group(1)
    return None


def _detect_stroke_question(msg: str) -> Optional[Tuple[Optional[str], str]]:
    """
    偵測使用者是否在問筆畫/筆順問題。
    回傳 (字或None, 問題類型) 或 None。
    """
    # 統一「比」→「筆」（常見錯字/注音）
    normalized = msg.replace("比", "筆")

    # 「前N筆」模式：提示前三筆、給我前5筆、前三筆畫
    m = re.search(r'前\s*([一二三四五六七八九十\d]+)\s*筆', normalized)
    if m:
        n = _parse_cn_num(m.group(1))
        if n:
            char = _extract_char_from_msg(msg)
            return (char, f"first_n:{n}")

    # 「第N筆」模式
    m = re.search(r'第\s*([一二三四五六七八九十\d]+)\s*筆', normalized)
    if m:
        n = _parse_cn_num(m.group(1))
        if n:
            char = _extract_char_from_msg(msg)
            return (char, f"nth:{n}")

    # 問筆畫數量
    if re.search(r'幾筆|幾畫|筆畫數', normalized):
        char = _extract_char_from_msg(msg)
        return (char, "count")

    # 問筆順/寫法
    if re.search(r'筆順|筆畫|怎麼寫', normalized):
        char = _extract_char_from_msg(msg)
        return (char, "stroke_order")

    # 提示筆畫（沒指定第幾筆，預設第1筆）
    if re.search(r'提示.{0,3}筆', normalized):
        return (None, "hint:1")

    return None


def _answer_stroke_from_db(char: str, question_type: str) -> Optional[str]:
    """用資料庫回答筆畫問題，回傳答案字串。"""
    names = _lookup_stroke_names(char)
    if not names:
        return None

    if question_type == "count":
        info = _lookup_char_info(char)
        return f"「{char}」共{info or f'{len(names)}筆'}。"

    if question_type == "stroke_order":
        info = _lookup_char_info(char)
        name_str = "、".join(names)
        return f"「{char}」共{info}，筆順為：{name_str}。"

    if question_type.startswith("first_n:"):
        n = int(question_type.split(":")[1])
        n = min(n, len(names))
        name_str = "、".join(names[:n])
        return f"「{char}」的前{n}筆為：{name_str}。"

    if question_type.startswith("nth:"):
        n = int(question_type.split(":")[1])
        if 1 <= n <= len(names):
            return f"「{char}」的第{n}筆是「{names[n-1]}」。"
        else:
            return f"「{char}」共{len(names)}筆，沒有第{n}筆。"

    if question_type.startswith("hint:"):
        n = int(question_type.split(":")[1])
        if 1 <= n <= len(names):
            return f"提示：第{n}筆是「{names[n-1]}」。"
        else:
            return f"「{char}」共{len(names)}筆，沒有第{n}筆。"

    return None


def _extract_practice_char(msg: str) -> Optional[str]:
    """
    從使用者訊息中提取要練習的漢字（純規則，不依賴 LLM）。
    支援：「我想練 你」「練習大」「換成三」「下一題練永」「我要寫山」等。
    """
    stop_chars = {"這", "那", "個", "字", "題", "它"}
    # 模式：關鍵字 + 可選的引號/空格 + 一個漢字
    patterns = [
        r'(?:想練|要練|練習|想學|要學|學習|想寫|要寫|換成|下一題練|下一題換)\s*[「「]?([\u4e00-\u9fff])[」」]?',
        r'(?:想練|要練|練習|想學|要學|學習|想寫|要寫|換成|下一題練|下一題換)\s*[「「]?([\u4e00-\u9fff])[」」]?',
        r'(?:練|學)\s*[「「]([\u4e00-\u9fff])[」」]',  # 「練/學『X』」
    ]
    for pat in patterns:
        m = re.search(pat, msg)
        if m:
            char = m.group(1)
            if char not in stop_chars:
                return char
    return None


def _extract_single_char_request(msg: str) -> Optional[str]:
    """Treat a bare single Han character as a direct practice-target request."""
    normalized = msg.strip()
    m = re.fullmatch(r'[「『〈《\(\[【]?\s*([\u4e00-\u9fff])\s*[」』〉》\)\]】]?', normalized)
    return m.group(1) if m else None


def _has_set_char_intent(msg: str) -> bool:
    """Whether the user clearly intends to switch the current practice character."""
    return (
        _extract_practice_char(msg) is not None
        or _extract_single_char_request(msg) is not None
        or _is_random_practice_request(msg)
    )


def _has_practice_intent_without_char(msg: str) -> bool:
    """Detect explicit practice intent that failed to name a valid target char."""
    if _extract_practice_char(msg) is not None or _extract_single_char_request(msg) is not None:
        return False
    return bool(re.search(r"想練|要練|練習|想學|要學|學習|想寫|要寫|換成|下一題練|下一題換", msg))


def _is_random_practice_request(msg: str) -> bool:
    """判斷使用者是否在要求系統隨機換一個字。"""
    patterns = [
        r"隨便換一個字",
        r"隨便來一個字",
        r"隨機換字",
        r"隨機來一題",
        r"換一個字",
        r"換一題",
        r"下一題",
        r"隨便出一題",
    ]
    return any(re.search(pat, msg) for pat in patterns)


def _pick_random_char(exclude: Optional[str] = None) -> Optional[str]:
    """從字庫隨機選一個可練習的字。"""
    import random

    candidates = [p.stem for p in _HANZI_DIR.glob("*.json")]
    if exclude:
        candidates = [c for c in candidates if c != exclude]
    if not candidates:
        return None
    return random.choice(candidates)


def _extract_set_char_marker(reply: str) -> Optional[str]:
    """從 LLM 回覆中提取【設定字：X】標記。"""
    m = re.search(r"【設定字：([\u4e00-\u9fff])】", reply)
    return m.group(1) if m else None


def _is_current_char_reference(msg: str) -> bool:
    """Detect vague references to the currently displayed practice character."""
    return bool(re.search(r"這個字|這題|目前這個字|現在這個字|目前這題|現在這題", msg))


def _looks_like_current_char_help(msg: str) -> bool:
    """Help requests that should usually bind to the current target character."""
    return bool(re.search(r"教我|好難|很難|不會寫|怎麼練|怎麼寫|寫法|卡住了", msg))


def _answer_current_char_request(char: str, msg: str) -> Optional[str]:
    """Answer common current-target questions without relying on chat history."""
    info = _lookup_char_info(char)
    names = _lookup_stroke_names(char) or []

    if re.search(r"幾筆|筆畫", msg):
        return f"目前這題是「{char}」，{info or '筆畫資料暫時查不到。'}"

    if re.search(r"筆順|順序|怎麼寫", msg):
        return _answer_stroke_from_db(char, "stroke_order")

    if re.search(r"提示|給我提示|提示一下|提示我", msg):
        if names:
            preview = "、".join(names[:3])
            return f"目前這題是「{char}」，{info or f'共{len(names)}筆'}。提示：先注意前幾筆，通常是 {preview}。"
        if info:
            return f"目前這題是「{char}」，{info}。"
        return f"目前這題是「{char}」，但我現在查不到更完整的筆畫提示。"

    if _looks_like_current_char_help(msg):
        if names:
            preview = "、".join(names[:3])
            return f"「{char}」先別急，先從 {preview} 開始，一筆一筆慢慢寫。"
        if info:
            return f"「{char}」先別急，這個字有 {info}，我可以一步一步帶你寫。"
        return f"「{char}」先別急，我可以先從筆順一步一步帶你。"

    return None


def _should_accept_set_char_marker(user_message: str, marker_char: Optional[str]) -> bool:
    """Only trust LLM set-char markers when the user clearly asked to switch characters."""
    if marker_char is None:
        return False
    return _has_set_char_intent(user_message)


OLLAMA_HOST  = os.environ.get("OLLAMA_HOST",  "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")
MAX_TOKENS   = 300

# ── Prompt ────────────────────────────────────────────────────────────────────

_CHAT_SYSTEM = """你是漢字書寫練習系統的AI助手，請一律使用繁體中文回答，不可使用簡體字。

規則：只有當使用者明確說「想練」、「要練」、「想學」、「要學」、「學習」、「換成」、「下一題練」某個字時，才在回覆最後加上：【設定字：Ｘ】（Ｘ為單一漢字）。
若只是問筆順、字義等問題，絕對不要加【設定字】標記。
若使用者說「這個字」「這題」「目前這題」「現在這題」，預設就是指目前正在練習的字。
若使用者說「好難」「教我」「不會寫」，請直接教目前正在練習的字，不要要求重新指定字。

正確範例：
  使用者：我想練「三」
  你：好的！「三」共3筆，由三條橫從上到下書寫。【設定字：三】

  使用者：我想學「軌」
  你：好的！來練習「軌」吧！【設定字：軌】

  使用者：「永」的筆順是什麼？
  你：「永」共5筆：點、橫折、豎、撇、捺。

  使用者：下一題換大這個字
  你：「大」共3筆，撇、捺、橫，筆順是先寫橫再撇捺。【設定字：大】

  使用者：這個字好難，教我
  你：先別急，可以先從前幾筆開始慢慢寫。

  使用者：這個字幾筆
  你：目前這題共9筆。

回答要簡潔，不超過60字。
"""

_FEEDBACK_SYSTEM = """你是漢字書寫老師，請一律使用繁體中文，不可使用簡體字。
回答要簡短，不超過60字，包含：錯誤原因 + 一句鼓勵。
"""

# ── 底層呼叫 ──────────────────────────────────────────────────────────────────

def _call_ollama(messages: List[Dict[str, str]]) -> str:
    payload = json.dumps({
        "model":   OLLAMA_MODEL,
        "messages": messages,
        "stream":  False,
        "options": {"num_predict": MAX_TOKENS},
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{OLLAMA_HOST}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["message"]["content"]
    except urllib.error.URLError as e:
        return f"（LLM 連線失敗：{e}）"
    except Exception as e:
        return f"（LLM 錯誤：{e}）"


# ── 對外介面 ──────────────────────────────────────────────────────────────────

def chat(user_message: str, history: Optional[List[Dict[str, str]]] = None) -> Tuple[str, Optional[str]]:
    """
    學生對話介面。

    Returns
    -------
    (reply_text, char_to_set_or_None)
      char_to_set: 若學生要求練某字，回傳該字；否則 None
    """
    # ── 1. 用程式碼直接解析使用者是否要練某字（不依賴 LLM） ──
    char_to_set = _extract_practice_char(user_message)
    if char_to_set:
        info = _lookup_char_info(char_to_set)
        if info:
            return f"「{char_to_set}」共{info}。", char_to_set
        else:
            return f"抱歉，資料庫中沒有「{char_to_set}」的筆畫資料，請換一個字練習吧！", None

    single_char = _extract_single_char_request(user_message)
    if single_char:
        info = _lookup_char_info(single_char)
        if info:
            return f"「{single_char}」共{info}。", single_char
        return f"抱歉，資料庫中沒有「{single_char}」的筆畫資料，請換一個字練習吧！", None

    if _has_practice_intent_without_char(user_message):
        return "你想練哪個字？例如：我想練「永」。", None

    # ── 1.5 隨機換字請求：直接由程式決定，不依賴 LLM ──
    if _is_random_practice_request(user_message):
        import state

        current_char = state.app_state.current_target_char()
        random_char = _pick_random_char(exclude=current_char)
        if random_char is None:
            return "目前找不到可切換的字，請稍後再試。", None
        info = _lookup_char_info(random_char) or "未知筆畫數"
        return f"好的，來練習「{random_char}」吧！「{random_char}」共{info}。", random_char

    # ── 2. 偵測筆畫相關問題，優先從資料庫回答 ──
    stroke_q = _detect_stroke_question(user_message)
    if stroke_q:
        char_q, q_type = stroke_q
        # 沒指定字 → 用目前題目的字
        if char_q is None:
            import state
            char_q = state.app_state.current_target_char()
        if char_q:
            db_answer = _answer_stroke_from_db(char_q, q_type)
            if db_answer:
                return db_answer, None

    # ── 2.5 「這個字／目前這題」這類模糊指代，直接綁定當前題目 ──
    if _is_current_char_reference(user_message):
        import state
        current_char = state.app_state.current_target_char()
        current_answer = _answer_current_char_request(current_char, user_message)
        if current_answer:
            return current_answer, None

    # ── 2.6 像「這好難教我」「教我」「好難」這種求助句，優先綁定目前題目 ──
    if _looks_like_current_char_help(user_message):
        import state
        current_char = state.app_state.current_target_char()
        if current_char:
            current_answer = _answer_current_char_request(current_char, user_message)
            if current_answer:
                return current_answer, None

    # ── 3. 其餘交給 LLM 處理一般對話 ──
    import state
    current_char = state.app_state.current_target_char()
    system_with_context = _CHAT_SYSTEM + f"\n目前學生正在練習的字是「{current_char}」。"
    messages = [{"role": "system", "content": system_with_context}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    raw = _call_ollama(messages)
    marker_char = _extract_set_char_marker(raw)
    if not _should_accept_set_char_marker(user_message, marker_char):
        marker_char = None
    clean_reply = re.sub(r'【設定字：.】', '', raw).strip()

    return clean_reply, marker_char


def get_feedback(result: Dict[str, Any]) -> str:
    """
    根據 verify_character() 的結果產生 LLM 教學反饋。
    """
    char    = result.get("target_char", "？")
    status  = result.get("status", "")
    correct = result.get("correct", False)
    final_score   = result.get("final_score", 0.0)
    stroke_scores = result.get("stroke_scores", [])
    reason  = result.get("reason", {})
    details = reason.get("details", {})

    lines = [f"學生剛寫完「{char}」字。"]

    if status == "OK":
        lines.append("結果：完全正確。")
    elif status == "STROKE_COUNT_MISMATCH":
        n_u   = details.get("n_user_strokes", "?")
        n_s   = details.get("n_std_strokes", "?")
        delta = details.get("delta", 0)
        lines.append(f"結果：筆畫數錯誤（標準{n_s}畫，學生寫了{n_u}畫，{'多' if delta>0 else '少'}了{abs(delta)}畫）。")
    elif status == "ORDER_WRONG":
        failed = reason.get("failed_rule", "")
        if failed == "ORDER_WRONG_SWAP":
            swaps = details.get("suspected_swaps_1based", [])
            swap_desc = "、".join(f"第{s['a']}筆↔第{s['b']}筆" for s in swaps[:2])
            lines.append(f"結果：筆順對調（{swap_desc}）。")
        else:
            widx   = details.get("wrong_idx", -1)
            wscore = details.get("wrong_score", 0.0)
            lines.append(f"結果：第{widx+1}筆寫法有誤（分數{wscore:.2f}）。")
        if stroke_scores:
            lines.append(f"各筆分數：{' / '.join(f'{s:.2f}' for s in stroke_scores)}")
    elif status == "WRONG_CHARACTER":
        lines.append(f"結果：整體不像「{char}」（分數{final_score:.2f}）。")

    lines.append("請給簡短的繁體中文反饋：錯誤原因 + 一句鼓勵（共不超過60字）。")

    messages = [
        {"role": "system", "content": _FEEDBACK_SYSTEM},
        {"role": "user",   "content": "\n".join(lines)},
    ]
    return _call_ollama(messages)

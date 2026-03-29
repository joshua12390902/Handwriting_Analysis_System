#!/usr/bin/env python3
"""
Smoke-test representative llm_chat behaviors against common prompt漏洞 cases.

Usage:
    python tools/llm_chat_smoke_test.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import llm_chat  # noqa: E402
import state  # noqa: E402


CASES = [
    {
        "name": "single-char switch",
        "current": "永",
        "msg": "哈",
        "expect_set": "哈",
        "reply_contains": "哈",
    },
    {
        "name": "learn-verb switch",
        "current": "永",
        "msg": "我想學軌",
        "expect_set": "軌",
        "reply_contains": "軌",
    },
    {
        "name": "help stays on current char",
        "current": "哈",
        "msg": "這好難教我",
        "expect_set": None,
        "reply_contains": "哈",
    },
    {
        "name": "current-char hint",
        "current": "哈",
        "msg": "提示我這個字",
        "expect_set": None,
        "reply_contains": "目前這題是「哈」",
    },
    {
        "name": "current-char count",
        "current": "哈",
        "msg": "這個字幾筆",
        "expect_set": None,
        "reply_contains": "「哈」共",
    },
    {
        "name": "explicit other-char count",
        "current": "哈",
        "msg": "軌幾筆",
        "expect_set": None,
        "reply_contains": "「軌」共",
    },
    {
        "name": "current-char order",
        "current": "哈",
        "msg": "現在這題怎麼寫",
        "expect_set": None,
        "reply_contains": "「哈」共",
    },
    {
        "name": "missing-char practice intent",
        "current": "哈",
        "msg": "我想學這個字",
        "expect_set": None,
        "reply_contains": "你想練哪個字",
    },
    {
        "name": "quoted learn switch",
        "current": "哈",
        "msg": "學「舞」",
        "expect_set": "舞",
        "reply_contains": "舞",
    },
]


def run_case(case: dict) -> tuple[bool, dict]:
    current = case["current"]
    msg = case["msg"]
    state.app_state.set_target(current, current.encode("utf-8").hex(), 1)
    reply, set_char = llm_chat.chat(msg, [])

    passed = True
    if set_char != case["expect_set"]:
        passed = False
    if case["reply_contains"] not in reply:
        passed = False

    return passed, {
        "name": case["name"],
        "current": current,
        "msg": msg,
        "reply": reply,
        "set": set_char,
        "expected_set": case["expect_set"],
        "expected_reply_contains": case["reply_contains"],
    }


def main() -> int:
    failed = 0
    for case in CASES:
        passed, detail = run_case(case)
        print(json.dumps({"passed": passed, **detail}, ensure_ascii=False))
        if not passed:
            failed += 1

    if failed:
        print(f"FAIL: {failed} case(s) failed.")
        return 1

    print("PASS: all smoke-test cases passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

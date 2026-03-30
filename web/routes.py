"""
web/routes.py — Flask 路由

所有 HTTP endpoint 集中在這裡。
"""
import time

import cv2
import numpy as np
from flask import Response, jsonify, render_template_string, request

import state
from web import app
from web.template import HTML_TEMPLATE
from web.viz import draw_standard_strokes, extract_wrong_stroke_set

try:
    import llm_chat
    _LLM_AVAILABLE = True
except Exception:
    _LLM_AVAILABLE = False


# ── 頁面 ──────────────────────────────────────────────────────────────

@app.get("/")
def index():
    return render_template_string(HTML_TEMPLATE)


# ── 狀態查詢 ───────────────────────────────────────────────────────────

@app.get("/get_target")
def get_target():
    return jsonify(state.app_state.snapshot_target())


@app.get("/get_result")
def get_result():
    return jsonify(state.app_state.snapshot_result())


# ── 影像串流 ───────────────────────────────────────────────────────────

@app.get("/video_feed")
def video_feed():
    return Response(_gen_mjpeg(), mimetype="multipart/x-mixed-replace; boundary=frame")


def _gen_mjpeg():
    while True:
        frame = state.app_state.frame_copy()
        if frame is None:
            time.sleep(0.05)
            continue
        ok, jpg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 50])
        if ok:
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg.tobytes() + b"\r\n"
        time.sleep(0.04)


# ── 標準筆畫圖 ─────────────────────────────────────────────────────────

@app.get("/std_strokes.png")
def std_strokes_png():
    try:
        std_json, res = state.app_state.std_and_result()

        if not std_json:
            img = np.zeros((320, 320, 3), dtype=np.uint8)
            cv2.putText(img, "No Data", (80, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (100, 100, 100), 2)
        else:
            wrong_set = extract_wrong_stroke_set(res)
            img = draw_standard_strokes(std_json, wrong_set)

        ok, buf = cv2.imencode(".png", img)
        return Response(buf.tobytes(), mimetype="image/png")
    except Exception:
        return ("", 500)


# ── 按鈕指令 ───────────────────────────────────────────────────────────

@app.post("/command/<action>")
def command(action: str):
    t = state.app_state.get_tracker()
    if t:
        if   action == "record":     t.trigger_record()
        elif action == "undo":       t.trigger_undo()
        elif action == "reset":      t.trigger_reset()
        elif action == "send":       t.trigger_send()
        elif action == "auto":       t.trigger_auto_request()
        elif action == "switch_cam": t.trigger_switch_camera()
        elif action == "calibrate":  t.trigger_calibration()
    return jsonify({"ok": True})


# ── LLM 對話 ───────────────────────────────────────────────────────────

@app.post("/chat")
def chat():
    if not _LLM_AVAILABLE:
        return jsonify({"reply": "LLM 模組未載入", "set_char": None})

    body = request.get_json(silent=True) or {}
    user_msg = str(body.get("message", "")).strip()
    history  = body.get("history", [])

    if not user_msg:
        return jsonify({"reply": "", "set_char": None})

    # 直接同步等待 LLM 回應，結果直接回傳給前端
    reply, char_to_set = llm_chat.chat(user_msg, history)

    if char_to_set:
        import standard_loader
        char_exists = (standard_loader.STANDARD_DIR / f"{char_to_set}.json").exists()
        if not char_exists:
            # hanzi/ 原始資料也算
            char_exists = (standard_loader.RAW_HANZI_DIR / f"{char_to_set}.json").exists()
        if char_exists:
            state.app_state.set_requested_char(char_to_set)
            tracker = state.app_state.get_tracker()
            if tracker:
                tracker.trigger_auto_request()
        else:
            reply += f"（找不到「{char_to_set}」的標準資料，請換一個字）"
            char_to_set = None

    return jsonify({"reply": reply, "set_char": char_to_set})


@app.post("/set_color/<color_name>")
def set_color(color_name: str):
    tracker = state.app_state.get_tracker()
    if tracker:
        tracker.set_pen_color(color_name)
    return jsonify({"ok": True, "color": color_name})

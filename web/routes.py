"""Flask routes for the handwriting analysis web app."""

from __future__ import annotations

import os
import platform
import time
from pathlib import Path

import cv2
import numpy as np
from flask import Response, jsonify, render_template_string, request, send_from_directory
from flask_cors import CORS
import standard_loader
import state

from web import app
from web.template import HTML_TEMPLATE
from web.viz import draw_standard_strokes, extract_wrong_stroke_set
CORS(app)
try:
    import llm_chat

    _LLM_AVAILABLE = True
except Exception:
    _LLM_AVAILABLE = False


IS_AARCH64 = platform.machine().lower() in {"aarch64", "arm64"}
MJPEG_QUALITY = int(os.environ.get("MJPEG_QUALITY", "70"))
MJPEG_SLEEP_S = float(os.environ.get("MJPEG_STREAM_SLEEP", "0.005" if IS_AARCH64 else "0.04"))


def _character_exists(char: str) -> bool:
    return (
        (standard_loader.STANDARD_DIR / f"{char}.json").exists()
        or (standard_loader.RAW_HANZI_DIR / f"{char}.json").exists()
    )


@app.get("/")
def index():
    if app.static_folder and (Path(app.static_folder) / "index.html").exists():
        return send_from_directory(app.static_folder, "index.html")
    return render_template_string(HTML_TEMPLATE)


@app.get("/get_target")
def get_target():
    return jsonify(state.app_state.snapshot_target())


@app.get("/get_result")
def get_result():
    return jsonify(state.app_state.snapshot_result())


@app.get("/video_feed")
def video_feed():
    return Response(_gen_mjpeg(), mimetype="multipart/x-mixed-replace; boundary=frame")


def _gen_mjpeg():
    while True:
        frame = state.app_state.frame_copy()
        if frame is None:
            time.sleep(0.05)
            continue
        ok, jpg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), MJPEG_QUALITY])
        if ok:
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg.tobytes() + b"\r\n"
        if MJPEG_SLEEP_S > 0:
            time.sleep(MJPEG_SLEEP_S)


@app.get("/std_strokes.png")
def std_strokes_png():
    try:
        std_json, result = state.app_state.std_and_result()
        if not std_json:
            img = np.zeros((320, 320, 3), dtype=np.uint8)
            cv2.putText(img, "No Data", (80, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (100, 100, 100), 2)
        else:
            wrong_set = extract_wrong_stroke_set(result)
            img = draw_standard_strokes(std_json, wrong_set)

        ok, buf = cv2.imencode(".png", img)
        return Response(buf.tobytes(), mimetype="image/png") if ok else ("", 500)
    except Exception:
        return ("", 500)


@app.post("/command/<action>")
def command(action: str):
    tracker = state.app_state.get_tracker()
    if not tracker:
        return jsonify({"ok": False, "reason": "tracker_unavailable"}), 503

    actions = {
        "record": tracker.trigger_record,
        "undo": tracker.trigger_undo,
        "reset": tracker.trigger_reset,
        "send": tracker.trigger_send,
        "auto": tracker.trigger_auto_request,
        "switch_cam": tracker.trigger_switch_camera,
        "calibrate": tracker.trigger_calibration,
    }
    handler = actions.get(action)
    if handler is None:
        return jsonify({"ok": False, "reason": "unknown_action"}), 404

    handler()
    return jsonify({"ok": True})


@app.post("/chat")
def chat():
    if not _LLM_AVAILABLE:
        return jsonify({"reply": "聊天功能目前不可用。", "set_char": None})

    body = request.get_json(silent=True) or {}
    user_msg = str(body.get("message", "")).strip()
    history = body.get("history", [])

    if not user_msg:
        return jsonify({"reply": "", "set_char": None})

    reply, char_to_set = llm_chat.chat(user_msg, history)

    if char_to_set:
        if _character_exists(char_to_set):
            state.app_state.set_requested_char(char_to_set)
            tracker = state.app_state.get_tracker()
            if tracker:
                tracker.trigger_auto_request()
        else:
            reply = f"{reply}\n找不到「{char_to_set}」的字庫資料。"
            char_to_set = None

    return jsonify({"reply": reply, "set_char": char_to_set})


@app.post("/set_color/<color_name>")
def set_color(color_name: str):
    tracker = state.app_state.get_tracker()
    if tracker:
        tracker.set_pen_color(color_name)
    return jsonify({"ok": True, "color": color_name})

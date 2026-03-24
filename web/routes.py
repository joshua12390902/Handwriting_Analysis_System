"""
web/routes.py — Flask 路由

所有 HTTP endpoint 集中在這裡。
"""
import time

import cv2
import numpy as np
from flask import Response, jsonify, render_template_string

import state
from web import app
from web.template import HTML_TEMPLATE
from web.viz import draw_standard_strokes, extract_wrong_stroke_set


# ── 頁面 ──────────────────────────────────────────────────────────────

@app.get("/")
def index():
    return render_template_string(HTML_TEMPLATE)


# ── 狀態查詢 ───────────────────────────────────────────────────────────

@app.get("/get_target")
def get_target():
    with state.data_lock:
        return jsonify({
            "target_char": state.global_target_char,
            "target_hex":  state.global_target_hex,
            "ts":          state.global_target_ts,
        })


@app.get("/get_result")
def get_result():
    with state.data_lock:
        return jsonify(state.global_result)


# ── 影像串流 ───────────────────────────────────────────────────────────

@app.get("/video_feed")
def video_feed():
    return Response(_gen_mjpeg(), mimetype="multipart/x-mixed-replace; boundary=frame")


def _gen_mjpeg():
    while True:
        with state.data_lock:
            if state.global_frame is None:
                time.sleep(0.05)
                continue
            frame = state.global_frame.copy()
        ok, jpg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 50])
        if ok:
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg.tobytes() + b"\r\n"
        time.sleep(0.04)


# ── 標準筆畫圖 ─────────────────────────────────────────────────────────

@app.get("/std_strokes.png")
def std_strokes_png():
    try:
        with state.data_lock:
            std_json = state.global_std_json
            res = dict(state.global_result)

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
    t = state._tracker_ref
    if t:
        if   action == "record":     t.trigger_record()
        elif action == "undo":       t.trigger_undo()
        elif action == "reset":      t.trigger_reset()
        elif action == "send":       t.trigger_send()
        elif action == "auto":       t.trigger_auto_request()
        elif action == "switch_cam": t.trigger_switch_camera()
    return jsonify({"ok": True})

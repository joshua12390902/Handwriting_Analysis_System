#!/usr/bin/env python3
# -*- coding: utf-8 -*-
try:
    import mediapipe as mp
except ImportError:
    mp = None
import io
import os
import csv
import json
import time
import random
import threading
from typing import Any, Dict, List, Optional, Set, Tuple

import cv2
import numpy as np
from flask import Flask, Response, jsonify, render_template_string

import standard_loader
try:
    import compare as compare_core
except Exception:
    compare_core = None

try:
    from pygrabber.dshow_graph import FilterGraph
except Exception:
    FilterGraph = None

# ============================================================
# 取代原本 ROS 的 geometry_msgs.msg.Point
# ============================================================
class Point:
    def __init__(self, x=-1.0, y=-1.0, z=0.0):
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)

# ============================================================
# Flask Globals
# ============================================================
app = Flask(__name__)

data_lock = threading.Lock()
global_frame: Optional[np.ndarray] = None
global_target_char: str = "永"  # 沒有 ROS 餵資料，先預設一個字
global_target_hex: str = "e6b0b8"
global_target_ts: int = int(time.time()*1000)
global_std_json: Optional[Dict[str, Any]] = None

SAVE_DIR = os.path.join(os.path.dirname(__file__), "saved_writings")
os.makedirs(SAVE_DIR, exist_ok=True)

# 預設結果狀態
DEFAULT_RESULT = {"status": "WAIT", "message": "準備就緒", "correct": None, "result_ts": 0}
global_result: Dict[str, Any] = DEFAULT_RESULT

# ============================================================
# Web UI
# ============================================================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>AI 書法教練</title>
  <style>
    body { font-family: 'Segoe UI', Arial, sans-serif; background:#121212; color:#eee; margin:0; padding:20px; text-align:center; }
    .container { display:flex; gap:20px; justify-content:center; flex-wrap:wrap; align-items:flex-start; margin-bottom: 20px;}
    .card { background:#1e1e1e; border-radius:12px; padding:20px; box-shadow:0 4px 20px rgba(0,0,0,0.6); border: 1px solid #333; }
    
    .target-char { 
        font-size:140px; font-weight:bold; color:#f1c40f; 
        border:3px dashed #555; width:220px; height:220px; 
        line-height:220px; border-radius:15px; margin:0 auto; 
        transition: all 0.3s;
    }
    
    .video-feed { width:640px; height:480px; border-radius:8px; border:2px solid #444; background:#000; }

    .btn-group { margin-top:20px; display:flex; gap:10px; justify-content:center; flex-wrap:wrap; }
    button { padding:12px 24px; font-size:16px; border:none; border-radius:8px; cursor:pointer; font-weight:bold; color:white; transition: transform 0.1s, opacity 0.2s; }
    button:active { transform: scale(0.95); }
    button:disabled { background: #333 !important; color: #777; cursor: not-allowed; transform: none; box-shadow: none; border: 1px solid #444; }

    .btn-auto { background:#8e44ad; width: 100%; font-size: 18px; }
    .btn-rec { background:#c0392b; }
    .btn-undo { background:#d35400; }
    .btn-reset{ background:#7f8c8d; }
    .btn-send { background:#27ae60; width: 100%; font-size: 18px; }

    .result-section { width: 100%; max-width: 680px; display: none; margin-top: 10px; }
    .badge { display:inline-block; padding:8px 16px; border-radius:20px; font-size:20px; font-weight:bold; margin-bottom:10px; }
    .badge-ok { background:#27ae60; color:white; box-shadow: 0 0 15px #27ae60; }
    .badge-bad { background:#c0392b; color:white; box-shadow: 0 0 15px #c0392b; }
    .badge-wait { background:#7f8c8d; color:white; }
    .badge-load { background:#f39c12; color:black; animation: pulse 1s infinite; }

    @keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.6; } 100% { opacity: 1; } }

    .std-img { width:320px; height:320px; border:1px solid #555; border-radius:10px; background:#000; object-fit: contain; }
    .instruction { font-size: 24px; font-weight: bold; margin: 10px 0; color: #aaa; }
    .hint-text { color: #f39c12; font-weight: bold; font-size: 18px; margin-top: 5px; }
  </style>
</head>
<body>

  <h1>Real-Time Visual Sketch Reproduction and AI Handwriting Analysis System</h1>

  <div class="container">
    <div class="card" style="width: 260px; display:flex; flex-direction:column; justify-content:space-between;">
      <div>
        <h2 style="margin-top:0; color:#ccc;">題目</h2>
        <div id="targetDisplay" class="target-char">?</div>
        <div style="color:#666; font-size:12px; margin-top:5px;" id="targetMeta">Waiting...</div>
      </div>

      <div class="btn-group" style="flex-direction:column;">
        <button id="btnAuto" class="btn-auto" onclick="sendCommand('auto')" disabled>下一題 (Next)</button>
        <div style="height:15px; border-bottom:1px solid #444; margin-bottom:15px;"></div>
        <button class="btn-rec" onclick="sendCommand('record')">⏺ 錄影 (Record)</button>
        <div style="display:flex; gap:5px;">
            <button class="btn-undo" style="flex:1;" onclick="sendCommand('undo')">↩ Undo</button>
            <button class="btn-reset" style="flex:1;" onclick="sendCommand('reset')">清除重寫</button>
        </div>
        <button id="btnSend" class="btn-send" onclick="sendCommand('send')">送出評分</button>
                <button class="btn-reset" style="background:#555; margin-top:10px;" onclick="sendCommand('switch_cam')">📷 切換相機</button>
      </div>
    </div>

    <div class="card">
        <img src="/video_feed" class="video-feed">
    </div>
  </div>

  <div class="container">
      <div id="resultBox" class="card result-section">
        <span id="statusBadge" class="badge badge-wait">WAIT</span>
        <div id="instructionText" class="instruction">...</div>
        <div style="display:flex; gap:20px; justify-content:center; align-items:flex-start; margin-top:15px;">
            <div>
                <div style="color:#aaa; font-size:14px; margin-bottom:5px;">標準筆畫比對 (紅線=寫錯)</div>
                <img id="stdImage" src="" class="std-img">
                <div id="hintText" class="hint-text"></div>
            </div>
        </div>
      </div>
  </div>

<script>
let lastResultTs = 0; 

async function refreshState() {
    const tData = await fetch('/get_target').then(r => r.json());
    const charDiv = document.getElementById('targetDisplay');
    if (charDiv.innerText !== tData.target_char) {
        charDiv.innerText = tData.target_char;
        charDiv.style.borderColor = '#f1c40f'; 
    }
    document.getElementById('targetMeta').innerText = `TS: ${tData.ts}`;

    const rData = await fetch('/get_result').then(r => r.json());
    const resBox = document.getElementById('resultBox');
    const badge = document.getElementById('statusBadge');
    const instr = document.getElementById('instructionText');
    const btnAuto = document.getElementById('btnAuto');
    const hint = document.getElementById('hintText');
    
    if (rData.status === 'WAIT') {
        resBox.style.display = 'none';
        btnAuto.disabled = false;
        btnAuto.innerText = " 跳過 / 下一題";
        btnAuto.style.opacity = "1";
    }
    else if (rData.status === 'ANALYZING') {
        resBox.style.display = 'block';
        badge.className = 'badge badge-load';
        badge.innerText = '分析中...';
        instr.innerText = 'AI 正在判讀您的筆跡';
        instr.style.color = '#ccc';
        btnAuto.disabled = true;
    }
    else {
        resBox.style.display = 'block';
        if (rData.correct === true) {
            badge.className = 'badge badge-ok';
            badge.innerText = 'PASS (通過)';
            instr.innerText = '太棒了！請按「下一題」繼續挑戰。';
            instr.style.color = '#2ecc71';
            charDiv.style.borderColor = '#2ecc71';
            hint.innerText = "";
            btnAuto.disabled = false;
            btnAuto.style.opacity = "1";
            btnAuto.innerText = "下一題 (Next)";
        } else {
            badge.className = 'badge badge-bad';
            badge.innerText = 'FAIL (未通過)';
            instr.innerText = rData.message || '筆畫有誤，請參考下方紅線標示。';
            instr.style.color = '#e74c3c';
            charDiv.style.borderColor = '#e74c3c';
            hint.innerText = "請按「清除重寫」再試一次！";
            btnAuto.disabled = true;
            btnAuto.innerText = "🔒 請先訂正錯誤";
        }

        if (rData.result_ts && rData.result_ts !== lastResultTs) {
            console.log("New result detected, refreshing image...");
            document.getElementById('stdImage').src = '/std_strokes.png?t=' + rData.result_ts;
            lastResultTs = rData.result_ts;
        }
    }
}
setInterval(refreshState, 500);

async function sendCommand(action) {
    if (action === 'auto') {
        document.getElementById('resultBox').style.display = 'none';
        document.getElementById('targetDisplay').innerText = '...';
        document.getElementById('targetDisplay').style.borderColor = '#555';
    }
    if (action === 'reset') {
        document.getElementById('targetDisplay').style.borderColor = '#f1c40f';
    }
    await fetch('/command/' + action, {method:'POST'});
}
</script>
</body>
</html>
"""

@app.get("/")
def index():
    return render_template_string(HTML_TEMPLATE)

@app.get("/get_target")
def get_target():
    with data_lock:
        return jsonify({
            "target_char": global_target_char,
            "target_hex": global_target_hex,
            "ts": global_target_ts
        })

@app.get("/get_result")
def get_result():
    with data_lock:
        return jsonify(global_result)

@app.get("/video_feed")
def video_feed():
    return Response(gen_mjpeg(), mimetype="multipart/x-mixed-replace; boundary=frame")

def gen_mjpeg():
    global global_frame
    while True:
        with data_lock:
            if global_frame is None:
                time.sleep(0.05); continue
            frame = global_frame.copy()
        ok, jpg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 50])
        if ok:
            yield (b"--frame\r\n" b"Content-Type: image/jpeg\r\n\r\n" + jpg.tobytes() + b"\r\n")
        time.sleep(0.04)

@app.get("/std_strokes.png")
def std_strokes_png():
    try:
        with data_lock:
            std_json = global_std_json
            res = dict(global_result)
        
        if not std_json:
            img = np.zeros((320, 320, 3), dtype=np.uint8)
            cv2.putText(img, "No Data", (80, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (100,100,100), 2)
        else:
            wrong_set = _extract_wrong_stroke_set(res)
            img = _draw_standard_strokes_image(std_json, wrong_set, size=320)
            
        ok, buf = cv2.imencode(".png", img)
        return Response(buf.tobytes(), mimetype="image/png")
    except:
        return ("", 500)

def _extract_wrong_stroke_set(result: Dict[str, Any]) -> Set[int]:
    wrong = set()
    try:
        if result.get("correct") is True: return wrong
        details = result.get("reason", {}).get("details", {})
        swaps = details.get("suspected_swaps_1based", [])
        if swaps:
            # 只取最可能的一組對調，避免把 1~N 全部標紅
            s = swaps[0]
            if isinstance(s, dict):
                wrong.add(int(s.get("a", 0)) - 1)
                wrong.add(int(s.get("b", 0)) - 1)
            elif isinstance(s, list):
                wrong.add(int(s[0]) - 1)
                wrong.add(int(s[1]) - 1)
            return wrong
        
        w_idx = result.get("wrong_idx", -1)
        if isinstance(w_idx, int) and w_idx >= 0:
            wrong.add(w_idx)
        elif isinstance(w_idx, list):
             for i in w_idx: wrong.add(int(i))
    except: pass
    return wrong

def _draw_standard_strokes_image(std_json, wrong_set, size=320):
    canvas = np.zeros((size, size, 3), dtype=np.uint8)
    strokes = std_json.get("strokes") or std_json.get("medians")
    if not strokes: return canvas

    pts_all = []
    parsed = []
    for s in strokes:
        arr = np.array(s, dtype=np.float32).reshape(-1, 2)
        parsed.append(arr)
        if len(arr) > 0: pts_all.append(arr)
    
    if not pts_all: return canvas
    
    all_pts_flat = np.vstack(pts_all)
    mn, mx = all_pts_flat.min(axis=0), all_pts_flat.max(axis=0)
    span = np.maximum(mx - mn, 1e-6)
    scale = (size - 40) / max(span)
    center = (mn + mx) / 2

    for i, arr in enumerate(parsed):
        if len(arr) < 2: continue
        q = (arr - center) * scale
        q[:, 1] = -q[:, 1]
        pts = (q + [size/2, size/2]).astype(np.int32)
        
        if i in wrong_set:
            color = (0, 0, 255) # Red for wrong
            thickness = 4
        else:
            color = (0, 255, 0) # Green for correct
            thickness = 2
        
        cv2.polylines(canvas, [pts], False, color, thickness, cv2.LINE_AA)
        idx_pos = pts[0]
        cv2.putText(canvas, str(i+1), tuple(idx_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255,255,255), 1)

    return canvas

def _draw_user_strokes_image(user_strokes, size=320):
    canvas = np.zeros((size, size, 3), dtype=np.uint8)
    if not user_strokes:
        return canvas

    parsed = []
    pts_all = []
    for stroke in user_strokes:
        arr = np.array(stroke, dtype=np.float32).reshape(-1, 2)
        if len(arr) < 2:
            continue
        parsed.append(arr)
        pts_all.append(arr)

    if not pts_all:
        return canvas

    all_pts_flat = np.vstack(pts_all)
    mn, mx = all_pts_flat.min(axis=0), all_pts_flat.max(axis=0)
    span = np.maximum(mx - mn, 1e-6)
    scale = (size - 40) / max(span)
    center = (mn + mx) / 2

    for i, arr in enumerate(parsed):
        q = (arr - center) * scale
        pts = (q + [size/2, size/2]).astype(np.int32)
        cv2.polylines(canvas, [pts], False, (255, 180, 0), 3, cv2.LINE_AA)
        idx_pos = pts[0]
        cv2.putText(canvas, str(i+1), tuple(idx_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255,255,255), 1)

    return canvas

_tracker_ref = None
@app.post("/command/<action>")
def command(action):
    if _tracker_ref:
        if action == 'record': _tracker_ref.trigger_record()
        elif action == 'undo': _tracker_ref.trigger_undo()
        elif action == 'reset': _tracker_ref.trigger_reset()
        elif action == 'send': _tracker_ref.trigger_send()
        elif action == 'auto': _tracker_ref.trigger_auto_request()
        elif action == 'switch_cam': _tracker_ref.trigger_switch_camera()
    return jsonify({"ok": True})

H_MIN, S_MIN, V_MIN = 90, 70, 50
H_MAX, S_MAX, V_MAX = 130, 255, 255
BASE_THRESHOLD = 400
LINEAR_COMPENSATION = 2.6
FRONT_STAGE_TEST_MODE = False
AUTO_CALIBRATE_ON_RECORD = True

def _detect_c922_index() -> Optional[int]:
    if FilterGraph is None:
        return None
    try:
        devices = FilterGraph().get_input_devices()
        for idx, name in enumerate(devices):
            lower_name = str(name).lower()
            if "c922" in lower_name or "logitech" in lower_name:
                return idx
    except Exception:
        return None
    return None

class PenTracker:
    def __init__(self):
        self.is_running = True
        self.cap_lock = threading.Lock()
        self.current_camera_index = -1
        self.current_camera_backend = "unknown"
        self.cap = self._open_camera()
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        
        self.roi_x1, self.roi_y1 = 50, 50
        self.roi_x2, self.roi_y2 = 590, 430
        self.roi_area = (self.roi_x2 - self.roi_x1) * (self.roi_y2 - self.roi_y1)
        self.is_paper_ready = False
        
        self.M = None
        project_h_path = os.path.join(os.path.dirname(__file__), "homography.npy")
        legacy_h_path = os.path.expanduser("~/sketch_ws/homography.npy")
        if os.path.exists(project_h_path):
            self.M = np.load(project_h_path)
            print(f"[INFO] Homography 矩陣載入成功: {project_h_path}")
        elif os.path.exists(legacy_h_path):
            self.M = np.load(legacy_h_path)
            print(f"[INFO] Homography 矩陣載入成功: {legacy_h_path}")
        else:
            print("[WARN] 找不到 homography.npy，將使用未校正座標。")
        # ====================================================
        # [新增] 初始化 MediaPipe 手部追蹤模型
        # ====================================================
        self.mp_hands = None
        self.hands = None
        self.mp_draw = None
        self.mediapipe_ready = False
        try:
            self.mp_hands = mp.solutions.hands
            self.hands = self.mp_hands.Hands(
                static_image_mode=False,
                max_num_hands=1,
                min_detection_confidence=0.7,
                min_tracking_confidence=0.7
            )
            self.mp_draw = mp.solutions.drawing_utils
            self.mediapipe_ready = True
            print("[INFO] MediaPipe Hands 初始化成功。")
        except Exception as e:
            print(f"[WARN] MediaPipe Hands 無法啟用，將改用 HSV+ROI 偵測。原因: {e}")
        # ====================================================
        self.paint_canvas = None
        self.last_pos = None  # 修正：統一變數名稱
        self.is_recording = False
        self.strokes_data = []
        self.start_t = 0
        self.prev_z = 0
        self.stroke_count = 0
        self.history = []
        self.idx_history = []
        self.curr_stroke_frames = 0
        
        self.curr_char = "永" # 沒有 ROS 輸入了，這裡提供一個預設字
        self.curr_hex = self.curr_char.encode('utf-8').hex()
        self.curr_ts = int(time.time()*1000)

        self.reset_canvas()

    @staticmethod
    def _order_points(pts: np.ndarray) -> np.ndarray:
        """將四點排序為 TL, TR, BR, BL"""
        rect = np.zeros((4, 2), dtype=np.float32)
        s = pts.sum(axis=1)
        d = np.diff(pts, axis=1).reshape(-1)
        rect[0] = pts[np.argmin(s)]
        rect[2] = pts[np.argmax(s)]
        rect[1] = pts[np.argmin(d)]
        rect[3] = pts[np.argmax(d)]
        return rect

    def _auto_calibrate_homography_from_roi(self) -> bool:
        """在目前畫面自動抓紙張四角並校正到綠框 ROI。"""
        with self.cap_lock:
            ret, frame = self.cap.read()
        if not ret:
            print("[WARN] 自動校正失敗：無法讀取相機畫面")
            return False

        frame = cv2.flip(frame, -1)
        roi = frame[self.roi_y1:self.roi_y2, self.roi_x1:self.roi_x2]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        _, bw = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8), iterations=2)

        cnts, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cnts = sorted(cnts, key=cv2.contourArea, reverse=True)

        quad = None
        roi_min_area = self.roi_area * 0.35
        for c in cnts:
            area = cv2.contourArea(c)
            if area < roi_min_area:
                continue
            peri = cv2.arcLength(c, True)
            approx = cv2.approxPolyDP(c, 0.02 * peri, True)
            if len(approx) == 4:
                quad = approx.reshape(4, 2).astype(np.float32)
                break

        if quad is None:
            print("[WARN] 自動校正失敗：找不到紙張四角，請先把白紙完整放進綠框")
            return False

        src = self._order_points(quad)
        src[:, 0] += self.roi_x1
        src[:, 1] += self.roi_y1

        dst = np.array(
            [
                [float(self.roi_x1), float(self.roi_y1)],
                [float(self.roi_x2), float(self.roi_y1)],
                [float(self.roi_x2), float(self.roi_y2)],
                [float(self.roi_x1), float(self.roi_y2)],
            ],
            dtype=np.float32,
        )

        self.M = cv2.getPerspectiveTransform(src, dst)
        save_path = os.path.join(os.path.dirname(__file__), "homography.npy")
        np.save(save_path, self.M)
        print(f"[INFO] 自動校正成功，已更新 homography: {save_path}")
        return True

    def _build_camera_order(self) -> List[int]:
        detected_idx = _detect_c922_index()
        if detected_idx is not None:
            camera_order = [detected_idx] + [i for i in [0, 1, 2, 3, 4] if i != detected_idx]
            print(f"[INFO] 偵測到 C922 索引: {detected_idx}")
        else:
            camera_order = [1, 2, 3, 4, 0]
        return camera_order

    def _open_camera(self, camera_order: Optional[List[int]] = None):
        if os.name == "nt":
            candidates = [cv2.CAP_DSHOW, cv2.CAP_MSMF, None]
        else:
            candidates = [cv2.CAP_V4L2, None]

        if camera_order is None:
            camera_order = self._build_camera_order()

        print(f"[INFO] 相機掃描順序: {camera_order}")

        for cam_idx in camera_order:
            for backend in candidates:
                cap = cv2.VideoCapture(cam_idx) if backend is None else cv2.VideoCapture(cam_idx, backend)
                if cap is not None and cap.isOpened():
                    ok, _ = cap.read()
                    if ok:
                        backend_name = "default" if backend is None else str(backend)
                        self.current_camera_index = cam_idx
                        self.current_camera_backend = backend_name
                        print(f"[INFO] 相機啟動成功，index={cam_idx}, backend={backend_name}")
                        return cap
                if cap is not None:
                    cap.release()

        raise RuntimeError("無法開啟相機。請確認攝影機已連接且未被其他程式占用。")

    def trigger_switch_camera(self):
        print("[INFO] 收到切換相機請求")

        def do_switch():
            base_order = self._build_camera_order()
            cur = self.current_camera_index
            if cur in base_order:
                cur_pos = base_order.index(cur)
                scan_order = base_order[cur_pos + 1:] + base_order[:cur_pos + 1]
            else:
                scan_order = base_order

            print(f"[INFO] 切換相機掃描順序: {scan_order}")

            try:
                new_cap = self._open_camera(camera_order=scan_order)
            except Exception as e:
                print(f"[WARN] 切換相機失敗：{e}")
                return

            new_cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            new_cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

            with self.cap_lock:
                old_cap = self.cap
                self.cap = new_cap

            try:
                old_cap.release()
            except Exception:
                pass

        threading.Thread(target=do_switch, daemon=True).start()

    def on_result(self, d):
        global global_result
        try:
            if 'result_ts' not in d:
                d['result_ts'] = int(time.time() * 1000)
            
            # --- 自動產生筆畫錯誤文字 ---
            if d.get("correct") is False:
                wrong_list = set()
                
                details = d.get("reason", {}).get("details", {})
                swaps = details.get("suspected_swaps_1based", [])
                if swaps:
                    # 只顯示最可能的一組對調，避免訊息過度擴張
                    s = swaps[0]
                    if isinstance(s, dict):
                        wrong_list.add(int(s.get("a", 0)))
                        wrong_list.add(int(s.get("b", 0)))
                    elif isinstance(s, list):
                        wrong_list.add(int(s[0]))
                        wrong_list.add(int(s[1]))
                
                w_idx = d.get("wrong_idx", -1)
                if isinstance(w_idx, list):
                    for i in w_idx: wrong_list.add(int(i) + 1)
                elif isinstance(w_idx, int) and w_idx >= 0:
                    wrong_list.add(w_idx + 1)
                
                if wrong_list:
                    sorted_w = sorted(list(wrong_list))
                    str_nums = "、".join(map(str, sorted_w))
                    d["message"] = f"第 {str_nums} 筆畫錯誤"

            with data_lock:
                global_result = d
            print(f"[INFO] 分析結果更新: {d.get('status')} / {d.get('message', '')}")
        except Exception as e:
            print(f"[ERROR] 處理結果時發生錯誤: {e}")

    def trigger_auto_request(self):
        global global_target_char, global_target_hex, global_target_ts
        print("[INFO] 收到 '下一題' 請求")

        # 從 hanzi/ 資料夾隨機抽一個不同的字
        hanzi_dir = standard_loader.RAW_HANZI_DIR
        candidates = [p.stem for p in hanzi_dir.glob("*.json") if p.stem != self.curr_char]
        if candidates:
            new_char = random.choice(candidates)
            new_hex = new_char.encode('utf-8').hex()
            new_ts = int(time.time() * 1000)
            self.curr_char = new_char
            self.curr_hex = new_hex
            self.curr_ts = new_ts
            with data_lock:
                global_target_char = new_char
                global_target_hex = new_hex
                global_target_ts = new_ts
                global_result["status"] = "WAIT"
            self.reset_canvas()
            print(f"[INFO] 切換到新題目：{new_char}")
        else:
            with data_lock:
                global_result["status"] = "WAIT"

    def trigger_send(self):
        self.is_recording = False
        print(f"\n[INFO] 正在處理 {len(self.strokes_data)} 個筆跡軌跡點...")

        if FRONT_STAGE_TEST_MODE:
            with data_lock:
                global_result.update({
                    "status": "DONE",
                    "correct": True,
                    "wrong_idx": -1,
                    "message": "前段測試模式：已收到筆跡資料（未進行評分）",
                    "result_ts": int(time.time() * 1000),
                })
            print("[INFO] 前段測試模式：跳過評分流程。")
            return
        
        if not self.curr_hex: self.curr_hex = self.curr_char.encode('utf-8').hex()

        # 通知 UI 進入分析中狀態
        with data_lock:
            global_result["status"] = "ANALYZING"

        threading.Thread(target=self._run_compare_analysis, daemon=True).start()

    def _segment_strokes_from_data(
        self,
        gap_tolerance: int = 2,
        min_points: int = 10,
        min_path_len: float = 25.0,
        min_bbox_diag: float = 10.0,
    ):
        strokes = []
        current = []
        in_stroke = False
        zero_run = 0

        def append_if_valid(stroke_pts):
            if len(stroke_pts) < min_points:
                return
            arr = np.array(stroke_pts, dtype=np.float32)
            diffs = arr[1:] - arr[:-1]
            path_len = float(np.linalg.norm(diffs, axis=1).sum()) if len(arr) > 1 else 0.0
            span = arr.max(axis=0) - arr.min(axis=0)
            bbox_diag = float(np.linalg.norm(span))

            center = arr.mean(axis=0)
            border_margin = 20.0
            near_border = (
                center[0] < (self.roi_x1 + border_margin)
                or center[0] > (self.roi_x2 - border_margin)
                or center[1] < (self.roi_y1 + border_margin)
                or center[1] > (self.roi_y2 - border_margin)
            )

            # 邊界附近出現的小抖動長按，視為假筆劃雜訊（例如右下角卡住）
            if near_border and path_len < 80.0 and bbox_diag < 30.0:
                return

            if path_len >= min_path_len and bbox_diag >= min_bbox_diag:
                strokes.append(stroke_pts)

        for _, x, y, pen_state in self.strokes_data:
            pen = int(pen_state)
            if pen == 1:
                if not in_stroke:
                    in_stroke = True
                    current = []
                    zero_run = 0
                current.append((float(x), float(y)))
                zero_run = 0
            else:
                if in_stroke:
                    zero_run += 1
                    if zero_run > gap_tolerance:
                        in_stroke = False
                        zero_run = 0
                        append_if_valid(current)
                        current = []

        if in_stroke:
            append_if_valid(current)

        return strokes

    def _run_compare_analysis(self):
        global global_std_json
        try:
            if compare_core is None:
                raise RuntimeError("compare.py 無法載入，請確認 pandas / numpy 依賴完整")

            user_strokes = self._segment_strokes_from_data()
            std_entry = standard_loader.load_standard_entry(self.curr_char)
            std_strokes = standard_loader.load_standard(self.curr_char)

            ts = int(time.time() * 1000)
            dt = time.strftime("%Y%m%d_%H%M%S", time.localtime(ts / 1000))
            ms = ts % 1000
            char_safe = "".join(ch if ch not in '\\/:*?\"<>|' else "_" for ch in self.curr_char)

            with data_lock:
                global_std_json = std_entry

            result = compare_core.verify_character(
                user_strokes=user_strokes,
                std_strokes=std_strokes,
                target_char=self.curr_char,
            )

            status_tag = "PASS" if bool(result.get("correct")) else "FAIL"
            base_name = f"{dt}_{ms:03d}_{char_safe}_{status_tag}"

            csv_path = os.path.join(SAVE_DIR, f"{base_name}.csv")
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["timestamp", "x", "y", "pen_state"])
                writer.writerows(self.strokes_data)

            user_img = _draw_user_strokes_image(user_strokes, size=320)
            user_img_path = os.path.join(SAVE_DIR, f"{base_name}_user.png")
            ok, buf = cv2.imencode(".png", user_img)
            if ok:
                with open(user_img_path, "wb") as _f:
                    _f.write(buf.tobytes())

            result["status"] = "DONE"
            result["result_ts"] = ts
            result["saved_csv"] = csv_path
            result["saved_user_image"] = user_img_path

            if "wrong_idx" not in result:
                result["wrong_idx"] = -1

            self.on_result(result)

        except Exception as e:
            print(f"[ERROR] 評分流程失敗: {e}")
            self.on_result({
                "status": "DONE",
                "correct": False,
                "wrong_idx": -1,
                "message": f"評分失敗：{e}",
                "reason": {"failed_rule": "ANALYSIS_ERROR"},
                "result_ts": int(time.time() * 1000),
            })

    def trigger_record(self):
        self.is_recording = not self.is_recording
        print(f"[INFO] 錄影狀態切換: {'開始' if self.is_recording else '停止'}")
        if self.is_recording:
            if AUTO_CALIBRATE_ON_RECORD:
                ok = self._auto_calibrate_homography_from_roi()
                if not ok and self.M is None:
                    print("[WARN] 尚無可用校正矩陣，座標可能偏移。")
            self.reset_canvas()
            self.strokes_data = []
            self.start_t = time.time()
            self.stroke_count = 0

    def trigger_undo(self):
        if len(self.history) > 1:
            self.history.pop()
            self.paint_canvas = self.history[-1].copy()
            self.idx_history.pop()
            self.strokes_data = self.strokes_data[:self.idx_history[-1]]
            if self.stroke_count > 0: self.stroke_count -= 1
            print("[INFO] 已撤銷最後一筆 (Undo)")

    def trigger_reset(self):
        print("[INFO] 清除畫布 (Reset)")
        self.reset_canvas()

    def reset_canvas(self):
        if self.paint_canvas is not None:
            self.paint_canvas = np.zeros_like(self.paint_canvas)
        self.history = [] if self.paint_canvas is None else [self.paint_canvas.copy()]
        self.idx_history = [0]
        self.strokes_data = []
        self.stroke_count = 0

    def run(self):
        """主影像處理迴圈 (取代原先的 ROS Timer)"""
        print("[INFO] 影像處理引擎已啟動，按 Ctrl+C 結束程式。")
        while self.is_running:
            self.loop()
            # 暫停一下以控制 FPS 大約在 30 左右
            time.sleep(0.033)

        with self.cap_lock:
            self.cap.release()

    def loop(self):
        global global_frame
        start_time = time.time()
        with self.cap_lock:
            ret, frame = self.cap.read()
        if not ret: return
        frame = cv2.flip(frame, -1)
        
        if self.paint_canvas is None or self.paint_canvas.shape != frame.shape:
            self.paint_canvas = np.zeros_like(frame)
            self.history = [self.paint_canvas.copy()]
            self.idx_history = [0]
        
        roi = frame[self.roi_y1:self.roi_y2, self.roi_x1:self.roi_x2]
        gray_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        
        # 假設白紙的亮度大於 130 (可依現場環境光源微調此數值)
        _, mask_paper = cv2.threshold(gray_roi, 130, 255, cv2.THRESH_BINARY)
        white_pixels = cv2.countNonZero(mask_paper)
        paper_ratio = white_pixels / self.roi_area

        if not self.is_recording:
            if not self.is_paper_ready:
                if paper_ratio > 0.85:
                    self.is_paper_ready = True
            else:
                if paper_ratio < 0.50:
                    self.is_paper_ready = False

        paper_ready_now = self.is_paper_ready or self.is_recording

        if paper_ready_now:
            box_color = (0, 255, 0)
            status_text = "Ready! Please write inside."
        else:
            box_color = (0, 0, 255)
            status_text = "Align paper inside the box..."
    
        # ====================================================
        # [升級] MediaPipe 手部追蹤與指尖動態遮罩
        # ====================================================
        # 1. 將影像轉為 RGB 餵給 MediaPipe（若可用）
        results = None
        if self.mediapipe_ready and self.hands is not None and self.mp_hands is not None:
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = self.hands.process(frame_rgb)

        # 2. 建立一個全黑的遮罩，用來限制 OpenCV 的搜尋範圍
        finger_mask = np.zeros(frame.shape[:2], dtype=np.uint8)
        
        # 預設搜尋半徑 (如果沒抓到手，就搜整個紙張 ROI)
        search_radius = -1 
        
        if results is not None and results.multi_hand_landmarks:
            for hand_landmarks in results.multi_hand_landmarks:
                # 取得食指指尖 (Landmark 8) 的座標
                lm8 = hand_landmarks.landmark[self.mp_hands.HandLandmark.INDEX_FINGER_TIP]
                h, w, _ = frame.shape
                finger_x, finger_y = int(lm8.x * w), int(lm8.y * h)
                
                # 在食指指尖周圍畫一個白色的圓 (半徑約 80 像素)
                # 這代表我們「只」在這個範圍內尋找筆頭！
                cv2.circle(finger_mask, (finger_x, finger_y), 80, 255, -1)
                search_radius = 80
               # ====================================================
                # 2. [新增] 在真實畫面上畫出「AI 可偵測範圍圈」！
                # 畫一個半徑 80 的粉紅色空心圓，並加上標示文字
                # ====================================================
                cv2.circle(frame, (finger_x, finger_y), 80, (255, 105, 180), 2) 
                cv2.putText(frame, "AI Search Zone", (finger_x - 50, finger_y - 90), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 105, 180), 2)
                
                # (可選) 畫出 MediaPipe 手部骨架
                if self.mp_draw is not None:
                    self.mp_draw.draw_landmarks(frame, hand_landmarks, self.mp_hands.HAND_CONNECTIONS) 
                
        else:
            # 如果 MediaPipe 沒抓到手，退回原本的防線：只看紙張 ROI 區域
            finger_mask[self.roi_y1:self.roi_y2, self.roi_x1:self.roi_x2] = 255

        # 3. 結合原本的 HSV 顏色過濾
        clean_frame = np.zeros_like(frame)
        clean_frame[self.roi_y1:self.roi_y2, self.roi_x1:self.roi_x2] = roi
        hsv = cv2.cvtColor(clean_frame, cv2.COLOR_BGR2HSV)
        
        # 產生初步的顏色遮罩
        color_mask = cv2.inRange(hsv, np.array([H_MIN, S_MIN, V_MIN]), np.array([H_MAX, S_MAX, V_MAX]))
        
        # 4. 【關鍵爆擊】將「顏色遮罩」與「指尖遮罩」做 AND 運算 (交集)
        # 只有「顏色對」且「在食指旁邊」的像素，才能存活下來！
        mask = cv2.bitwise_and(color_mask, finger_mask)
        
        mask = cv2.erode(mask, None, iterations=2)
        mask = cv2.dilate(mask, None, iterations=2)
        # ====================================================
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        msg = Point()
        cx, cy, tx, ty = 0, 0, -1, -1
        writing = False
        color = (100,100,100)
        curr_area = 0
        thr = BASE_THRESHOLD
        
        if cnts:
            c = max(cnts, key=cv2.contourArea)
            curr_area = cv2.contourArea(c)
            if curr_area > 50:
                M = cv2.moments(c)
                if M["m00"]:
                    cx = int(M["m10"]/M["m00"])
                    cy = int(M["m01"]/M["m00"])
                    tx, ty = float(cx), float(cy)
                    if self.M is not None:
                        pts = np.array([[[cx,cy]]], dtype="float32")
                        dst = cv2.perspectiveTransform(pts, self.M)
                        tx, ty = float(dst[0][0][0]), float(dst[0][0][1])
                    
                    delta = cx - (frame.shape[1]//2)
                    thr = max(100, BASE_THRESHOLD + delta*LINEAR_COMPENSATION)
                    
                    if not (-20<=tx<=660 and -20<=ty<=500):
                        msg.z=0.0
                    elif curr_area < thr:
                        msg.z=1.0; writing=True; color=(0,255,0)
                    else:
                        msg.z=0.0; color=(0,0,255)
                    msg.x, msg.y = tx, ty

                    if writing:
                        if paper_ready_now: # 錄製中保持可寫狀態，避免手遮擋導致中斷
                            if self.last_pos: 
                                cv2.line(self.paint_canvas, self.last_pos, (cx,cy), (0,255,255), 2)
                            self.last_pos = (cx,cy)
                        else:
                            self.last_pos = None
                    else: 
                        self.last_pos = None
                        
                    cv2.circle(frame, (cx,cy), 10, color, 2)

        # 筆畫過濾邏輯：只有連續 5 個 frame 都按下才算一筆
        if self.prev_z==1 and msg.z==0:
            self.history.append(self.paint_canvas.copy())
            self.idx_history.append(len(self.strokes_data))
            if len(self.history)>20: self.history.pop(0); self.idx_history.pop(0)
        
        # 雜訊過濾
        if msg.z == 1.0:
            self.curr_stroke_frames += 1
            if self.curr_stroke_frames == 5: 
                self.stroke_count += 1
        else:
            self.curr_stroke_frames = 0 

        self.prev_z = msg.z
        if self.is_recording:
            elapsed = time.time() - self.start_t
            self.strokes_data.append([round(elapsed,3), round(msg.x,2), round(msg.y,2), int(msg.z)])
            cv2.circle(frame, (610, 30), 10, (0,0,255), -1)

        comb = cv2.add(frame, self.paint_canvas)
        
        # 畫引導框與 UI 資訊
        cv2.rectangle(comb, (self.roi_x1, self.roi_y1), (self.roi_x2, self.roi_y2), box_color, 2)
        cv2.putText(comb, status_text, (self.roi_x1, self.roi_y1 - 10),cv2.FONT_HERSHEY_SIMPLEX, 0.6, box_color, 2)
        cv2.putText(comb, f"Paper Coverage: {paper_ratio*100:.1f}%",(self.roi_x1, self.roi_y2 + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, box_color, 1)
        pen_text = "Pen: DOWN" if msg.z == 1.0 else "Pen: UP"
        pen_color = (0, 255, 0) if msg.z == 1.0 else (0, 0, 255)
        cv2.putText(comb, pen_text, (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, pen_color, 2)
        
        end_time = time.time()
        fps = 1.0 / (end_time - start_time) if (end_time - start_time) > 0 else 0
        cv2.putText(comb, f"FPS: {int(fps)}", (10, 30),cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255,255,255), 2)
        
        with data_lock:
            global_frame = comb.copy()

def main():
    global _tracker_ref
    
    # 1. 啟動 Flask 背景執行緒
    print("[INFO] 正在啟動 Flask Web 伺服器 (http://0.0.0.0:5000) ...")
    t = threading.Thread(target=lambda: app.run(host="0.0.0.0", port=5000, debug=False, threaded=True), daemon=True)
    t.start()
    
    # 2. 實例化 Tracker
    tracker = PenTracker()
    _tracker_ref = tracker
    
    # 3. 在主執行緒執行 OpenCV 迴圈
    try: 
        tracker.run()
    except KeyboardInterrupt:
        print("\n[INFO] 接收到中斷訊號 (Ctrl+C)，正在關閉系統...")
    finally:
        tracker.is_running = False

if __name__ == "__main__":
    main()

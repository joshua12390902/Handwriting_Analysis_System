"""
tracker/pen_tracker.py — 主追蹤邏輯

包含 PenTracker class：
- 攝影機讀取與筆跡偵測主迴圈 (loop)
- 筆畫錄製、undo、reset
- 評分觸發與結果處理
- 換題 (trigger_auto_request)
"""
import csv
import os
import random
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

try:
    import mediapipe as mp
except ImportError:
    mp = None

import state
import standard_loader
from tracker.camera import build_camera_order, open_camera
from tracker.calibration import auto_calibrate, load_homography
from web.viz import draw_user_strokes

try:
    import compare as compare_core
except Exception:
    compare_core = None


# ── 設定常數 ──────────────────────────────────────────────────────────

# 藍色筆頭 HSV 範圍
H_MIN, S_MIN, V_MIN = 90, 70, 50
H_MAX, S_MAX, V_MAX = 130, 255, 255

BASE_THRESHOLD = 400          # 輪廓面積門檻（畫面中央）
LINEAR_COMPENSATION = 2.6     # 往右每像素補償量

FRONT_STAGE_TEST_MODE   = False   # True → 跳過評分，僅測試前端流程
AUTO_CALIBRATE_ON_RECORD = True   # True → 每次按 Record 自動校正 homography

SAVE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "saved_writings")
os.makedirs(SAVE_DIR, exist_ok=True)


# ── 簡易 Point 替代 ROS geometry_msgs.msg.Point ───────────────────────

class _Point:
    def __init__(self, x: float = -1.0, y: float = -1.0, z: float = 0.0):
        self.x, self.y, self.z = float(x), float(y), float(z)


# ── PenTracker ────────────────────────────────────────────────────────

class PenTracker:

    # ROI 綠框（與 UI 中顯示的框一致）
    ROI_X1, ROI_Y1 = 50, 50
    ROI_X2, ROI_Y2 = 590, 430

    def __init__(self):
        self.is_running = True
        self.cap_lock = threading.Lock()

        # 相機
        self.current_camera_index = -1
        self.cap = open_camera()
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        # ROI 尺寸
        self.roi_area = (self.ROI_X2 - self.ROI_X1) * (self.ROI_Y2 - self.ROI_Y1)
        self.is_paper_ready = False

        # Homography
        project_root = os.path.dirname(os.path.dirname(__file__))
        self._h_save_path = os.path.join(project_root, "homography.npy")
        self.M = load_homography(project_root)

        # MediaPipe
        self.mp_hands = None
        self.hands = None
        self.mp_draw = None
        self.mediapipe_ready = False
        self._init_mediapipe()

        # 畫布 & 錄製狀態
        self.paint_canvas: Optional[np.ndarray] = None
        self.last_pos: Optional[Tuple[int, int]] = None
        self.is_recording = False
        self.strokes_data: List = []
        self.start_t: float = 0.0
        self.prev_z: float = 0.0
        self.stroke_count: int = 0
        self.curr_stroke_frames: int = 0
        self.history: List[np.ndarray] = []
        self.idx_history: List[int] = []

        # 目前題目
        self.curr_char = state.global_target_char
        self.curr_hex  = state.global_target_hex
        self.curr_ts   = state.global_target_ts

        self.reset_canvas()

    # ── 初始化 ────────────────────────────────────────────────────────

    def _init_mediapipe(self) -> None:
        if mp is None:
            print("[WARN] mediapipe 未安裝，使用 HSV+ROI 偵測。")
            return
        try:
            self.mp_hands = mp.solutions.hands
            self.hands = self.mp_hands.Hands(
                static_image_mode=False,
                max_num_hands=1,
                min_detection_confidence=0.7,
                min_tracking_confidence=0.7,
            )
            self.mp_draw = mp.solutions.drawing_utils
            self.mediapipe_ready = True
            print("[INFO] MediaPipe Hands 初始化成功。")
        except Exception as e:
            print(f"[WARN] MediaPipe Hands 無法啟用，改用 HSV+ROI。原因: {e}")

    # ── 相機切換 ──────────────────────────────────────────────────────

    def trigger_switch_camera(self) -> None:
        print("[INFO] 收到切換相機請求")

        def _do():
            scan_order = build_camera_order(self.current_camera_index)
            try:
                new_cap = open_camera(camera_order=scan_order)
            except Exception as e:
                print(f"[WARN] 切換相機失敗：{e}")
                return
            new_cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            new_cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            with self.cap_lock:
                old_cap, self.cap = self.cap, new_cap
            try:
                old_cap.release()
            except Exception:
                pass

        threading.Thread(target=_do, daemon=True).start()

    # ── 透視校正 ──────────────────────────────────────────────────────

    def _try_auto_calibrate(self) -> None:
        with self.cap_lock:
            ret, frame = self.cap.read()
        if not ret:
            print("[WARN] 自動校正失敗：無法讀取相機畫面")
            return
        frame = cv2.flip(frame, -1)
        roi = (self.ROI_X1, self.ROI_Y1, self.ROI_X2, self.ROI_Y2)
        result = auto_calibrate(frame, roi, self._h_save_path)
        if result is not None:
            self.M = result

    # ── 畫布管理 ──────────────────────────────────────────────────────

    def reset_canvas(self) -> None:
        if self.paint_canvas is not None:
            self.paint_canvas = np.zeros_like(self.paint_canvas)
        self.history      = [] if self.paint_canvas is None else [self.paint_canvas.copy()]
        self.idx_history  = [0]
        self.strokes_data = []
        self.stroke_count = 0

    def trigger_record(self) -> None:
        self.is_recording = not self.is_recording
        print(f"[INFO] 錄影狀態切換: {'開始' if self.is_recording else '停止'}")
        if self.is_recording:
            if AUTO_CALIBRATE_ON_RECORD:
                self._try_auto_calibrate()
            self.reset_canvas()
            self.start_t      = time.time()
            self.stroke_count = 0

    def trigger_undo(self) -> None:
        if len(self.history) > 1:
            self.history.pop()
            self.paint_canvas = self.history[-1].copy()
            self.idx_history.pop()
            self.strokes_data = self.strokes_data[: self.idx_history[-1]]
            if self.stroke_count > 0:
                self.stroke_count -= 1
            print("[INFO] 已撤銷最後一筆 (Undo)")

    def trigger_reset(self) -> None:
        print("[INFO] 清除畫布 (Reset)")
        self.reset_canvas()

    # ── 換題 ─────────────────────────────────────────────────────────

    def trigger_auto_request(self) -> None:
        print("[INFO] 收到下一題請求")
        hanzi_dir = standard_loader.RAW_HANZI_DIR
        candidates = [p.stem for p in hanzi_dir.glob("*.json") if p.stem != self.curr_char]
        if candidates:
            new_char = random.choice(candidates)
            new_hex  = new_char.encode("utf-8").hex()
            new_ts   = int(time.time() * 1000)
            self.curr_char = new_char
            self.curr_hex  = new_hex
            self.curr_ts   = new_ts
            with state.data_lock:
                state.global_target_char = new_char
                state.global_target_hex  = new_hex
                state.global_target_ts   = new_ts
                state.global_result["status"] = "WAIT"
            self.reset_canvas()
            print(f"[INFO] 切換到新題目：{new_char}")
        else:
            with state.data_lock:
                state.global_result["status"] = "WAIT"

    # ── 評分 ─────────────────────────────────────────────────────────

    def trigger_send(self) -> None:
        self.is_recording = False
        print(f"\n[INFO] 正在處理 {len(self.strokes_data)} 個筆跡軌跡點...")

        if FRONT_STAGE_TEST_MODE:
            with state.data_lock:
                state.global_result.update({
                    "status":     "DONE",
                    "correct":    True,
                    "wrong_idx":  -1,
                    "message":    "前段測試模式：已收到筆跡資料（未進行評分）",
                    "result_ts":  int(time.time() * 1000),
                })
            return

        if not self.curr_hex:
            self.curr_hex = self.curr_char.encode("utf-8").hex()

        with state.data_lock:
            state.global_result["status"] = "ANALYZING"

        threading.Thread(target=self._run_compare_analysis, daemon=True).start()

    def _segment_strokes_from_data(
        self,
        gap_tolerance: int   = 2,
        min_points:    int   = 10,
        min_path_len:  float = 25.0,
        min_bbox_diag: float = 10.0,
    ) -> List[List[Tuple[float, float]]]:
        strokes: List[List[Tuple[float, float]]] = []
        current: List[Tuple[float, float]] = []
        in_stroke = False
        zero_run  = 0
        border_margin = 20.0

        def _append_if_valid(pts: List[Tuple[float, float]]) -> None:
            if len(pts) < min_points:
                return
            arr = np.array(pts, dtype=np.float32)
            path_len  = float(np.linalg.norm(arr[1:] - arr[:-1], axis=1).sum()) if len(arr) > 1 else 0.0
            bbox_diag = float(np.linalg.norm(arr.max(axis=0) - arr.min(axis=0)))
            center    = arr.mean(axis=0)
            near_border = (
                center[0] < self.ROI_X1 + border_margin
                or center[0] > self.ROI_X2 - border_margin
                or center[1] < self.ROI_Y1 + border_margin
                or center[1] > self.ROI_Y2 - border_margin
            )
            if near_border and path_len < 80.0 and bbox_diag < 30.0:
                return
            if path_len >= min_path_len and bbox_diag >= min_bbox_diag:
                strokes.append(pts)

        for _, x, y, pen_state in self.strokes_data:
            if int(pen_state) == 1:
                if not in_stroke:
                    in_stroke = True
                    current   = []
                    zero_run  = 0
                current.append((float(x), float(y)))
                zero_run = 0
            else:
                if in_stroke:
                    zero_run += 1
                    if zero_run > gap_tolerance:
                        in_stroke = False
                        zero_run  = 0
                        _append_if_valid(current)
                        current = []

        if in_stroke:
            _append_if_valid(current)

        return strokes

    def _run_compare_analysis(self) -> None:
        try:
            if compare_core is None:
                raise RuntimeError("compare.py 無法載入，請確認 pandas / numpy 依賴完整")

            user_strokes = self._segment_strokes_from_data()
            std_entry    = standard_loader.load_standard_entry(self.curr_char)
            std_strokes  = standard_loader.load_standard(self.curr_char)

            ts      = int(time.time() * 1000)
            dt      = time.strftime("%Y%m%d_%H%M%S", time.localtime(ts / 1000))
            ms      = ts % 1000
            char_s  = "".join(c if c not in r'\/:*?"<>|' else "_" for c in self.curr_char)

            with state.data_lock:
                state.global_std_json = std_entry

            result = compare_core.verify_character(
                user_strokes=user_strokes,
                std_strokes=std_strokes,
                target_char=self.curr_char,
            )

            status_tag = "PASS" if result.get("correct") else "FAIL"
            base_name  = f"{dt}_{ms:03d}_{char_s}_{status_tag}"

            # 存 CSV
            csv_path = os.path.join(SAVE_DIR, f"{base_name}.csv")
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerows(
                    [["timestamp", "x", "y", "pen_state"]] + list(self.strokes_data)
                )

            # 存使用者筆畫圖
            img = draw_user_strokes(user_strokes)
            img_path = os.path.join(SAVE_DIR, f"{base_name}_user.png")
            ok, buf = cv2.imencode(".png", img)
            if ok:
                with open(img_path, "wb") as fimg:
                    fimg.write(buf.tobytes())

            result.update({
                "status":           "DONE",
                "result_ts":        ts,
                "saved_csv":        csv_path,
                "saved_user_image": img_path,
            })
            result.setdefault("wrong_idx", -1)

            with state.data_lock:
                state.global_result = result
            print(f"[INFO] 分析結果：{result.get('status')} / {result.get('message', '')}")

        except Exception as e:
            print(f"[ERROR] 評分流程失敗: {e}")
            with state.data_lock:
                state.global_result = {
                    "status":    "DONE",
                    "correct":   False,
                    "wrong_idx": -1,
                    "message":   f"評分失敗：{e}",
                    "reason":    {"failed_rule": "ANALYSIS_ERROR"},
                    "result_ts": int(time.time() * 1000),
                }

    # ── 主迴圈 ────────────────────────────────────────────────────────

    def run(self) -> None:
        print("[INFO] 影像處理引擎已啟動，按 Ctrl+C 結束程式。")
        try:
            while self.is_running:
                self.loop()
                time.sleep(0.033)   # ~30 FPS
        finally:
            with self.cap_lock:
                self.cap.release()

    def loop(self) -> None:
        with self.cap_lock:
            ret, frame = self.cap.read()
        if not ret:
            return
        frame = cv2.flip(frame, -1)

        # 初始化畫布
        if self.paint_canvas is None or self.paint_canvas.shape != frame.shape:
            self.paint_canvas = np.zeros_like(frame)
            self.history      = [self.paint_canvas.copy()]
            self.idx_history  = [0]

        # ── 紙張就緒偵測 ──────────────────────────────────────────────
        roi_img    = frame[self.ROI_Y1:self.ROI_Y2, self.ROI_X1:self.ROI_X2]
        gray_roi   = cv2.cvtColor(roi_img, cv2.COLOR_BGR2GRAY)
        _, mask_paper = cv2.threshold(gray_roi, 130, 255, cv2.THRESH_BINARY)
        paper_ratio = cv2.countNonZero(mask_paper) / self.roi_area

        if not self.is_recording:
            if not self.is_paper_ready:
                if paper_ratio > 0.85:
                    self.is_paper_ready = True
            else:
                if paper_ratio < 0.50:
                    self.is_paper_ready = False

        paper_ready_now = self.is_paper_ready or self.is_recording
        box_color   = (0, 255, 0) if paper_ready_now else (0, 0, 255)
        status_text = "Ready! Please write inside." if paper_ready_now else "Align paper inside the box..."

        # ── MediaPipe 手部追蹤 ────────────────────────────────────────
        mp_results = None
        if self.mediapipe_ready and self.hands is not None:
            mp_results = self.hands.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

        finger_mask = np.zeros(frame.shape[:2], dtype=np.uint8)
        if mp_results is not None and mp_results.multi_hand_landmarks:
            for hand_lm in mp_results.multi_hand_landmarks:
                lm8 = hand_lm.landmark[self.mp_hands.HandLandmark.INDEX_FINGER_TIP]
                h, w, _ = frame.shape
                fx, fy = int(lm8.x * w), int(lm8.y * h)
                cv2.circle(finger_mask, (fx, fy), 80, 255, -1)
                cv2.circle(frame, (fx, fy), 80, (255, 105, 180), 2)
                cv2.putText(frame, "AI Search Zone", (fx - 50, fy - 90),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 105, 180), 2)
                if self.mp_draw is not None:
                    self.mp_draw.draw_landmarks(frame, hand_lm, self.mp_hands.HAND_CONNECTIONS)
        else:
            finger_mask[self.ROI_Y1:self.ROI_Y2, self.ROI_X1:self.ROI_X2] = 255

        # ── HSV 顏色過濾 + 與指尖遮罩交集 ────────────────────────────
        clean = np.zeros_like(frame)
        clean[self.ROI_Y1:self.ROI_Y2, self.ROI_X1:self.ROI_X2] = roi_img
        hsv = cv2.cvtColor(clean, cv2.COLOR_BGR2HSV)
        color_mask = cv2.inRange(
            hsv,
            np.array([H_MIN, S_MIN, V_MIN]),
            np.array([H_MAX, S_MAX, V_MAX]),
        )
        mask = cv2.bitwise_and(color_mask, finger_mask)
        mask = cv2.erode(mask, None, iterations=2)
        mask = cv2.dilate(mask, None, iterations=2)

        # ── 輪廓偵測 & 筆頭定位 ───────────────────────────────────────
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        msg = _Point()
        cx = cy = 0
        writing = False
        color   = (100, 100, 100)

        if cnts:
            c = max(cnts, key=cv2.contourArea)
            area = cv2.contourArea(c)
            if area > 50:
                moments = cv2.moments(c)
                if moments["m00"]:
                    cx = int(moments["m10"] / moments["m00"])
                    cy = int(moments["m01"] / moments["m00"])
                    tx, ty = float(cx), float(cy)

                    if self.M is not None:
                        dst = cv2.perspectiveTransform(
                            np.array([[[cx, cy]]], dtype="float32"), self.M
                        )
                        tx, ty = float(dst[0][0][0]), float(dst[0][0][1])

                    delta = cx - (frame.shape[1] // 2)
                    thr   = max(100, BASE_THRESHOLD + delta * LINEAR_COMPENSATION)

                    if not (-20 <= tx <= 660 and -20 <= ty <= 500):
                        msg.z = 0.0
                    elif area < thr:
                        msg.z = 1.0; writing = True; color = (0, 255, 0)
                    else:
                        msg.z = 0.0; color = (0, 0, 255)
                    msg.x, msg.y = tx, ty

                    if writing and paper_ready_now:
                        if self.last_pos:
                            cv2.line(self.paint_canvas, self.last_pos, (cx, cy), (0, 255, 255), 2)
                        self.last_pos = (cx, cy)
                    else:
                        self.last_pos = None

                    cv2.circle(frame, (cx, cy), 10, color, 2)
                else:
                    self.last_pos = None
            else:
                self.last_pos = None
        else:
            self.last_pos = None

        # ── 筆畫歷史 & 雜訊過濾 ───────────────────────────────────────
        if self.prev_z == 1 and msg.z == 0:
            self.history.append(self.paint_canvas.copy())
            self.idx_history.append(len(self.strokes_data))
            if len(self.history) > 20:
                self.history.pop(0)
                self.idx_history.pop(0)

        if msg.z == 1.0:
            self.curr_stroke_frames += 1
            if self.curr_stroke_frames == 5:
                self.stroke_count += 1
        else:
            self.curr_stroke_frames = 0

        self.prev_z = msg.z

        # ── 錄製資料 ──────────────────────────────────────────────────
        if self.is_recording:
            elapsed = time.time() - self.start_t
            self.strokes_data.append(
                [round(elapsed, 3), round(msg.x, 2), round(msg.y, 2), int(msg.z)]
            )
            cv2.circle(frame, (610, 30), 10, (0, 0, 255), -1)  # 錄影指示點

        # ── 合成畫面並推送 ────────────────────────────────────────────
        comb = cv2.add(frame, self.paint_canvas)
        cv2.rectangle(comb, (self.ROI_X1, self.ROI_Y1), (self.ROI_X2, self.ROI_Y2), box_color, 2)
        cv2.putText(comb, status_text, (self.ROI_X1, self.ROI_Y1 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, box_color, 2)
        cv2.putText(comb, f"Paper: {paper_ratio*100:.1f}%", (self.ROI_X1, self.ROI_Y2 + 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, box_color, 1)
        pen_color = (0, 255, 0) if msg.z == 1.0 else (0, 0, 255)
        cv2.putText(comb, "Pen: DOWN" if msg.z == 1.0 else "Pen: UP",
                    (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, pen_color, 2)

        with state.data_lock:
            state.global_frame = comb.copy()

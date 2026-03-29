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
    from mediapipe.tasks import python as mp_tasks
    from mediapipe.tasks.python import vision as mp_vision
except ImportError:
    mp = None
    mp_tasks = None
    mp_vision = None

import state
import standard_loader
from tracker.camera import build_camera_order, open_camera
from tracker.calibration import manual_calibrate
from web.viz import draw_user_strokes

try:
    import compare as compare_core
except Exception:
    compare_core = None

try:
    import llm_chat as _llm_chat
    _LLM_OK = True
except Exception:
    _llm_chat = None
    _LLM_OK = False


# ── 設定常數 ──────────────────────────────────────────────────────────

# 藍色筆頭 HSV 範圍
H_MIN, S_MIN, V_MIN = 90, 70, 50
H_MAX, S_MAX, V_MAX = 130, 255, 255

BASE_THRESHOLD = 400          # 輪廓面積門檻（畫面中央）
LINEAR_COMPENSATION = 2.6     # 往右每像素補償量
MP_SEARCH_RADIUS = 50         # MediaPipe 搜尋半徑（像素）
RISE_THRESHOLD   = -105       # 後三指 Y 位移門檻，小於此值 → 下筆姿勢
PEN_EXTEND       = 0.25       # 食指方向延伸比例（搜尋圈超出指尖多遠）

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
        self.cap, self.current_camera_index = open_camera()
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        # ROI 尺寸
        self.roi_area = (self.ROI_X2 - self.ROI_X1) * (self.ROI_Y2 - self.ROI_Y1)
        self.is_paper_ready = False

        # Homography
        # Homography
        project_root = os.path.dirname(os.path.dirname(__file__))
        self._h_save_path = os.path.join(project_root, "homography.npy")
        
        # 加上這段直接讀取的邏輯
        if os.path.exists(self._h_save_path):
            self.M = np.load(self._h_save_path)
            print("[INFO] 載入既有的 homography 矩陣。")
        else:
            self.M = None
            

        # MediaPipe
        self.hand_detector = None
        self._mp_timestamp: int = 0
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

        # Hysteresis pen state machine
        self._pen_state: bool = False   # 目前確認的筆狀態（True=下筆）
        self._pen_raw:   bool = False   # 上一幀的原始訊號
        self._pen_confirm: int = 0      # 連續同方向幀數

        # 目前題目
        target = state.app_state.snapshot_target()
        self.curr_char = target["target_char"]
        self.curr_hex  = target["target_hex"]
        self.curr_ts   = target["ts"]

        self.reset_canvas()

    # ── 初始化 ────────────────────────────────────────────────────────

    # 手部骨架連線（MediaPipe 21 個關鍵點的連線對）
    HAND_CONNECTIONS = [
        (0,1),(1,2),(2,3),(3,4),
        (0,5),(5,6),(6,7),(7,8),
        (5,9),(9,10),(10,11),(11,12),
        (9,13),(13,14),(14,15),(15,16),
        (13,17),(17,18),(18,19),(19,20),
        (0,17),
    ]

    def _init_mediapipe(self) -> None:
        if mp is None or mp_tasks is None:
            print("[WARN] mediapipe 未安裝，使用 HSV+ROI 偵測。")
            return
        try:
            model_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), "hand_landmarker.task"
            )
            if not os.path.exists(model_path):
                print(f"[WARN] 找不到 {model_path}，無法啟用 MediaPipe。")
                return
            base_opts = mp_tasks.BaseOptions(model_asset_path=model_path)
            options   = mp_vision.HandLandmarkerOptions(
                base_options=base_opts,
                running_mode=mp_vision.RunningMode.VIDEO,
                num_hands=1,
                min_hand_detection_confidence=0.7,
                min_hand_presence_confidence=0.7,
                min_tracking_confidence=0.7,
            )
            self.hand_detector = mp_vision.HandLandmarker.create_from_options(options)
            self.mediapipe_ready = True
            print("[INFO] MediaPipe HandLandmarker 初始化成功。")
        except Exception as e:
            print(f"[WARN] MediaPipe HandLandmarker 無法啟用，改用 HSV+ROI。原因: {e}")

    # ── 相機切換 ──────────────────────────────────────────────────────

    def trigger_switch_camera(self) -> None:
        print("[INFO] 收到切換相機請求")

        def _do():
            scan_order = build_camera_order(self.current_camera_index)
            # 排除目前正在用的相機，避免只有一台時切到自己然後壞掉
            scan_order = [i for i in scan_order if i != self.current_camera_index]
            if not scan_order:
                print("[WARN] 只有一台相機，無法切換")
                return
            try:
                new_cap, new_idx = open_camera(camera_order=scan_order)
            except Exception as e:
                print(f"[WARN] 切換相機失敗（可能只有一台相機）：{e}")
                return
            new_cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            new_cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            with self.cap_lock:
                old_cap, self.cap = self.cap, new_cap
                self.current_camera_index = new_idx
            try:
                old_cap.release()
            except Exception:
                pass

        threading.Thread(target=_do, daemon=True).start()

    # ── 透視校正 ──────────────────────────────────────────────────────

    def _try_auto_calibrate(self) -> None:
        # 直接使用 UI 上的綠框作為紙張邊界，放棄影像辨識找角點
        roi = (self.ROI_X1, self.ROI_Y1, self.ROI_X2, self.ROI_Y2)
        self.M = manual_calibrate(roi, self._h_save_path)

    # ── 畫布管理 ──────────────────────────────────────────────────────

    def reset_canvas(self) -> None:
        if self.paint_canvas is not None:
            self.paint_canvas = np.zeros_like(self.paint_canvas)
        self.history      = [] if self.paint_canvas is None else [self.paint_canvas.copy()]
        self.idx_history  = [0]
        self.strokes_data = []
        self.stroke_count = 0
        self._pen_state   = False
        self._pen_raw     = False
        self._pen_confirm = 0

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

        # 優先使用學生對話中指定的字
        requested = state.app_state.pop_requested_char()

        if requested:
            new_char = requested
            print(f"[INFO] 使用學生指定字：{new_char}")
        else:
            hanzi_dir  = standard_loader.RAW_HANZI_DIR
            candidates = [p.stem for p in hanzi_dir.glob("*.json") if p.stem != self.curr_char]
            if not candidates:
                state.app_state.update_result(status="WAIT")
                return
            new_char = random.choice(candidates)
            print(f"[INFO] 隨機切換到：{new_char}")

        new_hex = new_char.encode("utf-8").hex()
        new_ts  = int(time.time() * 1000)
        self.curr_char = new_char
        self.curr_hex  = new_hex
        self.curr_ts   = new_ts
        state.app_state.set_target(new_char, new_hex, new_ts)
        state.app_state.reset_result(status="WAIT")
        self.reset_canvas()

    # ── 評分 ─────────────────────────────────────────────────────────

    def trigger_send(self) -> None:
        self.is_recording = False
        print(f"\n[INFO] 正在處理 {len(self.strokes_data)} 個筆跡軌跡點...")

        if FRONT_STAGE_TEST_MODE:
            state.app_state.update_result(
                status="DONE",
                correct=True,
                wrong_idx=-1,
                message="前段測試模式：已收到筆跡資料（未進行評分）",
                result_ts=int(time.time() * 1000),
            )
            return

        if not self.curr_hex:
            self.curr_hex = self.curr_char.encode("utf-8").hex()

        state.app_state.update_result(status="ANALYZING")

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

            state.app_state.set_std_json(std_entry)

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
                "llm_feedback":     "",
                "llm_loading":      _LLM_OK,
            })
            result.setdefault("wrong_idx", -1)
            result["target_char"] = self.curr_char

            state.app_state.replace_result(result)
            print(f"[INFO] 分析結果：{result.get('status')} / {result.get('message', '')}")

            # LLM 反饋（在同一 thread 裡，避免競爭）
            if _LLM_OK:
                try:
                    feedback = _llm_chat.get_feedback(result)
                    state.app_state.update_result(
                        llm_feedback=feedback,
                        llm_loading=False,
                    )
                    print(f"[INFO] LLM 反饋已產生")
                except Exception as e:
                    print(f"[WARN] LLM 反饋失敗: {e}")
                    state.app_state.update_result(llm_loading=False)

        except Exception as e:
            print(f"[ERROR] 評分流程失敗: {e}")
            state.app_state.replace_result({
                "status":    "DONE",
                "correct":   False,
                "wrong_idx": -1,
                "message":   f"評分失敗：{e}",
                "reason":    {"failed_rule": "ANALYSIS_ERROR"},
                "result_ts": int(time.time() * 1000),
            })

    # ── Hysteresis 輔助 ───────────────────────────────────────────────

    def _calc_back_finger_rise(self, landmarks, h: int) -> float:
        """計算後三指（中指、無名指、小指）相對手腕的垂直位移。
        回傳 avg_tip_y - wrist_y（像素）。
        值小（負）→ 手指比手腕高（下筆姿勢）
        值大（正）→ 手指比手腕低（提筆姿勢）
        """
        wrist_y   = landmarks[0].y * h
        avg_tip_y = sum(landmarks[i].y * h for i in [12, 16, 20]) / 3
        return avg_tip_y - wrist_y

    def _update_pen_hysteresis(self, raw_down: bool) -> None:
        """更新 pen-state 狀態機（含 hysteresis）。"""
        FRAMES_TO_DOWN = 3
        FRAMES_TO_UP   = 3
        if raw_down == self._pen_raw:
            self._pen_confirm += 1
        else:
            self._pen_raw     = raw_down
            self._pen_confirm = 1
        if not self._pen_state and raw_down and self._pen_confirm >= FRAMES_TO_DOWN:
            self._pen_state = True
        elif self._pen_state and not raw_down and self._pen_confirm >= FRAMES_TO_UP:
            self._pen_state = False

    def _force_pen_up(self) -> None:
        """無輪廓或面積太小時，直接送 pen-up 訊號給狀態機。"""
        self._update_pen_hysteresis(False)

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

        # ── MediaPipe 手部追蹤（核心）─────────────────────────────────
        mp_result    = None
        hand_detected = False
        if self.mediapipe_ready and self.hand_detector is not None:
            self._mp_timestamp += 33   # ~30 FPS
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_img   = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            mp_result = self.hand_detector.detect_for_video(mp_img, self._mp_timestamp)

        msg = _Point()
        cx = cy = 0
        writing = False
        color   = (100, 100, 100)

        if mp_result is not None and mp_result.hand_landmarks:
            landmarks = mp_result.hand_landmarks[0]   # 第一隻手的 21 個點
            h_f, w_f  = frame.shape[:2]
            hand_detected = True

            # 搜尋中心 = 沿食指方向延伸到筆尖位置
            lm5 = landmarks[5]   # INDEX_FINGER_MCP（指根）
            lm8 = landmarks[8]   # INDEX_FINGER_TIP（指尖）
            dx = (lm8.x - lm5.x) * w_f
            dy = (lm8.y - lm5.y) * h_f
            fx = int(lm8.x * w_f + dx * PEN_EXTEND)
            fy = int(lm8.y * h_f + dy * PEN_EXTEND)

            # 繪製手部骨架
            for a, b in self.HAND_CONNECTIONS:
                la, lb = landmarks[a], landmarks[b]
                pa = (int(la.x * w_f), int(la.y * h_f))
                pb = (int(lb.x * w_f), int(lb.y * h_f))
                cv2.line(frame, pa, pb, (200, 200, 200), 1, cv2.LINE_AA)
            for lm in landmarks:
                cv2.circle(frame, (int(lm.x * w_f), int(lm.y * h_f)), 3, (255, 255, 255), -1)

            cv2.circle(frame, (fx, fy), MP_SEARCH_RADIUS, (255, 105, 180), 2)
            cv2.putText(frame, "AI Tracking", (fx - 45, fy - MP_SEARCH_RADIUS - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 105, 180), 2)

            # ── HSV 藍色筆偵測（限定在 AI 引導區域內）──────────────────
            finger_mask = np.zeros(frame.shape[:2], dtype=np.uint8)
            cv2.circle(finger_mask, (fx, fy), MP_SEARCH_RADIUS, 255, -1)

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

            cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if cnts:
                c    = max(cnts, key=cv2.contourArea)
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

                        in_bounds = (-20 <= tx <= 660 and -20 <= ty <= 500)

                        # 雙重判斷：HSV 面積 + AI 手指蜷曲度
                        rise = self._calc_back_finger_rise(landmarks, h_f)
                        area_ok = area < thr
                        rise_ok = rise < RISE_THRESHOLD
                        raw_down = in_bounds and area_ok and rise_ok
                        self._update_pen_hysteresis(raw_down)

                        msg.x, msg.y = tx, ty
                        msg.z    = 1.0 if self._pen_state else 0.0
                        writing  = self._pen_state
                        color    = (0, 255, 0) if writing else (0, 0, 255)

                        cv2.circle(frame, (cx, cy), 10, color, 3)
                        cv2.putText(frame, f"A:{area:.0f} R:{rise:.0f}", (cx + 15, cy),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 0), 1)
                    else:
                        self._force_pen_up()
                else:
                    self._force_pen_up()
            else:
                self._force_pen_up()

        if not hand_detected:
            # 未偵測到手 → 不進行筆跡偵測，提示使用者
            self._force_pen_up()
            self.last_pos = None
            cv2.putText(frame, "Please show your hand", (150, 240),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

        # ── 畫線到畫布 ───────────────────────────────────────────────
        if writing and paper_ready_now:
            if self.last_pos:
                cv2.line(self.paint_canvas, self.last_pos, (cx, cy), (0, 255, 255), 2)
            self.last_pos = (cx, cy)
        elif not writing:
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

        state.app_state.set_frame(comb)

"""
tracker/pen_tracker.py — 主追蹤邏輯

包含 PenTracker class：
- 攝影機讀取與筆跡偵測主迴圈 (loop)
- 筆畫錄製、undo、reset
- 評分觸發與結果處理
- 換題 (trigger_auto_request)
- 動態四角定位與 18 步自動校正 (包含 2D 平面迴歸與冷卻時間)
- 動態筆頭顏色切換
- ⭐ 校正時光機 (Undo 回上一步功能)
"""
import csv
import json
import math
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


# ── 設定常數 ──────────────────────────────────────────────────────────

PEN_COLORS = {
    "blue": {
        "lower": np.array([29, 27, 109]),
        "upper": np.array([110, 143, 228])
    },
    "yellow": {
        "lower": np.array([19, 128, 138]),
        "upper": np.array([44, 255, 255])
    },
    "orange": {
        "lower": np.array([0, 168, 145]),
        "upper": np.array([16, 255, 255])
    },
    "pink": {
        "lower": np.array([148, 52, 99]),
        "upper": np.array([179, 142, 255])
    }
}

AREA_COEFFS = [0.0, 0.0, 400.0]  
RISE_COEFFS = [0.0, 0.0, -105.0] 
PEN_EXTEND       = 1.0        

MP_SEARCH_RADIUS = 200        

FRONT_STAGE_TEST_MODE   = False   
AUTO_CALIBRATE_ON_RECORD = True   

SAVE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "saved_writings")
os.makedirs(SAVE_DIR, exist_ok=True)

CALIB_FILE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "calibration.json")


# ── 校正與參數計算 ────────────────────────────────────────────────────

class CalibrationCollector:
    def __init__(self):
        self.hover_pts_area: List[List[float]] = []
        self.hover_areas: List[float] = []
        self.hover_pts_rise: List[List[float]] = []
        self.hover_rises: List[float] = []
        
        self.draw_pts_area: List[List[float]] = []
        self.draw_areas: List[float] = []
        self.draw_pts_rise: List[List[float]] = []
        self.draw_rises: List[float] = []
        
        self.pen_extends: List[float] = []
        
        # ⭐ 升級：時光機快照紀錄 (儲存每個步驟開始前的陣列長度)
        self.snapshots = []
        self.save_snapshot()

    def save_snapshot(self):
        """建立一個存檔點"""
        self.snapshots.append({
            "ha": len(self.hover_areas),
            "hr": len(self.hover_rises),
            "da": len(self.draw_areas),
            "dr": len(self.draw_rises),
            "pe": len(self.pen_extends)
        })

    def restore_current_snapshot(self):
        """清除剛錄到的髒資料，退回當前步驟的最開始狀態"""
        s = self.snapshots[-1]
        self.hover_pts_area = self.hover_pts_area[:s["ha"]]
        self.hover_areas    = self.hover_areas[:s["ha"]]
        self.hover_pts_rise = self.hover_pts_rise[:s["hr"]]
        self.hover_rises    = self.hover_rises[:s["hr"]]
        self.draw_pts_area  = self.draw_pts_area[:s["da"]]
        self.draw_areas     = self.draw_areas[:s["da"]]
        self.draw_pts_rise  = self.draw_pts_rise[:s["dr"]]
        self.draw_rises     = self.draw_rises[:s["dr"]]
        self.pen_extends    = self.pen_extends[:s["pe"]]

    def pop_and_restore(self):
        """捨棄當前步驟，退回上一個步驟的存檔點"""
        if len(self.snapshots) > 1:
            self.snapshots.pop()
        self.restore_current_snapshot()
        
    def add_hover_sample(self, pen_area: float, rise_value: Optional[float], cx: float, cy: float) -> None:
        self.hover_pts_area.append([cx, cy])
        self.hover_areas.append(pen_area)
        if rise_value is not None:
            self.hover_pts_rise.append([cx, cy])
            self.hover_rises.append(rise_value)

    def add_draw_sample(
        self, pen_area: float, rise_value: Optional[float], cx: float, cy: float,
        finger_tip: Optional[Tuple[float, float]], finger_base: Optional[Tuple[float, float]], pen_center: Tuple[float, float]
    ) -> None:
        self.draw_pts_area.append([cx, cy])
        self.draw_areas.append(pen_area)
        if rise_value is not None:
            self.draw_pts_rise.append([cx, cy])
            self.draw_rises.append(rise_value)
            
        if finger_tip is not None and finger_base is not None:
            vx = finger_tip[0] - finger_base[0]
            vy = finger_tip[1] - finger_base[1]
            v_len_sq = vx**2 + vy**2
            if v_len_sq > 0:
                rx = pen_center[0] - finger_tip[0]
                ry = pen_center[1] - finger_tip[1]
                extend_ratio = (rx * vx + ry * vy) / v_len_sq
                self.pen_extends.append(max(0.0, min(3.0, extend_ratio)))
        
    def calculate_parameters(self) -> Dict[str, Any]:
        if len(self.hover_areas) < 9 or len(self.draw_areas) < 9:
            raise ValueError("數據不足，請完整完成 18 步校正流程")

        def fit_plane(pts, vals, default_val):
            if len(pts) < 3:
                return np.array([0.0, 0.0, float(np.median(vals)) if len(vals) > 0 else default_val])
            try:
                X = np.c_[np.array(pts), np.ones(len(pts))]
                Z = np.array(vals)
                coeffs, _, _, _ = np.linalg.lstsq(X, Z, rcond=None)
                return coeffs
            except Exception:
                return np.array([0.0, 0.0, float(np.median(vals)) if len(vals) > 0 else default_val])

        h_area_coeffs = fit_plane(self.hover_pts_area, self.hover_areas, 400.0)
        d_area_coeffs = fit_plane(self.draw_pts_area, self.draw_areas, 200.0)
        area_coeffs = (h_area_coeffs + d_area_coeffs) / 2.0

        h_rise_coeffs = fit_plane(self.hover_pts_rise, self.hover_rises, RISE_COEFFS[2] + 20)
        d_rise_coeffs = fit_plane(self.draw_pts_rise, self.draw_rises, RISE_COEFFS[2] - 20)
        rise_coeffs = (h_rise_coeffs + d_rise_coeffs) / 2.0

        pen_extend = float(np.median(self.pen_extends)) if self.pen_extends else PEN_EXTEND
        
        return {
            "AREA_COEFFS": area_coeffs.tolist(),
            "RISE_COEFFS": rise_coeffs.tolist(),
            "PEN_EXTEND": pen_extend,
        }

def generate_calibration_ui_points(roi_x1: int, roi_y1: int, roi_x2: int, roi_y2: int) -> Dict[str, Tuple[int, int]]:
    x_positions = [roi_x1 + (roi_x2 - roi_x1) * 0.25, roi_x1 + (roi_x2 - roi_x1) * 0.50, roi_x1 + (roi_x2 - roi_x1) * 0.75]
    y_positions = [roi_y1 + (roi_y2 - roi_y1) * 0.25, roi_y1 + (roi_y2 - roi_y1) * 0.50, roi_y1 + (roi_y2 - roi_y1) * 0.75]
    
    point_names = ["top_left", "top_center", "top_right", "mid_left", "mid_center", "mid_right", "bottom_left", "bottom_center", "bottom_right"]
    
    points = {}
    for i, name in enumerate(point_names):
        px = int(x_positions[i % 3])
        py = int(y_positions[i // 3])
        points[f"hover_{name}"] = (px, py)
        points[f"draw_{name}"]  = (px, py)
        
    return points


class _Point:
    def __init__(self, x: float = -1.0, y: float = -1.0, z: float = 0.0):
        self.x, self.y, self.z = float(x), float(y), float(z)


# ── PenTracker ────────────────────────────────────────────────────────

class PenTracker:

    def __init__(self):
        self.is_running = True
        self.cap_lock = threading.Lock()

        self.roi_x1, self.roi_y1 = 50, 50
        self.roi_x2, self.roi_y2 = 590, 430
        self.roi_area = (self.roi_x2 - self.roi_x1) * (self.roi_y2 - self.roi_y1)
        self.is_paper_ready = False

        self.current_camera_index = -1
        self.cap = open_camera()
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        project_root = os.path.dirname(os.path.dirname(__file__))
        self._h_save_path = os.path.join(project_root, "homography.npy")
        
        if os.path.exists(self._h_save_path):
            self.M = np.load(self._h_save_path)
        else:
            self.M = None

        self.hand_detector = None
        self._mp_timestamp: int = 0
        self.mediapipe_ready = False
        self._init_mediapipe()

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

        self._pen_state: bool = False
        self._pen_raw:   bool = False
        self._pen_confirm: int = 0

        self.last_dx: float = -1.0      
        self.last_dy: float = 1.0

        self.hsv_lower = PEN_COLORS["blue"]["lower"]
        self.hsv_upper = PEN_COLORS["blue"]["upper"]

        self.curr_char = state.global_target_char
        self.curr_hex  = state.global_target_hex
        self.curr_ts   = state.global_target_ts

        self.calibration_mode = False
        self.calibration_collector = None
        self.calibration_points = {}
        self.current_calibration_idx = 0
        self.calib_hover_frames = 0
        
        self.calib_cooldown = 0
        
        self.corner_points = []
        self.stationary_pos = None

        self._load_calibration_params()
        self.reset_canvas()

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
            return
        try:
            model_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), "hand_landmarker.task"
            )
            if not os.path.exists(model_path):
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
        except Exception as e:
            print(f"[WARN] MediaPipe HandLandmarker 無法啟用：{e}")
            
    def set_pen_color(self, color_name: str) -> None:
        if color_name in PEN_COLORS:
            self.hsv_lower = PEN_COLORS[color_name]["lower"]
            self.hsv_upper = PEN_COLORS[color_name]["upper"]
            print(f"[INFO] 筆頭顏色已切換為：{color_name}")
    
    def _load_calibration_params(self):
        if os.path.exists(CALIB_FILE_PATH):
            try:
                with open(CALIB_FILE_PATH, 'r') as f:
                    params = json.load(f)
                global AREA_COEFFS, RISE_COEFFS, PEN_EXTEND
                
                if "AREA_COEFFS" in params:
                    AREA_COEFFS = params["AREA_COEFFS"]
                    RISE_COEFFS = params["RISE_COEFFS"]
                else:
                    AREA_COEFFS = [0.0, 0.0, params.get("BASE_THRESHOLD", 400.0)]
                    RISE_COEFFS = [0.0, 0.0, params.get("RISE_THRESHOLD", -105.0)]
                    
                PEN_EXTEND = params.get("PEN_EXTEND", PEN_EXTEND)
                
                self.roi_x1 = params.get("ROI_X1", self.roi_x1)
                self.roi_y1 = params.get("ROI_Y1", self.roi_y1)
                self.roi_x2 = params.get("ROI_X2", self.roi_x2)
                self.roi_y2 = params.get("ROI_Y2", self.roi_y2)
                self.roi_area = (self.roi_x2 - self.roi_x1) * (self.roi_y2 - self.roi_y1)
                print("[INFO] 成功載入使用者專屬校正檔與紙張範圍！")
            except Exception as e:
                print(f"[WARN] 讀取校正檔失敗：{e}")

    def trigger_calibration(self) -> None:
        print("[INFO] 進入校準模式：請先用筆尖定義紙張四個角落")
        self.calibration_mode = True
        self.calibration_collector = CalibrationCollector()
        self.corner_points = []
        self.stationary_pos = None
        self.calib_hover_frames = 0
        self.calib_cooldown = 0
        self.reset_canvas()
            
    def _finish_calibration(self) -> None:
        try:
            params = self.calibration_collector.calculate_parameters()
            print(f"[INFO] 校準完成！")
            
            global AREA_COEFFS, RISE_COEFFS, PEN_EXTEND
            AREA_COEFFS = params["AREA_COEFFS"]
            RISE_COEFFS = params["RISE_COEFFS"]
            PEN_EXTEND = params["PEN_EXTEND"]
            
            params["ROI_X1"] = self.roi_x1
            params["ROI_Y1"] = self.roi_y1
            params["ROI_X2"] = self.roi_x2
            params["ROI_Y2"] = self.roi_y2
            
            if "MP_SEARCH_RADIUS" in params:
                del params["MP_SEARCH_RADIUS"]
            
            with open(CALIB_FILE_PATH, 'w') as f:
                json.dump(params, f, indent=4)
            print(f"[INFO] 參數與紙張範圍已儲存至 {CALIB_FILE_PATH}")
            
            self.calibration_mode = False
        except Exception as e:
            print(f"[ERROR] 校準失敗：{e}")
            self.calibration_mode = False

    def trigger_switch_camera(self) -> None:
        def _do():
            scan_order = build_camera_order(self.current_camera_index)
            try:
                new_cap = open_camera(camera_order=scan_order)
            except Exception:
                return
            new_cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            new_cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            with self.cap_lock:
                old_cap, self.cap = self.cap, new_cap
            try: old_cap.release()
            except Exception: pass
        threading.Thread(target=_do, daemon=True).start()

    def _try_auto_calibrate(self) -> None:
        roi = (self.roi_x1, self.roi_y1, self.roi_x2, self.roi_y2)
        self.M = manual_calibrate(roi, self._h_save_path)

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
        if self.is_recording:
            if AUTO_CALIBRATE_ON_RECORD:
                self._try_auto_calibrate()
            self.reset_canvas()
            self.start_t      = time.time()
            self.stroke_count = 0

    def trigger_undo(self) -> None:
        # ⭐ 升級：處理校正模式下的 Undo (時光機功能)
        if self.calibration_mode:
            if len(self.corner_points) < 4:
                # 階段一：退回上一個角
                if len(self.corner_points) > 0:
                    self.corner_points.pop()
                    self.stationary_pos = None
                    self.calib_hover_frames = 0
                    print(f"[INFO] 已退回第 {len(self.corner_points)+1} 個角")
            else:
                # 階段二：退回上一個 18 步收集點
                if self.current_calibration_idx > 0:
                    self.current_calibration_idx -= 1
                    self.calib_hover_frames = 0
                    self.calib_cooldown = 0
                    self.stationary_pos = None
                    self.calibration_collector.pop_and_restore()
                    print(f"[INFO] 已退回步驟 {self.current_calibration_idx+1}/18")
                else:
                    # 如果已經是第 1 步，就直接退回四角定位階段
                    self.corner_points.pop()
                    self.stationary_pos = None
                    self.calib_hover_frames = 0
                    self.calibration_collector = CalibrationCollector()
                    print("[INFO] 退回四角定位階段")
            return

        # 寫字模式下的 Undo 邏輯
        if len(self.history) > 1:
            self.history.pop()
            self.paint_canvas = self.history[-1].copy()
            self.idx_history.pop()
            self.strokes_data = self.strokes_data[: self.idx_history[-1]]
            if self.stroke_count > 0:
                self.stroke_count -= 1

    def trigger_reset(self) -> None:
        self.reset_canvas()

    def trigger_auto_request(self) -> None:
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
        else:
            with state.data_lock:
                state.global_result["status"] = "WAIT"

    def trigger_send(self) -> None:
        self.is_recording = False
        if FRONT_STAGE_TEST_MODE:
            with state.data_lock:
                state.global_result.update({
                    "status":     "DONE",
                    "correct":    True,
                    "wrong_idx":  -1,
                    "message":    "前段測試模式：已收到筆跡資料",
                    "result_ts":  int(time.time() * 1000),
                })
            return

        if not self.curr_hex:
            self.curr_hex = self.curr_char.encode("utf-8").hex()

        with state.data_lock:
            state.global_result["status"] = "ANALYZING"
        threading.Thread(target=self._run_compare_analysis, daemon=True).start()

    def _segment_strokes_from_data(self, gap_tolerance: int = 2, min_points: int = 10, min_path_len: float = 25.0, min_bbox_diag: float = 10.0) -> List[List[Tuple[float, float]]]:
        strokes: List[List[Tuple[float, float]]] = []
        current: List[Tuple[float, float]] = []
        in_stroke = False
        zero_run  = 0
        border_margin = 20.0

        def _append_if_valid(pts: List[Tuple[float, float]]) -> None:
            if len(pts) < min_points: return
            arr = np.array(pts, dtype=np.float32)
            path_len  = float(np.linalg.norm(arr[1:] - arr[:-1], axis=1).sum()) if len(arr) > 1 else 0.0
            bbox_diag = float(np.linalg.norm(arr.max(axis=0) - arr.min(axis=0)))
            center    = arr.mean(axis=0)
            near_border = (center[0] < self.roi_x1 + border_margin or center[0] > self.roi_x2 - border_margin or center[1] < self.roi_y1 + border_margin or center[1] > self.roi_y2 - border_margin)
            if near_border and path_len < 80.0 and bbox_diag < 30.0: return
            if path_len >= min_path_len and bbox_diag >= min_bbox_diag: strokes.append(pts)

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
        if in_stroke: _append_if_valid(current)
        return strokes

    def _run_compare_analysis(self) -> None:
        try:
            if compare_core is None: raise RuntimeError("compare.py 無法載入")
            user_strokes = self._segment_strokes_from_data()
            std_entry    = standard_loader.load_standard_entry(self.curr_char)
            std_strokes  = standard_loader.load_standard(self.curr_char)
            ts      = int(time.time() * 1000)
            dt      = time.strftime("%Y%m%d_%H%M%S", time.localtime(ts / 1000))
            ms      = ts % 1000
            char_s  = "".join(c if c not in r'\/:*?"<>|' else "_" for c in self.curr_char)
            with state.data_lock: state.global_std_json = std_entry
            result = compare_core.verify_character(user_strokes=user_strokes, std_strokes=std_strokes, target_char=self.curr_char)
            status_tag = "PASS" if result.get("correct") else "FAIL"
            base_name  = f"{dt}_{ms:03d}_{char_s}_{status_tag}"
            csv_path = os.path.join(SAVE_DIR, f"{base_name}.csv")
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerows([["timestamp", "x", "y", "pen_state"]] + list(self.strokes_data))
            img = draw_user_strokes(user_strokes)
            img_path = os.path.join(SAVE_DIR, f"{base_name}_user.png")
            ok, buf = cv2.imencode(".png", img)
            if ok:
                with open(img_path, "wb") as fimg: fimg.write(buf.tobytes())
            result.update({"status": "DONE", "result_ts": ts, "saved_csv": csv_path, "saved_user_image": img_path})
            result.setdefault("wrong_idx", -1)
            with state.data_lock: state.global_result = result
        except Exception as e:
            with state.data_lock:
                state.global_result = {"status": "DONE", "correct": False, "wrong_idx": -1, "message": f"評分失敗：{e}", "reason": {"failed_rule": "ANALYSIS_ERROR"}, "result_ts": int(time.time() * 1000)}

    def _calc_back_finger_rise(self, landmarks, h: int) -> float:
        wrist_y   = landmarks[0].y * h
        avg_tip_y = sum(landmarks[i].y * h for i in [12, 16, 20]) / 3
        return avg_tip_y - wrist_y

    def _update_pen_hysteresis(self, raw_down: bool) -> None:
        FRAMES_TO_DOWN = 3
        FRAMES_TO_UP   = 3
        if raw_down == self._pen_raw: self._pen_confirm += 1
        else:
            self._pen_raw     = raw_down
            self._pen_confirm = 1
        if not self._pen_state and raw_down and self._pen_confirm >= FRAMES_TO_DOWN: self._pen_state = True
        elif self._pen_state and not raw_down and self._pen_confirm >= FRAMES_TO_UP: self._pen_state = False

    def _force_pen_up(self) -> None:
        self._update_pen_hysteresis(False)

    def run(self) -> None:
        print("[INFO] 影像處理引擎已啟動，按 Ctrl+C 結束程式。")
        try:
            while self.is_running:
                self.loop()
                time.sleep(0.033)
        finally:
            with self.cap_lock:
                self.cap.release()

    def loop(self) -> None:
        with self.cap_lock:
            ret, frame = self.cap.read()
        if not ret: return
        frame = cv2.flip(frame, -1)

        if self.paint_canvas is None or self.paint_canvas.shape != frame.shape:
            self.paint_canvas = np.zeros_like(frame)
            self.history      = [self.paint_canvas.copy()]
            self.idx_history  = [0]

        roi_img    = frame[self.roi_y1:self.roi_y2, self.roi_x1:self.roi_x2]
        gray_roi   = cv2.cvtColor(roi_img, cv2.COLOR_BGR2GRAY)
        _, mask_paper = cv2.threshold(gray_roi, 130, 255, cv2.THRESH_BINARY)
        safe_roi_area = self.roi_area if self.roi_area > 0 else 1
        paper_ratio = cv2.countNonZero(mask_paper) / safe_roi_area

        if not self.is_recording:
            if not self.is_paper_ready:
                if paper_ratio > 0.85: self.is_paper_ready = True
            else:
                if paper_ratio < 0.50: self.is_paper_ready = False

        paper_ready_now = self.is_paper_ready or self.is_recording
        box_color   = (0, 255, 0) if paper_ready_now else (0, 0, 255)
        status_text = "Ready! Please write inside." if paper_ready_now else "Align paper inside the box..."

        mp_result    = None
        hand_detected = False
        if self.mediapipe_ready and self.hand_detector is not None:
            self._mp_timestamp += 33
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_img   = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            mp_result = self.hand_detector.detect_for_video(mp_img, self._mp_timestamp)

        msg = _Point()
        cx = cy = 0
        writing = False
        color   = (100, 100, 100)

        is_corner_calib = self.calibration_mode and len(self.corner_points) < 4
        
        fx, fy = -1, -1
        
        search_radius = MP_SEARCH_RADIUS
        has_search_center = False
        rise = 0.0

        if mp_result is not None and mp_result.hand_landmarks:
            landmarks = mp_result.hand_landmarks[0]
            h_f, w_f  = frame.shape[:2]
            hand_detected = True

            lm6 = landmarks[6]   
            lm8 = landmarks[8]   
            dx = (lm8.x - lm6.x) * w_f
            dy = (lm8.y - lm6.y) * h_f
            
            self.last_dx = dx
            self.last_dy = dy
            
            fx = int(lm8.x * w_f + dx * PEN_EXTEND)
            fy = int(lm8.y * h_f + dy * PEN_EXTEND)
            
            rise = self._calc_back_finger_rise(landmarks, h_f)
            has_search_center = True

            for a, b in self.HAND_CONNECTIONS:
                la, lb = landmarks[a], landmarks[b]
                cv2.line(frame, (int(la.x * w_f), int(la.y * h_f)), (int(lb.x * w_f), int(lb.y * h_f)), (200, 200, 200), 1, cv2.LINE_AA)
            for lm in landmarks:
                cv2.circle(frame, (int(lm.x * w_f), int(lm.y * h_f)), 3, (255, 255, 255), -1)

            cv2.circle(frame, (fx, fy), search_radius, (255, 105, 180), 2)
            cv2.putText(frame, "AI Tracking", (fx - 45, fy - search_radius - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 105, 180), 2)

        elif self.last_pos is not None:
            fx, fy = self.last_pos
            search_radius = int(MP_SEARCH_RADIUS * 1.5)
            rise = RISE_COEFFS[0]*fx + RISE_COEFFS[1]*fy + RISE_COEFFS[2] - 10 
            has_search_center = True
            
            cv2.circle(frame, (fx, fy), search_radius, (0, 165, 255), 2)
            cv2.putText(frame, "Edge Tracking", (fx - 45, fy - search_radius - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 165, 255), 2)
                        
        elif is_corner_calib:
            fx, fy = frame.shape[1] // 2, frame.shape[0] // 2
            search_radius = 2000 
            rise = RISE_COEFFS[2] - 10
            has_search_center = True

        if has_search_center:
            finger_mask = np.zeros(frame.shape[:2], dtype=np.uint8)
            cv2.circle(finger_mask, (fx, fy), search_radius, 255, -1)

            if self.last_pos is not None:
                cv2.circle(finger_mask, self.last_pos, int(MP_SEARCH_RADIUS * 1.5), 255, -1)

            clean = frame.copy()
            hsv = cv2.cvtColor(clean, cv2.COLOR_BGR2HSV)
            
            color_mask = cv2.inRange(hsv, self.hsv_lower, self.hsv_upper)
            
            mask = cv2.bitwise_and(color_mask, finger_mask)
            mask = cv2.erode(mask, None, iterations=2)
            mask = cv2.dilate(mask, None, iterations=2)

            cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            valid_cnts = [c for c in cnts if cv2.contourArea(c) > 5]
            
            if valid_cnts:
                area = sum(cv2.contourArea(c) for c in valid_cnts)
                
                if area > 20:
                    best_pt = None
                    max_score = -float('inf')
                    
                    for c in valid_cnts:
                        pts = c.reshape(-1, 2)
                        scores = pts[:, 0] * self.last_dx + pts[:, 1] * self.last_dy
                        idx = np.argmax(scores)
                        if scores[idx] > max_score:
                            max_score = scores[idx]
                            best_pt = pts[idx]
                            
                    cx, cy = int(best_pt[0]), int(best_pt[1])
                    tx, ty = float(cx), float(cy)

                    if self.M is not None:
                        dst = cv2.perspectiveTransform(
                            np.array([[[cx, cy]]], dtype="float32"), self.M
                        )
                        tx, ty = float(dst[0][0][0]), float(dst[0][0][1])

                    thr = AREA_COEFFS[0] * cx + AREA_COEFFS[1] * cy + AREA_COEFFS[2]
                    thr = max(50.0, thr) 
                    
                    rise_thresh_current = RISE_COEFFS[0] * cx + RISE_COEFFS[1] * cy + RISE_COEFFS[2]

                    in_bounds = (-20 <= tx <= 660 and -20 <= ty <= 500)
                    area_ok = area < thr
                    rise_ok = rise < rise_thresh_current
                    raw_down = in_bounds and area_ok and rise_ok
                    self._update_pen_hysteresis(raw_down)

                    msg.x, msg.y = tx, ty
                    msg.z    = 1.0 if self._pen_state else 0.0
                    writing  = self._pen_state
                    color    = (0, 255, 0) if writing else (0, 0, 255)

                    cv2.circle(frame, (cx, cy), 10, color, 3)
                    
                    cv2.putText(frame, f"Area: {area:.0f} / {thr:.0f}", (cx + 15, cy - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)
                    cv2.putText(frame, f"Rise: {rise:.0f} / {rise_thresh_current:.0f}", (cx + 15, cy + 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)

                    if self.calibration_mode:
                        if len(self.corner_points) < 4:
                            if self.stationary_pos is None:
                                self.stationary_pos = (cx, cy)
                                self.calib_hover_frames = 0
                            else:
                                dist = math.hypot(cx - self.stationary_pos[0], cy - self.stationary_pos[1])
                                if dist < 15: 
                                    self.calib_hover_frames += 1
                                    cv2.ellipse(frame, (cx, cy), (30, 30), -90, 0, 
                                                int((self.calib_hover_frames/30)*360), (0, 255, 255), 4)
                                    
                                    if self.calib_hover_frames >= 30:
                                        self.corner_points.append(self.stationary_pos)
                                        print(f"[INFO] 記錄角落座標: {self.stationary_pos}")
                                        self.stationary_pos = None
                                        self.calib_hover_frames = 0
                                        
                                        if len(self.corner_points) == 4:
                                            xs = [p[0] for p in self.corner_points]
                                            ys = [p[1] for p in self.corner_points]
                                            self.roi_x1, self.roi_x2 = min(xs), max(xs)
                                            self.roi_y1, self.roi_y2 = min(ys), max(ys)
                                            self.roi_area = (self.roi_x2 - self.roi_x1) * (self.roi_y2 - self.roi_y1)
                                            
                                            self.calibration_points = generate_calibration_ui_points(
                                                self.roi_x1, self.roi_y1, self.roi_x2, self.roi_y2
                                            )
                                            self.current_calibration_idx = 0
                                            self.calib_cooldown = 45 
                                            print("[INFO] 紙張範圍已更新，進入筆畫收集階段。")
                                else:
                                    self.stationary_pos = (cx, cy)
                                    self.calib_hover_frames = 0
                                    
                        elif self.current_calibration_idx < 18:
                            point_list = list(self.calibration_points.keys())
                            current_point_name = point_list[self.current_calibration_idx]
                            target_x, target_y = self.calibration_points[current_point_name]
                            
                            if self.calib_cooldown > 0:
                                self.calib_cooldown -= 1
                                cv2.circle(frame, (target_x, target_y), 15, (100, 100, 100), 2)
                                cv2.putText(frame, f"Wait: {self.calib_cooldown/30:.1f}s", (target_x - 40, target_y - 25), 
                                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
                            else:
                                is_hover_step = current_point_name.startswith("hover_")
                                dist = math.hypot(cx - target_x, cy - target_y)
                                
                                if dist < 40: 
                                    self.calib_hover_frames += 1
                                    cv2.ellipse(frame, (target_x, target_y), (40, 40), -90, 0, 
                                                int((self.calib_hover_frames/30)*360), (0, 255, 0), 4)
                                    
                                    r_val = float(rise) if hand_detected else None
                                    
                                    if is_hover_step:
                                        self.calibration_collector.add_hover_sample(float(area), r_val, float(cx), float(cy))
                                    else:
                                        f_tip = (lm8.x * w_f, lm8.y * h_f) if hand_detected else None
                                        f_base = (lm6.x * w_f, lm6.y * h_f) if hand_detected else None 
                                        self.calibration_collector.add_draw_sample(
                                            float(area), r_val, float(cx), float(cy), f_tip, f_base, (cx, cy)
                                        )
                                    
                                    if self.calib_hover_frames >= 30:
                                        self.current_calibration_idx += 1
                                        self.calib_hover_frames = 0
                                        if self.current_calibration_idx >= 18:
                                            self._finish_calibration()
                                        else:
                                            self.calib_cooldown = 45
                                            # ⭐ 每完成一個新步驟，建立一個新存檔點
                                            self.calibration_collector.save_snapshot() 
                                else:
                                    # ⭐ 防呆防抖機制：滑出圈外，清空這幾幀不小心錄到的資料
                                    if self.calib_hover_frames > 0:
                                        self.calib_hover_frames = 0
                                        self.calibration_collector.restore_current_snapshot()
                else:
                    self._force_pen_up()
            else:
                self._force_pen_up()
        else:
            self._force_pen_up()

        if not hand_detected and self.last_pos is None and not is_corner_calib:
            self._force_pen_up()
            self.last_pos = None
            cv2.putText(frame, "Please show your hand", (150, 240),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

        if not self.calibration_mode:
            if writing and paper_ready_now:
                if self.last_pos:
                    cv2.line(self.paint_canvas, self.last_pos, (cx, cy), (0, 255, 255), 2)
                self.last_pos = (cx, cy)
            elif not writing:
                self.last_pos = None
        else:
            self.last_pos = (cx, cy) if writing else None

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

        if self.is_recording:
            elapsed = time.time() - self.start_t
            self.strokes_data.append(
                [round(elapsed, 3), round(msg.x, 2), round(msg.y, 2), int(msg.z)]
            )
            cv2.circle(frame, (610, 30), 10, (0, 0, 255), -1)  

        if self.calibration_mode:
            if len(self.corner_points) < 4:
                corner_names = ["Top-Left", "Top-Right", "Bottom-Right", "Bottom-Left"]
                cal_text = f"Step 0: Point pen at {corner_names[len(self.corner_points)]}"
                cv2.putText(frame, cal_text, (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
                for pt in self.corner_points:
                    cv2.circle(frame, pt, 5, (0, 255, 255), -1)
            else:
                point_list = list(self.calibration_points.keys())
                if self.current_calibration_idx < len(point_list):
                    current_point_name = point_list[self.current_calibration_idx]
                    
                    if current_point_name.startswith("hover_"):
                        cal_text = f"Step {self.current_calibration_idx + 1}/18: HOVER (懸空停頓)"
                        color = (255, 0, 255)
                    else:
                        cal_text = f"Step {self.current_calibration_idx + 1}/18: PRESS (下筆停頓)"
                        color = (0, 165, 255)
                        
                    if self.calib_cooldown > 0:
                        cal_text = f"Get Ready... Next is: {cal_text}"
                        color = (0, 255, 255)
                        
                    cv2.putText(frame, cal_text, (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
                    
                    if self.calib_cooldown == 0:
                        cv2.circle(frame, self.calibration_points[current_point_name], 15, color, 2)
                else:
                    cv2.putText(frame, "Calibration Done! Saving...", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

        comb = cv2.add(frame, self.paint_canvas)
        cv2.rectangle(comb, (self.roi_x1, self.roi_y1), (self.roi_x2, self.roi_y2), box_color, 2)
        cv2.putText(comb, status_text, (self.roi_x1, self.roi_y1 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, box_color, 2)
        cv2.putText(comb, f"Paper: {paper_ratio*100:.1f}%", (self.roi_x1, self.roi_y2 + 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, box_color, 1)
        pen_color = (0, 255, 0) if msg.z == 1.0 else (0, 0, 255)
        cv2.putText(comb, "Pen: DOWN" if msg.z == 1.0 else "Pen: UP",
                    (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, pen_color, 2)

        with state.data_lock:
            state.global_frame = comb.copy()
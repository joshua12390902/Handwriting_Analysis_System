"""
tracker/pen_tracker.py — 主追蹤邏輯

包含 PenTracker class：
- 攝影機讀取與筆跡偵測主迴圈 (loop)
- 筆畫錄製、undo、reset
- 評分觸發與結果處理
- 換題 (trigger_auto_request)
"""
import csv
import json
import math
import os
import platform
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
from tracker.camera import build_camera_order, configure_capture, open_camera
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

PEN_COLORS = {
    "blue": {
        "lower": np.array([29, 27, 109]),
        "upper": np.array([110, 143, 228]),
    },
    "yellow": {
        "lower": np.array([19, 128, 138]),
        "upper": np.array([44, 255, 255]),
    },
    "orange": {
        "lower": np.array([0, 168, 145]),
        "upper": np.array([16, 255, 255]),
    },
    "pink": {
        "lower": np.array([148, 52, 99]),
        "upper": np.array([179, 142, 255]),
    },
}

AREA_COEFFS = [0.0, 0.0, 400.0]
RISE_COEFFS = [0.0, 0.0, -105.0]
PEN_EXTEND = 1.0
MP_SEARCH_RADIUS = 200

FRONT_STAGE_TEST_MODE   = False   
AUTO_CALIBRATE_ON_RECORD = True   

SAVE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "saved_writings")
os.makedirs(SAVE_DIR, exist_ok=True)
CALIB_FILE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "calibration.json")


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
        self.snapshots: List[Dict[str, int]] = []
        self.save_snapshot()

    def save_snapshot(self) -> None:
        self.snapshots.append(
            {
                "ha": len(self.hover_areas),
                "hr": len(self.hover_rises),
                "da": len(self.draw_areas),
                "dr": len(self.draw_rises),
                "pe": len(self.pen_extends),
            }
        )

    def restore_current_snapshot(self) -> None:
        snapshot = self.snapshots[-1]
        self.hover_pts_area = self.hover_pts_area[: snapshot["ha"]]
        self.hover_areas = self.hover_areas[: snapshot["ha"]]
        self.hover_pts_rise = self.hover_pts_rise[: snapshot["hr"]]
        self.hover_rises = self.hover_rises[: snapshot["hr"]]
        self.draw_pts_area = self.draw_pts_area[: snapshot["da"]]
        self.draw_areas = self.draw_areas[: snapshot["da"]]
        self.draw_pts_rise = self.draw_pts_rise[: snapshot["dr"]]
        self.draw_rises = self.draw_rises[: snapshot["dr"]]
        self.pen_extends = self.pen_extends[: snapshot["pe"]]

    def pop_and_restore(self) -> None:
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
        self,
        pen_area: float,
        rise_value: Optional[float],
        cx: float,
        cy: float,
        finger_tip: Optional[Tuple[float, float]],
        finger_base: Optional[Tuple[float, float]],
        pen_center: Tuple[float, float],
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

        def fit_plane(points: List[List[float]], values: List[float], default_value: float) -> np.ndarray:
            if len(points) < 3:
                fallback = float(np.median(values)) if values else default_value
                return np.array([0.0, 0.0, fallback])
            try:
                x = np.c_[np.array(points), np.ones(len(points))]
                z = np.array(values)
                coeffs, _, _, _ = np.linalg.lstsq(x, z, rcond=None)
                return coeffs
            except Exception:
                fallback = float(np.median(values)) if values else default_value
                return np.array([0.0, 0.0, fallback])

        hover_area = fit_plane(self.hover_pts_area, self.hover_areas, 400.0)
        draw_area = fit_plane(self.draw_pts_area, self.draw_areas, 200.0)
        hover_rise = fit_plane(self.hover_pts_rise, self.hover_rises, RISE_COEFFS[2] + 20)
        draw_rise = fit_plane(self.draw_pts_rise, self.draw_rises, RISE_COEFFS[2] - 20)

        return {
            "AREA_COEFFS": ((hover_area + draw_area) / 2.0).tolist(),
            "RISE_COEFFS": ((hover_rise + draw_rise) / 2.0).tolist(),
            "PEN_EXTEND": float(np.median(self.pen_extends)) if self.pen_extends else PEN_EXTEND,
        }


def generate_calibration_ui_points(roi_x1: int, roi_y1: int, roi_x2: int, roi_y2: int) -> Dict[str, Tuple[int, int]]:
    x_positions = [
        roi_x1 + (roi_x2 - roi_x1) * 0.25,
        roi_x1 + (roi_x2 - roi_x1) * 0.50,
        roi_x1 + (roi_x2 - roi_x1) * 0.75,
    ]
    y_positions = [
        roi_y1 + (roi_y2 - roi_y1) * 0.25,
        roi_y1 + (roi_y2 - roi_y1) * 0.50,
        roi_y1 + (roi_y2 - roi_y1) * 0.75,
    ]
    names = [
        "top_left", "top_center", "top_right",
        "mid_left", "mid_center", "mid_right",
        "bottom_left", "bottom_center", "bottom_right",
    ]

    points: Dict[str, Tuple[int, int]] = {}
    for i, name in enumerate(names):
        px = int(x_positions[i % 3])
        py = int(y_positions[i // 3])
        points[f"hover_{name}"] = (px, py)
        points[f"draw_{name}"] = (px, py)
    return points


class _Point:
    def __init__(self, x: float = -1.0, y: float = -1.0, z: float = 0.0):
        self.x, self.y, self.z = float(x), float(y), float(z)


# ── PenTracker ────────────────────────────────────────────────────────

class PenTracker:

    def __init__(self):
        is_aarch64 = platform.machine().lower() in {"aarch64", "arm64"}
        # Capture at 720p for a sharp preview. Orin Nano handles this easily;
        # the old Jetson Nano defaults (640x480 + heavy throttling) are gone.
        self.frame_width = int(os.environ.get("CAMERA_FRAME_WIDTH", "1280"))
        self.frame_height = int(os.environ.get("CAMERA_FRAME_HEIGHT", "720"))
        self.loop_sleep_s = float(os.environ.get("TRACKER_LOOP_SLEEP", "0.002" if is_aarch64 else "0.01"))
        # Track every frame (no frame-skipping) so the pen tip stays in sync.
        self.mediapipe_every_n_frames = max(
            1, int(os.environ.get("MEDIAPIPE_EVERY_N_FRAMES", "1"))
        )
        # Feed MediaPipe a downscaled copy (0.5 of 720p = 640x360): fast tracking
        # while the preview stays full-res. Raise toward 1.0 if you want more accuracy.
        self.mediapipe_input_scale = min(
            1.0, max(0.25, float(os.environ.get("MEDIAPIPE_INPUT_SCALE", "0.5" if is_aarch64 else "1.0")))
        )
        self.draw_hand_overlay = os.environ.get("DRAW_HAND_OVERLAY", "1").lower() not in {
            "0", "false", "no"
        }
        self._loop_count = 0

        self.is_running = True
        self.cap_lock = threading.Lock()

        # ROI (paper area) scales with frame size — originally tuned for 640x480,
        # so it stays in the same relative position at any resolution.
        self.roi_x1 = int(self.frame_width * 50 / 640)
        self.roi_y1 = int(self.frame_height * 50 / 480)
        self.roi_x2 = int(self.frame_width * 590 / 640)
        self.roi_y2 = int(self.frame_height * 430 / 480)
        self.roi_area = (self.roi_x2 - self.roi_x1) * (self.roi_y2 - self.roi_y1)
        self.is_paper_ready = False

        self.cap, self.current_camera_index = open_camera()
        configure_capture(self.cap, self.frame_width, self.frame_height)

        project_root = os.path.dirname(os.path.dirname(__file__))
        self._h_save_path = os.path.join(project_root, "homography.npy")
        if os.path.exists(self._h_save_path):
            self.M = np.load(self._h_save_path)
            print("[INFO] 載入既有的 homography 矩陣。")
        else:
            self.M = None

        self.hand_detector = None
        self._mp_timestamp: int = 0
        self._last_mp_result = None
        self.mediapipe_ready = False
        self._init_mediapipe()

        self.paint_canvas: Optional[np.ndarray] = None
        self.last_pos: Optional[Tuple[int, int]] = None
        self.is_recording = False
        self.strokes_data: List = []
        self.start_t: float = 0.0
        self.prev_z: float = 0.0
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

        self.calibration_mode = False
        self.calibration_collector: Optional[CalibrationCollector] = None
        self.calibration_points: Dict[str, Tuple[int, int]] = {}
        self.current_calibration_idx = 0
        self.calib_hover_frames = 0
        self.calib_cooldown = 0
        self.corner_points: List[Tuple[int, int]] = []
        self.stationary_pos: Optional[Tuple[int, int]] = None

        target = state.app_state.snapshot_target()
        self.curr_char = target["target_char"]

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
            print("[WARN] mediapipe 套件未安裝。")
            return
        try:
            model_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "hand_landmarker.task")
            if not os.path.exists(model_path): 
                print(f"[WARN] 找不到 {model_path}")
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
            print(f"[WARN] MediaPipe 初始化失敗: {e}")

    def set_pen_color(self, color_name: str) -> None:
        if color_name in PEN_COLORS:
            self.hsv_lower = PEN_COLORS[color_name]["lower"]
            self.hsv_upper = PEN_COLORS[color_name]["upper"]

    def _load_calibration_params(self) -> None:
        global AREA_COEFFS, RISE_COEFFS, PEN_EXTEND
        if not os.path.exists(CALIB_FILE_PATH):
            self.roi_x1, self.roi_y1 = 50, 50
            self.roi_x2, self.roi_y2 = 590, 430
            self.roi_area = (self.roi_x2 - self.roi_x1) * (self.roi_y2 - self.roi_y1)
            AREA_COEFFS = [0.0, 0.0, 400.0]
            RISE_COEFFS = [0.0, 0.0, -105.0]
            PEN_EXTEND = 1.0
            return
            
        try:
            with open(CALIB_FILE_PATH, "r", encoding="utf-8") as f:
                params = json.load(f)
            
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
        except Exception:
            pass

    def trigger_calibration(self) -> None:
        self.calibration_mode = True
        self.calibration_collector = CalibrationCollector()
        self.calibration_points = {}
        self.current_calibration_idx = 0
        self.calib_hover_frames = 0
        self.calib_cooldown = 0
        self.corner_points = []
        self.stationary_pos = None
        self.reset_canvas()

    def _finish_calibration(self) -> None:
        try:
            if self.calibration_collector is None: return
            params = self.calibration_collector.calculate_parameters()
            global AREA_COEFFS, RISE_COEFFS, PEN_EXTEND
            AREA_COEFFS = params["AREA_COEFFS"]
            RISE_COEFFS = params["RISE_COEFFS"]
            PEN_EXTEND = params["PEN_EXTEND"]
            params["ROI_X1"] = self.roi_x1
            params["ROI_Y1"] = self.roi_y1
            params["ROI_X2"] = self.roi_x2
            params["ROI_Y2"] = self.roi_y2
            with open(CALIB_FILE_PATH, "w", encoding="utf-8") as f:
                json.dump(params, f, indent=4, ensure_ascii=False)
        except Exception:
            pass
        finally:
            self.calibration_mode = False

    def trigger_switch_camera(self) -> None:
        def _do():
            scan_order = build_camera_order(self.current_camera_index)
            scan_order = [i for i in scan_order if i != self.current_camera_index]
            if not scan_order: return
            try:
                new_cap, new_idx = open_camera(camera_order=scan_order)
            except Exception: return
            configure_capture(new_cap, self.frame_width, self.frame_height)
            with self.cap_lock:
                old_cap, self.cap = self.cap, new_cap
                self.current_camera_index = new_idx
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
        self._pen_state   = False
        self._pen_raw     = False
        self._pen_confirm = 0

    def trigger_record(self) -> None:
        self.is_recording = not self.is_recording
        if self.is_recording:
            if AUTO_CALIBRATE_ON_RECORD: self._try_auto_calibrate()
            self.reset_canvas()
            self.start_t = time.time()

    def trigger_undo(self) -> None:
        if self.calibration_mode:
            if len(self.corner_points) < 4:
                if self.corner_points:
                    self.corner_points.pop()
                    self.stationary_pos = None
                    self.calib_hover_frames = 0
                return
            if self.current_calibration_idx > 0 and self.calibration_collector is not None:
                self.current_calibration_idx -= 1
                self.calib_hover_frames = 0
                self.calib_cooldown = 0
                self.stationary_pos = None
                self.calibration_collector.pop_and_restore()
            return
        if len(self.history) > 1:
            self.history.pop()
            self.paint_canvas = self.history[-1].copy()
            self.idx_history.pop()
            self.strokes_data = self.strokes_data[: self.idx_history[-1]]

    def trigger_reset(self) -> None:
        if self.calibration_mode:
            self.calibration_mode = False
            self._load_calibration_params()
        self.reset_canvas()

    def trigger_auto_request(self) -> None:
        requested = state.app_state.pop_requested_char()
        if requested:
            new_char = requested
        else:
            hanzi_dir  = standard_loader.RAW_HANZI_DIR
            candidates = [p.stem for p in hanzi_dir.glob("*.json") if p.stem != self.curr_char]
            if not candidates:
                state.app_state.update_result(status="WAIT")
                return
            new_char = random.choice(candidates)
        new_ts  = int(time.time() * 1000)
        self.curr_char = new_char
        state.app_state.set_target(new_char, new_ts)
        state.app_state.set_std_json(None)
        state.app_state.reset_result(status="WAIT")
        self.reset_canvas()

    def trigger_send(self) -> None:
        self.is_recording = False
        if FRONT_STAGE_TEST_MODE:
            state.app_state.update_result(status="DONE", correct=True, wrong_idx=-1, message="TEST", result_ts=int(time.time() * 1000))
            return
        state.app_state.update_result(status="ANALYZING")
        threading.Thread(target=self._run_compare_analysis, daemon=True).start()

    def _segment_strokes_from_data(self, gap_tolerance=2, min_points=10, min_path_len=25.0, min_bbox_diag=10.0):
        strokes = []
        current = []
        in_stroke = False
        zero_run  = 0
        border_margin = 20.0
        def _append_if_valid(pts):
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
            if compare_core is None: raise RuntimeError("compare.py ERROR")
            user_strokes = self._segment_strokes_from_data()
            std_entry    = standard_loader.load_standard_entry(self.curr_char)
            std_strokes  = standard_loader.load_standard(self.curr_char)
            ts = int(time.time() * 1000)
            dt = time.strftime("%Y%m%d_%H%M%S", time.localtime(ts / 1000))
            ms = ts % 1000
            char_s = "".join(c if c not in r'\/:*?"<>|' else "_" for c in self.curr_char)
            state.app_state.set_std_json(std_entry)
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
            result.update({"status": "DONE", "result_ts": ts, "llm_feedback": "", "llm_loading": _LLM_OK})
            result.setdefault("wrong_idx", -1)
            result["target_char"] = self.curr_char
            state.app_state.replace_result(result)
            if _LLM_OK:
                try:
                    feedback = _llm_chat.get_feedback(result, user_strokes=user_strokes, std_strokes=std_strokes)
                    state.app_state.update_result(llm_feedback=feedback, llm_loading=False)
                except Exception:
                    state.app_state.update_result(llm_loading=False)
        except Exception as e:
            state.app_state.replace_result({"status": "DONE", "correct": False, "wrong_idx": -1, "message": f"評分失敗：{e}", "reason": {"failed_rule": "ANALYSIS_ERROR"}, "result_ts": int(time.time() * 1000)})

    def _calc_back_finger_rise(self, landmarks, h: int) -> float:
        wrist_y   = landmarks[0].y * h
        avg_tip_y = sum(landmarks[i].y * h for i in [12, 16, 20]) / 3
        return avg_tip_y - wrist_y

    def _update_pen_hysteresis(self, raw_down: bool) -> None:
        FRAMES_TO_DOWN = 3
        FRAMES_TO_UP   = 3
        if raw_down == self._pen_raw: self._pen_confirm += 1
        else:
            self._pen_raw = raw_down
            self._pen_confirm = 1
        if not self._pen_state and raw_down and self._pen_confirm >= FRAMES_TO_DOWN: self._pen_state = True
        elif self._pen_state and not raw_down and self._pen_confirm >= FRAMES_TO_UP: self._pen_state = False

    def _force_pen_up(self) -> None:
        self._update_pen_hysteresis(False)

    def run(self) -> None:
        try:
            while self.is_running:
                self.loop()
                if self.loop_sleep_s > 0:
                    time.sleep(self.loop_sleep_s)
        finally:
            with self.cap_lock: self.cap.release()

    def loop(self) -> None:
        self._loop_count += 1
        with self.cap_lock:
            ret, frame = self.cap.read()
        if not ret: return
        frame = cv2.flip(frame, -1)

        if self.paint_canvas is None or self.paint_canvas.shape != frame.shape:
            self.paint_canvas = np.zeros_like(frame)
            self.history      = [self.paint_canvas.copy()]
            self.idx_history  = [0]

        roi_img = frame[self.roi_y1:self.roi_y2, self.roi_x1:self.roi_x2]
        gray_roi = cv2.cvtColor(roi_img, cv2.COLOR_BGR2GRAY)
        _, mask_paper = cv2.threshold(gray_roi, 130, 255, cv2.THRESH_BINARY)
        safe_roi_area = self.roi_area if self.roi_area > 0 else 1
        paper_ratio = cv2.countNonZero(mask_paper) / safe_roi_area

        if not self.is_recording:
            if not self.is_paper_ready:
                if paper_ratio > 0.85: self.is_paper_ready = True
            elif paper_ratio < 0.50: self.is_paper_ready = False

        paper_ready_now = self.is_paper_ready or self.is_recording
        box_color = (0, 255, 0) if paper_ready_now else (0, 0, 255)
        status_text = "Ready! Please write inside." if paper_ready_now else "Align paper inside the box..."

        mp_result = self._last_mp_result
        hand_detected = False
        if self.mediapipe_ready and self.hand_detector is not None:
            should_run_mediapipe = (
                self._last_mp_result is None
                or self._loop_count % self.mediapipe_every_n_frames == 0
            )
            if should_run_mediapipe:
                self._mp_timestamp += 33 * self.mediapipe_every_n_frames
                mp_frame = frame
                if self.mediapipe_input_scale < 0.999:
                    mp_frame = cv2.resize(
                        frame,
                        None,
                        fx=self.mediapipe_input_scale,
                        fy=self.mediapipe_input_scale,
                        interpolation=cv2.INTER_LINEAR,
                    )
                rgb = cv2.cvtColor(mp_frame, cv2.COLOR_BGR2RGB)
                mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                mp_result = self.hand_detector.detect_for_video(mp_img, self._mp_timestamp)
                self._last_mp_result = mp_result

        msg = _Point()
        cx = cy = 0
        writing = False
        color = (100, 100, 100)
        lm6 = lm8 = None
        h_f, w_f = frame.shape[:2]

        is_corner_calib = self.calibration_mode and len(self.corner_points) < 4
        fx, fy = -1, -1
        search_radius = MP_SEARCH_RADIUS
        has_search_center = False
        rise = 0.0

        if mp_result is not None and mp_result.hand_landmarks:
            landmarks = mp_result.hand_landmarks[0]
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
            if self.draw_hand_overlay:
                for a, b in self.HAND_CONNECTIONS:
                    la, lb = landmarks[a], landmarks[b]
                    cv2.line(
                        frame,
                        (int(la.x * w_f), int(la.y * h_f)),
                        (int(lb.x * w_f), int(lb.y * h_f)),
                        (200, 200, 200),
                        1,
                        cv2.LINE_AA,
                    )
                for lm in landmarks:
                    cv2.circle(frame, (int(lm.x * w_f), int(lm.y * h_f)), 3, (255, 255, 255), -1)

            cv2.circle(frame, (fx, fy), search_radius, (255, 105, 180), 2)
            cv2.putText(frame, "AI Tracking", (fx - 45, fy - search_radius - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 105, 180), 2)

        elif self.last_pos is not None:
            fx, fy = self.last_pos
            search_radius = int(MP_SEARCH_RADIUS * 1.5)
            rise = RISE_COEFFS[0] * fx + RISE_COEFFS[1] * fy + RISE_COEFFS[2] - 10
            has_search_center = True

            cv2.circle(frame, (fx, fy), search_radius, (0, 165, 255), 2)
            cv2.putText(frame, "Edge Tracking", (fx - 45, fy - search_radius - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 165, 255), 2)

        elif is_corner_calib:
            fx, fy = frame.shape[1] // 2, frame.shape[0] // 2
            search_radius = 2000
            rise = RISE_COEFFS[2] - 10
            has_search_center = True

        if has_search_center:
            # 1. 建立空的遮罩與基礎搜尋範圍（紫色圈圈）
            finger_mask = np.zeros(frame.shape[:2], dtype=np.uint8)
            search_mask = np.zeros(frame.shape[:2], dtype=np.uint8)
            
            # 在 search_mask 畫出搜尋範圍
            cv2.circle(search_mask, (fx, fy), search_radius, 255, -1)
            if self.last_pos is not None:
                cv2.circle(search_mask, self.last_pos, int(MP_SEARCH_RADIUS * 1.5), 255, -1)
            
            # 2. 判斷是否在校正模式外
            if not is_corner_calib:
                # 建立紙張範圍遮罩（包含 30 像素邊緣緩衝）
                roi_mask = np.zeros(frame.shape[:2], dtype=np.uint8)
                margin = 30
                safe_x1 = max(0, self.roi_x1 - margin)
                safe_y1 = max(0, self.roi_y1 - margin)
                safe_x2 = min(frame.shape[1], self.roi_x2 + margin)
                safe_y2 = min(frame.shape[0], self.roi_y2 + margin)
                cv2.rectangle(roi_mask, (safe_x1, safe_y1), (safe_x2, safe_y2), 255, -1)
                
                # 核心改動：檢查「紫色搜尋圈」與「紙張範圍」是否有重疊
                overlap = cv2.bitwise_and(search_mask, roi_mask)
                
                # 如果有任何重疊點，則 finger_mask 直接使用完整的 search_mask（不裁切邊界）
                if cv2.countNonZero(overlap) > 0:
                    finger_mask = search_mask
                else:
                    # 完全沒碰到框框，則不偵測
                    finger_mask = np.zeros(frame.shape[:2], dtype=np.uint8)
            else:
                # 校正點四角階段，直接使用搜尋圈
                finger_mask = search_mask

            # 3. 接下來進行顏色偵測（以下保持原樣）
            hsv = cv2.cvtColor(frame.copy(), cv2.COLOR_BGR2HSV)
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
                    max_score = -float("inf")
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
                        dst = cv2.perspectiveTransform(np.array([[[cx, cy]]], dtype="float32"), self.M)
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
                    msg.z = 1.0 if self._pen_state else 0.0
                    writing = self._pen_state
                    color = (0, 255, 0) if writing else (0, 0, 255)

                    cv2.circle(frame, (cx, cy), 10, color, 3)

                    if self.calibration_mode:
                        cv2.putText(frame, f"Area: {area:.0f}", (cx + 15, cy - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)
                        cv2.putText(frame, f"Rise: {rise:.0f}", (cx + 15, cy + 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)
                    else:
                        cv2.putText(frame, f"Area: {area:.0f} / {thr:.0f}", (cx + 15, cy - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)
                        cv2.putText(frame, f"Rise: {rise:.0f} / {rise_thresh_current:.0f}", (cx + 15, cy + 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)

                    if self.calibration_mode and self.calibration_collector is not None:
                        if len(self.corner_points) < 4:
                            if self.stationary_pos is None:
                                self.stationary_pos = (cx, cy)
                                self.calib_hover_frames = 0
                            else:
                                dist = math.hypot(cx - self.stationary_pos[0], cy - self.stationary_pos[1])
                                if dist < 15:
                                    self.calib_hover_frames += 1
                                    cv2.ellipse(frame, (cx, cy), (30, 30), -90, 0, int((self.calib_hover_frames / 30) * 360), (0, 255, 255), 4)
                                    if self.calib_hover_frames >= 30:
                                        self.corner_points.append(self.stationary_pos)
                                        self.stationary_pos = None
                                        self.calib_hover_frames = 0
                                        if len(self.corner_points) == 4:
                                            xs = [p[0] for p in self.corner_points]
                                            ys = [p[1] for p in self.corner_points]
                                            self.roi_x1, self.roi_x2 = min(xs), max(xs)
                                            self.roi_y1, self.roi_y2 = min(ys), max(ys)
                                            self.roi_area = (self.roi_x2 - self.roi_x1) * (self.roi_y2 - self.roi_y1)
                                            self.calibration_points = generate_calibration_ui_points(self.roi_x1, self.roi_y1, self.roi_x2, self.roi_y2)
                                            self.current_calibration_idx = 0
                                            self.calib_cooldown = 45
                                else:
                                    self.stationary_pos = (cx, cy)
                                    self.calib_hover_frames = 0
                        elif self.current_calibration_idx < 18:
                            point_names = list(self.calibration_points.keys())
                            current_point_name = point_names[self.current_calibration_idx]
                            target_x, target_y = self.calibration_points[current_point_name]

                            if self.calib_cooldown > 0:
                                self.calib_cooldown -= 1
                                cv2.circle(frame, (target_x, target_y), 15, (100, 100, 100), 2)
                                # ⭐ 補回 2：校正時的準備倒數計時文字
                                cv2.putText(frame, f"Wait: {self.calib_cooldown / 30:.1f}s", (target_x - 40, target_y - 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
                            else:
                                is_hover_step = current_point_name.startswith("hover_")
                                dist = math.hypot(cx - target_x, cy - target_y)
                                if dist < 40:
                                    self.calib_hover_frames += 1
                                    cv2.ellipse(frame, (target_x, target_y), (40, 40), -90, 0, int((self.calib_hover_frames / 30) * 360), (0, 255, 0), 4)
                                    rise_value = float(rise) if hand_detected else None
                                    if is_hover_step:
                                        self.calibration_collector.add_hover_sample(float(area), rise_value, float(cx), float(cy))
                                    else:
                                        f_tip = (lm8.x * w_f, lm8.y * h_f) if lm8 is not None else None
                                        f_base = (lm6.x * w_f, lm6.y * h_f) if lm6 is not None else None
                                        self.calibration_collector.add_draw_sample(float(area), rise_value, float(cx), float(cy), f_tip, f_base, (cx, cy))
                                    if self.calib_hover_frames >= 30:
                                        self.current_calibration_idx += 1
                                        self.calib_hover_frames = 0
                                        if self.current_calibration_idx >= 18:
                                            self._finish_calibration()
                                        else:
                                            self.calib_cooldown = 45
                                            self.calibration_collector.save_snapshot()
                                elif self.calib_hover_frames > 0:
                                    self.calib_hover_frames = 0
                                    self.calibration_collector.restore_current_snapshot()
                else:
                    self._force_pen_up()
            else:
                self._force_pen_up()
        else:
            self._force_pen_up()

        # ⭐ 補回 1：找不到手的紅色警告文字
        if not hand_detected and self.last_pos is None and not is_corner_calib:
            self._force_pen_up()
            self.last_pos = None
            cv2.putText(frame, "Please show your hand", (150, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

        if not self.calibration_mode:
            if writing and paper_ready_now:
                if self.last_pos: cv2.line(self.paint_canvas, self.last_pos, (cx, cy), (0, 255, 255), 2)
                self.last_pos = (cx, cy)
            elif not writing: self.last_pos = None
        else:
            self.last_pos = (cx, cy) if writing else None

        if self.prev_z == 1 and msg.z == 0:
            self.history.append(self.paint_canvas.copy())
            self.idx_history.append(len(self.strokes_data))
            if len(self.history) > 20:
                self.history.pop(0)
                self.idx_history.pop(0)

        if msg.z == 1.0: self.curr_stroke_frames += 1
        else: self.curr_stroke_frames = 0
        self.prev_z = msg.z

        if self.is_recording:
            elapsed = time.time() - self.start_t
            self.strokes_data.append([round(elapsed, 3), round(msg.x, 2), round(msg.y, 2), int(msg.z)])
            cv2.circle(frame, (610, 30), 10, (0, 0, 255), -1)

        if self.calibration_mode:
            cal_text = ""
            if len(self.corner_points) < 4:
                corner_names = ["左上角 (Top-Left)", "右上角 (Top-Right)", "右下角 (Bottom-Right)", "左下角 (Bottom-Left)"]
                cal_text = f"Step 0 ({len(self.corner_points)+1}/4): 請用筆尖觸碰畫面設定紙張的【 {corner_names[len(self.corner_points)]} 】"
                for pt in self.corner_points:
                    cv2.circle(frame, pt, 5, (0, 255, 255), -1)
            else:
                point_names = list(self.calibration_points.keys())
                if self.current_calibration_idx < len(point_names):
                    current_point_name = point_names[self.current_calibration_idx]
                    
                    if current_point_name.startswith("hover_"):
                        cal_text = f"Step {self.current_calibration_idx + 1}/18: 請將筆對準灰圈，懸空停頓 (HOVER)"
                    else:
                        cal_text = f"Step {self.current_calibration_idx + 1}/18: 請將筆對準灰圈，下筆停頓 (PRESS)"

                    if self.calib_cooldown > 0:
                        cal_text = f"準備中... 下一個是: {cal_text}"
                else:
                    cal_text = "校正完成！正在儲存參數..."
            
            try:
                state.app_state.update_result(calibration_prompt=cal_text)
            except Exception:
                pass
        else:
            try:
                state.app_state.update_result(calibration_prompt="")
            except Exception:
                pass

        comb = cv2.add(frame, self.paint_canvas)
        cv2.rectangle(comb, (self.roi_x1, self.roi_y1), (self.roi_x2, self.roi_y2), box_color, 2)
        cv2.putText(comb, status_text, (self.roi_x1, self.roi_y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, box_color, 2)
        cv2.putText(comb, f"Paper: {paper_ratio * 100:.1f}%", (self.roi_x1, self.roi_y2 + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, box_color, 1)
        pen_color = (0, 255, 0) if msg.z == 1.0 else (0, 0, 255)
        cv2.putText(comb, "Pen: DOWN" if msg.z == 1.0 else "Pen: UP", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, pen_color, 2)
        state.app_state.set_frame(comb)

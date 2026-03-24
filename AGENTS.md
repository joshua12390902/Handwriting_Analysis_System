# AGENTS.md

## Purpose
此工作區是「即時手寫分析系統」：相機擷取 + 筆劃軌跡記錄 + `compare.py` 筆順/形狀比對。

## User Preferences
- 預設使用繁體中文回覆。
- 優先提供可直接執行的步驟與 Windows PowerShell 指令。
- 變更以最小、精準為原則；先看檔案再提修正。

## Current Project Layout (重要)
- `pen_tracker_mediapipe.py`：主程式（Flask + OpenCV 即時追蹤與送評分）
- `compare.py`：核心比對邏輯（筆畫數、筆順、DTW 分數）
- `standard_loader.py`：載入標準字資料
- `standard_db/`、`standard_db.json`：標準筆畫資料庫
- `saved_writings/`：每次送出後自動存檔（CSV + 使用者筆劃圖）
- `tools/calibrate_homography.py`：手動四角校正工具（備用）
- `.venv/`：目前主要 Python 環境

## Runtime Snapshot (目前行為)
- 網頁入口：`http://127.0.0.1:5000`
- 顏色偵測：藍色 HSV（`H: 90-130, S: 70-255, V: 50-255`）
- MediaPipe：可選；失敗時自動 fallback 到 HSV+ROI 流程
- 校正：按 `Record` 會嘗試「自動校正」(由綠框內白紙估計 homography)
- Homography 載入優先順序：
	1) 專案根目錄 `homography.npy`
	2) `~/sketch_ws/homography.npy`（舊路徑相容）

## Runbook: Real Camera Test (Windows PowerShell)
1. `cd c:\Users\joshu\Downloads\Module_final`
2. `.\.venv\Scripts\python.exe pen_tracker_mediapipe.py`
3. 開啟 `http://127.0.0.1:5000`

## Demo Flow
1. 白紙放進綠框（盡量填滿 ROI）
2. 按 `Record`（同時觸發自動校正）
3. 寫字
4. 按 `Send` 評分
5. 到 `saved_writings/` 查看保存的 CSV 與 `_user.png`

## Known Pitfalls
- 若畫面邊界出現抖動點，可能被切成額外筆畫（會觸發筆畫數錯誤）。
- 校正失敗常見原因：白紙未完整進入綠框、光線過暗、背景干擾強。
- 若出現 `module 'mediapipe' has no attribute 'solutions'`，系統仍可在 fallback 模式運作。

## Agent Behavior
- 先讀相關檔案再改。
- 先驗證根因（可用實際 CSV 重跑 compare）再調參。
- 非使用者要求時，不主動做大幅重構。
- 使用者若明確說「先不要改 compare」，優先更新文件/流程，不改 `compare.py`。

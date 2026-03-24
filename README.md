# 即時手寫分析系統（Module_final）

本專案提供「攝影機即時追蹤 + 筆劃評分」流程：
- 前端：Flask 網頁 (`http://127.0.0.1:5000`)
- 即時偵測：OpenCV（藍色 HSV + ROI）
- 評分核心：`compare.py`（筆畫數、筆順/形狀比對）
- 輸出存檔：`saved_writings/`（每次送出都存 CSV 與 `_user.png`）

## 專案結構
- `pen_tracker_mediapipe.py`：主程式（攝影機、錄製、送評分）
- `compare.py`：筆畫比對邏輯
- `standard_loader.py`：載入標準字資料
- `standard_db/`、`standard_db.json`：標準字筆畫資料
- `saved_writings/`：送出後保存結果
- `tools/calibrate_homography.py`：手動四角校正工具

## 快速啟動（Windows PowerShell）
```powershell
cd c:\Users\joshu\Downloads\Module_final
.\.venv\Scripts\python.exe pen_tracker_mediapipe.py
```
開啟瀏覽器：`http://127.0.0.1:5000`

## 操作流程
1. 白紙放入綠框（盡量填滿）
2. 按 `Record`（會嘗試自動校正）
3. 書寫目標字
4. 按 `Send` 送評分
5. 到 `saved_writings/` 查看：
   - `YYYYMMDD_HHMMSS_mmm_字_PASS/FAIL.csv`
   - `YYYYMMDD_HHMMSS_mmm_字_PASS/FAIL_user.png`

## 校正說明
系統在 `Record` 開始時會嘗試自動校正（用綠框內白紙估計 homography）。
若自動校正失敗，可手動執行：
```powershell
cd c:\Users\joshu\Downloads\Module_final
.\.venv\Scripts\python.exe tools\calibrate_homography.py --camera 0
```
並依序點紙張四角（左上 → 右上 → 右下 → 左下），按 `s` 儲存。

`homography.npy` 載入優先順序：
1. 專案根目錄 `homography.npy`
2. `~/sketch_ws/homography.npy`（舊路徑相容）

## 常見問題
- **UI 顯示筆畫錯誤很多筆**：先檢查 `saved_writings/*.csv` 是否被分段成多筆（邊界抖動常見）。
- **畫在正中間但座標偏移**：通常是鏡頭非垂直造成透視誤差，先做校正。
- **MediaPipe 初始化失敗**：系統會自動 fallback 至 HSV+ROI，不會中斷流程。

## 目前偵測設定
- 藍色 HSV：`H 90-130, S 70-255, V 50-255`
- 評分在送出後執行，結果回傳到 UI 並寫入保存檔。

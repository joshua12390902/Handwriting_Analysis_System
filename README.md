# 即時手寫分析系統

攝影機即時追蹤漢字筆跡，並與標準筆畫資料比對、給分。

## 功能
- 攝影機即時偵測藍色筆跡（HSV 色域）
- 支援 MediaPipe 手部偵測，失敗時自動 fallback 至 HSV+ROI
- 透視校正（homography），補償鏡頭角度造成的座標偏移
- 按 **下一題** 從 9500+ 字資料集隨機抽題
- 評分結果分類：
  - `STROKE_COUNT_MISMATCH`：筆畫數錯誤
  - `ORDER_WRONG`：筆順不對（標示具體哪幾筆位置錯誤）
  - `WRONG_CHARACTER`：整體不像目標字
  - `OK`：通過
- 每次送分自動存檔至 `saved_writings/`（CSV 軌跡 + 筆跡圖）

## 環境需求
- Python 3.10+
- 有藍色外殼的筆 + 攝影機

## 安裝
```powershell
git clone https://github.com/joshua12390902/Handwriting_Analysis_System.git
cd Handwriting_Analysis_System
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

## 啟動
```powershell
.\.venv\Scripts\python.exe app.py
```
開啟瀏覽器：`http://127.0.0.1:5000`

## 操作流程
1. 白紙放入綠框（盡量填滿）
2. 按 **Record**（同時觸發自動透視校正）
3. 書寫畫面上顯示的目標字
4. 按 **Send** 送出評分
5. 結果即時顯示在網頁，並自動存至 `saved_writings/`
6. 按 **下一題** 隨機換字繼續練習

## 專案結構
```
app.py                     入口點（啟動 Flask + 攝影機迴圈）
state.py                   共用全域狀態與 threading lock
web/
  __init__.py              Flask app 實例
  template.py              前端 HTML/CSS/JS
  routes.py                HTTP 路由（GET/POST endpoints）
  viz.py                   OpenCV 畫圖輔助（標準筆畫、使用者筆畫）
tracker/
  pen_tracker.py           PenTracker 主追蹤邏輯
  camera.py                相機偵測、開啟、切換
  calibration.py           透視校正（homography）
compare.py                 評分核心（DTW、筆順比對、IQR 離群過濾）
standard_loader.py         載入 hanzi/ 字庫資料
hanzi/                     hanzi-writer 標準筆畫資料集（9500+ 字）
tools/
  calibrate_homography.py  手動四角透視校正工具
  visual.py / visual_hanzi.py  筆跡視覺化
  fetch_hanziwriter.py     重新下載字庫
saved_writings/            每次評分後自動存檔（git 不追蹤內容）
pen_tracker_mediapipe.py   向後相容入口（等同於 app.py）
```

## 透視校正
按 **Record** 時系統會自動用綠框內白紙估算校正矩陣。

若自動校正失敗，手動執行：
```powershell
.\.venv\Scripts\python.exe tools\calibrate_homography.py --camera 0
```
依序點紙張四角（左上 → 右上 → 右下 → 左下），按 `s` 儲存。

## 評分演算法簡介
- **座標系對齊**：相機 y 軸向下，hanzi-writer y 軸向上，自動 flip_y 對齊
- **整字正規化**：所有筆畫同步平移縮放，保留相對位置
- **Arc-length resampling**：每筆重取 64 點
- **DTW 距離**：計算使用者筆畫與標準筆畫的形狀相似度
- **位置矩陣**：NxN 中心距離矩陣偵測筆順對調，標示位置偏離的筆畫
- **離群筆畫過濾**：IQR fence 自動移除邊界雜訊（不影響筆畫數計算）

## 常見問題
- **MediaPipe 無法初始化**：系統自動切換到 HSV 模式，不影響使用
- **座標偏移**：鏡頭未垂直時請做透視校正
- **偵測到多餘筆畫**：系統會自動過濾離字體中心過遠的雜訊筆畫
- **伺服器無法用 Ctrl+C 停止**：在 PowerShell 執行 `taskkill /F /IM python.exe`

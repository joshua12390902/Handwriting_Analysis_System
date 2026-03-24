# CLAUDE.md

## 專案簡介
即時手寫分析系統：攝影機擷取藍色筆跡 → 筆畫分割 → DTW 比對 → 評分回饋。

## 使用者偏好
- 預設繁體中文回覆。
- 提供可直接執行的 Windows PowerShell 指令。
- 變更以最小、精準為原則；先讀檔案再提修正。
- 非使用者要求時，不主動重構。

## 專案結構
```
pen_tracker_mediapipe.py   主程式（Flask + OpenCV 即時追蹤）
compare.py                 評分核心（DTW、筆順比對、IQR 離群過濾）
standard_loader.py         載入 hanzi/ 字庫，提供 load_standard(char_id)
hanzi/                     hanzi-writer 標準筆畫資料集（9500+ 字，.json）
tools/
  calibrate_homography.py  手動四角透視校正工具
  visual.py / visual_hanzi.py  筆跡視覺化
saved_writings/            每次評分後自動存檔（CSV + _user.png）
requirements.txt           依賴套件
.venv/                     主要 Python 環境（Python 3.10+）
```

`standard_db/` 已從 git 移除（gitignore），不需要存在。

## 啟動方式
```powershell
cd c:\Users\joshu\Downloads\Module_final
.\.venv\Scripts\python.exe pen_tracker_mediapipe.py
# 開啟 http://127.0.0.1:5000
```

停止伺服器（Ctrl+C 無效時）：
```powershell
taskkill /F /IM python.exe
```

## 操作流程
1. 白紙放入綠框（盡量填滿）
2. 按 **Record**（同時觸發自動透視校正）
3. 書寫畫面上顯示的目標字
4. 按 **Send** 送出評分
5. 按 **下一題** 隨機換字

## 評分流程（compare.py）
1. `segment_strokes()` — 從 CSV (x, y, pen_state) 切出各筆畫
2. `filter_outlier_strokes()` — IQR fence (k=1.5) 移除離群筆畫（不影響筆畫數計算前的計數，只過濾後再比對）
3. 筆畫數比對 → `STROKE_COUNT_MISMATCH`
4. 中心距離矩陣偵測筆順對調 → `ORDER_WRONG`（`swap_score_gate=1.0`，等於停用 gate，只看位置）
5. Per-stroke DTW → `WRONG_CHARACTER`
6. 全過 → `OK`

### 關鍵參數
| 參數 | 預設值 | 說明 |
|---|---|---|
| `swap_score_gate` | `1.0` | 設為 1.0 = 停用形狀過濾，對調只看中心距離 |
| `iqr_k` | `1.5` | IQR fence 係數，越小越嚴格 |
| `t_min` | `0.55` | 單筆最低相似度門檻 |
| `T_char` | `0.40` | 整字平均分門檻 |

## 已知坑（重要）
- **Windows 中文路徑圖片存檔**：`cv2.imwrite` 在 cp950 系統遇中文路徑會靜默失敗。
  務必用 `cv2.imencode(".png", img)` + `open(path, "wb").write(buf.tobytes())`。
- **多個伺服器實例**：多次啟動可能造成 port 5000 衝突，需手動 `taskkill /F /IM python.exe`。
- **Windows 終端機編碼**：cp950 終端機顯示 JSON 中文 key 可能亂碼，這是顯示問題，檔案本身正常。
- **MediaPipe 初始化失敗**：正常，系統自動 fallback 至 HSV+ROI 模式。
- **↔ 字元**：cp950 無法編碼 U+2194，swap 說明應用中文「第N筆與第M筆」。

## 座標系對齊
- 相機 y 軸向下，hanzi-writer y 軸向上。
- `standard_loader` 載入後需 `flip_y` 對齊。
- 全字統一平移縮放（whole-character normalization），保留相對位置。
- Arc-length resampling：每筆重取 64 點後再做 DTW。

## Git 工作流程
- 主要分支：`main`（GitHub 上）
- 協作方式：開 feature branch → push → PR → review → merge
- `standard_db/`、`.venv/`、`saved_writings/*.csv/png`、`homography.npy` 不追蹤

## Agent 行為規則
- 先讀相關檔案再改。
- 用實際 CSV 重跑 compare 驗證根因後再調參。

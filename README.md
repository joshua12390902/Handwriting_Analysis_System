# 手寫分析系統

這是一套以紙本書寫為核心的即時漢字手寫分析系統。  
系統會透過攝影機擷取使用者在紙上書寫的筆跡，將資料轉成 `(timestamp, x, y, pen_state)` 的軌跡格式，再與標準字資料比對，分析筆畫數、筆順與整體字形是否合理。

除了筆跡分析外，專案也包含：
- Flask 網頁介面
- MediaPipe 手部追蹤
- 筆尖顏色追蹤
- 書寫區域校正
- 標準字筆順視覺化
- Ollama 本地 AI 老師聊天與回饋
- Jetson Nano 與 Logitech C922 用的 3D 列印支架設計

## 專案目前在做什麼

系統主要流程如下：

1. [`app.py`](app.py) 啟動 Flask 與追蹤器。
2. [`tracker/pen_tracker.py`](tracker/pen_tracker.py) 持續讀取相機影像，偵測手與筆尖。
3. 使用者開始錄製後，系統記錄筆跡資料。
4. 送出分析後，由 [`compare.py`](compare.py) 和標準字資料做比對。
5. 分析結果透過 [`state.py`](state.py) 回傳給前端。
6. [`web/template.py`](web/template.py) 顯示目前題目、影像、結果與聊天介面。
7. [`llm_chat.py`](llm_chat.py) 提供換字、筆畫問題、提示與 AI 回饋。

## 主要功能

- 即時相機畫面顯示
- 紙張 ROI 偵測與書寫區域檢查
- MediaPipe 手部追蹤
- HSV 筆尖顏色追蹤
- 筆跡錄製、復原、清空、送出分析
- 自動換題與聊天換字
- 標準筆順圖顯示與錯誤筆畫標示
- 筆順驗證結果：
  - `OK`
  - `ORDER_WRONG`
  - `WRONG_CHARACTER`
  - `STROKE_COUNT_MISMATCH`
- AI 老師提示與鼓勵式回饋
- 分析後自動存出 CSV 與使用者筆跡圖到 [`saved_writings/`](saved_writings)

## 目前真正有在跑的核心檔案

- [`app.py`](app.py)
  - 專案正式啟動入口。
  - 現在只保留這一個啟動方式。

- [`state.py`](state.py)
  - 共用執行狀態。
  - 負責保存目前題目、最新畫面、分析結果、標準字資料與 tracker 參考。

- [`tracker/pen_tracker.py`](tracker/pen_tracker.py)
  - 專案最核心的執行引擎。
  - 負責相機讀取、手部與筆尖追蹤、錄製筆跡、校正、切題與送分析。

- [`compare.py`](compare.py)
  - 筆順驗證核心。
  - 將使用者筆跡切成筆畫後，和標準字資料做比對。

- [`standard_loader.py`](standard_loader.py)
  - 載入標準字資料。
  - 優先讀取 `standard_db/`，找不到時 fallback 到 [`hanzi/`](hanzi)。

- [`llm_chat.py`](llm_chat.py)
  - 聊天與 AI 回饋模組。
  - 先用規則處理換字、筆畫數、筆順、提示，再視情況 fallback 給 Ollama。

- [`web/routes.py`](web/routes.py)
  - Flask API 路由。

- [`web/template.py`](web/template.py)
  - 內嵌式前端頁面。

- [`web/viz.py`](web/viz.py)
  - 標準筆順與使用者筆跡的視覺化工具。

## 專案結構

```text
app.py
compare.py
llm_chat.py
state.py
standard_loader.py
requirements.txt
hand_landmarker.task

tracker/
  camera.py
  calibration.py
  pen_tracker.py

web/
  __init__.py
  routes.py
  template.py
  viz.py

tools/
  llm_chat_smoke_test.py
  build_index.py
  calibrate_homography.py
  cam_*_probe.py
  fetch_hanziwriter.py
  fill_empty_hanzi.py
  generate_db.py
  shuffle_user_strokes.py
  visual.py
  visual_hanzi.py
  test.py

hanzi/
saved_writings/
3d_mount/
hardware_stl/
```

## 安裝方式

```powershell
git clone https://github.com/joshua12390902/Handwriting_Analysis_System.git
cd Handwriting_Analysis_System
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

## 啟動方式

請直接使用：

```powershell
python app.py
```

啟動後打開：

```text
http://127.0.0.1:5000
```

## 相依套件

相依套件定義在 [`requirements.txt`](requirements.txt)：

- Flask
- NumPy
- OpenCV
- Pandas
- MediaPipe
- pygrabber

建議 Python 版本：

- Python 3.10 以上

## LLM 與 Ollama

聊天老師與分析回饋可搭配 Ollama 使用。

可設定的環境變數：

```powershell
$env:OLLAMA_HOST="http://localhost:11434"
$env:OLLAMA_MODEL="qwen2.5:3b"
```

如果沒有啟動 Ollama：
- 主分析流程仍然可以使用
- 聊天中的規則型回覆仍可正常工作
- 只有需要模型生成的部分會退化

## 基本使用流程

1. 把白紙放進畫面中的書寫框內。
2. 在網頁中按下 `開始錄製`。
3. 在紙上書寫目前題目。
4. 按下 `送出分析`。
5. 查看分析結果、標準筆順圖與 AI 回饋。
6. 按 `下一題` 或用聊天切換字。

## 聊天功能

聊天模組目前支援這類輸入：

- `哈`
- `我想學軌`
- `這個字幾筆`
- `提示我這個字`
- `這好難教我`
- `隨便換一個字`

系統會優先用規則處理這些需求，讓結果更穩定，不會太依賴模型自由發揮。

## 測試方式

聊天 smoke test：

```powershell
python tools\llm_chat_smoke_test.py
```

語法檢查：

```powershell
python -m py_compile app.py state.py standard_loader.py llm_chat.py tracker\camera.py tracker\calibration.py tracker\pen_tracker.py web\routes.py web\template.py web\viz.py
```

## 資料

- [`hanzi/`](hanzi)
  - 專案主要字庫資料。
  - 每個 `.json` 大致對應一個字的標準筆畫資料。

- `standard_db/`
  - 若存在，會優先作為已處理的標準字資料來源。

- [`saved_writings/`](saved_writings)
  - 儲存分析後輸出的 CSV 與使用者筆跡圖。

## 3D 列印支架

專案也包含給硬體展示用的 3D 列印支架設計，目標硬體為：

- Jetson Nano
- Logitech C922 Pro Stream Webcam

目前主要 3D 檔案在 [`3d_mount/`](3d_mount)：

- [`3d_mount/generate_mounts.py`](3d_mount/generate_mounts.py)
- [`3d_mount/jetson_nano_base.stl`](3d_mount/jetson_nano_base.stl)
- [`3d_mount/mast_base.stl`](3d_mount/mast_base.stl)
- [`3d_mount/mast_segment_50mm.stl`](3d_mount/mast_segment_50mm.stl)
- [`3d_mount/camera_head.stl`](3d_mount/camera_head.stl)

目前已確認的尺寸：

- `jetson_nano_base.stl`: `126 x 136 x 28 mm`
- `mast_base.stl`: `97 x 36 x 36 mm`
- `mast_segment_50mm.stl`: `65 x 30 x 50 mm`
- `camera_head.stl`: `65 x 150 x 26 mm`

目前設計重點：

- Nano 放置區可用平面：`102 x 82 mm`
- 柱子外形：`65 x 30 mm`
- 柱子單段高度：`50 mm`

建議起始列印參數：

- 材料：`PETG` 或 `PLA`
- 層高：`0.20 mm`
- 壁數：`4`
- 填充：`30%`

更細的裝配與列印說明請看 [`3d_mount/README.md`](3d_mount/README.md)。

[`hardware_stl/`](hardware_stl) 目前保留作為較早期或替代版本的 STL 輸出。

## 常用工具腳本

- [`tools/llm_chat_smoke_test.py`](tools/llm_chat_smoke_test.py)
  - 測試聊天規則是否正常。

- [`tools/build_index.py`](tools/build_index.py)
  - 建立字庫索引。

- [`tools/fetch_hanziwriter.py`](tools/fetch_hanziwriter.py)
  - 抓取字庫來源資料。

- [`tools/generate_db.py`](tools/generate_db.py)
  - 生成標準字資料。

- [`tools/fill_empty_hanzi.py`](tools/fill_empty_hanzi.py)
  - 補齊或修復 `hanzi/*.json`。

- [`tools/calibrate_homography.py`](tools/calibrate_homography.py)
  - 獨立校正工具。

- `tools/cam_*_probe.py`
  - 相機偵測與排查工具。

- [`tools/visual.py`](tools/visual.py)
  - 視覺化使用者筆跡資料。

- [`tools/visual_hanzi.py`](tools/visual_hanzi.py)
  - 對照標準字與使用者筆跡。

- [`tools/shuffle_user_strokes.py`](tools/shuffle_user_strokes.py)
  - 產生錯誤筆順樣本。

## 已知限制

- 這套系統仍然很吃硬體條件，像相機角度、光線、筆的顏色、紙張位置都會影響效果。
- [`tracker/pen_tracker.py`](tracker/pen_tracker.py) 目前仍是最硬體耦合、最難拆的小宇宙。
- 前端仍寫在一個模板檔裡，不是拆成獨立元件式架構。
- Ollama 目前是單一後端整合，沒有多模型/多後端抽象。
- 字庫很大，但不代表所有特殊字、特殊寫法都已完全驗證。

## 建議後續方向

- 持續整理 runtime 檔案內的訊息與註解一致性。
- 若 UI 繼續成長，可把 [`web/template.py`](web/template.py) 拆出來。
- 增加更多聊天與狀態切換 smoke test。
- 若系統繼續擴充，建議把 tracker、analysis、chat 拆成更明確的 service 邊界。

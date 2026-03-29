# Handwriting Analysis System

以攝影機即時追蹤紙上手寫軌跡，分析漢字筆畫數、筆順與整體字形，並透過 Web 介面與 LLM 提供互動式練習回饋。

## 目前進度

目前已完成的主體功能：

- Flask Web 介面可即時顯示相機畫面、目標字、評分結果與標準筆畫圖
- `PenTracker` 可持續讀取攝影機畫面並記錄 `(timestamp, x, y, pen_state)` 軌跡
- 支援 MediaPipe 手部偵測，若初始化失敗會自動退回 HSV 顏色偵測流程
- 支援紙張 ROI 檢查與 homography 透視校正
- 支援錄製、重設、Undo、送評分、切換相機、隨機換題
- 已整合 9500+ 個 `hanzi-writer` 漢字資料檔
- 評分核心可判斷：
  - `STROKE_COUNT_MISMATCH`
  - `ORDER_WRONG`
  - `WRONG_CHARACTER`
  - `OK`
- 送評分後會自動存出 CSV 與使用者筆跡圖到 `saved_writings/`
- 已加入 LLM 對話與簡短教學反饋
- 支援從聊天視窗直接指定下一題練習字

## 系統架構

### 1. 入口與執行模型

- [app.py](app.py)
  - 啟動 Flask
  - 建立 `PenTracker`
  - 主執行緒持續跑攝影機追蹤迴圈

### 2. 執行期狀態

- [state.py](state.py)
  - 目前已收斂成單一 `AppState` 物件
  - 統一管理：
    - 當前 frame
    - 目標字
    - 標準筆畫 JSON
    - 最新評分結果
    - 對話指定的下一題
    - tracker 參照

### 3. 視覺追蹤

- [tracker/pen_tracker.py](tracker/pen_tracker.py)
  - 主流程：
    1. 讀相機畫面
    2. 偵測紙張是否放在 ROI 內
    3. 使用 MediaPipe 抓手部關鍵點
    4. 沿食指方向推估筆尖搜尋區
    5. 在搜尋區內用 HSV 找藍色筆尖
    6. 以手勢與顏色共同決定 pen down / pen up
    7. 將結果記錄進 `strokes_data`

- [tracker/camera.py](tracker/camera.py)
  - 相機掃描順序
  - C922 偵測
  - 切換相機

- [tracker/calibration.py](tracker/calibration.py)
  - 自動與手動 homography 校正

### 4. 評分核心

- [compare.py](compare.py)
  - 筆畫切段
  - 離群筆畫過濾
  - 整字正規化
  - Arc-length 重取樣
  - DTW 比對
  - 中心距離矩陣筆順偵測

### 5. 標準字庫

- [standard_loader.py](standard_loader.py)
  - 優先讀 `standard_db/`
  - 若不存在則 fallback 讀 `hanzi/`
  - 目前 repo 主要實際使用的是 `hanzi/` 原始資料

### 6. Web 與互動

- [web/routes.py](web/routes.py)
  - `/video_feed`
  - `/get_target`
  - `/get_result`
  - `/std_strokes.png`
  - `/command/<action>`
  - `/chat`

- [web/template.py](web/template.py)
  - 單檔前端模板
  - 包含按鈕、結果顯示、聊天區、輪詢更新邏輯

### 7. LLM 輔助

- [llm_chat.py](llm_chat.py)
  - 規則式解析練習字
  - 筆畫問題優先直接查字庫回答
  - 其餘對話交給 Ollama
  - 根據評分結果產生簡短繁中教學回饋

## 評分流程

1. 使用者按 `Record`
2. 系統開始累積 `strokes_data`
3. 使用者按 `Send`
4. `PenTracker` 將軌跡切成筆畫
5. 載入目標字標準筆畫
6. 執行 `compare.verify_character()`
7. 更新 Web 顯示結果
8. 儲存：
   - CSV 軌跡
   - 使用者筆跡 PNG
9. 若 LLM 可用，再產生教學反饋

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

開啟：

```text
http://127.0.0.1:5000
```

## 依賴

- Python 3.10+
- Flask
- OpenCV
- NumPy
- Pandas
- MediaPipe
- pygrabber

安裝列表見 [requirements.txt](requirements.txt)。

## LLM 設定

目前 `llm_chat.py` 預設走本機 Ollama。

可用環境變數：

```powershell
$env:OLLAMA_HOST="http://localhost:11434"
$env:OLLAMA_MODEL="qwen2.5:3b"
```

若未啟動 Ollama：

- 對話功能會失敗
- 但影像追蹤與評分主流程仍可使用

## 操作流程

1. 將白紙放入綠框中
2. 按 `Record`
3. 在紙上書寫顯示的目標字
4. 按 `Send`
5. 查看評分結果與標準筆畫提示
6. 按 `Next` 換題，或在聊天區直接指定下一題

## 3D 列印硬體支架

這個專案目前也包含一套給 `Jetson Nano + Logitech C922 Pro Stream Webcam` 使用的 3D 列印支架設計，目的是把系統移到 Jetson Nano 上執行，並用後方立柱與相機平台讓鏡頭能垂直向下拍攝紙面。

目前設計重點：

- `Jetson Nano` 托盤底座
- 位於板子正後方的立柱基座
- 可堆疊的高度調整立柱
- 給 `C922` 夾具使用的 `camera_head` 平台
- 立柱上的走線通道，方便整理 webcam 線材

目前主要 STL 與生成腳本位於：

- `3d_mount/`
  - `generate_mounts.py`
  - `jetson_nano_base.stl`
  - `mast_base.stl`
  - `mast_segment_50mm.stl`
  - `camera_head.stl`
- `hardware_stl/`
  - 另存的一組硬體 STL 輸出

目前 3D 支架尺寸摘要：

- 柱子外形：`65 x 30 mm`
- 柱子單段高度：`50 mm`
- Nano 托盤可用區：`102 x 82 mm`
- `jetson_nano_base.stl` 外形：`126 x 136 x 28 mm`
- `mast_base.stl` 外形：`97 x 36 x 36 mm`
- `mast_segment_50mm.stl` 外形：`65 x 30 x 50 mm`
- `camera_head.stl` 外形：`65 x 150 x 26 mm`

列印建議起始參數：

- 材料：`PETG` 或 `PLA`
- 層高：`0.20 mm`
- 牆層數：`4`
- 填充：`30%`
- `camera_head.stl` 建議開支撐

更細的接頭尺寸、裝配方式與列印說明，請看 [3d_mount/README.md](3d_mount/README.md)。

## 專案結構

```text
app.py
state.py
compare.py
standard_loader.py
llm_chat.py
tracker/
  camera.py
  calibration.py
  pen_tracker.py
web/
  __init__.py
  routes.py
  template.py
  viz.py
3d_mount/
  README.md
  generate_mounts.py
  *.stl
hardware_stl/
  *.stl
tools/
  build_index.py
  calibrate_homography.py
  cam_*_probe.py
  fetch_hanziwriter.py
  fill_empty_hanzi.py
  generate_db.py
  shuffle_user_strokes.py
  test.py
  visual.py
  visual_hanzi.py
hanzi/
saved_writings/
hand_landmarker.task
```

## 資料與工具

- `hanzi/`
  - 9500+ 個漢字資料

- `saved_writings/`
  - 每次送分的 CSV 與筆跡圖

- [tools/fill_empty_hanzi.py](tools/fill_empty_hanzi.py)
  - 補抓原本為空的 `hanzi/*.json`

- `tools/cam_*_probe.py`
  - 相機除錯工具

- `tools/visual.py`
  - 使用者軌跡視覺化

- `tools/visual_hanzi.py`
  - 標準字與使用者筆跡對照

- `3d_mount/`
  - Jetson Nano 與 C922 的模組化 3D 列印支架

- `hardware_stl/`
  - 目前額外輸出的 STL 成品檔

## 已知限制

- 目前前端仍是單檔字串模板，維護性一般
- 執行模式仍以單進程本機 demo 為主，不是多使用者部署架構
- 偵測品質仍受光線、鏡頭角度、紙張位置、筆顏色影響
- LLM 目前僅整合 Ollama，尚未抽象成多後端配置
- `hanzi/` 資料檔目前處於整理階段，部分檔案近期有補資料變動

## 後續建議

- 將前端從 `web/template.py` 拆成獨立模板與靜態資源
- 為 `compare.py` 與 `PenTracker` 加上更明確的單元測試
- 將狀態流進一步收斂為明確的 service/controller 層
- 為 LLM 模組增加 fallback 與 timeout UI 提示
- 將 `hanzi/` 的補資料結果整理後正式提交

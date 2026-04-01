# 手寫分析系統

這是一套以紙本書寫為核心的即時漢字手寫分析系統。  
系統會透過攝影機擷取使用者在紙上書寫的筆跡，將資料轉成 `(timestamp, x, y, pen_state)` 的軌跡格式，再與標準字資料比對，分析筆畫數、筆順與整體字形是否合理。

## 系統架構

```
React 前端 (Vite)          Flask 後端               遠端 Container (RTX 3090)
localhost:5173       →    localhost:5000       →    140.113.110.42:50052
                          相機 / MediaPipe /         Ollama + qwen3:14b
                          筆跡分析 / API              LLM 推論
```

- **前端**：React (Vite)，提供練習介面、聊天室、分析結果顯示
- **後端**：Flask，負責相機讀取、手部追蹤、筆跡錄製、筆順比對、API 路由
- **LLM 推論**：Ollama 跑在遠端 Docker container（RTX 3090 GPU），模型為 qwen3:14b

聊天與回饋完全由 LLM 驅動，不再依賴規則式 prompt。LLM 透過 marker 機制（`【設定字：X】`、`【隨機換字】`）控制換字邏輯。

## 主要功能

- 即時相機畫面顯示
- 紙張 ROI 偵測與書寫區域校正
- MediaPipe 手部追蹤 + HSV 筆尖顏色追蹤
- 筆跡錄製、復原、清空、送出分析
- 自動換題與聊天換字
- 標準筆順圖顯示與錯誤筆畫標示
- 筆順驗證：`OK` / `ORDER_WRONG` / `WRONG_CHARACTER` / `STROKE_COUNT_MISMATCH`
- AI 老師聊天（LLM 驅動，支援閒聊、換字、筆畫問答）
- AI 回饋（比對使用者筆跡座標與標準筆跡，給出具體建議）
- 分析後自動存出 CSV 與使用者筆跡圖到 [`saved_writings/`](saved_writings)
- 3D 列印支架設計（Jetson Nano + Logitech C922）

## 主要流程

1. [`app.py`](app.py) 啟動 Flask 與追蹤器
2. [`tracker/pen_tracker.py`](tracker/pen_tracker.py) 持續讀取相機影像，偵測手與筆尖
3. 使用者開始錄製後，系統記錄筆跡資料
4. 送出分析後，由 [`compare.py`](compare.py) 和標準字資料做比對
5. 分析結果透過 [`state.py`](state.py) 回傳給前端
6. [`llm_chat.py`](llm_chat.py) 提供 AI 聊天與筆跡回饋（透過遠端 Ollama）
7. React 前端 [`frontend/src/App.jsx`](frontend/src/App.jsx) 顯示所有介面

## 核心檔案

| 檔案 | 說明 |
|------|------|
| [`app.py`](app.py) | 啟動入口 |
| [`state.py`](state.py) | 共用執行狀態（題目、畫面、分析結果） |
| [`tracker/pen_tracker.py`](tracker/pen_tracker.py) | 相機讀取、手部追蹤、筆跡錄製、校正、送分析 |
| [`compare.py`](compare.py) | 筆順驗證核心 |
| [`standard_loader.py`](standard_loader.py) | 載入標準字資料（優先 `standard_db/`，fallback `hanzi/`） |
| [`llm_chat.py`](llm_chat.py) | LLM 聊天與回饋模組 |
| [`web/routes.py`](web/routes.py) | Flask API 路由 |
| [`web/viz.py`](web/viz.py) | 標準筆順與筆跡視覺化 |
| [`frontend/src/App.jsx`](frontend/src/App.jsx) | React 前端主元件 |

## 專案結構

```text
app.py                    # Flask 啟動入口
compare.py                # 筆順比對
llm_chat.py               # LLM 聊天與回饋
state.py                  # 共用狀態
standard_loader.py        # 標準字載入
requirements.txt          # Python 套件
hand_landmarker.task      # MediaPipe 模型

frontend/                 # React 前端 (Vite)
  src/
    App.jsx
    App.css
  package.json
  vite.config.js

tracker/
  camera.py
  calibration.py
  pen_tracker.py

web/
  __init__.py
  routes.py
  template.py             # 舊版內嵌前端（保留）
  viz.py

tools/                    # 工具腳本
  llm_chat_smoke_test.py
  build_index.py
  calibrate_homography.py
  fetch_hanziwriter.py
  generate_db.py
  fill_empty_hanzi.py
  visual.py
  visual_hanzi.py
  shuffle_user_strokes.py

hanzi/                    # 字庫 JSON
saved_writings/           # 分析輸出
3d_mount/                 # 3D 列印支架
hardware_stl/             # 早期 STL 檔案
```

## 安裝方式

### Python 後端

```bash
git clone https://github.com/joshua12390902/Handwriting_Analysis_System.git
cd Handwriting_Analysis_System
python -m venv .venv
pip install -r requirements.txt
```

### React 前端

```bash
cd frontend
npm install
```

## 啟動方式

### 1. 確認遠端 Ollama 已啟動

SSH 進 container，在 tmux 中執行：

```bash
ssh root@140.113.110.42 -p 50002
tmux attach  # 或 tmux new
OLLAMA_FLASH_ATTENTION=1 OLLAMA_NUM_GPU=999 OLLAMA_HOST=0.0.0.0:8888 ollama serve
```

### 2. 啟動 Flask 後端

```bash
python app.py
```

後端啟動在 `http://127.0.0.1:5000`。預設已連接遠端 Ollama（`http://140.113.110.42:50052`）。

### 3. 啟動 React 前端

```bash
cd frontend
npm run dev
```

前端啟動在 `http://localhost:5173`。

## LLM 與 Ollama

| 環境變數 | 預設值 | 說明 |
|----------|--------|------|
| `OLLAMA_HOST` | `http://140.113.110.42:50052` | 預設遠端 Ollama API 位址，可用環境變數覆蓋 |
| `OLLAMA_MODEL` | `qwen3:14b` | 使用的模型 |

### Port 對照

| 位置 | Port | 用途 |
|------|------|------|
| Container 內 | 8888 | Ollama 監聽 |
| 主機 | 50052 | 映射到 container 8888 |
| 主機 | 50002 | SSH 進 container |
| 你的電腦 | 5000 | Flask 後端 |
| 你的電腦 | 5173 | Vite dev server |

如果沒有啟動 Ollama，主分析流程仍可使用，AI 聊天與回饋會退化為簡單規則回覆。

## 基本使用流程

1. 把白紙放進畫面中的書寫框內
2. 在網頁中按下「開始錄製」
3. 在紙上書寫目前題目
4. 按下「送出分析」
5. 查看分析結果、標準筆順圖與 AI 回饋
6. 按「下一題」或在聊天室切換字

## 聊天功能

聊天完全由 qwen3:14b 驅動，支援：

- 指定練習字：「我想練永」→ LLM 回覆並附上 `【設定字：永】`
- 隨機換字：「隨便換一個」→ LLM 回覆 `【隨機換字】`
- 詢問寫得如何：根據最新分析結果回答
- 一般閒聊與漢字問答

## 3D 列印支架

目標硬體：Jetson Nano + Logitech C922 Pro Stream Webcam

主要檔案在 [`3d_mount/`](3d_mount)，詳見 [`3d_mount/README.md`](3d_mount/README.md)。

建議列印參數：PETG 或 PLA，層高 0.20mm，壁數 4，填充 30%。

## 相依套件

Python（定義在 [`requirements.txt`](requirements.txt)）：
- Flask, flask-cors
- NumPy, OpenCV, Pandas
- MediaPipe, pygrabber

前端：
- React, Vite

建議 Python 版本：3.10 以上

## 常用工具腳本

| 腳本 | 說明 |
|------|------|
| [`tools/llm_chat_smoke_test.py`](tools/llm_chat_smoke_test.py) | 聊天功能測試 |
| [`tools/build_index.py`](tools/build_index.py) | 建立字庫索引 |
| [`tools/fetch_hanziwriter.py`](tools/fetch_hanziwriter.py) | 抓取字庫來源資料 |
| [`tools/generate_db.py`](tools/generate_db.py) | 生成標準字資料 |
| [`tools/fill_empty_hanzi.py`](tools/fill_empty_hanzi.py) | 補齊 hanzi/*.json |
| [`tools/calibrate_homography.py`](tools/calibrate_homography.py) | 獨立校正工具 |
| [`tools/visual.py`](tools/visual.py) | 視覺化使用者筆跡 |
| [`tools/visual_hanzi.py`](tools/visual_hanzi.py) | 對照標準字與使用者筆跡 |

## 已知限制

- 系統效果受硬體條件影響（相機角度、光線、筆色、紙張位置）
- [`tracker/pen_tracker.py`](tracker/pen_tracker.py) 硬體耦合度高
- Ollama 目前為單一後端，沒有多模型抽象
- 字庫大但不保證所有特殊字都已驗證

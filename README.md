# 手寫分析系統

這個專案是一套以相機擷取紙上書寫、分析筆順與字形，並結合遠端 LLM 給出教學回饋的互動式手寫練習系統。

系統分成三塊：
- Flask 後端：相機、MediaPipe、筆跡分析、API
- React 前端：練習介面、結果顯示、AI 聊天
- 遠端 LLM：Ollama + `qwen3:14b`，跑在 GPU container

## 系統架構

```text
React 前端
  ↓
Flask 後端
  ↓
相機 / MediaPipe / 筆跡分析 / API
  ↓
遠端 Ollama API
  ↓
qwen3:14b（RTX 3090）
```

目前預設的遠端 LLM 位址：

- `http://140.113.110.42:50052`

## 主要功能

- 即時相機畫面擷取
- 手部追蹤與筆尖定位
- 筆畫錄製、重設、送出分析
- 筆順、字形、筆畫數比對
- 標準筆順視覺化
- AI 書寫回饋
- AI 聊天助教
- 書寫結果與 CSV 輸出
- Jetson Nano + Logitech C922 硬體支架設計

## 核心檔案

- [`app.py`](app.py)：Flask 啟動入口
- [`tracker/pen_tracker.py`](tracker/pen_tracker.py)：相機、追蹤、錄製與分析主流程
- [`compare.py`](compare.py)：筆跡比對邏輯
- [`state.py`](state.py)：全域狀態管理
- [`llm_chat.py`](llm_chat.py)：遠端 Ollama 呼叫與聊天/回饋邏輯
- [`web/routes.py`](web/routes.py)：Flask 路由
- [`frontend/src/App.jsx`](frontend/src/App.jsx)：React 前端主介面

## 專案結構

```text
app.py
compare.py
llm_chat.py
state.py
standard_loader.py
requirements.txt
requirements-jetson.txt
hand_landmarker.task

frontend/
  src/
  dist/

tracker/
web/
tools/
hanzi/
saved_writings/
3d_mount/
hardware_stl/
docs/
```

## 一般開發環境

### Python 後端

```bash
git clone https://github.com/joshua12390902/Handwriting_Analysis_System.git
cd Handwriting_Analysis_System
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

### React 前端

```bash
cd frontend
npm install
npm run dev
```

預設開發網址：
- Flask：`http://127.0.0.1:5000`
- Vite：`http://localhost:5173`

## 遠端 Ollama / LLM 部署方式

本專案的 LLM 不是跑在本機，也不是跑在 Jetson Nano。  
目前實際架構是：

```text
本機 / Jetson Nano
  ↓
http://140.113.110.42:50052
  ↓
Docker port mapping
  ↓
container:8888
  ↓
Ollama
  ↓
qwen3:14b（RTX 3090）
```

也就是：
- 應用程式只負責送 prompt 與接收回覆
- 真正的模型推論發生在遠端 container
- container 內的 Ollama 監聽 `8888`
- 主機把 `50052` 映射到 container 的 `8888`
- `50002` 是 SSH 進 container 的埠

### tmux 常駐方式

遠端 Ollama 目前是透過 **container 內的 tmux session 常駐執行**。  
這一點很重要，因為如果只是直接跑 `ollama serve`，SSH 關掉之後服務就會一起停掉。

若要確認或重新啟動遠端 LLM，可執行：

```bash
ssh root@140.113.110.42 -p 50002
tmux attach  # 若沒有 session 可用 tmux new
OLLAMA_FLASH_ATTENTION=1 OLLAMA_NUM_GPU=999 OLLAMA_HOST=0.0.0.0:8888 ollama serve
```

一般使用者通常不需要進 container；只有在遠端 LLM 服務中斷、需要檢查或重啟時，才需要進去看 tmux。

### 環境變數

| 變數 | 預設值 | 用途 |
|------|--------|------|
| `OLLAMA_HOST` | `http://140.113.110.42:50052` | 遠端 Ollama API |
| `OLLAMA_MODEL` | `qwen3:14b` | 使用模型 |

### Port 對照

| 位置 | Port | 用途 |
|------|------|------|
| Container 內 | 8888 | Ollama 監聽 |
| 主機 | 50052 | 映射到 container 8888 |
| 主機 | 50002 | SSH 進 container |
| 本地後端 | 5000 | Flask |
| 本地前端 | 5173 | Vite dev server |

## Jetson Nano 部署重點

Jetson Nano 已實測可跑通，但正式做法和一般桌面開發不同。

### 已驗證路線

- Ubuntu 18.04.6
- Python 3.9.19
- 虛擬環境：`.venv39`
- `pip install mediapipe==0.10.9`
- 遠端 Ollama：`http://140.113.110.42:50052`

### 為什麼 Jetson 走特別路線

- Jetson 內建 Python 3.6 太舊
- MediaPipe source build 在這個環境上會卡到 `GLIBC_2.28`
- Jetson 上 Node.js 16 無法直接跑新版 Vite

### Jetson 依賴

Jetson 請使用：

```bash
pip install -r requirements-jetson.txt
```

Jetson 版依賴重點：
- `mediapipe==0.10.9`
- 不安裝 `pygrabber`

### Jetson 前端部署方式

Jetson Nano 不跑 `npm run dev`。  
正式做法是：

1. 在 Windows 電腦先 build 前端
2. 把 `frontend/dist` 複製到 Jetson
3. Jetson 上只跑 Flask
4. Flask 直接 serve build 好的前端

Windows 端：

```bash
cd frontend
npm install
npm run build
```

複製到 Jetson：

```bash
scp -r frontend/dist/ penyi@Jetson_IP:~/Handwriting_Analysis_System/frontend/
```

Jetson 端啟動：

```bash
cd ~/Handwriting_Analysis_System
source .venv39/bin/activate
python app.py
```

之後直接開：

```text
http://Jetson_IP:5000
```

更完整的 Jetson 安裝流程請看：

- [`docs/JETSON_NANO_README.md`](docs/JETSON_NANO_README.md)

## 3D 列印支架

目標硬體：
- Jetson Nano
- Logitech C922 Pro Stream Webcam

相關檔案在：
- [`3d_mount/`](3d_mount)
- [`3d_mount/README.md`](3d_mount/README.md)

## 備註

- 相機、光線、紙張位置會直接影響辨識效果
- Jetson 上目前相機 probe 順序仍會先試 `1..4` 再試 `0`，因此啟動時可能看到一些 warning，但只要最後成功打開 `video0` 就可正常使用
- 若本地有另外 clone `~/mediapipe` source tree，測試 pip 安裝的 MediaPipe 時不要在那個目錄裡執行，避免被本地 source 蓋掉

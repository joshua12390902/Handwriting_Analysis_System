# Jetson Nano 安裝與啟動 README

## 目的
這份文件整理目前已經實測可行的 Jetson Nano 部署方式，讓其他人不用再重走 MediaPipe source build 那條路。

## 最終可行路線
Jetson Nano 目前採用的正式路線是：
- Ubuntu 18.04.6
- Python 3.9.19
- 專案虛擬環境：`.venv39`
- `pip install mediapipe==0.10.9`
- 遠端 Ollama：`http://140.113.110.42:50052`

不要採用目前 MediaPipe source build 當正式部署方法，因為在 Jetson Nano 這個環境上會卡到 Bazel / Node 依賴的 `GLIBC_2.28` 問題。

## Jetson Nano 需要負責的內容
Jetson Nano 端負責：
- Flask 後端
- OpenCV 攝影機流程
- MediaPipe 手部追蹤
- 手寫分析邏輯
- 呼叫遠端 Ollama API

Jetson Nano 不需要本地跑大模型。

## 0. 前提
已確認：
- Jetson Nano 可連網
- 可透過 SSH 連入 Jetson Nano
- USB 攝影機已接上
- 專案已 clone 到 Jetson Nano

## 1. 取得專案
```bash
git clone -b react-lina https://github.com/joshua12390902/Handwriting_Analysis_System.git
cd Handwriting_Analysis_System
```

## 2. 安裝 Python 3.9.19
Jetson Nano 內建 Python 3.6.9 太舊，因此需自行安裝 Python 3.9。

先安裝編譯依賴：
```bash
sudo apt update
sudo apt install -y \
  build-essential \
  wget \
  libssl-dev \
  zlib1g-dev \
  libbz2-dev \
  libreadline-dev \
  libsqlite3-dev \
  libffi-dev \
  libncurses5-dev \
  libncursesw5-dev \
  liblzma-dev \
  tk-dev \
  uuid-dev
```

下載並編譯 Python 3.9.19：
```bash
cd ~
wget https://www.python.org/ftp/python/3.9.19/Python-3.9.19.tgz
tar -xzf Python-3.9.19.tgz
cd Python-3.9.19
./configure --prefix=$HOME/.local/python-3.9.19 --with-ensurepip=install --with-openssl=/usr
make -j2
make install
```

驗證 SSL 正常：
```bash
$HOME/.local/python-3.9.19/bin/python3.9 -c "import ssl; print(ssl.OPENSSL_VERSION)"
```

## 3. 建立虛擬環境
回到專案根目錄：
```bash
cd ~/Handwriting_Analysis_System
$HOME/.local/python-3.9.19/bin/python3.9 -m venv .venv39
source .venv39/bin/activate
python --version
```

預期：
```bash
Python 3.9.19
```

## 4. 安裝 Jetson 依賴
先升級 pip 工具：
```bash
pip install --upgrade pip setuptools wheel
```

安裝 Jetson 依賴：
```bash
pip install -r requirements-jetson.txt
```

目前 `requirements-jetson.txt` 會包含：
- flask
- flask-cors
- numpy
- opencv-python
- pandas
- `mediapipe==0.10.9`

注意：
- `pygrabber` 是 Windows-only，不需要在 Jetson 安裝
- MediaPipe 在 Jetson 上請固定用 `0.10.9`

## 5. 驗證 Python 套件
```bash
python -c "import cv2; print(cv2.__version__)"
python -c "import mediapipe as mp; print(mp.__version__)"
python -c "from mediapipe.tasks import python as mp_tasks; from mediapipe.tasks.python import vision as mp_vision; print('tasks ok')"
```

注意：
不要在自己另外 clone 的 `~/mediapipe` source 目錄裡做這些測試，否則會被本地 source tree 蓋掉 pip 安裝版本。

## 6. 驗證遠端 Ollama
```bash
python -c "import urllib.request; r=urllib.request.urlopen('http://140.113.110.42:50052/api/tags', timeout=15); print(r.status); print(r.read(300).decode('utf-8', errors='ignore'))"
```

預期：
- HTTP status 為 `200`
- 回傳模型清單中包含 `qwen3:14b`

## 7. 驗證攝影機
安裝 V4L2 工具：
```bash
sudo apt install -y v4l-utils
```

查看裝置：
```bash
ls -l /dev/video*
v4l2-ctl --list-devices
lsusb
```

OpenCV 最小測試：
```bash
python - <<'PY'
import cv2
for i in range(5):
    cap = cv2.VideoCapture(i, cv2.CAP_V4L2)
    ok = cap.isOpened()
    print("index", i, "opened =", ok)
    if ok:
        ret, frame = cap.read()
        print("index", i, "read =", ret, "shape =", None if frame is None else frame.shape)
    cap.release()
PY
```

目前實測結果：
- Jetson Nano 上只有 `/dev/video0` 可用
- Logitech C922 可正常被偵測

## 8. 啟動專案
在專案根目錄執行：
```bash
cd ~/Handwriting_Analysis_System
source .venv39/bin/activate
python app.py
```

成功時應看到類似：
- Flask 啟動於 `0.0.0.0:5000`
- Camera opened: index=0
- `MediaPipe HandLandmarker 初始化成功。`

## 9. 前端部署方式
Jetson Nano 不建議直接跑 Vite dev server。

原因：
- Jetson 上目前是 Node.js 16
- 新版 Vite 需要 Node 20+
- Jetson 這個環境還會受 glibc 限制影響，不適合在本機直接升到新版 Node 做前端開發

正式做法是：
- 在 Windows 電腦先把 React 前端 build 成靜態檔
- 把 `frontend/dist` 複製到 Jetson Nano
- Jetson Nano 只跑 Flask，由 Flask 直接 serve build 好的前端

### 9.1 Windows 端 build 前端
在 Windows 專案目錄執行：
```bash
cd frontend
npm install
npm run build
```

完成後會產生：
```text
frontend/dist/
```

### 9.2 把 dist 複製到 Jetson Nano
例如：
```bash
scp -r frontend/dist/ penyi@Jetson_IP:~/Handwriting_Analysis_System/frontend/
```

### 9.3 Jetson Nano 端啟動
Jetson Nano 上只需要：
```bash
cd ~/Handwriting_Analysis_System
source .venv39/bin/activate
python app.py
```

### 9.4 開啟頁面
之後直接在瀏覽器打：
```text
http://Jetson_IP:5000
```

目前 Flask 已經會在偵測到 `frontend/dist` 時：
- 直接 serve `dist/index.html`
- 直接 serve `dist/assets/*`

所以 Nano 不需要再額外跑 `npm run dev`。

## 10. 已知事項
- 目前相機 probe 順序仍會先試 `1,2,3,4`，最後才試 `0`
- 因此啟動時會看到一串 camera warning
- 但只要最後出現 `Camera opened: index=0`，就表示系統已正常啟動

## 11. 結論
目前 Jetson Nano 的正式可行部署方式是：
- Python 3.9.19
- `.venv39`
- `pip install mediapipe==0.10.9`
- 遠端 Ollama `http://140.113.110.42:50052`
- Windows 先 build `frontend/dist`
- Jetson Nano 用 Flask 直接 serve 前端
- 從專案根目錄執行 `python app.py`

這是目前已實測可跑通的路線。

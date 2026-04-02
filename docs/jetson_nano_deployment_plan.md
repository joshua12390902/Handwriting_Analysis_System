# Jetson Nano Deployment Plan

## Goal
Run the Handwriting Analysis System on Jetson Nano while keeping LLM inference on the remote Ollama server.

## Validated deployment path
The validated Jetson Nano path is:
- Ubuntu 18.04.6
- Python 3.9.19 in a dedicated virtual environment
- `pip install mediapipe==0.10.9`
- Remote Ollama at:
  - `http://140.113.110.42:50052`

## Important decision
Do not use the current MediaPipe source-build path for deployment on this Jetson Nano.

Reason:
- The explored source-build route for the current MediaPipe tree eventually depends on a Node / Bazel toolchain that requires `GLIBC_2.28`.
- Jetson Nano on Ubuntu 18.04 provides `glibc 2.27`.
- This makes the direct source-build route a poor fit for the current deployment target.

## Required runtime components on Jetson Nano
- Python 3.9.19
- Virtual environment:
  - `.venv39`
- Flask backend
- OpenCV
- pandas
- numpy
- MediaPipe:
  - `mediapipe==0.10.9`
- Local model file:
  - `hand_landmarker.task`

## Not required on Jetson Nano
- Local large language model inference
- MediaPipe source build
- `pygrabber`

Notes:
- `pygrabber` is Windows-only and should not be part of the Jetson dependency path.
- Jetson should call the remote Ollama API instead of running the model locally.

## Installation outline
1. Install or prepare Python 3.9.19.
2. Create and activate `.venv39`.
3. Install Jetson dependencies from `requirements-jetson.txt`.
4. Verify remote Ollama access.
5. Verify webcam access.
6. Start the app from the repository root.

## Runtime checks
Run these checks on Jetson Nano:

```bash
source .venv39/bin/activate
python --version
python -c "import cv2; print(cv2.__version__)"
python -c "import mediapipe as mp; print(mp.__version__)"
python -c "from mediapipe.tasks import python as mp_tasks; from mediapipe.tasks.python import vision as mp_vision; print('tasks ok')"
python -c "import urllib.request; r=urllib.request.urlopen('http://140.113.110.42:50052/api/tags', timeout=15); print(r.status)"
ls -l /dev/video*
```

## Launch
Run from the repository root:

```bash
source .venv39/bin/activate
python app.py
```

Expected result:
- Flask starts on `0.0.0.0:5000`
- Camera opens successfully
- MediaPipe HandLandmarker initializes successfully
- Web endpoints respond normally

## Known operational note
The current camera probe order still tries indices `1..4` before `0`, so startup may print warnings before eventually opening `video0`. This is noisy but not a blocker if the app ultimately reports that camera index `0` opened successfully.

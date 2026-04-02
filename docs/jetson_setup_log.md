# Jetson Nano Setup Log

## 2026-04-02 - Environment discovery
- Device: Jetson Nano
- OS: Ubuntu 18.04.6 LTS
- Arch: aarch64
- System Python: 3.6.9
- Initial conclusion:
  - The stock Python on Jetson was too old for the current project dependencies.
  - A separate Python 3.9 environment was required.

## 2026-04-02 - Python 3.9 route established
- Built and installed Python 3.9.19 under the user home directory.
- Rebuilt Python after confirming the `ssl` module was missing in the first build.
- Verified:
  - `python3.9 -c "import ssl; print(ssl.OPENSSL_VERSION)"`
- Created a clean virtual environment:
  - `.venv39`

## 2026-04-02 - Base Python dependencies verified
- Installed and verified:
  - Flask
  - Flask-Cors
  - numpy
  - pandas
- Verified OpenCV import:
  - `cv2 4.13.0`

## 2026-04-03 - Remote Ollama connectivity verified
- Confirmed Jetson Nano can reach the remote Ollama server:
  - `http://140.113.110.42:50052`
- Verified `/api/tags` returns the expected model list.
- Confirmed `hand_landmarker.task` is present in the project.

## 2026-04-03 - MediaPipe source-build exploration
- Attempted the source-build route with:
  - Java 11
  - Bazelisk / Bazel 7.4.1
  - MediaPipe source checkout
  - clang-10
  - gcc-10 / g++-10
- Findings from this exploration:
  - The current source-build route for the checked-out MediaPipe tree is not a good fit for Jetson Nano on Ubuntu 18.04.
  - The toolchain path eventually hit a Node / Bazel dependency that required:
    - `GLIBC_2.28`
  - Jetson Nano on Ubuntu 18.04 only provides:
    - `glibc 2.27`
- Conclusion:
  - Source-building the current MediaPipe tree was explored but is not the recommended deployment path for this Jetson environment.

## 2026-04-03 - Final validated MediaPipe route
- Direct wheel install was tested and succeeded:
  - `pip install mediapipe==0.10.9`
- Important result:
  - A working wheel was available for:
    - `cp39`
    - `manylinux2014_aarch64`
- Verified outside the local MediaPipe source directory:
  - `import mediapipe`
  - `from mediapipe.tasks import python`
  - `from mediapipe.tasks.python import vision`
- Final conclusion:
  - The validated Jetson route is:
    - Python 3.9
    - `pip install mediapipe==0.10.9`
  - Do not use the MediaPipe source-build route for the current Jetson Nano deployment.

## 2026-04-03 - Camera verification
- Confirmed camera device exists:
  - `/dev/video0`
- Confirmed webcam detection:
  - Logitech C922 Pro Stream Webcam
- Verified direct OpenCV access:
  - index `0` opens successfully
  - indices `1..4` do not open

## 2026-04-03 - Application launch verification
- Ran the project from:
  - `~/Handwriting_Analysis_System`
  - using `.venv39`
- Verified successful startup of:
  - Flask
  - OpenCV camera access
  - MediaPipe HandLandmarker
  - Remote Ollama integration path
- Observed successful requests to:
  - `/`
  - `/video_feed`
  - `/get_target`
  - `/get_result`

## Current validated Jetson deployment summary
- Use Python 3.9 in `.venv39`
- Use:
  - `pip install mediapipe==0.10.9`
- Keep using the remote Ollama endpoint:
  - `http://140.113.110.42:50052`
- Run the project from the repository root, not from a local `~/mediapipe` source checkout
- Treat the earlier MediaPipe source-build path as historical investigation, not the deployment method

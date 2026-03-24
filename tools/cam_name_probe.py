import cv2
names = [
    'C922 Pro Stream Webcam',
    'c922 Pro Stream Webcam',
    'USB2.0 HD UVC WebCam'
]
for n in names:
    src = f"video={n}"
    cap = cv2.VideoCapture(src, cv2.CAP_DSHOW)
    opened = cap.isOpened()
    ok = False
    if opened:
        ok, frame = cap.read()
    print(f"name={n} opened={opened} read={ok}", flush=True)
    if opened:
        print('shape=', None if not ok else frame.shape, flush=True)
    cap.release()

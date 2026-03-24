import cv2
for idx in [0,1,2,3,4]:
    cap = cv2.VideoCapture(idx)
    opened = cap.isOpened()
    ok = False
    w = h = fps = -1
    if opened:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        cap.set(cv2.CAP_PROP_FPS, 30)
        ok, frame = cap.read()
        w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        fps = cap.get(cv2.CAP_PROP_FPS)
    print(f"idx={idx} opened={opened} read={ok} wh=({w:.0f},{h:.0f}) fps={fps:.1f}", flush=True)
    cap.release()

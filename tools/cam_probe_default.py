import cv2
for idx in [0,1,2,3]:
    cap = cv2.VideoCapture(idx)
    opened = cap.isOpened()
    ok = False
    if opened:
        ok, _ = cap.read()
    print(f"DEFAULT idx={idx} opened={opened} read={ok}", flush=True)
    cap.release()

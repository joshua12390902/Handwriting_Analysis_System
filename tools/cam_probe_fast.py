import cv2
for idx in [0,1,2,3]:
    cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
    opened = cap.isOpened()
    ok = False
    if opened:
        ok, _ = cap.read()
    print(f"DSHOW idx={idx} opened={opened} read={ok}", flush=True)
    cap.release()
for idx in [0,1,2,3]:
    cap = cv2.VideoCapture(idx, cv2.CAP_MSMF)
    opened = cap.isOpened()
    ok = False
    if opened:
        ok, _ = cap.read()
    print(f"MSMF idx={idx} opened={opened} read={ok}", flush=True)
    cap.release()

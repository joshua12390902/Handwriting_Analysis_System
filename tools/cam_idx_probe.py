import cv2
for i in range(6):
    ok_any = False
    for b in [cv2.CAP_MSMF, cv2.CAP_DSHOW, None]:
        cap = cv2.VideoCapture(i) if b is None else cv2.VideoCapture(i, b)
        opened = cap.isOpened() if cap is not None else False
        ok = False
        if opened:
            ok, _ = cap.read()
        if cap is not None:
            cap.release()
        if opened and ok:
            ok_any = True
            break
    print(f'idx={i} usable={ok_any}')

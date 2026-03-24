#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
from pathlib import Path

import cv2
import numpy as np


def main():
    parser = argparse.ArgumentParser(description="手動點四角建立 homography.npy")
    parser.add_argument("--camera", type=int, default=0, help="相機索引，預設 0")
    parser.add_argument(
        "--output",
        type=str,
        default=str(Path(__file__).resolve().parents[1] / "homography.npy"),
        help="輸出 homography 檔案路徑",
    )
    args = parser.parse_args()

    cap = cv2.VideoCapture(args.camera, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        raise RuntimeError(f"無法開啟相機 index={args.camera}")

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    points = []
    window_name = "Calibrate Homography (click TL,TR,BR,BL)"

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN and len(points) < 4:
            points.append((float(x), float(y)))

    cv2.namedWindow(window_name)
    cv2.setMouseCallback(window_name, on_mouse)

    print("[INFO] 請依序點擊紙張四角：左上 -> 右上 -> 右下 -> 左下")
    print("[INFO] 鍵盤：r=重點, s=儲存, q=離開")

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                continue

            frame = cv2.flip(frame, -1)
            vis = frame.copy()

            cv2.rectangle(vis, (50, 50), (590, 430), (80, 80, 80), 1)
            cv2.putText(
                vis,
                "Click paper corners: TL -> TR -> BR -> BL",
                (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                2,
            )

            for idx, (x, y) in enumerate(points):
                cv2.circle(vis, (int(x), int(y)), 6, (0, 255, 255), -1)
                cv2.putText(
                    vis,
                    str(idx + 1),
                    (int(x) + 8, int(y) - 8),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 255, 255),
                    2,
                )

            if len(points) == 4:
                src = np.array(points, dtype=np.float32)
                dst = np.array(
                    [[50.0, 50.0], [590.0, 50.0], [590.0, 430.0], [50.0, 430.0]],
                    dtype=np.float32,
                )
                M = cv2.getPerspectiveTransform(src, dst)

                cv2.polylines(vis, [src.astype(np.int32)], True, (0, 255, 0), 2)
                cv2.putText(
                    vis,
                    "Press S to save homography.npy",
                    (10, 460),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 255, 0),
                    2,
                )
            else:
                M = None

            cv2.imshow(window_name, vis)
            key = cv2.waitKey(1) & 0xFF

            if key == ord("q"):
                print("[INFO] 取消校正")
                break
            if key == ord("r"):
                points.clear()
                print("[INFO] 已清除點位，請重新點選")
            if key == ord("s") and M is not None:
                output_path = Path(args.output).resolve()
                output_path.parent.mkdir(parents=True, exist_ok=True)
                np.save(str(output_path), M)
                print(f"[INFO] 已儲存 homography: {output_path}")
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()

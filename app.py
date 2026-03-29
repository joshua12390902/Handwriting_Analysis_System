#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app.py — 入口點

啟動 Flask 伺服器（背景執行緒）並執行攝影機追蹤主迴圈。
"""
import threading

import state
from web import app
import web.routes  # 註冊路由（side-effect import）
from tracker.pen_tracker import PenTracker


def main() -> None:
    # 1. Flask 跑在背景執行緒
    print("[INFO] 啟動 Flask Web 伺服器 http://0.0.0.0:5000 ...")
    flask_thread = threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=5000, debug=False, threaded=True),
        daemon=True,
    )
    flask_thread.start()

    # 2. 建立 Tracker（在此之後路由才能操作 tracker）
    tracker = PenTracker()
    state.app_state.set_tracker(tracker)

    # 3. 主執行緒跑攝影機迴圈（Ctrl+C 可中斷）
    try:
        tracker.run()
    except KeyboardInterrupt:
        print("\n[INFO] 使用者中斷，正在關閉...")
        tracker.is_running = False


if __name__ == "__main__":
    main()

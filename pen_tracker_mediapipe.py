#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pen_tracker_mediapipe.py — 向後相容入口點

保留此檔案是為了讓舊指令 `.venv/Scripts/python pen_tracker_mediapipe.py` 繼續有效。
實際邏輯已拆分到各模組，請見 app.py。
"""
from app import main

if __name__ == "__main__":
    main()

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import json
import os
import re

# 1. 解析 SVG 或 Median 資料
def load_json_strokes(json_path):
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # 優先使用中心線，若無則解析輪廓
    if "medians" in data:
        strokes = [np.array(s) for s in data["medians"]]
    elif "strokes" in data:
        def parse_svg(path_str):
            numbers = re.findall(r"[-+]?\d*\.\d+|\d+", path_str)
            return np.array(numbers, dtype=float).reshape(-1, 2)
        strokes = [parse_svg(s) for s in data["strokes"]]
    else:
        return []

    # --- 重要：修正 Standard 的座標系 ---
    # HanziWriter 座標通常 Y 是反的，我們在這裡統一做一次處理
    # 假設標準空間是 1024x1024
    corrected_strokes = []
    for s in strokes:
        # 如果 Standard 還是倒的，就啟用下面這行反轉 Y
        s[:, 1] = 1024 - s[:, 1] 
        corrected_strokes.append(s)
    
    return corrected_strokes

# 2. 載入 CSV 並處理翻轉
def load_csv_strokes(csv_path, flip_x=True, flip_y=True):
    df = pd.read_csv(csv_path)
    strokes, current, in_stroke = [], [], False
    # 您的畫布尺寸
    W, H = 800, 600 

    for _, row in df.iterrows():
        rx, ry, pen = float(row["x"]), float(row["y"]), int(row["pen_state"])
        
        # 這裡處理 User 的翻轉
        x = (W - rx) if flip_x else rx
        y = (H - ry) if flip_y else ry
        
        if pen == 1:
            if not in_stroke: in_stroke, current = True, []
            current.append([x, y])
        else:
            if in_stroke:
                in_stroke = False
                if len(current) > 5: strokes.append(np.array(current))
    
    if in_stroke and len(current) > 5: strokes.append(np.array(current))
    return strokes

# 3. 全字歸一化 (對齊關鍵)
def normalize_strokes(strokes_list):
    if not strokes_list: return []
    all_pts = np.vstack(strokes_list)
    center = all_pts.mean(axis=0)
    # 先平移到中心
    pts_centered = [s - center for s in strokes_list]
    # 計算縮放比例
    all_pts_centered = np.vstack(pts_centered)
    mn, mx = all_pts_centered.min(axis=0), all_pts_centered.max(axis=0)
    scale = max(float(np.max(mx - mn)), 1e-6)
    return [s / scale for s in pts_centered]

# 4. 繪圖對比
def plot_comparison(char, csv_path, json_path, u_flip_x=True, u_flip_y=True):
    user_raw = load_csv_strokes(csv_path, flip_x=u_flip_x, flip_y=u_flip_y)
    std_raw = load_json_strokes(json_path)

    user_n = normalize_strokes(user_raw)
    std_n = normalize_strokes(std_raw)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 6))

    def draw(ax, strokes, title, color):
        for i, s in enumerate(strokes):
            ax.plot(s[:, 0], s[:, 1], 'o-', label=f'S{i+1}', linewidth=2)
            ax.text(s[0, 0], s[0, 1], str(i+1), color=color, fontsize=14, fontweight='bold')
        ax.set_title(title)
        ax.set_aspect('equal')
        ax.grid(True, linestyle=':', alpha=0.6)
        # 強制座標軸一致：Y 軸由正到負（頂部為負）
        ax.set_xlim(-0.7, 0.7)
        ax.set_ylim(0.7, -0.7) 

    draw(ax1, std_n, f"Standard: {char}", "red")
    draw(ax2, user_n, f"User: {os.path.basename(csv_path)}", "blue")

    plt.tight_layout()
    plt.savefig("final_debug_comparison.png")
    print("已產出對比圖：final_debug_comparison.png")

if __name__ == "__main__":
    # 修改您的路徑
    char = "能"
    csv = "/workspace/Module_final/data/neng_14.csv"
    json_f = f"/workspace/Module_final/hanzi/{char}.json"
    
    # 調整參數直到兩邊看起來一樣
    # 如果 Standard (左圖) 還是倒的，請去 load_json_strokes 裡面解開 s[:, 1] = 1024 - s[:, 1] 的註解
    plot_comparison(char, csv, json_f, u_flip_x=False, u_flip_y=False)
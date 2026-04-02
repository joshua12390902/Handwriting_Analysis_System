# Jetson Nano + C922 3D Mount

這個資料夾放的是 Jetson Nano 與 Logitech C922 Pro Stream Webcam 的模組化支架設計。

目前輸出零件為：
- `jetson_nano_base.stl`
- `mast_segment_80mm.stl`
- `camera_head.stl`
- `generate_mounts.py`

## 組裝方式

目前設計採用：

```text
jetson_nano_base -> mast_segment_80mm x N -> camera_head
```

`mast_base` 已不再是正式輸出的一部分，現在直接由 `jetson_nano_base` 接第一段 `mast_segment_80mm`。

## 設計重點

- Jetson Nano 可放置的完整平坦區域：
  - `102 x 82 mm`
- 立柱段高度：
  - `80 mm`
- 使用 `peg / socket` 榫接方式堆疊
- 側邊有外掛式 cable clip
- `camera_head` 提供給 C922 夾具的承載平台與定位凹槽

## 榫接尺寸

目前榫接尺寸為：

注意：
- `peg / socket` 目前不是同尺寸
- 這是刻意保留的裝配間隙，不是寫錯

- Peg：
  - `48.8 x 19.8 x 16 mm`
- Socket 主內尺寸：
  - `49.0 x 20.0 x 17 mm`
- Socket 深度 relief：
  - `0.5 mm`
- Socket 入口放寬：
  - `1.0 mm`

這組尺寸代表：
- `peg` 比 `socket` 在 X/Y 每側放鬆 `0.1 mm`
- `socket` 比 `peg` 深 `1 mm`

目的：
- 降低堆疊時因為頂到底而產生縫隙的機率
- 保留非常緊的插接手感

## 立柱與 clip 尺寸

立柱截面：
- `66 x 30 mm`

側邊 cable clip 尺寸：
- Wall thickness：
  - `2.0 mm`
- Arm length：
  - `10.0 mm`
- Inner gap：
  - `5.0 mm`
- Lip inward：
  - `2.0 mm`
- Clip width：
  - `8.0 mm`

## 目前 STL 外尺寸

- `jetson_nano_base.stl`
  - `114 x 136 x 37 mm`
- `mast_segment_80mm.stl`
  - `76 x 30 x 80 mm`
- `camera_head.stl`
  - `76 x 150 x 31 mm`

## camera_head 說明

`camera_head` 用來承接 Logitech C922 的夾具後半段。

目前設計包含：
- 下方 socket 與立柱銜接
- 向前延伸的 boom
- 上方平台承接 C922 夾具
- 平台上的凹槽與 notch 幫助夾具定位
- 側邊 cable clip

## 生成方式

`generate_mounts.py` 目前不是舊版的 voxel `STEP` 做法。

現在採用的是：
- axis-aligned box CSG
- adaptive coordinate grid

也就是：
- 先記錄 add / remove box 操作
- 在輸出 STL 時再依座標邊界解算幾何

所以 README 不再使用舊版 `STEP = 0.1 / 0.5` 的描述。

## 幾何驗證狀態

目前設計已經依照以下組合做過數位裝配驗證：

- `jetson_nano_base`
- `mast_segment_80mm x2`
- `camera_head`

重點結論：
- 幾何上可以堆疊
- Jetson Nano 主程式部署時，這套支架已實際進入使用流程

## 列印建議

建議材料：
- `PLA`
- `PETG`

建議切片設定：
- Layer height：
  - `0.20 mm`
- Walls：
  - `4`
- Top / Bottom layers：
  - `5`
- Infill：
  - `30%`

如果只是先做試裝，也可以先用較低 infill。

## 注意事項

- 這套支架屬於結構件，列印誤差、材料膨脹、`elephant foot` 都會影響插接鬆緊。
- 如果實體列印後仍偏緊，可先微磨 peg。
- `jetson_nano_base` 本身不帶 cable clip，走線主要由 `mast_segment_80mm` 與 `camera_head` 負責。

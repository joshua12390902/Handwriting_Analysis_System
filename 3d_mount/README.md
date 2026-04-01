# Jetson Nano + C922 可調式支架

這個資料夾放的是目前使用中的 3D 列印版本，目標硬體是：

- `Jetson Nano Developer Kit`
- 可堆疊的立柱段
- `Logitech C922 Pro Stream Webcam`

## 目前零件

- `jetson_nano_base.stl`
- `mast_segment_80mm.stl`
- `camera_head.stl`
- `generate_mounts.py`

目前的主組裝流程是：

`jetson_nano_base -> mast_segment_80mm x N -> camera_head`

`mast_base` 已不在主輸出流程中，因為底座現在可以直接接第一段 `mast_segment_80mm`。

## 目前設計重點

- Nano 放置區是完整連續平面：`102 x 82 mm`
- `jetson_nano_base` 本身不帶夾線結構
- 立柱段高度為 `80 mm`
- `peg` / `socket` 主尺寸相同，列印過緊時靠砂紙微修
- 線材固定改成側邊小型 clip，不再用整片盒狀側槽

## 榫接尺寸

- `STEP = 0.1 mm`
- Peg：`48.8 x 19.8 x 16 mm`
- Socket 內尺寸：`49.0 x 20.0 x 17 mm`
- Socket 深度額外 relief：`0.5 mm`
- Socket 入口放寬：`1.0 mm`

主配合目前是 `XY` 零間隙設計。若你的機器列印偏擠，請預期需要輕磨 `peg` 或 `socket`。

## 側邊夾線 Clip

目前的夾線結構是參考一般 FDM hook / snap clip 的做法，改成：

- 側邊貼附的 spine
- 上下兩支 arm
- 外側保留側向壓線入口
- 末端加小 lip 避免線材自己滑出

目前尺寸：

- 壁厚：`2.0 mm`
- Arm 長度：`10.0 mm`
- 內部 gap：`5.0 mm`
- Lip inward：`2.0 mm`
- 沿 Z 的寬度：`8.0 mm`

## 數位裝配檢查

目前有用程式做過數位組裝檢查，至少確認：

- `jetson_nano_base`
- `mast_segment_80mm` x2
- `camera_head`

這組堆疊在幾何上沒有互相穿模。

目前 STL 外尺寸：

- `jetson_nano_base.stl`：`114 x 136 x 37 mm`
- `mast_segment_80mm.stl`：`76 x 30 x 80 mm`
- `camera_head.stl`：`76 x 150 x 30 mm`

注意：

- 這是數位幾何檢查，不是實體列印手感驗證
- 真實列印仍可能因為 `elephant foot`、擠出過量或材料差異而偏緊

## 建議列印順序

先試印：

- `mast_segment_80mm.stl`
- `camera_head.stl` 或只看夾線區局部

確認榫接與夾線手感後，再印：

- `jetson_nano_base.stl`

## 建議切片參數

- 材料：`PLA` 或 `PETG`
- 層高：`0.20 mm`
- 牆數：`4`
- 上下層：`5`
- 填充：`30%`

通常只有 `camera_head.stl` 比較可能需要支撐。

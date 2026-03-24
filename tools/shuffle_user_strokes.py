import pandas as pd

IN_CSV = "user.csv"
OUT_CSV = "user_wrong_order.csv"

df = pd.read_csv(IN_CSV).reset_index(drop=True)

# 把資料切成「段」：每段是 (一段連續的 pen_state=1) + (後面緊跟的一段 pen_state=0)
blocks = []
i = 0
n = len(df)

while i < n:
    # 找下一段 pen_state=1 的開始
    while i < n and int(df.loc[i, "pen_state"]) != 1:
        i += 1
    if i >= n:
        break

    start1 = i
    while i < n and int(df.loc[i, "pen_state"]) == 1:
        i += 1
    end1 = i  # [start1, end1) 是 pen_state=1

    # 把後面的 0 gap 也吃進來（當分隔用）
    start0 = i
    while i < n and int(df.loc[i, "pen_state"]) == 0:
        i += 1
    end0 = i  # [start0, end0) 是 pen_state=0（可能長或短）

    block = df.iloc[start1:end0]  # 包含 1 段 + 0 段
    blocks.append(block)

print("num blocks =", len(blocks))
print("block lengths =", [len(b) for b in blocks])
print("ones per block =", [int((b['pen_state']==1).sum()) for b in blocks])

# 交換第 0、2 筆（大：通常是 3 筆）
if len(blocks) >= 3:
    blocks[0], blocks[2] = blocks[2], blocks[0]

out_df = pd.concat(blocks, ignore_index=True)

# 重新做 timestamp（可選，但建議做，避免時間不單調）
# 這裡用固定間隔 0.03 秒重建
dt = 0.03
out_df["timestamp"] = [round((k+1)*dt, 3) for k in range(len(out_df))]

out_df.to_csv(OUT_CSV, index=False)
print("Saved", OUT_CSV)

#!/usr/bin/env python3
"""
fill_empty_hanzi.py — 從 HanziWriter CDN 補齊 hanzi/ 中的空 JSON 檔案
用法：python tools/fill_empty_hanzi.py
"""
import json
import os
import time
import urllib.request
import urllib.error
from pathlib import Path

HANZI_DIR = Path(__file__).resolve().parent.parent / "hanzi"
CDN_URL = "https://cdn.jsdelivr.net/npm/hanzi-writer-data@latest/{}.json"

def main():
    empty_files = sorted(p for p in HANZI_DIR.glob("*.json") if p.stat().st_size == 0)
    total = len(empty_files)
    print(f"找到 {total} 個空檔案，開始從 HanziWriter CDN 下載...")

    success = 0
    fail = 0
    not_found = 0

    for i, path in enumerate(empty_files, 1):
        char = path.stem
        url = CDN_URL.format(urllib.request.quote(char))
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = resp.read()
                # 驗證是有效 JSON
                json.loads(data)
                path.write_bytes(data)
                success += 1
                if i % 50 == 0 or i == total:
                    print(f"  [{i}/{total}] 已下載 {success} 個，失敗 {fail} 個，CDN無資料 {not_found} 個")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                not_found += 1
            else:
                fail += 1
                print(f"  [{i}/{total}] {char} HTTP {e.code}")
        except Exception as e:
            fail += 1
            print(f"  [{i}/{total}] {char} 錯誤: {e}")

        # 避免被 CDN 限流
        time.sleep(0.05)

    print(f"\n完成！成功: {success}, CDN無資料: {not_found}, 失敗: {fail}")

if __name__ == "__main__":
    main()

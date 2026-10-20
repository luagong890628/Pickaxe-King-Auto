"""把 farm.py 的 log 整理成人看得懂的成效報告。

用法：python report.py [log路徑]
"""
from __future__ import annotations

import glob
import json
import os
import sys
from collections import Counter


def main():
    if len(sys.argv) > 1:
        path = sys.argv[1]
    else:                       # 依修改時間取最新（不能按字母排，farm_night/farm_test 會排錯）
        path = max(glob.glob("captures/farm_*.txt"), key=os.path.getmtime)
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip().startswith("{")]
    if not rows:
        print("沒有資料")
        return
    print(f"== {path} ==")
    print("事件統計:", Counter(r["note"][:16] for r in rows).most_common(12))

    chops = [r for r in rows if "砍到" in r["note"]]
    print(f"\n總砍到：{len(chops)} 次")
    if chops:
        print(f"第一次 {chops[0]['t']}　最後一次 {chops[-1]['t']}")
    # 每小時
    per_hour = Counter(r["t"][:2] for r in chops)
    print("每小時:", dict(sorted(per_hour.items())))
    # 每個地區
    per_area = Counter(r.get("area", "?") for r in chops)
    print("每個地區:", dict(per_area))
    # 換區／休息
    areas = [r for r in rows if "進入地區" in r["note"]]
    rests = [r for r in rows if "休息" in r["note"] or "帳篷" in r["note"]]
    popups = [r for r in rows if "彈窗" in r["note"]]
    print(f"進入地區 {len(areas)} 次、休息相關 {len(rests)} 筆、關彈窗 {len(popups)} 次")
    for r in areas:
        print("  進入:", r.get("area"), r["t"])
    for r in rests[-6:]:
        print("  休息:", r["note"][:40], r["t"])


if __name__ == "__main__":
    main()

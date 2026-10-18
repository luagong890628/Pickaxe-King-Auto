"""記錄使用者手動走的路線（只截圖，不控制手機），存成可以重播的路徑。

輸出：captures/paths/<name>.json = {"start": {...}, "points": [[x, y], ...]}
座標系：以「記錄開始時角色的位置」為原點，單位是畫面像素（右+/下+）。
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import cv2

from pkauto import adb, vision


def shot():
    return vision.normalize_brightness(adb.screencap())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name", help="路徑名稱（例如 start_orchard）")
    ap.add_argument("minutes", type=float, nargs="?", default=5.0)
    ap.add_argument("--interval", type=float, default=0.6, help="取樣間隔秒")
    ap.add_argument("--min-step", type=float, default=25.0, help="累積超過這個距離才記一個點")
    args = ap.parse_args()

    out_dir = Path("captures/paths")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{args.name}.json"

    prev = shot()
    acc = [0.0, 0.0]
    pts = [[0.0, 0.0]]
    moved_total = 0.0
    deadline = time.time() + args.minutes * 60
    n = 0
    print(f"開始記錄 → {out}（{args.minutes} 分鐘，Ctrl-C 可提早結束）")

    while time.time() < deadline:
        time.sleep(args.interval)
        cur = shot()
        dx, dy, resp = vision.scroll(prev, cur)
        if resp > 0.4 and (abs(dx) > 4 or abs(dy) > 4):
            acc[0] += -dx
            acc[1] += -dy
            moved_total += abs(dx) + abs(dy)
            if (abs(acc[0] - pts[-1][0]) + abs(acc[1] - pts[-1][1])) >= args.min_step:
                pts.append([round(acc[0], 1), round(acc[1], 1)])
                print(f"  +點 {pts[-1]}（共 {len(pts)} 個，總位移 {round(moved_total)}px）")
        prev = cur
        n += 1
        if n % 60 == 0:
            print(f"  …持續記錄中（{n} 次取樣，{len(pts)} 個點，總位移 {round(moved_total)}px）")

    json.dump({"name": args.name, "points": pts}, open(out, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"完成：{len(pts)} 個點，總位移 {round(moved_total)}px → {out}")


if __name__ == "__main__":
    main()

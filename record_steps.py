"""錄製使用者的「步伐」（只截圖不碰手機）：把每一小段的移動量記下來，之後照著重播。

為什麼用步伐而不是座標：誤差在重播時不累積是關鍵，而每趟都先用傳送石回固定落點，
所以只要「相對上一刻走多少」準就好——短距離的位移量測是準的。

輸出：captures/steps/<name>.json = [[dx, dy], ...]（dx/dy = 角色在世界上移動的向量）
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
    ap.add_argument("name")
    ap.add_argument("minutes", type=float, nargs="?", default=6.0)
    ap.add_argument("--interval", type=float, default=1.15, help="取樣間隔秒")
    ap.add_argument("--min-step", type=float, default=55.0, help="位移超過這個才記一步")
    args = ap.parse_args()

    out_dir = Path("captures/steps")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{args.name}.json"

    prev = shot()
    steps = []
    total = 0.0
    deadline = time.time() + args.minutes * 60
    n = 0
    print(f"開始錄製步伐 → {out}（{args.minutes} 分鐘；只看畫面不動手機）")

    while time.time() < deadline:
        time.sleep(args.interval)
        cur = shot()
        sh = vision.shift_by_template(prev, cur, threshold=0.62)
        if sh is None:
            s2 = vision.scroll(prev, cur)
            dx, dy, q = s2[0], s2[1], s2[2]
        else:
            dx, dy, q = sh[0], sh[1], sh[2]
        prev = cur
        n += 1
        if q > 0.75 and (abs(dx) > args.min_step * 0.2 or abs(dy) > args.min_step * 0.2):
            mv = (-dx, -dy)                       # 畫面往 (dx,dy) 移 → 角色往反方向走
            steps.append([round(mv[0]), round(mv[1])])
            total += abs(mv[0]) + abs(mv[1])
            print(f"  + 步驟 {len(steps)}: ({round(mv[0])}, {round(mv[1])}) 累計 {round(total)}px")
        if n % 40 == 0:
            print(f"  …{n} 次取樣，{len(steps)} 步，累計 {round(total)}px")

    json.dump({"name": args.name, "steps": steps}, open(out, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"完成：{len(steps)} 步，總位移 {round(total)}px → {out}")


if __name__ == "__main__":
    main()

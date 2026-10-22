"""測「拖曳長度 → 移動速度」：固定按住時間，只改拖曳長度，量實際走了多少 px。

背景（使用者 2026-10-21 說明）：這遊戲**第一次按下的點就是搖桿原點**，往外拉越遠走得越快
（例：拉 50px 速度約 5，拉滿約 10）。所以拖曳長度＝速度旋鈕、按住時間＝時間旋鈕，
距離＝速度 × 時間。

用法
    python test_drag.py                       # 按住 1500ms，拖曳長度 50→400
    python test_drag.py --hold 1200 --lens 80,120,160,200,250
    python test_drag.py --dir N --repeat 2
"""
from __future__ import annotations

import argparse
import time

import cycle_fixed as cf
from pkauto import adb, measure

START = cf.DRAG            # (720, 2600)：使用者確認這裡是空白區，按下去不會開任何東西
SETTLE = 0.85
DIRS = {"N": (0, -1), "S": (0, 1), "L": (-1, 0), "R": (1, 0)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hold", type=int, default=1500, help="每次按住毫秒（固定）")
    ap.add_argument("--lens", default="50,75,100,125,150,200,250,300,400")
    ap.add_argument("--dir", default="N")
    ap.add_argument("--repeat", type=int, default=1)
    args = ap.parse_args()

    focus = adb.current_app()
    if "pickaxeking" not in focus.lower():
        print(f"前景不是遊戲，中止：{focus}")
        return 2

    lens = [int(x) for x in args.lens.split(",") if x.strip()]
    order = [args.dir, "S" if args.dir == "N" else "N"]
    rows, k = [], 0
    for L in lens:
        for _ in range(args.repeat):
            d = order[k % 2]
            k += 1
            vx, vy = DIRS[d]
            a = cf.shot()
            adb.swipe(START[0], START[1],
                      int(START[0] + vx * L), int(START[1] + vy * L), args.hold)
            time.sleep(SETTLE)
            b = cf.shot()
            m = measure.world_shift(a, b)
            if m:
                cx, cy, score, src = m
                dist = (cx ** 2 + cy ** 2) ** 0.5
                rows.append((L, dist, score, src))
                print(f"拖 {L:>3}px 按住 {args.hold}ms {d}：走 {dist:6.1f}px "
                      f"→ {dist / (args.hold / 1000):5.0f}px/秒 分數 {score:.2f} [{src}]", flush=True)
            else:
                rows.append((L, None, None, None))
                print(f"拖 {L:>3}px：量不到位移", flush=True)

    print(f"\n拖曳px  實走px  等效px/秒  相對最大速度")
    base = max((r[1] for r in rows if r[1]), default=0) or 1
    seen = {}
    for L, dist, score, src in rows:
        if dist is None:
            print(f"{L:>6}  {'—':>6}  {'—':>9}  —")
            continue
        n = seen.get(L, 0) + 1
        seen[L] = n
        print(f"{L:>6}  {dist:>6.0f}  {dist / (args.hold / 1000):>9.0f}  {dist / base:>11.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

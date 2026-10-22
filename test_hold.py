"""測「多短的按住會被遊戲算成點擊」：固定起點 (720,2600)、固定拖曳 250px，只改按住毫秒。

做法：一段南一段北交替（淨位移≈0，不會一路走遠），每段前後各一張截圖量世界位移。
位移≈0 ＝ 被當成點擊（角色沒動）；位移 >0 ＝ 有移動。

用法
    python test_hold.py                          # 預設測 11 個毫秒值
    python test_hold.py --holds 500,300,200,150,100,80,60,40 --dir N
    python test_hold.py --repeat 2               # 每段測兩次（看穩定性）
"""
from __future__ import annotations

import argparse
import math
import time

from pkauto import adb, measure, vision
import cycle_fixed as cf

START = cf.DRAG                # (720, 2600)：使用者確認這裡沒有 UI，點到也不會開彈窗
DRAG_LEN = 250
SETTLE = 0.85


def run(holds, first_dir, repeat, cross=False):
    focus = adb.current_app()
    if "pickaxeking" not in focus.lower():
        print(f"前景不是遊戲，中止：{focus}")
        return 2

    rows = []
    dirs = {"N": (0, -1), "S": (0, 1), "L": (-1, 0), "R": (1, 0)}
    order = [first_dir, "S" if first_dir == "N" else "N"]
    k = 0
    for hold in holds:
        for _ in range(repeat):
            d = order[k % 2]
            k += 1
            vx, vy = dirs[d]
            a = cf.shot()
            adb.swipe(START[0], START[1],
                      int(START[0] + vx * DRAG_LEN), int(START[1] + vy * DRAG_LEN), hold)
            time.sleep(SETTLE)
            b = cf.shot()
            m = measure.world_shift(a, b)
            if cross:
                st = vision.shift_by_template(a, b, threshold=0.6)
                sdx, sdy, sresp = vision.scroll(a, b)
                print(f"    [cross] scroll ({-sdx:+.0f},{-sdy:+.0f}) resp {sresp:.2f}"
                      f" ／ template {(-st[0], -st[1]) if st else None}"
                      f" ／ 採用 {m[3] if m else None}", flush=True)
            if m:
                cx, cy, score, src = m
                dist = (cx ** 2 + cy ** 2) ** 0.5
                rows.append({"hold": hold, "dir": d, "px": [round(cx), round(cy)],
                             "dist": round(dist), "score": round(score, 2), "src": src})
                print(f"按住 {hold:>4}ms {d}：角色位移 ({round(cx):+d},{round(cy):+d}) "
                      f"= {dist:6.1f}px 分數 {score:.2f} [{src}]", flush=True)
            else:
                rows.append({"hold": hold, "dir": d, "px": None, "dist": None, "score": None})
                print(f"按住 {hold:>4}ms {d}：量不到位移（可能是點擊、或畫面無靜態區塊）", flush=True)

    print("\n按住ms  實走px  預期px  比率  判定")
    for r in rows:
        if r["dist"] is None:
            print(f"{r['hold']:>6}  {'—':>6}  {'—':>6}   {'—':>4}  量不到")
            continue
        want = r["hold"] / 1000 * 346
        ratio = r["dist"] / want if want else 0
        # 位移 0～2px 落在量測解析度內，才視為「沒動（＝被當成點擊）」
        verdict = "沒動（＝點擊）" if r["dist"] < 3 else "有移動"
        print(f"{r['hold']:>6}  {r['dist']:>6}  {want:>6.0f}  {ratio:>4.2f}  {verdict}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--holds", default="500,400,300,250,200,150,120,100,80,60,40")
    ap.add_argument("--dir", default="N")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--cross", action="store_true", help="同時印相位相關的位移做交叉檢查")
    args = ap.parse_args()
    holds = [int(x) for x in args.holds.split(",") if x.strip()]
    return run(holds, args.dir, args.repeat, args.cross)


if __name__ == "__main__":
    raise SystemExit(main())

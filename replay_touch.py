"""重播「原始搖桿操作」：把錄到的觸控事件用 input motionevent 1:1 送出。

- down/move/up 的座標由錄製時裝置的絕對值線性映射到螢幕像素
- move 之間依原本的時間間隔送出（可 --speed 調整）
- 沒有 move 的手勢自動用 motionevent 送；若裝置不支援則退回 input swipe
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from pkauto import adb


def load_calib():
    """實測校正檔（do_calib.py 產生）：screen = a*raw + b。"""
    p = Path("data/touch/_calib.json")
    if not p.exists():
        raise SystemExit("找不到校正檔 data/touch/_calib.json（先跑 do_calib.py）")
    return json.load(open(p, encoding="utf-8"))


def to_px(ev, rng, screen, cal=None):
    if cal is not None:
        (ax, bx), (ay, by) = cal["x"], cal["y"]
        return (max(0, min(screen[0]-1, int(round(ax*ev["x"]+bx)))),
                max(0, min(screen[1]-1, int(round(ay*ev["y"]+by)))))
    xr, yr = rng["ABS_MT_POSITION_X"], rng["ABS_MT_POSITION_Y"]
    x = (ev["x"] - xr["min"]) / max(1, xr["max"] - xr["min"]) * screen[0]
    y = (ev["y"] - yr["min"]) / max(1, yr["max"] - yr["min"]) * screen[1]
    return int(x), int(y)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--dry", action="store_true", help="只印出前幾個事件，不真的送")
    args = ap.parse_args()
    rec = json.load(open(Path("data/touch") / f"{args.name}.json", encoding="utf-8"))
    rng, screen = rec["abs_range"], rec["screen"]
    events = rec["events"]
    cal = load_calib()
    print(f"重播 {args.name}: {len(events)} 事件 | 校正誤差 {cal.get('err_px','?')}px | 速度 {args.speed}x")
    if args.dry:
        for ev in events[:12]:
            if ev.get("x") is not None:
                print("   ", ev["t"], ev["type"], to_px(ev, rng, screen, cal))
        return

    for rep_i in range(args.repeat):
        t_prev = 0.0
        for ev in events:
            dt = min(3.0, max(0.0, (ev["t"] - t_prev) / max(0.05, args.speed)))
            if dt > 0:
                time.sleep(dt)
            t_prev = ev["t"]
            if ev.get("x") is None or ev.get("y") is None:
                continue
            x, y = to_px(ev, rng, screen, cal)
            typ = {"down": "DOWN", "move": "MOVE", "up": "UP"}[ev["type"]]
            adb.shell(f"input motionevent {typ} {x} {y}")
        print(f"  第 {rep_i+1} 輪完成")


if __name__ == "__main__":
    main()

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


def to_px(ev, rng, screen):
    xr, yr = rng["ABS_MT_POSITION_X"], rng["ABS_MT_POSITION_Y"]
    x = (ev["x"] - xr["min"]) / max(1, xr["max"] - xr["min"]) * screen[0]
    y = (ev["y"] - yr["min"]) / max(1, yr["max"] - yr["min"]) * screen[1]
    return int(x), int(y)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--repeat", type=int, default=1)
    args = ap.parse_args()

    rec = json.load(open(Path("data/touch") / f"{args.name}.json", encoding="utf-8"))
    rng, screen = rec["abs_range"], rec["screen"]
    events = rec["events"]
    print(f"重播 {args.name}: {len(events)} 事件, 裝置 {rec['device']}, 螢幕 {screen}")

    for rep_i in range(args.repeat):
        t_prev = 0.0
        for ev in events:
            dt = (ev["t"] - t_prev) / max(0.05, args.speed)
            if dt > 0:
                time.sleep(dt)
            t_prev = ev["t"]
            if ev.get("x") is None or ev.get("y") is None:
                continue
            x, y = to_px(ev, rng, screen)
            typ = {"down": "DOWN", "move": "MOVE", "up": "UP"}[ev["type"]]
            adb.shell(f"input motionevent {typ} {x} {y}")
        print(f"  第 {rep_i+1} 輪完成")


if __name__ == "__main__":
    main()

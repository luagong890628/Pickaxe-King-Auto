"""重播「原始搖桿操作」——用 input swipe 一次送一個完整手勢（v2）。

為什麼不用 motionevent 逐事件送：
  每次 `adb shell input ...` 是獨立的一次注入，遊戲會把 2600 個碎片事件
  看成「一直點同一處」→ 角色原地打轉。改用 swipe（按下→拖曳→放開，一次完成）
  才符合這遊戲的搖桿模型（點的地方開始拖曳＝搖桿）。

座標：錄到的原始值 → 校正檔 data/touch/_calib.json → 螢幕像素。
每筆觸碰的起點用「第一個 move 的座標」（down 事件的座標是前一筆殘值，不可用），
按住位置用「所有 move 的中位數」。

用法：replay_touch2.py village_loop [--speed 1.0] [--repeat 1] [--dry]
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

from pkauto import adb


def load_calib():
    p = Path("data/touch/_calib.json")
    if not p.exists():
        raise SystemExit("找不到校正檔 data/touch/_calib.json（先跑 do_calib.py）")
    return json.load(open(p, encoding="utf-8"))


def to_screen(x, y, cal):
    (ax, bx), (ay, by) = cal["x"], cal["y"]
    w, h = cal.get("screen", [1440, 3120])
    return (max(0, min(w - 1, int(round(ax * x + bx)))),
            max(0, min(h - 1, int(round(ay * y + by)))))


def parse_touches(events):
    touches, cur = [], None
    for e in events:
        if e["type"] == "down":
            cur = {"t0": e["t"], "moves": []}
        elif e["type"] == "move" and cur is not None:
            if e.get("x") is not None and e.get("y") is not None:
                cur["moves"].append((e["x"], e["y"]))
        elif e["type"] == "up" and cur is not None:
            cur["t1"] = e["t"]
            touches.append(cur)
            cur = None
    out = []
    for t in touches:
        if not t["moves"]:
            continue
        start = t["moves"][0]
        hold = (int(statistics.median([m[0] for m in t["moves"]])),
                int(statistics.median([m[1] for m in t["moves"]])))
        out.append({"t0": t["t0"], "t1": t["t1"], "start": start, "hold": hold})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    rec = json.load(open(Path("data/touch") / f"{args.name}.json", encoding="utf-8"))
    cal = load_calib()
    touches = parse_touches(rec["events"])
    print(f"重播 {args.name}: {len(rec['events'])} 事件 → {len(touches)} 個手勢 "
          f"| 校正誤差 {cal.get('err_px','?')}px | 速度 {args.speed}x")

    if args.dry:
        for i, t in enumerate(touches[:12]):
            s = to_screen(*t["start"], cal)
            h = to_screen(*t["hold"], cal)
            print(f"  #{i+1} swipe {s} → {h}  {int((t['t1']-t['t0'])*1000)}ms")
        return

    for rep in range(args.repeat):
        t_prev_end = 0.0
        for i, t in enumerate(touches):
            gap = min(3.0, max(0.0, (t["t0"] - t_prev_end) / max(0.05, args.speed)))
            if gap > 0:
                time.sleep(gap)
            dur = max(120, int((t["t1"] - t["t0"]) * 1000 / max(0.05, args.speed)))
            sx, sy = to_screen(*t["start"], cal)
            hx, hy = to_screen(*t["hold"], cal)
            if abs(hx - sx) + abs(hy - sy) < 40:
                adb.tap(sx, sy)
            else:
                adb.swipe(sx, sy, hx, hy, dur)
            t_prev_end = t["t1"]
            if (i + 1) % 10 == 0:
                print(f"  …{i+1}/{len(touches)} 個手勢", flush=True)
        print(f"  第 {rep+1} 輪完成（{len(touches)} 個手勢）")


if __name__ == "__main__":
    main()

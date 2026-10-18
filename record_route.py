"""錄製路線（關鍵幀版）：使用者走，我每隔一小段距離存一張畫面當「路標」。

之後重播時不是靠座標硬走，而是「走到某一張畫面的樣子」——每次都用畫面比對修正方向，
所以誤差不會累積（實測走出去 107px、走回來誤差只剩 32px）。

輸出：captures/routes/<name>/frame_000.png, ... + meta.json（含每張的相對位移估計）
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import cv2

from pkauto import adb, vision

SCALE = 0.5          # 存檔用縮圖比例（比對用）


def shot():
    img = vision.normalize_brightness(adb.screencap())
    return cv2.resize(img, None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_AREA)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("minutes", type=float, nargs="?", default=6.0)
    ap.add_argument("--interval", type=float, default=1.1)
    ap.add_argument("--min-move", type=float, default=90.0, help="畫面位移超過這個距離才存新關鍵幀")
    args = ap.parse_args()

    out = Path(f"captures/routes/{args.name}")
    out.mkdir(parents=True, exist_ok=True)
    for f in out.glob("frame_*.png"):
        f.unlink()

    prev = shot()
    cv2.imwrite(str(out / "frame_000.png"), prev)
    frames = [{"file": "frame_000.png", "move_from_prev": [0, 0]}]
    deadline = time.time() + args.minutes * 60
    print(f"開始錄製關鍵幀 → {out}（{args.minutes} 分鐘）")

    while time.time() < deadline:
        time.sleep(args.interval)
        cur = shot()
        sh = vision.shift_by_template(cv2.resize(prev, None, fx=2, fy=2), cv2.resize(cur, None, fx=2, fy=2))
        if sh is None:
            dx, dy, resp = vision.scroll(prev, cur)
            sh = (dx, dy, resp, 0)
        dx, dy, q, n = sh
        if q > 0.7 and (abs(dx) > args.min_move or abs(dy) > args.min_move):
            name = f"frame_{len(frames):03d}.png"
            cv2.imwrite(str(out / name), cur)
            frames.append({"file": name, "move_from_prev": [round(-dx), round(-dy)]})
            print(f"  + {name}（自上一幀移動 {-dx:.0f},{-dy:.0f}px，共 {len(frames)} 幀）")
        prev = cur

    json.dump({"name": args.name, "scale": SCALE, "frames": frames},
              open(out / "meta.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"完成：{len(frames)} 個關鍵幀 → {out}")


if __name__ == "__main__":
    main()

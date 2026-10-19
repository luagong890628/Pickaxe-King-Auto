"""被動錄製：只截圖、完全不操作手機。

用途：錄下「你砍樹/石頭」的畫面，之後用來學習「哪些東西是要砍的」。

每 0.8 秒存一張（半解析度 JPEG）+ 一行 metadata（生命值、偵測到的目標），
存到 data/chop_rec/（git 有追蹤，不會像 captures/ 那樣被清掉）。
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np

from pkauto import adb, vision, hp

ANCHOR = (720, 1400)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("minutes", type=float, nargs="?", default=10.0)
    ap.add_argument("--fps", type=float, default=1.25, help="每秒存幾張")
    args = ap.parse_args()

    run = Path("data/chop_rec") / time.strftime("%Y%m%d_%H%M%S")
    run.mkdir(parents=True, exist_ok=True)
    meta = (run / "meta.jsonl").open("w", encoding="utf-8")
    n = 0
    t0 = time.time()
    deadline = t0 + args.minutes * 60
    print(f"被動錄製開始（不操作手機）→ {run}；每 {1/args.fps:.2f} 秒一張，{args.minutes} 分鐘")

    while time.time() < deadline:
        tick = time.time()
        img = vision.normalize_brightness(adb.screencap())
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        h, s, v = cv2.split(hsv)
        green = ((h > 45) & (h < 95) & (s > 150) & (v > 80)).mean()
        gray = ((s < 42) & (v > 115) & (v < 225)).mean()
        text, _ = hp.read(img)
        small = cv2.resize(img, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
        name = f"f{n:05d}.jpg"
        cv2.imwrite(str(run / name), small, [cv2.IMWRITE_JPEG_QUALITY, 82])
        meta.write(json.dumps({
            "f": name, "t": round(time.time() - t0, 2), "hp": text,
            "green": round(float(green), 4), "gray": round(float(gray), 4),
        }, ensure_ascii=False) + "\n")
        meta.flush()
        n += 1
        if n % 25 == 0:
            print(f"  {n} 張，{time.time()-t0:.0f}s，hp={text}")
        dt = 1.0 / args.fps - (time.time() - tick)
        if dt > 0:
            time.sleep(dt)

    meta.close()
    print(f"done: {n} 張 → {run}")


if __name__ == "__main__":
    main()

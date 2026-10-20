"""連續快拍：抓傷害數字範本用。

用法：burst_shot.py [秒數] [每秒幾張]
輸出：captures/burst/b_000.jpg ... + 之後用 diff 找「短暫出現又消失的數字」。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, ".")
from pkauto import adb, vision


def main():
    sec = float(sys.argv[1]) if len(sys.argv) > 1 else 20.0
    fps = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0
    out = Path("captures/burst")
    out.mkdir(parents=True, exist_ok=True)
    for p in out.glob("*.jpg"):
        p.unlink()
    n = 0
    t0 = time.time()
    while time.time() - t0 < sec:
        tick = time.time()
        s = vision.normalize_brightness(adb.screencap())
        cv2.imwrite(str(out / f"b_{n:03d}.jpg"), s, [cv2.IMWRITE_JPEG_QUALITY, 92])
        n += 1
        dt = 1.0 / fps - (time.time() - tick)
        if dt > 0:
            time.sleep(dt)
    print(f"拍了 {n} 張 → {out}（{sec}s @ {fps}fps）")


if __name__ == "__main__":
    main()

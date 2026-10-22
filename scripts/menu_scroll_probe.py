"""選單到底有沒有在捲？錄 3 秒螢幕、期間做慢滑＋快 flick，再逐格相位相關判定。

為什麼不能用兩張截圖：捲了又彈回（rubber-band）在「滑完後 1 秒」的兩張圖看起來一模一樣，
只有逐格分析影片才分得出來。2026-10-23 實測結論是「完全不會捲動」，滑動只是保險。

用法
    python scripts/menu_scroll_probe.py            # 開選單 → 錄影 → 分析
    python scripts/menu_scroll_probe.py --keep     # 保留 captures/menu_scroll.mp4
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # 讓 scripts/ 底下也 import 得到專案模組
import cycle_fixed as cf
from pkauto import adb

MENU_OUT = (720, 3050)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=3)
    ap.add_argument("--keep", action="store_true", help="保留錄影檔")
    args = ap.parse_args()

    out = Path("captures/menu_scroll.mp4")
    dev = "/sdcard/menu_scroll.mp4"

    cf.adb.tap(*MENU_OUT)          # 先確保選單關著
    time.sleep(0.8)
    cf.adb.tap(*cf.HEART)
    time.sleep(2.0)                # 選單開好再動（1 秒內滑動會被吃掉）

    rec = subprocess.Popen([adb.adb_path(), "shell", "screenrecord", "--time-limit", str(args.seconds), dev])
    time.sleep(0.6)
    cf.adb.swipe(719, 2400, 719, 1100, 300)     # 慢滑
    time.sleep(0.4)
    cf.adb.swipe(719, 2400, 719, 1100, 120)     # 快 flick
    rec.wait(timeout=args.seconds + 15)
    subprocess.run([adb.adb_path(), "pull", dev, str(out)], capture_output=True)

    cap = cv2.VideoCapture(str(out))
    print(f"影格數 {int(cap.get(cv2.CAP_PROP_FRAME_COUNT))}　fps {cap.get(cv2.CAP_PROP_FPS):.1f}")
    prev = None
    i = 0
    moved = []
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        i += 1
        g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY).astype(np.float32)
        g = cv2.resize(g, (g.shape[1] // 2, g.shape[0] // 2))
        if prev is not None:
            (dx, dy), resp = cv2.phaseCorrelate(prev, g)
            if resp > 0.15 and abs(dy) > 1.0:
                moved.append((i, round(dy * 2, 1), round(resp, 2)))
        prev = g
    cap.release()

    print(f"偵測到垂直位移的影格：{len(moved)}（0 ＝ 選單沒有捲動）")
    for row in moved[:40]:
        print("  frame", row)
    cf.adb.tap(*MENU_OUT)
    time.sleep(0.8)
    if not args.keep:
        out.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

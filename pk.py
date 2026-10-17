"""Pickaxe King 自動化工具（CLI）。

常用：
  python pk.py shot [name]              # 截圖 → captures/
  python pk.py tap X Y                  # 點擊
  python pk.py swipe X1 Y1 X2 Y2 [ms]   # 滑動（預設 300ms）
  python pk.py app                      # 目前前景 App
  python pk.py scroll A B               # 兩張截圖之間的世界位移
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2

from pkauto import adb, vision

CAP = Path(__file__).resolve().parent / "captures"


def _load(name: str):
    path = Path(name)
    if not path.exists():
        path = CAP / name
    img = cv2.imread(str(path))
    if img is None:
        raise SystemExit(f"讀不到圖：{path}")
    return img


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__)
        return 1
    cmd, rest = argv[0], argv[1:]

    if cmd == "shot":
        name = rest[0] if rest else time.strftime("shot_%Y%m%d_%H%M%S.png")
        if not name.endswith(".png"):
            name += ".png"
        print(adb.screencap_to(CAP / name))
    elif cmd == "tap":
        adb.tap(int(rest[0]), int(rest[1]))
        print(f"tapped {rest[0]} {rest[1]}")
    elif cmd == "swipe":
        ms = int(rest[4]) if len(rest) > 4 else 300
        adb.swipe(int(rest[0]), int(rest[1]), int(rest[2]), int(rest[3]), ms)
        print(f"swiped {rest[0]} {rest[1]} -> {rest[2]} {rest[3]} ({ms}ms)")
    elif cmd == "app":
        print(adb.current_app())
    elif cmd == "scroll":
        dx, dy, r = vision.scroll(_load(rest[0]), _load(rest[1]))
        print(f"dx={dx:+.1f} dy={dy:+.1f} response={r:.3f}")
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

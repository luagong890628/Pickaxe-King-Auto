"""在起始之地系統性搜尋帳篷（休息對話框），找到就記錄位置並休息。

只會在 rest.find_rest_dialog 命中時才點擊（該判定已收緊到 1004x220、中心 y≈1839），
不會亂點白色大面板。

用法：python find_tent.py
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, ".")
import cv2

from pkauto import adb, popup, rest, teleport, vision


def shot():
    return vision.normalize_brightness(adb.screencap())


def step(dx, dy, dist=200):
    a = math.atan2(dy, dx)
    hold = int(min(1000, max(250, dist / 315.0 * 1000)))
    adb.swipe(720, 2600, int(720 + math.cos(a) * 250), int(2600 + math.sin(a) * 250), hold)
    time.sleep(hold / 1000.0 + 0.45)


def check(tag):
    img = shot()
    if popup.close_popup(img):
        print(f"  [{tag}] 關掉彈窗")
        img = shot()
    box = rest.find_rest_dialog(img)
    return box, img


def main():
    print("傳送到起始之地…")
    if not teleport.go("start"):
        print("傳送失敗")
        return
    time.sleep(2.5)

    trail = []
    plan = []
    for i in range(8):
        plan.append(("北", 0, -1))
    for i in range(10):
        plan.append(("西", -1, 0))
    for i in range(20):
        plan.append(("東", 1, 0))
    for i in range(8):
        plan.append(("北", 0, -1))

    for idx, (name, dx, dy) in enumerate(plan):
        step(dx, dy, 200)
        box, img = check(name)
        trail.append({"i": idx, "dir": name, "box": box})
        print(f"  #{idx+1} 往{name} → 對話框: {box}")
        if box:
            print("找到帳篷！點擊休息")
            adb.tap(box[0], box[1])
            time.sleep(5.0)
            after, _ = check("after")
            print("休息後對話框:", after)
            Path("data/tent_path.json").write_text(
                json.dumps({"trail": trail, "found_index": idx, "dir": name}, ensure_ascii=False, indent=1),
                encoding="utf-8")
            return
    Path("data/tent_path.json").write_text(
        json.dumps({"trail": trail, "found_index": None}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("這輪沒找到帳篷（路徑已存 data/tent_path.json）")


if __name__ == "__main__":
    main()

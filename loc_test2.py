"""定位驗證：同時量「畫面位移累積（里程計）」與「地標實際位移」，比較兩者一致不一致。

重點驗證：
1. 拖曳後等動畫結束（1.5s）才取樣 → 位移量測準不準。
2. 地標（帳篷/SHOP）只在「預測位置附近」小範圍搜尋 → 穩不穩（全畫面搜尋會認錯建築）。
"""
from __future__ import annotations

import math
import time

import cv2

from pkauto import adb, vision

ANCHOR = (720, 1400)
DRAG = (600, 1650)
TENT = cv2.imread("captures/tpl_tent.png")
SHOP = cv2.imread("captures/tpl_shop.png")


def shot():
    return vision.normalize_brightness(adb.screencap())


def find_local(img, tpl, prev, radius=200, threshold=0.72):
    h, w = img.shape[:2]
    x1, y1 = max(0, int(prev[0] - radius)), max(0, int(prev[1] - radius))
    x2, y2 = min(w, int(prev[0] + radius)), min(h, int(prev[1] + radius))
    if x2 - x1 < 80 or y2 - y1 < 80:
        return None
    r = vision.find(img[y1:y2, x1:x2], tpl, threshold=threshold)
    return None if not r else (r[0] + x1, r[1] + y1, r[2])


def main():
    img = shot()
    tent = vision.find(img, TENT, 0.85)
    shop = vision.find(img, SHOP, 0.85)
    print("起始畫面地標：帳篷", tent, "| SHOP", shop)

    acc = [0.0, 0.0]                       # 角色世界位移累積（px，右+/下+）
    moves = [(0, -300), (0, -300), (300, 0), (300, 0), (0, 300), (0, 300), (-300, 0), (0, -300)]
    prev_frame = img
    lm_kind = "tent" if tent else ("shop" if shop else None)
    lm_pos = (tent[0], tent[1]) if tent else ((shop[0], shop[1]) if shop else None)

    print(f"{'#':>3} {'拖曳':>12} {'里程計位移':>14} {'地標預測':>16} {'地標實測':>16} {'誤差px':>8} resp")
    for i, (dx, dy) in enumerate(moves):
        adb.swipe(*DRAG, DRAG[0] + dx, DRAG[1] + dy, int(min(800, max(300, math.hypot(dx, dy) * 2.0))))
        time.sleep(1.5)                     # 等角色走完、動畫結束才取樣
        cur = shot()
        mx, my, resp = vision.scroll(prev_frame, cur)
        step = (-mx, -my) if resp > 0.4 else (0.0, 0.0)
        acc[0] += step[0]
        acc[1] += step[1]

        pred = None
        got = None
        if lm_pos:
            # 世界往 +step 移動 → 地標在畫面上往 -step 移動
            pred = (lm_pos[0] - step[0], lm_pos[1] - step[1])
            f = find_local(cur, TENT if lm_kind == "tent" else SHOP, pred)
            if f:
                got = (f[0], f[1])
                lm_pos = got
        err = "" if not (pred and got) else f"{math.hypot(got[0]-pred[0], got[1]-pred[1]):6.0f}"
        print(f"{i:>3} {str((dx,dy)):>12} {str([round(v) for v in step]):>14} "
              f"{str(None if not pred else [round(v) for v in pred]):>16} "
              f"{str(None if not got else [round(v) for v in got]):>16} {err:>8} {resp:.2f}")
        prev_frame = cur
    print("完成")


if __name__ == "__main__":
    main()

"""定位驗證：比較「畫面位移累積(里程計)」與「地標實際位移」，找出可信的量測方式。

要驗證的兩件事：
1. 拖曳後「等動畫結束」再取樣，位移量測是否準確（之前可能在角色還在走時取樣 → 誤差大）。
2. 地標（帳篷/SHOP）用「在預測位置附近小範圍搜尋」是否穩定（之前全畫面搜尋會認錯建築）。
"""
from __future__ import annotations

import math
import time

import cv2
import numpy as np

from pkauto import adb, vision

ANCHOR = (720, 1400)
DRAG = (600, 1650)
TENT = cv2.imread("captures/tpl_tent.png")
SHOP = cv2.imread("captures/tpl_shop.png")


def shot():
    return vision.normalize_brightness(adb.screencap())


def find_local(img, tpl, prev, radius=240, threshold=0.72):
    """只在 prev 附近搜尋模板，避免全畫面誤判。"""
    h, w = img.shape[:2]
    x1, y1 = max(0, int(prev[0] - radius)), max(0, int(prev[1] - radius))
    x2, y2 = min(w, int(prev[0] + radius)), min(h, int(prev[1] + radius))
    if x2 - x1 < 60 or y2 - y1 < 60:
        return None
    sub = img[y1:y2, x1:x2]
    r = vision.find(sub, tpl, threshold=threshold)
    if not r:
        return None
    return (r[0] + x1, r[1] + y1, r[2])


def main():
    print("初始畫面…")
    img = shot()
    cv2.imwrite("captures/loc_t0.png", img)
    tent = vision.find(img, TENT, 0.85)
    shop = vision.find(img, SHOP, 0.85)
    print("帳篷:", tent, "| SHOP:", shop)
    if not tent and not shop:
        print("!! 畫面裡沒有地標，先隨便走幾步找地標")
        for _ in range(4):
            adb.swipe(*DRAG, DRAG[0], DRAG[1] - 300, 600)
            time.sleep(1.3)
            img = shot()
            tent = vision.find(img, TENT, 0.85)
            shop = vision.find(img, SHOP, 0.85)
            if tent or shop:
                print("找到：帳篷", tent, "SHOP", shop)
                break

    acc = [0.0, 0.0]
    moves = [(0, -300), (0, -300), (300, 0), (300, 0), (0, 300), (0, 300), (-300, 0), (0, -300)]
    prev_settled = img
    prev_tent = (tent[0], tent[1]) if tent else None
    prev_shop = (shop[0], shop[1]) if shop else None
    print(f"{'步驟':>4} {'拖曳':>12} {'里程計累積':>16} {'地標推算位移':>16} {'誤差':>8}")
    for i, (dx, dy) in enumerate(moves):
        adb.swipe(*DRAG, DRAG[0] + dx, DRAG[1] + dy, int(min(800, max(300, math.hypot(dx, dy) * 2.0))))
        time.sleep(1.5)                      # 等角色走完、動畫結束
        cur = shot()
        cv2.imwrite(f"captures/loc_t{i+1}.png", cur)
        mx, my, resp = vision.scroll(prev_settled, cur)
        if resp > 0.4:
            acc[0] += -mx
            acc[1] += -my
        # 地標：在預測位置（上一個位置 + 累積位移的相反）附近搜尋
        lm = None
        if prev_tent:
            px = prev_tent[0] - acc[0] + (acc[0])      # 預測＝上一個位置 + 世界位移；世界位移≈acc
            p = find_local(cur, TENT, (prev_tent[0] - acc[0] + acc[0] * 0, prev_tent[1]))
            p = find_local(cur, TENT, (prev_tent[0] - (acc[0] - 0), prev_tent[1] - (acc[1] - 0)))
            if p:
                lm = ("tent", p, p[0] - prev_tent[0], p[1] - prev_tent[1])
                prev_tent = (p[0], p[1])
        if lm is None and prev_shop:
            p = find_local(cur, SHOP, (prev_shop[0] - acc[0], prev_shop[1] - acc[1]))
            if p:
                lm = ("shop", p, p[0] - prev_shop[0], p[1] - prev_shop[1])
                prev_shop = (p[0], p[1])
        err = ""
        if lm:
            ldx, ldy = lm[2], lm[3]
            err = f"{math.hypot(ldx + (acc[0]), ldy + (acc[1])):7.0f}" if False else f"{math.hypot(ldx - (-mx if resp>0.4 else 0), ldy - (-my if resp>0.4 else 0)):7.0f}"
        print(f"{i:>4} {str((dx,dy)):>12} {str([round(v) for v in acc]):>16} "
              f"{str(None if not lm else (lm[0], round(lm[2]), round(lm[3]))):>16} {err:>8} resp={resp:.2f}")
        prev_settled = cur
    print("完成；截圖存 captures/loc_t*.png")


if __name__ == "__main__":
    main()

"""彈窗處理：偵測畫面上的大白框，並點粉紅 X 關閉。

使用者 2026-10-20 指示：
- **不要點畫面上一大塊白色的東西**（通常是彈窗/黑市交易），點了會開新視窗。
- 如果已經彈窗 → 在畫面上找叉叉（粉紅方塊 X，實測位置約 (719,2920)）點掉。
"""
from __future__ import annotations

import time

import cv2
import numpy as np

from . import adb, vision

# 粉紅 X 可能出現的範圍（畫面下方中央）
X_Y0, X_Y1 = 2350, 3120
X_X0, X_X1 = 500, 950


def find_close_button(img):
    """找粉紅/洋紅的關閉鈕，回傳 (x, y)；找不到回傳 None。"""
    b, g, r = cv2.split(img.astype(np.int16))
    pink = ((r > 165) & (b > 130) & (g < 135)).astype(np.uint8) * 255
    roi = np.zeros_like(pink)
    roi[X_Y0:X_Y1, X_X0:X_X1] = pink[X_Y0:X_Y1, X_X0:X_X1]
    roi = cv2.morphologyEx(roi, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8), 2)
    n, _l, st, ce = cv2.connectedComponentsWithStats(roi, 8)
    best = None
    for i in range(1, n):
        if st[i][4] < 700:
            continue
        if best is None or st[i][4] > st[best][4]:
            best = i
    if best is None:
        return None
    return int(ce[best][0]), int(ce[best][1])


def has_popup(img) -> bool:
    """畫面中央是否有大面積白色面板（彈窗特徵）。"""
    b, g, r = cv2.split(img.astype(np.int16))
    white = ((b > 205) & (g > 205) & (r > 205)).astype(np.uint8)
    mid = white[900:2200, 200:1240]
    return float(mid.mean()) > 0.35


def close_popup(img=None, tries=3) -> bool:
    """有關閉鈕就點掉；回傳是否處理過。"""
    for _ in range(tries):
        if img is None:
            img = vision.normalize_brightness(adb.screencap())
        btn = find_close_button(img)
        if btn is None:
            return False
        adb.tap(btn[0], btn[1])
        time.sleep(1.5)
        img = vision.normalize_brightness(adb.screencap())
        if find_close_button(img) is None:
            return True
    return False

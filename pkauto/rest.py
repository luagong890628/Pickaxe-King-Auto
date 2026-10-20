"""偵測「在小屋裡休息！」對話框（大白框），用於生命值歸零後自動休息。

實測：白框約 1004x220、中心 ≈ (720,1839)，出現在角色站到帳篷旁時。
"""
from __future__ import annotations

import cv2
import numpy as np


def find_rest_dialog(img, debug_path=None):
    """回傳對話框中心 (x, y)；沒有回傳 None。"""
    b, g, r = cv2.split(img.astype(np.int16))
    white = ((b > 210) & (g > 210) & (r > 210)).astype(np.uint8) * 255
    roi = white[1100:2600, 120:1320]
    roi = cv2.morphologyEx(roi, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8), 3)
    n, _l, st, ce = cv2.connectedComponentsWithStats(roi, 8)
    best = None
    for i in range(1, n):
        x, y, w, h, a = st[i]
        # 收緊：休息框實測 1004x220，中心 y≈1839 → 避免誤點其他白色面板
        if w < 880 or w > 1150:
            continue
        if h < 170 or h > 270:
            continue
        cy = ce[i][1] + 1100
        if not (1700 < cy < 1980):
            continue
        fill = a / float(w * h)
        if fill < 0.55:          # 對話框是實心白框
            continue
        if best is None or a > st[best][4]:
            best = i
    if best is None:
        return None
    return int(ce[best][0]) + 120, int(ce[best][1]) + 1100


def has_rest_dialog(img) -> bool:
    return find_rest_dialog(img) is not None

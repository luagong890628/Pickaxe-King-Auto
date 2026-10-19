"""偵測「白色四角框」＝角色靠近可互動目標（樹、石頭、帳篷）時遊戲畫的瞄準框。

外觀（實際量測）：純白、1~2px 細線、由四個角落的 L 型線段組成（不是完整矩形）。
用途：程式不需要知道樹在哪——白框出現＝旁邊有東西，停下來讓它砍即可。
"""
from __future__ import annotations

import cv2
import numpy as np

# 遊戲世界區域（避開左右 UI 欄與上下列）
X0, X1 = 240, 1240
Y0, Y1 = 560, 2900


def _white_mask(img, v=205):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    m = (gray > v).astype(np.uint8) * 255
    m[:, :X0] = 0
    m[:, X1:] = 0
    m[:Y0, :] = 0
    m[Y1:, :] = 0
    return m


def find_white_box(img, min_side=120, max_side=620, v=205, near=None, near_r=900):
    """回傳 (x, y, w, h) 或 None。near=(cx,cy) 時只找該點附近的框。"""
    m = _white_mask(img, v)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), 1)
    n, lab, st, ce = cv2.connectedComponentsWithStats(m, 8)
    blobs = []
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if a < 25 or a > 4000:
            continue
        if w > 90 or h > 90:
            continue                       # 角落小段，不會太大
        blobs.append((float(ce[i][0]), float(ce[i][1]), int(a)))
    if len(blobs) < 4:
        return None
    best = None
    pts = blobs
    for i in range(len(pts)):
        for j in range(len(pts)):
            if i == j:
                continue
            x1, y1 = pts[i][0], pts[i][1]
            x2, y2 = pts[j][0], pts[j][1]
            if x2 - x1 < min_side or y2 - y1 < min_side:
                continue
            if x2 - x1 > max_side or y2 - y1 > max_side:
                continue
            w, h = x2 - x1, y2 - y1
            if not (0.55 < w / h < 1.8):
                continue
            # 檢查另外兩角（允許 ±45px 誤差）
            def has(cx, cy, skip):
                for k, (px, py, _a) in enumerate(pts):
                    if k in skip:
                        continue
                    if abs(px - cx) < 45 and abs(py - cy) < 45:
                        return True
                return False
            if has(x1, y2, (i, j)) and has(x2, y1, (i, j)):
                area = w * h
                cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
                score = area
                if near is not None:
                    d = float(np.hypot(cx - near[0], cy - near[1]))
                    if d > near_r:
                        continue
                    score = -d                  # 離角色越近越優先
                if best is None or score > best[0]:
                    best = (score, int(x1), int(y1), int(w), int(h))
    if best is None:
        return None
    return best[1], best[2], best[3], best[4]


def draw(img, box):
    if box is None:
        return img
    x, y, w, h = box
    cv2.rectangle(img, (x, y), (x + w, y + h), (0, 0, 255), 4)
    return img

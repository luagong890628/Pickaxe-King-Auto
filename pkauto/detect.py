"""畫面物件偵測：針葉樹、灰色石頭（依這個遊戲的實際調色盤）。

調色盤依據（擷取自實機畫面）：
- 針葉樹冠：飽和黃綠，BGR≈(115,188,30)，H≈76, S≈214, V≈188
- 草地：BGR≈(105,219,145)，H≈49, S≈133 → 用 S>150 可與樹分開
- 灰色石頭：低飽和（S<40）、中高亮度（V 140-235，避開純白 255）
"""
from __future__ import annotations

import cv2
import numpy as np

TREE_HSV_LO = (60, 150, 60)
TREE_HSV_HI = (100, 255, 235)
STONE_MAX_SAT = 40
STONE_V_LO, STONE_V_HI = 140, 235


def _blobs(mask: np.ndarray, min_area=250, max_area=60000, max_wh=460):
    k = np.ones((3, 3), np.uint8)
    m = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k, iterations=2)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k, iterations=3)
    n, _labels, stats, _cent = cv2.connectedComponentsWithStats(m, 8)
    out = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if min_area <= area <= max_area and w <= max_wh and h <= max_wh:
            out.append((int(x + w // 2), int(y + h // 2), int(w), int(h), int(area)))
    return out


BOX = (600, 3000, 250, 1190)  # 遊戲可視區（y1, y2, x1, x2）：排除頂部資源列與左右 UI 欄


def _limit(mask: np.ndarray, box) -> np.ndarray:
    m = np.zeros_like(mask)
    y1, y2, x1, x2 = box
    m[y1:y2, x1:x2] = mask[y1:y2, x1:x2]
    return m


def find_trees(img: np.ndarray, box=BOX):
    """回傳 [(cx, cy, w, h, area), ...]（針葉樹冠），只找遊戲可視區內。"""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(TREE_HSV_LO, np.uint8), np.array(TREE_HSV_HI, np.uint8))
    return _blobs(_limit(mask, box))


def find_stones(img: np.ndarray, box=BOX):
    """回傳 [(cx, cy, w, h, area), ...]（灰色石頭），只找遊戲可視區內。"""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    _h, s, v = cv2.split(hsv)
    mask = ((s < STONE_MAX_SAT) & (v >= STONE_V_LO) & (v <= STONE_V_HI)).astype(np.uint8) * 255
    return _blobs(_limit(mask, box), min_area=200)


def annotate(img: np.ndarray, trees, stones):
    out = img.copy()
    for cx, cy, w, h, _a in trees:
        cv2.rectangle(out, (cx - w // 2, cy - h // 2), (cx + w // 2, cy + h // 2), (0, 0, 255), 4)
        cv2.putText(out, "T", (cx - 10, cy), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 3)
    for cx, cy, w, h, _a in stones:
        cv2.rectangle(out, (cx - w // 2, cy - h // 2), (cx + w // 2, cy + h // 2), (255, 0, 255), 4)
        cv2.putText(out, "S", (cx - 10, cy), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 0, 255), 3)
    return out

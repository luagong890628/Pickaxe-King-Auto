"""生命值條（粉紅/洋紅填充）比例偵測 —— 比 OCR 可靠，也不需要數字變動。

畫面：上方一條深藍底血條，外框黃色，內部粉紅/洋紅填充由左往右。
生命值越低，粉紅區域越短。

用法：
    from pkauto.hpbar import hp_fraction
    f = hp_fraction(img)     # 0.0 ~ 1.0，失敗回傳 None
"""
from __future__ import annotations

import cv2
import numpy as np

# 血條區域（實測：y≈601 那一列，粉紅填充從 x≈160 到 x≈1163，全滿寬 1004px）
Y0, Y1 = 560, 700
X0, X1 = 140, 1180


def _pink_mask(img):
    h, s, v = cv2.split(cv2.cvtColor(img[Y0:Y1, X0:X1], cv2.COLOR_BGR2HSV))
    # 粉紅/洋紅：色相在紫紅區、飽和度高、亮度中高
    m = ((h > 145) & (h < 178) & (s > 70) & (v > 120)).astype(np.uint8)
    return m


def bar_extent(img):
    """回傳 (left, right, width, row) 或 None。"""
    m = _pink_mask(img)
    rows = m.sum(axis=1)
    if rows.max() < 30:
        return None
    row = int(np.argmax(rows))
    xs = np.where(m[row] > 0)[0]
    if len(xs) == 0:
        return None
    return int(xs.min()), int(xs.max()), int(xs.max() - xs.min() + 1), row


FULL_WIDTH = 1004     # 滿血時量到的填充寬度（固定基準，不要每張重新量）


def hp_fraction(img, full_width=None):
    """生命值比例 0~1（以 FULL_WIDTH=1004 為滿血基準）。"""
    ext = bar_extent(img)
    if ext is None:
        return None
    _left, _right, width, _row = ext
    ref = full_width or FULL_WIDTH
    return min(1.0, width / float(ref))


def reset_cache():
    """保留介面（現在不需要快取）。"""
    return None

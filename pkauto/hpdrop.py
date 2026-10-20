"""血量變化偵測：不比對數字，直接比較「血量數字區域」前後是否改變。

好用處：每次揮鎬生命值 −1 → 數字一定變 → 「這塊區域變了」＝剛剛有砍到東西。
不需要 OCR、不需要範本，換角色/升級都照樣有效。

用法：
    from hpdrop import hp_sig, hp_changed
    s1 = hp_sig(img1); s2 = hp_sig(img2); hp_changed(s1, s2)
"""
from __future__ import annotations

import cv2
import numpy as np

# 生命值數字區（舊資料：y575-690, x560-900；愛心在最左邊 ~51px 要跳過）
Y0, Y1 = 570, 700
X0, X1 = 610, 910


def hp_sig(img):
    """取血量數字區的灰階圖（用來跟前一張比）。"""
    roi = img[Y0:Y1, X0:X1]
    g = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    return cv2.resize(g, (150, 65), interpolation=cv2.INTER_AREA)


def hp_changed(sig_a, sig_b, thr=8) -> bool:
    """兩張血量簽章是否不同（＝血量有變化）。"""
    if sig_a is None or sig_b is None:
        return False
    d = cv2.absdiff(sig_a, sig_b)
    # 只看「明顯變亮/變暗」的像素，避免雜訊
    return int((d > 45).sum()) > thr


def hp_diff_pixels(sig_a, sig_b) -> int:
    if sig_a is None or sig_b is None:
        return 0
    return int((cv2.absdiff(sig_a, sig_b) > 45).sum())

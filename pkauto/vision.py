"""影像工具：世界位移量測、模板比對、區域裁切。"""
from __future__ import annotations

import cv2
import numpy as np

# 遊戲可視區（y1, y2, x1, x2）：排除左右 UI 欄與頂部資源列
PLAY_BOX = (700, 2900, 260, 1140)


def normalize_brightness(img: np.ndarray, target: float = 130.0) -> np.ndarray:
    """畫面整體偏暗時（例如手機進入調暗、夜間模式）等比提亮，讓顏色遮罩仍可用。

    回傳新陣列；亮度正常時原樣回傳。
    """
    mean = float(img.mean())
    if mean >= 80 or mean < 1:
        return img
    gain = min(12.0, target / mean)
    return cv2.convertScaleAbs(img, alpha=gain, beta=0)


def to_gray(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img


def crop(img: np.ndarray, box) -> np.ndarray:
    y1, y2, x1, x2 = box
    return img[y1:y2, x1:x2]


def scroll(a: np.ndarray, b: np.ndarray, box=PLAY_BOX):
    """量測 b 相對 a 的世界位移（像素），回傳 (dx, dy, response)。

    正負號以 tests/test_vision.py 固定：dx>0 表示畫面內容在兩張圖之間往右移。
    response 越高越可信（>0.5 佳，<0.3 表示位移量測不可靠）。
    """
    y1, y2, x1, x2 = box
    ga = to_gray(a)[y1:y2, x1:x2].astype(np.float32)
    gb = to_gray(b)[y1:y2, x1:x2].astype(np.float32)
    win = cv2.createHanningWindow((ga.shape[1], ga.shape[0]), cv2.CV_32F)
    (dx, dy), response = cv2.phaseCorrelate(ga, gb, win)
    return float(dx), float(dy), float(response)


def find(img: np.ndarray, tpl: np.ndarray, threshold: float = 0.75):
    """模板比對，回傳 (cx, cy, score) 或 None（低於門檻）。

    純色或近乎純色的模板在 TM_CCOEFF_NORMED 下是退化情況（變異數趨近 0），
    分數不可信，直接拒絕。
    """
    if float(np.asarray(tpl, dtype=np.float32).std()) < 1.0:
        raise ValueError("模板近乎純色，TM_CCOEFF_NORMED 分數不可信")
    res = cv2.matchTemplate(img, tpl, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)
    if max_val < threshold:
        return None
    h, w = tpl.shape[:2]
    return max_loc[0] + w // 2, max_loc[1] + h // 2, float(max_val)


def diff(a: np.ndarray, b: np.ndarray, box=None) -> float:
    """兩張圖的平均像素差（0–255）。box 可限定區域。"""
    if box is not None:
        a, b = crop(a, box), crop(b, box)
    return float(np.abs(a.astype(np.int16) - b.astype(np.int16)).mean())


PATCH_SPOTS = [
    (280, 760, 300, 300),
    (860, 760, 300, 300),
    (420, 1900, 300, 300),
    (820, 1900, 300, 300),
]


def shift_by_template(a: np.ndarray, b: np.ndarray, threshold: float = 0.6):
    """用「畫面範本」量兩張圖之間的位移：取幾個靜態區塊，在 b 裡找回它們。

    比 phaseCorrelate 穩（畫面有雞/NPC/落葉在動時 phaseCorrelate 常失準）。
    回傳 (dx, dy, 平均分數, 用了幾塊) 或 None。

    正負號與 scroll() 一致：dx>0 表示畫面內容往右移（＝角色往左走）。
    """
    out = []
    h, w = a.shape[:2]
    for (x, y, pw, ph) in PATCH_SPOTS:
        if x + pw > w or y + ph > h:
            continue
        t = a[y:y + ph, x:x + pw]
        if float(t.std()) < 8.0:            # 純色區塊無法比對
            continue
        r = find(b, t, threshold=threshold)
        if r:
            out.append((r[0] - (x + pw // 2), r[1] - (y + ph // 2), r[2]))
    if not out:
        return None
    dx = float(np.median([o[0] for o in out]))
    dy = float(np.median([o[1] for o in out]))
    return dx, dy, float(np.mean([o[2] for o in out])), len(out)

"""讀取畫面頂部生命值數字（例：491/768），用於判斷「生命值歸零 → 去休息」。

作法是字模比對：把血條上的白色數字切成一個個字元，跟 captures/hp_digits/ 裡的範本比對。
遇到沒見過的字元會存到 captures/hp_digits/_unknown_*.png，之後人工標記就能補齊（例如 0、2、3、5）。
"""
from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np

REGION = (575, 690, 560, 900)      # y1, y2, x1, x2：血條數字的範圍
DIGITS_DIR = Path("captures/hp_digits")
NORM = (20, 30)                    # 統一縮放大小（寬, 高）


def _strip(img):
    y1, y2, x1, x2 = REGION
    return img[y1:y2, x1:x2]


def _segments(reg):
    """切出字元方塊（排除上下橫線、愛心圖示與小雜點）。

    不做形態學 close：close 會把相鄰字元黏在一起（實測把斜線吃掉）。
    """
    gray = cv2.cvtColor(reg, cv2.COLOR_BGR2GRAY)
    white = (gray > 175).astype(np.uint8) * 255
    n, _l, st, _c = cv2.connectedComponentsWithStats(white, 8)
    out = []
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if h > 20 and w < 200 and a > 40:
            out.append([int(x), int(y), int(w), int(h)])
    out.sort()
    if out and out[0][2] > 40:          # 最左邊是愛心圖示（約 50px 寬）→ 移除
        out = out[1:]
    return out, reg


def _norm(glyph_gray):
    return cv2.resize(glyph_gray, NORM, interpolation=cv2.INTER_AREA).astype(np.float32)


def load_templates():
    tpl = {}
    for p in DIGITS_DIR.glob("*.png"):
        if p.stem.startswith("_"):
            continue
        g = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        if g is not None:
            tpl[p.stem] = _norm(g)
    return tpl


def _is_dup_unknown(gg) -> bool:
    """已存在長得像的未知字元就不再存一份（等人工標記）。"""
    g = _norm(cv2.cvtColor(gg, cv2.COLOR_BGR2GRAY) if gg.ndim == 3 else gg)
    for p in DIGITS_DIR.glob("_unknown_*.png"):
        o = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        if o is None:
            continue
        t = _norm(o)
        a, b = g - g.mean(), t - t.mean()
        d = float((a * b).sum() / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-6))
        if d > 0.9:
            return True
    return False


def _classify(glyph_gray, tpl):
    g = _norm(glyph_gray)
    best, score = None, -1.0
    for lab, t in tpl.items():
        a = g - g.mean()
        b = t - t.mean()
        d = float((a * b).sum() / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-6))
        if d > score:
            best, score = lab, d
    return best, score


def read(img, save_unknown=True):
    """回傳 (文字, 明細)。無法辨識時文字為 None。"""
    reg = _strip(img)
    segs, reg = _segments(reg)
    tpl = load_templates()
    if not segs or not tpl:
        return None, {"reason": "no-glyph-or-template", "segs": segs}
    chars, det = [], []
    prev_right = None
    for (x, y, w, h) in segs:
        # 斜線常常切不出來：字元間距 > 25px 就代表這裡是「分子/分母」的分界
        if prev_right is not None and x - prev_right > 25:
            chars.append("/")
            det.append(("slash", 1.0, 0, 0))
        prev_right = x + w
        gg = cv2.cvtColor(reg[y:y + h, x:x + w], cv2.COLOR_BGR2GRAY)
        lab, sc = _classify(gg, tpl)
        if sc < 0.72:
            if save_unknown and not _is_dup_unknown(gg):
                p = DIGITS_DIR / f"_unknown_{time.strftime('%H%M%S')}_{len(list(DIGITS_DIR.glob('_unknown_*.png'))):03d}.png"
                cv2.imwrite(str(p), gg)
            chars.append("?")
            det.append(("?", round(sc, 2), w, h))
        else:
            chars.append(lab)
            det.append((lab, round(sc, 2), w, h))
    text = "".join(chars)
    return text, {"segs": det}


def is_zero(img) -> bool:
    """生命值是否歸零（畫面上顯示 0/xxx）。"""
    text, _det = read(img)
    return bool(text) and text.startswith("0/")


if __name__ == "__main__":
    import sys

    from pkauto import adb, vision

    s = vision.normalize_brightness(adb.screencap())
    print(read(s))

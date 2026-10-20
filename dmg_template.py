"""從連拍幀切出傷害數字範本，並用使用者標記驗證偵測率。

傷害數字特徵（實測）：白色字 + 粗黑描邊，出現在錨點左上固定位置附近（約 x600-740, y1220-1300）。
關鍵：不用認「158」，只認「這裡有沒有白底黑邊的數字筆畫」→ 升級後數字改變也照樣偵測得到。
"""

import glob
import json

import cv2
import numpy as np

BOX = (560, 800, 1180, 1330)      # x0, x1, y0, y1

FULL = [2, 3, 6, 8, 20, 22, 23, 27, 31, 33, 37, 39, 40, 41]
PART = [4, 5, 7, 13, 17, 19, 21, 25, 28, 30, 32, 34, 35]
NO = [0, 1, 9, 10, 11, 12, 15, 16, 18, 24, 26, 29, 36, 38]


def white_glyph_mask(img, box=BOX):
    x0, x1, y0, y1 = box
    roi = img[y0:y1, x0:x1]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    white = ((v > 195) & (s < 70)).astype(np.uint8) * 255
    white = cv2.morphologyEx(white, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), 1)
    return roi, white


def glyph_score(img, box=BOX):
    """回傳 (分數, bbox, 遮罩)；分數＝最大白塊面積（數字筆畫會連成一大塊）。"""
    roi, white = white_glyph_mask(img, box)
    n, _l, st, _c = cv2.connectedComponentsWithStats(white, 8)
    best = (0, None)
    total = 0
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if a < 40 or h < 14 or h > 110:
            continue
        if w / max(h, 1) > 3.2:            # 太扁的橫線不是數字
            continue
        total += int(a)
        if a > best[0]:
            best = (int(a), (int(x), int(y), int(w), int(h)))
    return total, best[1], roi, white


def main():
    files = sorted(glob.glob("captures/burst/*.jpg"))
    rows = []
    best_frame, best_score = None, 0
    for idx, f in enumerate(files):
        img = cv2.imread(f)
        total, bbox, roi, white = glyph_score(img)
        rows.append((idx, total, bbox))
        if total > best_score:
            best_score, best_frame = total, idx
    rows_sorted = sorted(rows, key=lambda r: -r[1])
    print("白塊面積最大的前 8 幀:", [(i, t) for i, t, _ in rows_sorted[:8]])
    print("沒有數字的幀（使用者標記）分數:", [(i, t) for i, t, _ in rows if i in NO])

    # 用最高分那幀切範本
    img = cv2.imread(files[best_frame])
    total, bbox, roi, white = glyph_score(img)
    x, y, w, h = bbox
    pad = 6
    crop = roi[max(0, y - pad):y + h + pad, max(0, x - pad):x + w + pad]
    cv2.imwrite("captures/tpl_dmg.png", crop)
    print(f"範本取自幀 {best_frame}，大小 {crop.shape[1]}x{crop.shape[0]} → captures/tpl_dmg.png")

    # 驗證：範本比對 vs 使用者標記
    tpl = crop
    print("\n幀  分數  標記")
    ok = bad = 0
    for idx, f in enumerate(files):
        g = cv2.cvtColor(cv2.imread(f), cv2.COLOR_BGR2GRAY)
        res = cv2.matchTemplate(g[1180:1330, 560:800], cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY), cv2.TM_CCOEFF_NORMED)
        sc = float(res.max())
        label = "full" if idx in FULL else ("part" if idx in PART else "no")
        hit = sc >= 0.55
        want = label != "no"
        if hit == want:
            ok += 1
        else:
            bad += 1
            print(f"  {idx:03d} {sc:.2f} {label}  ← 錯")
    print(f"\n比對正確 {ok}/{ok+bad}")


if __name__ == "__main__":
    main()

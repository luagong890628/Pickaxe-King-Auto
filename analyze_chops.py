"""從被動錄影自動學習「使用者砍掉的目標長什麼樣」。

原理（不需要人工標註）：
- 使用者砍樹/石頭時角色是停下來的 → 相鄰兩張畫面幾乎對齊（位移小）
- 對齊後做差分：上一張「是綠色（樹冠）或灰色（石頭）」、下一張「不見了」的區塊
  = 被砍掉的目標 → 自動存成正樣本
- 一直沒消失的綠色/灰色區塊 = 不能砍的（黃金樹、建築、小雞…）→ 存成負樣本

輸出：data/chop_learn/pos/ 與 data/chop_learn/neg/
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

import cv2
import numpy as np


def green_mask(img):
    h, s, v = cv2.split(cv2.cvtColor(img, cv2.COLOR_BGR2HSV))
    return ((h > 45) & (h < 95) & (s > 140) & (v > 70)).astype(np.uint8) * 255


def gray_mask(img):
    h, s, v = cv2.split(cv2.cvtColor(img, cv2.COLOR_BGR2HSV))
    return ((s < 45) & (v > 110) & (v < 230)).astype(np.uint8) * 255


def main():
    d = sorted(glob.glob("data/chop_rec/*/"))[-1]
    files = sorted(glob.glob(d + "f*.jpg"))
    out = Path("data/chop_learn")
    (out / "pos").mkdir(parents=True, exist_ok=True)
    (out / "neg").mkdir(parents=True, exist_ok=True)
    print(f"來源: {d}（{len(files)} 張）")
    pos = neg = pairs = 0
    report = []
    prev = cv2.imread(files[0])
    prev_g, prev_y = green_mask(prev), gray_mask(prev)
    for i in range(1, len(files)):
        cur = cv2.imread(files[i])
        if cur is None or cur.shape != prev.shape:
            prev = cur if cur is not None else prev
            continue
        # 對齊（只接受「幾乎沒動」的幀對＝使用者正在砍）
        (dx, dy), resp = cv2.phaseCorrelate(np.float32(cv2.cvtColor(prev, cv2.COLOR_BGR2GRAY)),
                                            np.float32(cv2.cvtColor(cur, cv2.COLOR_BGR2GRAY)))
        if resp < 0.30 or abs(dx) + abs(dy) > 9:
            prev, prev_g, prev_y = cur, green_mask(cur), gray_mask(cur)
            continue
        pairs += 1
        M = np.float32([[1, 0, dx], [0, 1, dy]])
        cur_b = cv2.warpAffine(cur, M, (cur.shape[1], cur.shape[0]))
        cur_g, cur_y = green_mask(cur_b), gray_mask(cur_b)
        changed = (cv2.absdiff(cv2.cvtColor(prev, cv2.COLOR_BGR2GRAY),
                               cv2.cvtColor(cur_b, cv2.COLOR_BGR2GRAY)) > 28).astype(np.uint8) * 255
        for name, pm, cm in (("tree", prev_g, cur_g), ("stone", prev_y, cur_y)):
            gone = cv2.bitwise_and(cv2.bitwise_and(pm, cv2.bitwise_not(cm)), changed)
            gone = cv2.morphologyEx(gone, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8), 1)
            n, _l, st, ce = cv2.connectedComponentsWithStats(gone, 8)
            for j in range(1, n):
                x, y, w, hh, a = st[j]
                if a < 1200 or a > 60000 or y < 380 or y > 1500:
                    continue
                cx, cy = int(ce[j][0]), int(ce[j][1])
                r = int(max(w, hh) * 0.75) + 30
                x1, y1 = max(0, cx - r), max(0, cy - r)
                x2, y2 = min(prev.shape[1], cx + r), min(prev.shape[0], cy + r)
                crop = prev[y1:y2, x1:x2]
                if crop.size == 0 or min(crop.shape[:2]) < 40:
                    continue
                pos += 1
                cv2.imwrite(str(out / "pos" / f"{name}_{pos:03d}_a{a}.png"), crop)
                report.append({"i": i, "kind": name, "area": int(a), "at": [cx, cy]})
        # 負樣本：一直存在的綠色（黃金樹／遠景樹）與灰色（建築）
        n, _l, st, ce = cv2.connectedComponentsWithStats(cv2.morphologyEx(prev_g, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8), 1), 8)
        for j in range(1, n):
            x, y, w, hh, a = st[j]
            if a < 30000:
                continue
            cx, cy = int(ce[j][0]), int(ce[j][1])
            if prev_g[max(0, cy-5):cy+5, max(0, cx-5):cx+5].size == 0:
                continue
            r = int(max(w, hh) * 0.6) + 30
            crop = prev[max(0, cy-r):cy+r, max(0, cx-r):cx+r]
            if crop.size == 0 or min(crop.shape[:2]) < 60:
                continue
            neg += 1
            cv2.imwrite(str(out / "neg" / f"persist_{neg:03d}_a{a}.png"), crop)
            if neg > 400:
                break
        prev, prev_g, prev_y = cur, green_mask(cur), gray_mask(cur)
    json.dump(report, open(out / "pos_report.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"對齊成功的幀對: {pairs}")
    print(f"正樣本（砍掉的目標）: {pos} 張 → data/chop_learn/pos/")
    print(f"負樣本（一直存在的）: {neg} 張 → data/chop_learn/neg/")


if __name__ == "__main__":
    main()

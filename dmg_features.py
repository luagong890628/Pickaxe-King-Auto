"""用使用者標記的「有/沒有傷害數字」幀，找出能分開兩邊的影像特徵。

重點：特徵必須是「這裡有沒有數字筆畫」而不是「是不是 158」，
這樣鎬子升級、傷害數字改變也不用重新校正。
"""

import glob
import json

import cv2
import numpy as np

# 使用者標記（2026-10-20）
NO_DMG = [0, 1, 9, 10, 11, 12, 15, 16, 18, 24, 26, 29, 36, 38]
FULL = [2, 3, 6, 8, 20, 22, 23, 27, 31, 33, 37, 39, 40, 41]
PART = [4, 5, 7, 13, 17, 19, 21, 25, 28, 30, 32, 34, 35]

# 數字會往上飄 → 取一個涵蓋飄移路徑的區域（錨點 720,1400 的左上方）
X0, X1, Y0, Y1 = 500, 900, 1050, 1420


def features(img):
    roi = img[Y0:Y1, X0:X1]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    # 數字＝很亮的字（黃或白都算），飽和度不限
    bright = ((v > 195) & (s < 210)).astype(np.uint8) * 255
    bright = cv2.morphologyEx(bright, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), 1)
    n, _l, st, _c = cv2.connectedComponentsWithStats(bright, 8)
    digitish = []
    for i in range(1, n):
        x, y, w, hh, a = st[i]
        if a < 60 or a > 2600:
            continue
        if hh < 18 or hh > 130:
            continue
        if not (0.15 < w / max(hh, 1) < 1.8):
            continue
        digitish.append(int(a))
    digitish.sort(reverse=True)
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 80, 200)
    return {
        "bright_px": int(bright.sum() // 255),
        "digit_blobs": len(digitish),
        "digit_area": int(sum(digitish)),
        "digit_top3": int(sum(digitish[:3])),
        "edge_px": int((edges > 0).sum()),
    }


def main():
    files = sorted(glob.glob("captures/burst/*.jpg"))
    rows = []
    for idx, f in enumerate(files):
        img = cv2.imread(f)
        fe = features(img)
        fe["idx"] = idx
        fe["label"] = "no" if idx in NO_DMG else ("full" if idx in FULL else ("part" if idx in PART else "?"))
        rows.append(fe)

    def show(label):
        sel = [r for r in rows if r["label"] == label]
        if not sel:
            return
        for k in ("bright_px", "digit_blobs", "digit_area", "digit_top3", "edge_px"):
            vals = sorted(r[k] for r in sel)
            print(f"  {label:4s} {k:12s} 中位數 {vals[len(vals)//2]:6d}  範圍 {vals[0]}~{vals[-1]}")

    print("=== 各組特徵 ===")
    for lb in ("no", "part", "full"):
        show(lb)

    # 用 digit_top3 找分界
    no = [r["digit_top3"] for r in rows if r["label"] == "no"]
    yes = [r["digit_top3"] for r in rows if r["label"] in ("full", "part")]
    print(f"\ndigit_top3: 沒有=最高 {max(no)}  有=最低 {min(yes)}")
    for thr in range(200, 2000, 100):
        fp = sum(1 for v in no if v >= thr)
        fn = sum(1 for v in yes if v < thr)
        if fp + fn <= 2:
            print(f"  門檻 {thr}: 誤判 {fp} / 漏抓 {fn}  ← 可用")

    json.dump(rows, open("captures/dmg_features.json", "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()

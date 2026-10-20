"""自動砍素材：固定錨點 + 把目標帶到錨點 + 「目標消失」驗證。

設計（使用者 2026-10-20 定案）
- 角色固定在畫面 (720,1400)，**不去偵測角色**（他是常數）。
- 目標出現在畫面某處 → 朝它走，讓它被「帶到」錨點上 → 到了遊戲自動揮鎬。
- 移動用「按住時間」控制（實測 ≈315px/秒），每步重新偵測目標位置（閉環，誤差不累積）。
- 驗證：貼上後等 1.2 秒，目標消失＝砍掉了 ✓（比傷害數字可靠：數字會飄、會被遮擋、只亮 0.8 秒）。
- 貼上兩次目標還在 → 判定「不能砍」→ 黑名單跳過。
- 畫面沒有目標 → 傳送到小村莊／起始之地另一邊。

用法：
    chop_servo.py 20 --area village
    chop_servo.py 20 --area start --dry
"""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import cv2
import numpy as np

from pkauto import adb, hp, teleport, vision

ANC = (720, 1400)
DRAG = (720, 2600)
PPS = 315.0                      # 按住每秒的畫面位移（實測）
REACH = 820                      # 只找錨點附近的目標


def shot():
    return vision.normalize_brightness(adb.screencap())


# ---------- 偵測 ----------

def find_targets(img):
    """回傳 [(dist, x, y, kind)]，依離錨點距離排序。

    樹＝深綠（V<165，含 H>42 排除黃色帳篷）；石頭＝灰（V 110~205，避開白色小雞/蛋）。
    兩者都要求「下方是綠草地」，濾掉建築物裡的道具。
    """
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    out = []

    def grass_below(x, y, w, hh):
        y1, y2 = min(img.shape[0], y + hh + 4), min(img.shape[0], y + hh + 46)
        x1, x2 = max(0, x), min(img.shape[1], x + w)
        if y2 <= y1 or x2 <= x1:
            return False
        hh2, ss2, vv2 = cv2.split(cv2.cvtColor(img[y1:y2, x1:x2], cv2.COLOR_BGR2HSV))
        return float(((hh2 > 35) & (hh2 < 100) & (ss2 > 60) & (vv2 > 60)).mean()) > 0.35

    tree = ((h > 42) & (h < 100) & (s > 80) & (v > 55) & (v < 170)).astype(np.uint8) * 255
    tree = cv2.morphologyEx(tree, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8), 2)
    tree = cv2.morphologyEx(tree, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8), 2)
    n, _l, st, _c = cv2.connectedComponentsWithStats(tree, 8)
    for i in range(1, n):
        x, y, w, hh, a = st[i]
        if a < 1500 or y < 500 or y > 2900 or x < 200 or x > 1240:
            continue
        if not grass_below(x, y, w, hh):
            continue
        cx, cy = x + w / 2, min(y + hh + 30, 2900)
        d = math.hypot(cx - ANC[0], cy - ANC[1])
        if 55 < d < REACH:
            out.append((d, float(cx), float(cy), "tree"))

    stone = ((s < 45) & (v > 110) & (v < 205)).astype(np.uint8) * 255
    stone = cv2.morphologyEx(stone, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8), 2)
    n2, _l2, st2, _c2 = cv2.connectedComponentsWithStats(stone, 8)
    for i in range(1, n2):
        x, y, w, hh, a = st2[i]
        if a < 900 or a > 9000 or w > 170 or hh > 170:
            continue
        if y < 500 or y > 2900 or x < 200 or x > 1240:
            continue
        if not grass_below(x, y, w, hh):
            continue
        cx, cy = x + w / 2, y + hh / 2
        d = math.hypot(cx - ANC[0], cy - ANC[1])
        if 55 < d < REACH:
            out.append((d, float(cx), float(cy), "stone"))

    out.sort()
    return out


def target_still_there(img, tx, ty, kind, tol=110):
    for _d, cx, cy, k in find_targets(img):
        if k == kind and abs(cx - tx) < tol and abs(cy - ty) < tol:
            return True
    return False


# ---------- 移動 ----------

def move(img, vx, vy, dist):
    """朝 (vx,vy) 走 dist 距離（按住時間控制）；被擋換角度。回傳 (dx, dy, moved, img)。"""
    base = math.atan2(vy, vx)
    hold = int(min(1500, max(260, dist / PPS * 1000)))
    cur = img
    for off in (0, 35, -35, 70, -70, 130, -130, 180):
        a = base + math.radians(off)
        adb.swipe(*DRAG, int(DRAG[0] + math.cos(a) * 260), int(DRAG[1] + math.sin(a) * 260), hold)
        time.sleep(hold / 1000.0 + 0.5)
        cur = shot()
        sh = vision.shift_by_template(img, cur, threshold=0.6)
        dx, dy = (sh[0], sh[1]) if sh else tuple(vision.scroll(img, cur)[:2])
        if abs(dx) + abs(dy) > 25:
            return dx, dy, True, cur
    return 0.0, 0.0, False, cur


# ---------- 主流程 ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("minutes", type=float, nargs="?", default=20.0)
    ap.add_argument("--area", choices=["village", "start"], default="village")
    ap.add_argument("--dry", action="store_true", help="不傳送、不動作，只印偵測結果")
    args = ap.parse_args()

    run = Path("captures") / time.strftime("servo_%Y%m%d_%H%M%S")
    run.mkdir(parents=True, exist_ok=True)
    log = (run / "log.jsonl").open("w", encoding="utf-8")

    def rec(o):
        o["t"] = time.strftime("%H:%M:%S")
        log.write(json.dumps(o, ensure_ascii=False) + "\n")
        log.flush()
        print(json.dumps(o, ensure_ascii=False), flush=True)

    area = args.area
    other = "start" if area == "village" else "village"

    if args.dry:
        img = shot()
        ts = find_targets(img)
        print(f"偵測到 {len(ts)} 個目標（乾跑，不動手機）")
        for d, x, y, k in ts[:10]:
            print(f"  {k} 距離{d:.0f}px 位置({x:.0f},{y:.0f})")
        cv2.imwrite(str(run / "dry.png"), img)
        return

    rec({"note": "start", "area": area})
    if not teleport.go(area):
        rec({"note": "傳送失敗 → 結束"})
        return
    time.sleep(2.5)

    hits = 0
    misses = 0
    idle = 0
    blacklist = []
    t0 = time.time()
    deadline = t0 + args.minutes * 60

    while time.time() < deadline:
        img = shot()

        # 腳下不是草地（跑進建築物）→ 往南走出來
        foot = img[ANC[1] + 60:ANC[1] + 170, ANC[0] - 120:ANC[0] + 120]
        fh, fs, fv = cv2.split(cv2.cvtColor(foot, cv2.COLOR_BGR2HSV))
        if float(((fh > 35) & (fh < 100) & (fs > 60) & (fv > 60)).mean()) < 0.22:
            rec({"note": "在建築物裡 → 往南走出來"})
            move(img, 0, 1, 280)
            continue

        cands = [c for c in find_targets(img)
                 if all(math.hypot(c[1] - bx, c[2] - by) > 150 for bx, by in blacklist)]
        if not cands:
            idle += 1
            if idle >= 3:
                rec({"note": f"{area} 沒目標了 → 換到 {other}", "idle": idle})
                if teleport.go(other):
                    area, other = other, area
                    idle = 0
                    blacklist.clear()
                    continue
                idle = 0
            rec({"note": "找不到目標 → 往一個方向探"})
            move(img, math.cos(time.time()), math.sin(time.time()), 300)
            continue

        idle = 0
        d, tx, ty, kind = cands[0]

        if d <= 95:
            # 貼上了 → 等揮鎬 → 看目標有沒有消失
            time.sleep(1.25)
            cur = shot()
            if target_still_there(cur, tx, ty, kind):
                misses += 1
                if misses >= 2:
                    rec({"note": "貼兩次還在 → 不能砍，列入黑名單", "kind": kind, "at": [tx, ty]})
                    blacklist.append((tx, ty))
                    misses = 0
            else:
                hits += 1
                misses = 0
                rec({"note": "砍掉了 ✓", "kind": kind, "hits": hits, "at": [tx, ty]})
            continue

        # 朝目標走（走 85% 的距離，留餘裕避免衝過頭）
        vx, vy = tx - ANC[0], ty - ANC[1]
        n = max(abs(vx), abs(vy), 1)
        dx, dy, moved, img2 = move(img, vx / n, vy / n, min(420, max(120, d * 0.85)))
        rec({"note": "走向目標", "kind": kind, "d": round(d), "moved": moved,
             "shift": [round(dx), round(dy)], "hits": hits})
        misses = 0

    log.close()
    print(f"完成：{hits} 次砍掉，記錄在 {run}")


if __name__ == "__main__":
    main()

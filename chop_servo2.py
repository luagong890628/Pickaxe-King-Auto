"""自動砍素材 v2：錨點 + 「最近的樹像素」導引。

核心（使用者 2026-10-20 定案）
- 角色固定在畫面 (720,1400)，不偵測角色（常數）。
- 樹/石頭都在角色上方；樹常整片黏在一起，**不切單棵**，直接找「離錨點最近的目標像素」當導引點。
- 朝它走（按住時間控制，≈315px/秒），每步重新偵測 → 目標被帶到錨點上 → 遊戲自動揮鎬。
- 命中驗證：錨點附近那個區域的目標像素大幅減少＝砍掉了（比傷害數字可靠）。
- 貼上兩次還在 → 判定不能砍 → 從導引遮罩裡挖掉，換下一個。
- 沒有目標像素 → 換地區（小村莊 ⇄ 起始之地）。

用法：chop_servo2.py 20 --area village
"""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import cv2
import numpy as np

from pkauto import adb, teleport, vision

ANC = (720, 1400)
DRAG = (720, 2600)
PPS = 315.0
NEAR = 175                     # 貼上判定（角色本身遮罩半徑 150，所以貼上門檻要大於它）

HX0, HX1 = 200, 1260           # 遊戲視野（避開左右 UI）
HY0, HY1 = 380, 1390           # 只看角色上方（使用者確認：往下絕對沒有樹）


def shot():
    return vision.normalize_brightness(adb.screencap())


def target_mask(img):
    """樹＋石頭的遮罩（樹＝深綠核心，石頭＝灰）。"""
    h, s, v = cv2.split(cv2.cvtColor(img, cv2.COLOR_BGR2HSV))
    tree = ((h > 40) & (h < 105) & (s > 105) & (v > 85) & (v < 178))
    # 石頭：灰色、不能太白（乳牛/雞是白色會被誤判），要求有一定大小
    stone = (s < 40) & (v > 120) & (v < 190)
    m = (tree | stone).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), 1)
    keep = np.zeros_like(m)
    keep[HY0:HY1, HX0:HX1] = m[HY0:HY1, HX0:HX1]
    # 角色自己就在錨點上，把他周圍一圈遮掉（否則會把自己的身體/腳下陰影當成目標）
    cv2.circle(keep, ANC, 150, 0, -1)
    return keep


def nearest_point(mask, exclude=None, max_d=760):
    """回傳離錨點最近的目標像素 (x, y, d)；太遠回傳 None。"""
    ys, xs = np.where(mask > 0)
    if len(xs) == 0:
        return None
    d = np.hypot(xs - ANC[0], ys - ANC[1])
    if exclude is not None:
        d = d + exclude[ys, xs] * 2000        # 黑名單區域推遠
    i = int(np.argmin(d))
    if d[i] > max_d:
        return None
    return int(xs[i]), int(ys[i]), float(d[i])


def move(img, vx, vy, dist):
    base = math.atan2(vy, vx)
    hold = int(min(1400, max(250, dist / PPS * 1000)))
    cur = img
    for off in (0, 30, -30, 65, -65, 120, -120, 180):
        a = base + math.radians(off)
        adb.swipe(*DRAG, int(DRAG[0] + math.cos(a) * 260), int(DRAG[1] + math.sin(a) * 260), hold)
        time.sleep(hold / 1000.0 + 0.45)
        cur = shot()
        sh = vision.shift_by_template(img, cur, threshold=0.6)
        dx, dy = (sh[0], sh[1]) if sh else tuple(vision.scroll(img, cur)[:2])
        if abs(dx) + abs(dy) > 20:
            return dx, dy, True, cur
    return 0.0, 0.0, False, cur


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("minutes", type=float, nargs="?", default=20.0)
    ap.add_argument("--area", choices=["village", "start"], default="village")
    ap.add_argument("--no-teleport", action="store_true")
    args = ap.parse_args()

    run = Path("captures") / time.strftime("s2_%Y%m%d_%H%M%S")
    run.mkdir(parents=True, exist_ok=True)
    log = (run / "log.jsonl").open("w", encoding="utf-8")

    def rec(o):
        o["t"] = time.strftime("%H:%M:%S")
        log.write(json.dumps(o, ensure_ascii=False) + "\n")
        log.flush()
        print(json.dumps(o, ensure_ascii=False), flush=True)

    area, other = args.area, ("start" if args.area == "village" else "village")
    if not args.no_teleport:
        rec({"note": f"傳送到 {area}"})
        if not teleport.go(area):
            rec({"note": "傳送失敗 → 結束"})
            return
        time.sleep(2.5)

    hits = misses = 0
    blacklist = np.zeros((3120, 1440), np.float32)
    t0 = time.time()
    deadline = t0 + args.minutes * 60
    idle = 0

    while time.time() < deadline:
        img = shot()
        mask = target_mask(img)

        pt = nearest_point(mask, exclude=blacklist)
        if pt is None:
            idle += 1
            if idle >= 2:
                rec({"note": f"{area} 沒目標 → 換到 {other}"})
                if not args.no_teleport and teleport.go(other):
                    area, other = other, area
                    blacklist[:] = 0
                    idle = 0
                    continue
                idle = 0
            rec({"note": "畫面沒有目標 → 往上探"})
            move(img, 0, -1, 340)
            continue

        idle = 0
        tx, ty, d = pt
        before = int(mask[max(0, ty - 120):ty + 120, max(0, tx - 120):tx + 120].sum())

        if d <= NEAR:
            time.sleep(1.3)
            cur = shot()
            after_mask = target_mask(cur)
            after = int(after_mask[max(0, ty - 120):ty + 120, max(0, tx - 120):tx + 120].sum())
            if after < before * 0.45:
                hits += 1
                misses = 0
                rec({"note": "砍掉了 ✓", "hits": hits, "at": [tx, ty], "px": [before, after]})
            else:
                misses += 1
                if misses >= 2:
                    rec({"note": "貼兩次還在 → 不能砍，跳過", "at": [tx, ty]})
                    cv2.circle(blacklist, (tx, ty), 170, 1.0, -1)
                    misses = 0
            continue

        # 上方中線有樹 → 直接往上（樹會被帶到錨點）；否則才朝目標橫向修正
        strip = mask[max(0, ANC[1] - 520):ANC[1], ANC[0] - 250:ANC[0] + 250]
        if strip.sum() > 400:
            vx, vy, step = -0.25 * (tx - ANC[0]) / max(d, 1), -1.0, 300
        else:
            vx, vy = tx - ANC[0], ty - ANC[1]
            step = min(360, max(90, d * 0.8))
        vy = min(vy, -0.15)                     # 絕對不往南（往下是牛的農場）
        n = max(abs(vx), abs(vy), 1)
        dx, dy, moved, img2 = move(img, vx / n, vy / n, step)
        rec({"note": "走向目標", "d": round(d), "moved": moved, "shift": [round(dx), round(dy)], "hits": hits})
        misses = 0

    log.close()
    print(f"完成：{hits} 次砍掉 → {run}")


if __name__ == "__main__":
    main()

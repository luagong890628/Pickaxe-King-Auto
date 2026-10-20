"""掃描式自動砍素材：不偵測任何東西，走過去就會自動砍。

使用者 2026-10-20 確認：
- 傳送到 小村莊 / 起始之地 後，**往上走**才會到可砍的樹；往下是牛的農場（絕對沒有樹）。
- **邊移動邊砍也可以**（走過去就自動揮鎬）→ 所以不需要偵測樹 ✗。
- 樹石在生成範圍內隨機，砍掉 100 秒重生 → 反覆掃同一區即可。

策略：
1. 傳送 → 往上推進（撞到東西就左右換角度）
2. 進入森林後做「之字形」掃描：左右橫掃 + 每趟往上一小步
3. 血量下降量 = 揮鎬次數（客觀成效指標）
4. 掃完一輪 → 換另一個地區

用法：sweep_up.py 20 --area village
"""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import cv2
import numpy as np

from pkauto import adb, hp, hpdrop, teleport, vision

ANC = (720, 1400)
DRAG = (720, 2600)
PPS = 315.0


def shot():
    return vision.normalize_brightness(adb.screencap())


def move(img, vx, vy, dist, tries=(0, 25, -25, 55, -55, 100, -100, 150, -150, 180)):
    """朝 (vx,vy) 走 dist；被擋就換角度。回傳 (dx, dy, moved, img)。"""
    base = math.atan2(vy, vx)
    hold = int(min(1600, max(260, dist / PPS * 1000)))
    cur = img
    for off in tries:
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

    run = Path("captures") / time.strftime("sweep_%Y%m%d_%H%M%S")
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
            rec({"note": "傳送失敗"})
            return
        time.sleep(2.5)

    img = shot()
    sig = hpdrop.hp_sig(img)
    chop_events = 0
    rec({"note": "開始掃描", "area": area})

    t0 = time.time()
    deadline = t0 + args.minutes * 60
    direction = -1          # -1 = 往北（上）
    lateral = 1             # 橫掃方向
    passes = 0
    stuck_up = 0

    while time.time() < deadline:
        # 先確保「往上」有路：上方沒路就橫掃
        dx, dy, moved, img = move(img, 0, direction, 320)
        if not moved:
            stuck_up += 1
            # 卡住時：先試斜上（45°），再大幅橫移繞路
            if stuck_up % 3 == 1:
                rec({"note": "上方沒路 → 試斜上", "stuck": stuck_up, "side": lateral})
                dx, dy, moved, img = move(img, lateral * 0.7, -1, 340)
            else:
                rec({"note": "上方沒路 → 大幅橫移繞路", "stuck": stuck_up, "side": lateral})
                dx, dy, moved, img = move(img, lateral, 0, 560)
                if not moved:
                    lateral *= -1
                    rec({"note": "橫向也沒路 → 換邊", "side": lateral})
            if stuck_up >= 4:
                # 卡死了 → 換地區
                rec({"note": f"卡住 → 換到 {other}"})
                if not args.no_teleport and teleport.go(other):
                    area, other = other, area
                    stuck_up = 0
                    time.sleep(2.0)
                    img = shot()
                continue
            continue

        # 有往上 → 繼續推；順便偶爾橫掃擴大覆蓋
        passes += 1
        if passes % 4 == 0:
            lateral *= -1
        if passes % 5 == 0:
            rec({"note": "推進中", "passes": passes, "chops": chop_events, "up": round(dy)})
        if passes % 3 == 0:
            move(img, lateral, -0.6, 360)
            img = shot()
        new_sig = hpdrop.hp_sig(img)
        if hpdrop.hp_changed(sig, new_sig):
            chop_events += 1
            rec({"note": "砍到東西 ✓", "chop_events": chop_events,
                 "diff_px": hpdrop.hp_diff_pixels(sig, new_sig), "moved": [round(dx), round(dy)]})
        sig = new_sig

    rec({"note": "結束", "chop_events": chop_events, "area": area})
    log.close()
    print(f"完成 → {run}")


if __name__ == "__main__":
    main()

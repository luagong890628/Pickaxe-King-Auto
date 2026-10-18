"""自動砍素材（A 方案：局部智慧，不需要知道自己在哪）。

設計（全部靠「這一張畫面」就能判斷，不做地圖、不做全局定位）：
- 看到樹/石頭 → 朝最近的那個走過去（走一步就重新偵測，目標會自己更新）。
- 被擋住 → 自動換角度繞（±45/±90/±135/180°）——實測有效。
- 貼上目標（很近）→ 停一下讓揮鎬砍，然後把那個方向設為「剛去過」，避免原地打轉。
- 畫面裡沒有目標 → 沿目前方向一直走（撞到就換角度），直到看到目標為止。
- 生命值歸零 → 走去帳篷休息（沿用已驗證的流程）→ 醒來繼續。

成效指標：每分鐘揮鎬次數（用生命值下降量估算——每揮一次 -1）。
"""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import cv2
import numpy as np

from pkauto import adb, vision, hp

ANCHOR = (720, 1400)
DRAG = (720, 2600)
MENU_BG = np.array([255, 211, 143])
DMG_TPL = cv2.imread("captures/tpl_dmg151.png")
TENT_TPL = cv2.imread("captures/tpl_tent.png")
REST_TPL = cv2.imread("captures/tpl_rest_dialog.png")
HIT_R = 80          # 到這個距離算「貼上目標」
MIN_DRAG = 250      # 拖曳下限（太短會被遊戲當成點擊）


def shot():
    return vision.normalize_brightness(adb.screencap())


def menu_share(img) -> float:
    mid = img[560:2840, 60:1380]
    return float((np.abs(mid.astype(np.int16) - MENU_BG).max(axis=2) < 45).mean())


def targets(img):
    """畫面裡的樹冠/石頭（依離角色距離排序）。樹冠取底部（樹幹位置）。"""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    out = []
    green = ((h > 45) & (h < 95) & (s > 150) & (v > 80)).astype(np.uint8) * 255
    green = cv2.morphologyEx(green, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8), 1)
    n, _l, st, _c = cv2.connectedComponentsWithStats(green, 8)
    for i in range(1, n):
        x, y, w, hh, a = st[i]
        if a < 2500 or y < 700 or y > 2860 or x < 260 or x > 1230:
            continue
        tx, ty = x + w / 2, min(y + hh + 36, 2840.0)
        d = math.hypot(tx - ANCHOR[0], ty - ANCHOR[1])
        if d > 55:
            out.append((d, float(tx), float(ty), "tree"))
    gray = ((s < 42) & (v > 115) & (v < 225)).astype(np.uint8) * 255
    n2, _l2, st2, _c2 = cv2.connectedComponentsWithStats(gray, 8)
    for i in range(1, n2):
        x, y, w, hh, a = st2[i]
        if a < 800 or a > 9000 or w > 170 or hh > 170 or y < 700 or y > 2860 or x < 260 or x > 1230:
            continue
        cx, cy = x + w / 2, y + hh / 2
        d = math.hypot(cx - ANCHOR[0], cy - ANCHOR[1])
        if d > 55:
            out.append((d, float(cx), float(cy), "stone"))
    out.sort()
    return out


def drag(img, vx, vy, dist=MIN_DRAG):
    """朝 (vx,vy) 拖曳，沒動就換角度與長度重試。回傳 (dx, dy, moved, frame, 角度)。"""
    base = math.atan2(vy, vx)
    cur = img
    for off in (0, 45, -45, 90, -90, 135, -135, 180):
        a = base + math.radians(off)
        cvx, cvy = math.cos(a), math.sin(a)
        L = int(dist)
        adb.swipe(*DRAG, int(DRAG[0] + cvx * L), int(DRAG[1] + cvy * L), 620)
        time.sleep(1.25)
        cur = shot()
        sh = vision.shift_by_template(img, cur, threshold=0.65)
        if sh is None:
            s2 = vision.scroll(img, cur)
            dx, dy = s2[0], s2[1]
        else:
            dx, dy = sh[0], sh[1]
        if abs(dx) + abs(dy) > 25:
            return dx, dy, True, cur, off
    return 0.0, 0.0, False, cur, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("minutes", type=float, nargs="?", default=15.0)
    args = ap.parse_args()

    run = Path("captures") / time.strftime("local_%Y%m%d_%H%M%S")
    run.mkdir(parents=True, exist_ok=True)
    log = (run / "log.jsonl").open("w", encoding="utf-8")

    def rec(o):
        o["t"] = time.strftime("%H:%M:%S")
        log.write(json.dumps(o, ensure_ascii=False) + "\n")
        log.flush()
        print(json.dumps(o, ensure_ascii=False))

    hits = 0
    hp_start = None
    hp_now = None
    last_target_xy = None
    same_target = 0
    heading = 0.0                     # 沒目標時的行進方向
    deadline = time.time() + args.minutes * 60
    step = 0
    t0 = time.time()

    while time.time() < deadline:
        step += 1
        img = shot()
        if menu_share(img) > 0.10:
            adb.swipe(*DRAG, DRAG[0] - 380, DRAG[1], 900)
            time.sleep(1.0)
            continue

        text, _d = hp.read(img)
        if text:
            hp_now = text
            if hp_start is None:
                hp_start = text
        if text and text.startswith("0/"):
            rec({"step": step, "note": "生命值歸零 → 回帳篷休息", "hp": text, "hits": hits})
            for _i in range(60):
                s = shot()
                r = vision.find(s, REST_TPL, threshold=0.72)
                if r:
                    adb.tap(r[0], r[1])
                    time.sleep(1.5)
                    for _k in range(14):
                        time.sleep(0.6)
                        if vision.find(shot(), REST_TPL, threshold=0.72) is None:
                            break
                    break
                t = vision.find(s, TENT_TPL, threshold=0.82)
                if t:
                    n = max(abs(t[0] - ANCHOR[0]), abs(t[1] - ANCHOR[1]), 1)
                    drag(s, (t[0] - ANCHOR[0]) / n, (t[1] - ANCHOR[1]) / n, 250)
                else:
                    drag(s, 0, 1, 250)          # 帳篷在起始之地南側 → 往南找
            rec({"step": step, "note": "休息流程結束", "hits": hits, "hp": hp_now})
            continue

        cands = targets(img)
        if not cands:
            dx, dy, moved, img, off = drag(img, math.cos(heading), math.sin(heading))
            if not moved:
                heading += math.pi / 2       # 走不動 → 換方向
            rec({"step": step, "note": "沒目標 → 前進", "heading": round(math.degrees(heading)),
                 "moved": moved, "hits": hits})
            continue

        d, tx, ty, kind = cands[0]
        if last_target_xy and math.hypot(tx - last_target_xy[0], ty - last_target_xy[1]) < 60:
            same_target += 1
        else:
            same_target = 0
        last_target_xy = (tx, ty)
        if same_target >= 5 and len(cands) > 1:      # 同一個目標卡住 → 換下一個
            d, tx, ty, kind = cands[1]
            same_target = 0

        if d <= HIT_R:
            time.sleep(0.6)
            cur = shot()
            if vision.find(cur, DMG_TPL, threshold=0.70):
                hits += 1
                cv2.imwrite(str(run / f"hit_{hits:03d}.png"), cur)
            rec({"step": step, "note": "貼上目標", "kind": kind, "d": round(d), "hits": hits})
            heading = math.atan2(ty - ANCHOR[1], tx - ANCHOR[0]) + math.pi / 2   # 換個方向離開
            time.sleep(0.2)
            continue

        vx, vy = tx - ANCHOR[0], ty - ANCHOR[1]
        n = max(abs(vx), abs(vy), 1)
        mdx, mdy, moved, img, off = drag(img, vx / n, vy / n)
        rec({"step": step, "note": "走向目標", "kind": kind, "d": round(d), "moved": moved,
             "繞": off, "same": same_target, "hits": hits})

    mins = (time.time() - t0) / 60
    rate = ""
    if hp_start and hp_now:
        try:
            a = int(hp_start.split("/")[0]) if not hp_start.startswith("?") else None
            b = int(hp_now.split("/")[0]) if not hp_now.startswith("?") else None
            if a and b:
                rate = f"，生命值 {a}→{b}（約 {a-b} 次揮鎬 / {mins:.1f} 分鐘 = {(a-b)/mins:.1f} 次/分）"
        except Exception:
            pass
    log.close()
    print(f"done: {hits} 次拍到命中{rate}, 記錄在 {run}")


if __name__ == "__main__":
    main()

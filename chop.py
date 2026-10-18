"""自動砍素材 v7：用「傷害數字」判定命中 + 更好的走動策略。

v6 的問題：走路效率差（每步 4 張截圖很慢、撞到東西只會換方向）。
v7：大步走（最大 1.2 秒）、撞住就垂直滑開繞過去、每步只拍 2-3 張並檢查傷害數字。
只用拖曳（swipe），不點擊任何 UI。
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np

from pkauto import adb, detect, vision

ANCHOR = (720, 1400)
DRAG_ORIGIN = (600, 1650)
TREE_HSV_LO = (62, 175, 70)
TREE_HSV_HI = (98, 255, 235)
MENU_BG = np.array([255, 211, 143])
DMG_TPL = Path("captures/tpl_dmg151.png")


def awake() -> bool:
    out = adb._run(["shell", "dumpsys", "power"]).stdout.decode("utf-8", "replace")
    return "mWakefulness=Awake" in out


def unlock():
    adb.swipe(720, 1900, 1250, 1000, 400)
    time.sleep(1.2)


def norm_shot():
    return vision.normalize_brightness(adb.screencap())


def tree_mask(img, box=None):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(TREE_HSV_LO, np.uint8), np.array(TREE_HSV_HI, np.uint8))
    if box is None:
        return mask
    y1, y2, x1, x2 = box
    out = np.zeros_like(mask)
    out[y1:y2, x1:x2] = mask[y1:y2, x1:x2]
    return out


def menu_share(img) -> float:
    mid = img[560:2840, 60:1380]
    return float((np.abs(mid.astype(np.int16) - MENU_BG).max(axis=2) < 45).mean())


def directions(img, box=detect.BOX):
    mask = tree_mask(img, box)
    y1, y2, x1, x2 = box
    nx, ny = 7, 7
    cw, ch = (x2 - x1) // nx, (y2 - y1) // ny
    cands = []
    for gy in range(ny):
        for gx in range(nx):
            cx = x1 + gx * cw + cw // 2
            cy = y1 + gy * ch + ch // 2
            d = ((cx - ANCHOR[0]) ** 2 + (cy - ANCHOR[1]) ** 2) ** 0.5
            if d < 150 or d > 650:
                continue
            dens = float(mask[cy - ch // 2:cy + ch // 2, cx - cw // 2:cx + cw // 2].mean()) / 255
            if dens < 0.20:
                continue
            cands.append((dens - d / 2000.0, cx - ANCHOR[0], cy - ANCHOR[1], dens, d))
    cands.sort(reverse=True)
    out = []
    for _s, vx, vy, dens, d in cands[:6]:
        n = max(abs(vx), abs(vy), 1)
        out.append((vx / n, vy / n, dens, d))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("minutes", type=float, nargs="?", default=6.0)
    args = ap.parse_args()

    tpl = cv2.imread(str(DMG_TPL))
    if tpl is None:
        raise SystemExit(f"找不到傷害數字範本 {DMG_TPL}")

    run = Path("captures") / time.strftime("chop_%Y%m%d_%H%M%S")
    run.mkdir(parents=True, exist_ok=True)
    log = (run / "log.jsonl").open("w", encoding="utf-8")

    def rec(obj):
        obj["t"] = time.strftime("%H:%M:%S")
        log.write(json.dumps(obj, ensure_ascii=False) + "\n")
        log.flush()
        print(json.dumps(obj, ensure_ascii=False))

    deadline = time.time() + args.minutes * 60
    step = hits = 0
    blocked = 0
    dirs = []
    last_hit_ts = None
    last_dir = (0, -1)

    while time.time() < deadline:
        step += 1
        if not awake():
            rec({"step": step, "note": "睡著→解鎖"})
            unlock()
            continue

        a = norm_shot()
        if menu_share(a) > 0.10:
            rec({"step": step, "note": "選單底色→離開"})
            adb.swipe(*DRAG_ORIGIN, DRAG_ORIGIN[0] - 380, DRAG_ORIGIN[1], 900)
            time.sleep(1.0)
            continue

        if not dirs:
            dirs = directions(a)
        if not dirs:
            rec({"step": step, "note": "附近沒有樹→換方向巡"})
            ang = (step * 97) % 360
            adb.swipe(*DRAG_ORIGIN, int(DRAG_ORIGIN[0] + 300 * np.cos(np.radians(ang))),
                      int(DRAG_ORIGIN[1] + 200 * np.sin(np.radians(ang))), 800)
            time.sleep(0.8)
            continue

        vx, vy, dens, dist = dirs[0]
        ms_walk = int(min(1200, max(500, dist * 1.2)))
        adb.swipe(*DRAG_ORIGIN, int(DRAG_ORIGIN[0] + vx * 340), int(DRAG_ORIGIN[1] + vy * 340), ms_walk)
        time.sleep(0.15)
        last_dir = (vx, vy)

        found = None
        frames = []
        for k in range(3):
            b = norm_shot()
            frames.append(b)
            m = vision.find(b, tpl, threshold=0.72)
            if m:
                found = m
                break
            if k == 0:
                time.sleep(0.3)

        b = frames[-1]
        dx, dy, r = vision.scroll(a, b)
        moved = abs(dx) > 8 or abs(dy) > 8

        if found:
            hits += 1
            now = time.time()
            dt_prev = None if last_hit_ts is None else round(now - last_hit_ts, 1)
            last_hit_ts = now
            cv2.imwrite(str(run / f"hit_{hits:03d}.png"), b)
            rec({"step": step, "note": "命中", "at": [found[0], found[1]],
                 "score": round(found[2], 2), "距上次命中(秒)": dt_prev, "hits": hits})
            blocked = 0
            continue

        if moved:
            blocked = 0
        else:
            blocked += 1
            # 撞住 → 垂直滑開繞過去（樹很小，側滑通常能繞過）
            px, py = -last_dir[1], last_dir[0]
            side = 1 if (step % 2 == 0) else -1
            adb.swipe(*DRAG_ORIGIN, int(DRAG_ORIGIN[0] + px * side * 300),
                      int(DRAG_ORIGIN[1] + py * side * 300), 700)
            time.sleep(0.6)
            if blocked >= 2:
                dirs = dirs[1:]
                blocked = 0

        rec({"step": step, "dir": [round(vx, 2), round(vy, 2)], "dens": round(dens, 2),
             "dist": int(dist), "scroll": [round(dx, 1), round(dy, 1), round(r, 2)],
             "moved": moved, "hits": hits})

    log.close()
    print(f"done: {step} 步, {hits} 次命中, 記錄在 {run}")


if __name__ == "__main__":
    main()

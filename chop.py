"""自動砍素材 v10：森林巡邏 + 命中判定（傷害數字）+ 地標判斷在不在起始之地（不在就傳送回家）。

在 v9（每步重選方向、走不動的方向黑名單、傷害數字當命中）之上加：
- 地標：畫面中央區找到「帳篷」或「SHOP」範本＝還在起始之地。
- 連續 4 步都看不到地標 → 用傳送石回家（點右側藍色愛心 → 選單比對「起始之地」格子 → 點它）。
只用拖曳＋（使用者授權的）傳送石點擊；不點其他任何 UI。
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
DRAG_ORIGIN = (720, 2600)
TREE_HSV_LO = (62, 175, 70)
TREE_HSV_HI = (98, 255, 235)
MENU_BG = np.array([255, 211, 143])
HEART = (1275, 1710)
DMG_TPL = Path("captures/tpl_dmg151.png")
TENT_TPL = Path("captures/tpl_tent.png")
SHOP_TPL = Path("captures/tpl_shop.png")
TILE_TPL = Path("captures/tpl_tile_start.png")
LANDMARK_BOX = (650, 2200, 150, 1290)   # y1,y2,x1,x2 只在這區找地標


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
    nx, ny = 9, 9
    cw, ch = (x2 - x1) // nx, (y2 - y1) // ny
    cands = []
    for gy in range(ny):
        for gx in range(nx):
            cx = x1 + gx * cw + cw // 2
            cy = y1 + gy * ch + ch // 2
            d = ((cx - ANCHOR[0]) ** 2 + (cy - ANCHOR[1]) ** 2) ** 0.5
            if d < 140 or d > 700:
                continue
            dens = float(mask[cy - ch // 2:cy + ch // 2, cx - cw // 2:cx + cw // 2].mean()) / 255
            if dens < 0.18:
                continue
            cands.append((round(dens - d / 2200.0, 4), cx - ANCHOR[0], cy - ANCHOR[1], dens, d))
    cands.sort(reverse=True)
    out = []
    for _s, vx, vy, dens, d in cands[:6]:
        n = max(abs(vx), abs(vy), 1)
        out.append((vx / n, vy / n, dens, d))
    return out


class Landmarks:
    def __init__(self):
        self.tent = cv2.imread(str(TENT_TPL))
        self.shop = cv2.imread(str(SHOP_TPL))
        self.tile = cv2.imread(str(TILE_TPL))
        for name, t in [("tent", self.tent), ("shop", self.shop), ("tile", self.tile)]:
            if t is None:
                raise SystemExit(f"缺少範本 {name}")

    def in_area(self, img):
        y1, y2, x1, x2 = LANDMARK_BOX
        reg = img[y1:y2, x1:x2]
        for tpl in (self.tent, self.shop):
            r = vision.find(reg, tpl, threshold=0.78)
            if r:
                return r
        return None

    def teleport_home(self, rec) -> bool:
        """點傳送石 → 選單找『起始之地』 → 點它。成功回 True。"""
        adb.tap(*HEART)
        time.sleep(1.8)
        menu = norm_shot()
        if menu_share(menu) < 0.10:
            rec({"note": "點愛心後沒開選單"})
            return False
        for attempt in range(5):
            hit = vision.find(menu, self.tile, threshold=0.75)
            if hit:
                x, y, score = hit
                rec({"note": "傳送回家", "tile_at": [x, y], "score": round(score, 2)})
                adb.tap(x, y)
                time.sleep(3.0)
                return True
            adb.swipe(720, 2350, 720, 1500, 700)
            time.sleep(1.0)
            menu = norm_shot()
        rec({"note": "選單找不到起始之地 → 放棄傳送"})
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("minutes", type=float, nargs="?", default=8.0)
    args = ap.parse_args()

    lm = Landmarks()
    tpl = cv2.imread(str(DMG_TPL))
    if tpl is None:
        raise SystemExit("缺少傷害數字範本")

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
    out_of_area = 0
    teleports = 0
    last_hit_ts = None
    prev = norm_shot()
    last_dir = (0.0, -1.0)
    no_move = 0
    tried = []

    while time.time() < deadline:
        step += 1
        if not awake():
            rec({"step": step, "note": "睡著→解鎖"})
            unlock()
            continue

        if menu_share(prev) > 0.10:
            rec({"step": step, "note": "選單底色→拖曳離開"})
            adb.swipe(*DRAG_ORIGIN, DRAG_ORIGIN[0] - 380, DRAG_ORIGIN[1], 900)
            time.sleep(1.0)
            prev = norm_shot()
            continue

        m = vision.find(prev, tpl, threshold=0.72)
        if m:
            hits += 1
            now = time.time()
            dt_prev = None if last_hit_ts is None else round(now - last_hit_ts, 1)
            last_hit_ts = now
            cv2.imwrite(str(run / f"hit_{hits:03d}.png"), prev)
            rec({"step": step, "note": "命中", "at": [m[0], m[1]], "score": round(m[2], 2),
                 "距上次命中(秒)": dt_prev, "hits": hits})

        if lm.in_area(prev):
            out_of_area = 0
        else:
            out_of_area += 1
            if out_of_area >= 4:
                teleports += 1
                lm.teleport_home(rec)
                out_of_area = 0
                tried = []
                prev = norm_shot()
                continue

        cands = [(vx, vy, dens, d) for vx, vy, dens, d in directions(prev) if (vx, vy) not in tried]
        if not cands:
            ang = (step * 71) % 360
            vx, vy = float(np.cos(np.radians(ang))), float(np.sin(np.radians(ang)))
            action = "探索"
        else:
            vx, vy, dens, d = cands[0]
            action = "往樹走"

        adb.swipe(*DRAG_ORIGIN, int(DRAG_ORIGIN[0] + vx * 340), int(DRAG_ORIGIN[1] + vy * 340), 900)
        time.sleep(0.35)
        cur = norm_shot()
        dx, dy, r = vision.scroll(prev, cur)
        moved = abs(dx) > 8 or abs(dy) > 8
        if moved:
            no_move = 0
            tried = []
        else:
            no_move += 1
            tried.append((vx, vy))
            if no_move >= 2:
                tried = []
                no_move = 0

        rec({"step": step, "action": action, "dir": [round(vx, 2), round(vy, 2)],
             "scroll": [round(dx, 1), round(dy, 1), round(r, 2)], "moved": moved,
             "in_area": bool(lm.in_area(cur)), "hits": hits, "teleports": teleports})
        prev = cur

    log.close()
    print(f"done: {step} 步, {hits} 命中, {teleports} 次傳送回家, 記錄在 {run}")


if __name__ == "__main__":
    main()

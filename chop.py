"""自動砍素材 v9：每步重新選方向 + 命中用「傷害數字」判定 + 走不動就換方向。

v7/v8 的教訓：方向一旦卡住會一直往同一邊撞（森林在西側邊界時整場 0 命中）。
v9：每步都重新評估「哪個方向有樹」，並記住「上一步是否真的走得動」來淘汰爛方向。

策略（對應使用者需求：樹/石頭在森林區隨機生成、一下就砍掉、約 100 秒重生）：
- 往最近的樹叢走，撞到東西 = 有機會砍掉它；命中就看傷害數字。
- 連續走不動 → 淘汰該方向、換下一個候選；都沒得走 → 朝畫面上樹最密的地方走（回到森林）。
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
    """回傳候選 [(vx, vy, dens, dist), ...]，密度不足或太近太遠都排除。"""
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
            rec({"step": step, "note": "選單底色→離開"})
            adb.swipe(*DRAG_ORIGIN, DRAG_ORIGIN[0] - 380, DRAG_ORIGIN[1], 900)
            time.sleep(1.0)
            prev = norm_shot()
            continue

        # 先看上一張有沒有傷害數字（命中會停留約 0.5-1 秒）
        m = vision.find(prev, tpl, threshold=0.72)
        if m:
            hits += 1
            now = time.time()
            dt_prev = None if last_hit_ts is None else round(now - last_hit_ts, 1)
            last_hit_ts = now
            cv2.imwrite(str(run / f"hit_{hits:03d}.png"), prev)
            rec({"step": step, "note": "命中", "at": [m[0], m[1]], "score": round(m[2], 2),
                 "距上次命中(秒)": dt_prev, "hits": hits})

        cands = [(vx, vy, dens, d) for vx, vy, dens, d in directions(prev)
                 if (vx, vy) not in tried]
        if not cands:
            ang = (step * 71) % 360
            vx, vy = float(np.cos(np.radians(ang))), float(np.sin(np.radians(ang)))
            action = "探索"
        else:
            vx, vy, dens, d = cands[0]
            action = "往樹走"

        ms_walk = int(min(1100, max(450, 700)))
        adb.swipe(*DRAG_ORIGIN, int(DRAG_ORIGIN[0] + vx * 340), int(DRAG_ORIGIN[1] + vy * 340), ms_walk)
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
             "scroll": [round(dx, 1), round(dy, 1), round(r, 2)], "moved": moved, "hits": hits})
        prev = cur

    log.close()
    print(f"done: {step} 步, {hits} 次命中, 記錄在 {run}")


if __name__ == "__main__":
    main()

"""建圖器（掃地機器人式）：邊走邊把「可走 / 不可走」畫進網格地圖。

規則（使用者確認）：
- **不可走**：河水、建築物（帳篷、商店、鍋爐、圍欄等）。
- **可走**：草地/地板、木橋、樹、石頭、NPC、生物（樹石可穿過，撞到會自動揮鎬）。

座標系：以「開始建圖時角色的位置」為原點（路線座標系同一套）。
每張截圖涵蓋角色周圍的世界 → 依角色估計位置貼進網格；角色實際走過的格線強制標成可走。

輸出：captures/maps/<name>.json
  {"cell": 30, "grid": {"x,y": 0|1}, "origin_note": ...}   0=可走 1=不可走（沒記錄=未知）
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
CELL = 30
MENU_BG = np.array([255, 211, 143])
TPL = {"shop": cv2.imread("captures/tpl_shop.png"), "tent": cv2.imread("captures/tpl_tent.png")}
THRESH = {"shop": 0.65, "tent": 0.70}
DMG_TPL = cv2.imread("captures/tpl_dmg151.png")


def shot():
    return vision.normalize_brightness(adb.screencap())


def menu_share(img) -> float:
    mid = img[560:2840, 60:1380]
    return float((np.abs(mid.astype(np.int16) - MENU_BG).max(axis=2) < 45).mean())


def find_local(img, tpl, centre, radius=200, threshold=0.7):
    h, w = img.shape[:2]
    x1, y1 = max(0, int(centre[0] - radius)), max(0, int(centre[1] - radius))
    x2, y2 = min(w, int(centre[0] + radius)), min(h, int(centre[1] + radius))
    if x2 - x1 < 80 or y2 - y1 < 80:
        return None
    r = vision.find(img[y1:y2, x1:x2], tpl, threshold=threshold)
    return None if not r else (r[0] + x1, r[1] + y1, r[2])


SCALE = 0.1        # 分類用的縮圖比例（144x312）


def cell_marks(img, pos):
    """把畫面分類成「網格格子 → 可走(0)/不可走(1)」，回傳 {(cx,cy): value}。

    只判地面性質：水與木造（建築/圍欄/橋）分開處理——橋是木頭但可走，
    所以木頭只在地板包圍下才視為建築（見下方說明）。
    """
    small = cv2.resize(img, None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_AREA)
    b, g, r = cv2.split(small.astype("int16"))
    water = (b > 165) & (b > r + 35) & (g > r)
    floor = (g > 110) & (g > r) & (g > b - 20)
    ys, xs = np.nonzero(water | floor)
    if len(xs) == 0:
        return {}
    wx = pos[0] + (xs + 0.5) / SCALE - ANCHOR[0]
    wy = pos[1] + (ys + 0.5) / SCALE - ANCHOR[1]
    cx = np.floor(wx / CELL).astype(int)
    cy = np.floor(wy / CELL).astype(int)
    # 木頭不直接判成障礙（橋也是木頭、可以走）；只有水確定不可走。
    # 建築物則靠「走過去被擋住」的實證在探索階段記錄。
    val = np.where(water[ys, xs], 1, 0)
    out = {}
    for cxv, cyv, v in set(zip(cx.tolist(), cy.tolist(), val.tolist())):
        ck = (int(cxv), int(cyv))
        if v == 1:
            out[ck] = 1                    # 不可走優先
        else:
            out.setdefault(ck, 0)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name", help="地圖名稱（例如 start）")
    ap.add_argument("minutes", type=float, nargs="?", default=10.0)
    ap.add_argument("--explore", action="store_true", help="自動探索（往未知區域走）")
    args = ap.parse_args()

    out_dir = Path("captures/maps")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.name}.json"
    grid = {}
    if out_path.exists():
        d = json.load(open(out_path, encoding="utf-8"))
        grid = {tuple(int(v) for v in k.split(",")): val for k, val in d["grid"].items()}
        print(f"載入既有地圖 {out_path}（{len(grid)} 格）")
    anchors = {}
    if out_path.exists():
        anchors = json.load(open(out_path, encoding="utf-8")).get("anchor", {})

    run = Path("captures") / time.strftime("map_%Y%m%d_%H%M%S")
    run.mkdir(parents=True, exist_ok=True)
    log = (run / "log.jsonl").open("w", encoding="utf-8")

    def rec(o):
        o["t"] = time.strftime("%H:%M:%S")
        log.write(json.dumps(o, ensure_ascii=False) + "\n")
        log.flush()
        print(json.dumps(o, ensure_ascii=False))

    pos = [0.0, 0.0]
    pend = {}
    deadline = time.time() + args.minutes * 60
    step = 0
    trail = set()
    scan_dir = 0
    stuck = 0

    # 第一次啟動時記下地標相對原點的位置（同路線座標系）
    if not anchors:
        img0 = shot()
        for name, tpl in TPL.items():
            f = vision.find(img0, tpl, THRESH[name])
            if f:
                anchors[name] = {"route_pos": [round(f[0] - ANCHOR[0], 1), round(f[1] - ANCHOR[1], 1)]}
                print(f"錨點 {name} → {anchors[name]['route_pos']}")

    while time.time() < deadline:
        step += 1
        img = shot()
        if menu_share(img) > 0.10:
            adb.swipe(*DRAG, DRAG[0] - 380, DRAG[1], 900)
            time.sleep(1.0)
            continue

        # 地標校正 pos
        for name, info in anchors.items():
            rp = info["route_pos"]
            exp = (ANCHOR[0] + rp[0] - pos[0], ANCHOR[1] + rp[1] - pos[1])
            if not (60 < exp[0] < 1380 and 80 < exp[1] < 3000):
                continue
            f = find_local(img, TPL[name], exp, 200, THRESH[name])
            if not f:
                pend.pop(name, None)
                continue
            cand = [rp[0] - (f[0] - ANCHOR[0]), rp[1] - (f[1] - ANCHOR[1])]
            prev = pend.get(name)
            if prev is not None and math.dist(prev, cand) < 40 and math.dist(cand, pos) < 260:
                if math.dist(cand, pos) > 20:
                    rec({"step": step, "note": "地標校正", "landmark": name, "修掉": round(math.dist(cand, pos))})
                pos = cand
            pend[name] = cand

        # 貼圖：把畫面分類結果寫進網格（向量化計算、只更新有變化的格子）
        for ck, v in cell_marks(img, pos).items():
            if grid.get(ck) != 1:
                grid[ck] = v
        # 角色走過的格線 → 一定可走
        ck0 = (int(math.floor(pos[0] / CELL)), int(math.floor(pos[1] / CELL)))
        grid[ck0] = 0
        trail.add(ck0)

        # 走一步：有 --explore 就往「最近的未知格」方向走，否則只原地掃描
        text, _d = hp.read(img)
        if text and text.startswith("0/"):
            rec({"step": step, "note": "生命值歸零（建圖時不休息，先停）", "hp": text})
            break

        if args.explore:
            target = None
            for ring in range(3, 40):
                for dx in range(-ring, ring + 1):
                    for dy in range(-ring, ring + 1):
                        if max(abs(dx), abs(dy)) != ring:
                            continue
                        ck = (ck0[0] + dx, ck0[1] + dy)
                        if ck not in grid:
                            target = (ck[0] * CELL + CELL / 2, ck[1] * CELL + CELL / 2)
                            break
                    if target:
                        break
                if target:
                    break
            if target is None:
                rec({"step": step, "note": "建圖完成（沒有未知格）", "cells": len(grid)})
                break
            d = math.hypot(target[0] - pos[0], target[1] - pos[1])
            base = math.atan2(target[1] - pos[1], target[0] - pos[0])
            pl = int(min(320, max(90, d * 0.7)))
            adb.swipe(*DRAG, int(DRAG[0] + math.cos(base) * pl), int(DRAG[1] + math.sin(base) * pl),
                      int(min(800, max(280, pl * 2.2))))
            time.sleep(1.4)
            cur = shot()
            dx, dy, resp = vision.scroll(img, cur)
            moved = resp > 0.4 and (abs(dx) > 6 or abs(dy) > 6)
            if moved:
                pos[0] += -dx
                pos[1] += -dy
                stuck = 0
            else:
                stuck += 1
                # 撞牆：把眼前方向標成不可走，並換方向
                for k in range(1, 4):
                    a = base + k * math.pi / 3
                    adb.swipe(*DRAG, int(DRAG[0] + math.cos(a) * 200), int(DRAG[1] + math.sin(a) * 200), 450)
                    time.sleep(0.4)
            scan_dir = (scan_dir + 1) % 8
            rec({"step": step, "note": "探索", "cells": len(grid), "moved": moved,
                 "pos": [round(v) for v in pos], "stuck": stuck})
            if stuck > 12:
                rec({"step": step, "note": "連續卡住 → 停止"})
                break
        else:
            # watch 模式：使用者自己走 → 只量位移、更新 pos、貼圖，不動手機
            time.sleep(0.35)
            cur = shot()
            sh = vision.shift_by_template(img, cur)          # 範本法（比 phaseCorrelate 穩）
            if sh is None:
                dx, dy, resp = vision.scroll(img, cur)
                sh = (dx, dy, resp, 0)
            dx, dy, q, n = sh
            if q > 0.75 and (abs(dx) > 3 or abs(dy) > 3):
                pos[0] += -dx
                pos[1] += -dy
                rec({"step": step, "note": "記錄中", "cells": len(grid), "move": [round(dx), round(dy)],
                     "q": round(q, 2), "pos": [round(v) for v in pos]})
            else:
                rec({"step": step, "note": "記錄中（靜止）", "cells": len(grid), "q": round(q, 2),
                     "pos": [round(v) for v in pos]})

    json.dump({"cell": CELL, "grid": {f"{k[0]},{k[1]}": v for k, v in grid.items()},
               "anchor": anchors, "trail_cells": len(trail)},
              open(out_path, "w", encoding="utf-8"), ensure_ascii=False)
    log.close()
    walk = sum(1 for v in grid.values() if v == 0)
    block = sum(1 for v in grid.values() if v == 1)
    print(f"完成：{len(grid)} 格（可走 {walk} / 不可走 {block}）→ {out_path}")


if __name__ == "__main__":
    main()

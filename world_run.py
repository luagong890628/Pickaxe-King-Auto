"""世界地圖定位主程式：邊走邊建立世界地圖，並用它持續修正自己位置。

兩種模式：
- `--watch`：使用者自己走，程式只觀察（不碰手機）→ 建圖。
- （預設）自己走：每次往前/探索一步，用「地圖比對」修正位置後再走下一步。

輸出路徑：captures/world/<name>_map.png 與 <name>.npz（地圖資料）
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
from pkauto import worldmap as wm

ANCHOR = (720, 1400)
DRAG = (720, 2000)
MENU_BG = np.array([255, 211, 143])
CELL = wm.CELL


def shot():
    return vision.normalize_brightness(adb.screencap())


def menu_share(img) -> float:
    mid = img[560:2840, 60:1380]
    return float((np.abs(mid.astype(np.int16) - MENU_BG).max(axis=2) < 45).mean())


def step_delta(img, cur):
    """量這一步的畫面位移（預測用）。回傳 (dx, dy, q)。"""
    sh = vision.shift_by_template(img, cur, threshold=0.65)
    if sh is None:
        dx, dy, resp = vision.scroll(img, cur)
        return dx, dy, resp
    return sh[0], sh[1], sh[2]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("minutes", type=float, nargs="?", default=10.0)
    ap.add_argument("--watch", action="store_true", help="只觀察（使用者自己走）")
    ap.add_argument("--radius", type=int, default=8, help="定位搜尋半徑（格）")
    args = ap.parse_args()

    out_dir = Path("captures/world")
    out_dir.mkdir(parents=True, exist_ok=True)
    run = Path("captures") / time.strftime("world_%Y%m%d_%H%M%S")
    run.mkdir(parents=True, exist_ok=True)
    log = (run / "log.jsonl").open("w", encoding="utf-8")

    def rec(o):
        o["t"] = time.strftime("%H:%M:%S")
        log.write(json.dumps(o, ensure_ascii=False) + "\n")
        log.flush()
        print(json.dumps(o, ensure_ascii=False))

    world: dict = {}
    pos = [0.0, 0.0]
    prev_img = shot()
    wm.update(world, wm.observe(prev_img), pos)
    rec({"step": 0, "note": "start", "cells": len(world)})

    deadline = time.time() + args.minutes * 60
    step = 0
    walk_dir = 0
    stuck = 0

    while time.time() < deadline:
        step += 1
        time.sleep(0.6 if args.watch else 0.2)
        img = shot()

        if menu_share(img) > 0.10:
            if not args.watch:
                adb.swipe(*DRAG, DRAG[0] - 380, DRAG[1], 900)
            time.sleep(1.0)
            continue

        dx, dy, q = step_delta(prev_img, img)
        moved = q > 0.7 and (abs(dx) > 5 or abs(dy) > 5)
        if moved:
            pos[0] += -dx
            pos[1] += -dy

        obs = wm.observe(img)
        newpos, err, used = wm.localize(obs, world, pos, radius_cells=args.radius)
        shift = math.dist(newpos, pos)
        if used >= 25:
            pos = [newpos[0], newpos[1]]
        wm.update(world, obs, pos)
        rec({"step": step, "note": "觀測", "moved": moved, "q": round(q, 2),
             "定位格數": used, "誤差": None if err is None else round(err, 3),
             "修正": round(shift), "pos": [round(v) for v in pos], "cells": len(world)})

        if not args.watch:
            # 自己走：朝「最近的未知格」前進（掃地機器人式探索）
            pcx = int(math.floor(pos[0] / CELL))
            pcy = int(math.floor(pos[1] / CELL))
            tgt = None
            for ring in range(2, 25):
                for a in range(0, 360, 30):
                    cx = pcx + int(round(ring * math.cos(math.radians(a))))
                    cy = pcy + int(round(ring * math.sin(math.radians(a))))
                    if (cx, cy) not in world:
                        tgt = (cx, cy)
                        break
                if tgt:
                    break
            if tgt is None:
                rec({"step": step, "note": "建圖完成"})
                break
            gx, gy = tgt[0] * CELL + CELL / 2, tgt[1] * CELL + CELL / 2
            n = max(abs(gx - pos[0]), abs(gy - pos[1]), 1)
            vx, vy = (gx - pos[0]) / n, (gy - pos[1]) / n
            adb.swipe(*DRAG, int(DRAG[0] + vx * 320), int(DRAG[1] + vy * 320), 700)
            time.sleep(1.3)
            if not moved:
                stuck += 1
                vx, vy = -vy, vx                     # 撞牆 → 側移
                # 拖曳長度/時間要有下限，否則遊戲會當成「點擊」（曾因此誤開商店/訓練場）
                adb.swipe(*DRAG, int(DRAG[0] + vx * 320), int(DRAG[1] + vy * 320), 700)
                time.sleep(0.5)
                if stuck > 15:
                    rec({"step": step, "note": "連續卡住 → 停止"})
                    break
            else:
                stuck = 0

        prev_img = img
        if step % 40 == 0:
            wm.render(world, out_dir / f"{args.name}_map.png")

    wm.render(world, out_dir / f"{args.name}_map.png")
    np.savez_compressed(out_dir / f"{args.name}.npz",
                        keys=np.array([f"{k[0]},{k[1]}" for k in world]),
                        vals=np.array([world[k] for k in world]))
    log.close()
    print(f"done: {len(world)} 格 → {out_dir}/{args.name}_map.png")


if __name__ == "__main__":
    main()

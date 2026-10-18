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
DRAG = (720, 2600)          # 拖曳起點（實測：越靠下越有效；2600 是 4/4 成功的點）
MENU_BG = np.array([255, 211, 143])
CELL = wm.CELL


def drag(img, vx, vy, dist=250):
    """朝 (vx,vy) 拖曳；沒動就換角度（±45/±90/±135/180°）與長度重試（自動繞障礙）。

    實測：拖曳本身有效（8 方向有 6 個能動）；量到 0 幾乎都是「那個方向被擋住」。
    回傳 (dx, dy, moved, frame, 用了幾度)。
    """
    import math as _m
    base = _m.atan2(vy, vx)
    cur = img
    for off in (0, 45, -45, 90, -90, 135, -135, 180):
        a = base + _m.radians(off)
        cvx, cvy = _m.cos(a), _m.sin(a)
        for k in (1.0, 0.65):
            L = max(90, int(dist * k))
            adb.swipe(*DRAG, int(DRAG[0] + cvx * L), int(DRAG[1] + cvy * L), 600)
            time.sleep(1.3)
            cur = shot()
            sh = vision.shift_by_template(img, cur, threshold=0.65)
            if sh is None:
                s2 = vision.scroll(img, cur)
                dx, dy, q = s2[0], s2[1], s2[2]
            else:
                dx, dy, q = sh[0], sh[1], sh[2]
            if abs(dx) + abs(dy) > 25:
                return dx, dy, True, cur, off
    return 0.0, 0.0, False, cur, None


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
        newpos, err, used, second = wm.localize(obs, world, pos, radius_cells=args.radius)
        shift = math.dist(newpos, pos)
        # 只有「最佳明顯勝出（有辨別力）、誤差夠低、修正幅度合理」才採用；
        # 否則沿用位移量測的預測值（避免地圖稀疏時被釘在同一格）。
        decided = (err is not None and used >= 60 and err < 0.06 and shift < 220
                   and (second is None or err < second * 0.75))
        if decided:
            pos = [newpos[0], newpos[1]]
        wm.update(world, obs, pos)
        rec({"step": step, "note": "觀測", "moved": moved, "q": round(q, 2),
             "定位格數": used, "誤差": None if err is None else round(err, 3),
             "次佳": None if second is None else round(second, 3), "採用": decided,
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
            mdx, mdy, moved2, _cur, used_off = drag(img, vx, vy)
            img = _cur                                # 之後的位移量測從拖曳後那張開始（避免重複計算）
            if moved2:
                pos[0] += -mdx
                pos[1] += -mdy
                stuck = 0
            else:
                stuck += 1
                drag(img, -vy, vx)                   # 撞牆 → 側移繞開
                if stuck > 15:
                    rec({"step": step, "note": "連續卡住 → 停止"})
                    break

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

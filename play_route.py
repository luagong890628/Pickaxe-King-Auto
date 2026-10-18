"""重播路線（關鍵幀版）：走到每一張關鍵幀的畫面 → 下一個 → … 走完一圈再從頭。

核心：每一步都用「現在畫面 vs 目標關鍵幀」算位移，往目標方向走一步。
因為每次都重新比對，誤差不會累積（不像純座標推算）。
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
SCALE = 0.5
REACH = 42          # 殘餘位移小於這個就算到達
DMG_TPL = cv2.imread("captures/tpl_dmg151.png")


def shot_small():
    img = vision.normalize_brightness(adb.screencap())
    return img, cv2.resize(img, None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_AREA)


def menu_share(img) -> float:
    mid = img[560:2840, 60:1380]
    return float((np.abs(mid.astype(np.int16) - MENU_BG).max(axis=2) < 45).mean())


def shift_to(cur_small, tgt_small):
    """現在畫面 → 目標畫面 的位移（大圖座標）。"""
    sh = vision.shift_by_template(cv2.resize(cur_small, None, fx=2, fy=2),
                                  cv2.resize(tgt_small, None, fx=2, fy=2))
    if sh is None:
        dx, dy, resp = vision.scroll(cur_small, tgt_small)
        return dx / SCALE, dy / SCALE, resp
    return sh[0], sh[1], sh[2]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("minutes", type=float, nargs="?", default=15.0)
    ap.add_argument("--passes", type=int, default=0)
    args = ap.parse_args()

    d = json.load(open(f"captures/routes/{args.name}/meta.json", encoding="utf-8"))
    frames = [cv2.imread(f"captures/routes/{args.name}/{f['file']}") for f in d["frames"]]
    print(f"路線 {args.name}：{len(frames)} 幀")

    run = Path("captures") / time.strftime("play_%Y%m%d_%H%M%S")
    run.mkdir(parents=True, exist_ok=True)
    log = (run / "log.jsonl").open("w", encoding="utf-8")

    def rec(o):
        o["t"] = time.strftime("%H:%M:%S")
        log.write(json.dumps(o, ensure_ascii=False) + "\n")
        log.flush()
        print(json.dumps(o, ensure_ascii=False))

    hits = 0
    idx = 0
    passes = 0
    step = 0
    stalled = 0
    deadline = time.time() + args.minutes * 60

    while time.time() < deadline:
        step += 1
        img, small = shot_small()
        if menu_share(img) > 0.10:
            adb.swipe(*DRAG, DRAG[0] - 380, DRAG[1], 900)
            time.sleep(1.0)
            continue

        text, _h = hp.read(img)
        if text and text.startswith("0/"):
            rec({"step": step, "note": "生命值歸零 → 停止（休息流程另外處理）", "hp": text, "hits": hits})
            break

        tgt = frames[idx]
        dx, dy, q = shift_to(small, tgt)
        dist = math.hypot(dx, dy)
        if dist <= REACH:
            time.sleep(0.55)                     # 停一下讓揮鎬砍旁邊的樹
            cur = vision.normalize_brightness(adb.screencap())
            if vision.find(cur, DMG_TPL, threshold=0.70):
                hits += 1
                cv2.imwrite(str(run / f"hit_{hits:03d}.png"), cur)
            rec({"step": step, "note": "到幀", "idx": idx, "殘餘": round(dist), "q": round(q, 2),
                 "hits": hits})
            idx += 1
            if idx >= len(frames):
                idx = 0
                passes += 1
                rec({"step": step, "note": "完成一圈", "passes": passes, "hits": hits})
                if args.passes and passes >= args.passes:
                    break
            continue

        # 往目標走一步：畫面要往 (dx,dy) 移 → 角色往 (-dx,-dy) 走
        n = max(abs(dx), abs(dy), 1)
        vx, vy = -dx / n, -dy / n
        pl = int(min(360, max(90, dist * 0.9)))
        adb.swipe(*DRAG, int(DRAG[0] + vx * pl), int(DRAG[1] + vy * pl),
                  int(min(800, max(280, pl * 2.2))))
        time.sleep(1.4)
        after = vision.normalize_brightness(adb.screencap())
        if vision.find(after, DMG_TPL, threshold=0.70):
            hits += 1
            cv2.imwrite(str(run / f"hit_{hits:03d}.png"), after)
        _, small2 = after, cv2.resize(after, None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_AREA)
        dx2, dy2, q2 = shift_to(small2, tgt)
        improved = math.hypot(dx2, dy2) < dist - 15
        stalled = 0 if improved else stalled + 1
        if stalled >= 4:
            rec({"step": step, "note": "走不到 → 跳過此幀", "idx": idx, "殘餘": round(dist)})
            idx = (idx + 1) % len(frames)
            stalled = 0
            continue
        rec({"step": step, "note": "走", "idx": idx, "前": round(dist), "後": round(math.hypot(dx2, dy2)),
             "q": round(q, 2), "hits": hits})

    log.close()
    print(f"done: {passes} 圈, {hits} 命中, 記錄在 {run}")


if __name__ == "__main__":
    main()

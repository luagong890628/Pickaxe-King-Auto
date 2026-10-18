"""巡生成點砍素材（v11）：照使用者標註的生成點清單走，一點一點砍。

核心：
- 生成點清單存成「相對地標的位移」（起始之地＝帳篷、小村莊＝黃金樹），
  所以任何時候只要在畫面找到地標，就能算出每個生成點現在在畫面的哪裡。
- 走法：每次選「離我最近的未走過的點」走過去 → 到點附近停一下（讓揮鎬完成）→ 記錄有沒有命中 → 下一點。
- 命中判定＝傷害數字範本；走完整區就結束（或依參數傳送）。
只用拖曳；除了傳送石與「在小屋裡休息」外不點任何 UI。
"""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import cv2
import numpy as np

from pkauto import adb, vision

ANCHOR = (720, 1400)
DRAG_ORIGIN = (720, 2600)
MENU_BG = np.array([255, 211, 143])
DMG_TPL = Path("captures/tpl_dmg151.png")
TENT_TPL = Path("captures/tpl_tent.png")
POINTS = Path("captures/spawn_points.json")
REACH = 85.0          # 距目標小於這個像素就算「到了」
PAUSE = 0.7           # 到點後停多久讓揮鎬完成


def awake() -> bool:
    out = adb._run(["shell", "dumpsys", "power"]).stdout.decode("utf-8", "replace")
    return "mWakefulness=Awake" in out


def unlock():
    adb.swipe(720, 1900, 1250, 1000, 400)
    time.sleep(1.2)


def norm_shot():
    return vision.normalize_brightness(adb.screencap())


def try_hit(tpl, run, hits):
    """停下來連拍幾張找傷害數字；沒有就前後左右輕推再找。"""
    for k in range(3):
        s = norm_shot()
        m = vision.find(s, tpl, threshold=0.70)
        if m:
            hits[0] += 1
            cv2.imwrite(str(run / f"hit_{hits[0]:03d}.png"), s)
            return True, s
        time.sleep(0.22)
    for ddx, ddy in ((0, -90), (0, 90), (-90, 0), (90, 0)):
        adb.swipe(*DRAG_ORIGIN, DRAG_ORIGIN[0] + ddx, DRAG_ORIGIN[1] + ddy, 500)
        time.sleep(0.3)
        s = norm_shot()
        m = vision.find(s, tpl, threshold=0.70)
        if m:
            hits[0] += 1
            cv2.imwrite(str(run / f"hit_{hits[0]:03d}.png"), s)
            return True, s
    return False, s


def menu_share(img) -> float:
    mid = img[560:2840, 60:1380]
    return float((np.abs(mid.astype(np.int16) - MENU_BG).max(axis=2) < 45).mean())


def gold_tree(img):
    """小村莊的參考地標：黃金樹（大面積金黃色樹冠）中心。"""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    m = ((h > 18) & (h < 40) & (s > 120) & (v > 140)).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8), 3)
    n, _l, stats, cent = cv2.connectedComponentsWithStats(m, 8)
    best = None
    for i in range(1, n):
        if stats[i][4] > 8000:
            if best is None or stats[i][4] > stats[best][4]:
                best = i
    if best is None:
        return None
    return float(cent[best][0]), float(cent[best][1])


class Area:
    def __init__(self, name, ref_kind):
        self.name = name
        self.ref_kind = ref_kind          # 'tent' or 'gold'
        self.tent = cv2.imread(str(TENT_TPL))

    def ref_pos(self, img):
        if self.ref_kind == "tent":
            r = vision.find(img, self.tent, threshold=0.68)
            return (float(r[0]), float(r[1])) if r else None
        return gold_tree(img)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("area", choices=["start_left", "start_right", "village_left", "village_right"])
    ap.add_argument("minutes", type=float, nargs="?", default=6.0)
    args = ap.parse_args()

    tpl = cv2.imread(str(DMG_TPL))
    pts = json.load(open(POINTS, encoding="utf-8"))
    area = Area(args.area, "tent" if args.area.startswith("start") else "gold")
    targets = [tuple(p) for p in pts[args.area]]

    run = Path("captures") / time.strftime("sweep_%Y%m%d_%H%M%S")
    run.mkdir(parents=True, exist_ok=True)
    log = (run / "log.jsonl").open("w", encoding="utf-8")

    def rec(obj):
        obj["t"] = time.strftime("%H:%M:%S")
        log.write(json.dumps(obj, ensure_ascii=False) + "\n")
        log.flush()
        print(json.dumps(obj, ensure_ascii=False))

    deadline = time.time() + args.minutes * 60
    visited = set()
    blocked = {}
    progress = {}         # idx -> [best_d, 沒進展次數]
    hits = 0
    hits_box = [0]
    step = 0

    while time.time() < deadline and len(visited) < len(targets):
        step += 1
        if not awake():
            rec({"step": step, "note": "睡著→解鎖"})
            unlock()
            continue

        img = norm_shot()
        if menu_share(img) > 0.10:
            rec({"step": step, "note": "選單底色→拖曳離開"})
            adb.swipe(*DRAG_ORIGIN, DRAG_ORIGIN[0] - 380, DRAG_ORIGIN[1], 900)
            time.sleep(1.0)
            continue

        ref = area.ref_pos(img)
        if ref is None:
            rec({"step": step, "note": f"找不到地標（{area.ref_kind}）→ 隨機探索"})
            adb.swipe(*DRAG_ORIGIN, DRAG_ORIGIN[0] - 300, DRAG_ORIGIN[1] - 200, 800)
            time.sleep(0.8)
            continue

        # 每個生成點在目前畫面上的位置 = 地標位置 + 相對位移
        cand = []
        for i, off in enumerate(targets):
            if i in visited:
                continue
            sx, sy = ref[0] + off[0], ref[1] + off[1]
            d = math.hypot(sx - ANCHOR[0], sy - ANCHOR[1])
            cand.append((blocked.get(i, 0), d, i, sx, sy))
        if not cand:
            break
        cand.sort()
        _blk, d, idx, sx, sy = cand[0]

        if d <= REACH:                      # 到了 → 停一下讓揮鎬完成，並用微調搜尋確認
            time.sleep(PAUSE)
            hit, _s = try_hit(tpl, run, hits_box)
            visited.add(idx)
            rec({"step": step, "note": "到點", "idx": idx, "d": round(d), "hit": bool(hit),
                 "hits": hits_box[0], "done": len(visited), "total": len(targets)})
            continue

        # 走一步朝目標
        vx, vy = sx - ANCHOR[0], sy - ANCHOR[1]
        n = max(abs(vx), abs(vy), 1)
        vx, vy = vx / n, vy / n
        ms = int(min(900, max(350, d * 1.1)))
        adb.swipe(*DRAG_ORIGIN, int(DRAG_ORIGIN[0] + vx * 330), int(DRAG_ORIGIN[1] + vy * 330), ms)
        time.sleep(0.25)
        cur = norm_shot()
        dx, dy, r = vision.scroll(img, cur)
        moved = abs(dx) > 8 or abs(dy) > 8
        # 走動後先看有沒有傷害數字（可能路上撞到東西）
        m = vision.find(cur, tpl, threshold=0.72)
        if m:
            hits += 1
            cv2.imwrite(str(run / f"hit_{hits:03d}.png"), cur)
        best, cnt = progress.get(idx, [d, 0])
        if d < best - 5:
            progress[idx] = [d, 0]
        else:
            cnt += 1
            progress[idx] = [best, cnt]
            if cnt >= 5:                     # 距離一直沒縮短 → 這個點被擋住，放棄
                visited.add(idx)
                print(json.dumps({"note": "放棄點（走不到）", "idx": idx, "d": round(d)}, ensure_ascii=False))
        if not moved:
            blocked[idx] = blocked.get(idx, 0) + 1
            if blocked[idx] >= 3:
                visited.add(idx)
        rec({"step": step, "note": "走", "idx": idx, "d": round(d), "moved": moved, "blk": blocked.get(idx, 0),
             "dir": [round(vx, 2), round(vy, 2)], "hits": hits,
             "done": len(visited), "total": len(targets)})

    log.close()
    print(f"done: 走過 {len(visited)}/{len(targets)} 點, {hits} 命中, 記錄在 {run}")


if __name__ == "__main__":
    main()

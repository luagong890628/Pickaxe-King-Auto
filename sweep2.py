"""巡生成點砍素材（v12）：里程計＋地標校正。

為什麼需要里程計：生成點清單是「以地標（帳篷／黃金樹）為原點」的相對座標；
但角色一離開地標附近，畫面就找不到地標 → 座標失準（v11 就是這樣飄出起始之地）。

v12 的做法：
- 用 phaseCorrelate 量每一格的畫面位移，累積成角色的世界座標 W（帳篷＝原點）。
- 任何時候只要畫面裡看到地標（帳篷或 SHOP），就用它重新校正 W，消除累積誤差。
- 每個生成點的畫面位置 = ANCHOR + (點位 − W) → 永遠知道往哪走。
- 到點後連拍找傷害數字；沒有就前後左右輕推再找（自動揮鎬需要貼近）。
- 只用拖曳；除了傳送石與「在小屋裡休息」不點任何 UI。
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import time
from pathlib import Path

import cv2
import numpy as np

from pkauto import adb, vision

ANCHOR = (720, 1400)
DRAG_ORIGIN = (600, 1650)
MENU_BG = np.array([255, 211, 143])
SHOP_OFF = (400, 80)      # SHOP 相對帳篷的世界位移（實測：同一張畫面上帳篷(644,1270)、SHOP(1044,1350)）
REACH = 85.0
PAUSE = 0.7
TENT = cv2.imread("captures/tpl_tent.png")
SHOP = cv2.imread("captures/tpl_shop.png")
DMG = cv2.imread("captures/tpl_dmg151.png")
TILE_START = cv2.imread("captures/tpl_tile_start.png")
HEART = (1275, 1715)
POINTS_FILE = Path("captures/spawn_points.json")


def norm_shot():
    return vision.normalize_brightness(adb.screencap())


def menu_share(img) -> float:
    mid = img[560:2840, 60:1380]
    return float((np.abs(mid.astype(np.int16) - MENU_BG).max(axis=2) < 45).mean())


def gold_tree(img):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    m = ((h > 18) & (h < 40) & (s > 120) & (v > 140)).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8), 3)
    n, _l, stats, cent = cv2.connectedComponentsWithStats(m, 8)
    best = None
    for i in range(1, n):
        if stats[i][4] > 8000 and (best is None or stats[i][4] > stats[best][4]):
            best = i
    return None if best is None else (float(cent[best][0]), float(cent[best][1]))


def floor_kind(img) -> str:
    """角色腳下周圍的地板色 → 判斷在哪一類島（用於「飄出起始之地」的保險）。"""
    b, g, r = cv2.split(img.astype("int16"))
    votes = {}
    for ddx, ddy in ((-140, 60), (140, 60), (0, 150), (0, -120), (-160, -60), (160, -60)):
        x, y = ANCHOR[0] + ddx, ANCHOR[1] + ddy
        patch = img[y - 12:y + 12, x - 12:x + 12].reshape(-1, 3)
        col = np.median(patch, axis=0)
        bb, gg, rr = col
        if bb > 170 and bb > rr + 40:
            k = "water"
        elif rr > 200 and gg > 200 and bb > 200:
            k = "snow"
        elif gg > rr + 40 and bb < 120 and gg > 170:
            k = "lightgreen"      # 青綠草地（起始之地那一類）
        elif rr > gg and rr > 120 and bb < 110:
            k = "brown"
        elif gg > rr + 20 and gg < 180:
            k = "darkgreen"
        else:
            k = "other"
        votes[k] = votes.get(k, 0) + 1
    return max(votes, key=votes.get)


def teleport_home(out: Path) -> bool:
    """用傳送石回起始之地：點愛心 → 找『起始之地』格子 → 點下去。"""
    cur = adb.screencap()
    if menu_share(cur) > 0.10:                       # 已經開著就先關掉
        adb.swipe(*DRAG_ORIGIN, DRAG_ORIGIN[0] - 380, DRAG_ORIGIN[1], 900)
        time.sleep(1.0)
    adb.tap(*HEART)
    time.sleep(1.6)
    for attempt in range(6):
        s = norm_shot()
        r = vision.find(s, TILE_START, threshold=0.75)
        if r:
            adb.tap(r[0], r[1])
            time.sleep(2.5)
            return menu_share(adb.screencap()) < 0.10
        adb.swipe(720, 2400, 720, 1700, 700)
        time.sleep(1.2)
    return False


class Tracker:
    """角色世界座標（帳篷＝原點）：里程計累積 + 看到地標就校正。"""

    def __init__(self, ref_kind: str):
        self.ref_kind = ref_kind            # 'tent'（起始之地）或 'gold'（小村莊）
        self.W = None
        self.prev = None
        self.anchors = 0

    def anchor(self, img):
        if self.ref_kind == "gold":
            g = gold_tree(img)
            if g is None:
                return None, None
            return (ANCHOR[0] - g[0], ANCHOR[1] - g[1]), "gold"
        t = vision.find(img, TENT, threshold=0.68)
        if t:
            return (ANCHOR[0] - t[0], ANCHOR[1] - t[1]), "tent"
        s = vision.find(img, SHOP, threshold=0.70)
        if s:
            return (ANCHOR[0] - s[0] + SHOP_OFF[0], ANCHOR[1] - s[1] + SHOP_OFF[1]), "shop"
        return None, None

    def update(self, img):
        moved = 0.0
        if self.prev is not None and self.W is not None:
            dx, dy, resp = vision.scroll(self.prev, img)
            if resp > 0.3:
                self.W = (self.W[0] - dx, self.W[1] - dy)
                moved = math.hypot(dx, dy)
        self.prev = img
        a, _kind = self.anchor(img)
        if a is not None:
            self.W = a
            self.anchors += 1
        return self.W, moved


def try_hit(run: Path, hits_box, tag=""):
    for _k in range(3):
        s = norm_shot()
        m = vision.find(s, DMG, threshold=0.70)
        if m:
            hits_box[0] += 1
            cv2.imwrite(str(run / f"hit_{hits_box[0]:03d}{tag}.png"), s)
            return True
        time.sleep(0.22)
    for ddx, ddy in ((0, -85), (0, 85), (-85, 0), (85, 0)):
        adb.swipe(*DRAG_ORIGIN, DRAG_ORIGIN[0] + ddx, DRAG_ORIGIN[1] + ddy, 480)
        time.sleep(0.3)
        s = norm_shot()
        m = vision.find(s, DMG, threshold=0.70)
        if m:
            hits_box[0] += 1
            cv2.imwrite(str(run / f"hit_{hits_box[0]:03d}{tag}.png"), s)
            return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("area", choices=["start_left", "start_right", "village_left", "village_right"])
    ap.add_argument("minutes", type=float, nargs="?", default=6.0)
    ap.add_argument("--no-teleport", action="store_true")
    args = ap.parse_args()

    pts = json.load(open(POINTS_FILE, encoding="utf-8"))
    targets = [tuple(p) for p in pts[args.area]]
    ref_kind = "tent" if args.area.startswith("start") else "gold"
    trk = Tracker(ref_kind)

    run = Path("captures") / time.strftime("sweep_%Y%m%d_%H%M%S")
    run.mkdir(parents=True, exist_ok=True)
    log = (run / "log.jsonl").open("w", encoding="utf-8")

    def rec(o):
        o["t"] = time.strftime("%H:%M:%S")
        log.write(json.dumps(o, ensure_ascii=False) + "\n")
        log.flush()
        print(json.dumps(o, ensure_ascii=False))

    hits_box = [0]
    visited, blocked, progress = set(), {}, {}
    deadline = time.time() + args.minutes * 60
    step = 0
    started = None

    while time.time() < deadline and len(visited) < len(targets):
        step += 1
        img = norm_shot()
        if menu_share(img) > 0.10:
            rec({"step": step, "note": "選單開著 → 拖曳離開"})
            adb.swipe(*DRAG_ORIGIN, DRAG_ORIGIN[0] - 380, DRAG_ORIGIN[1], 900)
            time.sleep(1.0)
            continue

        W, moved = trk.update(img)
        if started is None and W is not None:
            started = time.time()
            rec({"step": step, "note": "起始錨定完成", "W": [round(W[0]), round(W[1])]})
        if W is None:
            if step > 3 and not args.no_teleport and ref_kind == "tent":
                rec({"step": step, "note": "沒有地標可定位 → 傳送回起始之地"})
                if teleport_home(run):
                    trk.prev = None
                continue
            rec({"step": step, "note": "定位中：找不到地標，先往南走"})
            adb.swipe(*DRAG_ORIGIN, DRAG_ORIGIN[0], DRAG_ORIGIN[1] - 330, 700)
            time.sleep(0.6)
            continue

        kind = floor_kind(img)
        if ref_kind == "tent" and kind == "darkgreen" and not args.no_teleport:
            rec({"step": step, "note": "地板變深綠 → 飄出起始之地，傳送回來", "floor": kind})
            if teleport_home(run):
                trk.prev = None
            continue

        cand = []
        for i, off in enumerate(targets):
            if i in visited:
                continue
            sx, sy = ANCHOR[0] + off[0] - W[0], ANCHOR[1] + off[1] - W[1]
            d = math.hypot(sx - ANCHOR[0], sy - ANCHOR[1])
            if 120 < sx < 1320 and 200 < sy < 2900:      # 只在畫面內挑（太遠的走過去很花時間）
                cand.append((blocked.get(i, 0), d, i, sx, sy))
        if not cand:                                     # 畫面內沒點 → 朝最近未訪點的方向走
            rest = [(i, off) for i, off in enumerate(targets) if i not in visited]
            if not rest:
                break
            i, off = min(rest, key=lambda t: math.hypot(t[1][0] - W[0], t[1][1] - W[1]))
            sx, sy = ANCHOR[0] + off[0] - W[0], ANCHOR[1] + off[1] - W[1]
            d = math.hypot(sx - ANCHOR[0], sy - ANCHOR[1])
            cand = [(blocked.get(i, 0), d, i, sx, sy)]
        cand.sort()
        _blk, d, idx, sx, sy = cand[0]

        if d <= REACH:
            time.sleep(PAUSE)
            hit = try_hit(run, hits_box)
            visited.add(idx)
            rec({"step": step, "note": "到點", "idx": idx, "d": round(d), "hit": hit,
                 "hits": hits_box[0], "done": len(visited), "total": len(targets),
                 "W": [round(W[0]), round(W[1])]})
            continue

        vx, vy = sx - ANCHOR[0], sy - ANCHOR[1]
        n = max(abs(vx), abs(vy), 1)
        vx, vy = vx / n, vy / n
        ms = int(min(900, max(400, d * 1.2)))
        adb.swipe(*DRAG_ORIGIN, int(DRAG_ORIGIN[0] + vx * 340), int(DRAG_ORIGIN[1] + vy * 340), ms)
        time.sleep(0.2)
        cur = norm_shot()
        m = vision.find(cur, DMG, threshold=0.70)
        if m:
            hits_box[0] += 1
            cv2.imwrite(str(run / f"hit_{hits_box[0]:03d}_walk.png"), cur)
        dx, dy, resp = vision.scroll(img, cur)
        really = resp > 0.3 and abs(dx) > 8 or resp > 0.3 and abs(dy) > 8
        best, cnt = progress.get(idx, (d, 0))
        if d < best - 6:
            progress[idx] = (d, 0)
        else:
            cnt += 1
            progress[idx] = (best, cnt)
            if cnt >= 5:
                visited.add(idx)
                rec({"step": step, "note": "放棄點（走不到）", "idx": idx, "d": round(d)})
        if not really:
            blocked[idx] = blocked.get(idx, 0) + 1
            if blocked[idx] >= 3:
                visited.add(idx)
        rec({"step": step, "note": "走", "idx": idx, "d": round(d), "moved": really,
             "resp": round(resp, 2), "blk": blocked.get(idx, 0), "hits": hits_box[0],
             "done": len(visited), "total": len(targets), "W": [round(W[0]), round(W[1])]})

    log.close()
    print(f"done: 走過 {len(visited)}/{len(targets)} 點, {hits_box[0]} 命中, 錨定 {trk.anchors} 次, 記錄在 {run}")
    shutil.copy(run / "log.jsonl", "captures/last_sweep_log.jsonl")


if __name__ == "__main__":
    main()

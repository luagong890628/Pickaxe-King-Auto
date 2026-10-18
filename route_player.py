"""照使用者錄好的固定路線重播走一圈（起始之地用）。

定位方式：
- 角色位置 pos 存在「路線座標系」（原點＝使用者開始錄製時站的位置）。
- 每一步用畫面位移（phaseCorrelate，等角色走完才取樣）累加。
- 畫面裡看到 SHOP／帳篷時，用「預測位置附近小窗搜尋」重新校正 pos（連續兩張一致才採用）。
- 走到路線點附近就停一下（讓自動揮鎬把旁邊的樹/石頭砍掉），再走下一個點。
- 生命值歸零 → 走去帳篷點休息 → 醒來回到路線繼續。
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
DRAG = (720, 2000)
MENU_BG = np.array([255, 211, 143])
TPL = {
    "shop": cv2.imread("captures/tpl_shop.png"),
    "tent": cv2.imread("captures/tpl_tent.png"),
}
THRESH = {"shop": 0.65, "tent": 0.70}
REST_TPL = cv2.imread("captures/tpl_rest_dialog.png")
DMG_TPL = cv2.imread("captures/tpl_dmg151.png")
REACH = 70
PAUSE = 0.7
SETTLE = 1.4          # 拖曳後等角色走完動畫才取樣


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


class Player:
    def __init__(self, route):
        self.pts = [tuple(p) for p in route["points"]]
        self.anchors = route.get("anchor", {})
        self.pos = [0.0, 0.0]
        self.pend = {}

    def expected_screen(self, route_xy):
        """路線座標 → 目前畫面上的位置。"""
        return (ANCHOR[0] + route_xy[0] - self.pos[0], ANCHOR[1] + route_xy[1] - self.pos[1])

    def correct(self, img, log):
        """用可見地標校正 pos。"""
        for name, info in self.anchors.items():
            rp = info["route_pos"]
            exp = self.expected_screen(rp)
            if not (60 < exp[0] < 1380 and 80 < exp[1] < 3000):
                continue
            f = find_local(img, TPL[name], exp, 200, THRESH[name])
            if not f:
                self.pend.pop(name, None)
                continue
            cand = [rp[0] - (f[0] - ANCHOR[0]), rp[1] - (f[1] - ANCHOR[1])]
            prev = self.pend.get(name)
            if prev is not None and math.dist(prev, cand) < 40 and math.dist(cand, self.pos) < 260:
                moved = math.dist(cand, self.pos)
                self.pos = cand
                log({"note": "地標校正", "landmark": name, "pos": [round(v) for v in self.pos],
                     "修掉": round(moved)})
            self.pend[name] = cand
        return self.pos

    def walk_step(self, img, target, log):
        """朝目標走一步；被擋住時自動試「旋轉 ±25°/±50°」與側移（走窄路/繞建築用）。"""
        sx, sy = self.expected_screen(target)
        d = math.hypot(sx - ANCHOR[0], sy - ANCHOR[1])
        base = math.atan2(sy - ANCHOR[1], sx - ANCHOR[0])
        pl = int(min(330, max(80, d * 0.8)))
        tries = [0.0, 25.0, -25.0, 50.0, -50.0, 90.0, -90.0]
        cur, moved = img, False
        used = 0.0
        for k, off in enumerate(tries):
            a = base + math.radians(off)
            length = pl if k == 0 else max(90, int(pl * 0.7))
            adb.swipe(*DRAG, int(DRAG[0] + math.cos(a) * length), int(DRAG[1] + math.sin(a) * length),
                      int(min(800, max(260, length * 2.2))))
            time.sleep(SETTLE)
            cur = shot()
            dx, dy, resp = vision.scroll(img, cur)
            moved = resp > 0.4 and (abs(dx) > 6 or abs(dy) > 6)
            used = off
            if moved:
                self.pos[0] += -dx
                self.pos[1] += -dy
                break
        if used != 0.0:
            log({"note": "繞路", "角度": used, "成功": moved, "d": round(d)})
        m = vision.find(cur, DMG_TPL, threshold=0.70)
        return cur, moved, d, bool(m)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("route", help="captures/paths/<name>.json 的 name")
    ap.add_argument("minutes", type=float, nargs="?", default=15.0)
    ap.add_argument("--passes", type=int, default=0, help="走幾圈（0=時間到才停）")
    args = ap.parse_args()

    route = json.load(open(f"captures/paths/{args.route}.json", encoding="utf-8"))
    p = Player(route)
    run = Path("captures") / time.strftime("route_%Y%m%d_%H%M%S")
    run.mkdir(parents=True, exist_ok=True)
    log_f = (run / "log.jsonl").open("w", encoding="utf-8")

    def log(o):
        o["t"] = time.strftime("%H:%M:%S")
        log_f.write(json.dumps(o, ensure_ascii=False) + "\n")
        log_f.flush()
        print(json.dumps(o, ensure_ascii=False))

    log({"note": "start", "route": args.route, "points": len(p.pts), "anchors": list(p.anchors)})
    hits = 0
    stalled = 0
    idx = 0
    passes = 0
    deadline = time.time() + args.minutes * 60
    step = 0

    while time.time() < deadline:
        step += 1
        img = shot()
        if menu_share(img) > 0.10:
            adb.swipe(*DRAG, DRAG[0] - 380, DRAG[1], 900)
            time.sleep(1.0)
            continue

        p.correct(img, log)

        text, _d = hp.read(img)
        if text and text.startswith("0/"):
            log({"step": step, "note": "生命值歸零 → 回帳篷休息", "hp": text, "hits": hits})
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
                f = find_local(s, TPL["tent"], p.expected_screen(p.anchors["tent"]["route_pos"]), 260, 0.70)
                if f:
                    cand = [p.anchors["tent"]["route_pos"][0] - (f[0] - ANCHOR[0]),
                            p.anchors["tent"]["route_pos"][1] - (f[1] - ANCHOR[1])]
                    p.pos = cand
                tp = p.anchors["tent"]["route_pos"]
                sx, sy = p.expected_screen(tp)
                n = max(abs(sx - ANCHOR[0]), abs(sy - ANCHOR[1]), 1)
                d = math.hypot(sx - ANCHOR[0], sy - ANCHOR[1])
                pl = int(min(320, max(90, d * 0.8)))
                adb.swipe(*DRAG, int(DRAG[0] + (sx - ANCHOR[0]) / n * pl), int(DRAG[1] + (sy - ANCHOR[1]) / n * pl),
                          int(min(800, max(280, pl * 2.2))))
                time.sleep(SETTLE)
                cur2 = shot()
                dx, dy, resp = vision.scroll(s, cur2)
                if resp > 0.4:
                    p.pos[0] += -dx
                    p.pos[1] += -dy
            log({"step": step, "note": "休息流程結束", "hits": hits, "pos": [round(v) for v in p.pos]})
            continue

        target = p.pts[idx]
        cur, moved, d, hit = p.walk_step(img, target, log)
        if hit:
            hits += 1
            cv2.imwrite(str(run / f"hit_{hits:03d}.png"), cur)
        if not moved:
            stalled += 1
        else:
            stalled = 0
        if d <= REACH or stalled >= 4:
            time.sleep(PAUSE)
            cur2 = shot()
            if vision.find(cur2, DMG_TPL, threshold=0.70):
                hits += 1
                cv2.imwrite(str(run / f"hit_{hits:03d}.png"), cur2)
            log({"step": step, "note": "到點", "idx": idx, "d": round(d), "stall": stalled,
                 "hits": hits, "pos": [round(v) for v in p.pos]})
            stalled = 0
            idx += 1
            if idx >= len(p.pts):
                idx = 0
                passes += 1
                log({"step": step, "note": "完成一圈", "passes": passes, "hits": hits})
                if args.passes and passes >= args.passes:
                    break
            continue
        log({"step": step, "note": "走", "idx": idx, "d": round(d), "moved": moved,
             "hits": hits, "pos": [round(v) for v in p.pos]})

    log_f.close()
    print(f"done: {passes} 圈, {hits} 命中, 記錄在 {run}")


if __name__ == "__main__":
    main()

"""自己找目標砍素材（v14）：從畫面偵測樹冠/石頭 → 走向最近的目標 → 砍 → 記錄（100 秒內不重複）。

為什麼改成這樣：
- 使用者說遊戲裡沒有紅點（那是他畫的標註），要程式自己抓位置。
- 物件（建築/樹/石頭）都不能穿越 → 直接走直線常被擋住；改成「目標都在畫面裡、看得見才走過去」，
  被擋住就側滑繞開、一直靠近不了就放棄換下一個目標。
- 角色位置用里程計 + 地標（帳篷/SHOP）校正；生命值歸零 → 自動回帳篷休息。
"""
from __future__ import annotations

import argparse
import math
import time
from pathlib import Path

import cv2
import numpy as np

from pkauto import adb, vision, hp
from sweep2 import ANCHOR, DRAG_ORIGIN, DMG, Tracker, menu_share, norm_shot, floor_kind, teleport_home

REST_TPL = cv2.imread("captures/tpl_rest_dialog.png")
SPENT_TTL = 100.0        # 砍掉後 100 秒重生
SPENT_R = 90.0           # 記錄半徑
HIT_R = 62.0             # 到這個距離就算到位


def canopy_targets(img):
    """回傳畫面上的樹冠/石頭目標（螢幕座標），由近到遠。"""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    green = ((h > 45) & (h < 95) & (s > 150) & (v > 80)).astype(np.uint8) * 255
    k = np.ones((5, 5), np.uint8)
    green = cv2.morphologyEx(green, cv2.MORPH_OPEN, k, 1)
    n, lab, st, ce = cv2.connectedComponentsWithStats(green, 8)
    out = []
    for i in range(1, n):
        x, y, w, hh, a = st[i]
        if a < 4000 or y < 500 or y > 2900 or x < 200 or x > 1250:
            continue
        if a > 20000:
            # 大塊樹冠 → 取「離角色最近的那一點」，不是質心（質心可能在畫面外）
            sub = (lab[y:y + hh, x:x + w] == i)
            ys, xs = np.nonzero(sub)
            ddx = xs + x - ANCHOR[0]
            ddy = ys + y - ANCHOR[1]
            k = int(np.argmin(ddx * ddx + ddy * ddy))
            cx, cy = float(xs[k] + x), float(ys[k] + y)
        else:
            cx, cy = float(ce[i][0]), float(ce[i][1])
        d = math.hypot(cx - ANCHOR[0], cy - ANCHOR[1])
        out.append((d, cx, cy, int(a)))
    # 石頭（灰色、低飽和、比地板暗）
    gray = ((s < 40) & (v > 110) & (v < 225)).astype(np.uint8) * 255
    n2, _l2, st2, ce2 = cv2.connectedComponentsWithStats(gray, 8)
    for i in range(1, n2):
        x, y, w, hh, a = st2[i]
        if a < 900 or a > 9000 or y < 500 or y > 2900 or x < 200 or x > 1250:
            continue
        if w > 160 or hh > 160:
            continue
        cx, cy = float(ce2[i][0]), float(ce2[i][1])
        d = math.hypot(cx - ANCHOR[0], cy - ANCHOR[1])
        if d < 55:
            continue
        out.append((d, cx, cy, int(a)))
    out.sort()
    return out


def go_rest(trk, log):
    for i in range(70):
        img = norm_shot()
        r = vision.find(img, REST_TPL, threshold=0.72)
        if r:
            log({"note": "休息：點對話框", "at": [r[0], r[1]]})
            adb.tap(r[0], r[1])
            time.sleep(1.5)
            for _k in range(14):
                time.sleep(0.6)
                s2 = norm_shot()
                if vision.find(s2, REST_TPL, threshold=0.72) is None:
                    text, _d = hp.read(s2)
                    if text and not text.startswith("0/"):
                        log({"note": "休息完成", "hp": text})
                        return True
            return False
        W, _m = trk.update(img)
        if W is None:
            log({"note": "休息：找不到地標，退回"})
            return False
        sx, sy = ANCHOR[0] - W[0], ANCHOR[1] - W[1]
        d = math.hypot(sx - ANCHOR[0], sy - ANCHOR[1])
        if d > 30:
            n = max(abs(sx - ANCHOR[0]), abs(sy - ANCHOR[1]), 1)
            vx, vy = (sx - ANCHOR[0]) / n, (sy - ANCHOR[1]) / n
            pl = int(min(340, max(70, d * 0.8)))
            adb.swipe(*DRAG_ORIGIN, int(DRAG_ORIGIN[0] + vx * pl), int(DRAG_ORIGIN[1] + vy * pl),
                      int(min(800, max(260, pl * 2.2))))
        else:
            adb.swipe(*DRAG_ORIGIN, DRAG_ORIGIN[0] + 140, DRAG_ORIGIN[1], 520)
        time.sleep(0.35)
    log({"note": "休息：走不到帳篷"})
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("minutes", type=float, nargs="?", default=10.0)
    ap.add_argument("--no-gateway", action="store_true", help="不套用起始之地的繞路（在別的區用）")
    args = ap.parse_args()

    trk = Tracker("tent")
    if args.no_gateway:
        trk.W = (0.0, 0.0)          # 不靠地標：以出發點為原點，純里程計
    run = Path("captures") / time.strftime("harvest_%Y%m%d_%H%M%S")
    run.mkdir(parents=True, exist_ok=True)
    log = (run / "log.jsonl").open("w", encoding="utf-8")

    def rec(o):
        o["t"] = time.strftime("%H:%M:%S")
        log.write(__import__("json").dumps(o, ensure_ascii=False) + "\n")
        log.flush()
        print(__import__("json").dumps(o, ensure_ascii=False))

    spent = {}                       # (gx, gy) -> 時間
    hits = 0
    target = None
    target_world = None
    stall = 0
    best_d = None
    deadline = time.time() + args.minutes * 60
    step = 0

    while time.time() < deadline:
        step += 1
        img = norm_shot()

        if menu_share(img) > 0.10:
            adb.swipe(*DRAG_ORIGIN, DRAG_ORIGIN[0] - 380, DRAG_ORIGIN[1], 900)
            time.sleep(1.0)
            continue

        text, _d = hp.read(img)
        if text and text.startswith("0/"):
            rec({"step": step, "note": "生命值歸零 → 去帳篷休息", "hp": text})
            go_rest(trk, rec)
            target = None
            continue

        W, _m = trk.update(img)
        if W is None:
            if args.no_gateway:
                trk.W = (0.0, 0.0)
                continue
            rec({"step": step, "note": "找不到地標 → 傳送回起始之地"})
            if teleport_home(run):
                trk.prev = None
            continue

        if floor_kind(img) == "darkgreen" and not args.no_gateway:
            rec({"step": step, "note": "地板深綠 → 飄出起始之地，傳送回來"})
            if teleport_home(run):
                trk.prev = None
            continue

        # 在果園外（南邊的草地/商店區）→ 先繞到果園入口，不要傻傻往北撞商店
        if W[1] > 60 and not args.no_gateway:
            for gx, gy in ((-280, 120), (-280, -140)):
                sx, sy = ANCHOR[0] + gx - W[0], ANCHOR[1] + gy - W[1]
                if math.hypot(sx - ANCHOR[0], sy - ANCHOR[1]) > 90:
                    n = max(abs(sx - ANCHOR[0]), abs(sy - ANCHOR[1]), 1)
                    vx, vy = (sx - ANCHOR[0]) / n, (sy - ANCHOR[1]) / n
                    pl = int(min(340, max(80, math.hypot(sx - ANCHOR[0], sy - ANCHOR[1]) * 0.8)))
                    adb.swipe(*DRAG_ORIGIN, int(DRAG_ORIGIN[0] + vx * pl), int(DRAG_ORIGIN[1] + vy * pl),
                              int(min(800, max(260, pl * 2.2))))
                    time.sleep(0.3)
                    rec({"step": step, "note": "繞路進果園", "gate": [gx, gy],
                         "W": [round(W[0]), round(W[1])]})
                    target = None
                    break
            if target is None:
                continue

        now = time.time()
        # 目標以世界座標保存；角色移動後要重算它在畫面上的位置
        if target_world is not None:
            target = (ANCHOR[0] + target_world[0] - W[0], ANCHOR[1] + target_world[1] - W[1])
        # 目標失效（走太久/被砍掉）→ 重新挑
        if target is not None:
            tx, ty = target
            d = math.hypot(tx - ANCHOR[0], ty - ANCHOR[1])
            if d <= HIT_R or stall >= 6:
                gw = target_world if target_world is not None else (
                    round((W[0] + tx - ANCHOR[0]) / SPENT_R), round((W[1] + ty - ANCHOR[1]) / SPENT_R))
                if isinstance(gw, tuple) and len(gw) == 2:
                    gw = (round(gw[0] / SPENT_R), round(gw[1] / SPENT_R))
                spent[gw] = now
                time.sleep(0.45)
                cur = norm_shot()
                if vision.find(cur, DMG, threshold=0.70):
                    hits += 1
                    cv2.imwrite(str(run / f"hit_{hits:03d}.png"), cur)
                rec({"step": step, "note": "到位/放棄", "d": round(d), "stall": stall,
                     "hits": hits, "W": [round(W[0]), round(W[1])]})
                target, target_world, stall, best_d = None, None, 0, None
                continue

        if target is None:
            # 挑最近的「還沒砍過（100 秒內）」的樹冠/石頭
            cands = canopy_targets(img)
            for d, cx, cy, a in cands:
                gw = (round((W[0] + cx - ANCHOR[0]) / SPENT_R), round((W[1] + cy - ANCHOR[1]) / SPENT_R))
                if now - spent.get(gw, -9999) < SPENT_TTL:
                    continue
                target_world = (W[0] + cx - ANCHOR[0], W[1] + cy - ANCHOR[1])
                target, stall, best_d = (cx, cy), 0, d
                break
            if target is None:
                # 附近沒東西 → 朝畫面裡的樹冠最密處走（探索）
                if cands:
                    _d, cx, cy, _a = cands[0]
                    target = (cx, cy)
                    target_world = (W[0] + cx - ANCHOR[0], W[1] + cy - ANCHOR[1])
                    stall, best_d = 0, _d
                else:
                    adb.swipe(*DRAG_ORIGIN, DRAG_ORIGIN[0] - 240, DRAG_ORIGIN[1] - 160, 700)
                    time.sleep(0.4)
                    rec({"step": step, "note": "畫面裡沒有目標 → 探索", "W": [round(W[0]), round(W[1])]})
                    continue
            rec({"step": step, "note": "選定目標", "at": [round(target[0]), round(target[1])],
                 "d": round(best_d), "W": [round(W[0]), round(W[1])]})

        tx, ty = target
        vx, vy = tx - ANCHOR[0], ty - ANCHOR[1]
        d = math.hypot(vx, vy)
        n = max(abs(vx), abs(vy), 1)
        vx, vy = vx / n, vy / n
        pl = int(min(340, max(70, d * 0.8)))
        adb.swipe(*DRAG_ORIGIN, int(DRAG_ORIGIN[0] + vx * pl), int(DRAG_ORIGIN[1] + vy * pl),
                  int(min(800, max(260, pl * 2.2))))
        time.sleep(0.2)
        cur = norm_shot()
        m = vision.find(cur, DMG, threshold=0.70)
        if m:
            hits += 1
            cv2.imwrite(str(run / f"hit_{hits:03d}.png"), cur)
        dx, dy, resp = vision.scroll(img, cur)
        moved = resp > 0.3 and (abs(dx) > 8 or abs(dy) > 8)
        if not moved:
            stall += 1
            px, py = (-vy, vx) if stall % 2 else (vy, -vx)
            adb.swipe(*DRAG_ORIGIN, int(DRAG_ORIGIN[0] + px * 250), int(DRAG_ORIGIN[1] + py * 250), 520)
            time.sleep(0.25)
        else:
            if best_d is not None and d < best_d - 10:
                best_d, stall = d, 0
            else:
                stall += 1
        rec({"step": step, "note": "走", "d": round(d), "moved": moved, "stall": stall,
             "hits": hits, "W": [round(W[0]), round(W[1])]})

    log.close()
    print(f"done: {hits} 命中（拍到）, 記錄在 {run}")


if __name__ == "__main__":
    main()

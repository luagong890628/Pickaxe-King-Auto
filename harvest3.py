"""砍素材（v16）：朝「樹最密的方向」走（偏光性走法），不需要定位。

why：實測兩條路都不通——
 (1) 世界座標：畫面位移量測雜訊太大（畫面裡有雞/NPC 在動），累積起來走幾步就偏幾百 px。
 (2) 直接鎖定最近的樹：很多樹在建築後面，走過去會被擋住，角色就站在原地不動（也砍不到）。
所以改成只看「哪個方向的樹/石頭最多」就往那邊走；撞到東西（畫面沒動）就換方向。
走進樹叢後一直移動就會不斷撞到樹、觸發自動揮鎬。
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
DRAG_ORIGIN = (600, 1650)
MENU_BG = np.array([255, 211, 143])
TENT_TPL = cv2.imread("captures/tpl_tent.png")
REST_TPL = cv2.imread("captures/tpl_rest_dialog.png")
DMG_TPL = cv2.imread("captures/tpl_dmg151.png")

DIRS = [(-1, 0), (-1, -1), (0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1)]   # N NE E SE S SW W NW
DIRNAME = ["W", "NW", "N", "NE", "E", "SE", "S", "SW"]


def norm_shot():
    return vision.normalize_brightness(adb.screencap())


def menu_share(img) -> float:
    mid = img[560:2840, 60:1380]
    return float((np.abs(mid.astype(np.int16) - MENU_BG).max(axis=2) < 45).mean())


def floor_kind(img) -> str:
    """角色腳下地板色（取半徑 130 的環狀中位色）。

    實測：起始之地淺色草地 BGR(105,219,145)、松露島深綠 (99,144,35)；
    深綠島＝紅龍／鯊魚／松露／鴨子島，淺色＝起始之地與各農村。
    """
    pts = []
    for ang in range(0, 360, 30):
        x = int(ANCHOR[0] + 130 * math.cos(math.radians(ang)))
        y = int(ANCHOR[1] + 130 * math.sin(math.radians(ang)))
        patch = img[y - 6:y + 6, x - 6:x + 6].reshape(-1, 3)
        if patch.size:
            pts.append(np.median(patch, axis=0))
    if not pts:
        return "other"
    b, g, r = np.median(np.array(pts), axis=0)
    if b > 170 and b > r + 40:
        return "water"
    if min(b, g, r) > 190:
        return "snow"
    if b > 100 and g > 180:
        return "light"          # 起始之地／農村
    if b < 85 and g < 195 and g > r:
        return "darkgreen"      # 松露島等深綠島
    if r > 150 and r > g and b < 120:
        return "brown"
    return "other"


def resource_mask(img):
    """樹冠（綠）+ 石頭（灰）的遮罩。"""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    m = ((h > 45) & (h < 95) & (s > 150) & (v > 80)) | ((s < 42) & (v > 115) & (v < 225))
    m = m.astype(np.uint8) * 255
    m[:520, :] = 0
    m[2880:, :] = 0
    m[:, :210] = 0
    m[:, 1240:] = 0
    return m


def sector_scores(mask):
    """8 個方向的資源量（越近的權重越高）；回傳由高到低排序的 (分數, dir_index)。"""
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return []
    dx = xs - ANCHOR[0]
    dy = ys - ANCHOR[1]
    dist = np.hypot(dx, dy)
    keep = dist > 60
    if not keep.any():
        return []
    dx, dy, dist = dx[keep], dy[keep], dist[keep]
    ang = (np.degrees(np.arctan2(dy, dx)) + 360) % 360        # 0=右, 90=下
    # 8 方位：以 W(180°) 為起點切 45° 一格
    idx = ((ang - 157.5) % 360 // 45).astype(int)
    w = 1.0 / np.maximum(dist, 80.0)
    out = []
    for k in range(8):
        sel = idx == k
        out.append((float(w[sel].sum()), k))
    out.sort(reverse=True)
    return out


def step_dir(vx, vy, length):
    adb.swipe(*DRAG_ORIGIN, int(DRAG_ORIGIN[0] + vx * length), int(DRAG_ORIGIN[1] + vy * length),
              int(min(800, max(280, length * 2.2))))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("minutes", type=float, nargs="?", default=10.0)
    args = ap.parse_args()

    run = Path("captures") / time.strftime("h3_%Y%m%d_%H%M%S")
    run.mkdir(parents=True, exist_ok=True)
    log = (run / "log.jsonl").open("w", encoding="utf-8")

    def rec(o):
        o["t"] = time.strftime("%H:%M:%S")
        log.write(json.dumps(o, ensure_ascii=False) + "\n")
        log.flush()
        print(json.dumps(o, ensure_ascii=False))

    hits = 0
    block_until = {}
    deadline = time.time() + args.minutes * 60
    step = 0
    since = 0
    density_log = []

    while time.time() < deadline:
        step += 1
        img = norm_shot()

        if menu_share(img) > 0.10:
            adb.swipe(*DRAG_ORIGIN, DRAG_ORIGIN[0] - 380, DRAG_ORIGIN[1], 900)
            time.sleep(1.0)
            continue

        text, _d = hp.read(img)
        if text and text.startswith("0/"):
            rec({"step": step, "note": "生命值歸零 → 找帳篷休息", "hp": text, "hits": hits})
            for _i in range(60):
                s = norm_shot()
                r = vision.find(s, REST_TPL, threshold=0.72)
                if r:
                    adb.tap(r[0], r[1])
                    time.sleep(1.5)
                    for _k in range(14):
                        time.sleep(0.6)
                        if vision.find(norm_shot(), REST_TPL, threshold=0.72) is None:
                            break
                    break
                t = vision.find(s, TENT_TPL, threshold=0.82)
                if t:
                    d = math.hypot(t[0] - ANCHOR[0], t[1] - ANCHOR[1])
                    n = max(abs(t[0] - ANCHOR[0]), abs(t[1] - ANCHOR[1]), 1)
                    step_dir((t[0] - ANCHOR[0]) / n, (t[1] - ANCHOR[1]) / n, min(320, max(90, d * 0.8)))
                else:
                    step_dir(0, 1, 240)          # 帳篷在起始之地南側 → 往南找
                time.sleep(0.45)
            rec({"step": step, "note": "休息流程結束", "hits": hits})
            continue

        fk = floor_kind(img)
        if fk == "darkgreen":
            step_dir(0, 1, 300)                 # 深綠島（松露島等）在起始之地北方 → 往南退回
            time.sleep(0.3)
            back_n = time.time() + 40
            for k in (1, 2, 3):                  # 先封鎖 N/NE/NW，避免又立刻飄回去
                block_until[k] = max(block_until.get(k, 0), time.time() + 40)
            rec({"step": step, "note": "地板深綠（松露島）→ 往南退回", "floor": fk, "hits": hits})
            continue

        mask = resource_mask(img)
        density = float(mask.mean())
        density_log.append(round(density * 100, 1))
        scores = sector_scores(mask)
        if not scores:
            step_dir(1, 0, 260)
            time.sleep(0.35)
            rec({"step": step, "note": "看不到資源 → 橫向探索", "density": round(density * 100, 1), "hits": hits})
            continue

        chosen = None
        for sc, k in scores:
            if time.time() >= block_until.get(k, 0):
                chosen = (sc, k)
                break
        if chosen is None:                       # 全部被封鎖 → 清掉重來
            block_until.clear()
            chosen = scores[0]
        sc, k = chosen
        vx, vy = DIRS[k]
        step_dir(vx, vy, 300)
        time.sleep(0.22)
        cur = norm_shot()
        d = vision.diff(img, cur)
        moved = d > 1.2
        if not moved:
            block_until[k] = time.time() + 12     # 撞到東西 → 這方向封鎖一下
        m = vision.find(cur, DMG_TPL, threshold=0.70)
        if m:
            hits += 1
            cv2.imwrite(str(run / f"hit_{hits:03d}.png"), cur)
        since += 1
        if since >= 20:
            cv2.imwrite(str(run / f"frame_{step:04d}.png"), cur)
            since = 0
        rec({"step": step, "note": "走", "dir": DIRNAME[k], "score": round(sc, 3),
             "moved": moved, "density": round(density * 100, 1), "hits": hits})

    log.close()
    print(f"done: {hits} 命中, 樹密度平均 {np.mean(density_log):.1f}%, 記錄在 {run}")


if __name__ == "__main__":
    main()

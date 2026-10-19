"""自動砍素材 v17：目標導向 + 兩地區輪替（完全不做定位）。

使用者要的邏輯：
1. 角色永遠在畫面固定位置 → 偵測樹/石頭 → 讓它「出現在角色身上」＝走過去砍。
2. 砍到畫面裡都沒目標（連續 N 次看不到）→ 傳送到另一個地區。
3. 只在 小村莊 ⇄ 起始之地 輪流；不需要知道自己在座標上的哪裡（內部記狀態即可）。
4. 移動用「按住時間」控制（實測 ≈315px/秒）。
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
TILE = {
    "village": cv2.imread("captures/tpl_tile_village.png"),
    "start": cv2.imread("captures/tpl_tile_start.png"),
}
PPS = 315.0                       # 按住每秒移動的畫面像素（實測）
DMG_TPL = cv2.imread("captures/tpl_dmg151.png")


def shot():
    return vision.normalize_brightness(adb.screencap())


def menu_share(img) -> float:
    mid = img[560:2840, 60:1380]
    return float((np.abs(mid.astype(np.int16) - MENU_BG).max(axis=2) < 45).mean())


def rest_box(img):
    """「在小屋裡休息」白框（大面積近白矩形）。"""
    b, g, r = cv2.split(img.astype("int16"))
    white = ((b > 215) & (g > 215) & (r > 215)).astype(np.uint8) * 255
    roi = cv2.morphologyEx(white[1000:2700, 150:1350], cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8), 3)
    n, _l, st, ce = cv2.connectedComponentsWithStats(roi, 8)
    best = None
    for i in range(1, n):
        if st[i][4] > 40000 and 600 < st[i][2] < 1250 and 120 < st[i][3] < 320:
            if best is None or st[i][4] > st[best][4]:
                best = i
    if best is None:
        return None
    return int(ce[best][0]) + 150, int(ce[best][1]) + 1000


def targets(img):
    """畫面裡的樹冠/石頭，依離角色距離排序。"""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    out = []
    green = ((h > 45) & (h < 95) & (s > 150) & (v > 80)).astype(np.uint8) * 255
    green = cv2.morphologyEx(green, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8), 1)
    n, _l, st, _c = cv2.connectedComponentsWithStats(green, 8)
    for i in range(1, n):
        x, y, w, hh, a = st[i]
        if a < 2500 or y < 700 or y > 2860 or x < 260 or x > 1230:
            continue
        tx, ty = x + w / 2, min(y + hh + 36, 2840.0)
        d = math.hypot(tx - ANCHOR[0], ty - ANCHOR[1])
        if d > 60:
            out.append((d, float(tx), float(ty), "tree"))
    gray = ((s < 42) & (v > 115) & (v < 225)).astype(np.uint8) * 255
    n2, _l2, st2, _c2 = cv2.connectedComponentsWithStats(gray, 8)
    for i in range(1, n2):
        x, y, w, hh, a = st2[i]
        if a < 800 or a > 9000 or w > 170 or hh > 170 or y < 700 or y > 2860 or x < 260 or x > 1230:
            continue
        cx, cy = x + w / 2, y + hh / 2
        d = math.hypot(cx - ANCHOR[0], cy - ANCHOR[1])
        if d > 60:
            out.append((d, float(cx), float(cy), "stone"))
    out.sort()
    return out


def drag(img, vx, vy, dist):
    """朝 (vx,vy) 走 dist 距離（用按住時間控制）；被擋就換角度。"""
    base = math.atan2(vy, vx)
    hold = int(min(2000, max(280, dist / PPS * 1000)))
    cur = img
    for off in (0, 40, -40, 80, -80, 150, -150, 180):
        a = base + math.radians(off)
        adb.swipe(*DRAG, int(DRAG[0] + math.cos(a) * 260), int(DRAG[1] + math.sin(a) * 260), hold)
        time.sleep(hold / 1000.0 + 0.45)
        cur = shot()
        sh = vision.shift_by_template(img, cur, threshold=0.62)
        if sh is None:
            s2 = vision.scroll(img, cur)
            dx, dy = s2[0], s2[1]
        else:
            dx, dy = sh[0], sh[1]
        if abs(dx) + abs(dy) > 25:
            return dx, dy, True, cur, off
    return 0.0, 0.0, False, cur, None


def teleport_to(area: str, rec) -> bool:
    """用傳送石到指定地區（動態找愛心、冷卻就等、選單靜止才點格子）。"""
    if menu_share(adb.screencap()) > 0.10:
        adb.tap(720, 300)
        time.sleep(1.2)
    opened = False
    for i in range(6):
        s = shot()
        b, g, r = cv2.split(s.astype("int16"))
        m = (((b > 150) & (b > r + 40) & (r < 130))[:, 1255:1420] & True).astype(np.uint8) * 255
        roi = m[600:2600]
        n, _l, st, ce = cv2.connectedComponentsWithStats(roi, 8)
        if n > 1:
            k = max(range(1, n), key=lambda j: st[j][4])
            if st[k][4] > 300:
                hx, hy = int(ce[k][0]) + 1255, int(ce[k][1]) + 600
                adb.tap(hx, hy)
                time.sleep(2.4)
                if menu_share(shot()) > 0.10:
                    opened = True
                    break
        rec({"note": "傳送石沒開 → 等 6 秒再試", "try": i})
        time.sleep(6.0)
    if not opened:
        return False
    tpl = TILE[area]
    for i in range(8):
        s1 = shot()
        time.sleep(1.3)
        s2 = shot()
        r1 = vision.find(s1, tpl, 0.85)
        r2 = vision.find(s2, tpl, 0.85)
        if r1 and r2 and abs(r1[0] - r2[0]) < 4 and abs(r1[1] - r2[1]) < 4:
            adb.tap(r2[0], r2[1])
            time.sleep(3.0)
            ok = menu_share(shot()) < 0.10
            rec({"note": f"傳送到 {area}", "ok": ok})
            return ok
        adb.swipe(720, 2300, 720, 1900, 600)
        time.sleep(1.6)
    rec({"note": f"找不到 {area} 的格子"})
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("minutes", type=float, nargs="?", default=20.0)
    ap.add_argument("--from", dest="start_area", default="village", choices=list(TILE))
    ap.add_argument("--idle", type=int, default=14, help="連續幾步看不到目標就換地區")
    args = ap.parse_args()

    run = Path("captures") / time.strftime("area_%Y%m%d_%H%M%S")
    run.mkdir(parents=True, exist_ok=True)
    log = (run / "log.jsonl").open("w", encoding="utf-8")

    def rec(o):
        o["t"] = time.strftime("%H:%M:%S")
        log.write(json.dumps(o, ensure_ascii=False) + "\n")
        log.flush()
        print(json.dumps(o, ensure_ascii=False))

    area = args.start_area
    other = "start" if area == "village" else "village"
    rec({"note": "start", "area": area})
    if not teleport_to(area, rec):
        rec({"note": "一開始就傳送失敗 → 結束"})
        return

    idle = 0
    hits = 0
    hp_start = hp_now = None
    heading = 0.0
    t0 = time.time()
    deadline = t0 + args.minutes * 60
    step = 0
    same = 0
    last_xy = None

    while time.time() < deadline:
        step += 1
        img = shot()
        if menu_share(img) > 0.10:
            adb.tap(720, 300)
            time.sleep(1.2)
            continue

        box = rest_box(img)
        if box:
            rec({"step": step, "note": "偵測到休息白框 → 點它", "at": list(box)})
            adb.tap(box[0], box[1])
            time.sleep(1.5)
            for _k in range(12):
                time.sleep(0.6)
                if rest_box(shot()) is None:
                    break
            continue

        text, _h = hp.read(img)
        if text:
            if hp_start is None:
                hp_start = text
            hp_now = text

        cands = targets(img)
        if not cands:
            idle += 1
            if idle >= args.idle:
                rec({"step": step, "note": f"{area} 沒目標了 → 換到 {other}", "idle": idle})
                if teleport_to(other, rec):
                    area, other = other, area
                    idle = 0
                    heading = 0.0
                    continue
                rec({"note": "傳送失敗 → 繼續原地找"})
                idle = 0
            dx, dy, moved, img, off = drag(img, math.cos(heading), math.sin(heading), 260)
            if not moved:
                heading += math.pi / 2
            rec({"step": step, "note": "探索", "heading": round(math.degrees(heading)), "idle": idle, "hits": hits})
            continue

        d, tx, ty, kind = cands[0]
        if last_xy and math.hypot(tx - last_xy[0], ty - last_xy[1]) < 70:
            same += 1
        else:
            same = 0
        last_xy = (tx, ty)
        if same >= 4 and len(cands) > 1:
            d, tx, ty, kind = cands[1]
            same = 0

        vx, vy = tx - ANCHOR[0], ty - ANCHOR[1]
        norm = max(abs(vx), abs(vy), 1)
        if d <= 80:
            time.sleep(0.55)
            cur = shot()
            if vision.find(cur, DMG_TPL, threshold=0.70):
                hits += 1
                cv2.imwrite(str(run / f"hit_{hits:03d}.png"), cur)
            rec({"step": step, "note": "貼上目標", "kind": kind, "d": round(d), "hits": hits})
            heading = math.atan2(vy, vx) + math.pi / 2
            idle = 0
            continue
        dx, dy, moved, img, off = drag(img, vx / norm, vy / norm, min(320, max(120, d * 0.85)))
        rec({"step": step, "note": "走向目標", "kind": kind, "d": round(d), "moved": moved,
             "繞": off, "hits": hits, "area": area})
        idle = 0

    mins = (time.time() - t0) / 60
    rate = ""
    try:
        if hp_start and hp_now and "?" not in hp_start and "?" not in hp_now:
            a, b = int(hp_start.split("/")[0]), int(hp_now.split("/")[0])
            rate = f"，生命值 {a}→{b}（{a-b} 次揮鎬 / {mins:.1f} 分 = {(a-b)/max(mins,0.1):.1f} 次/分）"
    except Exception:
        pass
    log.close()
    print(f"done: {hits} 次拍到命中{rate}, 記錄在 {run}")


if __name__ == "__main__":
    main()

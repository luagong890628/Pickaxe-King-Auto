"""循環執行器：傳送小村莊 → 走小村莊段 → 傳送起始之地 → 走起始之地段 → 110 秒後重複。

設計重點
- 每段都從「傳送落地點」開始跑，所以誤差不累積（每圈重置）。
- 步伐是錄好的相對位移，照著拖曳；被擋住時自動換角度重試（備用）。
- 路線裡若走到小屋，出現「在小屋裡休息」白框時會自動點它（白框是用顏色/尺寸偵測，不靠舊範本）。
- 不寫「血量歸零自動找小屋」——使用者要求休息由路線固定安排。
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
HEART = (1275, 1715)
TILES = {
    "village": cv2.imread("captures/tpl_tile_village.png"),
    "start": cv2.imread("captures/tpl_tile_start.png"),
}


def shot():
    return vision.normalize_brightness(adb.screencap())


def menu_share(img) -> float:
    mid = img[560:2840, 60:1380]
    return float((np.abs(mid.astype(np.int16) - MENU_BG).max(axis=2) < 45).mean())


def rest_dialog_box(img):
    """找「在小屋裡休息」白框（大面積近白矩形）→ 回傳中心或 None。"""
    b, g, r = cv2.split(img.astype("int16"))
    white = ((b > 215) & (g > 215) & (r > 215)).astype(np.uint8) * 255
    roi = white[1000:2700, 150:1350]
    n, _l, st, ce = cv2.connectedComponentsWithStats(cv2.morphologyEx(roi, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8), 3), 8)
    best = None
    for i in range(1, n):
        if st[i][4] > 40000 and 600 < st[i][2] < 1250 and 120 < st[i][3] < 320:
            if best is None or st[i][4] > st[best][4]:
                best = i
    if best is None:
        return None
    return int(ce[best][0]) + 150, int(ce[best][1]) + 1000


def drag(img, vx, vy, dist=250):
    """朝 (vx,vy) 拖曳；移動距離由「按住時間」控制（實測 ≈315px/秒）。

    dist 是「想要移動的距離」，會換算成按住時間（並夾在 250~2000ms）。
    """
    base = math.atan2(vy, vx)
    cur = img
    hold_ms = int(min(2000, max(250, dist / 315.0 * 1000)))
    drag_len = 260                              # 拖曳長度固定（這是搖桿偏移量，不是距離）
    for off in (0, 40, -40, 80, -80, 135, -135, 180):
        a = base + math.radians(off)
        adb.swipe(*DRAG, int(DRAG[0] + math.cos(a) * drag_len), int(DRAG[1] + math.sin(a) * drag_len), hold_ms)
        time.sleep(max(1.2, hold_ms / 1000.0 + 0.35))
        cur = shot()
        sh = vision.shift_by_template(img, cur, threshold=0.62)
        if sh is None:
            s2 = vision.scroll(img, cur)
            dx, dy = s2[0], s2[1]
        else:
            dx, dy = sh[0], sh[1]
        if abs(dx) + abs(dy) > 25:
            return dx, dy, True, cur
    return 0.0, 0.0, False, cur


def close_menu():
    """關選單：點面板外的空白處（實測有效；點面板內會選到地區）。"""
    adb.tap(720, 300)
    time.sleep(1.2)
    if menu_share(shot()) > 0.10:
        adb.tap(720, 3060)
        time.sleep(1.2)


def find_heart(img):
    """偵測右側的藍色愛心（傳送石）位置——它是會移動/有冷卻的，寫死座標會點空。"""
    b, g, r = cv2.split(img.astype("int16"))
    m = ((b > 150) & (b > r + 40) & (r < 130)).astype(np.uint8) * 255
    roi = m[600:2600, 1255:1435]          # 只看右側 UI 欄，避免把河水當成愛心
    n, _l, st, ce = cv2.connectedComponentsWithStats(roi, 8)
    best = None
    for i in range(1, n):
        a = st[i][4]
        if a > 800 and (best is None or a > st[best][4]):
            best = i
    if best is None:
        return None
    return int(ce[best][0]) + 1255, int(ce[best][1]) + 600


def teleport(area: str, rec) -> bool:
    if menu_share(adb.screencap()) > 0.10:
        close_menu()
    # 點傳送石（可能還在冷卻）：最多試 5 次，每次重新偵測位置
    opened = False
    for _try in range(5):
        s = shot()
        h = find_heart(s)
        if h:
            adb.tap(h[0], h[1])
            time.sleep(2.4)
            if menu_share(shot()) > 0.10:
                opened = True
                rec({"note": "傳送選單已開啟", "heart": list(h)})
                break
        rec({"note": "傳送石沒開（可能冷卻中）→ 等 6 秒再試", "try": _try})
        time.sleep(6.0)
    if not opened:
        return False
    tile = TILES[area]
    for i in range(8):
        s1 = shot()
        time.sleep(1.3)
        s2 = shot()
        r1 = vision.find(s1, tile, 0.85)
        r2 = vision.find(s2, tile, 0.85)
        if r1 and r2 and abs(r1[0] - r2[0]) < 4 and abs(r1[1] - r2[1]) < 4:
            adb.tap(r2[0], r2[1])
            time.sleep(3.0)
            ok = menu_share(shot()) < 0.10
            rec({"note": f"傳送到{area}", "ok": ok, "tile": [r2[0], r2[1]]})
            return ok
        adb.swipe(720, 2300, 720, 1900, 600)
        time.sleep(1.6)
    rec({"note": f"傳送到{area}失敗（找不到格子）"})
    return False


def run_steps(name, steps, rec, run, deadline):
    """照錄好的步伐走一段：每一步都閉環（走完量誤差，不夠就補走）。

    為什麼要閉環：一次拖曳造成的位移不只取決於拖曳長度（實測同長度可能 200~500px），
    開環照長度走會每步都少走、整條路徑被壓縮。改成「量到走夠了才換下一步」。
    """
    img = shot()
    hits = 0
    for i, (sx, sy) in enumerate(steps):
        if time.time() > deadline:
            break
        acc = [0.0, 0.0]
        for _att in range(6):
            box = rest_dialog_box(img)
            if box:
                rec({"note": "偵測到休息白框 → 點它", "at": list(box)})
                adb.tap(box[0], box[1])
                time.sleep(1.5)
                for _k in range(12):
                    time.sleep(0.6)
                    if rest_dialog_box(shot()) is None:
                        break
                img = shot()
                continue
            ex, ey = sx - acc[0], sy - acc[1]
            err = math.hypot(ex, ey)
            if err < 35:
                break
            dx, dy, moved, img = drag(img, ex / err, ey / err, dist=min(320, max(110, err * 1.15)))
            acc[0] += -dx
            acc[1] += -dy
            if not moved:
                break
        rec({"note": f"{name} 步伐", "i": i, "目標": [round(sx), round(sy)],
             "實走": [round(acc[0]), round(acc[1])], "誤差": round(math.hypot(sx-acc[0], sy-acc[1])), "hits": hits})
        time.sleep(0.35)                      # 到點小停（讓揮鎬砍一下）
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("minutes", type=float, nargs="?", default=30.0)
    ap.add_argument("--cycle", type=float, default=110.0)
    args = ap.parse_args()

    seg = {}
    for name in ("village_loop", "start_loop"):
        d = json.load(open(f"data/steps/{name}.json", encoding="utf-8"))
        seg[name] = [(float(x), float(y)) for x, y in d["steps"]]
    run = Path("captures") / time.strftime("cycle_%Y%m%d_%H%M%S")
    run.mkdir(parents=True, exist_ok=True)
    log = (run / "log.jsonl").open("w", encoding="utf-8")

    def rec(o):
        o["t"] = time.strftime("%H:%M:%S")
        log.write(json.dumps(o, ensure_ascii=False) + "\n")
        log.flush()
        print(json.dumps(o, ensure_ascii=False))

    rec({"note": "start", "village_steps": len(seg["village_loop"]), "start_steps": len(seg["start_loop"])})
    t0 = time.time()
    deadline = t0 + args.minutes * 60
    lap = 0
    hp_start = hp_now = None

    while time.time() < deadline:
        lap += 1
        lap_t0 = time.time()
        rec({"note": f"=== 第 {lap} 圈 ==="})
        if not teleport("village", rec):
            break
        run_steps("小村莊", seg["village_loop"], rec, run, deadline)
        if not teleport("start", rec):
            break
        run_steps("起始之地", seg["start_loop"], rec, run, deadline)
        text, _h = hp.read(shot())
        if text:
            hp_now = text
            if hp_start is None:
                hp_start = text
        rec({"note": "本圈完成", "lap": lap, "hp": text})
        if args.cycle:
            wait = args.cycle - (time.time() - lap_t0)
            if wait > 0:
                rec({"note": f"等待 {round(wait)} 秒（等樹重生）"})
                while wait > 0 and time.time() < deadline:
                    time.sleep(min(5, wait))
                    wait = args.cycle - (time.time() - lap_t0)

    mins = (time.time() - t0) / 60
    rate = ""
    try:
        if hp_start and hp_now and "?" not in hp_start and "?" not in hp_now:
            a, b = int(hp_start.split("/")[0]), int(hp_now.split("/")[0])
            rate = f"，生命值 {a}→{b}（{a-b} 次揮鎬 / {mins:.1f} 分 = {(a-b)/max(mins,0.1):.1f} 次/分）"
    except Exception:
        pass
    log.close()
    print(f"done: {lap} 圈{rate}, 記錄在 {run}")


if __name__ == "__main__":
    main()

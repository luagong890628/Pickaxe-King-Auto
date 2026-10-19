"""重播步伐（機械化循環）：每一圈都先傳送回固定落點，再照錄好的步伐走一遍。

因為每圈都從「傳送落地點」重新開始，誤差不會累積（這是這版最重要的設計）。
流程：傳送 → 走步伐(一路砍) → 生命值歸零就回帳篷休息 → 走完 → 再傳送 → 下一圈。
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
DMG_TPL = cv2.imread("captures/tpl_dmg151.png")
TENT_TPL = cv2.imread("captures/tpl_tent.png")
REST_TPL = cv2.imread("captures/tpl_rest_dialog.png")
TILE_START = cv2.imread("captures/tpl_tile_start.png")
HEART = (1275, 1715)


def shot():
    return vision.normalize_brightness(adb.screencap())


def menu_share(img) -> float:
    mid = img[560:2840, 60:1380]
    return float((np.abs(mid.astype(np.int16) - MENU_BG).max(axis=2) < 45).mean())


def drag(img, vx, vy, dist=250):
    """朝 (vx,vy) 拖曳，沒動就換角度重試。回傳 (dx, dy, moved, frame)。"""
    base = math.atan2(vy, vx)
    cur = img
    for off in (0, 40, -40, 80, -80, 135, -135, 180):
        a = base + math.radians(off)
        adb.swipe(*DRAG, int(DRAG[0] + math.cos(a) * dist), int(DRAG[1] + math.sin(a) * dist), 620)
        time.sleep(1.25)
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


def teleport_home(run) -> bool:
    """傳送回起始之地（選單靜止才點，避免慣性滑動點錯）。"""
    cur = adb.screencap()
    if menu_share(cur) > 0.10:
        adb.swipe(*DRAG, DRAG[0] - 380, DRAG[1], 900)
        time.sleep(1.0)
    adb.tap(*HEART)
    time.sleep(2.2)
    for _ in range(8):
        s1 = shot()
        time.sleep(1.3)
        s2 = shot()
        r1 = vision.find(s1, TILE_START, 0.75)
        r2 = vision.find(s2, TILE_START, 0.75)
        if r1 and r2 and abs(r1[0] - r2[0]) < 4 and abs(r1[1] - r2[1]) < 4:
            adb.tap(r2[0], r2[1])
            time.sleep(3.0)
            ok = menu_share(adb.screencap()) < 0.10
            if ok:
                cv2.imwrite(str(run / f"landing_{time.strftime('%H%M%S')}.png"), shot())
            return ok
        adb.swipe(720, 2300, 720, 1900, 600)
        time.sleep(1.6)
    return False


def rest(run, rec) -> None:
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
            return
        t = vision.find(s, TENT_TPL, threshold=0.82)
        if t:
            n = max(abs(t[0] - ANCHOR[0]), abs(t[1] - ANCHOR[1]), 1)
            drag(s, (t[0] - ANCHOR[0]) / n, (t[1] - ANCHOR[1]) / n, 250)
        else:
            drag(s, 0, 1, 250)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("minutes", type=float, nargs="?", default=20.0)
    ap.add_argument("--passes", type=int, default=0)
    ap.add_argument("--cycle", type=float, default=0, help="每圈間隔秒數（例如 110：走完等補到 110 秒再下一圈）")
    args = ap.parse_args()

    d = json.load(open(f"data/steps/{args.name}.json", encoding="utf-8"))
    steps = [(float(x), float(y)) for x, y in d["steps"]]
    run = Path("captures") / time.strftime("replay_%Y%m%d_%H%M%S")
    run.mkdir(parents=True, exist_ok=True)
    log = (run / "log.jsonl").open("w", encoding="utf-8")

    def rec(o):
        o["t"] = time.strftime("%H:%M:%S")
        log.write(json.dumps(o, ensure_ascii=False) + "\n")
        log.flush()
        print(json.dumps(o, ensure_ascii=False))

    rec({"note": "start", "steps": len(steps)})
    hits = 0
    passes = 0
    hp_start = hp_now = None
    t0 = time.time()
    deadline = t0 + args.minutes * 60

    while time.time() < deadline:
        pass_start = time.time()
        # 每圈開始：傳送回落點（誤差歸零）
        rec({"note": "傳送回落點（重置位置）"})
        if not teleport_home(run):
            rec({"note": "傳送失敗 → 停止"})
            break
        img = shot()

        for i, (sx, sy) in enumerate(steps):
            if time.time() > deadline:
                break
            text, _h = hp.read(img)
            if text:
                if hp_start is None:
                    hp_start = text
                hp_now = text
            if text and text.startswith("0/"):
                rec({"note": "生命值歸零 → 休息", "hp": text, "step": i, "hits": hits})
                rest(run, rec)
                img = shot()
                continue
            n = max(abs(sx), abs(sy), 1)
            dx, dy, moved, img = drag(img, sx / n, sy / n, dist=min(300, max(120, math.hypot(sx, sy))))
            if vision.find(img, DMG_TPL, threshold=0.70):
                hits += 1
                cv2.imwrite(str(run / f"hit_{hits:03d}.png"), img)
            rec({"note": "步伐", "i": i, "目標": [round(sx), round(sy)], "moved": moved, "hits": hits})

        passes += 1
        rec({"note": "完成一圈", "passes": passes, "hits": hits})
        if args.passes and passes >= args.passes:
            break
        if args.cycle:
            wait = args.cycle - (time.time() - pass_start)
            if wait > 0:                     # 走完還不到 110 秒 → 等補滿再下一圈（讓樹重生）
                rec({"note": f"等待 {round(wait)} 秒（等樹重生）"})
                while wait > 0 and time.time() < deadline:
                    time.sleep(min(5, wait))
                    wait = args.cycle - (time.time() - pass_start)

    mins = (time.time() - t0) / 60
    rate = ""
    try:
        if hp_start and hp_now and not hp_start.startswith("?") and not hp_now.startswith("?"):
            a, b = int(hp_start.split("/")[0]), int(hp_now.split("/")[0])
            rate = f"，生命值 {a}→{b}（約 {a-b} 次揮鎬 / {mins:.1f} 分 = {(a-b)/max(mins,0.1):.1f} 次/分）"
    except Exception:
        pass
    log.close()
    print(f"done: {passes} 圈, {hits} 次拍到命中{rate}, 記錄在 {run}")


if __name__ == "__main__":
    main()

"""自己找目標砍素材（v15）：純畫面座標追蹤，不依賴絕對定位。

why：實測發現畫面位移量測誤差很大（畫面裡有雞/NPC/落葉在動，resp 只有 0.3），
累積成世界座標會漂掉（走幾步就偏幾百 px）。所以改成：
- 每一格重新偵測畫面裡的樹冠/石頭，挑「離角色最近的」當目標，朝它走。
- 目標消失（被砍掉）＝命中；目標一直在（走不到／被擋）＝換下一個。
- HP=0 才回帳篷休息；其餘時間一直在區內走動砍。
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
DRAG_ORIGIN = (720, 2000)
MENU_BG = np.array([255, 211, 143])
TENT_TPL = cv2.imread("captures/tpl_tent.png")
REST_TPL = cv2.imread("captures/tpl_rest_dialog.png")
DMG_TPL = cv2.imread("captures/tpl_dmg151.png")
HIT_R = 78          # 目標進到這個距離就算「貼上」（樹幹就在腳邊）
MOVE_R = 130        # 目標再靠近就停手（等揮鎬）


def norm_shot():
    return vision.normalize_brightness(adb.screencap())


def menu_share(img) -> float:
    mid = img[560:2840, 60:1380]
    return float((np.abs(mid.astype(np.int16) - MENU_BG).max(axis=2) < 45).mean())


def targets(img):
    """畫面裡的樹冠/石頭目標，依離角色（ANCHOR）距離排序。"""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    out = []
    green = ((h > 45) & (h < 95) & (s > 150) & (v > 80)).astype(np.uint8) * 255
    green = cv2.morphologyEx(green, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8), 1)
    n, _l, st, _c = cv2.connectedComponentsWithStats(green, 8)
    for i in range(1, n):
        x, y, w, hh, a = st[i]
        if a < 2500 or y < 520 or y > 2880 or x < 210 or x > 1240:
            continue
        # 樹幹在樹冠底部下方：走到那裡才會撞到、觸發自動揮鎬
        tx = x + w / 2
        ty = min(y + hh + 36, 2860.0)
        d = math.hypot(tx - ANCHOR[0], ty - ANCHOR[1])
        if d < 45:
            continue
        out.append((d, float(tx), float(ty), "tree"))
    gray = ((s < 42) & (v > 115) & (v < 225)).astype(np.uint8) * 255
    n2, _l2, st2, _c2 = cv2.connectedComponentsWithStats(gray, 8)
    for i in range(1, n2):
        x, y, w, hh, a = st2[i]
        if a < 800 or a > 9000 or w > 170 or hh > 170 or y < 520 or y > 2880 or x < 210 or x > 1240:
            continue
        cx, cy = x + w / 2, y + hh / 2
        d = math.hypot(cx - ANCHOR[0], cy - ANCHOR[1])
        if d < 45:
            continue
        out.append((d, float(cx), float(cy), "stone"))
    out.sort()
    return out


def step_toward(sx, sy, d):
    vx, vy = sx - ANCHOR[0], sy - ANCHOR[1]
    n = max(abs(vx), abs(vy), 1)
    vx, vy = vx / n, vy / n
    pl = int(min(330, max(80, d * 0.75)))
    ms = int(min(800, max(280, pl * 2.2)))
    adb.swipe(*DRAG_ORIGIN, int(DRAG_ORIGIN[0] + vx * pl), int(DRAG_ORIGIN[1] + vy * pl), ms)
    return vx, vy


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("minutes", type=float, nargs="?", default=10.0)
    args = ap.parse_args()

    run = Path("captures") / time.strftime("h2_%Y%m%d_%H%M%S")
    run.mkdir(parents=True, exist_ok=True)
    log = (run / "log.jsonl").open("w", encoding="utf-8")

    def rec(o):
        o["t"] = time.strftime("%H:%M:%S")
        log.write(json.dumps(o, ensure_ascii=False) + "\n")
        log.flush()
        print(json.dumps(o, ensure_ascii=False))

    hits = 0
    misses = 0
    last_sig = None
    same = 0
    sweep_dir = 1              # 沒目標時的探索方向（左右交替）
    deadline = time.time() + args.minutes * 60
    step = 0
    target_kind = None

    while time.time() < deadline:
        step += 1
        img = norm_shot()

        if menu_share(img) > 0.10:
            adb.swipe(*DRAG_ORIGIN, DRAG_ORIGIN[0] - 380, DRAG_ORIGIN[1], 900)
            time.sleep(1.0)
            continue

        text, _d = hp.read(img)
        if text and text.startswith("0/"):
            rec({"step": step, "note": "生命值歸零 → 找帳篷休息", "hp": text})
            done = False
            for _i in range(50):
                s = norm_shot()
                r = vision.find(s, REST_TPL, threshold=0.72)
                if r:
                    adb.tap(r[0], r[1])
                    time.sleep(1.5)
                    for _k in range(14):
                        time.sleep(0.6)
                        if vision.find(norm_shot(), REST_TPL, threshold=0.72) is None:
                            done = True
                            break
                    break
                t = vision.find(s, TENT_TPL, threshold=0.80)
                if t:
                    step_toward(t[0], t[1], math.hypot(t[0] - ANCHOR[0], t[1] - ANCHOR[1]))
                else:
                    # 看不到帳篷：往南找（帳篷在起始之地南側）
                    adb.swipe(*DRAG_ORIGIN, DRAG_ORIGIN[0], DRAG_ORIGIN[1] + 230, 600)
                time.sleep(0.5)
            rec({"step": step, "note": "休息完成" if done else "休息失敗", "hits": hits})
            continue

        cands = targets(img)
        if not cands:
            adb.swipe(*DRAG_ORIGIN, DRAG_ORIGIN[0] + 300 * sweep_dir, int(DRAG_ORIGIN[1] - 90), 700)
            sweep_dir *= -1
            time.sleep(0.4)
            rec({"step": step, "note": "畫面內沒目標 → 往旁邊走", "hits": hits})
            continue

        d, tx, ty, kind = cands[0]
        sig = (round(tx / 40), round(ty / 40))
        if sig == last_sig:
            same += 1
        else:
            last_sig, same = sig, 0
        if same >= 5:                       # 同一個目標卡住 → 換下一個
            if len(cands) > 1:
                d, tx, ty, kind = cands[1]
                last_sig, same = (round(tx / 40), round(ty / 40)), 0
            else:
                adb.swipe(*DRAG_ORIGIN, int(DRAG_ORIGIN[0] - 260 * sweep_dir), int(DRAG_ORIGIN[1] + 160), 700)
                sweep_dir *= -1
                last_sig, same = None, 0
                continue

        if d <= HIT_R:
            time.sleep(0.5)
            cur = norm_shot()
            m = vision.find(cur, DMG_TPL, threshold=0.70)
            if m:
                hits += 1
                cv2.imwrite(str(run / f"hit_{hits:03d}.png"), cur)
            still = targets(cur)
            near = [c for c in still if math.hypot(c[1] - tx, c[2] - ty) < 80]
            rec({"step": step, "note": "貼上目標", "kind": kind, "d": round(d),
                 "砍掉": not near, "傷害數字": bool(m), "hits": hits})
            time.sleep(0.25)
            continue

        vx, vy = step_toward(tx, ty, d)
        rec({"step": step, "note": "走", "kind": kind, "d": round(d), "same": same, "hits": hits})
        time.sleep(0.18)

    log.close()
    print(f"done: {hits} 命中, 記錄在 {run}")


if __name__ == "__main__":
    main()

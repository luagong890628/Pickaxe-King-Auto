"""重播路線 v2：先用「全畫面比對」定位自己在哪一幀，再往下一幀走；每一步都持續重新定位。

v1 失敗原因：直接從第 0 幀硬走，而且只看位移量測 → 地形重複時會認錯地方、起點不符時整條歪掉。
v2 改法：
- 每一步都算「現在畫面 vs 所有關鍵幀」的全畫面相似度 → 知道自己在路線的哪一段。
- 目標永遠是「目前最像那幀的下一幀」→ 不會亂跳、也不會走反向。
- 走一步後重新定位；連續幾步沒進展就重新全域定位（恢復用）。
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
SCALE = 0.5
CMP = (360, 780)            # 比對用的縮圖尺寸（0.25x）
REACH = 45
DMG_TPL = cv2.imread("captures/tpl_dmg151.png")


def shot_pair():
    img = vision.normalize_brightness(adb.screencap())
    small = cv2.resize(img, None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_AREA)
    return img, small


def cmp_img(img):
    g = cv2.cvtColor(cv2.resize(img, CMP, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    return cv2.GaussianBlur(g, (7, 7), 0)


def menu_share(img) -> float:
    mid = img[560:2840, 60:1380]
    return float((np.abs(mid.astype(np.int16) - MENU_BG).max(axis=2) < 45).mean())


def shift_to(cur_small, tgt_small):
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
    args = ap.parse_args()

    d = json.load(open(f"captures/routes/{args.name}/meta.json", encoding="utf-8"))
    frames = [cv2.imread(f"captures/routes/{args.name}/{f['file']}") for f in d["frames"]]
    cmps = [cmp_img(f) for f in frames]
    print(f"路線 {args.name}：{len(frames)} 幀")

    run = Path("captures") / time.strftime("play2_%Y%m%d_%H%M%S")
    run.mkdir(parents=True, exist_ok=True)
    log = (run / "log.jsonl").open("w", encoding="utf-8")

    def rec(o):
        o["t"] = time.strftime("%H:%M:%S")
        log.write(json.dumps(o, ensure_ascii=False) + "\n")
        log.flush()
        print(json.dumps(o, ensure_ascii=False))

    def locate(cur_cmp, near=None):
        """回傳 (最佳幀索引, 分數, 前三名)。near=(lo,hi) 時只看這段（避免跳太遠）。"""
        best = []
        rng = range(len(cmps)) if near is None else range(max(0, near[0]), min(len(cmps), near[1]))
        for i in rng:
            diff = float(np.abs(cur_cmp.astype(np.int16) - cmps[i].astype(np.int16)).mean())
            best.append((diff, i))
        best.sort()
        return best[0][1], best[0][0], best[:3]

    hits = 0
    idx = None
    passes = 0
    step = 0
    stalled = 0
    last_dist = None
    deadline = time.time() + args.minutes * 60

    while time.time() < deadline:
        step += 1
        img, small = shot_pair()
        if menu_share(img) > 0.10:
            adb.swipe(*DRAG, DRAG[0] - 380, DRAG[1], 900)
            time.sleep(1.0)
            continue

        text, _h = hp.read(img)
        if text and text.startswith("0/"):
            rec({"step": step, "note": "生命值歸零 → 停止（休息流程另處理）", "hp": text, "hits": hits})
            break

        cur_cmp = cmp_img(img)
        # 定位：先看附近 ±3 幀，若都不像（分數差）再看全部
        near = None if idx is None else (idx - 3, idx + 4)
        cand, score, top3 = locate(cur_cmp, near)
        if score > 26 and idx is not None:                      # 附近都不像 → 全域重找
            cand2, score2, top32 = locate(cur_cmp, None)
            if score2 < score:
                cand, score, top3 = cand2, score2, top32
        if idx is None:
            idx = cand
            rec({"step": step, "note": "起始定位", "idx": idx, "分數": round(score, 1),
                 "前三": [(round(s, 1), i) for s, i in top3]})
        elif cand != idx and abs(cand - idx) <= 3:
            rec({"step": step, "note": "修正定位", "由": idx, "到": cand, "分數": round(score, 1)})
            idx = cand

        tgt = frames[min(idx + 1, len(frames) - 1)]
        dx, dy, q = shift_to(small, tgt)
        dist = math.hypot(dx, dy)

        if dist <= REACH:
            time.sleep(0.5)
            cur = vision.normalize_brightness(adb.screencap())
            if vision.find(cur, DMG_TPL, threshold=0.70):
                hits += 1
                cv2.imwrite(str(run / f"hit_{hits:03d}.png"), cur)
            idx += 1
            if idx >= len(frames):
                idx = 0
                passes += 1
                rec({"step": step, "note": "完成一圈", "passes": passes, "hits": hits})
            else:
                rec({"step": step, "note": "到幀", "idx": idx, "hits": hits})
            stalled = 0
            last_dist = None
            continue

        n = max(abs(dx), abs(dy), 1)
        vx, vy = -dx / n, -dy / n
        pl = int(min(340, max(90, dist * 0.9)))
        adb.swipe(*DRAG, int(DRAG[0] + vx * pl), int(DRAG[1] + vy * pl),
                  int(min(800, max(280, pl * 2.2))))
        time.sleep(1.4)
        after = vision.normalize_brightness(adb.screencap())
        if vision.find(after, DMG_TPL, threshold=0.70):
            hits += 1
            cv2.imwrite(str(run / f"hit_{hits:03d}.png"), after)
        after_cmp = cmp_img(after)
        c2, s2, _t = locate(after_cmp, (max(0, idx - 2), min(len(cmps), idx + 5)))
        small2 = cv2.resize(after, None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_AREA)
        dx2, dy2, q2 = shift_to(small2, tgt)
        d2 = math.hypot(dx2, dy2)
        improved = d2 < dist - 15
        stalled = 0 if improved else stalled + 1
        if stalled >= 5:
            rec({"step": step, "note": "沒進展 → 重新定位並跳下一幀", "idx": idx,
                 "殘餘": round(dist), "重定位": c2, "分數": round(s2, 1)})
            idx = min(c2 + 1, len(frames) - 1)
            stalled = 0
            continue
        rec({"step": step, "note": "走", "idx": idx, "前": round(dist), "後": round(d2),
             "q": round(q, 2), "自己像哪幀": c2, "分數": round(s2, 1),
             "移動": [round(after_cmp.shape[1] * 0), 0], "hits": hits})

    log.close()
    print(f"done: {passes} 圈, {hits} 命中, 記錄在 {run}")


if __name__ == "__main__":
    main()

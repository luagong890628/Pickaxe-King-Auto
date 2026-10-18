"""列掃砍素材（v13）：照使用者說的「從左到右一列一列走過去」。

- 區域範圍＝使用者標註生成點的外框（以地標為原點：起始之地＝帳篷、小村莊＝黃金樹）。
- 角色位置用里程計 + 地標校正持續追蹤，所以永遠知道「我現在在區域的哪裡」。
- 每一列的間距 140px（揮鎬範圍約一格，走過去周圍的樹/石頭會被自動揮鎬砍掉）。
- 走的途中每張截圖都檢查傷害數字 → 命中計數（證據圖存起來）。
- 只用拖曳；休息/傳送另外處理。
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
from sweep2 import ANCHOR, DRAG_ORIGIN, DMG, Tracker, menu_share, norm_shot, floor_kind, teleport_home

REST_TPL = cv2.imread("captures/tpl_rest_dialog.png")   # 「在小屋裡休息！/ 生命值將恢復。」白框


def go_rest(trk, run, log) -> bool:
    """生命值 0 時：走向帳篷（世界原點）→ 點休息對話框 → 等睡醒。"""
    for i in range(70):
        img = norm_shot()
        r = vision.find(img, REST_TPL, threshold=0.72)
        if r:
            log({"step": i, "note": "休息：點對話框", "at": [r[0], r[1]]})
            adb.tap(r[0], r[1])
            time.sleep(1.5)
            for _k in range(12):                     # 等睡醒（主角消失 → 回來）
                time.sleep(0.6)
                s2 = norm_shot()
                if vision.find(s2, REST_TPL, threshold=0.72) is None:
                    text, _d = hp.read(s2)
                    if text and not text.startswith("0/"):
                        log({"step": i, "note": "休息完成", "hp": text})
                        return True
            return False
        W, _m = trk.update(img)
        if W is None:
            log({"step": i, "note": "休息：途中找不到地標，退回"})
            return False
        sx, sy = ANCHOR[0] - W[0], ANCHOR[1] - W[1]     # 帳篷＝世界原點
        d = math.hypot(sx - ANCHOR[0], sy - ANCHOR[1])
        if d > 30:
            vx, vy = (sx - ANCHOR[0]) / max(abs(sx - ANCHOR[0]), abs(sy - ANCHOR[1]), 1), \
                     (sy - ANCHOR[1]) / max(abs(sx - ANCHOR[0]), abs(sy - ANCHOR[1]), 1)
            pl = int(min(340, max(70, d * 0.8)))
            adb.swipe(*DRAG_ORIGIN, int(DRAG_ORIGIN[0] + vx * pl), int(DRAG_ORIGIN[1] + vy * pl), int(min(800, max(260, pl * 2.2))))
        else:
            adb.swipe(*DRAG_ORIGIN, DRAG_ORIGIN[0] + 140, DRAG_ORIGIN[1], 520)   # 已到帳篷位置但沒對話框 → 微調
        time.sleep(0.35)
    log({"note": "休息：走不到帳篷"})
    return False

LANE_STEP = 140        # 列間距
WP_STEP = 250          # 同一列每走多遠停一下
REACH = 70

AREAS = {
    "start":   {"x": (-560, 540), "y": (-500, 220), "ref": "tent"},
    "village": {"x": (-550, 430), "y": (-580, 60),  "ref": "gold"},
}


def tree_px(img) -> int:
    """畫面可視區的綠色樹冠像素量（用來客觀看『樹有沒有變少』）。"""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    m = (h > 45) & (h < 95) & (s > 150) & (v > 80)
    return int(m[700:2900, 260:1140].sum())


def build_waypoints(box, start_w):
    """蛇行路徑：從離角色最近的列開始，左右來回。"""
    x0, x1 = box["x"]
    y0, y1 = box["y"]
    ys = list(range(y0 + 70, y1 - 40, LANE_STEP))
    ys.sort(key=lambda y: abs(y - start_w[1]))          # 先走離自己最近的那一列
    wps = []
    for k, y in enumerate(ys):
        xs = list(range(x0 + 50, x1 - 50, WP_STEP))
        if not xs or xs[-1] < x1 - 90:
            xs.append(x1 - 55)               # 補最右邊，避免漏掉東側
        if k % 2:
            xs = xs[::-1]
        wps.extend((x, y) for x in xs)
    return wps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("area", choices=list(AREAS))
    ap.add_argument("minutes", type=float, nargs="?", default=6.0)
    args = ap.parse_args()

    box = AREAS[args.area]
    trk = Tracker(box["ref"])
    run = Path("captures") / time.strftime(f"lanes_{args.area}_%Y%m%d_%H%M%S")
    run.mkdir(parents=True, exist_ok=True)
    log = (run / "log.jsonl").open("w", encoding="utf-8")

    def rec(o):
        o["t"] = time.strftime("%H:%M:%S")
        log.write(json.dumps(o, ensure_ascii=False) + "\n")
        log.flush()
        print(json.dumps(o, ensure_ascii=False))

    hits = 0
    progress = {}
    wp_i = None
    wps = None
    deadline = time.time() + args.minutes * 60
    step = 0
    stall = {}

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
            go_rest(trk, run, rec)
            continue

        W, _moved = trk.update(img)
        if W is None:
            rec({"step": step, "note": "找不到地標 → 傳送回起始之地"})
            if args.area == "start" and teleport_home(run):
                trk.prev = None
            else:
                adb.swipe(*DRAG_ORIGIN, DRAG_ORIGIN[0], DRAG_ORIGIN[1] - 330, 700)
                time.sleep(0.6)
            continue

        if args.area == "start" and floor_kind(img) == "darkgreen":
            rec({"step": step, "note": "地板深綠 → 飄出起始之地，傳送回來", "W": [round(W[0]), round(W[1])]})
            if teleport_home(run):
                trk.prev = None
            continue

        if wps is None:
            wps = build_waypoints(box, W)
            wp_i = 0
            rec({"step": step, "note": "路徑規劃", "waypoints": len(wps), "W": [round(W[0]), round(W[1])]})

        if wp_i >= len(wps):
            rec({"step": step, "note": "全部走完", "hits": hits, "tree_px": tree_px(img)})
            break

        tx, ty = wps[wp_i]
        sx, sy = ANCHOR[0] + tx - W[0], ANCHOR[1] + ty - W[1]
        d = math.hypot(sx - ANCHOR[0], sy - ANCHOR[1])

        if d <= REACH:
            time.sleep(0.35)
            wp_i += 1
            continue

        vx, vy = sx - ANCHOR[0], sy - ANCHOR[1]
        n = max(abs(vx), abs(vy), 1)
        vx, vy = vx / n, vy / n
        # 拖曳長度依剩餘距離縮放（固定 340px 會衝過頭 → 來回震盪）
        pl = int(min(340, max(70, d * 0.8)))
        ms = int(min(800, max(260, pl * 2.2)))
        adb.swipe(*DRAG_ORIGIN, int(DRAG_ORIGIN[0] + vx * pl), int(DRAG_ORIGIN[1] + vy * pl), ms)
        time.sleep(0.18)
        cur = norm_shot()
        m = vision.find(cur, DMG, threshold=0.70)
        if m:
            hits += 1
            cv2.imwrite(str(run / f"hit_{hits:03d}.png"), cur)
        dx, dy, resp = vision.scroll(img, cur)
        moved = resp > 0.3 and (abs(dx) > 8 or abs(dy) > 8)
        bd, cnt = progress.get(wp_i, (d, 0))
        if d < bd - 8:
            progress[wp_i] = (d, 0)
        else:
            cnt += 1
            progress[wp_i] = (bd, cnt)
            if cnt >= 6:                      # 一直靠近不了 → 這個航點被擋住，跳過
                rec({"step": step, "note": "航點走不到 → 跳過", "wp": wp_i, "d": round(d)})
                wp_i += 1
                continue
        k = stall.get(wp_i, 0)
        stall[wp_i] = 0 if moved else k + 1
        if not moved and stall[wp_i] < 5:
            # 撞到東西 → 先往側向滑一步繞開，再繼續朝目標走
            px, py = (-vy, vx) if stall[wp_i] % 2 else (vy, -vx)
            adb.swipe(*DRAG_ORIGIN, int(DRAG_ORIGIN[0] + px * 240), int(DRAG_ORIGIN[1] + py * 240), 520)
            time.sleep(0.25)
        if stall[wp_i] >= 5:
            rec({"step": step, "note": "這格走不到 → 跳過", "wp": wp_i, "d": round(d)})
            wp_i += 1
        rec({"step": step, "note": "走", "wp": wp_i, "d": round(d), "moved": moved,
             "hits": hits, "W": [round(W[0]), round(W[1])], "tree_px": tree_px(cur)})
        if step % 15 == 0:
            cv2.imwrite(str(run / f"frame_{step:04d}.png"), cur)

    log.close()
    print(f"done: {wp_i}/{len(wps) if wps else 0} 個航點, {hits} 命中, 記錄在 {run}")


if __name__ == "__main__":
    main()

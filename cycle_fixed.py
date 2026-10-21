"""機械化固定流程：小村莊 → 起始之地 → 等 10 秒 → 重複。

全部固定座標、固定步數，不做任何畫面偵測（只有「位移量測」用來記錄走了多少）。

流程
  1. 點傳送石 (1340,1670) → 等選單
  2. 選單往南滑 500ms（內容上移 416px）→ 點小村莊 (330,1464)
  3. 往北 3 步 → 左1 北1 右2 南1
  4. 點傳送石 → 滑 → 點起始之地 (720,1434)
  5. 往北 2 步 → 點 (721,1839) 休息
  6. 左1 北1 右2 南1
  7. 等 10 秒 → 回 1

實測座標（2026-10-20 measure_teleport.py）
  愛心 (1340,1670) 分數 1.00
  手指往上滑 500ms（內容往上 416px）：小村莊 (330,1464)、起始之地 (720,1434)

用法：
    python cycle_fixed.py --minutes 240
    python cycle_fixed.py --minutes 5 --dry-run     # 只印流程不動手機
"""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

from pkauto import adb, vision

# ---- 固定座標 ----
HEART = (1340, 1670)
# 手指往上滑（內容往上）：避免之後上方新增地區時格子位置被推走
MENU_SCROLL_FROM = (720, 2600)
MENU_SCROLL_TO = (720, 2350)
MENU_SCROLL_MS = 500
TILE = {"village": (330, 1464), "start": (720, 1434)}
REST_TAP = (721, 1839)

# ---- 固定路線 ----
DRAG = (720, 2600)
DRAG_LEN = 250
STEP_PX = 300.0        # 每步想走的 px（按住時間 = STEP_PX / PPS * 1000 ms）
PPS = 345.0            # 實測 ≈345px/秒（按住 952ms 走 328px；315 是早期低估值）
DIRS = {"N": (0, -1), "S": (0, 1), "L": (-1, 0), "R": (1, 0)}
NAMES = {"N": "北", "S": "南", "L": "西", "R": "東"}

VILLAGE_NORTH = 3
START_NORTH = 2
SWEEP = [("L", 1), ("N", 1), ("R", 2), ("S", 1)]
MERGE_NORTH = True      # 往北的多步合併成「一次按住」（少一次截圖量測、走得順）
MAX_HOLD_MS = 3000      # 單次按住上限；超過就自動拆段

MENU_BG = (255, 211, 143)      # 傳送選單底色（BGR），用來確認選單有沒有關掉


def menu_still_open(img):
    import numpy as np
    bg = np.array(MENU_BG)
    mid = img[560:2840, 60:1380]
    return float((np.abs(mid.astype(np.int16) - bg).max(axis=2) < 45).mean()) > 0.10


def shot():
    return vision.normalize_brightness(adb.screencap())


def step(img, d, px=None):
    """一步 = 一次拖曳；距離由按住時間決定（px 預設 STEP_PX）。"""
    px = STEP_PX if px is None else float(px)
    vx, vy = DIRS[d]
    hold = int(px / PPS * 1000)
    a = math.atan2(vy, vx)
    adb.swipe(DRAG[0], DRAG[1],
              int(DRAG[0] + math.cos(a) * DRAG_LEN),
              int(DRAG[1] + math.sin(a) * DRAG_LEN), hold)
    time.sleep(hold / 1000.0 + 0.45)
    cur = shot()
    sh = vision.shift_by_template(img, cur, threshold=0.6)
    dx, dy = (sh[0], sh[1]) if sh else tuple(vision.scroll(img, cur)[:2])
    return dx, dy, cur


def teleport(area, rec):
    """機械化傳送：點愛心 → 滑選單 → 點格子。"""
    adb.tap(*HEART)
    time.sleep(2.2)
    adb.swipe(*MENU_SCROLL_FROM, *MENU_SCROLL_TO, MENU_SCROLL_MS)   # 手指往上＝內容往上（上方擴增不影響）
    time.sleep(1.3)
    adb.tap(*TILE[area])
    time.sleep(2.6)
    opened = menu_still_open(shot())
    rec({"note": f"傳送 {area}", "選單還開著": opened})
    if opened:                      # 點歪了：再點一次同一個固定位置
        adb.tap(*TILE[area])
        time.sleep(3.0)
        rec({"note": f"傳送 {area} 重試", "選單還開著": menu_still_open(shot())})


REST_WAIT = 3.2          # 點擊休息後等動畫（原本 4.5 秒太長，實測 3 秒就結束）


def rest(rec, img, label):
    adb.tap(*REST_TAP)
    time.sleep(REST_WAIT)
    img = shot()
    rec({"note": f"{label} 休息（點固定座標）"})
    return img


def step_merge(img, d, px):
    """一次走完 px（超過 MAX_HOLD_MS 才平均拆段）。回傳累計 shift。"""
    n = max(1, math.ceil(px / PPS * 1000 / MAX_HOLD_MS))
    seg = px / n
    tx = ty = 0.0
    for _ in range(n):
        dx, dy, img = step(img, d, seg)
        tx += dx
        ty += dy
    return tx, ty, img


def walk(img, steps, rec, label):
    if steps <= 0:
        return img
    if not MERGE_NORTH:
        for i in range(steps):
            dx, dy, img = step(img, "N")
            rec({"note": f"{label} 北 {i+1}/{steps}", "shift": [round(dx), round(dy)]})
        return img
    px = STEP_PX * steps
    dx, dy, img = step_merge(img, "N", px)
    rec({"note": f"{label} 北 {steps} 步合併（{px:.0f}px）", "shift": [round(dx), round(dy)]})
    return img


def sweep(img, rec, label):
    for d, n in SWEEP:
        for i in range(n):
            dx, dy, img = step(img, d)
            rec({"note": f"{label} {NAMES[d]} {i+1}/{n}", "shift": [round(dx), round(dy)]})
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=240)
    ap.add_argument("--wait", type=float, default=30)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    def north_text(steps):
        if MERGE_NORTH:
            px = STEP_PX * steps
            return f"北 {steps} 步合併（{px:.0f}px → 按住 {px / PPS * 1000:.0f}ms）"
        return f"北 {steps} 步 × {STEP_PX:.0f}px"

    plan = [
        "傳送小村莊", north_text(VILLAGE_NORTH), "掃描 L1 N1 R2 S1",
        "傳送起始之地", north_text(START_NORTH), "點 (721,1839) 休息", "掃描 L1 N1 R2 S1",
        f"等 {args.wait:.0f} 秒",
    ]
    if args.dry_run:
        print("流程：")
        for i, p in enumerate(plan, 1):
            print(f"  {i}. {p}")
        print(f"固定座標：愛心{HEART} 格子{TILE} 休息{REST_TAP}")
        return

    run = Path("captures") / time.strftime("fixed_%Y%m%d_%H%M%S")
    run.mkdir(parents=True, exist_ok=True)
    log = (run / "log.jsonl").open("w", encoding="utf-8")

    def rec(o):
        o["t"] = time.strftime("%H:%M:%S")
        log.write(json.dumps(o, ensure_ascii=False) + "\n")
        log.flush()
        print(json.dumps(o, ensure_ascii=False), flush=True)

    rec({"note": "開始", "wait": args.wait, "分鐘": args.minutes})
    t0 = time.time()
    deadline = t0 + args.minutes * 60
    cycles = 0

    while time.time() < deadline:
        cycles += 1
        rec({"note": f"=== 第 {cycles} 輪 ==="})

        teleport("village", rec)
        img = shot()
        img = walk(img, VILLAGE_NORTH, rec, "小村莊")
        img = sweep(img, rec, "小村莊")

        teleport("start", rec)
        img = shot()
        img = walk(img, START_NORTH, rec, "起始之地")
        img = rest(rec, img, "起始之地")
        img = sweep(img, rec, "起始之地")

        rec({"note": "本輪結束", "已跑分鐘": round((time.time() - t0) / 60, 1)})
        end = min(time.time() + args.wait, deadline)
        while time.time() < end:
            time.sleep(min(2, end - time.time()))

    rec({"note": "收工", "cycles": cycles, "小時": round((time.time() - t0) / 3600, 2)})
    log.close()


if __name__ == "__main__":
    main()

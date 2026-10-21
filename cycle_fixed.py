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
STEP_PX = 300.0        # step() 沒指定 px 時的預設距離（路線都用 ROUTES 的 px）
PPS = 345.0            # 實測 ≈345px/秒（按住 952ms 走 328px；315 是早期低估值）
DIRS = {"N": (0, -1), "S": (0, 1), "L": (-1, 0), "R": (1, 0)}
NAMES = {"N": "北", "S": "南", "L": "西", "R": "東"}

MAX_HOLD_MS = 3000         # 單次按住上限；超過就平均拆段

# ---- 路線（照順序走；每項是 (方向, px)，("REST",) = 點固定座標休息）----
# 要調走路只改這裡；一段一個方向，距離直接用 px。
ROUTES = {
    "village": [
        ("N", 950.0),      # 1 往北（原「北 3 步」合併）
        ("L", 300.0),      # 2 掃描：左 1 步
        ("N", 300.0),      # 3 北 1 步
        ("R", 600.0),      # 4 東 2 步
        ("S", 300.0),      # 5 南 1 步
    ],
    "start": [
        ("N", 600.0),      # 1 往北（原「北 2 步」合併）
        ("REST",),         # 2 帳篷休息
        ("L", 300.0),      # 3 掃描：左 1 步
        ("N", 300.0),      # 4 北 1 步
        ("R", 600.0),      # 5 東 2 步
        ("S", 300.0),      # 6 南 1 步
    ],
}
LABEL = {"village": "小村莊", "start": "起始之地"}

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


def leg(img, d, px, rec, label):
    """一個方向走 px（按住時間＝px/PPS；超過 MAX_HOLD_MS 就平均拆段）。"""
    if px <= 0:
        return img
    n = max(1, math.ceil(px / PPS * 1000 / MAX_HOLD_MS))
    seg = px / n
    tx = ty = 0.0
    for _ in range(n):
        dx, dy, img = step(img, d, seg)
        tx += dx
        ty += dy
    note = f"{label} {NAMES[d]} {px:.0f}px" + (f"（拆 {n} 段）" if n > 1 else "")
    rec({"note": note, "shift": [round(tx), round(ty)]})
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=240)
    ap.add_argument("--wait", type=float, default=30)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.dry_run:
        for area in ("village", "start"):
            print(f"\n[{LABEL[area]}] 傳送落點 {TILE[area]}")
            for i, act in enumerate(ROUTES[area], 1):
                if act[0] == "REST":
                    print(f"  {i}. 休息（點 {REST_TAP}，等 {REST_WAIT}s）")
                    continue
                d, px = act
                n = max(1, math.ceil(px / PPS * 1000 / MAX_HOLD_MS))
                holds = " + ".join(f"{px / n / PPS * 1000:.0f}" for _ in range(n))
                extra = f"（拆 {n} 段）" if n > 1 else ""
                print(f"  {i}. {NAMES[d]} {px:.0f}px → 按住 {holds}ms{extra}")
        print(f"\n等 {args.wait:.0f} 秒後下一輪　固定座標：愛心{HEART} 格子{TILE} 休息{REST_TAP}")
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

        for area in ("village", "start"):
            teleport(area, rec)
            img = shot()
            for act in ROUTES[area]:
                if act[0] == "REST":
                    img = rest(rec, img, LABEL[area])
                else:
                    img = leg(img, act[0], act[1], rec, LABEL[area])

        rec({"note": "本輪結束", "已跑分鐘": round((time.time() - t0) / 60, 1)})
        end = min(time.time() + args.wait, deadline)
        while time.time() < end:
            time.sleep(min(2, end - time.time()))

    rec({"note": "收工", "cycles": cycles, "小時": round((time.time() - t0) / 3600, 2)})
    log.close()


if __name__ == "__main__":
    main()

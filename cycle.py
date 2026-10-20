"""兩區循環農素材：小村莊流程 → 傳送起始之地流程 → 等 N 秒 → 重複。

路線由使用者指定（每步約 300px）：
    N3        往北 3 步
    L1,N1,R2,S1   左1、北1、右2、南1

流程（使用者 2026-10-20 定案）
1. 傳送到小村莊 → 走 VILLAGE_ROUTE
2. 傳送到起始之地 → 走 START_ROUTE
3. 等 WAIT 秒（等樹重生）
4. 回到 1

血量低於 REST_AT 就回帳篷休息（傳起始之地 → 北 3 步 → 點休息框）。

用法：
    python cycle.py --minutes 480
    python cycle.py --start-route "N3,L1,N1,R2,S1"    # 指定起始之地路線
"""
from __future__ import annotations

import argparse
import json
import math
import re
import time
from pathlib import Path

from pkauto import adb, hpbar, popup, rest, restflow, teleport, vision

DIRS = {"N": (0, -1), "S": (0, 1), "L": (-1, 0), "R": (1, 0)}
NAMES = {"N": "北", "S": "南", "L": "西", "R": "東"}

# 小村莊：傳送落點 → 北 3 步到樹區 → 一輪掃描（使用者實測一輪就清光）
VILLAGE_PREFIX = "N3"
VILLAGE_ROUTE = "L1,N1,R2,S1"

# 起始之地：待使用者提供（先給一組暫定的，可用 --start-route 覆寫）
START_PREFIX = "N2"
START_ROUTE = "L1,N1,R2,S1"


def shot():
    return vision.normalize_brightness(adb.screencap())


def parse_route(spec):
    out = []
    for part in re.split(r"[,\s]+", spec.strip()):
        if not part:
            continue
        m = re.fullmatch(r"([NSLR])(\d+)", part.upper())
        if not m:
            raise SystemExit(f"看不懂的路線指令: {part}")
        out.append((m.group(1), int(m.group(2))))
    return out


def one_step(img, d, step_px=300.0):
    """固定路線：一步 = 一次拖曳，不換角度、不側走、不繞路。"""
    vx, vy = DIRS[d]
    a = math.atan2(vy, vx)
    hold = int(min(1600, max(240, step_px / 315.0 * 1000)))
    adb.swipe(720, 2600, int(720 + math.cos(a) * 250), int(2600 + math.sin(a) * 250), hold)
    time.sleep(hold / 1000.0 + 0.40)
    cur = shot()
    sh = vision.shift_by_template(img, cur, threshold=0.6)
    dx, dy = (sh[0], sh[1]) if sh else tuple(vision.scroll(img, cur)[:2])
    return dx, dy, (abs(dx) + abs(dy) > 18), cur


REST_TAP = (721, 1839)      # 起始之地往北 2 步後，休息對話框固定出現在這個位置


def walk_north_and_rest(img, steps, rec, label):
    """往北走 steps 步（起始之地 2 步就到帳篷）→ 直接點固定座標休息。

    使用者要求：不用偵測對話框，位置固定，點固定點就好。
    """
    for i in range(steps):
        dx, dy, moved, img = one_step(img, "N")
        rec({"note": f"{label} 北 {i+1}/{steps}", "shift": [round(dx), round(dy)]})
        if not moved:
            rec({"note": f"{label} 北 {i+1} 走不動"})
    adb.tap(REST_TAP[0], REST_TAP[1])
    time.sleep(4.5)
    img = shot()
    rec({"note": f"{label} 點固定位置休息", "at": list(REST_TAP),
         "對話框還在": rest.has_rest_dialog(img)})
    return img


def run_route(img, route, rec, label):
    """照固定路線走完；卡住也只記錄，不繞路。"""
    blocked = 0
    for d, n in route:
        for i in range(n):
            dx, dy, moved, img = one_step(img, d)
            if not moved:
                blocked += 1
                rec({"note": f"{label} 這步沒動", "dir": NAMES[d], "i": i})
    rec({"note": f"{label} 路線完成", "沒動的步數": blocked})
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=480)
    ap.add_argument("--wait", type=float, default=0,
                    help="兩區跑完後等待秒數（預設 0：流程本身已約 110 秒）")
    ap.add_argument("--village-route", default=VILLAGE_ROUTE)
    ap.add_argument("--village-prefix", default=VILLAGE_PREFIX)
    ap.add_argument("--start-route", default=START_ROUTE)
    ap.add_argument("--start-prefix", default=START_PREFIX)
    ap.add_argument("--rest-at", type=float, default=0.15)
    args = ap.parse_args()

    v_prefix = parse_route(args.village_prefix) if args.village_prefix else []
    v_route = parse_route(args.village_route)
    s_prefix = parse_route(args.start_prefix) if args.start_prefix else []
    s_route = parse_route(args.start_route)

    run = Path("captures") / time.strftime("cycle_%Y%m%d_%H%M%S")
    run.mkdir(parents=True, exist_ok=True)
    log = (run / "log.jsonl").open("w", encoding="utf-8")

    def rec(o):
        o["t"] = time.strftime("%H:%M:%S")
        log.write(json.dumps(o, ensure_ascii=False) + "\n")
        log.flush()
        print(json.dumps(o, ensure_ascii=False), flush=True)

    rec({"note": "開始循環", "小村莊": f"{args.village_prefix} | {args.village_route}",
         "起始之地": f"{args.start_prefix} | {args.start_route}", "wait": args.wait})

    t0 = time.time()
    deadline = t0 + args.minutes * 60
    cycles = 0
    prev_w = None

    while time.time() < deadline:
        cycles += 1
        rec({"note": f"=== 第 {cycles} 輪 ==="})

        # ---- 小村莊 ----
        if not teleport.go("village"):
            rec({"note": "傳送小村莊失敗"})
            time.sleep(5)
            continue
        time.sleep(2.5)
        img = shot()

        frac = hpbar.hp_fraction(img)
        if frac is not None and frac < args.rest_at:
            rec({"note": "血量過低 → 休息", "hp_frac": round(frac, 3)})
            restflow.go_rest(verbose=lambda m: rec({"note": str(m)}))
            img = shot()

        w0 = hpbar.bar_extent(img)[2] if hpbar.bar_extent(img) else None
        img = run_route(img, v_prefix, rec, "小村莊前置")
        img = run_route(img, v_route, rec, "小村莊")
        w1 = hpbar.bar_extent(img)[2] if hpbar.bar_extent(img) else None
        if w0 and w1:
            rec({"note": "小村莊砍伐", "估次數": max(0, round((w0 - w1) / 1.284)),
                 "血條": [w0, w1]})
        ext = hpbar.bar_extent(img)
        if ext:
            prev_w = ext[2]

        # ---- 起始之地 ----
        if not teleport.go("start"):
            rec({"note": "傳送起始之地失敗"})
            time.sleep(5)
            continue
        time.sleep(2.5)
        img = shot()
        # 起始之地：往北 2 步就到帳篷 → 順便休息（使用者定案，不多一個流程）
        img = walk_north_and_rest(img, sum(n for _d, n in s_prefix) if s_prefix else 2, rec, "起始之地")
        w2 = hpbar.bar_extent(img)[2] if hpbar.bar_extent(img) else None
        img = run_route(img, s_route, rec, "起始之地")
        w3 = hpbar.bar_extent(img)[2] if hpbar.bar_extent(img) else None
        if w2 and w3:
            rec({"note": "起始之地砍伐", "估次數": max(0, round((w2 - w3) / 1.284)),
                 "血條": [w2, w3]})

        ext = hpbar.bar_extent(shot())
        if ext:
            rec({"note": "本輪結束", "hp_frac": round(hpbar.hp_fraction(shot()), 3), "血條寬": ext[2]})

        if time.time() >= deadline:
            break
        rec({"note": f"等待 {args.wait:.0f} 秒（等樹重生）"})
        end = min(time.time() + args.wait, deadline)
        while time.time() < end:
            time.sleep(min(5, end - time.time()))

    rec({"note": "收工", "cycles": cycles})
    log.close()


if __name__ == "__main__":
    main()

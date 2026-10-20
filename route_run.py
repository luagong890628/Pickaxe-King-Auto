"""固定路線跑圖：照使用者指定的「往哪個方向幾步」重複走。

為什麼要用這個：自主遊走會被牆逼著往同一個角滑（實測卡在小村莊右上角），
使用者指定步數的固定路線反而穩定 —— 走過去就會自動砍。

路線語法（逗號分隔）：
    N8   往北（畫面上方）8 步
    S3   往南 3 步
    L5   往西 5 步
    R10  往東 10 步
每「步」預設 300px（可用 --step 調整）。

用法範例：
    python route_run.py "N8,L6,N4,R12" --area village --minutes 30
    python route_run.py "N8,L6,N4,R12" --area village --dry     # 只印路線不動手機
"""
from __future__ import annotations

import argparse
import json
import math
import re
import time
from pathlib import Path

from pkauto import adb, hpbar, popup, restflow, teleport, vision

DIRS = {"N": (0, -1), "S": (0, 1), "L": (-1, 0), "R": (1, 0)}
NAMES = {"N": "北", "S": "南", "L": "西", "R": "東"}


def shot():
    return vision.normalize_brightness(adb.screencap())


def parse_route(spec):
    out = []
    for part in re.split(r"[,\s]+", spec.strip()):
        if not part:
            continue
        m = re.fullmatch(r"([NSLR])(\d+)", part.upper())
        if not m:
            raise SystemExit(f"看不懂的路線指令: {part}（格式例如 N8 或 L3）")
        out.append((m.group(1), int(m.group(2))))
    if not out:
        raise SystemExit("路線是空的")
    return out


def one_step(img, d, step_px, tries=(0, 25, -25, 45, -45)):
    """朝 d 走一步（按住時間控制）；回傳 (dx, dy, moved, img)。"""
    vx, vy = DIRS[d]
    base = math.atan2(vy, vx)
    hold = int(min(1600, max(240, step_px / 315.0 * 1000)))
    cur = img
    for off in tries:
        a = base + math.radians(off)
        adb.swipe(720, 2600, int(720 + math.cos(a) * 250), int(2600 + math.sin(a) * 250), hold)
        time.sleep(hold / 1000.0 + 0.40)
        cur = shot()
        sh = vision.shift_by_template(img, cur, threshold=0.6)
        dx, dy = (sh[0], sh[1]) if sh else tuple(vision.scroll(img, cur)[:2])
        if abs(dx) + abs(dy) > 18:
            return dx, dy, True, cur, off
    return 0.0, 0.0, False, cur, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("route", help='例如 "N8,L6,N4,R12"')
    ap.add_argument("--area", choices=["village", "start"], default="village")
    ap.add_argument("--step", type=float, default=300.0, help="每一步的像素距離")
    ap.add_argument("--minutes", type=float, default=30.0)
    ap.add_argument("--loops", type=int, default=0, help="跑幾輪（0＝跑到時間到）")
    ap.add_argument("--rest-at", type=float, default=0.15, help="血條低於此比例就休息")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--wait", type=float, default=0.0,
                    help="每輪之間等待秒數（等樹重生，約 100 秒）")
    ap.add_argument("--no-teleport", action="store_true",
                    help="不傳送，直接從目前位置開始走（測試路線用）")
    args = ap.parse_args()

    route = parse_route(args.route)
    total_steps = sum(n for _d, n in route)
    pretty = " → ".join(f"{NAMES[d]}{n}步" for d, n in route)
    print(f"路線：{pretty}（共 {total_steps} 步，每步約 {args.step:.0f}px）")
    if args.dry:
        return

    run = Path("captures") / time.strftime("route_%Y%m%d_%H%M%S")
    run.mkdir(parents=True, exist_ok=True)
    log = (run / "log.jsonl").open("w", encoding="utf-8")

    def rec(o):
        o["t"] = time.strftime("%H:%M:%S")
        log.write(json.dumps(o, ensure_ascii=False) + "\n")
        log.flush()
        print(json.dumps(o, ensure_ascii=False), flush=True)

    if not args.no_teleport:
        if not teleport.go(args.area):
            rec({"note": "傳送失敗"})
            return
        time.sleep(2.5)

    img = shot()
    t0 = time.time()
    deadline = t0 + args.minutes * 60
    loops = 0
    blocked = 0
    chops = 0
    prev_w = hpbar.bar_extent(img)[2] if hpbar.bar_extent(img) else None

    while time.time() < deadline:
        loops += 1
        rec({"note": f"=== 第 {loops} 輪 ==="})

        frac = hpbar.hp_fraction(img)
        if frac is not None and frac < args.rest_at:
            rec({"note": "血量過低 → 休息", "hp_frac": round(frac, 3)})
            restflow.go_rest(verbose=lambda m: rec({"note": str(m)}))
            hpbar.reset_cache()
            img = shot()
            continue

        if popup.close_popup(img):
            rec({"note": "關掉彈窗"})
            img = shot()

        for d, n in route:
            for i in range(n):
                if time.time() > deadline:
                    break
                dx, dy, moved, img, off = one_step(img, d, args.step)
                if not moved:
                    blocked += 1
                    rec({"note": "卡住", "dir": NAMES[d], "i": i, "blocked": blocked})
                    # 卡住就試垂直方向繞一小步
                    side = "R" if d in ("N", "S") else "N"
                    dx, dy, moved, img, _ = one_step(img, side, args.step * 0.8)
                    continue
                # 血條變短＝剛剛砍到東西（每砍一次少約 1.3px）
                ext = hpbar.bar_extent(img)
                if ext and prev_w is not None and ext[2] <= prev_w - 1:
                    chops += 1
                    rec({"note": "砍到 ✓", "dir": NAMES[d], "i": i, "chops": chops,
                         "hp_frac": round(hpbar.hp_fraction(img), 3)})
                if ext:
                    prev_w = ext[2]
                else:
                    rec({"note": "步", "dir": NAMES[d], "i": i, "shift": [round(dx), round(dy)]})
            rec({"note": "段落完成", "dir": NAMES[d], "steps": n})

        if args.loops and loops >= args.loops:
            break
        if args.wait and time.time() < deadline:
            rec({"note": f"等待 {args.wait:.0f} 秒（等樹重生）", "loops": loops, "chops": chops})
            end_wait = min(time.time() + args.wait, deadline)
            while time.time() < end_wait:
                time.sleep(min(5, end_wait - time.time()))

    rec({"note": "結束", "loops": loops, "blocked": blocked, "chops": chops})
    log.close()


if __name__ == "__main__":
    main()

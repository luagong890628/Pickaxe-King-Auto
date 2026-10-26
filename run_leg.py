"""只走指定的段（不用跑整輪），每段都量「目標 vs 實走」。

用法
    python run_leg.py village 1 2            # 傳送到小村莊 → 走第 1、2 段（有量測）
    python run_leg.py village 1 --drag 400   # 指定搖桿速度（拖曳長度）
    python run_leg.py village --walk L:100   # 從「現在位置」走西 100px（不傳送）
    python run_leg.py village --walk N:250 --walk L:300   # 連續走臨時段
    python run_leg.py start 1 --no-teleport  # 不傳送，從現在位置走路線第 1 段

臨時段（--walk）每次都會追加到 data/tune_log.jsonl：方向、目標 px、實走 px、量測來源與分數，
方便之後把「邊走邊調」的結果整理回 cycle_fixed.py 的 ROUTES。

調參流程（使用者 2026-10-21 定案）
    要改哪一段就直接改 cycle_fixed.py 的 ROUTES，然後只走「起點到那一段」為止：
    例如改第 2 段 → 跑 `village 1 2`（因為第 2 段的起點是靠第 1 段走出來的）。
    除非使用者說「重跑」，不要開整輪。

量速度倍率 k（遊戲改跑速後的第一步）
    python run_leg.py village --walk N:300 --drag 250 --no-teleport --settle 1.5
    python run_leg.py village --walk S:300 --drag 400 --no-teleport --settle 1.5
    python run_leg.py village --walk N:300 --drag 1200 --no-teleport --settle 1.5
    每段會印「建議 --speed-scale」。三次建議值一致＝搖桿曲線形狀沒變，只改倍率即可；
    不一致（尤其 1200 那筆）＝曲線被改過或超出標定區間，要重標 SPEED_TABLE。
    南北交替是為了消掉漂移；拖 1200 那筆專門驗進場段（ENTRY_DRAG）能不能套同一個倍率。
"""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import cv2

import cycle_fixed as cf
from pkauto import adb

TUNE_LOG = Path("data/tune_log.jsonl")


def rec_plain(o):
    if "shift" in o:
        tx, ty = o["目標"]
        # shift 是「畫面內容」的位移，角色位移要取反向
        sx, sy = -o["shift"][0], -o["shift"][1]
        print(f"{o['note']}：目標 ({tx:+d},{ty:+d}) / 實走 ({sx:+d},{sy:+d})"
              f"  → 差 ({sx - tx:+d},{sy - ty:+d})", flush=True)
    else:
        print(o.get("note", json.dumps(o, ensure_ascii=False)), flush=True)


def parse_walk(specs):
    """["L:100", "N:250"] → [("L", 100.0), ("N", 250.0)]"""
    out = []
    for s in specs:
        d, px = s.split(":")
        d = d.strip().upper()
        if d not in cf.DIRS:
            raise SystemExit(f"方向只能用 {sorted(cf.DIRS)}：{s}")
        out.append((d, float(px)))
    return out


def log_walk(rec):
    TUNE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with TUNE_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("area", choices=sorted(cf.ROUTES))
    ap.add_argument("legs", nargs="*", type=int, help="段號（1 起算，照 --dry-run 的編號）")
    ap.add_argument("--walk", action="append", default=[],
                    help="臨時段『方向:px』（例 --walk L:100）；從現在位置走、不傳送，可重複")
    ap.add_argument("--no-teleport", action="store_true")
    ap.add_argument("--settle", type=float, default=None,
                    help="段與段之間停多久；不給＝照路線設定（cycle_fixed.SETTLE_LEGS／SETTLE）")
    ap.add_argument("--settle-first", type=float, default=None,
                    help="第 1 段走完後改停這麼久（預設同 --settle）；其餘段仍用 --settle")
    ap.add_argument("--save", action="store_true", help="另存每段前後的畫面到 captures/")
    ap.add_argument("--template", action="store_true",
                    help="量測只信範本比對（預設是範本＋相位相關交叉驗證，較穩）")
    ap.add_argument("--drag", type=float, default=None,
                    help="覆寫拖曳長度＝搖桿速度（250≈343px/秒、400≈488、500≈541）")
    ap.add_argument("--speed-scale", type=float, default=None,
                    help="全域速度倍率（遊戲改跑速後用；量 k 時先留 1.0）")
    ap.add_argument("--force", action="store_true", help="即使前景不是遊戲也照跑")
    ap.add_argument("--timing", action="store_true", help="量每段按下的時間與段間間隔（秒）")
    ap.add_argument("--fill", action="store_true",
                    help="走完路線後照 FILL_LEGS 再走 FILL_PAIRS 組補時（等同正式程式的農場補時）")
    ap.add_argument("--no-measure", action="store_true",
                    help="不量位移（＝長跑時的真實節奏；段間間隔會回到 ~1 秒）")
    args = ap.parse_args()

    if not args.legs and not args.walk:
        print("要指定段號（village 1 2）或臨時段（--walk L:100）")
        return 2

    focus = adb.current_app()
    if "pickaxeking" not in focus.lower() and not args.force:
        print(f"前景不是遊戲，中止：{focus}")
        return 2

    cf.MEASURE = not args.no_measure      # 預設要量；--no-measure 用來看長跑節奏
    cf.MEASURE_TEMPLATE = args.template
    if args.speed_scale is not None:
        cf.SPEED_SCALE = args.speed_scale
    if args.drag:
        cf.DRAG_LEN = args.drag

    presses = []
    if args.timing:
        orig_swipe = cf.adb.swipe

        def timed_swipe(x1, y1, x2, y2, ms=300):
            t0 = time.time()
            orig_swipe(x1, y1, x2, y2, ms)
            presses.append((t0, time.time(), ms))

        cf.adb.swipe = timed_swipe

    save_dir = None
    if args.save:
        save_dir = Path("captures") / time.strftime("legs_%Y%m%d_%H%M%S")
        save_dir.mkdir(parents=True, exist_ok=True)

    if args.walk:
        acts, teleport = [(i, a) for i, a in enumerate(parse_walk(args.walk), 1)], False
    else:
        route = cf.ROUTES[args.area]
        acts = []
        for n in args.legs:
            if not 1 <= n <= len(route):
                print(f"第 {n} 段不存在（{cf.LABEL[args.area]} 共 {len(route)} 段）")
                return 2
            acts.append((n, route[n - 1]))
        teleport = not args.no_teleport

    if teleport:
        print(f"傳送到 {cf.LABEL[args.area]} …", flush=True)
        cf.teleport(args.area, rec_plain)
        time.sleep(2.5)

    def settle_for(i, leg_no):
        """這次走訪的第 i 段（路線段號 leg_no）走完後停多久。

        優先序：--settle-first（只作用在本次第一段）> --settle（全部套用）
                > 路線設定 route_settle（--walk 臨時段用全域 SETTLE）。
        ⚠️ 這裡以前是 `default=1.0` 且直接回傳 args.settle，導致**每一段都停 1 秒**、
           而且完全忽略 SETTLE_LEGS（使用者 2026-10-26 抓到：「為什麼感覺全部都有停」）。
           要驗證停頓設定時千萬不要順手加 --settle，否則量到的不是程式真正的行為。
        """
        if i == 1 and args.settle_first is not None:
            return args.settle_first
        if args.settle is not None:
            return args.settle
        return cf.SETTLE if args.walk else cf.route_settle(args.area, leg_no)

    img = cf.shot() if cf.MEASURE else None
    cur_drag = [cf.DRAG_LEN]

    def rec_leg(o):
        rec_plain(o)
        if "source" in o:
            rec = {"dir": d, "px": px, "measured": [-v for v in o["shift"]],
                   "source": o["source"], "score": round(o["score"], 2),
                   "drag": cur_drag[0], "area": args.area,
                   "t": time.strftime("%Y-%m-%d %H:%M:%S")}
            log_walk(rec)
            print(f"    紀錄：{d} {px:.0f}px → 實走 ({rec['measured'][0]:+d},"
                  f"{rec['measured'][1]:+d}) [{rec['source']} {rec['score']}]", flush=True)
            # 實走/目標 = k / 目前倍率 → 建議倍率 = 目前倍率 × 比值
            actual = math.hypot(rec["measured"][0], rec["measured"][1])
            if px > 0:
                print(f"    速度倍率推估：實走/目標 = {actual / px:.3f}"
                      f" → 建議 --speed-scale {cf.SPEED_SCALE * actual / px:.2f}", flush=True)

    for i, (leg_no, act) in enumerate(acts, 1):
        if act[0] == "REST":
            img = cf.rest(rec_plain, img, cf.LABEL[args.area])
            time.sleep(settle_for(i, leg_no))
            continue
        d, px, _ = cf.route_act(act)
        # 路線段照主循環的分段速度；--drag 覆寫或 --walk 臨時段才用通用 DRAG_LEN
        # 注意要用**路線上的段號 leg_no**，不是本次走訪的第幾個（--no-teleport 續走時兩者不同）
        drag_len = cf.route_drag(args.area, leg_no) if not args.walk and args.drag is None else None
        cur_drag[0] = cf.DRAG_LEN if drag_len is None else drag_len
        if save_dir is not None and img is not None:
            small = cv2.resize(img, (img.shape[1] // 2, img.shape[0] // 2))
            cv2.imwrite(str(save_dir / f"leg{leg_no:02d}_before.jpg"), small)
        img = cf.leg(img, d, px, rec_leg, f"{cf.LABEL[args.area]}[{leg_no}]",
                     drag_len=drag_len, settle=settle_for(i, leg_no))
        if save_dir is not None and img is not None:
            small = cv2.resize(img, (img.shape[1] // 2, img.shape[0] // 2))
            cv2.imwrite(str(save_dir / f"leg{leg_no:02d}_after.jpg"), small)
    if args.fill and not args.walk and args.area in cf.FILL_LEGS:
        print(f"補時：{cf.FILL_PAIRS} 組 第 {cf.FILL_LEGS[args.area]} 段來回", flush=True)
        img = cf.fill_cycle(args.area, rec_plain, img)
    if save_dir is not None:
        print(f"畫面存到 {save_dir}")
    if args.timing and presses:
        print("\n按下時刻      按住ms   段間間隔（上一次放開→這一次按下）")
        t_base = presses[0][0]
        for i, (t0, t1, ms) in enumerate(presses):
            gap = "—" if i == 0 else f"{t0 - presses[i - 1][1]:.2f}s"
            print(f"{t0 - t_base:8.2f}s  {ms:>7}   {gap:>8}（按住實測 {t1 - t0:.2f}s）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

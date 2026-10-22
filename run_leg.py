"""只走指定的段（不用跑整輪），每段都量「目標 vs 實走」。

用法
    python run_leg.py village 1 2          # 傳送到小村莊 → 走第 1、2 段（有量測）
    python run_leg.py start 1 --no-teleport # 不傳送，從現在位置走第 1 段
    python run_leg.py village 1 2 --save    # 另存實走後的畫面（captures/，預設開）

調參流程（使用者 2026-10-21 定案）
    要改哪一段就直接改 cycle_fixed.py 的 ROUTES，然後只走「起點到那一段」為止：
    例如改第 2 段 → 跑 `village 1 2`（因為第 2 段的起點是靠第 1 段走出來的，
    只走第 2 段會從錯誤的位置出發）。除非使用者說「重跑」，不要開整輪。
"""
from __future__ import annotations

import argparse
import json
import time

import cv2

import cycle_fixed as cf
from pkauto import adb

SAVE_DIR = None


def rec_plain(o):
    if "shift" in o:
        tx, ty = o["目標"]
        # shift 是「畫面內容」的位移，角色位移要取反向
        sx, sy = -o["shift"][0], -o["shift"][1]
        print(f"{o['note']}：目標 ({tx:+d},{ty:+d}) / 實走 ({sx:+d},{sy:+d})"
              f"  → 差 ({sx - tx:+d},{sy - ty:+d})", flush=True)
    else:
        print(o.get("note", json.dumps(o, ensure_ascii=False)), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("area", choices=sorted(cf.ROUTES))
    ap.add_argument("legs", nargs="+", type=int, help="段號（1 起算，照 --dry-run 的編號）")
    ap.add_argument("--no-teleport", action="store_true")
    ap.add_argument("--settle", type=float, default=1.0, help="段與段之間停多久")
    ap.add_argument("--save", action="store_true", help="另存每段走完的畫面到 captures/")
    ap.add_argument("--template", action="store_true",
                    help="量測只信範本比對（預設是範本＋相位相關交叉驗證，較穩）")
    ap.add_argument("--force", action="store_true", help="即使前景不是遊戲也照跑")
    args = ap.parse_args()

    focus = adb.current_app()
    if "pickaxeking" not in focus.lower() and not args.force:
        print(f"前景不是遊戲，中止：{focus}")
        return 2

    cf.MEASURE = True                     # 這段工具一定要量
    cf.MEASURE_TEMPLATE = args.template

    save_dir = None
    if args.save:
        from pathlib import Path
        save_dir = Path("captures") / time.strftime("legs_%Y%m%d_%H%M%S")
        save_dir.mkdir(parents=True, exist_ok=True)

    if not args.no_teleport:
        print(f"傳送到 {cf.LABEL[args.area]} …", flush=True)
        cf.teleport(args.area, rec_plain)
        time.sleep(2.5)

    route = cf.ROUTES[args.area]
    img = cf.shot()
    for n in args.legs:
        if not 1 <= n <= len(route):
            print(f"第 {n} 段不存在（{cf.LABEL[args.area]} 共 {len(route)} 段）")
            return 2
        act = route[n - 1]
        if act[0] == "REST":
            img = cf.rest(rec_plain, img, cf.LABEL[args.area])
        else:
            d, px = act
            img = cf.leg(img, d, px, rec_plain, f"{cf.LABEL[args.area]}[{n}]")
            if save_dir is not None and img is not None:
                small = cv2.resize(img, (img.shape[1] // 2, img.shape[0] // 2))
                cv2.imwrite(str(save_dir / f"leg{n:02d}_after.jpg"), small)
        time.sleep(args.settle)

    if save_dir is not None:
        print(f"畫面存到 {save_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

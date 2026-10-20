"""整夜自動農素材：小村莊 ⇄ 起始之地 輪替 + 自動休息 + 砍到判定。

流程
1. 傳送到某地區 → 一路往上推進（撞到試斜上，再撞大幅繞路）
2. 每步比對血量數字區域 → 有變＝砍到 ✓（不需 OCR）
3. 該區連續 NO_CHOP_SWITCH 秒沒砍到 → 換另一個地區
4. 兩個地區都空轉一輪 → 傳到起始之地找帳篷休息（生命值歸零時必需）
5. 全程寫 log，早上可直接看統計

用法：
    farm.py 480                 # 跑 8 小時
    farm.py 60 --areas village,start
"""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import cv2
import numpy as np

from pkauto import adb, hpdrop, popup, rest, restflow, teleport, vision
from sweep_up import DRAG, move, shot

NO_CHOP_SWITCH = 150          # 某區幾秒沒砍到就換區
REST_AFTER_IDLE = 260         # 整體幾秒沒砍到就去找帳篷休息


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("minutes", type=float, nargs="?", default=480.0)
    ap.add_argument("--areas", default="village,start")
    ap.add_argument("--no-teleport", action="store_true")
    args = ap.parse_args()

    run = Path("captures") / time.strftime("farm_%Y%m%d_%H%M%S")
    run.mkdir(parents=True, exist_ok=True)
    log = (run / "log.jsonl").open("w", encoding="utf-8")

    def rec(o):
        o["t"] = time.strftime("%H:%M:%S")
        log.write(json.dumps(o, ensure_ascii=False) + "\n")
        log.flush()
        print(json.dumps(o, ensure_ascii=False), flush=True)

    areas = [a.strip() for a in args.areas.split(",") if a.strip()]
    ai = 0
    t0 = time.time()
    deadline = t0 + args.minutes * 60
    total_chops = 0
    last_chop_global = time.time()
    per_area = {}
    cycle_without_chop = 0

    while time.time() < deadline:
        area = areas[ai]
        rec({"note": "=== 進入地區 ===", "area": area, "chops_so_far": total_chops})
        if not args.no_teleport:
            if not teleport.go(area):
                rec({"note": "傳送失敗 → 換下一個地區"})
                ai = (ai + 1) % len(areas)
                time.sleep(3)
                continue
            time.sleep(2.5)

        img = shot()
        sig = hpdrop.hp_sig(img)
        area_chops = 0
        last_chop = time.time()
        passes = 0
        stuck = 0
        lateral = 1
        area_t0 = time.time()

        while time.time() < deadline and (time.time() - last_chop) < NO_CHOP_SWITCH:
            # 先處理彈窗（黑市、設定等）：找粉紅 X 點掉，絕不點白色大框
            if popup.close_popup(img):
                rec({"note": "關掉彈窗"})
                img = shot()
                sig = hpdrop.hp_sig(img)
                continue

            dx, dy, moved, img = move(img, 0, -1, 320)
            if not moved:
                stuck += 1
                if stuck % 3 == 1:
                    dx, dy, moved, img = move(img, lateral * 0.7, -1, 340)
                else:
                    dx, dy, moved, img = move(img, lateral, 0, 560)
                    if not moved:
                        lateral *= -1
                continue

            passes += 1
            if passes % 4 == 0:
                lateral *= -1

            new_sig = hpdrop.hp_sig(img)
            if hpdrop.hp_changed(sig, new_sig):
                area_chops += 1
                total_chops += 1
                last_chop = time.time()
                last_chop_global = time.time()
                per_area[area] = per_area.get(area, 0) + 1
                rec({"note": "砍到 ✓", "area": area, "area_chops": area_chops,
                     "total": total_chops, "min": round((time.time() - t0) / 60, 1)})
            sig = new_sig

            if passes % 20 == 0:
                rec({"note": "推進中", "area": area, "passes": passes,
                     "area_chops": area_chops, "total": total_chops})

        rec({"note": "地區結束", "area": area, "chops": area_chops,
             "秒數": round(time.time() - area_t0)})

        # 兩個地區都空轉 → 去起始之地找帳篷休息
        if area_chops == 0:
            cycle_without_chop += 1
        else:
            cycle_without_chop = 0

        if area_chops == 0 and not args.no_teleport:
            rec({"note": "這區 150 秒沒砍到 → 先休息再換區"})
            ok = restflow.go_rest(verbose=lambda m: rec({"note": str(m)}))
            rec({"note": "休息結果", "ok": ok})
            cycle_without_chop = 0
        elif cycle_without_chop >= len(areas) and not args.no_teleport:
            rec({"note": "兩區都沒砍到 → 回起始之地休息", "idle_min": round((time.time() - last_chop_global) / 60, 1)})
            ok = restflow.go_rest(verbose=lambda m: rec({"note": str(m)}))
            rec({"note": "休息結果", "ok": ok})
            cycle_without_chop = 0

        ai = (ai + 1) % len(areas)

    rec({"note": "收工", "total_chops": total_chops,
         "per_area": per_area, "小時": round((time.time() - t0) / 3600, 2)})
    log.close()


if __name__ == "__main__":
    main()

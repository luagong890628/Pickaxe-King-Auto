"""監聽真實手指觸控（校正用）：錄 N 秒後解析出每個觸碰的原始座標與換算後座標。

用法：calib_listen.py [秒數]
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, ".")
import record_touch as rt
from pkauto import adb


def main():
    dur = float(sys.argv[1]) if len(sys.argv) > 1 else 45.0
    dev = rt.pick_touch_device(rt.list_devices())
    print(f"監聽 {dev['path']} ({dev['name']}) {dur:.0f} 秒…", flush=True)
    raw = Path("captures/ge_listen.txt")
    f = open(raw, "w", encoding="utf-8")
    p = subprocess.Popen([adb.adb_path(), "shell", "getevent", "-lt", dev["path"]],
                         stdout=f, stderr=subprocess.DEVNULL, text=True)
    t0 = time.time()
    n_last = 0
    while time.time() - t0 < dur:
        time.sleep(2.0)
        try:
            n = sum(1 for _ in open(raw, encoding="utf-8"))
        except OSError:
            n = 0
        if n != n_last:
            print(f"  [{time.time()-t0:.0f}s] {n} 行", flush=True)
            n_last = n
        if Path("data/touch/STOP").exists():
            break
    p.terminate()
    time.sleep(0.5)
    f.close()

    # 解析
    pts, cx, cy, down = [], None, None, None
    for line in open(raw, encoding="utf-8"):
        m = rt.EV_RE.search(line)
        if not m:
            continue
        _ts, _dev, typ, code, val = m.groups()
        if typ == "EV_ABS" and code == "ABS_MT_POSITION_X":
            cx = int(val, 16)
        elif typ == "EV_ABS" and code == "ABS_MT_POSITION_Y":
            cy = int(val, 16)
        elif typ == "EV_KEY" and code == "BTN_TOUCH":
            if val == "DOWN":
                down = (cx, cy)
            elif val == "UP" and down is not None:
                # 取放開前的最後位置當終點
                pts.append({"down": down, "up": (cx, cy)})
                down = None
    w, h = adb.screen_size()
    print(f"\n共 {len(pts)} 次觸碰（原始座標）:")
    for i, t in enumerate(pts):
        print(f"  #{i+1} down={t['down']}  up={t['up']}")
    json.dump({"screen": [w, h], "points": pts},
              open("data/touch/_calib_raw.json", "w", encoding="utf-8"), ensure_ascii=False)
    print("已存 data/touch/_calib_raw.json")


if __name__ == "__main__":
    main()

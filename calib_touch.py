"""實測觸控座標校正：在安全區（HP 條那一帶）打幾個點，解出 raw → 螢幕 的線性映射。

輸出 data/touch/_calib.json: {"x": [ax, bx], "y": [ay, by]}，螢幕座標 = a*raw + b。
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

import record_touch as rt
from pkauto import adb

EV_RE = rt.EV_RE


def capture_with(actions, duration=9.0, raw_path="captures/ge_calib.txt"):
    """先開錄、再做動作、再停止（順序很重要）。"""
    dev = rt.pick_touch_device(rt.list_devices())
    f = open(raw_path, "w", encoding="utf-8")
    p = subprocess.Popen([adb.adb_path(), "shell", "getevent", "-lt", dev["path"]],
                         stdout=f, stderr=subprocess.DEVNULL, text=True)
    time.sleep(1.5)
    actions()
    time.sleep(1.5)
    p.terminate()
    time.sleep(0.5)
    f.close()
    pts, cx, cy, down = [], None, None, None
    for line in open(raw_path, encoding="utf-8"):
        m = EV_RE.search(line)
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
                pts.append((down, (cx, cy)))
                down = None
    p.terminate()
    return pts


def main():
    w, h = adb.screen_size()
    print(f"螢幕 {w}x{h}；開始校正（會打幾個無害的點）")
    def actions():
        for x in (180, 1260):
            adb.tap(x, 150)
            time.sleep(1.2)
        adb.swipe(720, 150, 720, 330, 500)
        time.sleep(0.6)

    pts = capture_with(actions)
    print("收到觸碰:", pts)
    # 前兩顆 = x 校正；第三顆 = y 校正
    if len(pts) < 3:
        print("樣本不足（<3），請確認手機畫面有反應後再試")
        return
    (r1, r1u), (r2, r2u), (r3, r3u) = pts[0], pts[1], pts[2]
    ax = (1260 - 180) / max(1, r2[0] - r1[0])
    bx = 180 - ax * r1[0]
    if r3u[1] == r3[1]:
        print("第二顆 y 樣本相同，改用 swipe 終點推 y（近似）")
    ay = (330 - 150) / max(1, r3u[1] - r3[1])
    by = 150 - ay * r3[1]
    out = {"x": [ax, bx], "y": [ay, by]}
    json.dump(out, open("data/touch/_calib.json", "w", encoding="utf-8"))
    print(f"校正完成: screen_x = {ax:.6f}*raw_x + {bx:.2f}; screen_y = {ay:.6f}*raw_y + {by:.2f}")
    print(f"驗算: raw({r1[0]},{r1[1]}) → ({ax*r1[0]+bx:.0f},{ay*r1[1]+by:.0f}) 應為 (180,150)")


if __name__ == "__main__":
    main()

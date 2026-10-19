"""從 captures/ge_listen.txt 解析觸碰並算出 raw → 螢幕 的線性換算。"""
import json
import re
import sys

sys.path.insert(0, ".")
import importlib
import record_touch as rt
importlib.reload(rt)
import numpy as np

raw_lines = open("captures/ge_listen.txt", encoding="utf-8").readlines()
# 注意：BTN_TOUCH DOWN 會比 ABS_MT_POSITION_X/Y 先出現，
# 所以要記錄「DOWN 之後第一次拿到的座標」才是那一下的真正位置。
pts, cx, cy = [], None, None
pending = False
for line in raw_lines:
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
            pending = True
            cx = cy = None
        elif val == "UP" and cx is not None:
            pts.append((cx, cy))
            pending = False

print("觸碰數:", len(pts))
for i, p in enumerate(pts):
    print(f"  #{i+1} raw={p}")

targets = [(300, 600), (1150, 600), (300, 2500), (1150, 2500)]
if len(pts) >= 4:
    raw = np.array(pts[:4], float)
    scr = np.array(targets, float)
    ax = (scr[1, 0] - scr[0, 0]) / (raw[1, 0] - raw[0, 0])
    bx = scr[0, 0] - ax * raw[0, 0]
    ay = (scr[2, 1] - scr[0, 1]) / (raw[2, 1] - raw[0, 1])
    by = scr[0, 1] - ay * raw[0, 1]
    print(f"\n換算: screen_x = {ax:.6f}*raw_x + {bx:.2f}")
    print(f"      screen_y = {ay:.6f}*raw_y + {by:.2f}")
    mx = 0
    for r, s in zip(raw, scr):
        px, py = ax * r[0] + bx, ay * r[1] + by
        mx = max(mx, abs(px - s[0]), abs(py - s[1]))
        print(f"  驗算 raw({r[0]:.0f},{r[1]:.0f}) → ({px:.0f},{py:.0f}) 目標{tuple(s.astype(int))} 誤差({abs(px-s[0]):.0f},{abs(py-s[1]):.0f})")
    print("最大誤差:", round(mx, 1), "px")
    json.dump({"x": [ax, bx], "y": [ay, by], "screen": [1440, 3120], "err_px": round(float(mx), 1)},
              open("data/touch/_calib.json", "w", encoding="utf-8"), ensure_ascii=False)
    print("已存 data/touch/_calib.json")

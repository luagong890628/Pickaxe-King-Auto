"""觸控座標校正 v2：6 個取樣點 + 最小平方法（比 4 點解聯立抗誤差）。

流程：
  1. 先在手機上截圖 → 畫 6 個編號十字 → 存成 data/calib_points.png（貼給使用者）
  2. 使用者照著點 6 下（每下間隔約 2 秒）
  3. 本程式監聽 getevent 收 6 筆 → 最小平方解 screen = a*raw + b（x/y 各自）×  並印出誤差

用法：
  do_calib2.py --make        產生十字圖（貼給使用者看）
  do_calib2.py --listen 60   聽 60 秒，收 6 筆後算校正
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, ".")
import record_touch as rt
from pkauto import adb, vision

# 取樣點（畫面座標）：分散在四個象限 + 中央，避開左右 UI 欄
POINTS = [
    (300, 700),     # 1 左上
    (1140, 700),    # 2 右上
    (300, 2400),    # 3 左下
    (1140, 2400),   # 4 右下
    (720, 1100),    # 5 中央上
    (720, 2700),    # 6 中央下
]


def make():
    s = vision.normalize_brightness(adb.screencap())
    vis = s.copy()
    for i, (x, y) in enumerate(POINTS):
        for d in range(-60, 61, 4):
            cv2.line(vis, (x + d, y - 12), (x + d, y + 12), (0, 0, 255), 2)
            cv2.line(vis, (x - 12, y + d), (x + 12, y + d), (0, 0, 255), 2)
        cv2.circle(vis, (x, y), 30, (0, 255, 255), 3)
        cv2.putText(vis, str(i + 1), (x + 40, y - 36), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (0, 0, 255), 5)
    out = Path("data/calib_points.png")
    cv2.imwrite(str(out), cv2.resize(vis, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA))
    json.dump(POINTS, open("data/calib_points.json", "w"))
    print(f"已存 {out}（6 個十字，請使用者照 1→6 順序點）")


def listen(dur: float):
    dev = rt.pick_touch_device(rt.list_devices())
    raw_path = Path("captures/ge_calib2.txt")
    f = open(raw_path, "w", encoding="utf-8")
    p = subprocess.Popen([adb.adb_path(), "shell", "getevent", "-lt", dev["path"]],
                         stdout=f, stderr=subprocess.DEVNULL, text=True)
    t0 = time.time()
    print(f"監聽 {dev['name']} {dur:.0f} 秒（請點 6 個十字）…", flush=True)
    while time.time() - t0 < dur:
        time.sleep(2)
        n = sum(1 for _ in open(raw_path, encoding="utf-8"))
        print(f"  [{time.time()-t0:.0f}s] {n} 行", flush=True)
        if Path("data/touch/STOP").exists():
            break
    p.terminate()
    time.sleep(0.5)
    f.close()

    pts, cx, cy = [], None, None
    for line in open(raw_path, encoding="utf-8"):
        m = rt.EV_RE.search(line)
        if not m:
            continue
        _ts, _dev, typ, code, val = m.groups()
        if typ == "EV_ABS" and code == "ABS_MT_POSITION_X":
            cx = int(val, 16)
        elif typ == "EV_ABS" and code == "ABS_MT_POSITION_Y":
            cy = int(val, 16)
        elif typ == "EV_KEY" and code == "BTN_TOUCH" and val == "DOWN":
            cx = cy = None                    # DOWN 的座標是上一筆殘值
        elif typ == "EV_KEY" and code == "BTN_TOUCH" and val == "UP" and cx is not None:
            pts.append((cx, cy))
    print(f"收到 {len(pts)} 筆觸碰", flush=True)
    if len(pts) < 4:
        print("樣本不足，無法校正")
        return

    targets = np.array(POINTS[:len(pts)], float)
    raw = np.array(pts[:len(pts)], float)
    # 最小平方：screen = a*raw + b（x/y 各自）
    ax, bx = np.polyfit(raw[:, 0], targets[:, 0], 1)
    ay, by = np.polyfit(raw[:, 1], targets[:, 1], 1)
    pred = np.stack([ax * raw[:, 0] + bx, ay * raw[:, 1] + by], axis=1)
    err = np.abs(pred - targets).max(axis=1)
    print(f"\n校正: screen_x = {ax:.6f}*raw_x + {bx:.2f}")
    print(f"      screen_y = {ay:.6f}*raw_y + {by:.2f}")
    for i, (r, t, e) in enumerate(zip(raw, targets, err)):
        print(f"  #{i+1} raw({r[0]:.0f},{r[1]:.0f}) → 目標({t[0]:.0f},{t[1]:.0f}) 誤差 {e:.0f}px")
    print(f"最大誤差 {err.max():.0f}px、平均 {err.mean():.0f}px")
    json.dump({"x": [float(ax), float(bx)], "y": [float(ay), float(by)],
               "screen": list(adb.screen_size()), "err_px": float(err.max())},
              open("data/touch/_calib.json", "w", encoding="utf-8"), ensure_ascii=False)
    print("已更新 data/touch/_calib.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--make", action="store_true")
    ap.add_argument("--listen", type=float, default=0)
    args = ap.parse_args()
    if args.make:
        make()
    if args.listen:
        listen(args.listen)
    if not args.make and not args.listen:
        make()


if __name__ == "__main__":
    main()

"""把建圖結果畫成圖片，方便肉眼確認區域對不對。

用法：python render_map.py start [--route start_orchard]
輸出：captures/maps/<name>_map.png
顏色：淺綠=可走、藍=水/不可走、深灰=未知、黃線=角色實際走過的路徑、紅點=地標、白圈=原點
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

CELL = 30


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--route", default=None, help="同時畫出錄製的路線")
    ap.add_argument("--scale", type=int, default=4, help="每格畫幾像素")
    args = ap.parse_args()

    p = Path(f"captures/maps/{args.name}.json")
    d = json.load(open(p, encoding="utf-8"))
    grid = d["grid"]
    cells = {}
    for k, v in grid.items():
        cx, cy = (int(t) for t in k.split(","))
        cells[(cx, cy)] = v
    if not cells:
        print("地圖是空的")
        return
    xs = [c[0] for c in cells]
    ys = [c[1] for c in cells]
    x0, x1 = min(xs) - 2, max(xs) + 3
    y0, y1 = min(ys) - 2, max(ys) + 3
    W, H = (x1 - x0) * args.scale, (y1 - y0) * args.scale
    img = np.full((H, W, 3), 40, np.uint8)              # 未知=深灰

    for (cx, cy), v in cells.items():
        px = (cx - x0) * args.scale
        py = (cy - y0) * args.scale
        color = (150, 230, 150) if v == 0 else (230, 150, 60)     # 可走=淺綠、不可走=藍(水)
        cv2.rectangle(img, (px, py), (px + args.scale - 1, py + args.scale - 1), color, -1)

    # 路線
    if args.route:
        rp = Path(f"captures/paths/{args.route}.json")
        if rp.exists():
            r = json.load(open(rp, encoding="utf-8"))
            pts = [(x0 + 0, y0 + 0) for _ in []]
            poly = []
            for (rx, ry) in r["points"]:
                gx = int(rx // CELL) - x0
                gy = int(ry // CELL) - y0
                poly.append((gx * args.scale + args.scale // 2, gy * args.scale + args.scale // 2))
            for i in range(len(poly) - 1):
                cv2.line(img, poly[i], poly[i + 1], (0, 255, 255), 2)
            for i, pt in enumerate(poly):
                cv2.circle(img, pt, 5, (0, 200, 255), -1)
                cv2.putText(img, str(i), (pt[0] + 6, pt[1] - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

    # 地標與原點
    for name, info in d.get("anchor", {}).items():
        rx, ry = info["route_pos"]
        gx = int(rx // CELL) - x0
        gy = int(ry // CELL) - y0
        pt = (gx * args.scale + args.scale // 2, gy * args.scale + args.scale // 2)
        cv2.drawMarker(img, pt, (0, 0, 255), cv2.MARKER_STAR, 18, 3)
        cv2.putText(img, name, (pt[0] + 8, pt[1] + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
    ox = (0 // CELL - x0) * args.scale + args.scale // 2
    oy = (0 // CELL - y0) * args.scale + args.scale // 2
    cv2.circle(img, (ox, oy), 10, (255, 255, 255), 2)
    cv2.putText(img, "origin", (ox + 12, oy - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

    out = Path(f"captures/maps/{args.name}_map.png")
    cv2.imwrite(str(out), img)
    walk = sum(1 for v in cells.values() if v == 0)
    block = len(cells) - walk
    print(f"{out}  ({W}x{H}, 可走 {walk} 格 / 不可走 {block} 格，1 格 = {CELL}px)")


if __name__ == "__main__":
    main()

"""估算各區一趟要多久（用路線設定 + 實測 adb 每次拖曳的額外開銷）。

跑法：python tools/plan.py
用途：排程規劃（各地區刷新時間 vs 一趟耗時），不要拿來當精確計時。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cycle_fixed as cf

OVERHEAD = 0.44      # 每次拖曳除了按住時間之外的額外開銷（實測 20 次拖曳多 8.8 秒）
TELEPORT = 2.0       # 傳送（含冷卻外的固定等待）大約 2 秒
REST = cf.REST_WAIT


def area_seconds(area):
    t = TELEPORT
    for i, act in enumerate(cf.ROUTES[area], 1):
        if act[0] == "REST":
            t += REST + OVERHEAD
            continue
        d, px, _ = cf.route_act(act)
        t += cf.hold_ms(px, cf.route_drag(area, i)) / 1000 + OVERHEAD
    if area in cf.FILL_LEGS:
        for _ in range(cf.FILL_PAIRS):
            for n in cf.FILL_LEGS[area]:
                d, px, _ = cf.route_act(cf.ROUTES[area][n - 1])
                t += cf.hold_ms(px, cf.route_drag(area, n)) / 1000 + OVERHEAD
    return t


if __name__ == "__main__":
    pearl = cf.PEARL_WEST / cf.speed_of(cf.PEARL_DRAG) + cf.PEARL_EAST / cf.speed_of(cf.PEARL_DRAG) + cf.REST_WAIT + 2 * OVERHEAD
    total = 0.0
    for a in ("village", "start", "farm"):
        s = area_seconds(a)
        total += s
        print(f"{cf.LABEL[a]:8s} {s:6.1f}s")
    print(f"{'珍珠':8s} {pearl:6.1f}s（附掛在小村莊）")
    print(f"一趟全區 ≈ {total + pearl:.0f}s（不含珍珠 {total:.0f}s）")

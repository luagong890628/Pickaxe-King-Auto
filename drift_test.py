"""整趟淨位移測試：傳送到某區 → 走完 ROUTES[區] → 量「傳送後 vs 走完」的世界位移。

為什麼不用逐段量測：逐段量測在低紋理方向（西側）與長北腿常常鎖錯/失效
（實測同一段 0/112/173/254 都出現過），拿來算偏差會得到假結論。
整趟淨位移只取兩張圖（起點、終點），位移大、共同特徵多，並印出分數與來源供判讀。

用法
    python drift_test.py --runs 3                # 預設小村莊
    python drift_test.py --area start --runs 2
"""
from __future__ import annotations

import argparse
import statistics
import time

import cycle_fixed as cf
from pkauto import measure


def expected_shift(area: str) -> tuple[float, float]:
    ex = ey = 0.0
    for act in cf.ROUTES[area]:
        if act[0] == "REST":
            continue
        d, px = act
        vx, vy = cf.DIRS[d]
        ex += vx * px
        ey += vy * px
    return ex, ey


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--area", default="village", choices=sorted(cf.ROUTES))
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--settle", type=float, default=1.0)
    ap.add_argument("--settle-first", type=float, default=0.5)
    args = ap.parse_args()

    ex, ey = expected_shift(args.area)
    print(f"[{cf.LABEL[args.area]}] 理論淨位移 ({ex:+.0f},{ey:+.0f})", flush=True)

    rows = []
    for i in range(1, args.runs + 1):
        cf.teleport(args.area, lambda o: None)
        time.sleep(2.5)
        a = cf.shot()
        for n, act in enumerate(cf.ROUTES[args.area], 1):
            settle = args.settle_first if n == 1 else args.settle
            if act[0] == "REST":
                cf.rest(lambda o: None, None, cf.LABEL[args.area])
                time.sleep(settle)
            else:
                cf.leg(None, act[0], act[1], lambda o: None, f"{cf.LABEL[args.area]}[{n}]",
                       settle=settle)
        time.sleep(1.2)
        b = cf.shot()
        m = measure.world_shift(a, b)          # (角色dx, 角色dy, 分數, 來源)
        if not m:
            print(f"  run{i}: 量測失敗（回 None）", flush=True)
            continue
        dx, dy = m[0], m[1]                    # world_shift 回的就是角色位移，不要再取負號
        reliable = m[3] != "低信心" and m[2] >= 0.5
        rows.append((dx, dy, m[2], m[3])) if reliable else None
        print(f"  run{i}: 實走 ({dx:+.0f},{dy:+.0f})  誤差 ({dx - ex:+.0f},{dy - ey:+.0f})"
              f"  [{m[3]} {m[2]:.2f}]{'' if reliable else '  ← 不可信，不列入統計'}", flush=True)

    if len(rows) >= 2:
        for k, name in ((0, "x"), (1, "y")):
            vals = [r[k] for r in rows]
            errs = [r[k] - (ex if k == 0 else ey) for r in rows]
            print(f"  {name}: 平均 {statistics.mean(vals):+.0f}　標準差 {statistics.pstdev(vals):.0f}"
                  f"　誤差平均 {statistics.mean(errs):+.0f}　誤差範圍 {min(errs):+.0f}~{max(errs):+.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

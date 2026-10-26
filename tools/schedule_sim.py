"""模擬排程 30 分鐘：每區會去幾次、空檔多少、珍珠幾次。

用「實測/估算的一趟耗時」＋ cycle_fixed 的 REFRESH 規則跑一次純數學模擬，
不會碰手機。跑法：python tools/schedule_sim.py [分鐘]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cycle_fixed as cf
from plan import area_seconds

MINUTES = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0


def main():
    dur = {a: area_seconds(a) for a in cf.REFRESH}
    pearl = (cf.PEARL_WEST + cf.PEARL_EAST) / cf.speed_of(cf.PEARL_DRAG) + cf.REST_WAIT
    end = MINUTES * 60
    now, last = 0.0, {}
    counts = {a: 0 for a in cf.REFRESH}
    pearls, idle = 0, 0.0
    pearl_ready = 0.0
    while True:
        area, wait = cf.next_stop(now, last)
        if wait > 0:
            if now + wait > end:
                idle += end - now
                break
            idle += wait
            now += wait
            continue
        d = dur[area] + (pearl if area == "village" and now >= pearl_ready else 0.0)
        if now + d > end:
            break
        last[area] = now
        counts[area] += 1
        if area == "village" and now >= pearl_ready:
            pearls += 1
            pearl_ready = now + cf.PEARL_COOLDOWN
        now += d

    print(f"模擬 {MINUTES:g} 分鐘（一趟耗時："
          + "、".join(f"{cf.LABEL[a]} {dur[a]:.0f}s" for a in dur) + f"、珍珠 {pearl:.0f}s）")
    for a in cf.REFRESH:
        c = counts[a]
        limit = int(end // cf.REFRESH[a])
        print(f"  {cf.LABEL[a]:8s} 去 {c:2d} 次（刷新上限 {limit:2d} 次）"
              f"＝ {c * dur[a]:5.0f}s")
    print(f"  {'珍珠':8s} 拿 {pearls:2d} 次 ＝ {pearls * pearl:5.0f}s")
    work = sum(counts[a] * dur[a] for a in dur) + pearls * pearl
    print(f"  做事 {work:.0f}s / {end:.0f}s ＝ {work / end * 100:.0f}%"
          f"　空檔 {idle:.0f}s（{idle / end * 100:.0f}%）")


if __name__ == "__main__":
    main()

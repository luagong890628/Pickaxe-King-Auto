"""跑一條錄好的路線：先傳送到該地區的落點，再 1:1 重播觸控。

用法：
    run_route.py village_loop --area village
    run_route.py start_loop  --area start

為什麼要「先傳送」：重播是相對操作，起點必須和錄製時一樣（傳送落點是固定錨點）。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time

sys.path.insert(0, ".")
from pkauto import teleport

AREA_OF = {"village_loop": "village", "start_loop": "start"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--area", choices=["village", "start"], default=None)
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    area = args.area or AREA_OF.get(args.name)
    if area is None:
        raise SystemExit("請指定 --area village 或 --area start")

    print(f"1) 傳送到 {area} 的落點…", flush=True)
    if not teleport.go(area):
        print("   傳送失敗 → 停止")
        return 1
    print("   傳送成功 ✓ 等 3 秒讓畫面穩定", flush=True)
    time.sleep(3.0)

    cmd = [sys.executable, "replay_touch2.py", args.name] + (["--dry"] if args.dry else [])
    print("2) 1:1 重播觸控…", flush=True)
    r = subprocess.run(cmd, text=True)
    print(f"   重播結束 returncode={r.returncode}")
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())

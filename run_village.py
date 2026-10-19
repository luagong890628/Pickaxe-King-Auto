"""把小村莊路線完整跑一次：先傳送回小村莊落點，再 1:1 重播觸控。

用法：run_village.py [--dry]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, ".")
from pkauto import adb, vision
import replay_cycle as rc          # 重用它的 teleport()（含動態找傳送石、冷卻重試）


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    def rec(o):
        print(json.dumps(o, ensure_ascii=False), flush=True)

    print("1) 傳送回小村莊落點…", flush=True)
    if not rc.teleport("village", rec):
        print("傳送失敗 → 停止")
        return
    print("   傳送成功 ✓ 等 3 秒讓畫面穩定", flush=True)
    time.sleep(3.0)

    name = "village_loop"
    cmd = [sys.executable, "replay_touch2.py", name] + (["--dry"] if args.dry else [])
    print("2) 開始 1:1 重播你的觸控…", flush=True)
    r = subprocess.run(cmd, text=True)
    print(f"   重播結束 returncode={r.returncode}", flush=True)


if __name__ == "__main__":
    main()

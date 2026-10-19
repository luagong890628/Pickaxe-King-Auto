"""錄製「原始搖桿操作」：直接讀取手機的觸控事件（getevent），不做任何猜測。

輸出 data/touch/<name>.json：
{
  "name": ..., "device": "/dev/input/eventN",
  "abs_range": {"x": [min,max], "y": [min,max]},
  "events": [ {"t": 秒, "type": "down"/"move"/"up", "x": 原始值, "y": 原始值}, ... ],
  "screen": [w, h]
}
重播時把原始值線性映射到螢幕座標即可 1:1 重現。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from pathlib import Path

from pkauto import adb

EV_RE = re.compile(r"\[\s*(\d+\.\d+)\]\s+(\S+):\s+(\S+)\s+(\S+)\s+([0-9a-fA-F]+)")


def list_devices():
    out = adb.shell("getevent -pl 2>/dev/null") or ""
    devs, cur = [], None
    for line in out.splitlines():
        m = re.match(r"add device \d+: (\S+)", line)
        if m:
            cur = {"path": m.group(1), "name": "", "ranges": {}}
            devs.append(cur)
            continue
        if cur is None:
            continue
        if "name:" in line:
            cur["name"] = line.split('"')[1] if '"' in line else line.split("name:")[1].strip()
        for axis in ("ABS_MT_POSITION_X", "ABS_MT_POSITION_Y"):
            if axis in line and "min" in line:
                nums = re.findall(r"(min|max)\s+(-?\d+)", line)
                cur["ranges"].setdefault(axis, {})
                for k, v in nums:
                    cur["ranges"][axis][k] = int(v)
    return devs


def pick_touch_device(devs):
    for d in devs:
        if "ABS_MT_POSITION_X" in d["ranges"] and "touch" in (d["name"] + d["path"]).lower():
            return d
    for d in devs:
        if "ABS_MT_POSITION_X" in d["ranges"]:
            return d
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--seconds", type=float, default=600)
    args = ap.parse_args()

    devs = list_devices()
    dev = pick_touch_device(devs)
    if dev is None:
        print("找不到觸控裝置")
        return
    print(f"觸控裝置: {dev['path']} ({dev['name']}) 範圍 {dev['ranges']}")

    out = Path("data/touch")
    out.mkdir(parents=True, exist_ok=True)
    w, h = adb.screen_size()
    events = []
    cur_x = cur_y = None
    down_ts = None
    t0 = None
    print(f"開始錄製 {args.seconds} 秒；在你手機上正常走動即可（我再按 Ctrl-C 或時間到就停）")

    p = subprocess.Popen([adb.adb_path(), "shell", "getevent", "-lt", dev["path"]],
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
    deadline = time.time() + args.seconds
    try:
        while time.time() < deadline:
            line = p.stdout.readline()
            if not line:
                break
            m = EV_RE.search(line)
            if not m:
                continue
            ts, devname, typ, code, val = m.groups()
            ts = float(ts)
            if t0 is None:
                t0 = ts
            if typ == "EV_ABS":
                if code == "ABS_MT_POSITION_X":
                    cur_x = int(val, 16)
                    if down_ts is not None:
                        events.append({"t": round(ts - t0, 4), "type": "move", "x": cur_x, "y": cur_y})
                elif code == "ABS_MT_POSITION_Y":
                    cur_y = int(val, 16)
            elif typ == "EV_KEY" and code in ("BTN_TOUCH", "BTN_LEFT"):
                if val == "DOWN":
                    down_ts = ts
                    events.append({"t": round(ts - t0, 4), "type": "down", "x": cur_x, "y": cur_y})
                elif val == "UP":
                    events.append({"t": round(ts - t0, 4), "type": "up", "x": cur_x, "y": cur_y})
                    down_ts = None
            if len(events) % 200 == 0 and len(events):
                print(f"  …{len(events)} 事件，{round(ts-t0,1)}s")
    except KeyboardInterrupt:
        print("手動停止")
    finally:
        p.terminate()

    rec = {"name": args.name, "device": dev["path"], "abs_range": dev["ranges"],
           "screen": [w, h], "events": events}
    path = out / f"{args.name}.json"
    json.dump(rec, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    nd = sum(1 for e in events if e["type"] == "down")
    print(f"完成：{len(events)} 事件、{nd} 次觸碰 → {path}")


if __name__ == "__main__":
    main()

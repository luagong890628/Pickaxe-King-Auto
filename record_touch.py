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

# getevent 直接指定裝置時「不會」印裝置名稱，所以要讓那段是可選的
EV_RE = re.compile(r"\[\s*(\d+\.\d+)\]\s+(?:(\S+):\s+)?(\S+)\s+(\S+)\s+(\S+)")


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


BAD = ("touchpad", "proximity", "hall", "vibrator", "gpio", "key", "pen", "stylus")


def pick_touch_device(devs):
    """挑真正的螢幕觸控裝置。

    坑：三星手機上還有一個 'sec_touchpad'（保護蓋觸控板），名字也有 touch，
    但它收不到螢幕觸控 → 必須優先 'touchscreen' 並排除 touchpad/proximity 等。
    """
    cands = [d for d in devs if "ABS_MT_POSITION_X" in d["ranges"]
             and not any(b in d["name"].lower() for b in BAD)]
    for d in cands:
        if "touchscreen" in d["name"].lower():
            return d
    return cands[0] if cands else None


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
            # 邊錄邊存：隨時中斷都不會丟資料
            if len(events) != getattr(main, "_saved", -1):
                main._saved = len(events)
                rec_now = {"name": args.name, "device": dev["path"], "abs_range": dev["ranges"],
                           "screen": [w, h], "events": events}
                tmp = out / f".{args.name}.tmp"
                json.dump(rec_now, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
                tmp.replace(out / f"{args.name}.json")      # 原子置換，中斷也不會寫壞
            if Path("data/touch/STOP").exists():
                print("收到 STOP 檔 → 停止錄製")
                break
            if len(events) % 200 == 0 and len(events):
                print(f"  …{len(events)} 事件，{round(ts-t0,1)}s", flush=True)
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

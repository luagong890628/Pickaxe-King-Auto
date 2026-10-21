"""被動校準：偵測「你手指」在手機上的按下／拖動／放開，量出「按住幾秒 = 走幾 px」。

**完全不送任何觸控**：只讀 getevent（sec_touchscreen）＋背景截圖。
用途＝用真手指的資料校正 cycle_fixed.py 的里程常數（SPEED / STARTUP_MS），
取代目前用兩個點硬推的估計值。

用法
    python record_touch_calib.py --devices               # 只列觸控裝置，不錄
    python record_touch_calib.py --name hand1 --minutes 6
    python record_touch_calib.py --report data/touch/hand1.jsonl

每次觸碰輸出一行 JSON（data/touch/<name>.jsonl）：
    {"i":3,"hold_ms":1420,"drag_raw":[0,-210],"drag_px_est":[0,-165],
     "px":[12,486],"dist":486,"resp":0.83,"score":0.87,"a_dt":-0.31}
    px／dist＝角色實際位移（畫面內容往反向移，所以取負號）；resp/score 越高越可信。

錄製要點（踩過的坑都在程式裡）
- 三星另有 sec_touchpad（保護蓋），名字也有 touch → 必須優先 sec_touchscreen。
- getevent 指定裝置時不印裝置名；數值是十六進位；BTN_TOUCH 的值是 DOWN/UP 字串。
- BTN_TOUCH DOWN 比 ABS_MT_POSITION 先到 → 起點座標取「DOWN 之後第一次出現的座標」。
"""
from __future__ import annotations

import argparse
import json
import queue
import re
import statistics
import subprocess
import threading
import time
from pathlib import Path

from pkauto import adb, vision

EV_RE = re.compile(r"\[\s*(\d+\.\d+)\]\s+(?:(\S+):\s+)?(\S+)\s+(\S+)\s+(\S+)")

# raw(0–4095) → 螢幕 px 的近似比例（舊校正實測；只用來顯示，判定一律用畫面量到的位移）
RAW_X, RAW_Y = 0.337, 0.787

POST = 1.2          # 放開後等角色停稳再截圖（實測 0.8 秒內會停，1.2 較保險）
TAP_MS = 250        # 短於此視為「點擊」不列入里程擬合


# ---------------- 裝置探索（純函式，可單元測試）----------------

def list_devices(out: str):
    """解析 `getevent -pl` 的輸出 → [{path, name, ranges}]。"""
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
                cur["ranges"].setdefault(axis, {})
                for k, v in re.findall(r"(min|max)\s+(-?\d+)", line):
                    cur["ranges"][axis][k] = int(v)
    return devs


BAD = ("touchpad", "proximity", "hall", "vibrator", "gpio", "key", "pen", "stylus")


def pick_touch_device(devs):
    """挑真正的螢幕觸控裝置：優先名稱含 touchscreen，排除 touchpad/proximity 等。"""
    cands = [d for d in devs if "ABS_MT_POSITION_X" in d["ranges"]
             and not any(b in d["name"].lower() for b in BAD)]
    for d in cands:
        if "touchscreen" in d["name"].lower():
            return d
    return cands[0] if cands else None


# ---------------- 事件解析（純函式，可單元測試）----------------

def parse_line(line: str):
    """→ (ts, type, code, value) 或 None。"""
    m = EV_RE.search(line)
    if not m:
        return None
    ts, _dev, typ, code, val = m.groups()
    return float(ts), typ, code, val


def _num(val: str):
    """hex（getevent 預設）優先，失敗再試十進位。"""
    try:
        return int(val, 16)
    except ValueError:
        return None


def _is_down(val: str) -> bool:
    return val in ("DOWN", "00000001", "1")


def _is_up(val: str) -> bool:
    return val in ("UP", "00000000", "0")


# ---------------- 背景截圖（唯一的 screencap 來源）----------------

class Shooter(threading.Thread):
    """持續截圖，保留最近一張；可要求「時間超過 X 之後的第一張」。"""

    def __init__(self):
        super().__init__(daemon=True)
        self.lock = threading.Lock()
        self.latest = None          # (ts, frame)
        self.target = None
        self.answer = None
        self.stop = False
        self.count = 0

    def run(self):
        while not self.stop:
            t0 = time.time()
            try:
                img = vision.normalize_brightness(adb.screencap())
            except Exception:
                time.sleep(0.4)
                continue
            ts = (t0 + time.time()) / 2
            with self.lock:
                self.latest = (ts, img)
                self.count += 1
                if self.target is not None and ts >= self.target:
                    self.answer = (ts, img)
                    self.target = None

    def before(self, ts):
        with self.lock:
            return self.latest

    def snap_after(self, ts: float, timeout: float = 8.0):
        with self.lock:
            self.answer, self.target = None, ts
        end = time.time() + timeout
        while time.time() < end:
            with self.lock:
                if self.answer is not None:
                    return self.answer
            time.sleep(0.05)
        return None


class Reader(threading.Thread):
    """getevent 讀取執行緒 → queue（主執行緒只處理，不會漏事件）。"""

    def __init__(self, dev_path: str):
        super().__init__(daemon=True)
        self.q: queue.Queue = queue.Queue()
        self.p = subprocess.Popen(
            [adb.adb_path(), "shell", "getevent", "-lt", dev_path],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)

    def run(self):
        for line in self.p.stdout:
            self.q.put(line)
        self.q.put(None)


# ---------------- 錄製 ----------------

def record(name: str, minutes: float, post: float):
    devs = list_devices(adb.shell("getevent -pl 2>/dev/null") or "")
    dev = pick_touch_device(devs)
    if dev is None:
        print("找不到觸控裝置")
        return 1
    print(f"觸控裝置 {dev['path']}（{dev['name']}）")
    print("開始錄製：手機畫面上正常走動即可（本程式不會送任何觸控）。Ctrl+C 停止。")

    out = Path("data/touch")
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{name}.jsonl"
    f = path.open("w", encoding="utf-8")

    shooter = Shooter()
    shooter.start()
    reader = Reader(dev["path"])
    reader.start()

    cur_x = cur_y = None
    down = None
    i = 0
    deadline = time.time() + minutes * 60
    try:
        while time.time() < deadline:
            try:
                line = reader.q.get(timeout=0.5)
            except queue.Empty:
                continue
            if line is None:
                break
            ev = parse_line(line)
            if ev is None:
                continue
            ts, typ, code, val = ev

            if typ == "EV_ABS":
                n = _num(val)
                if n is None:
                    continue
                if code == "ABS_MT_POSITION_X":
                    cur_x = n
                elif code == "ABS_MT_POSITION_Y":
                    cur_y = n
                elif code == "ABS_MT_TRACKING_ID" and _num(val) == 4294967295:
                    pass
                if down is not None and cur_x is not None and cur_y is not None:
                    down["points"].append((cur_x, cur_y))

            elif typ == "EV_KEY" and code == "BTN_TOUCH":
                if _is_down(val):
                    a = shooter.before(ts)
                    down = {"ts": ts, "x": cur_x, "y": cur_y, "a": a, "points": []}
                elif _is_up(val) and down is not None:
                    hold_ms = int(round((ts - down["ts"]) * 1000))
                    b = shooter.snap_after(ts + post)
                    rec = {"i": i, "hold_ms": hold_ms, "tap": hold_ms < TAP_MS}
                    if down["x"] is not None and cur_x is not None:
                        rx, ry = cur_x - down["x"], cur_y - down["y"]
                        rec["drag_raw"] = [rx, ry]
                        rec["drag_px_est"] = [round(rx * RAW_X), round(ry * RAW_Y)]
                    if down["points"]:
                        px0, py0 = down["x"], down["y"]
                        far = max(down["points"], key=lambda p: (p[0] - px0) ** 2 + (p[1] - py0) ** 2)
                        rec["far_raw"] = [far[0] - px0, far[1] - py0]
                    if down["a"] is not None and b is not None:
                        ats, aimg = down["a"]
                        bts, bimg = b
                        rec["a_dt"] = round(down["ts"] - ats, 2)
                        rec["b_dt"] = round(bts - ts, 2)
                        sh = vision.shift_by_template(aimg, bimg, threshold=0.6)
                        if sh:
                            # 畫面內容往右移＝角色往左走 → 角色位移取負號
                            rec["px"] = [-round(sh[0]), -round(sh[1])]
                            rec["dist"] = round((sh[0] ** 2 + sh[1] ** 2) ** 0.5)
                            rec["score"] = round(sh[2], 2)
                            rec["patches"] = sh[3]
                        else:
                            rec["px"] = None
                    else:
                        rec["px"] = None
                    i += 1
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    f.flush()
                    d = rec.get("dist")
                    extra = f"，角色位移 {rec['px']}（{d}px）" if d else "，位移量測失敗"
                    print(f"  #{rec['i']} 按住 {hold_ms}ms{'(點擊)' if rec['tap'] else ''}{extra}", flush=True)
                    down = None
    except KeyboardInterrupt:
        print("手動停止")
    finally:
        shooter.stop = True
        reader.p.terminate()
        f.close()
    print(f"完成：{i} 次觸碰 → {path}")
    print("接著跑報告：--report " + str(path))
    return 0


# ---------------- 報告／擬合 ----------------

def load(path):
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def fit_mileage(points):
    """最小平方擬合 dist = SPEED*(hold_s - STARTUP) → (speed_px_s, startup_s, r2)。"""
    pts = [(h, d) for h, d in points if d is not None]
    if len(pts) < 2:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    a = sum((x - mx) * (y - my) for x, y in pts) / sxx
    b = my - a * mx
    if a == 0:
        return None
    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - (a * x + b)) ** 2 for x, y in pts)
    r2 = 1 - ss_res / ss_tot if ss_tot else 1.0
    return a, -b / a, r2


def report(path: str):
    import cycle_fixed as cf
    rows = load(path)
    good = [r for r in rows if r.get("dist") and not r.get("tap")
            and r.get("score", 0) >= 0.5 and r.get("dist", 0) >= 40]
    print(f"共 {len(rows)} 次觸碰，可用 {len(good)} 筆（排除點擊／位移 <40px／分數 <0.5）")
    print(f"{'#':>3} {'按住ms':>7} {'角色位移px':>11} {'分數':>5}  方向")
    for r in rows:
        px = r.get("px")
        d = r.get("dist")
        if px and d:
            ns = ("南" if px[1] > 0 else "北") if abs(px[1]) >= abs(px[0]) else ("東" if px[0] > 0 else "西")
            print(f"{r['i']:>3} {r['hold_ms']:>7} {d:>11} {r.get('score', 0):>5}  {ns}")
        else:
            print(f"{r['i']:>3} {r['hold_ms']:>7} {'—':>11} {'—':>5}  （量不到）")
    fit = fit_mileage([(r["hold_ms"] / 1000, r["dist"]) for r in good])
    print()
    if fit:
        v, t0, r2 = fit
        print(f"實測擬合：px = {v:.0f} × (按住秒 − {t0:.3f})   R² = {r2:.3f}")
    print(f"目前程式：px = {cf.SPEED:.0f} × (按住秒 − {cf.STARTUP_MS / 1000:.3f})")
    print("\n按住秒 → 程式預測 / 實測平均")
    for h in (0.7, 1.0, 1.5, 2.0, 2.5):
        near = [(r["hold_ms"] / 1000, r["dist"]) for r in good
                if abs(r["hold_ms"] / 1000 - h) <= 0.15]
        pred = cf.SPEED * max(0.0, h - cf.STARTUP_MS / 1000)
        meas = f"{statistics.fmean([d for _, d in near]):.0f}px（{len(near)} 筆）" if near else "—"
        print(f"  {h:.1f}s → {pred:.0f}px / {meas}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="hand")
    ap.add_argument("--minutes", type=float, default=6)
    ap.add_argument("--post", type=float, default=POST)
    ap.add_argument("--devices", action="store_true")
    ap.add_argument("--report")
    args = ap.parse_args()
    if args.devices:
        for d in list_devices(adb.shell("getevent -pl 2>/dev/null") or ""):
            print(d["path"], d["name"], d["ranges"].get("ABS_MT_POSITION_X"))
        return 0
    if args.report:
        return report(args.report)
    return record(args.name, args.minutes, args.post)


if __name__ == "__main__":
    raise SystemExit(main())

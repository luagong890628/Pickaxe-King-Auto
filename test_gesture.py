"""驗證：一個「按下→瞬間移到→停住→放開」手勢能不能正確移動角色。

對照組：swipe（手指慢慢滑） vs motionevent 序列（按下即到位後停住）。
"""

import subprocess
import sys
import time

sys.path.insert(0, ".")
from pkauto import adb, vision


def shot():
    return vision.normalize_brightness(adb.screencap())


def measure(before, after):
    sh = vision.shift_by_template(before, after, threshold=0.6)
    if sh:
        return sh[0], sh[1], sh[2]
    s = vision.scroll(before, after)
    return s[0], s[1], s[2]


def one_shell_gesture(x1, y1, x2, y2, hold_ms):
    """單一 adb shell 內完成 DOWN→MOVE→停住→UP（＝真實觸控的模式）。"""
    cmd = (
        f"input motionevent DOWN {x1} {y1}; "
        f"input motionevent MOVE {x2} {y2}; "
        f"sleep {hold_ms/1000:.2f}; "
        f"input motionevent UP {x2} {y2}"
    )
    adb.shell(cmd, timeout=hold_ms / 1000 + 20)


def main():
    tests = [
        ("swipe 400px 1.0s", lambda: adb.swipe(720, 2600, 720, 2200, 1000)),
        ("motionevent 序列 400px 1.0s", lambda: one_shell_gesture(720, 2600, 720, 2200, 1000)),
        ("swipe 200px 0.5s", lambda: adb.swipe(720, 2600, 720, 2400, 500)),
        ("motionevent 序列 200px 0.5s", lambda: one_shell_gesture(720, 2600, 720, 2400, 500)),
    ]
    for name, act in tests:
        a = shot()
        t0 = time.time()
        act()
        dt = time.time() - t0
        time.sleep(1.2)
        b = shot()
        dx, dy, q = measure(a, b)
        dist = (dx * dx + dy * dy) ** 0.5
        print(f"{name}: 位移 {dist:6.1f}px (dx={dx:6.1f}, dy={dy:6.1f}) q={q:.2f} 耗時 {dt:.2f}s", flush=True)
        time.sleep(1.5)


if __name__ == "__main__":
    main()

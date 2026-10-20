"""驗證「按下→瞬間移到定點→停住→放開」vs swipe 的位移差異（單一 shell 手勢）。"""

import sys
import time

sys.path.insert(0, ".")
from pkauto import adb, vision


def shot():
    return vision.normalize_brightness(adb.screencap())


def measure(a, b):
    sh = vision.shift_by_template(a, b, threshold=0.6)
    if sh:
        return sh[0], sh[1]
    s = vision.scroll(a, b)
    return s[0], s[1]


def hold_gesture(x1, y1, x2, y2, hold_s):
    adb.shell(
        f"input motionevent DOWN {x1} {y1}; "          # 按下去
        f"input motionevent MOVE {x2} {y2}; "          # 瞬間拖到定點（真實手指就是這樣）
        f"sleep {hold_s:.2f}; "                        # 停住 = 角色持續走
        f"input motionevent UP {x2} {y2}",             # 放開
        timeout=hold_s + 20,
    )


def main():
    # 第一段真實錄製：位移 311px、按住 1612ms → 預期走 ~500-600px（全速約 490px/s）
    for name, fn in [
        ("swipe 311px 1612ms", lambda: adb.swipe(673, 2617, 612, 2312, 1612)),
        ("hold 手勢 311px 1612ms", lambda: hold_gesture(673, 2617, 612, 2312, 1.612)),
        ("hold 手勢 311px 500ms", lambda: hold_gesture(673, 2617, 612, 2312, 0.500)),
    ]:
        a = shot()
        fn()
        time.sleep(1.3)
        b = shot()
        dx, dy = measure(a, b)
        print(f"{name}: 位移 {((dx**2+dy**2)**0.5):6.1f}px (dx={dx:6.1f} dy={dy:6.1f})", flush=True)
        time.sleep(1.5)


if __name__ == "__main__":
    main()

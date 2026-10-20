"""休息流程：生命值歸零後回起始之地找帳篷 → 點「在小屋裡休息！」→ 等恢復。

實測要點
- 傳送到起始之地的落點後**不一定**立刻貼著帳篷 → 要小步繞行找。
- 休息對話框是**唯一可以點的白框**（其他大白框是彈窗/黑市，點了會出事）。
  因此偵測條件收得很緊（rest.find_rest_dialog：1004x220、中心 y≈1839）。
- 休息約 3 秒，醒來後左右工具列會回來。

用法：
    from pkauto.restflow import go_rest
    ok = go_rest()
"""
from __future__ import annotations

import time

from . import adb, rest, teleport, vision
from . import popup


def _shot():
    return vision.normalize_brightness(adb.screencap())


def _move(dx, dy, dist=170):
    """小步移動（按住時間控制），回傳是否真的有動。"""
    import math
    a = math.atan2(dy, dx)
    hold = int(min(900, max(240, dist / 315.0 * 1000)))
    adb.swipe(720, 2600, int(720 + math.cos(a) * 240), int(2600 + math.sin(a) * 240), hold)
    time.sleep(hold / 1000.0 + 0.4)


def go_rest(verbose=print) -> bool:
    """傳送到起始之地 → 繞行找帳篷 → 休息。成功回傳 True。"""
    verbose("休息流程：傳送到起始之地")
    if not teleport.go("start"):
        verbose("  傳送失敗")
        return False
    time.sleep(2.5)

    # 實測：起始之地傳送落點「往北走約 2 步（400px）」就會貼到帳篷
    # 先走這條已知路徑，找不到再用八方向繞行
    pattern = [(0, -1), (0, -1), (0, -1), (0, -1),
               (-1, 0), (1, 0), (0, 1), (-1, -1), (1, -1), (-1, 1), (1, 1)]
    for round_i in range(len(pattern)):
        img = _shot()
        if popup.close_popup(img):
            verbose("  先關掉彈窗")
            img = _shot()
        box = rest.find_rest_dialog(img)
        if box:
            verbose(f"  找到帳篷 → 點擊休息 {box}")
            adb.tap(box[0], box[1])
            time.sleep(4.5)
            if not rest.has_rest_dialog(_shot()):
                verbose("  休息完成 ✓")
                return True
            verbose("  對話框還在 → 再點一次")
            adb.tap(box[0], box[1])
            time.sleep(4.5)
            return True
        dx, dy = pattern[round_i % len(pattern)]
        verbose(f"  繞行找帳篷 #{round_i+1} 方向({dx},{dy})")
        _move(dx, dy, 180)

    # 最後再試一次
    img = _shot()
    box = rest.find_rest_dialog(img)
    if box:
        adb.tap(box[0], box[1])
        time.sleep(4.5)
        verbose("  最後一次點擊休息")
        return True
    verbose("  找不到帳篷")
    return False

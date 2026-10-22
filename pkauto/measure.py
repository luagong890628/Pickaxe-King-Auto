"""世界位移量測（角色位移）：範本比對＋相位相關交叉驗證。

為什麼要兩個都算
- `shift_by_template` 在**重複性地形**（草地、成排樹叢）會鎖到錯的位置：
  實測同一組畫面「角色真的走 136px」被量成 **604px**（分數只有 0.81，正常是 0.94–1.00）。
- `vision.scroll`（相位相關）在**有動物/落葉/水波動畫**時失準，resp 掉到 0.3x。

規則
- 範本分數 ≥ 0.9 且相位resp < 0.45 → 用範本（動畫干擾大的情況）
- 相位 resp ≥ 0.45 且範本分數 < 0.9 → 用相位（範本鎖錯的情況）
- 兩者都可信 → 一致（差距 ≤ max(30px, 20%)）就取範本，不一致就取分數較高者並標記 "!"
- 兩者都不可信 → 回範本結果但標記 "低信心"
"""
from __future__ import annotations

import math

import numpy as np

from . import vision

TEMPLATE_MIN = 0.90
SCROLL_MIN = 0.45


def _agree(a, b) -> bool:
    dx, dy = a[0] - b[0], a[1] - b[1]
    gap = math.hypot(dx, dy)
    return gap <= max(30.0, 0.2 * math.hypot(*a))


def world_shift(a: np.ndarray, b: np.ndarray, template_min: float = TEMPLATE_MIN,
                scroll_min: float = SCROLL_MIN):
    """→ (dx, dy, score, source)（dx/dy 是**角色**位移，畫面位移取負號）；量不到回 None。"""
    sh = vision.shift_by_template(a, b, threshold=0.6)
    sdx, sdy, resp = vision.scroll(a, b)
    t = (-sh[0], -sh[1], float(sh[2])) if sh else None
    s = (-sdx, -sdy, float(resp))

    if t is None:
        return s[0], s[1], s[2], "scroll" if resp >= scroll_min else "scroll?"
    t_ok, s_ok = t[2] >= template_min, s[2] >= scroll_min

    if t_ok and not s_ok:
        return t[0], t[1], t[2], "template"
    if s_ok and not t_ok:
        return s[0], s[1], s[2], "scroll"
    if t_ok and s_ok:
        if _agree(t, s):
            return t[0], t[1], t[2], "template"
        if t[2] >= s[2]:
            return t[0], t[1], t[2], "template!"
        return s[0], s[1], s[2], "scroll!"
    # 兩者都低於門檻：取相位（大位移時範本鎖錯的代價更高）
    return s[0], s[1], s[2], "低信心"

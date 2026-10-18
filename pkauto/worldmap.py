"""世界地圖定位（本專案智慧化的核心）。

為什麼這樣做：之前用「小尺度特徵」（樹葉紋理、屋簷細節）做位移量測／畫面比對都失敗——
遊戲地形大量重複（樹林/草地長得像），小特徵一定認錯。但「水/陸分布」是**大尺度、穩定**的
特徵（畫面上有雞在跑、樹在搖都不影響水的邊界），拿它當指紋就能定位。

作法：
1. 觀測：把可見區域切成 60px 格子，每格記三個比例——水、木造(建築)、深綠地板。
   這些都是「大尺度、不太動」的東西（刻意排除樹冠：樹會被砍掉又重生）。
2. 地圖：`{(格座標): [水總和, 木總和, 深綠總和, 次數]}`，用多次觀測平均。
3. 定位：給定預測位置，在 ±N 格內搜尋「觀測 vs 地圖」誤差最小的位置 → 修正座標。
   每步都修正 → 誤差不會累積（這正是前幾版缺的）。
4. 沒有足夠已知格可對比時（例如剛開始、或在大片陸地中央）就沿用預測位置。
"""
from __future__ import annotations

import math

import cv2
import numpy as np

CELL = 60                    # 世界格子大小（px）
VIEW = (1440, 3120)          # 畫面尺寸
BOX = (120, 1240)            # 只取中間可視區的 x 範圍（排除左右 UI）
FEATURES = 3                 # 水、木造、深綠地板


def _masks(img):
    """三個「大尺度、穩定」的特徵遮罩：水、樹冠覆蓋、深綠地板。

    刻意不用「木造/棕色」——農田泥土、木箱、橋都是棕色會混淆。
    樹冠雖然會被砍掉又重生，但大尺度上森林區塊仍然穩定，只是權重要容忍雜訊。
    """
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    b, g, r = cv2.split(img.astype("int16"))
    water = ((b > 165) & (b > r + 35) & (g > r)).astype(np.float32)
    canopy = ((h > 45) & (h < 95) & (s > 150) & (v > 80)).astype(np.float32)
    dark = ((g > 100) & (g < 190) & (b < 95) & (r < 130) & ~(canopy > 0)).astype(np.float32)
    return water, canopy, dark


def observe(img) -> dict:
    """回傳 {(dx_cell, dy_cell): np.array([水, 木, 深綠])}（相對角色的格子偏移）。"""
    img = cv2.resize(img, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA)
    water, wood, dark = _masks((img * 4).astype(np.uint8))
    h, w = img.shape[:2]
    cs = CELL // 4                                   # 縮圖上每格 = 15px
    out = {}
    for gy in range(0, h // cs):
        for gx in range(0, w // cs):
            x0, y0 = gx * cs, gy * cs
            wx = x0 * 4 + CELL / 2 - (VIEW[0] / 2)
            wy = y0 * 4 + CELL / 2 - (VIEW[1] / 2)
            if not (BOX[0] - VIEW[0] / 2 < wx < BOX[1] - VIEW[0] / 2):
                continue
            cx, cy = int(math.floor(wx / CELL)), int(math.floor(wy / CELL))
            vals = np.array([water[y0:y0 + cs, x0:x0 + cs].mean(),
                             wood[y0:y0 + cs, x0:x0 + cs].mean(),
                             dark[y0:y0 + cs, x0:x0 + cs].mean()], dtype=np.float32)
            out[(cx, cy)] = vals
    return out


def localize(obs: dict, world: dict, pred_pos, radius_cells: int = 8, min_cells: int = 25):
    """在預測位置附近找最匹配的格子位移。回傳 (新位置, 誤差, 用了幾格)。"""
    pcx = int(math.floor(pred_pos[0] / CELL))
    pcy = int(math.floor(pred_pos[1] / CELL))
    best = None
    for dy in range(-radius_cells, radius_cells + 1):
        for dx in range(-radius_cells, radius_cells + 1):
            errs, n = 0.0, 0
            for (ocx, ocy), v in obs.items():
                w = world.get((ocx + pcx + dx, ocy + pcy + dy))
                if w is None or w[3] < 2:            # 該格還沒看過足夠次數
                    continue
                avg = w[:FEATURES] / w[3]
                errs += float(np.abs(avg - v).sum())
                n += 1
            if n >= min_cells:
                e = errs / n
                if best is None or e < best[0]:
                    best = (e, (pcx + dx) * CELL + CELL / 2, (pcy + dy) * CELL + CELL / 2, n)
    if best is None:
        return pred_pos, None, 0
    return (best[1], best[2]), best[0], best[3]


def update(world: dict, obs: dict, pos):
    """把觀測併入地圖（在已知位置上）。"""
    pcx = int(math.floor(pos[0] / CELL))
    pcy = int(math.floor(pos[1] / CELL))
    for (ocx, ocy), v in obs.items():
        k = (ocx + pcx, ocy + pcy)
        w = world.get(k)
        if w is None:
            world[k] = np.array([v[0], v[1], v[2], 1.0], dtype=np.float64)
        else:
            w[0] += v[0]
            w[1] += v[1]
            w[2] += v[2]
            w[3] += 1
    return world


def render(world: dict, path, scale: int = 6):
    """畫出地圖：藍=水多、棕=木多、深綠=深綠地板、綠=一般陸地。"""
    if not world:
        return None
    xs = [k[0] for k in world]
    ys = [k[1] for k in world]
    x0, x1 = min(xs) - 1, max(xs) + 2
    y0, y1 = min(ys) - 1, max(ys) + 2
    W, H = (x1 - x0) * scale, (y1 - y0) * scale
    img = np.full((H, W, 3), 35, np.uint8)
    for (cx, cy), w in world.items():
        if w[3] < 1:
            continue
        wat, can, dk = w[0] / w[3], w[1] / w[3], w[2] / w[3]
        if wat > 0.5:
            col = (230, 140, 60)        # 水（藍）
        elif can > 0.5:
            col = (40, 140, 40)         # 樹冠（深綠）
        elif dk > 0.5:
            col = (60, 120, 60)         # 深綠地板
        else:
            col = (150, 220, 150)       # 一般陸地（淺綠）
        px, py = (cx - x0) * scale, (cy - y0) * scale
        cv2.rectangle(img, (px, py), (px + scale - 1, py + scale - 1), col, -1)
    ox = (0 // CELL - x0) * scale
    oy = (0 // CELL - y0) * scale
    cv2.circle(img, (ox + scale // 2, oy + scale // 2), 9, (255, 255, 255), 2)
    cv2.imwrite(str(path), img)
    return path

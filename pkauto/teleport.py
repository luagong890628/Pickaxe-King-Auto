"""傳送石：用「藍色愛心範本」開傳送選單，再點指定地區格子。

實測重點（踩過的坑）
- 傳送石愛心有冷卻（會顯示「2s」），冷卻中點了沒反應 → 要重試。
- 愛心會被天空/水面干擾，用顏色找不可靠 → 用範本比對（captures/tpl_heart.png）。
- 選單格子會慣性滑動 → 連續兩張畫面位置一致（<4px）才點。
- 關選單＝點面板外的空白處（點面板內會選到別的地區）。
"""
from __future__ import annotations

import time

import cv2
import numpy as np

from . import adb, vision

MENU_BG = np.array([255, 211, 143])
HEART_ROI = (1240, 1400, 1440, 2000)      # 右側 UI 欄中愛心可能出現的範圍
TILE_TPL = "captures/tpl_tile_{}.png"


def menu_share(img) -> float:
    """畫面上「傳送選單底色」的比例（>0.10 視為選單開著）。"""
    mid = img[560:2840, 60:1380]
    return float((np.abs(mid.astype(np.int16) - MENU_BG).max(axis=2) < 45).mean())


def shot():
    return vision.normalize_brightness(adb.screencap())


def close_menu():
    adb.tap(720, 300)
    time.sleep(1.2)
    if menu_share(shot()) > 0.10:
        adb.tap(720, 3060)
        time.sleep(1.2)


def open_menu(tries=6, wait=6.0) -> bool:
    """點傳送石開選單；冷卻中會等。"""
    if menu_share(shot()) > 0.10:
        return True
    heart = cv2.imread("captures/tpl_heart.png")
    for i in range(tries):
        s = shot()
        x0, y0, x1, y1 = HEART_ROI
        r = vision.find(s[y0:y1, x0:x1], heart, 0.80) if heart is not None else None
        if r:
            hx, hy = r[0] + x0, r[1] + y0
            adb.tap(hx, hy)
            time.sleep(2.2)
            if menu_share(shot()) > 0.10:
                return True
        time.sleep(wait)
    return False


def select(area: str, tries=8) -> bool:
    """在已開啟的選單中選地區（會捲動找格子，確認靜止才點）。"""
    tpl = cv2.imread(TILE_TPL.format(area))
    if tpl is None:
        raise FileNotFoundError(TILE_TPL.format(area))
    for _ in range(tries):
        s1 = shot()
        time.sleep(1.3)
        s2 = shot()
        r1 = vision.find(s1, tpl, 0.85)
        r2 = vision.find(s2, tpl, 0.85)
        if r1 and r2 and abs(r1[0] - r2[0]) < 4 and abs(r1[1] - r2[1]) < 4:
            adb.tap(r2[0], r2[1])
            time.sleep(3.0)
            return menu_share(shot()) < 0.10          # 選單關掉＝傳送成功
        adb.swipe(720, 2300, 720, 1900, 600)
        time.sleep(1.6)
    return False


def go(area: str) -> bool:
    """完整流程：開選單 → 選地區。回傳是否成功。"""
    if not open_menu():
        return False
    return select(area)

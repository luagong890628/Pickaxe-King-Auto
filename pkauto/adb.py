"""adb 控制層：截圖、點擊、滑動、按鍵。

adb 路徑預設為 scrcpy 內附版本，可用環境變數 PKAUTO_ADB 覆寫。
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import cv2
import numpy as np

DEFAULT_ADB = r"D:/Tools/scrcpy-win64-v3.3.4/adb.exe"
CAPTURES = Path(__file__).resolve().parent.parent / "captures"


def adb_path() -> str:
    return os.environ.get("PKAUTO_ADB", DEFAULT_ADB)


def _run(args, timeout=30):
    return subprocess.run(
        [adb_path(), *args], capture_output=True, timeout=timeout
    )


def screencap() -> np.ndarray:
    """回傳目前畫面（BGR ndarray）。

    用 exec-out 直接取 bytes，避免 Windows 上 shell 重導向把 PNG 的 \\n 換成 \\r\\n。
    """
    raw = _run(["exec-out", "screencap", "-p"]).stdout
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError("screencap 解碼失敗（畫面未取得或 adb 無回應）")
    return img


def screencap_to(path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), screencap())
    return path


def save(img: np.ndarray, name: str) -> Path:
    """把影像存到 captures/，回傳路徑。"""
    return _imwrite(CAPTURES / name, img)


def _imwrite(path: Path, img: np.ndarray) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), img)
    return path


def tap(x: int, y: int) -> None:
    _run(["shell", "input", "tap", str(int(x)), str(int(y))])


def swipe(x1: int, y1: int, x2: int, y2: int, ms: int = 300) -> None:
    _run(["shell", "input", "swipe",
          str(int(x1)), str(int(y1)), str(int(x2)), str(int(y2)), str(int(ms))])


def long_press(x: int, y: int, ms: int = 800) -> None:
    """原地長按（起點終點相同的 swipe）。"""
    swipe(x, y, x, y, ms)


def keyevent(code: int) -> None:
    _run(["shell", "input", "keyevent", str(int(code))])


def current_app() -> str:
    """回傳目前有焦點的視窗（含 package/activity）。"""
    out = _run(["shell", "dumpsys", "window"]).stdout.decode("utf-8", "replace")
    for line in out.splitlines():
        if "mCurrentFocus" in line and "null" not in line:
            return line.strip()
    return ""

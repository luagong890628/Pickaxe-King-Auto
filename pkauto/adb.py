"""adb 控制層：截圖、點擊、滑動、按鍵。

adb 路徑預設為 scrcpy 內附版本，可用環境變數 PKAUTO_ADB 覆寫。
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import cv2
import numpy as np

# 全部是「指令根本沒送到手機」的錯誤，重送不會讓角色多走一段：daemon 連不上，
# 或 transport 狀態在轉送前就被拒絕（AOSP 原始碼依據見 README「已知」）。
NOT_DELIVERED_MARKERS = (
    "daemon still not running",   # server 死了且起不回來
    "daemon not running",         # server 已死，client 這次才把它拉起來
    "cannot connect to daemon",   # 連不上 127.0.0.1:5037
    "failed to check server version",
    "adb server didn't ack",
    "adb server version",
    "device offline",             # 含 (no transport)／(transport offline) 兩個變體
    "device still connecting",
    "device still authorizing",
)
SERVER_RESTART_ATTEMPTS = 3     # 最多重開 server 幾次
SERVER_RESTART_DELAY = 1.5      # 每次重開後等裝置重新列舉（秒）

DEFAULT_ADB = r"D:/Tools/scrcpy-win64-v3.3.4/adb.exe"
CAPTURES = Path(__file__).resolve().parent.parent / "captures"


def adb_path() -> str:
    return os.environ.get("PKAUTO_ADB", DEFAULT_ADB)


def _command(args) -> list[str]:
    """組成 ADB 指令；有指定 serial 時固定使用該 transport。"""
    serial = os.environ.get("ANDROID_SERIAL")
    prefix = [adb_path()]
    if serial:
        prefix.extend(["-s", serial])
    return [*prefix, *args]


def shell(cmd: str, timeout: int = 30) -> str:
    """執行 adb shell 指令，回傳 stdout 字串。"""
    return _run(["shell", cmd], timeout=timeout).stdout.decode("utf-8", "replace")


def screen_size() -> tuple[int, int]:
    """回傳 (寬, 高) 像素。"""
    out = shell("wm size")
    for tok in out.split():
        if "x" in tok and tok.replace("x", "").isdigit():
            w, h = tok.split("x")
            return int(w), int(h)
    return 1440, 3120


def _not_delivered(stderr: bytes) -> bool:
    """stderr 是否代表「指令根本沒送到手機」（實機字串見 tests，原始碼依據見 README）。"""
    text = stderr.decode("utf-8", "replace").lower()
    if any(marker in text for marker in NOT_DELIVERED_MARKERS):
        return True
    # server 重開後無線裝置不在清單裡（device 'IP:PORT' not found），指令同樣沒送出；
    # 要求 "device '" 是為了排除手機上指令自己噴的 `sh: xxx: not found`。
    return "device '" in text and "not found" in text


def restart_server() -> None:
    """重開 adb server（best effort）；無線 serial 必須重新 connect 才接得回。"""
    adb = adb_path()
    serial = os.environ.get("ANDROID_SERIAL")
    commands = [[adb, "kill-server"], [adb, "start-server"]]
    if serial and ":" in serial:
        commands.append([adb, "connect", serial])
    for command in commands:
        try:
            subprocess.run(command, capture_output=True, timeout=30)
        except (subprocess.TimeoutExpired, OSError):
            pass  # 連 adb.exe 都叫不動時不在此處中斷；重試耗盡後由 _run 回報原因


def _run(args, timeout=30):
    """跑一條 adb 指令；server 沒回應或卡到 timeout 就重開 server 重送（見 README「執行」）。"""
    code = None
    reason = ""
    for attempt in range(SERVER_RESTART_ATTEMPTS + 1):
        try:
            result = subprocess.run(_command(args), capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            code, reason, retry = None, f"指令逾時 {timeout}s", True
        else:
            if not result.returncode:
                return result
            code = result.returncode
            reason = result.stderr.decode("utf-8", "replace").strip()
            retry = _not_delivered(result.stderr)
        if not retry or attempt == SERVER_RESTART_ATTEMPTS:
            break
        print(f"ADB 無回應（{reason.splitlines()[0] if reason else '未知錯誤'}），"
              f"重啟 adb server 後重試（{attempt + 1}/{SERVER_RESTART_ATTEMPTS}）",
              flush=True)
        restart_server()
        time.sleep(SERVER_RESTART_DELAY)
    if attempt:
        reason += f"（已重啟 adb server {attempt} 次仍失敗）"
    raise RuntimeError(f"ADB 指令失敗（{code or '逾時'}）：{reason}")


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
          str(int(x1)), str(int(y1)), str(int(x2)), str(int(y2)), str(int(ms))],
         timeout=max(30, ms / 1000 + 10))


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

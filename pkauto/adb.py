"""adb 控制層：截圖、點擊、滑動、按鍵。

adb 路徑預設為 scrcpy 內附版本，可用環境變數 PKAUTO_ADB 覆寫。
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np

# 全部是「指令根本沒送到手機」的錯誤，重送不會讓角色多走一段（AOSP 原始碼依據見 README「已知」）。
# daemon 層級：server 本身有問題，必須重開。
DAEMON_MARKERS = (
    "daemon still not running",   # server 死了且起不回來
    "daemon not running",         # server 已死，client 這次才把它拉起來
    "cannot connect to daemon",   # 連不上 127.0.0.1:5037
    "failed to check server version",
    "adb server didn't ack",
    "adb server version",
)
# 裝置暫態：transport 還沒就緒。mDNS 會自己重連，等待重送即可，砍掉整個 server 太重。
DEVICE_STATE_MARKERS = (
    "device offline",             # 含 (no transport)／(transport offline) 兩個變體
    "device still connecting",
    "device still authorizing",
)
NOT_DELIVERED_MARKERS = DAEMON_MARKERS + DEVICE_STATE_MARKERS
SERVER_RESTART_ATTEMPTS = 3     # 最多重試幾次
SERVER_RESTART_DELAY = 1.5      # 每次重試前等裝置重新列舉（秒）
MDNS_TLS_SUFFIX = "._adb-tls-connect._tcp"

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


def _needs_server_restart(stderr: bytes) -> bool:
    """只有 daemon 層級錯誤才需要重開 server；裝置暫態交給 mDNS 自己重連。"""
    text = stderr.decode("utf-8", "replace").lower()
    return any(marker in text for marker in DAEMON_MARKERS)


def reconnect_transport() -> None:
    """裝置暫態的輕量恢復：只補 connect，不砍 server。mDNS 名稱由 adb 自動重連。"""
    serial = os.environ.get("ANDROID_SERIAL")
    if serial and ":" in serial and not serial.endswith("._tcp"):
        try:
            subprocess.run([adb_path(), "connect", serial], capture_output=True, timeout=30)
        except (subprocess.TimeoutExpired, OSError):
            pass


def _online_serials() -> list[str]:
    """devices 裡狀態真的是 `device` 的 serial。"""
    r = subprocess.run([adb_path(), "devices"], capture_output=True, timeout=20)
    online = []
    for line in r.stdout.decode("utf-8", "replace").splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            online.append(parts[0])
    return online


def _pick_serial(online: list[str]) -> str | None:
    """優先序：無線偵錯的 mDNS 名稱 → 無線 IP:PORT → USB。"""
    for pick in (lambda s: s.endswith(MDNS_TLS_SUFFIX), lambda s: ":" in s, lambda s: True):
        for serial in online:
            if pick(serial):
                return serial
    return None


def detect_target(wait_s: float = 12.0) -> str:
    """自動找出要用的 transport，使用者不需要輸入埠號。

    優先序：無線偵錯的 mDNS 名稱 → 無線 IP:PORT → USB，且**回傳的一定是 devices
    裡狀態為 `device` 的那一個**。mDNS 名稱跨埠跳動穩定（實測 11 次換埠名稱不變），
    所以它在線時優先用它；名稱不在線時退回 IP:PORT，不要回一個連不到的 serial。
    """
    deadline = time.monotonic() + wait_s
    while True:
        serial = _pick_serial(_online_serials())
        if serial:
            return serial
        if time.monotonic() >= deadline:
            break
        time.sleep(1.0)
    # 沒有任何自動物件：跟 mDNS 要端點、連上去，再確認是哪一個形式真的在線。
    # 2026-11-23 實測：server 重開後同一個無線裝置只會以 IP:PORT 註冊，名稱別名不存在；
    # 直接回名稱會讓之後每一條指令都 `device '...' not found`（重試 3 次後整個流程停掉）。
    r = subprocess.run([adb_path(), "mdns", "services"], capture_output=True, timeout=20)
    for line in r.stdout.decode("utf-8", "replace").splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[1] == "_adb-tls-connect._tcp":
            endpoint = parts[2]
            name = parts[0] + MDNS_TLS_SUFFIX
            subprocess.run([adb_path(), "connect", endpoint], capture_output=True, timeout=30)
            for _ in range(20):     # 連上不等於馬上列進 devices
                online = _online_serials()
                for candidate in (name, endpoint):
                    if candidate in online:
                        return candidate
                time.sleep(0.5)
    raise RuntimeError("找不到任何 adb 裝置：請確認手機已開啟無線偵錯，或接上 USB 並允許 USB 偵錯")


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
    """跑一條 adb 指令；沒送到手機就重試。

    daemon 層級錯誤或逾時才重開 server；裝置暫態只等待重送（見 README「執行」）。
    """
    code = None
    reason = ""
    restarts = 0
    for attempt in range(SERVER_RESTART_ATTEMPTS + 1):
        try:
            result = subprocess.run(_command(args), capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            code, reason, retry, restart = None, f"指令逾時 {timeout}s", True, True
        else:
            if not result.returncode:
                return result
            code = result.returncode
            reason = result.stderr.decode("utf-8", "replace").strip()
            retry = _not_delivered(result.stderr)
            restart = _needs_server_restart(result.stderr)
        if not retry or attempt == SERVER_RESTART_ATTEMPTS:
            break
        print(f"ADB 無回應（{reason.splitlines()[0] if reason else '未知錯誤'}），"
              f"{'重啟 adb server ' if restart else '等待裝置就緒'}後重試"
              f"（{attempt + 1}/{SERVER_RESTART_ATTEMPTS}）", flush=True)
        if restart:
            restart_server()
            restarts += 1
        else:
            reconnect_transport()
        time.sleep(SERVER_RESTART_DELAY)
    if attempt:
        reason += f"（已重試 {attempt} 次、重啟 server {restarts} 次仍失敗）"
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


if __name__ == "__main__":
    # 給啟動器用：python -m pkauto.adb 印出自動偵測到的 target。
    try:
        print(detect_target())
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)

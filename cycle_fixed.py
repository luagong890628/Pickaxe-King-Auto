"""機械化固定流程：小村莊 → 起始之地 → 等 10 秒 → 重複。

全部固定座標、固定步數，不做任何畫面偵測（只有「位移量測」用來記錄走了多少）。

流程
  1. 點傳送石 (1340,1670) → 等選單
  2. 選單往南滑 500ms（內容上移 416px）→ 點小村莊 (330,1464)
  3. 往北 3 步 → 左1 北1 右2 南1
  4. 點傳送石 → 滑 → 點起始之地 (720,1434)
  5. 往北 2 步 → 點 (721,1839) 休息
  6. 左1 北1 右2 南1
  7. 等 10 秒 → 回 1

實測座標（2026-10-20 measure_teleport.py）
  愛心 (1340,1670) 分數 1.00
  手指往上滑 500ms（內容往上 416px）：小村莊 (330,1464)、起始之地 (720,1434)

用法：
    python cycle_fixed.py --minutes 240
    python cycle_fixed.py --minutes 5 --dry-run     # 只印流程不動手機
"""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

from pkauto import adb, measure, vision

# ---- 固定座標 ----
HEART = (1340, 1670)
# 手指往上滑（內容往上）：避免之後上方新增地區時格子位置被推走
MENU_SCROLL_FROM = (720, 2600)
MENU_SCROLL_TO = (720, 2350)
MENU_SCROLL_MS = 500
TILE = {"village": (330, 1464), "start": (720, 1434)}
REST_TAP = (721, 1839)

# ---- 固定路線 ----
DRAG = (720, 2600)
DRAG_LEN = 400         # 拖曳長度＝「搖桿推多遠」＝速度旋鈕（見 SPEED_TABLE；400≈488px/秒）
STEP_PX = 300.0        # step() 沒指定 px 時的預設距離（路線都用 ROUTES 的 px）
SETTLE = 0.85          # 手指放開後的緩衝：實測放開→下一次按下 ≈ SETTLE + 0.1 秒
MEASURE = False        # 每段量位移（截圖 0.76s／段）；調 px 要數字時用 --measure
MEASURE_TEMPLATE = False   # True＝量測一律走範本比對（慢 0.8s/段，但走動中比相位相關可靠）
DIRS = {"N": (0, -1), "S": (0, 1), "L": (-1, 0), "R": (1, 0)}
NAMES = {"N": "北", "S": "南", "L": "西", "R": "東"}

# ---- 里程模型：距離 ≈ SPEED × (按住秒 − STARTUP) ----
# 同場兩次實測（2026-10-21，run_leg.py village 1 2 --template）：
#   目標 970px / 按住 2809ms → 實走 978px（348px/秒）
#   目標 250px / 按住  847ms → 實走 291px（344px/秒）
# 兩點都落在「≈346px/秒、沒有起步延遲」；更早的「250px 只走 205px」與這兩點不符
# （很可能是那條腿被擋或量測誤差），不採用。
# 若日後短段又出現系統性偏短，先重測再動 STARTUP_MS，不要憑單一筆加補償。
SPEED = 346.0
STARTUP_MS = 0

# ---- 搖桿速度表：拖曳長度 → px/秒 ----
# 遊戲機制（使用者 2026-10-21）：第一次按下的點就是搖桿原點，往外拉越遠走越快。
# 實測（test_drag.py，按住 800ms、南北成對，每點誤差 ≤2px）：
#   L=50→50px/s、100→129、150→203、200→280、250→343、300→405、350→453、400→488、450→517、500→541
# 注意：這是 input swipe（偏移量在按住期間從 0 爬到 L）的平均速度，不是滿舵瞬時速度。
# 速度只跟拖曳長度有關、跟按住時間無關（L=250 在 800/1500/2803ms 都是 341~349px/s）。
SPEED_TABLE = [(50, 50.0), (100, 129.0), (150, 203.0), (200, 280.0), (250, 343.0),
               (300, 405.0), (350, 453.0), (400, 488.0), (450, 517.0), (500, 541.0)]


def speed_of(drag_len: float) -> float:
    """拖曳長度 → px/秒（線性內插，超出表格就夾住）。"""
    if drag_len <= SPEED_TABLE[0][0]:
        return SPEED_TABLE[0][1]
    for (l0, v0), (l1, v1) in zip(SPEED_TABLE, SPEED_TABLE[1:]):
        if drag_len <= l1:
            t = (drag_len - l0) / (l1 - l0)
            return v0 + t * (v1 - v0)
    return SPEED_TABLE[-1][1]

MAX_HOLD_MS = 3000         # 單次按住上限；超過就平均拆段
# 按住下限。2026-10-21 實測（test_hold.py，固定起點 (720,2600)、拖曳 250px）：
#   500ms→173px、300→112、250→96、200→80、150→51、120→37、100→37、80→24、60→13、40→8、20→0~11
# 也就是**只要拖曳就算移動，沒有「被判成點擊」的門檻**（位移縮到量測解析度內為止）；
# 而且 500ms 會把任何 <173px 的 px 偷偷放大成 173px。下限取 110ms（≈37px）＝
# 讓 110ms 以上都照 px/速度 換算，只有 ≲40px 的段會撞到下限。
MIN_HOLD_MS = 110

# ---- 路線（照順序走；每項是 (方向, px)，("REST",) = 點固定座標休息）----
# 要調走路只改這裡；一段一個方向，距離直接用 px。
# 小村莊路線（唯一來源）。起始之地＝北 400 到帳篷 → 休息 → 沿用小村莊第 2 段以後，
# 所以改小村莊的 px 兩邊會一起變（要讓兩區不同就各自複製成獨立清單）。
VILLAGE = [
    ("N", 980.0),      # 1 往北（2026-10-22 改 980）
    ("L", 250.0),      # 2 掃描：左 1 步（250px 試）
    ("L", 200.0),      # 3 往西（2026-10-22 現場實走 100+100 合併）
    ("N", 150.0),      # 4 往北（2026-10-22 改 150）
    ("R", 250.0),      # 5 往東（2026-10-22 現場實走 248px 記錄）
    ("N", 150.0),      # 6 往北（2026-10-22 改 150）
    ("L", 200.0),      # 7 往西（2026-10-22 改 200）
    ("N", 50.0),       # 8 往北（2026-10-22 改 50）
    ("R", 150.0),      # 9 往東（2026-10-22 改 150）
    ("R", 150.0),      # 10 往東（2026-10-22 改 150）
    ("S", 50.0),       # 11 往南（2026-10-22 改 50）
    ("R", 200.0),      # 12 往東（2026-10-22 指定 200）
    ("N", 50.0),       # 13 往北（2026-10-22 改 50）
    ("R", 150.0),      # 14 往東（2026-10-22 改 150）
    ("R", 150.0),      # 15 往東（2026-10-22 改 150）
    ("S", 150.0),      # 16 往南（2026-10-22 改 150）
    ("L", 150.0),      # 17 往西（2026-10-22 指定 150）
    ("S", 200.0),      # 18 往南（2026-10-22 改 200）
    ("R", 180.0),      # 19 往東（2026-10-22 改 180）
]

ROUTES = {
    "village": VILLAGE,
    "start": [
        ("N", 425.0),      # 1 往北到帳篷（2026-10-22 改 425；對話框 ≈ (721,1839)）
        ("REST",),         # 2 點帳篷休息
    ] + VILLAGE[1:],       # 3 起＝小村莊第 2 段以後
}
LABEL = {"village": "小村莊", "start": "起始之地"}

MENU_BG = (255, 211, 143)      # 傳送選單底色（BGR），用來確認選單有沒有關掉


def menu_still_open(img):
    import numpy as np
    bg = np.array(MENU_BG)
    mid = img[560:2840, 60:1380]
    return float((np.abs(mid.astype(np.int16) - bg).max(axis=2) < 45).mean()) > 0.10


def shot():
    return vision.normalize_brightness(adb.screencap())


def hold_ms(px: float, drag_len: float = None) -> int:
    """要走 px 要按住幾毫秒（速度由拖曳長度決定）。"""
    v = speed_of(DRAG_LEN if drag_len is None else drag_len)
    return int(max(MIN_HOLD_MS, px / v * 1000 + STARTUP_MS))


def split_count(px: float, drag_len: float = None) -> int:
    """一段 px 要不要拆。每段各自要付 STARTUP_MS，所以用「扣掉起步後可用時長」換算。"""
    v = speed_of(DRAG_LEN if drag_len is None else drag_len)
    usable = max(1, MAX_HOLD_MS - STARTUP_MS)
    return max(1, math.ceil(px / v * 1000 / usable))


def step(img, d, px=None, drag_len=None):
    """一步 = 一次拖曳；距離由按住時間決定（px 預設 STEP_PX）。"""
    px = STEP_PX if px is None else float(px)
    L = DRAG_LEN if drag_len is None else drag_len
    vx, vy = DIRS[d]
    hold = hold_ms(px, L)
    a = math.atan2(vy, vx)
    adb.swipe(DRAG[0], DRAG[1],
              int(DRAG[0] + math.cos(a) * L),
              int(DRAG[1] + math.sin(a) * L), hold)
    time.sleep(SETTLE)          # adb swipe 本身已經佔掉 hold 的時間，這裡只需緩衝
    if not MEASURE:
        return 0.0, 0.0, None
    cur = shot()
    if MEASURE_TEMPLATE:                        # 只信範本（舊行為，重複性地形會鎖錯位置）
        sh = vision.shift_by_template(img, cur, threshold=0.6)
        return (-sh[0], -sh[1], cur) if sh else (0.0, 0.0, cur)
    # 預設：範本＋相位相關交叉驗證（只見 pkauto/measure.py），回傳仍用「畫面位移」的正負號
    m = measure.world_shift(img, cur)           # (角色dx, 角色dy, 分數, 來源)
    if m:
        return -m[0], -m[1], cur
    return 0.0, 0.0, cur


def teleport(area, rec):
    """機械化傳送：點愛心 → 滑選單 → 點格子。"""
    adb.tap(*HEART)
    time.sleep(2.2)
    adb.swipe(*MENU_SCROLL_FROM, *MENU_SCROLL_TO, MENU_SCROLL_MS)   # 手指往上＝內容往上（上方擴增不影響）
    time.sleep(1.3)
    adb.tap(*TILE[area])
    time.sleep(2.6)
    opened = menu_still_open(shot())
    rec({"note": f"傳送 {area}", "選單還開著": opened})
    if opened:                      # 點歪了：再點一次同一個固定位置
        adb.tap(*TILE[area])
        time.sleep(3.0)
        rec({"note": f"傳送 {area} 重試", "選單還開著": menu_still_open(shot())})


REST_WAIT = 3.2          # 點擊休息後等動畫（原本 4.5 秒太長，實測 3 秒就結束）


def rest(rec, img, label):
    adb.tap(*REST_TAP)
    time.sleep(REST_WAIT)
    rec({"note": f"{label} 休息（點固定座標）"})
    return shot() if MEASURE else img      # 不量位移就不截圖（省 0.76s）


def leg(img, d, px, rec, label, drag_len=None):
    """一個方向走 px（按住時間＝px/速度；超過 MAX_HOLD_MS 就平均拆段）。"""
    if px <= 0:
        return img
    L = DRAG_LEN if drag_len is None else drag_len
    n = split_count(px, L)
    seg = px / n
    tx = ty = 0.0
    for _ in range(n):
        dx, dy, img = step(img, d, seg, L)
        tx += dx
        ty += dy
    note = (f"{label} {NAMES[d]} {px:.0f}px"
            + (f"（拖 {L:.0f}px／拆 {n} 段）" if n > 1 else f"（拖 {L:.0f}px）"))
    if MEASURE:
        rec({"note": note, "shift": [round(tx), round(ty)],
             "目標": [round(px * DIRS[d][0]), round(px * DIRS[d][1])]})
    else:
        rec({"note": note})
    return img


def main():
    global MEASURE
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=240)
    ap.add_argument("--wait", type=float, default=30)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--measure", action="store_true",
                    help="每段量實際位移（每段多花約 0.8 秒截圖；調 px 時用）")
    args = ap.parse_args()
    MEASURE = args.measure

    if args.dry_run:
        print(f"\n搖桿：拖 {DRAG_LEN:.0f}px → {speed_of(DRAG_LEN):.0f}px/秒"
              f"（拖越遠越快；按住毫秒 = px ÷ 速度）")
        for area in ("village", "start"):
            print(f"\n[{LABEL[area]}] 傳送落點 {TILE[area]}")
            for i, act in enumerate(ROUTES[area], 1):
                if act[0] == "REST":
                    print(f"  {i}. 休息（點 {REST_TAP}，等 {REST_WAIT}s）")
                    continue
                d, px = act
                n = split_count(px)
                holds = " + ".join(f"{hold_ms(px / n)}" for _ in range(n))
                extra = f"（拆 {n} 段）" if n > 1 else ""
                print(f"  {i}. {NAMES[d]} {px:.0f}px → 按住 {holds}ms{extra}")
        print(f"\n等 {args.wait:.0f} 秒後下一輪　固定座標：愛心{HEART} 格子{TILE} 休息{REST_TAP}")
        return

    run = Path("captures") / time.strftime("fixed_%Y%m%d_%H%M%S")
    run.mkdir(parents=True, exist_ok=True)
    log = (run / "log.jsonl").open("w", encoding="utf-8")

    def rec(o):
        o["t"] = time.strftime("%H:%M:%S")
        log.write(json.dumps(o, ensure_ascii=False) + "\n")
        log.flush()
        print(json.dumps(o, ensure_ascii=False), flush=True)

    rec({"note": "開始", "wait": args.wait, "分鐘": args.minutes})
    t0 = time.time()
    deadline = t0 + args.minutes * 60
    cycles = 0

    while time.time() < deadline:
        cycles += 1
        rec({"note": f"=== 第 {cycles} 輪 ==="})

        for area in ("village", "start"):
            teleport(area, rec)
            img = shot() if MEASURE else None
            for act in ROUTES[area]:
                if act[0] == "REST":
                    img = rest(rec, img, LABEL[area])
                else:
                    img = leg(img, act[0], act[1], rec, LABEL[area])

        rec({"note": "本輪結束", "已跑分鐘": round((time.time() - t0) / 60, 1)})
        end = min(time.time() + args.wait, deadline)
        while time.time() < end:
            time.sleep(min(2, end - time.time()))

    rec({"note": "收工", "cycles": cycles, "小時": round((time.time() - t0) / 3600, 2)})
    log.close()


if __name__ == "__main__":
    main()

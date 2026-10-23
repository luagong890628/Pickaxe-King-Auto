"""機械化固定流程：小村莊 → 起始之地（含休息）→ 直接重複。

實驗版：進場快、林內慢，不加移動後停頓；保留傳送與休息的必要等待。
全部固定座標、固定路線 px，預設不截圖、不偵測、不量測。

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
# 手指向下快速拖曳，將目的地列表歸頂；座標已由使用者確認
MENU_SCROLL_FROM = (720, 850)
MENU_SCROLL_TO = (720, 2250)
MENU_SCROLL_MS = 300
TILE = {"farm": (350, 800), "village": (350, 1810), "start": (720, 1810)}
REST_TAP = (721, 1839)                                  # 帳篷休息對話框中心

# ---- 固定路線 ----
DRAG = (720, 2600)
DRAG_LEN = 250         # 拖曳長度＝「搖桿推多遠」＝速度旋鈕（250≈343px/秒）
ENTRY_DRAG = 1200      # 實驗：1200 未標定，暫沿用速度表 500 的上限換算
ENTRY_WEST_DRAG = 250  # 進場第二個移動段往西時放慢，路線距離仍是 250px
FOREST_DRAG = 85       # 實驗：林內速度；不加等待補足週期
FARM_DRAG = 300        # 自由農場A 林內拖曳（第2步起；進場第1步仍用 ENTRY_DRAG）
ENTRY_LEGS = {"village": (1, 2), "start": (1,), "farm": (1,)}
# 為什麼不是 400（488px/秒）：2026-10-22 交替實測同一 400px 腿，
#   拖 400 → 395/387/387/392（平均 390、離散 3.9）
#   拖 250 → 392/397/392/395/395（平均 394、離散 2.0）
# 慢一點＝同樣 20ms 抖動只差 7px（vs 10px），精度更好；代價是路線總時長約 +40%。
STEP_PX = 300.0        # step() 沒指定 px 時的預設距離（路線都用 ROUTES 的 px）
SETTLE = 0.0           # 不加移動後等待；按目前速度實際完成，不補足週期
MEASURE = False        # 每段量位移（截圖 0.76s／段）；調 px 要數字時用 --measure
MEASURE_TEMPLATE = False   # True＝量測一律走範本比對（慢 0.8s/段，但走動中比相位相關可靠）
DIRS = {"N": (0, -1), "S": (0, 1), "L": (-1, 0), "R": (1, 0)}
NAMES = {"N": "北", "S": "南", "L": "西", "R": "東"}

# ---- 補時：農場走到定位（1、2）與固定 3、4 段後，再多砍固定組數的來回 ----
# 輪次基準＝小村莊第 2 步（第一刀）。2026-10-23 實測（無補時）：
#   輪首 → 下一輪輪首 83.1 秒；每組 3→4（東 700、西 700，拖 300）約 3.61 秒。
#   目標：下一輪小村莊第 2 步落在基準後 115～120 秒。
#   實跑：10 組 119～120 秒（5 輪）、9 組 115～116 秒（3 輪）；8 組 ≈ 112 秒。
# 純開環固定組數：不看時間、不判斷樹重生；要調週期就改 FILL_PAIRS。
FILL_LEGS = {"farm": (3, 4)}   # 補時重複的段（3→4→3→4…）
FILL_PAIRS = 8                 # 再多砍幾組；1 組 = 3、4 各一次

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


# 按住下限。2026-10-21 實測（test_hold.py，固定起點 (720,2600)、拖曳 250px）：
#   500ms→173px、300→112、250→96、200→80、150→51、120→37、100→37、80→24、60→13、40→8、20→0~11
# 也就是**只要拖曳就算移動，沒有「被判成點擊」的門檻**（位移縮到量測解析度內為止）；
# 而且 500ms 會把任何 <173px 的 px 偷偷放大成 173px。下限取 110ms（≈37px）＝
# 讓 110ms 以上都照 px/速度 換算，只有 ≲40px 的段會撞到下限。
MIN_HOLD_MS = 110

# ---- 路線（照順序走；每項是 (方向, px)，("REST",) = 點固定座標休息）----
# 要調走路只改這裡；一段一個方向，距離直接用 px。
# 兩區使用獨立清單：小村莊與起始之地可分開調整，不連動距離。
VILLAGE = [
    ("N", 850.0),      # 1 往北（使用者微調 850）
    ("L", 150.0),      # 2 往西（使用者指定）
    ("L", 300.0),      # 3 往西（使用者指定）
    ("N", 125.0),      # 4 往北（使用者指定 125）
    ("R", 250.0),      # 5 往東（2026-10-22 現場實走 248px 記錄）
    ("N", 125.0),      # 6 往北（使用者指定 125）
    ("L", 250.0),      # 7 往西（使用者指定 250）
    ("N", 100.0),      # 8 往北（使用者指定 100）
    ("R", 350.0),      # 9 往東（使用者指定 350）
    ("S", 125.0),      # 10 往南（使用者指定 125）
    ("R", 200.0),      # 11 往東
    ("N", 125.0),      # 12 往北（使用者指定 125）
    ("R", 350.0),      # 13 往東（使用者指定350）
    ("S", 125.0),      # 14 往南（使用者指定125）
    ("L", 250.0),      # 15 往西（使用者指定250）
    ("S", 250.0),      # 16 往南（使用者指定250）
    ("R", 180.0),      # 17 往東
    ("N", 100.0),      # 18 往北（使用者更正）
]

ROUTES = {
    "village": VILLAGE,
    "start": [
        ("N", 425.0),      # 1 往北到帳篷（2026-10-22 改 425；對話框 ≈ (721,1839)）
        ("REST",),         # 2 點帳篷休息
        ("L", 450.0),      # 第2個移動：合併西走，後續對齊小村莊第4段起
        ("N", 125.0),
        ("R", 250.0),
        ("N", 125.0),
        ("L", 250.0),
        ("N", 100.0),
        ("R", 350.0),
        ("S", 125.0),
        ("R", 200.0),
        ("N", 125.0),
        ("R", 350.0),
        ("S", 125.0),
        ("L", 250.0),
        ("S", 250.0),
        ("R", 180.0),
        ("N", 100.0),
    ],  # 兩區獨立調整，不連動小村莊
    "farm": [("N", 600.0), ("L", 350.0), ("R", 700.0), ("L", 700.0)],
    # 自由農場A：北進場 600 → 西 350 → 東 700 → 西 700（3、4 可來回重複）
}
LABEL = {"village": "小村莊", "start": "起始之地", "farm": "自由農場A"}


def route_drag(area, leg_number):
    if area == "farm" and leg_number not in ENTRY_LEGS["farm"]:
        return FARM_DRAG
    if leg_number in ENTRY_LEGS[area]:
        return ENTRY_WEST_DRAG if ROUTES[area][leg_number - 1][0] == "L" else ENTRY_DRAG
    return FOREST_DRAG

# 按住時間校正（2026-10-22 多場實測，固定起點、同方向來回各 5 次）
#   - 同一場內大致成比例；但**同一條腿跨場次差 3.5%**（800px：771 vs 835）＝每場速度不同，
#     這是「每次走出來不太一樣」的主因，靜態係數消不掉（隨機抖動只有 0~9px/段）。
#   - 靜態平均：名目 400px 實走 394（-1.5%）、800px→780（-2.5%）、150~250px→+1~2%。
#     **刻意不加靜態補正**：平均偏差只有 1.5%，補了在快場次反而多走 3%（實測 400 指令→416）。
#   - 已試過「每場探針校正」：南向量測被牛動畫干擾（1800ms 量成 -122px）→ 不可行，不要重做。



def shot():
    return vision.normalize_brightness(adb.screencap())


def hold_ms(px: float, drag_len: float = None) -> int:
    """要走 px 要按住幾毫秒（速度由拖曳長度決定）。"""
    v = speed_of(DRAG_LEN if drag_len is None else drag_len)
    return int(max(MIN_HOLD_MS, px / v * 1000 + STARTUP_MS))



def step(img, d, px=None, drag_len=None, settle=None):
    """一步 = 一次拖曳；距離由按住時間決定（px 預設 STEP_PX）。"""
    px = STEP_PX if px is None else float(px)
    L = DRAG_LEN if drag_len is None else drag_len
    vx, vy = DIRS[d]
    hold = hold_ms(px, L)
    a = math.atan2(vy, vx)
    adb.swipe(DRAG[0], DRAG[1],
              int(DRAG[0] + math.cos(a) * L),
              int(DRAG[1] + math.sin(a) * L), hold)
    pause = SETTLE if settle is None else settle
    if pause:
        time.sleep(pause)
    if not MEASURE:
        return 0.0, 0.0, None, None
    cur = shot()
    if MEASURE_TEMPLATE:                        # 只信範本（舊行為，重複性地形會鎖錯位置）
        sh = vision.shift_by_template(img, cur, threshold=0.6)
        return (sh[0], sh[1], cur, (sh[2], "template")) if sh else (0.0, 0.0, cur, None)
    # 預設：範本＋相位相關交叉驗證（只見 pkauto/measure.py），回傳仍用「畫面位移」的正負號
    m = measure.world_shift(img, cur)           # (角色dx, 角色dy, 分數, 來源)
    if m:
        return -m[0], -m[1], cur, (m[2], m[3])
    return 0.0, 0.0, cur, None


def teleport(area, rec):
    """點愛心 → 手指向下拖1400px/300ms歸頂 → 等0.5秒 → 點固定格子。"""
    adb.tap(*HEART)
    time.sleep(0.5)
    adb.swipe(*MENU_SCROLL_FROM, *MENU_SCROLL_TO, MENU_SCROLL_MS)
    time.sleep(0.5)
    adb.tap(*TILE[area])
    time.sleep(0.5)
    rec({"note": f"傳送 {area}"})


REST_WAIT = 2.0          # 點擊休息後等動畫（2026-10-23 由 3.2 改 2 秒，尚未實跑驗證）


def rest(rec, img, label):
    adb.tap(*REST_TAP)
    time.sleep(REST_WAIT)
    rec({"note": f"{label} 休息（點固定座標）"})
    return shot() if MEASURE else img      # 不量位移就不截圖（省 0.76s）


def leg(img, d, px, rec, label, drag_len=None, settle=None):
    """一個路線動作只送一次拖曳，不限制時長、不自動拆段。"""
    if px <= 0:
        return img
    L = DRAG_LEN if drag_len is None else drag_len
    tx, ty, img, measured = step(img, d, px, L, settle)
    note = f"{label} {NAMES[d]} {px:.0f}px（拖 {L:.0f}px）"
    if MEASURE:
        result = {"note": note, "shift": [round(tx), round(ty)],
                  "目標": [round(px * DIRS[d][0]), round(px * DIRS[d][1])]}
        if measured is not None:
            result["score"], result["source"] = measured
        rec(result)
    else:
        rec({"note": note})
    return img


def fill_cycle(area, rec, img, pairs=None):
    """固定組數來回（3→4），純開環：不看時間、不判斷樹重生。"""
    legs = FILL_LEGS[area]
    for _ in range(FILL_PAIRS if pairs is None else pairs):
        for n in legs:
            d, px = ROUTES[area][n - 1]
            img = leg(img, d, px, rec, f"{LABEL[area]}補時{n}",
                      drag_len=route_drag(area, n), settle=0)
    return img


def main():
    global MEASURE
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=None,
                    help="執行分鐘數（預設無限循環，按 Ctrl+C 停止）")
    ap.add_argument("--wait", type=float, default=0,
                    help="每輪之間額外等幾秒（預設 0：靠林內慢走控制週期）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--measure", action="store_true",
                    help="每段量實際位移（每段多花約 0.8 秒截圖；調 px 時用）")
    args = ap.parse_args()
    MEASURE = args.measure

    if args.dry_run:
        print(f"\n進場北走：拖 {ENTRY_DRAG}px；西走：拖 {ENTRY_WEST_DRAG}px；"
              f"林內：拖 {FOREST_DRAG}px → {speed_of(FOREST_DRAG):.1f}px/秒")
        for area in ("village", "start", "farm"):
            print(f"\n[{LABEL[area]}] 傳送落點 {TILE[area]}")
            for i, act in enumerate(ROUTES[area], 1):
                if act[0] == "REST":
                    print(f"  {i}. 休息（點 {REST_TAP}，等 {REST_WAIT}s）")
                    continue
                d, px = act
                drag = route_drag(area, i)
                print(f"  {i}. {NAMES[d]} {px:.0f}px → 拖 {drag}px／按住 {hold_ms(px, drag)}ms")
            if area in FILL_LEGS:
                print(f"  補時：再多 {FILL_PAIRS} 組第 "
                      f"{'、'.join(str(n) for n in FILL_LEGS[area])} 段來回（固定組數，不看時間）")
        print(f"\n每輪結束{'額外等 ' + str(int(args.wait)) + ' 秒' if args.wait else '立刻下一輪（不加移動後停頓）'}"
              f"　固定座標：愛心{HEART} 格子{TILE} 休息{REST_TAP}")
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
    deadline = float("inf") if args.minutes is None else t0 + args.minutes * 60
    cycles = 0

    try:
        while time.time() < deadline:
            cycles += 1
            rec({"note": f"=== 第 {cycles} 輪 ==="})

            for area in ("village", "start", "farm"):
                teleport(area, rec)
                img = shot() if MEASURE else None
                for i, act in enumerate(ROUTES[area], 1):
                    if act[0] == "REST":
                        img = rest(rec, img, LABEL[area])
                    else:
                        img = leg(img, act[0], act[1], rec, LABEL[area],
                                  drag_len=route_drag(area, i),
                                  settle=0)
                if area in FILL_LEGS:
                    img = fill_cycle(area, rec, img)

            rec({"note": "本輪結束", "已跑分鐘": round((time.time() - t0) / 60, 1)})
            end = min(time.time() + args.wait, deadline)
            while time.time() < end:
                time.sleep(min(2, end - time.time()))

    except KeyboardInterrupt:
        rec({"note": "使用者停止（Ctrl+C）"})
    finally:
        rec({"note": "收工", "cycles": cycles, "小時": round((time.time() - t0) / 3600, 2)})
        log.close()


if __name__ == "__main__":
    main()

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

# 傳送石冷卻（使用者 2026-10-26 確認 12 秒）：冷卻中再點不會傳送，選單會留在畫面上，
# 之後的手勢就打在選單上而不是搖桿。實測連續傳送間隔 6 秒時，後續滑動位移量到 0px。
# 目前每區走 24 秒以上，正常不會撞到；這個保護是為了日後再調快或縮短補時時不會靜默失敗。
TELEPORT_COOLDOWN = 12.0
_last_teleport = 0.0

# ---- 固定路線 ----
DRAG = (720, 2600)
# 拖曳終點必須留在 1440×3120 螢幕內，所以各方向的拖曳上限不同（起點 x=720、y=2600）：
#   北 2600、南 520、西 720、東 720 → **橫向最快 794px/秒**，比縱向 903 慢約 12%。
#   要橫向再快只能把起點往反方向移（往西從 x=1140 起手），但已貼右側 UI 欄，未驗證。
#   滑動一律從畫面中央起手，終點落在邊緣不會觸發 Android 的返回手勢。
DRAG_LEN = 250         # 拖曳長度＝「搖桿推多遠」＝速度旋鈕（250≈466px/秒）
# 林外（進場段）用最快：拖 1800 已達 903px/秒，再拉到 2200 平台只多 1.8%（2026-10-26 實測）
ENTRY_DRAG = 1800
ENTRY_WEST_DRAG = 250  # 進場第二個移動段往西時放慢（150px 短腿求精度，不用滿舵）
FOREST_DRAG = 200      # 林內（372px/秒）。**全域速度先不動**（2026-10-26 使用者指示）。
# 使用者：遊戲的跑速和砍速都還會再升、有些路線之後可能整段不需要走（可以省），
# 所以現在不要把全域速度調死 → 漏砍一律用「停頓 SETTLE」和「單段覆寫」解決，
# 全域速度留在 200 這個位置，等路線定稿、速度穩定後再重標一次。
# 演進記錄：85（155px/秒，太慢）→ 250（466，明顯漏砍）→ 200（372，位置全對）
#           → 160（297）試過一次，既然停頓就能解決，回到 200 不犧牲移動速度。
#
# **停頓（SETTLE）是修漏砍的主力，不要用降速去補**（2026-10-26 使用者實測）：
#   每段停 2 秒 → 「樹就都砍掉了」。漏的樹在**段終點附近**（走到定點時還差一兩刀，
#   下一段一拉走就永遠不會再砍），停下來的當下人就留在同一棵樹的攻擊範圍內。
#   ⚠️ 我先前一度推論「停頓無效、漏的在段中间」，那是把使用者「會漏一些」誤讀成
#      「停 2 秒後還漏」→ 已更正。以後遇到這類回報要先問清楚是哪一趟。
#
# **px 和拖曳是兩個獨立旋鈕，不要拿一個補另一個**（2026-10-26 使用者提問）：
#   同一條腿的揮鎬次數 ≈ 腿長 ÷ 速度 ÷ 揮鎬週期（揮鎬是自動打最近目標，
#   樹密時會一直換目標，每棵都砍一半 → 所以每棵樹要的是「時間」，不是「距離」）。
#   - 把 px 加長 → 停留時間變長、確實多砍幾刀，但**終點位移**，後續每段都繼承偏移，
#     開環路線沒有視覺修正，偏移收不回來 → px 只能改幾何，不能用來修速度。
#   - 把拖曳變小 → 停留時間變長、終點不變，但會拖長移動本身（輔助槓桿）。
#   - 加 SETTLE → 停留時間變長、終點不變、移動速度不變（**首選槓桿**）。
#   若加了停頓還是有某一段漏砍，別動全域值，直接在該段寫第三個元素覆寫（見 route_act）：
#       ("L", 300.0, 140)   ← 這段拖 140，其餘仍用 FOREST_DRAG
FARM_DRAG = 300        # 自由農場A 林內拖曳（第2步起；進場第1步仍用 ENTRY_DRAG）
ENTRY_LEGS = {"village": (1, 2), "start": (1,), "farm": (1,)}
# 為什麼不是 400（488px/秒）：2026-10-22 交替實測同一 400px 腿，
#   拖 400 → 395/387/387/392（平均 390、離散 3.9）
#   拖 250 → 392/397/392/395/395（平均 394、離散 2.0）
# 慢一點＝同樣 20ms 抖動只差 7px（vs 10px），精度更好；代價是路線總時長約 +40%。
STEP_PX = 300.0        # step() 沒指定 px 時的預設距離（路線都用 ROUTES 的 px）
# ---- 到點停頓（dwell）：走完一段後原地不動，讓揮鎬把附近的樹打完 ----
# 2026-10-26 使用者實測：**每段停 2 秒，樹就全部砍完了**（原本不停頓會「漏一些」）。
# 機制：揮鎬自動打最近目標，走到定點時常有一棵樹還差一兩刀，下一段一拉走就永遠不會再砍
#       → 停在原地＝留在同一棵樹的攻擊範圍內，把剩下的刀數補完。
# **這是修「漏砍」最划算的槓桿**，因為：
#   1. 終點完全不變（不像加 px 會位移、也不像降速會拖長每段移動）。
#   2. 停下來的時間不是純浪費：輪次本來就必須 >100 秒（樹重生時間），
#      停頓＝原地砍樹，比「補時來回」那種純移動更能把秒數用在刀口上。
# 代價：每段 +秒數。實測小村莊全部 18 段都停 2 秒要多 37.8 秒（17.9s → 55.7s），
#       所以**不要全部停**：使用者逐段看過後只指定需要的段（見 SETTLE_LEGS）。
SETTLE = 0.0           # 沒被 SETTLE_LEGS 指到的段，預設不停（0＝舊行為）
# 哪幾段走完要停多久（秒）。2026-10-26 使用者看完不停頓那一趟後指定的：
#   3 走完→4 之前、5 走完→6 之前、7 走完→8 之前、12 走完（北要走多一點+停頓）、15 走完→16 之前
# 秒數：先試 2 秒（確實能把樹砍完），使用者回「2 秒太多，0.5 就夠了」→ 0.5。
#       停頓只需要讓揮鎬補完最後一兩刀，不是停越久越好；0.5 秒≈一到兩次揮鎬。
# 註：使用者原話是「11 北要走多一點」，但第 11 段是東 200、第 12 段才是北 125
#     → 依方向判定為第 12 段。若其實是第 11 段，把 12 改成 11 即可。
SETTLE_LEGS = {
    "village": {3: 0.5, 5: 0.5, 7: 0.5, 12: 0.5, 15: 0.5},
    "start": {},   # 起始之地還沒逐段看過，先全不停
    "farm": {},    # 自由農場A 同上
}
MEASURE = False        # 每段量位移（截圖 0.76s／段）；調 px 要數字時用 --measure
VERBOSE = False        # False＝console 只印大項目（輪次、傳送、休息）；log.jsonl 一律記全部
MEASURE_TEMPLATE = False   # True＝量測一律走範本比對（慢 0.8s/段，但走動中比相位相關可靠）
DIRS = {"N": (0, -1), "S": (0, 1), "L": (-1, 0), "R": (1, 0)}
NAMES = {"N": "北", "S": "南", "L": "西", "R": "東"}

# ---- 補時：農場走到定位（1、2）與固定 3、4 段後，再多砍固定組數的來回 ----
# 輪次基準＝小村莊第 2 步（第一刀）。
# 2026-10-23 實測（舊速度，無補時）：輪首 → 下一輪輪首 83.1 秒；每組 3→4 約 3.61 秒。
# 2026-10-26 重標速度後（新表）：**8 組只有 84 秒**（實測），低於樹重生的 100 秒 → 會漏砍。
#   每組 3→4（東 700、西 700，拖 300／552px/秒）現在只要 2.54 秒。
#   要回到 115～120 秒約需 19 組（84 + 11 組 × 2.8 ≈ 115 秒）。
#   使用者 2026-10-26 指示「補時先不動」→ 維持 8 組，先觀察實際漏砍情況再決定。
#
# ⚠️ 但 `SETTLE=2.0` 之後，上面這套「靠補時把輪次撐到 100 秒」的算法**已經作廢**：
#   停頓本身就把輪次撐起來了。以拖 200 + 停 2 秒估算（移動段 55 段）：
#     小村莊 12.2s 移動 + 18×2s 停頓 = 51.5s
#     起始之地 11.8s + 17×2s          = 50.8s
#     自由農場A 24.1s + 20×2s（含 8 組補時）= 67.7s   → 一輪約 176s
#   而**補時全關（FILL_PAIRS=0）一輪仍有 121 秒**，已經 >100 秒 → 補時可能整批不需要。
#   停頓＝原地砍樹，補時來回＝純移動，同樣的秒數停頓更有價值 → 之後若要瘦身優先砍補時。
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
# **2026-10-26 重標**（遊戲內跑速變快，舊表整組失效；舊值見 git 歷史 f92d4ec）。
# 量法：test_drag.py --hold 1200（固定按住、只改拖曳長度）＋ run_leg.py 交叉驗證，
#       每次傳送回小村莊、往北量、往南回；分數 <0.9 或實走≈0（被地形擋）一律不採用。
#   L=85→155px/s（4 筆 152~156）、150→278、250→466（4 筆 463~472）、300→552、
#   400→650、500→721（4 筆 719~729）、700→791、1200→866（5 筆 856~874）、
#   1800→903（3 筆 901~905）
# 平台區（2026-10-26 補測，各 2 筆）：2000→917（919/916）、2100→910（920/900）、
#   2200→920（924/915）、2400→915（910/920）→ 2000 以後都在 910~924，差異在誤差內，
#   天花板 ≈919px/秒。**拖 1800 已達天花板的 98%**，再拉長只是讓手勢橫跨整個螢幕，
#   所以林外取 ENTRY_DRAG=1800；表上 2200/2400 同值 919 是平台，不是量到更高。
# 舊表在 L=500 就夾住（541），但實測拖 1200 仍有 866px/s → 搖桿沒有在 500 飽和，
# 進場段（ENTRY_DRAG）一直是表外值，這次一併納入標定。
# 注意：這是 input swipe（偏移量在按住期間從 0 爬到 L）的平均速度，不是滿舵瞬時速度。
# 速度只跟拖曳長度有關、跟按住時間無關（L=250 在 800/1500/2803ms 都是 341~349px/s）。
# L<85 未標定（沒有任何路線用到），一律夾在 155px/s。
SPEED_TABLE = [(85, 155.0), (150, 278.0), (250, 466.0), (300, 552.0),
               (400, 650.0), (500, 721.0), (700, 791.0), (1200, 866.0),
               (1800, 903.0), (2200, 919.0), (2400, 919.0)]

# ---- 全域速度倍率（給「日後又調速度」用的備援旋鈕，目前 1.0）----
# 上表已經是 2026-10-26 的實測值，正常情況不用動這裡。
# 曲線形狀被改過，所以倍率不等於「整張表等比」：只能在確定形狀沒變時用。
#   實際速度 = 表上速度 × SPEED_SCALE
# 量法（run_leg.py 每段會直接印建議值）：走一段已知 px，實走 ÷ 目標 = k ÷ 目前倍率。
SPEED_SCALE = 1.0


def _table_speed(drag_len: float) -> float:
    """速度表上的值（未套全域倍率）。"""
    if drag_len <= SPEED_TABLE[0][0]:
        return SPEED_TABLE[0][1]
    for (l0, v0), (l1, v1) in zip(SPEED_TABLE, SPEED_TABLE[1:]):
        if drag_len <= l1:
            t = (drag_len - l0) / (l1 - l0)
            return v0 + t * (v1 - v0)
    return SPEED_TABLE[-1][1]


def speed_of(drag_len: float) -> float:
    """拖曳長度 → 目前實際 px/秒（表上速度 × SPEED_SCALE）。"""
    return _table_speed(drag_len) * SPEED_SCALE


# 按住下限。2026-10-21 實測（test_hold.py，固定起點 (720,2600)、拖曳 250px）：
#   500ms→173px、300→112、250→96、200→80、150→51、120→37、100→37、80→24、60→13、40→8、20→0~11
# 也就是**只要拖曳就算移動，沒有「被判成點擊」的門檻**（位移縮到量測解析度內為止）；
# 而且 500ms 會把任何 <173px 的 px 偷偷放大成 173px。下限取 110ms（≈37px）＝
# 讓 110ms 以上都照 px/速度 換算，只有 ≲40px 的段會撞到下限。
MIN_HOLD_MS = 110

# ---- 路線（照順序走；每項是 (方向, px)，("REST",) = 點固定座標休息）----
# 要調走路只改這裡；一段一個方向，距離直接用 px。
# 兩區使用獨立清單：小村莊與起始之地可分開調整，不連動距離。
# 某一小段漏砍樹時，可在該段加第三個元素覆寫拖曳：(方向, px, 拖曳)，只影響那一段。
VILLAGE = [
    ("N", 1000.0),     # 1 往北進林（2026-10-26 由 850 改 1000，使用者現場確認）
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
    ("N", 150.0),      # 12 往北（2026-10-26 由 125 改 150：使用者「要走多一點」）
    ("R", 350.0),      # 13 往東（使用者指定350）
    ("S", 125.0),      # 14 往南（使用者指定125）
    ("L", 250.0),      # 15 往西（使用者指定250）
    ("S", 250.0),      # 16 往南（使用者指定250）
    ("R", 200.0),      # 17 往東（2026-10-26 由 180 改 200：使用者「17 也要多一點」）
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


def route_act(act):
    """路線項目正規化 → (方向, px, 拖曳覆寫或 None)。

    路線可以寫成兩種形式：
        ("N", 1000.0)            用該區預設拖曳（route_drag 的公式決定）
        ("N", 1000.0, 150)       這一段強制用拖 150（其餘不動）
    覆寫的用途：**只有某一小段漏砍時，只放慢那一段**，不要為了兩棵樹把整區變慢。
    """
    if act[0] == "REST":
        return "REST", 0.0, None
    if len(act) >= 3:
        return act[0], float(act[1]), float(act[2])
    return act[0], float(act[1]), None


def route_drag(area, leg_number):
    """這一段用多長的拖曳。優先序：單段覆寫 > 該區規則。"""
    d, _, override = route_act(ROUTES[area][leg_number - 1])
    if override is not None:
        return override
    if area == "farm" and leg_number not in ENTRY_LEGS["farm"]:
        return FARM_DRAG
    if leg_number in ENTRY_LEGS[area]:
        return ENTRY_WEST_DRAG if d == "L" else ENTRY_DRAG
    return FOREST_DRAG


def route_settle(area, leg_number):
    """這一段走完原地停多久（秒）。0＝不停。

    停頓＝留在同一棵樹的攻擊範圍內把最後一兩刀補完，是修漏砍最划算的槓桿
    （不動速度、不位移終點）。只有 SETTLE_LEGS 列出的段才停，其餘用 SETTLE。
    """
    return SETTLE_LEGS.get(area, {}).get(leg_number, SETTLE)

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
    """點愛心 → 手指向下拖1400px/300ms歸頂 → 等0.5秒 → 點固定格子（含 12 秒冷卻保護）。"""
    global _last_teleport
    if _last_teleport:
        gap = time.time() - _last_teleport
        if gap < TELEPORT_COOLDOWN:
            wait = TELEPORT_COOLDOWN - gap
            rec({"note": f"等傳送石冷卻 {wait:.1f}s"})
            time.sleep(wait)
    adb.tap(*HEART)
    _last_teleport = time.time()
    time.sleep(0.5)
    adb.swipe(*MENU_SCROLL_FROM, *MENU_SCROLL_TO, MENU_SCROLL_MS)
    time.sleep(0.5)
    adb.tap(*TILE[area])
    time.sleep(0.5)
    rec({"note": f"傳送 {area}", "big": True,
         "show": f"[{LABEL[area]}] 傳送完成"})


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
            d, px, _ = route_act(ROUTES[area][n - 1])
            img = leg(img, d, px, rec, f"{LABEL[area]}補時{n}",
                      drag_len=route_drag(area, n), settle=route_settle(area, n))
    return img


def main():
    global MEASURE, VERBOSE, SPEED_SCALE
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=None,
                    help="執行分鐘數（預設無限循環，按 Ctrl+C 停止）")
    ap.add_argument("--wait", type=float, default=0,
                    help="每輪之間額外等幾秒（預設 0：靠林內慢走控制週期）")
    ap.add_argument("--verbose", action="store_true",
                    help="console 也印每一段（預設只印輪次、傳送、休息與錯誤）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--measure", action="store_true",
                    help="每段量實際位移（每段多花約 0.8 秒截圖；調 px 時用）")
    ap.add_argument("--speed-scale", type=float, default=None,
                    help="全域速度倍率（遊戲改跑速後用；見 SPEED_SCALE 註解）")
    args = ap.parse_args()
    MEASURE = args.measure
    VERBOSE = args.verbose
    if args.speed_scale is not None:
        if args.speed_scale <= 0:
            ap.error("--speed-scale 必須大於 0")
        SPEED_SCALE = args.speed_scale

    if args.dry_run:
        print(f"速度倍率 {SPEED_SCALE:g}（速度表 2026-10-26 重標；1.0 = 表值即實際值）")
        print(f"進場北走：拖 {ENTRY_DRAG}px；西走：拖 {ENTRY_WEST_DRAG}px；"
              f"林內：拖 {FOREST_DRAG}px → {speed_of(FOREST_DRAG):.1f}px/秒")
        for area in ("village", "start", "farm"):
            print(f"\n[{LABEL[area]}] 傳送落點 {TILE[area]}")
            for i, act in enumerate(ROUTES[area], 1):
                if act[0] == "REST":
                    print(f"  {i}. 休息（點 {REST_TAP}，等 {REST_WAIT}s）")
                    continue
                d, px, override = route_act(act)
                drag = route_drag(area, i)
                tag = f"（單段覆寫 {override:g}）" if override is not None else ""
                s_ = route_settle(area, i)
                dwell = f"／停 {s_:g}s" if s_ else ""
                print(f"  {i}. {NAMES[d]} {px:.0f}px → 拖 {drag}px／按住 {hold_ms(px, drag)}ms{tag}{dwell}")
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
        if VERBOSE or o.get("big"):
            print(o.get("show") or o["note"], flush=True)

    rec({"note": "開始", "big": True, "wait": args.wait, "分鐘": args.minutes,
         "show": "開始（" + ("無限" if args.minutes is None else f"{args.minutes:g} 分鐘") + "）"})
    t0 = time.time()
    deadline = float("inf") if args.minutes is None else t0 + args.minutes * 60
    cycles = 0

    try:
        while time.time() < deadline:
            cycles += 1
            rec({"note": f"=== 第 {cycles} 輪 ({time.strftime('%H:%M')}) ===", "big": True})

            for area in ("village", "start", "farm"):
                teleport(area, rec)
                rec({"note": f"[{LABEL[area]}] 開始採集", "big": True})
                img = shot() if MEASURE else None
                for i, act in enumerate(ROUTES[area], 1):
                    if act[0] == "REST":
                        img = rest(rec, img, LABEL[area])
                    else:
                        d, px, _ = route_act(act)
                        img = leg(img, d, px, rec, LABEL[area],
                                  drag_len=route_drag(area, i),
                                  settle=route_settle(area, i))
                if area in FILL_LEGS:
                    img = fill_cycle(area, rec, img)

            rec({"note": "本輪結束", "已跑分鐘": round((time.time() - t0) / 60, 1)})
            end = min(time.time() + args.wait, deadline)
            while time.time() < end:
                time.sleep(min(2, end - time.time()))

    except KeyboardInterrupt:
        rec({"note": "使用者停止（Ctrl+C）", "big": True, "show": "使用者停止（Ctrl+C）"})
    finally:
        rec({"note": "收工", "big": True, "show": f"收工（完成 {cycles} 輪）",
             "cycles": cycles, "小時": round((time.time() - t0) / 3600, 2)})
        log.close()


if __name__ == "__main__":
    main()

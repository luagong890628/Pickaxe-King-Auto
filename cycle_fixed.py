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
# ---- 傳送選單座標 ----
# 2026-10-26 從實機選單截圖換算（畫面 1440×3120，截圖 500×1080 → ×2.88／×2.889）。
# 已實測驗證：ice (1066,1017) 確實傳到冰雪魔像島（雪地＋白色魔像）。
TILE = {"farm": (350, 800), "village": (350, 1810), "start": (720, 1810),
        # 四個島在選單右上／右中兩排（島嶼布局相同，只有傳送落點不同）
        "ice": (1066, 1077),      # 冰雪魔像島（選單右上）
        "shark": (711, 1077),     # 鯊魚島（選單中上）
        "duck": (1066, 1438),     # 鴨子島（選單右中）
        "truffle": (711, 1438)}   # 松露島（選單中中）
REST_TAP = (721, 1839)                                  # 帳篷休息對話框中心

# 傳送石冷卻（使用者 2026-10-26 確認 12 秒）：冷卻中再點不會傳送，選單會留在畫面上，
# 之後的手勢就打在選單上而不是搖桿。實測連續傳送間隔 6 秒時，後續滑動位移量到 0px。
# 目前每區走 24 秒以上，正常不會撞到；這個保護是為了日後再調快或縮短補時時不會靜默失敗。
TELEPORT_COOLDOWN = 12.0
# All island routes keep one second of slack: the game cooldown is 12s,
# while a completed island loop can land close to that boundary.
TELEPORT_COOLDOWN_MARGIN_BY_SOURCE = {"ice": 1.0, "shark": 1.0, "duck": 1.0, "truffle": 1.0}
_last_teleport = 0.0
_last_teleport_area = None

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
FOREST_DRAG = 150      # 林內（278px/秒）。需要更慢的段再覆寫成 120（見 VILLAGE）。
# 速度分三級（2026-10-26 定案）：
#   進場 1800（903px/秒）｜林內一般 150（278px/秒）｜需要更慢的段 120（221px/秒）
# 那些「慢段」原本是靠 SETTLE 停 0.5 秒補刀，後來改成降速取代停頓：
#   停頓是站著等（附近沒樹就純浪費），降速是邊走邊砍，同樣的時間花得更有效。
# 降速同時把一輪撐長，這是修「一輪 < 100 秒樹重生」的主要手段（不靠補時來回）。
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
FARM_DRAG = 150        # 自由農場A 林內拖曳（第2步起；進場第1步仍用 ENTRY_DRAG）
# 演進：300（552px/秒）→ 250（466）→ **150（278）**，跟其他區的林內速度一致。
# 農場是 700px 的長腿來回、佔全部距離約一半，所以這裡的速度對一輪長度影響最大。
# 進場段（用 ENTRY_DRAG / ENTRY_WEST_DRAG 的段）。'L' 方向的進場段用 ENTRY_WEST_DRAG。
# 起始之地是 (1, 3)：第 1 段北 425 在休息前，第 3 段西 150 在休息後
# （＝小村莊「先快後慢」那個快的部分）。
ENTRY_LEGS = {"village": (1, 2), "start": (1, 3), "farm": (1,)}
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
#   3 走完→4 之前、5 走完→6 之前、7 走完→8 之前、12 走完（北要走多一點+停頓）、
#   14 走完→15 之前、15 走完→16 之前、17 走完→18 之前
# 秒數：先試 2 秒（確實能把樹砍完），使用者回「2 秒太多，0.5 就夠了」→ 0.5。
#       停頓只需要讓揮鎬補完最後一兩刀，不是停越久越好；0.5 秒≈一到兩次揮鎬。
# 註：使用者原話是「11 北要走多一點」，但第 11 段是東 200、第 12 段才是北 125
#     → 依方向判定為第 12 段。若其實是第 11 段，把 12 改成 11 即可。
SETTLE_LEGS = {
    "village": {},   # 2026-10-26：原本停頓的段改成降速（拖 160），停頓歸零
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
FILL_PAIRS = 6                 # 再多砍幾組；1 組 = 3、4 各一次
# 前 5 組是採收所需，第 6 組是保險；作物刷新 4 分鐘，
# 不因村莊樹到期而縮短完整農場流程。

# ---- 里程模型：距離 → 按住時間（由 SPEED_TABLE 換算） ----
# 同場兩次實測（2026-10-21，run_leg.py village 1 2 --template）：
#   目標 970px / 按住 2809ms → 實走 978px（348px/秒）
#   目標 250px / 按住  847ms → 實走 291px（344px/秒）
# 兩點都落在「≈346px/秒、沒有起步延遲」；更早的「250px 只走 205px」與這兩點不符
# （很可能是那條腿被擋或量測誤差），不採用。
# 若日後短段又出現系統性偏短，先重測再動 STARTUP_MS，不要憑單一筆加補償。
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
# 起始之地＝START_PREFIX + VILLAGE[3:]（後段共用，改小村莊後段會兩區一起變）。
# 某一小段漏砍樹時，可在該段加第三個元素覆寫拖曳：(方向, px, 拖曳)，只影響那一段。
VILLAGE = [
    ("N", 1000.0),     # 1 往北進林（2026-10-26 由 850 改 1000，使用者現場確認）
    ("L", 150.0),      # 2 往西（使用者指定）
    ("L", 300.0, 120),      # 3 往西（使用者指定）
    ("N", 125.0),      # 4 往北（使用者指定 125）
    ("R", 250.0, 120),      # 5 往東（2026-10-22 現場實走 248px 記錄）
    ("N", 125.0),      # 6 往北（使用者指定 125）
    ("L", 250.0, 120),      # 7 往西（使用者指定 250）
    ("N", 100.0),      # 8 往北（使用者指定 100）
    ("R", 350.0),      # 9 往東（使用者指定 350）
    ("S", 125.0),      # 10 往南（使用者指定 125）
    ("R", 200.0),      # 11 往東
    ("N", 150.0, 120),      # 12 往北（2026-10-26 由 125 改 150：使用者「要走多一點」）
    ("R", 350.0),      # 13 往東（使用者指定350）
    ("S", 125.0, 120),      # 14 往南（使用者指定125）
    ("L", 250.0, 120),      # 15 往西（使用者指定250）
    ("S", 250.0),      # 16 往南（使用者指定250）
    ("R", 300.0, 120),      # 17 往東（2026-10-26 180 → 200 → 225 → 250 → 300：使用者「最後東走的走 300」）
    ("N", 100.0),      # 18 往北（使用者更正）
]

# 起始之地只有前 4 段是自己的（北到帳篷 → 休息 → 西 150 → 西 300），
# **第 5 段起與小村莊完全對齊**，所以後段直接共用 VILLAGE[3:]：
#   改小村莊的後段 = 兩區一起改，不會出現「調了一區忘了另一區」的漂移。
# 前段刻意跟小村莊同一個節奏（使用者 2026-10-26 指示「休息完跟小村莊一樣
#   先走一段快的、再走一段慢的」）：西 150 拖 250（快，ENTRY_WEST_DRAG）
#   → 西 300 拖 120（更慢）。原本是合併成一段西 450 走慢的。
START_PREFIX = [
    ("N", 450.0),      # 1 往北到帳篷（2026-10-26 由 425 改 450：使用者指定）
    ("REST",),         # 2 點帳篷休息
    ("L", 150.0),      # 3 往西（快：拖 250，＝小村莊第 2 段）
    ("L", 300.0, 120), # 4 往西（慢：拖 120，＝小村莊第 3 段；2026-10-26 使用者指定同步）
]

# ---- 島嶼：多餘時間（主三區都在刷新）才去 ----
# 使用者 2026-10-29：**固定順序** 冰雪魔像 → 鯊魚 → 鴨子 → 松露，排除剛離開的那座。
# 不要用權重抽選，也不要把重生時間寫成門檻（重生只是大約值：冰雪實測 108 秒，
# 四座島之後還會再降）。同一個補空檔窗口內每座島只去一次，逛完四座就回主區等樹。
# 路線還空著的島排程器會自動跳過（不會傳送過去發呆）。
ISLANDS = ("ice", "shark", "duck", "truffle")
ISLAND_ENTRY_LEGS = 2
ISLAND_SHRINK_PX = 100.0       # 每個循環的每段距離向內縮 100px
ISLAND_MIN_DWELL = 12.0
VILLAGE_FIRST_CUT_INTERVAL = 105.0

# 一趟島的實際耗時（傳送 → 下一座傳送）。2026-10-29 由 6 小時執行紀錄統計，
# 當時外圈只有 800×400 級別，約 13.6～15.2 秒；2026-10-30 外圈放大到生怪區滿版後
# 估計約 18 秒（進場 2.4s + 兩圈 7.4s×2 + 傳送 1.2s），實際值待實機驗證。
# 只用在 --dry-run 的說明與人工估算；程式判斷一律用「這一輪去過了沒」，
# 不把秒數寫進決策（重生時間只是大約值，寫死反而會擋掉還能採的島）。
ISLAND_TRIP_SECONDS = 18.0

ISLAND_LABEL = {"ice": "冰雪魔像島", "shark": "鯊魚島",
                "duck": "鴨子島", "truffle": "松露島"}

# 生怪區實測尺寸（東 × 南）。2026-10-29 冰雪魔像島：
#   A 西北、B 東北 = 東 1000；A → D = 南 844。
# 四座島**布局相同、只有傳送落點不同**（使用者 2026-10-26 確認），所以四座共用這組尺寸。
ISLAND_FIELD_W = 1000.0
ISLAND_FIELD_H = 844.0
# 外圈實際走的距離（使用者 2026-10-30 實走定案）：
#   東/西 1000 = 實測值剛好（東/西是水，走過頭會卡住，不會歪）
#   南/北  850 = 實測 844 + 6px 保險（南是柵欄、北是水，同樣會卡住）
# 四邊都是硬邊界 → 走過頭只是浪費幾毫秒，走不足會留下一條掃不到的邊；
# 而且任一角落出發，走完第一圈就會貼到真正的邊界上。
ISLAND_LOOP_W = 1000.0
ISLAND_LOOP_H = 850.0

ISLAND_ROUTES = {
    # 前 2 段＝進場（只走一次，把角色帶到生怪區的一個角落）；
    # 後 4 段＝一個完整外圈，之後每個循環由 ISLAND_SHRINK_PX 往內縮。
    # 四座外圈完全一樣（ISLAND_LOOP_W × ISLAND_LOOP_H），差別只在進場從哪個方向走進去。
    "ice": [("N", 950.0, 300), ("L", 500.0, 300),
            ("S", ISLAND_LOOP_H, 300), ("R", ISLAND_LOOP_W, 300),
            ("N", ISLAND_LOOP_H, 300), ("L", ISLAND_LOOP_W, 300)],      # 西北角進：南→東→北→西
    "shark": [("N", 950.0, 300), ("L", 500.0, 300),
              ("S", ISLAND_LOOP_H, 300), ("R", ISLAND_LOOP_W, 300),
              ("N", ISLAND_LOOP_H, 300), ("L", ISLAND_LOOP_W, 300)],    # 先照冰雪島進場與外圈
    "duck": [("R", 1000.0, 300), ("N", 250.0, 300),
             ("L", 850.0, 300), ("S", ISLAND_LOOP_H, 300),
             ("R", 850.0, 300), ("N", ISLAND_LOOP_H, 300)],     # 東北角進：西→南→東→北
    "truffle": [("N", 950.0, 300), ("L", 500.0, 300),
                ("S", ISLAND_LOOP_H, 300), ("R", ISLAND_LOOP_W, 300),
                ("N", ISLAND_LOOP_H, 300), ("L", ISLAND_LOOP_W, 300)],  # 先照冰雪島進場與外圈
}

ROUTES = {
    "village": VILLAGE,
    "start": START_PREFIX + VILLAGE[3:],
    "farm": [("N", 600.0), ("L", 350.0), ("R", 700.0), ("L", 700.0)],
    # 自由農場A：北進場 600 → 西 350 → 東 700 → 西 700（3、4 可來回重複）
    **ISLAND_ROUTES,
}
LABEL = {"village": "小村莊", "start": "起始之地", "farm": "自由農場A", **ISLAND_LABEL}

# ---- 排程：各地區的資源刷新時間（秒）----
# 為什麼要這個：以前是「小村莊→起始之地→農場」固定一輪，不管有沒有刷新。
# 一輪 98 秒、農場卻要 240 秒才刷新 → **每 2.4 趟就有 1.4 趟是白跑**（走過去、什麼都沒有）。
# 改成「只去已經刷新的地區」，空下來的時間拿去打其他場，而不是空跑一趟沒有東西的路線。
# 0 = 隨時可去（沒有刷新限制的地區用）。
REFRESH = {
    "village": 100.0,   # 樹重生（實測約 100 秒）
    "start": 100.0,     # 起始之地與小村莊同一批樹
    "farm": 240.0,      # 作物刷新 4 分鐘（使用者 2026-10-26 確認）
    # 島嶼：0＝不設刷新門檻（使用者 2026-10-29）。重生時間只是大約值
    # （冰雪實測 108 秒、之後還會再降），寫死成門檻反而會擋掉還能採的島；
    # 改用固定順序繞一輪，回來時自然就重生了。
    **{a: 0.0 for a in ISLANDS},
}
# 加新場地時：ROUTES 加路線、LABEL 加名稱、這裡加刷新秒數，排程器就會自動排進去。


def _ready_at(area, last):
    """這區下一次可以去的時刻。沒去過 → -inf（永遠最優先）。"""
    return last.get(area, float("-inf")) + REFRESH[area]


def _overdue(area, now, last):
    """超過自己刷新週期的比例。沒去過 → inf；刷新 0（隨時可去）→ inf。"""
    r = REFRESH[area]
    if r <= 0:
        return float("inf")
    return (now - last.get(area, float("-inf"))) / r


def choose_island(excluded=None):
    """固定順序：冰雪 → 鯊魚 → 鴨子 → 松露（排除已去過的）。

    使用者 2026-10-29：不抽選、也不看重生時間（那是大約值，寫死成門檻反而擋掉能採的島）。
    做法是「從被排除那些的下一座往後找」，所以順序固定、不會原地重複；
    排除集合就是「這個補空檔窗口已經逛過的島」，全部去過就回傳 None（＝回主區等樹）。
    路線還空著的島自動跳過。
    """
    excluded = set() if excluded is None else set(excluded)
    valid = [a for a in ISLANDS if ROUTES.get(a)]
    if not valid:
        return None
    start = 0
    for a in ISLANDS:                      # 從被排除那座（＝剛離開的）的下一座開始
        if a in excluded:
            start = ISLANDS.index(a) + 1
    for i in range(len(ISLANDS)):
        area = ISLANDS[(start + i) % len(ISLANDS)]
        if area not in excluded and area in valid:
            return area
    return None


ISLAND_RING_MARK = "RING"      # 一圈結束的標記（island_actions → run_island_filler）


def island_actions(area, max_loops=4):
    """進場一次，然後以四段螺旋向內掃描；每兩段各縮 100px。"""
    route = ROUTES[area]
    yield from route[:ISLAND_ENTRY_LEGS]
    loop = [route_act(act) for act in route[ISLAND_ENTRY_LEGS:]]
    loop_size = len(loop)
    for i in range((max_loops or 10 ** 6) * loop_size):
        direction, base_px, override = loop[i % loop_size]
        next_px = base_px - ISLAND_SHRINK_PX * (i // 2)
        if next_px <= 0:
            return
        yield (direction, next_px, override)
        if i % loop_size == loop_size - 1:
            yield (ISLAND_RING_MARK,)


def island_dwell_elapsed(start):
    """Return real elapsed island dwell; ``start`` comes from perf_counter."""
    return time.perf_counter() - start


def _teleport_cooldown_margin():
    return TELEPORT_COOLDOWN_MARGIN_BY_SOURCE.get(_last_teleport_area, 0.0)


def _teleport_cooldown_wait(now=None):
    """Seconds until a tap is safe, including the source route's margin."""
    if not _last_teleport:
        return 0.0
    now = time.time() if now is None else now
    return max(0.0, TELEPORT_COOLDOWN + _teleport_cooldown_margin()
               - (now - _last_teleport))


def _teleport_cooldown_ready():
    return _teleport_cooldown_wait() <= 0.0


def primary_cycle_limit(cycles):
    """--cycles counts the three primary areas, never island filler routes."""
    return None if cycles is None else cycles * 3


def next_stop(now, last, village_first_cut=None):
    """排程器：回傳 (地區, 還要等幾秒)。等 0 表示現在就可以去。

    兩層：
    1. **主區**（小村莊／起始之地／農場）先顧，只挑已經刷新的，
       並優先挑**超過自己週期比例最多**的那個（用比例而非絕對秒數，
       否則一趟走得比刷新還久的地區會永遠最超時、把其他區餓死）。
    2. 主區全都在刷新 → 這是**空檔**，由主迴圈交給島嶼補空檔。
    3. 連島都不能去 → 回傳最快好的主區 + 要等多久。

    last[area] = 上一次「開始採集」的時刻；沒去過視為 -inf（永遠最優先）。
    """
    main = [a for a in REFRESH if a not in ISLANDS]
    ready = [a for a in main if _ready_at(a, last) <= now]
    if village_first_cut is not None:
        village_ready = village_first_cut + VILLAGE_FIRST_CUT_INTERVAL
        if now < village_ready:
            ready = [a for a in ready if a != "village"]
    unvisited_other = [a for a in main if a != "village" and a not in last]
    if "village" in ready and village_first_cut is not None and not unvisited_other:
        return "village", 0.0
    if ready:
        # 同分時取宣告順序前面那個 → 第一趟固定是 village → start → farm
        return max(ready, key=lambda a: (_overdue(a, now, last), -main.index(a))), 0.0
    ready_at = {a: _ready_at(a, last) for a in main}
    if village_first_cut is not None:
        ready_at["village"] = max(ready_at["village"],
                                   village_first_cut + VILLAGE_FIRST_CUT_INTERVAL)
    soonest = min(main, key=lambda a: ready_at[a])
    return soonest, max(0.0, ready_at[soonest] - now)


# 起始之地後段與小村莊共用 → 停頓點直接沿用。
# 前段比小村莊多出 REST 這一段，所以段號要平移 _SHIFT：
#   起始之地第 4 段（西 300）＝小村莊第 3 段，第 5 段＝小村莊第 4 段 …
# 用平移而不是寫死數字，日後前段再增減段落時對應關係會自動跟上。
_SHIFT = len(START_PREFIX) - 3      # 前段比小村莊的 3 段多幾段（現在多 1 段 REST）
SETTLE_LEGS["start"] = {n + _SHIFT: s for n, s in SETTLE_LEGS["village"].items() if n >= 3}


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
    """固定傳送流程；不送 HEART tap 直到來源冷卻安全。"""
    global _last_teleport, _last_teleport_area
    wait = _teleport_cooldown_wait()
    if wait:
        rec({"note": f"等傳送石冷卻 {wait:.1f}s"})
        time.sleep(wait)
    adb.tap(*HEART)
    time.sleep(TELEPORT_WAIT)
    adb.swipe(*MENU_SCROLL_FROM, *MENU_SCROLL_TO, MENU_SCROLL_MS)
    time.sleep(TELEPORT_WAIT)
    adb.tap(*TILE[area])
    _last_teleport = time.time()
    _last_teleport_area = area
    time.sleep(TELEPORT_WAIT)
    rec({"note": f"傳送 {area}", "big": True,
         "show": f"[{LABEL[area]}] 傳送完成"})


REST_WAIT = 2.0          # 點擊休息後等動畫（2026-10-23 由 3.2 改 2 秒，尚未實跑驗證）
TELEPORT_WAIT = 0.3      # 傳送過程中每個手勢之後等畫面反應（2026-10-26 由 0.5 改 0.3）
# 這三個 0.3 秒是「選單還沒收起來、下一步手勢就打在那個選單上」的保險。
# 出事的話整趟都會歪掉，所以要再往下砍之前，先確認實機連走 20 站都沒失手。


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


# ---- 珍珠（小村莊）：純插拔，冷卻 10 分鐘 ----
# 2026-10-26 使用者實測：從傳送落點往西 1080 → 點 (721,1839) → 往東 1080
# **會精準回到落點**，所以不影響後面的路線，可以插在村莊流程最前面。
# 點擊座標和小屋休息同一個（REST_TAP）；冷卻中點下去不會有反應（跟黃金樹一樣）。
PEARL_WEST = 1080.0        # 往西走多遠（東西向拖曳上限 720px，1080 是分段走的距離，不是拖曳長度）
PEARL_EAST = 1080.0        # 回程往東（= 西的距離，才會回到原位）
PEARL_DRAG = 720           # 珍珠去回程用最快（東/西向的拖曳硬上限就是 720 → 794px/秒）
# 珍珠只是去拿東西、不需要邊走邊砍，所以不必跟林內一樣慢；
# 1080px 用 720（794px/秒）只要 1.4 秒，用林內的 150（278px/秒）要 3.9 秒。
PEARL_COOLDOWN = 600.0     # 冷卻 10 分鐘
PEARL_WAIT = 0.3           # 點珍珠後等拿取動畫（2026-10-26 由 REST_WAIT 的 2.0 改成 0.3）
# 和帳篷休息分開：休息要等角色躺完（2 秒），珍珠只是點一下就拿走，不用跟著等那麼久。
PEARL_TOLERANCE = 20.0     # --pearl-only 回歸驗證：出發點與回程點允許差幾 px 算「回到原位」
_pearl_at = 0.0            # 上次拿到珍珠的時刻（0＝還沒拿過，第一輪一定去）


def pearl(rec, img, force=False):
    """往西 1080 → 點珍珠 → 往東 1080 回原位。冷卻沒到就跳過、什麼都不做。

    用「距離上次拿到超過冷卻」判斷，不用「每 N 輪」：
    輪次長度會隨路線/速度變動，用輪數會在調整路線後失準。
    force=True 則忽略冷卻（--pearl-only 專用：測試落點時要能連續跑）。
    """
    global _pearl_at
    if not force and _pearl_at and time.time() - _pearl_at < PEARL_COOLDOWN:
        return img
    img = leg(img, "L", PEARL_WEST, rec, "珍珠去程", drag_len=PEARL_DRAG, settle=0)
    adb.tap(*REST_TAP)
    time.sleep(PEARL_WAIT)                   # 等拿取動畫
    img = leg(img, "R", PEARL_EAST, rec, "珍珠回程", drag_len=PEARL_DRAG, settle=0)
    _pearl_at = time.time()
    rec({"note": "拿珍珠", "big": True, "show": "拿珍珠（冷卻 10 分鐘）"})
    return img


def run_area(area, rec, no_pearl=False):
    """Teleport and complete one primary area without checking mid-gesture."""
    teleport(area, rec)
    rec({"note": f"[{LABEL[area]}] 開始採集", "big": True})
    img = shot() if MEASURE else None
    if area == "village" and not no_pearl:
        img = pearl(rec, img)
    first_cut = None
    for i, act in enumerate(ROUTES[area], 1):
        if area == "village" and i == 2:
            # The interval starts immediately before village movement #2,
            # the first harvesting gesture; movement #1 is unrelated travel.
            first_cut = time.time()
        if act[0] == "REST":
            img = rest(rec, img, LABEL[area])
        else:
            d, px, _ = route_act(act)
            img = leg(img, d, px, rec, LABEL[area],
                      drag_len=route_drag(area, i),
                      settle=route_settle(area, i))
    if area in FILL_LEGS:
        img = fill_cycle(area, rec, img)
    return first_cut, img


def run_island_filler(rec, deadline, visited=None):
    """Fill until deadline, yielding only after a complete loop and >=12s dwell.

    ``visited`` 由呼叫端持有、跨多次呼叫累積：**同一個補空檔窗口內每座島只去一次**。
    實測一趟島 13～16 秒，繞完四座約 60 秒；而島上樹木重生要一分鐘以上，
    所以第五趟起就是走同一塊空地、收益接近 0。逛完四座就回主區等樹。
    這裡刻意不寫任何重生秒數（那只是大約值），只用「這一輪去過了沒」當依據。

    Cooldown/minimum-dwell overruns keep the current loop moving. The caller's
    run_area owns the village transfer; a bounded --minutes run can instead
    stop here without an unnecessary return trip.
    """
    visited = set() if visited is None else visited
    area = choose_island(visited)
    if area is None:
        return False
    while True:
        teleport(area, rec)
        visited.add(area)
        rec({"note": f"[{LABEL[area]}] 開始補空檔", "big": True})
        img = shot() if MEASURE else None
        island_started = time.perf_counter()
        gesture = 0
        loop_count = 0
        dwell = 0.0
        for act in island_actions(area, max_loops=None):
            if act[0] == ISLAND_RING_MARK:
                loop_count += 1
                if dwell < ISLAND_MIN_DWELL:
                    continue
                if time.time() >= deadline:
                    rec({"note": f"{LABEL[area]}島補空檔結束（期限已到，傳送由 teleport 安全等待）",
                         "island": area, "gesture": gesture, "decision": "return"})
                    return True
                next_area = choose_island(visited)
                if next_area is None:
                    rec({"note": f"{LABEL[area]}島完成 {loop_count} 圈，四座都逛過 → 回主區",
                         "island": area, "gesture": gesture, "loop": loop_count,
                         "decision": "return", "visited": len(visited)})
                    return True
                rec({"note": f"{LABEL[area]}島完成 {loop_count} 圈，切換島嶼",
                     "island": area, "gesture": gesture, "loop": loop_count,
                     "decision": "switch"})
                area = next_area
                break
            d, px, override = route_act(act)
            img = leg(img, d, px, rec, f"{LABEL[area]}補空檔",
                      drag_len=override if override is not None else 300,
                      settle=0)
            gesture += 1
            dwell = island_dwell_elapsed(island_started)
            rec({"note": f"{LABEL[area]}島停留 {dwell:.1f}s，第{gesture}個手勢",
                 "island": area, "dwell_s": round(dwell, 3),
                 "gesture": gesture, "circle": loop_count, "loop": loop_count})
            # 滿 12 秒後，期限一到就在這個手勢邊界離開（不切斷正在送出的拖曳）
            if (gesture > ISLAND_ENTRY_LEGS and dwell >= ISLAND_MIN_DWELL
                    and time.time() >= deadline):
                rec({"note": f"{LABEL[area]}島補空檔結束（期限已到，傳送由 teleport 安全等待）",
                     "island": area, "gesture": gesture, "decision": "return"})
                return True
        else:
            rec({"note": f"{LABEL[area]}島循環距離已縮到邊界，回主區",
                 "island": area, "decision": "return"})
            return True


def main():
    global MEASURE, VERBOSE, SPEED_SCALE
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=None,
                    help="執行分鐘數（預設無限循環，按 Ctrl+C 停止）")
    ap.add_argument("--cycles", type=int, default=None,
                    help="跑幾輪就停（預設不限；--cycles 1 ＝每個地區各採一次後結束）")
    ap.add_argument("--wait", type=float, default=0,
                    help="每輪之間額外等幾秒（預設 0：靠林內慢走控制週期）")
    ap.add_argument("--verbose", action="store_true",
                    help="console 也印每一段（預設只印輪次、傳送、休息與錯誤）")

    ap.add_argument("--no-pearl", action="store_true",
                    help="不拿珍珠（預設每超過 10 分鐘冷卻就去拿一次）")
    ap.add_argument("--pearl-only", action="store_true",
                    help="只走珍珠路線：傳送到小村莊 → 西 → 點珍珠 → 東 → 結束（忽略冷卻，測落點用）")
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
        for area in ROUTES:
            print(f"\n[{LABEL[area]}] 傳送落點 {TILE[area]}")
            if not ROUTES[area]:
                print("  （路線還沒填 → 排程器會跳過這個島，不會傳送過去發呆）")
                continue
            for i, act in enumerate(ROUTES[area], 1):
                if act[0] == "REST":
                    print(f"  {i}. 休息（點 {REST_TAP}，等 {REST_WAIT}s）")
                    continue
                d, px, override = route_act(act)
                drag = route_drag(area, i)
                tag = f"（單段覆寫 {override:g}）" if override is not None else ""
                s_ = route_settle(area, i)
                dwell = f"／停 {s_:g}s" if s_ else ""
                print(f"  {i}. {NAMES[d]} {px:.0f}px → 拖 {drag:g}px／按住 {hold_ms(px, drag)}ms{tag}{dwell}")
            if area in FILL_LEGS:
                print(f"  補時：再多 {FILL_PAIRS} 組第 "
                      f"{'、'.join(str(n) for n in FILL_LEGS[area])} 段來回（固定組數，不看時間）")
        print(f"珍珠：往西 {PEARL_WEST:.0f} → 點 {REST_TAP}（等 {PEARL_WAIT:g}s）→ 往東 {PEARL_EAST:.0f}"
              f"（拖 {PEARL_DRAG}px → {speed_of(PEARL_DRAG):.1f}px/秒，"
              f"冷卻 {PEARL_COOLDOWN/60:.0f} 分鐘；第一輪一定拿）")
        if args.pearl_only:
            print("※ --pearl-only：只傳送到小村莊走珍珠，忽略冷卻，不走任何採集路段")
            return
        print("\n排程（只去已刷新的地區；主區全在刷新 → 用空檔打島嶼）：")
        for a in REFRESH:
            r = REFRESH[a]
            mark = ""
            if a in ISLANDS:
                mark = "　← 空檔才去" + ("" if ROUTES.get(a) else "，路線待填（跳過）")
            print(f"  {LABEL[a]:8s} 刷新 {r:5.0f}s"
                  + ("（隨時可去）" if r <= 0 else "") + mark)
        print(f"  {'珍珠':8s} 冷卻 {PEARL_COOLDOWN:5.0f}s（附掛在小村莊，不會單獨跑一趟）")
        print(f"  島嶼順序：{' → '.join(ISLAND_LABEL[a] for a in ISLANDS)}"
              f"（固定順序；不抽選、不設重生門檻、同一個窗口內不回頭）")
        print(f"  補空檔規則：一個窗口內每座島只去一次 → 最多 {len(ISLANDS)} 趟"
              f"（一趟約 {ISLAND_TRIP_SECONDS:g}s，四趟約 "
              f"{len(ISLANDS) * ISLAND_TRIP_SECONDS:g}s；逛完就回主區等樹）")
        print(f"　固定座標：愛心{HEART} 休息{REST_TAP}")
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

    if args.pearl_only:
        # 只走珍珠：傳送到小村莊落點 → 西 → 點珍珠 → 東 → 結束。
        # 忽略冷卻（測試落點時要能連續跑），不走任何採集路段。
        # **回歸驗證**：去程/回程各 1080px 太長（> 螢幕寬），逐段量位移一定量不到；
        # 所以改成「出發前拍一張、回來再拍一張」直接比對，位移 ≈0 就代表精準回到落點。
        rec({"note": "珍珠單走（忽略冷卻）", "big": True, "show": "珍珠單走（忽略冷卻）"})
        try:
            teleport("village", rec)
            before = shot()
            pearl(rec, before, force=True)
            # 只拍一張容易被動畫（落葉、水波、動物、獎勵提示）干擾而量不到，
            # 所以最多重拍 3 次、取分數最高的那張；分數 <0.9 的結果一律不採信。
            m = None
            for _ in range(3):
                m2 = measure.world_shift(before, shot())
                if m2 and (m is None or m2[2] > m[2]):
                    m = m2
                if m and m[2] >= 0.9:
                    break
            if m is None:
                rec({"note": "落點回歸：量不到", "big": True, "show": "落點回歸：量不到（換幀差異太大）"})
            else:
                dx, dy, score, src = m
                off = math.hypot(dx, dy)
                if score < 0.9:
                    verdict = f"不可信（分數 {score:.2f} 太低）"
                elif off <= PEARL_TOLERANCE:
                    verdict = "回到原位"
                else:
                    verdict = f"偏 {off:.0f}px"
                rec({"note": f"落點回歸：位移 ({dx:+.0f},{dy:+.0f})px 分數 {score:.2f}（{src}）→ {verdict}",
                     "big": True,
                     "show": f"落點回歸：位移 ({dx:+.0f},{dy:+.0f})px 分數 {score:.2f}（{src}）→ {verdict}"})
        except KeyboardInterrupt:
            rec({"note": "使用者停止（Ctrl+C）", "big": True, "show": "使用者停止（Ctrl+C）"})
        finally:
            rec({"note": "收工", "big": True, "show": "收工（珍珠單走）"})
            log.close()
        return

    # --cycles counts only the primary village/start/farm stations.
    step_limit = primary_cycle_limit(args.cycles)
    last_visit = {}          # area → 上一次開始採集的時刻
    steps = 0
    last_first_cut = None
    filler_visited = set()   # 這一輪補空檔已經逛過的島（小村莊重新採集就清空）

    try:
        while time.time() < deadline and (step_limit is None or steps < step_limit):
            now = time.time()
            area, wait = next_stop(now, last_visit, last_first_cut)
            if wait > 0:
                if last_first_cut is not None:
                    filler_deadline = min(last_first_cut + VILLAGE_FIRST_CUT_INTERVAL,
                                          deadline)
                    if now < filler_deadline:
                        did_work = run_island_filler(rec, filler_deadline, filler_visited)
                        if did_work:
                            continue
                        # 沒有可去的島（四座都逛過）→ 直接等主區刷新，不要空轉。
                        # 重新算一次 wait：剛剛補空檔可能已經跑到別的主區該上場了。
                        _, wait_now = next_stop(time.time(), last_visit, last_first_cut)
                        end = min(time.time() + wait_now, filler_deadline, deadline)
                        while time.time() < end:
                            time.sleep(min(1.0, end - time.time()))
                        continue
                rec({"note": f"{LABEL[area]} 還沒刷新，等 {wait:.0f}s", "big": True,
                     "show": f"等 {LABEL[area]} 刷新 {wait:.0f}s"})
                end = min(time.time() + wait, deadline)
                while time.time() < end:
                    time.sleep(min(2, end - time.time()))
                if time.time() >= deadline:
                    break
                continue

            steps += 1
            last_visit[area] = time.time()          # 以「開始採集」為刷新起點（保守）
            rec({"note": f"=== 第 {steps} 站：{LABEL[area]} ({time.strftime('%H:%M')}) ===",
                 "big": True, "show": f"=== 第 {steps} 站：{LABEL[area]} ==="})

            first_cut, _ = run_area(area, rec, args.no_pearl)
            if first_cut is not None:
                last_first_cut = first_cut
                filler_visited.clear()      # 小村莊重新採集 → 新的補空檔窗口

            if args.wait:
                time.sleep(args.wait)

    except KeyboardInterrupt:
        rec({"note": "使用者停止（Ctrl+C）", "big": True, "show": "使用者停止（Ctrl+C）"})
    finally:
        rec({"note": "收工", "big": True, "show": f"收工（完成 {steps} 站）",
             "站數": steps, "小時": round((time.time() - t0) / 3600, 2)})
        log.close()


if __name__ == "__main__":
    main()

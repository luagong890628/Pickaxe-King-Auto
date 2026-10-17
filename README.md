# Pickaxe King Auto

自動化《Pickaxe King Island》（Android `com.rogueuniongames.pickaxekingisland`）的素材採集。
透過 adb 控制手機、以 OpenCV 判斷畫面：截圖 → 判斷 → 點擊／滑動。

第一階段目標：「缺木頭」——自動導航到木材點（起始之地、小村莊為主）採集；
後續再擴充成整套自動刷流程。

## 現況（2026-10-18）

- 裝置：Samsung SM-S9360（Android 16），USB，`adb devices` = `R5GL15085ZJ`。
- 已驗證：
  - 截圖 `adb exec-out screencap -p`，約 0.7 秒／張（1440×3120）。
  - `adb shell input tap` 可送達 Unity 遊戲（點小屋會跳出「在小屋裡休息！」對話框）。
  - **移動＝按住拖曳**：拖曳方向＝角色行進方向；拖 0.9 秒 ≈ 世界位移 400–440 px；
    上／下／左／右四個方向量測一致。單純點一下、原地長按 1.5 秒皆不會移動。
  - 無輸入時位移量測為 (0, 0)（response > 0.6），可作為移動偵測基準（相位相關，見 `tests/`）。
  - 同一輸入連續兩次有位移、第三次變 0：是撞到地形／水域／地圖邊界，不是輸入失效。
- 待確認（等使用者確認）：
  - 角色在畫面上的固定錨點（暫定 (720, 1400)，水平置中、垂直中央偏上）。
  - 樹木位置與砍伐觸發方式（走過去自動砍？需點擊？）。
  - 「起始之地」「小村莊」與目前位置的相對方向（木材主要產地）。

## 快速開始

```bash
# 一次性：建立環境（已建立則略過）
python313 -m venv .venv && .venv\Scripts\python.exe -m pip install -r requirements.txt

# 截圖
.venv\Scripts\python.exe pk.py shot
# 點擊／滑動
.venv\Scripts\python.exe pk.py tap 720 1700
.venv\Scripts\python.exe pk.py swipe 720 1900 720 1500 800
# 目前前景 App
.venv\Scripts\python.exe pk.py app
# 量測兩張截圖之間的世界位移
.venv\Scripts\python.exe pk.py scroll captures/a.png captures/b.png

# 測試
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## 結構

```
pkauto/adb.py      adb 控制層（截圖／點擊／滑動／按鍵）
pkauto/vision.py   影像工具（世界位移、模板比對、區域裁切）
pk.py              CLI 入口
tests/             合成影像單元測試（不需裝置）
captures/          執行時截圖（不進版控）
```

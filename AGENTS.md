# Pickaxe King Auto — 專案規則

上層 `D:\project\AGENTS.md` 通則全部適用；本檔只列本專案特有事項。

## 環境

- Python 一律用本專案 `.venv`：`.venv\Scripts\python.exe`（勿用系統 python，系統 python 沒有 cv2）。
- 依賴見 `requirements.txt`（opencv-python、numpy）。
- 裝置：Samsung SM-S9360（Android 16）USB 連線。adb 預設 `D:/Tools/scrcpy-win64-v3.3.4/adb.exe`，可用環境變數 `PKAUTO_ADB` 覆寫。
- 遊戲：`com.rogueuniongames.pickaxekingisland`（Unity）。

## 原則

- 每次與手機互動都要可獨立重放：截圖存 `captures/`（不進版控）。
- 自動點擊只允許發生在遊戲可視區（`pkauto.vision.PLAY_BOX`）：x 260–1140、y 700–2900。左右 UI 欄、頂部資源列不盲點。
- 畫面判斷優先用可量測的訊號（相位相關位移、模板比對分數），且要在 `tests/` 用合成影像驗證，不靠目測猜。
- 移動／採集邏輯必須能回答「現在角色在哪、目標在哪、這一步有沒有效」，效果用截圖前後差異驗證。

## 目前做法（2026-10-21 使用者定案：純機械化固定流程）

- 唯一主程式 `cycle_fixed.py`：**不做任何畫面偵測**，全部固定座標 + 固定步數。
- 一輪：傳送小村莊 → 北 3 步 → 左1北1右2南1 → 傳送起始之地 → 北 2 步 →
  點 (721,1839) 休息 → 左1北1右2南1 → 等 30 秒。實測一輪 112 秒。
- 傳送石 (1340,1670)、選單格子 (330,1464)/(720,1434)（選單先手動往上滑一次歸位）。
- 一步 = 拖 250px、按住 950ms ≈ 走 300px（搖桿式：距離取決於按住時間，不是拖曳長度）。
- **不要再引入畫面偵測**：先前所有偵測/地圖/觸控重播的做法都已證明不穩並移除
  （詳見 README 的「歷史」與 git 歷史）。

## 程序管理（踩過大坑）

- **Hermes 的 process kill 只殺外層**，`python.exe` 子程序會活著 →
  多個殘留 `record_touch.py` 同時寫入同一個 JSON → 檔案損毀、資料報銷。
- 收工後一定用
  `powershell Get-CimInstance Win32_Process | Where CommandLine -like '*Pickaxe*'`
  核對，沒有殘留才繼續。
- 長時間錄製的檔案一律**原子寫入**（寫 `.tmp` 後 `os.replace`）。

## 測試

```
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## 文件

- `README.md` 記錄現況與操作方式；探索結論寫進 README 的「已知」段落。
- 不下未驗證的結論；不確定就標「待確認」。
- **給使用者看的圖一律存進 `captures/`**（agent 的 scratch 目錄使用者看不到），回報時附完整路徑；
  需要使用者判斷位置時，圖上要畫格線或標註座標，並在訊息中同時列出座標文字。

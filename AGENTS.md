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

## 目前路線（2026-10-19 使用者定案）

- **採固定路線 + 1:1 重播原始搖桿操作**；不做「看畫面偵測樹/石頭」的智慧化
  （樹會被擋住、看得到才偵測一定漏；而走過去就會自動揮砍，所以路線走過就好）。
- 路線錄製：`record_touch.py`（getevent）→ `data/touch/<name>.json`（進版控）。
  重播：`replay_touch2.py`（一個手勢一次 `input swipe`）＋ `run_route.py` 先傳送到落點。
- 換手機／換觸控面板要重跑 `do_calib.py`；`data/touch/_calib.json` 與裝置綁定。

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

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

## 測試

```
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## 文件

- `README.md` 記錄現況與操作方式；探索結論寫進 README 的「已知」段落。
- 不下未驗證的結論；不確定就標「待確認」。
- **給使用者看的圖一律存進 `captures/`**（agent 的 scratch 目錄使用者看不到），回報時附完整路徑；
  需要使用者判斷位置時，圖上要畫格線或標註座標，並在訊息中同時列出座標文字。

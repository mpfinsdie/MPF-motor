# 馬達測試系統 - Motor Test System

馬達測試數據量測程式，用於量測三相數位 Hall Sensor 與 Encoder (A/B) 訊號。
使用 **Advantech USB-4716** DAQ 裝置進行類比電壓量測與數位訊號讀取。

---

## 功能特色

### Hall Sensor (3.3V 系統)
- AI 通道量測三相 (U/V/W) 電壓準位（監控 WaveformAI 連續串流 20,000 Hz/通道，診斷模式可達 200,000 Hz/通道）
- DI 通道讀取 H/L 數位狀態
- AI 與 DI 一致性驗證
- 電壓閾值判斷：H > 2.0V，L < 0.8V（可調整）

### Encoder (5V 系統)
- AI 通道量測 A/B 相電壓準位（監控 WaveformAI 連續串流 20,000 Hz/通道，診斷模式可達 200,000 Hz/通道）
- DI 通道讀取 H/L 數位狀態
- 電壓閾值判斷：H > 3.5V，L < 1.5V（可調整）
- 軟體正交解碼（A/B 相位差 90°）
- 轉速計算（RPM）
- 旋轉方向判斷（正轉/反轉/靜止）
- 角度位置計算（度）

### 🔌 硬體通道彈性設定（v1.8 新增）
- **不再寫死 AI0~4 / DI0~4**：Hall U/V/W 與 Encoder A/B 對應的 AI、DI 通道可由使用者自行調整
- **UI 對話框設定**：主畫面新增「🔌 硬體通道」按鈕，開啟對話框即可設定每個訊號的 AI/DI 通道、AI 量程、DI 埠號
- **即時套用**：設定後立即熱重載（`refresh_channels()`），無需重啟程式
- **JSON 設定檔持久化**：設定存於 `config/channel_map.json`，下次啟動自動載入；缺漏欄位自動以預設值補齊
- **重複通道檢查**：套用前驗證 AI、DI 通道不重複，避免衝突
- **非連續通道支援**：可設定任意通道（如 AI 5/6/7/8/9），WaveformAI 以 min~max 範圍掃描後依欄位索引解交錯取出

### GUI 介面
- PyQt5 + pyqtgraph 即時波形顯示（20 Hz 刷新）
- Hall U/V/W 電壓波形（含閾值線）
- Encoder A/B 電壓波形（AI 電壓，含閾值線）
- **即時觀察面板（20 kHz/通道 連續串流）**：判斷一律以 **DI 數位訊號**為準，**AI 類比僅提供波形與電壓數值參考**（不做 H/L/X 準位判斷、不做 PASS/FAIL）
- **🆕 Hall 相序即時判斷（v1.9 新增，v1.12 擴充為 AI/DI 雙判斷）**：即時觀察面板底部**並列顯示 AI 與 DI 兩組**相序方向（✓ CW / ✓ CCW / ✗ Error）；**DI 相序**依數位讀取的 UVW 狀態、**AI 相序**依類比電壓經中點閾值編碼後判斷，兩者獨立運作互不干擾
- **🆕 Encoder 計數（DI）**：即時觀察的計數／方向／RPM 皆由 **DI** 正交解碼取得，AI 類比僅供波形觀察
- **倒數計時列**：顯示剩餘時間與進度條（檢測中）
- **即時統計面板**：PASS/FAIL 次數、成功率、平均 RPM（檢測中）
- 視窗高度固定 600px，波形圖滾輪縮放僅作用於 X 軸（時間軸）
- **監控預設關閉**：連線後不自動啟動 AI/DI 輪詢，需手動按「📡 監控開關」啟動

### 🔬 高取樣率診斷模式（v1.4 新增，v1.5 提升至 200 kS/s，v1.6 新增波形診斷分析，v1.7 新增比值交叉驗證）
- **獨立診斷模式**：另加「🔬 高取樣診斷」按鈕啟動（監控模式與診斷模式互斥）
- **逐通道高速採樣**：一次專注 1 個 AI 通道，以 **200,000 Hz**（硬體最高）連續採樣 **10 秒**
- **輪流掃描**：CH0（Hall U）→ CH1（Hall V）→ CH2（Hall W）→ CH3（Encoder A）→ CH4（Encoder B），跑滿 **2 輪**後自動結束
- **提早結束**：使用者可隨時按「⏹ 結束診斷」提早停止，已採資料仍會儲存
- **即時波形顯示**：診斷期間切換至全寬診斷視圖，每 0.1 秒（20,000 點）串流更新當前 CH 波形；自動 decimation 降採樣確保 UI 流暢
- **滾動視窗**：即時波形顯示最近 100,000 點（0.5 秒 @ 200kHz），含通道名稱、閾值線、倒數計時
- **資料儲存**：所有 CH × 輪次資料合併存成單一 `.npz` 檔案（`data/diagnostics/`）；每通道約 7.6 MB（float32），5CH × 2 輪壓縮後約 10~20 MB
- **🆕 高速波形診斷分析**：診斷完成後自動呼叫 `DiagAnalyzer` 對每通道高速波形做 H/L 比例、不定態比例、邊緣計數、頻率估算，輸出各通道與整體 PASS/FAIL
- **🆕 診斷結果顯示**：診斷完成對話框顯示各通道分析結果（H/L/X 比例、邊緣數、頻率、PASS/FAIL）
- **歷史記錄**：診斷場次寫入 DB（含 `diag_pass` 與各通道摘要 JSON），可在「📋 歷史記錄」中查看診斷 PASS/FAIL 與各通道結果，並以「🔬 回看診斷」按鈕回放波形
- **硬體上限自動偵測**：`enter_diag_mode()` 自動查詢 `AiFeatures.convertClockRange`，將取樣率 clamp 至硬體實際上限，避免超規導致 `prepare()` 失敗
- **🆕 Hall/Encoder 脈波比值交叉驗證**：每相 Hall（U/V/W）單獨與 Encoder 平均頻率做比值檢查，理論比值 = PPR / Hall週期/轉（例：512/90 ≈ 5.689），無論轉速多少比值應為常數；可偵測單相 Hall 掉脈波、Encoder 掉脈波、某相無訊號等異常
- **🆕 馬達規格可設定**：Hall 每轉週期數、Encoder 解析度（bits）、PPR、比值容差均可在「⚙ 參數設置」對話框調整，適應不同馬達規格

### 測試場次管理（v1.1 新增）
- 連線後**監控預設關閉**，操作員按「📡 監控開關」手動啟動 20 kHz/通道 即時觀察，確認訊號後再手動觸發檢測
- 每次檢測前可輸入**馬達序號**、操作員名稱，並設定量測參數（PPR、電壓閾值）
- 預設 **5 分鐘**計時，可調整（1~60 分鐘），支援提前停止
- 結果**自動儲存至 SQLite 資料庫**，不需手動操作
- 只記錄統計摘要（成功率、不合格率、RPM），不保留全部原始數據

### 資料庫與歷史查詢（v1.1 新增）
- SQLite 資料庫，預設路徑 `data/motor_test.db`，可在 UI 中變更
- 歷史查詢視窗：表格顯示所有場次，支援序號篩選、匯出 CSV、刪除記錄
- 全域統計摘要：總場次數、整體 PASS 率、平均成功率
- **場次類型區分**：📋 測試場次（灰色）與 🔬 診斷場次（藍色）分色顯示

### 報表輸出
- Excel (.xlsx) 格式：含摘要、Hall、Encoder 三個工作表（手動匯出）
- CSV 格式：Hall 與 Encoder 各一個檔案（手動匯出）
- 歷史記錄 CSV 匯出（從歷史查詢視窗）

---

## 硬體需求

| 項目 | 規格 |
|------|------|
| DAQ 裝置 | Advantech USB-4716 |
| Driver | DAQNavi（需另行下載安裝，詳見下方） |
| Hall Sensor | 3.3V 數位輸出，三相 (U/V/W) |
| Encoder | 5V 數位輸出，A/B 正交訊號 |

### 接線規劃

| 訊號 | AI 通道 | DI 通道 | 電壓系統 | AI 量程 |
|------|---------|---------|----------|---------|
| Hall U | AI Ch0 | DI0 | 3.3V | 0~5V |
| Hall V | AI Ch1 | DI1 | 3.3V | 0~5V |
| Hall W | AI Ch2 | DI2 | 3.3V | 0~5V |
| Encoder A | AI Ch3 | DI3 | 5V | 0~10V |
| Encoder B | AI Ch4 | DI4 | 5V | 0~10V |
| GND | AGND | DGND | 共地 | — |

> ⚠️ **注意**：USB-4716 DI 為 TTL 相容（VIH max = 5.5V），5V 訊號可直接接入。
>
> 🔌 **v1.8 起通道可調整**：上表為**預設**通道對應，實際使用的 AI/DI 通道、AI 量程、DI 埠號可在程式內「🔌 硬體通道」對話框自由設定，並存於 `config/channel_map.json`。詳見下方[硬體通道彈性設定](#硬體通道彈性設定v18-新增)章節。

---

## 軟體需求

- Python 3.8+
- Advantech DAQNavi SDK（需另行下載安裝）

---

## Driver 下載

使用本系統前，請先至 Advantech 官網下載並安裝 **DAQNavi Driver**：

| 項目 | 說明 |
|------|------|
| 下載頁面 | [Advantech DAQNavi Driver 下載](https://www.advantech.com/zh-tw/support/details/driver?id=1-1YPCECD) |
| 適用裝置 | USB-4716 及其他 Advantech DAQ 系列 |
| 安裝後路徑 | `C:\Program Files (x86)\Advantech\DAQNavi\` |

### 安裝步驟

1. 前往下載頁面：
   👉 https://www.advantech.com/zh-tw/support/details/driver?id=1-1YPCECD
2. 選擇對應作業系統版本（Windows）並下載安裝包
3. 執行安裝程式，依指示完成安裝
4. 安裝完成後，插入 USB-4716，確認裝置管理員中可正常識別

> ⚠️ **注意**：安裝 DAQNavi 後需重新啟動電腦，才能確保 Driver 正確載入。

---

## 安裝步驟

### Step 1：複製 DAQNavi Python SDK

從 DAQNavi 安裝目錄複製整個 `Automation` 資料夾到專案根目錄：

```powershell
Copy-Item -Path "C:\Advantech\DAQNavi\Examples\Python\Automation" `
          -Destination "C:\Users\830010\Documents\MPF\MPF-motor\Automation" -Recurse
```

複製後目錄結構應如下：

```
MPF-motor/
└── Automation/
    ├── __init__.py
    └── BDaq/
        ├── __init__.py
        ├── WaveformAiCtrl.py   ← AI 高速串流（本系統使用）
        ├── InstantDiCtrl.py    ← DI 即時讀取（本系統使用）
        └── ...
```

### Step 2：建立 Python 虛擬環境

```powershell
cd c:\Users\830010\Documents\MPF\MPF-motor
python -m venv venv
.\venv\Scripts\Activate.ps1
```

### Step 3：安裝相依套件

```powershell
pip install -r requirements.txt
```

### Step 4：驗證硬體連線

使用 Advantech **DAQNavi Device Test** 工具（開始選單可找到）確認：
- USB-4716 裝置可被識別
- AI Ch0~4 可讀取電壓
- DI Ch0~4 可讀取數位訊號

---

## 執行程式

```powershell
.\venv\Scripts\Activate.ps1
python main.py
```

> 💡 **模擬模式**：若未安裝 DAQNavi SDK 或未連接硬體，程式會自動進入模擬模式，使用模擬訊號進行測試（~100 Hz 輪詢）。

---

## 操作說明

### 標準測試流程

```
啟動程式
  ↓
自動連線 USB-4716（連線成功後監控預設關閉）
  ↓
按「📡 監控開關」啟動 20 kHz/通道 即時觀察（可選）
  ↓
觀察即時波形，確認訊號穩定
  ↓
點擊「▶ 開始檢測」→ 輸入馬達序號（可留空）、操作員、測試時長
  ↓
倒數計時（預設 5 分鐘）
  ├─ 時間到 → 自動停止並儲存
  └─ 點擊「⏹ 提前停止」→ 手動停止並儲存
  ↓
顯示結果摘要（Hall/Encoder 成功率、整體 PASS/FAIL）
  ↓
回到監控模式（繼續讀取，可進行下一次檢測）
```

### 按鈕說明

| 按鈕 | 說明 |
|------|------|
| **📡 監控開關** | 切換即時監控（AI WaveformAI 連續串流 20 kHz/通道 + DI 輪詢）開/關；連線後預設關閉 |
| **🏷 測試物件** | 開啟測試物件對話框，輸入馬達序號、操作員（記錄於診斷場次） |
| **⚙ 參數設置** | 開啟量測參數對話框，設定 Hall/Encoder 規格與電壓閾值；可存成馬達型號 profile 切換套用 |
| **🔬 高取樣診斷** | 啟動高取樣率診斷模式（暫停監控，逐 CH 200kHz 採樣，完成後自動分析 PASS/FAIL） |
| **⏹ 結束診斷** | 提早結束診斷，已採資料仍會儲存並分析 |
| **↺ 重置計數** | 重置 Encoder 計數器 |
| **💾 匯出報表** | 匯出最近一次場次的原始數據（Excel/CSV） |
| **📋 歷史記錄** | 開啟歷史查詢視窗，查看所有場次統計（含診斷 PASS/FAIL） |
| **🔌 硬體通道** | 開啟硬體通道設定對話框，調整 Hall/Encoder 的 AI/DI 通道、AI 量程、DI 埠號，設定後即時套用（診斷中禁用） |
| **🗄 DB 路徑** | 變更 SQLite 資料庫儲存路徑 |
| **🔌 重新連線** | 重新連線 USB-4716 |

### 「🏷 測試物件」對話框

點擊「🏷 測試物件」後彈出對話框，輸入本次測試物件資訊（與量測參數分離）：

- **馬達序號**：可留空
- **操作員**：可留空

> 序號與操作員會記錄於後續建立的診斷場次；再次開啟會自動帶入上次輸入的值。

### 「⚙ 參數設置」對話框（含馬達型號 Profile）

點擊「⚙ 參數設置」後彈出對話框，可設定量測參數並管理多組具名的「馬達型號 profile」，
讓不同馬達的設定可存檔重用，下次開啟自動載入上次套用的 profile，不需每次重設。

**馬達型號設定檔（Profile）**
- **套用設定（下拉選單）**：切換不同馬達的 profile，選取後欄位值即時帶入
- **💾 儲存**：將目前欄位值存回目前選取的 profile
- **➕ 另存新檔**：輸入新名稱，將目前欄位值另存成新的 profile
- **🗑 刪除**：刪除目前選取的 profile（至少保留一組）

**量測參數設定**
- **Hall 週期/轉**：Hall Sensor 每相每轉產生的 H-L 週期數（預設 90，依實際馬達規格修改）
- **Encoder 解析度**：Encoder 解析度位元數（預設 11 bits = 2048 counts/轉，自動帶出 PPR）
- **Encoder PPR**：每相每轉脈波數（預設 512 = 2^11 / 4，可手動覆蓋）
- **比值容差**：Hall/Encoder 脈波比值交叉驗證容差（預設 ±15%）
- **Hall VH_min / VL_max**：Hall Sensor 電壓閾值
- **Encoder VH_min / VL_max**：Encoder 電壓閾值

> 按「⚙ 套用參數」會立即生效，並將目前選取的 profile 記為預設載入項；
> 設定持久化於 `config/motor_profiles.json`，下次啟動自動載入 active profile。

**`config/motor_profiles.json` 結構**

```json
{
  "active_profile": "預設",
  "profiles": {
    "預設": {
      "hall_pulses_per_rev": 90,
      "hall_vh_min": 2.0,
      "hall_vl_max": 0.8,
      "resolution_bits": 11,
      "ppr": 512,
      "enc_vh_min": 3.5,
      "enc_vl_max": 1.5,
      "ratio_tolerance": 0.15
    }
  }
}
```

| 欄位 | 說明 |
|------|------|
| `active_profile` | 目前套用（下次啟動自動載入）的 profile 名稱 |
| `profiles.<名稱>` | 具名的馬達型號量測參數；可有多組，供不同馬達切換套用 |

> **相容性**：檔案不存在時自動產生預設檔；載入時缺漏欄位自動以預設值補齊，`active_profile` 不存在則退回第一組 profile。

### 高取樣率診斷流程

```
點擊「🔬 高取樣診斷」
  ↓
確認對話框（顯示通道數、取樣率、預計時長）
  ↓
暫停即時監控（若有開啟）→ 切換至診斷視圖（全寬波形圖）
  ↓
逐通道採樣（CH0 Hall U → CH1 Hall V → CH2 Hall W → CH3 Enc A → CH4 Enc B）
  │  每 CH 10 秒 × 200,000 Hz，每 0.1 秒串流 20,000 點至即時波形圖（自動 decimation）
  │  進度列顯示：當前通道名稱、第幾輪、倒數計時、整體進度條
  ├─ 使用者按「⏹ 結束診斷」→ 提早停止，已採資料仍儲存
  └─ 跑完 2 輪 → 自動結束
  ↓
合併所有 CH × 輪次資料 → 存成單一 .npz（data/diagnostics/diag_YYYYMMDD_HHMMSS.npz）
  ↓
DiagAnalyzer 分析各通道高速波形（H/L 比例、不定態比例、邊緣計數、頻率估算）
  ↓
計算各通道與整體 PASS/FAIL → 寫入 DB（diag_pass、diag_ch_results）
  ↓
顯示診斷結果對話框（各通道分析數據與 PASS/FAIL）
  ↓
監控維持關閉（需手動按「📡 監控開關」重新啟動）
```

### 診斷波形回放

1. 點擊「📋 歷史記錄」開啟歷史查詢視窗
2. 選取一筆 🔬 診斷場次（藍色標示）
3. 點擊「🔬 回看診斷」按鈕
4. 在回放對話框中：
   - 左側選擇要查看的**通道**（Hall U/V/W、Encoder A/B）
   - 左側選擇要查看的**輪次**（第 1 輪 / 第 2 輪）
   - 右側顯示完整 10 秒波形（含閾值線）
   - 使用滑桿、播放/暫停、步進按鈕瀏覽波形

### 歷史查詢視窗

1. 點擊「📋 歷史記錄」開啟
2. 可依序號關鍵字篩選
3. 點選任一列查看詳細資訊
4. 「💾 匯出 CSV」匯出目前顯示的所有記錄
5. 「🗑 刪除選取」刪除選取的場次記錄
6. 場次類型欄位：📋 測試（灰色）/ 🔬 診斷（藍色）
7. 診斷場次「整體結果」欄顯示高速診斷 PASS/FAIL（✔ PASS 綠色 / ✘ FAIL 紅色 / — 未分析）
8. 點選診斷場次可在詳細資訊框查看各通道分析結果（H/L/X 比例、邊緣數、頻率）

---

## 專案結構

```
MPF-motor/
├── main.py                        # 程式進入點
├── requirements.txt               # Python 相依套件
├── README.md                      # 本文件
│
├── Automation/                    # DAQNavi Python SDK（需手動複製）
│   └── BDaq/
│       ├── WaveformAiCtrl.py      # AI 高速串流控制器（本系統使用）
│       ├── InstantDiCtrl.py       # DI 即時讀取控制器（本系統使用）
│       └── ...
│
├── data/                          # 資料庫儲存目錄（自動建立）
│   ├── motor_test.db              # SQLite 測試記錄資料庫
│   └── diagnostics/               # 高取樣診斷 npz 儲存目錄（v1.4 新增）
│       └── diag_YYYYMMDD_HHMMSS.npz
│
├── config/
│   ├── __init__.py
│   ├── thresholds.py              # 電壓閾值、取樣設定、資料庫路徑、診斷設定（動態套用通道對應）
│   ├── channel_config.py          # 硬體通道對應中央設定（JSON 載入/儲存 + ValueRange 轉換）（v1.8 新增）
│   ├── channel_map.json           # 使用者通道對應設定檔（自動建立/持久化）（v1.8 新增）
│   ├── motor_profiles.py          # 馬達型號量測參數 profile 管理（JSON 多組具名設定，持久化）
│   └── motor_profiles.json        # 使用者馬達型號量測參數設定檔（自動建立/持久化）
│
├── daq/
│   ├── __init__.py
│   ├── daq_controller.py          # USB-4716 裝置控制器（含診斷模式切換）
│   ├── ai_reader.py               # 類比輸入讀取（WaveformAI 多通道連續串流 20kHz/通道，監控用，預設關閉）
│   └── di_reader.py               # 數位輸入讀取（H/L + Encoder 軟體計數）
│
├── db/                            # 資料庫模組（v1.1 新增）
│   ├── __init__.py
│   └── database.py                # SQLite CRUD 封裝（含診斷場次支援）
│
├── logic/
│   ├── __init__.py
│   ├── hall_analyzer.py           # Hall Sensor 分析邏輯 + HallSequenceDetector 相序判斷（v1.9）
│   ├── encoder_analyzer.py        # Encoder 分析邏輯（保留供參考）
│   ├── diag_analyzer.py           # 高速波形診斷分析器（v1.6 新增）
│   ├── test_session.py            # 測試場次管理 + 統計計算（v1.1 新增）
│   └── diagnostic_scanner.py      # 高取樣率診斷掃描器（v1.4 新增）
│
├── ui/
│   ├── __init__.py
│   ├── main_window.py             # PyQt5 主視窗（含診斷模式）
│   ├── waveform_widget.py         # pyqtgraph 即時波形元件（監控模式）
│   ├── diagnostic_widget.py       # 高取樣率即時波形元件（v1.4 新增）
│   ├── diagnostic_replay_dialog.py # 診斷波形回放對話框（v1.4 新增）
│   ├── result_panel.py            # 即時觀察面板（Hall 相序 AI/DI 雙判斷並列顯示、計數以 DI 為準，無 PASS/FAIL）
│   ├── session_dialog.py          # 量測參數設置對話框（含馬達型號 profile 管理）
│   ├── object_info_dialog.py      # 測試物件資訊對話框（馬達序號 / 操作員）
│   ├── channel_config_dialog.py   # 硬體通道設定對話框（v1.8 新增）
│   └── history_viewer.py          # 歷史查詢視窗（含診斷場次識別）
│
└── report/
    ├── __init__.py
    └── report_generator.py        # CSV/Excel 報表生成
```

---

## 高取樣率診斷架構（v1.4 新增，v1.5 提升至 200 kS/s）

### 設計動機

早期監控模式使用 `InstantAiCtrl` 同時輪詢 5 個 AI 通道，實際每通道取樣率約 100 Hz，不足以捕捉 Hall Sensor 與 Encoder 的高頻細節。**v1.9 起監控模式改用 `WaveformAiCtrl` 多通道硬體連續串流，每通道實際 20,000 Hz**。診斷模式則使用 `WaveformAiCtrl` 單通道高速採樣，達到硬體最高 **200,000 Hz**（USB-4716 單通道上限）。

### 硬體互斥設計

`WaveformAiCtrl`（診斷）與 `InstantAiCtrl`（監控）不能同時佔用 USB-4716，因此：

```
監控模式（InstantAiCtrl）
  ↓ 使用者按「🔬 高取樣診斷」
enter_diag_mode()：釋放 InstantAiCtrl → 建立 WaveformAiCtrl
  ↓ 診斷完成或提早停止
exit_diag_mode()：釋放 WaveformAiCtrl → 重建 InstantAiCtrl
  ↓
恢復監控模式
```

### 診斷資料流

```
WaveformAiCtrl（單通道，200,000 Hz）
  │  sectionLength=20000, sectionCount=8
  │  每 0.1 秒（20,000 點）觸發一次讀取
  │  環形緩衝深度 = 8 × 20,000 = 160,000 點（0.8s），防 overrun
  ↓
DiagnosticScanner._scan_channel_hw()
  │  clamp_clock_rate() 自動 clamp 至硬體上限
  │  chunk_callback(ch_idx, round_idx, chunk_20000pts, elapsed_s)
  ↓ pyqtSignal（跨執行緒安全）
MainWindow._on_diag_chunk()（主執行緒）
  │
  ↓
DiagnosticWidget.append_chunk()
  │  deque 滾動緩衝（最近 100,000 點 = 0.5s）
  │  自動 decimation：超過 5,000 點時等間距抽稀再繪圖
  ↓
pyqtgraph 即時波形更新（每 0.1 秒，繪圖點數 ≤ 5,000）
```

### 診斷 npz 格式

```python
# 儲存路徑：data/diagnostics/diag_YYYYMMDD_HHMMSS.npz
# 資料量：200,000 Hz × 10s × 5CH × 2輪 ≈ 76 MB（壓縮後約 10~20 MB）
{
    "ch0_round0": np.ndarray(float32, shape=(2000000,)),  # CH0 第1輪 10秒資料（200kHz × 10s）
    "ch1_round0": np.ndarray(float32, shape=(2000000,)),  # CH1 第1輪
    ...
    "ch4_round1": np.ndarray(float32, shape=(2000000,)),  # CH4 第2輪
    "sample_rate":    np.array([200000], dtype=int32),    # 200 kS/s
    "seconds_per_ch": np.array([10],    dtype=int32),
    "rounds":         np.array([2],     dtype=int32),
    "ch_count":       np.array([5],     dtype=int32),
    "channel_names":  np.array(["Hall U", "Hall V", "Hall W", "Encoder A", "Encoder B"]),
    "channel_nums":   np.array([0, 1, 2, 3, 4], dtype=int32),
    "diag_type":      np.array(["sequential_ch"]),  # 識別標記

    # ── v1.7 新增：馬達規格參數（供回放分析時還原比值交叉驗證設定）────────────
    "hall_pulses_per_rev": np.array([90],   dtype=int32),   # Hall 每相每轉週期數
    "ppr":                 np.array([512],  dtype=int32),   # Encoder 每相每轉脈波數
    "resolution_bits":     np.array([11],   dtype=int32),   # Encoder 解析度位元數
    "ratio_tolerance":     np.array([0.15], dtype=float32), # 比值容差（±15%）
}
```

> **舊格式相容性**：不含上述 v1.7 新增欄位的舊 npz 檔案，回放分析時會自動 fallback 至 `config/thresholds.py` 的當前預設值。

### 診斷設定（`config/thresholds.py`）

| 參數 | 值 | 說明 |
|------|--------|------|
| `HW_MAX_SAMPLE_RATE` | **200,000 Hz** | 硬體最高取樣率常數（USB-4716 單通道上限） |
| `sample_rate` | **200,000 Hz** | 每通道取樣率（診斷模式，WaveformAiCtrl 單通道） |
| `seconds_per_ch` | 10 秒 | 每個通道採樣秒數（每通道 2,000,000 點） |
| `rounds` | 2 | 總輪數 |
| `chunk_size` | **20,000 點** | 每次串流讀取點數（0.1 秒/段 @ 200kHz） |
| `section_count` | **8** | WaveformAI 環形緩衝 section 數（總緩衝 0.8s，防 overrun） |
| `display_window` | **100,000 點** | 即時波形顯示視窗點數（最近 0.5 秒 @ 200kHz） |
| `diag_dir` | `data/diagnostics` | npz 儲存目錄 |

**診斷分析參數（`DIAGNOSTIC["analysis"]`）**

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `hl_ratio_min` | 0.05 | H 準位樣本比例下限（低於此值視為訊號異常） |
| `hl_ratio_max` | 0.95 | H 準位樣本比例上限（高於此值視為訊號異常） |
| `undefined_ratio_max` | 0.20 | 不定態樣本比例上限（超過 20% 視為 FAIL） |
| `min_edges_hall` | 10 | Hall 通道最少邊緣數（10 秒內） |
| `min_edges_encoder` | 20 | Encoder 通道最少邊緣數（10 秒內） |
| `round_freq_diff_max` | 0.20 | 輪次間頻率差異上限（比例） |
| `enable_ratio_check` | `True` | 是否啟用 Hall/Encoder 比值交叉驗證 |
| `ratio_tolerance` | **0.15** | 比值容差（±15%），超出則 FAIL |

**馬達規格參數（可在「⚙ 參數設置」對話框調整）**

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `HALL_THRESHOLDS["hall_pulses_per_rev"]` | **90** | Hall Sensor 每相每轉 H-L 週期數 |
| `ENCODER_THRESHOLDS["resolution_bits"]` | **11** | Encoder 解析度位元數（11 bits = 2048 counts/轉） |
| `ENCODER_THRESHOLDS["ppr"]` | **512** | Encoder 每相每轉脈波數（= 2^11 / 4，四倍頻正交解碼） |

---

## Hall/Encoder 脈波比值交叉驗證（v1.7 新增）

### 設計原理

Hall Sensor 與 Encoder 安裝在同一轉軸上，因此兩者的脈波頻率比值為固定常數，**與轉速無關**：

```
理論比值 = Encoder PPR / Hall 每轉週期數
         = 512 / 90
         ≈ 5.689
```

無論馬達轉速多少，實測的 `f_encoder / f_hall_相` 都應落在理論比值 ±容差內。

### 異常偵測邏輯

| 現象 | 實測比值 | 判斷 |
|------|----------|------|
| 某相 Hall 掉脈波（頻率偏低） | **偏高**（> 理論 × (1+容差)） | ✘ FAIL：Hall X相 可能掉脈波 |
| Encoder 掉脈波（頻率偏低） | **偏低**（< 理論 × (1-容差)） | ✘ FAIL：Encoder 可能掉脈波 |
| 某相 Hall 無訊號（頻率 = 0） | 無法計算（除以零） | ✘ FAIL：Hall X相 頻率為 0 |
| Encoder 無訊號（頻率 = 0） | 0 | ✘ FAIL：Encoder 頻率為 0 |
| 正常 | 落在 [理論×(1-容差), 理論×(1+容差)] | ✔ PASS |

### 每相獨立驗證

每一相 Hall（U/V/W）都**單獨**與 Encoder 平均頻率（A/B 兩通道平均）做比值檢查，可精確定位到哪一相異常：

```
Hall U 頻率 vs Encoder 平均頻率 → 比值 → PASS/FAIL
Hall V 頻率 vs Encoder 平均頻率 → 比值 → PASS/FAIL
Hall W 頻率 vs Encoder 平均頻率 → 比值 → PASS/FAIL
```

### 計算範例

```
馬達規格：Hall 90 週期/轉，Encoder 11 bits（PPR = 512）
理論比值 = 512 / 90 = 5.689
容差 ±15%：允許範圍 [4.836, 6.542]

轉速 60 RPM（1 rps）：
  Hall U 頻率 = 90 × 1 = 90 Hz
  Encoder 頻率 = 512 × 1 = 512 Hz
  實測比值 = 512 / 90 = 5.689 → PASS ✔

轉速 300 RPM（5 rps）：
  Hall U 頻率 = 90 × 5 = 450 Hz
  Encoder 頻率 = 512 × 5 = 2560 Hz
  實測比值 = 2560 / 450 = 5.689 → PASS ✔（比值不隨轉速改變）

Hall V 掉脈波（頻率只有正常的 50%）：
  Hall V 頻率 = 45 Hz（異常）
  Encoder 頻率 = 512 Hz（正常）
  實測比值 = 512 / 45 = 11.378 → 超出上限 6.542 → FAIL ✘
  提示：Hall V 可能掉脈波（比值偏高）
```

### 參數設定

在「⚙ 參數設置」對話框可調整以下參數（適應不同馬達）：

| 參數 | 說明 | 預設值 |
|------|------|--------|
| **Hall 週期/轉** | Hall Sensor 每相每轉 H-L 週期數 | 90 |
| **Encoder 解析度** | Encoder 解析度位元數（自動帶出 PPR） | 11 bits |
| **Encoder PPR** | 每相每轉脈波數（= 2^bits / 4） | 512 |
| **比值容差** | 允許偏差比例（±%） | 0.15（±15%） |

> 💡 **提示**：對話框中的「理論比值」標籤會即時顯示當前設定的理論比值與允許範圍，方便確認設定是否正確。

### 模擬模式相容性

模擬模式下，`DiagnosticScanner._generate_sim_chunk()` 會從 `HALL_THRESHOLDS["hall_pulses_per_rev"]` 與 `ENCODER_THRESHOLDS["ppr"]` 動態計算模擬頻率，確保模擬比值與理論比值一致，避免模擬模式恆為 FAIL：

```python
sim_rps = 1.0  # 模擬轉速（1 rps = 60 RPM）
hall_base_freq = hall_pulses_per_rev × sim_rps  # 例：90 Hz
enc_base_freq  = enc_ppr × sim_rps              # 例：512 Hz
# 比值 = 512 / 90 ≈ 5.689（與理論比值一致）
```

---

## 硬體通道彈性設定（v1.8 新增）

### 設計動機

早期版本將 Hall（U/V/W）與 Encoder（A/B）對應的 AI/DI 通道寫死於 `ai_reader.py`、`di_reader.py`、`thresholds.py`、`diagnostic_scanner.py` 等多個檔案中（固定 AI0~4、DI0~4）。不同硬體佈線或需避開故障通道時，必須修改多處程式碼。v1.8 將通道對應集中管理，並提供 UI 對話框即時調整。

### 架構

```
config/channel_map.json（使用者設定檔，持久化）
  ↓ 載入 / 儲存
config/channel_config.py：CHANNEL_CONFIG 單例
  │  DEFAULT_CHANNEL_MAP 預設值 + _merge_defaults() 補齊缺漏欄位
  │  查詢方法：hall_ai/hall_di/encoder_ai/encoder_di、value_range(kind)、y_range(kind)、di_port() …
  ↓ 供各模組查詢
config/thresholds.py    → HALL/ENCODER_THRESHOLDS、AI_RANGE、DIAGNOSTIC["channels"] 動態帶入
daq/ai_reader.py        → 動態 AI 通道 + refresh_channels()（min~max 範圍讀取，欄位索引取值）
daq/di_reader.py        → 動態 DI 通道 + refresh_channels()
logic/diagnostic_scanner.py → 依 kind（hall/encoder）決定 value_range 與模擬相位
daq/daq_controller.py   → 模擬 DI 依動態通道產生位元
```

### 設定檔格式（`config/channel_map.json`）

```json
{
  "hall": {
    "U": { "ai": 0, "di": 0 },
    "V": { "ai": 1, "di": 1 },
    "W": { "ai": 2, "di": 2 }
  },
  "encoder": {
    "A": { "ai": 3, "di": 3 },
    "B": { "ai": 4, "di": 4 }
  },
  "value_range": { "hall": "V_0To5", "encoder": "V_0To10" },
  "y_range": { "hall": [-0.2, 3.8], "encoder": [-0.5, 6.0] },
  "di_port": 0
}
```

| 欄位 | 說明 |
|------|------|
| `hall.U/V/W.ai` `hall.U/V/W.di` | 三相 Hall 各自的 AI、DI 通道號 |
| `encoder.A/B.ai` `encoder.A/B.di` | Encoder A/B 相各自的 AI、DI 通道號 |
| `value_range.hall` `value_range.encoder` | AI 量程（DAQNavi `ValueRange` 名稱，如 `V_0To5`、`V_0To10`） |
| `y_range.hall` `y_range.encoder` | 波形圖 Y 軸顯示範圍 `[min, max]` |
| `di_port` | DI 讀取的埠號 |

### 「🔌 硬體通道」對話框

1. 點擊主畫面「🔌 硬體通道」按鈕開啟對話框（**診斷進行中禁止開啟**）
2. 為 Hall U/V/W 與 Encoder A/B 分別設定 **AI 通道**（0~15）與 **DI 通道**（0~7）
3. 選擇 Hall / Encoder 的 **AI 量程**（`V_0To5`、`V_0To10`、`V_Neg5To5`、`V_Neg10To10`、`V_0To2point5`、`V_Neg2point5To2point5`）
4. 設定 **DI 埠號**
5. 按鈕：
   - **恢復預設**：還原為 `DEFAULT_CHANNEL_MAP`（AI0~4、DI0~4）
   - **套用**：驗證 AI、DI 通道皆無重複後套用並存檔
   - **取消**：放棄變更
6. 套用後主程式依序執行：
   ```python
   CHANNEL_CONFIG.set_map(new_map, save=True)  # 更新單例並寫入 JSON
   refresh_channel_map()                        # 同步 thresholds 各字典
   self._ai_reader.refresh_channels()           # 熱重載 AI 讀取器
   self._di_reader.refresh_channels()           # 熱重載 DI 讀取器
   ```

### 熱重載機制

`AIReader` / `DIReader` 的 `refresh_channels()` 採「停止 → 重建通道狀態 → 若原本執行中則重新啟動」流程，套用新通道時若監控正在執行也能無縫切換。`thresholds.refresh_channel_map()` 以 in-place 方式更新（`DIAGNOSTIC["channels"][:] = ...`）以保留既有物件參照。

### 非連續通道讀取

使用者可設定任意（甚至非連續）AI 通道，例如 AI 5/6/7/8/9。`AIReader._instant_ai_loop()` 以 `readDataF64(min, max-min+1)` 讀取涵蓋範圍，再以 `col = ch - read_start` 由回傳陣列取出所需通道，兼顧彈性與效率。

### 向後相容

`diagnostic_scanner._build_channel_list()` 對不含 `kind` 欄位的舊通道定義，會依名稱（`Hall*` → hall，其餘 → encoder）自動推斷，確保舊資料與設定仍可運作。

---

## Hall 相序即時判斷（v1.9 新增）

### 設計原理

三相 Hall Sensor（U/V/W）在馬達旋轉時會依固定順序切換 H/L 狀態，將 UVW 三個數位狀態編碼為二進制整數即可判斷旋轉方向：

```
狀態編碼 = U×2^0 + V×2^1 + W×2^2
（U = bit0，V = bit1，W = bit2）
```

正常旋轉時，狀態值會依固定序列循環（不會出現 0=000 或 7=111 的全同狀態）：

| 方向 | 狀態循環序列 |
|------|--------------|
| **CW（順時針）** | 5 → 1 → 3 → 2 → 6 → 4 →（回）→ 5 |
| **CCW（逆時針）** | 4 → 6 → 2 → 3 → 1 → 5 →（回）→ 4 |

### 狀態對照表

| 狀態值 | 二進制 (WVU) | W | V | U |
|:---:|:---:|:---:|:---:|:---:|
| 5 | 101 | 1 | 0 | 1 |
| 1 | 001 | 0 | 0 | 1 |
| 3 | 011 | 0 | 1 | 1 |
| 2 | 010 | 0 | 1 | 0 |
| 6 | 110 | 1 | 1 | 0 |
| 4 | 100 | 1 | 0 | 0 |

### 判斷邏輯（`HallSequenceDetector`）

`logic/hall_analyzer.py` 新增 `HallSequenceDetector` 類別，於即時監控每次更新時記錄狀態變化：

1. 將最新 UVW 編碼為狀態值，**忽略無效狀態**（0=000、7=111）與**未變化狀態**
2. 以 deque 保留最近 **6 個不同狀態**（一個完整電氣週期）
3. 比對相鄰狀態跳轉是否全部符合 CW 或 CCW 合法轉換表：

| 判斷結果 | 顯示 | 條件 |
|----------|------|------|
| **CW** | ✓ CW（綠色）| 所有相鄰跳轉皆符合 CW 轉換表 |
| **CCW** | ✓ CCW（藍色）| 所有相鄰跳轉皆符合 CCW 轉換表 |
| **Error** | ✗ Error（紅色）| 出現不合法跳轉或方向混合（如接線錯誤、掉脈波、相序反接） |
| **---** | ---（灰色）| 有效狀態變化不足（< 2 次跳轉，無法判斷） |

### 顯示位置

相序判斷結果顯示於**即時觀察面板 Hall 區塊底部**（獨立於電壓數值表格），以大字標籤即時更新，並**並列顯示 AI 與 DI 兩組**判斷結果（v1.12）：

- **DI 相序**：以 **DI 數位訊號**讀取的 UVW 狀態直接判斷。
- **AI 相序**：以 **AI 類比電壓**經中點閾值 `midpoint = (vh_min + vl_max) / 2`（3.3V 系統為 1.4V）編碼為布林（`v ≥ midpoint → H`）後判斷，使用中點門檻可避免電壓落在未定義區導致相序卡住。

AI 與 DI 各自持有獨立的 `HallSequenceDetector` 實例，狀態歷程互不干擾。此判斷僅供監控觀察，不影響高取樣診斷的 PASS/FAIL。

### 資料流

```
DIReader.get_hall_states() → {"U": bool, "V": bool, "W": bool}
  ↓
HallSequenceDetector.update(u, v, w)
  │  編碼 state → 記錄狀態變化 → 比對 CW/CCW 轉換表
  ↓ 回傳 "CW" / "CCW" / "Error" / "---"
MainWindow._update_analysis()
  ↓
ResultPanel.update_live_voltages(hall_seq=...)
  ↓
HallLivePanel 底部相序標籤（即時更新）
```

---

## AI 取樣架構

### 即時監控模式（WaveformAiCtrl 多通道連續串流，v1.9 提升至 20 kHz/通道）

即時監控自 v1.9 起改用 `WaveformAiCtrl` **多通道硬體 DMA 連續串流**，每個通道實際以
**20,000 Hz** 硬體採樣（不再是 `InstantAiCtrl` 逐次輪詢的 ~100 Hz）。
`config/thresholds.py` 中 `SAMPLING["ai_sample_rate"]` = **20,000 Hz**（每通道真實硬體取樣率）。

多通道採樣時，`conversion.clockRate` 為**每通道**取樣率，硬體總取樣率 =
`ai_sample_rate × 通道數`（5 CH × 20 kHz = 100 kS/s），仍在 USB-4716 總頻寬
（`HW_MAX_SAMPLE_RATE` = 200 kS/s）之內。`getDataF64` 取回**交錯（interleaved）**資料，
背景執行緒依 `channelCount` 解交錯（reshape）後分配至各通道 deque。

> ⚠️ **注意**：監控模式連線後**預設關閉**，需手動按「📡 監控開關」啟動。監控僅用於初步觀察，不做 PASS/FAIL 判斷。

```
USB-4716 硬體 ADC（多通道掃描）
  │  每通道 20,000 Hz（conversion.clockRate；channelStart~channelCount 涵蓋所有 AI 通道）
  ↓ DMA
硬體環形緩衝區（sectionLength=2000 × sectionCount=0 無限循環）
  │  每累積 2,000 點/通道觸發一次讀取（約每 100ms）
  ↓
AIReader._waveform_ai_loop() → getDataF64(chunk×通道數) → reshape 解交錯
  │  各通道存入 deque 滾動緩衝（20,000 點/通道 = 1 秒）
  ↓
UI callback → 波形顯示（20 Hz 刷新，自動 decimation ≤ 4,000 點）+ 即時觀察面板（AI 電壓數值供參考；相序/計數以 DI 為準）
```

### 診斷模式（WaveformAiCtrl 單通道高速串流，v1.5 提升至 200 kS/s）

診斷模式改用 `WaveformAiCtrl` 單通道高速採樣，達到硬體最高 200,000 Hz：

```
USB-4716 硬體 ADC
  │  200,000 Hz/通道（單通道，WaveformAiCtrl）
  ↓ DMA
硬體環形緩衝區（sectionLength=20000 × sectionCount=8 = 160,000 點 = 0.8s）
  │  每累積 20,000 點觸發一次讀取（約每 100ms）
  ↓
DiagnosticScanner.getDataF64(20000, timeout_ms=500)
  │  chunk_callback → UI 即時繪圖（自動 decimation）
  ↓
npz 儲存（每通道 2,000,000 點 ≈ 7.6 MB float32）
```

### 效能對比

| 項目 | 即時監控（WaveformAI，v1.9） | 診斷模式（WaveformAI，v1.5） |
|------|----------------------|----------------------|
| AI 取樣架構 | 硬體 DMA 串流（多通道掃描） | 硬體 DMA 串流（單通道） |
| 實際 AI 取樣率 | **20,000 Hz/通道** | **200,000 Hz/通道** |
| 標示取樣率 | **20,000 Hz/通道**（真實硬體） | **200,000 Hz** |
| 預設啟動 | **關閉**（手動按鈕啟動） | 按「🔬 高取樣診斷」啟動 |
| PASS/FAIL 判斷 | **無**（僅顯示電壓/準位） | **有**（DiagAnalyzer 分析） |
| GUI 刷新率 | 20 Hz | **10 Hz（每 0.1s 一段）** |
| 波形緩衝點數 | 20,000 點/通道（1 秒） | **100,000 點（0.5 秒）** |
| 繪圖降採樣 | **自動 decimation（≤ 4,000 點）** | **自動 decimation（≤ 5,000 點）** |
| 硬體緩衝深度 | 16,000 點/通道（0.8s） | **160,000 點（0.8s），防 overrun** |

### 取樣參數設定（`config/thresholds.py`）

| 參數 | 值 | 說明 |
|------|--------|------|
| `HW_MAX_SAMPLE_RATE` | **200,000 Hz** | 硬體最高取樣率（USB-4716 單通道上限；多通道時為總頻寬共享） |
| `ai_sample_rate` | **20,000 Hz** | 監控每通道真實硬體取樣率（WaveformAI 多通道連續串流） |
| `monitor_chunk_size` | **2,000** | 監控串流每通道分段讀取點數（0.1s @ 20kHz，維持 10 Hz 回呼） |
| `buffer_size` | **20,000** | 監控波形顯示緩衝點數（20kHz × 1s = 20,000 點/通道） |
| `display_max_points` | **4,000** | 監控繪圖降採樣上限（超過則自動 decimation） |
| `section_length` | **2,000** | 監控 WaveformAI 每 section 樣本數（與 chunk 對齊）／診斷模式為 20,000 |
| `section_count` | **8** | 診斷模式環形緩衝 section 數（總緩衝 0.8s） |
| `display_update_ms` | 50 ms | GUI 刷新間隔（20 Hz） |

---

## 電壓判斷邏輯

### Hall Sensor（3.3V 系統）

| 量測電壓 | 判斷結果 | 測試 |
|----------|----------|------|
| V > 2.0V | H（高準位）| PASS |
| V < 0.8V | L（低準位）| PASS |
| 0.8V ≤ V ≤ 2.0V | X（不定態）| FAIL |

### Encoder（5V 系統）

| 量測電壓 | 判斷結果 | 測試 |
|----------|----------|------|
| V > 3.5V | H（高準位）| PASS |
| V < 1.5V | L（低準位）| PASS |
| 1.5V ≤ V ≤ 3.5V | X（不定態）| FAIL |

### 一致性驗證

AI 電壓判斷結果必須與 DI 讀取結果一致，否則判定 FAIL。

---

## 軟體計數限制

USB-4716 **無硬體計數器**，Encoder 使用 Python 軟體輪詢計數（DI 通道）。

| 參數 | 說明 |
|------|------|
| 輪詢間隔 | 0.1 ms（約 10 kHz） |
| 可靠最高頻率 | ~1~5 kHz（依系統負載） |
| 建議最高轉速 | 300 RPM @ 1000 PPR |

> 💡 AI 電壓波形已改用 WaveformAI 硬體連續串流（監控 20 kHz/通道、診斷 200 kHz/通道），不受此限制影響。
> 若需更高轉速量測，建議降低 Encoder PPR 或改用具硬體計數器的 DAQ 模組（如 USB-4751）。

---

## 常見問題

**Q: 程式啟動後顯示「連線失敗」**
- 確認 USB-4716 已插入並被 Windows 識別
- 確認 DAQNavi driver 已正確安裝
- 嘗試點擊「🔌 重新連線」按鈕

**Q: 程式進入模擬模式**
- 確認 `Automation/` 資料夾已複製到專案根目錄
- 確認 DAQNavi 安裝路徑正確（預設 `C:\Advantech\DAQNavi\`）

**Q: WaveformAI 啟動失敗（錯誤碼 0xXXXX）**
- 確認 USB-4716 韌體版本支援 WaveformAI（需 DAQNavi 3.x 以上）
- 確認 `section_length × section_count` 不超過裝置硬體緩衝上限
- 系統會自動查詢 `AiFeatures.convertClockRange` 並 clamp 取樣率，通常不需手動調整
- 若仍失敗，可嘗試降低 `DIAGNOSTIC["sample_rate"]`（如改為 100000）或減少 `section_count`

**Q: Encoder RPM 讀值不穩定**
- DI 軟體計數受系統負載影響，屬正常現象
- 可降低 `di_poll_interval`（如改為 0.0005）以減少 CPU 負載
- AI 電壓波形不受影響（已使用硬體串流）

**Q: 波形顯示卡頓**
- 可增大 `display_update_ms`（如改為 100）降低 GUI 刷新頻率
- 可減少 `buffer_size`（如改為 5000）降低每次繪圖的資料量

---

## 資料庫結構

SQLite 資料庫（`data/motor_test.db`）包含兩張資料表：

### `test_sessions`（測試場次）

| 欄位 | 型別 | 說明 |
|------|------|------|
| id | INTEGER | 自動遞增主鍵 |
| serial_no | TEXT | 馬達序號（可空白） |
| operator | TEXT | 操作員名稱（可空白） |
| started_at | TEXT | 開始時間（ISO 8601） |
| ended_at | TEXT | 結束時間 |
| duration_s | REAL | 實際測試秒數 |
| waveform_path | TEXT | npz 波形檔案路徑（FAIL 波形或診斷 npz） |
| notes | TEXT | 備註 |
| **session_type** | TEXT | **場次類型：`'test'`（一般檢測）或 `'diagnostic'`（高取樣診斷）** |
| **diag_pass** | INTEGER | **診斷判定結果（1=PASS, 0=FAIL, -1=未分析）；僅診斷場次有效** |
| **diag_ch_results** | TEXT | **各通道分析摘要（JSON 字串）；僅診斷場次有效** |

### `test_results`（統計結果）

| 欄位 | 型別 | 說明 |
|------|------|------|
| session_id | INTEGER | 對應場次 ID |
| hall_total | INTEGER | Hall 總採樣次數 |
| hall_pass | INTEGER | Hall PASS 次數 |
| hall_fail | INTEGER | Hall FAIL 次數 |
| hall_pass_rate | REAL | Hall 成功率（0.0~1.0） |
| enc_total | INTEGER | Encoder 總採樣次數 |
| enc_pass | INTEGER | Encoder PASS 次數 |
| enc_fail | INTEGER | Encoder FAIL 次數 |
| enc_pass_rate | REAL | Encoder 成功率（0.0~1.0） |
| avg_rpm | REAL | 平均轉速（RPM） |
| max_rpm | REAL | 最高轉速（RPM） |
| min_rpm | REAL | 最低轉速（RPM） |
| overall_pass | INTEGER | 整體判定（1=PASS, 0=FAIL） |

> **整體 PASS 條件**：Hall 成功率 ≥ 95% **且** Encoder 成功率 ≥ 95%

---

## 版本記錄

| 版本 | 日期 | 說明 |
|------|------|------|
| 1.0.0 | 2026-08-14 | 初始版本 |
| 1.1.0 | 2026-08-21 | 新增測試場次管理、SQLite 資料庫、歷史查詢視窗；流程改為連線後立即監控，手動觸發 5 分鐘計時檢測 |
| 1.2.0 | 2026-08-21 | AI 讀取改用 WaveformAiCtrl 硬體串流（10 kHz/通道）；AI 量程改為單極性（Hall 0~5V、Encoder 0~10V）；GUI 刷新率提升至 20 Hz；波形緩衝擴大至 10,000 點 |
| 1.3.0 | 2026-08-25 | 視窗高度限制 600px；移除 Encoder DI 數位波形子圖（只保留 Hall AI + Encoder AI 兩個子圖）；量測參數設定（PPR、電壓閾值）移至「開始檢測」對話框；波形滾輪縮放改為僅縮放 X 軸 |
| 1.4.0 | 2026-08-27 | 新增高取樣率診斷模式：逐 CH 10kHz 採樣（10s/CH × 2 輪）、即時波形顯示、npz 存檔、DB 診斷場次記錄、歷史回放對話框；DB 新增 `session_type` 欄位區分診斷/測試場次 |
| **1.5.0** | **2026-08-27** | **診斷模式取樣率提升至硬體最高 200 kS/s**：`sample_rate` 200,000 Hz、`chunk_size` 20,000 點、`section_count` 8（緩衝 0.8s）、`display_window` 100,000 點；新增 `HW_MAX_SAMPLE_RATE` 常數、`clamp_clock_rate()` 硬體上限自動偵測；`DiagnosticWidget` 加入繪圖 decimation（≤ 5,000 點）；回放對話框視窗/速度範圍更新；所有相依參數與測試斷言同步更新 |
| **1.6.0** | **2026-08-27** | **監控預設關閉 + 高速波形診斷分析**：新增「📡 監控開關」toggle 按鈕（連線後預設關閉）；監控模式改為純即時觀察（10 kHz 標示，移除 PASS/FAIL 即時判斷）；新增 `DiagAnalyzer` 對高速波形做 H/L 比例、不定態比例、邊緣計數、頻率估算，診斷完成後輸出各通道與整體 PASS/FAIL；DB 新增 `diag_pass`、`diag_ch_results` 欄位；歷史查詢視窗顯示診斷 PASS/FAIL 與各通道摘要 |
| **1.7.0** | **2026-09-02** | **Hall/Encoder 脈波比值交叉驗證 + 馬達規格可設定**：新增 `RatioCheckResult` 資料類別與 `DiagAnalyzer._cross_validate_ratio()` 方法，對每相 Hall（U/V/W）單獨與 Encoder 平均頻率做比值檢查（理論比值 = PPR / Hall週期/轉 = 512/90 ≈ 5.689），可偵測單相掉脈波、Encoder 掉脈波、無訊號等異常；`HALL_THRESHOLDS` 新增 `hall_pulses_per_rev=90`；`ENCODER_THRESHOLDS` 新增 `resolution_bits=11`、`ppr` 改為 512；`DIAGNOSTIC.analysis` 新增 `enable_ratio_check=True`、`ratio_tolerance=0.15`；`SessionStartDialog` 新增 Hall 週期/轉、Encoder 解析度 bits、比值容差三個設定欄位（bits 變更自動帶出 PPR 建議值，即時顯示理論比值與允許範圍）；npz metadata 新增四個馬達規格欄位供回放分析還原；模擬模式頻率改為動態計算確保比值正確 |
| **1.8.0** | **2026-09-14** | **硬體通道彈性設定**：Hall U/V/W 與 Encoder A/B 對應的 AI/DI 通道不再寫死，可由使用者自訂；新增 `config/channel_map.json` 設定檔與 `config/channel_config.py`（`CHANNEL_CONFIG` 單例，含 `DEFAULT_CHANNEL_MAP`、`load/save`、`_merge_defaults`、`value_range(kind)`、`diagnostic_channels()` 等查詢方法）；`config/thresholds.py` 改為動態帶入通道並新增 `refresh_channel_map()`；`ai_reader.py`/`di_reader.py` 重構為動態通道並新增 `refresh_channels()` 熱重載（AI 以 min~max 範圍讀取支援非連續通道）；`diagnostic_scanner.py` 改依 `kind`（hall/encoder）判斷量程與模擬相位並向後相容舊通道定義；`daq_controller._simulate_di()` 依動態通道產生位元；新增 `ui/channel_config_dialog.py` 對話框（AI/DI 通道、AI 量程、DI 埠號設定，含重複通道檢查與恢復預設）；主視窗新增「🔌 硬體通道」按鈕，套用後即時 `set_map`/`refresh_channel_map`/`refresh_channels` 熱套用 |
| **1.9.0** | **2026-09-14** | **Hall 相序即時判斷**：`logic/hall_analyzer.py` 新增 `HallSequenceDetector` 類別，將三相 Hall（U/V/W）狀態編碼為二進制整數（U=bit0、V=bit1、W=bit2），依相鄰狀態跳轉比對 CW（5→1→3→2→6→4）/ CCW（4→6→2→3→1→5）合法轉換表，判斷旋轉方向與訊號正確性；保留最近 6 個不同狀態（一電氣週期），忽略無效狀態（0/7）與未變化狀態，輸出 CW / CCW / Error / ---；`ui/result_panel.py` 的 `HallLivePanel` 底部新增獨立相序標籤（✓ CW 綠 / ✓ CCW 藍 / ✗ Error 紅 / --- 灰），`update_voltages()`、`update_live_voltages()` 新增相序參數；`ui/main_window.py` 於 `_update_analysis()` 補上 `get_hall_states()` 讀取（同時修正 Hall DI 狀態顯示）並整合相序偵測 |
| **1.10.0** | **2026-09-15** | **即時監控改用 WaveformAI 多通道連續串流（20 kHz/通道）**：`daq/ai_reader.py` 由 `InstantAiCtrl` 逐次輪詢（實際 ~100 Hz）改為 `WaveformAiCtrl` 多通道硬體 DMA 連續串流，每通道真實硬體取樣率提升至 **20,000 Hz**；conversion 以 `channelStart~channelCount` 涵蓋所有 AI 通道（支援非連續通道）、`clockRate` 為每通道取樣率，`getDataF64` 回傳交錯資料後以 numpy `reshape` 解交錯分配各通道 deque；模擬模式改為向量化分段產生（節奏對齊硬體）；`daq/daq_controller.py` 新增監控專用 `create_monitor_wfm_ctrl()`/`release_monitor_wfm_ctrl()`/`get_monitor_wfm_ctrl()`（與診斷 WaveformAiCtrl 分離，進入診斷模式前自動釋放，避免 AI 硬體資源競用）；`config/thresholds.py` 的 `SAMPLING` 更新為 `ai_sample_rate=20_000`、新增 `monitor_chunk_size=2_000`、`section_length=2_000`、`buffer_size=20_000`、`display_max_points=4_000`；`ui/waveform_widget.py` 波形繪製加入自動 decimation（≤ 4,000 點）；UI 標示（監控按鈕 tooltip、狀態列、即時觀察面板標題）同步更新為 20 kHz/通道 連續串流 |
| **1.11.0** | **2026-09-16** | **即時觀察判斷改以 DI 為準，AI 類比僅供波形/數值參考**：釐清即時觀察職責分工 — Hall 相序判斷（CW/CCW/Error）以 **DI** 讀取的 UVW 狀態為準、Encoder 計數/方向/RPM 由 **DI** 正交解碼取得，AI 類比訊號**僅提供波形圖與電壓數值參考**；`ui/result_panel.py` 的 `HallLivePanel` 與 `EncoderLivePanel` **移除「AI 準位（H/L/X）」欄**（連同 `_level_labels` 建立與判斷邏輯），表頭改為三欄（相別/通道、電壓(V)、DI 狀態），電壓數值改為純參考顯示不套用 PASS/FAIL 色彩；面板底部提示文字更新為「DI 判斷相序 · AI 電壓僅供參考」「DI 判斷計數/RPM · AI 電壓僅供參考」；相序標籤與分隔線 grid 跨欄索引由 4 欄調整為 3 欄。（AI/DI 同時檢測仍由高取樣診斷 `DiagAnalyzer` 完成，不受影響） |
| **1.12.0** | **2026-09-16** | **Hall 相序即時判斷擴充為 AI/DI 雙獨立判斷**：即時觀察面板同時以 **AI 類比** 與 **DI 數位** 讀取的 UVW 狀態各自判斷 CW/CCW/Error，兩者獨立運作。`logic/hall_analyzer.py` 的 `HallSequenceDetector` 新增靜態方法 `encode_from_voltages()`，將三相 Hall AI 電壓依中點閾值 `midpoint=(vh_min+vl_max)/2`（3.3V 系統為 1.4V）編碼為布林（`v≥midpoint→H`），避免落在未定義區導致相序卡住；`ui/main_window.py` 將 `_hall_seq_detector` 拆分為 `_hall_seq_detector_di` 與 `_hall_seq_detector_ai` 兩個獨立實例，`_update_analysis()` 分別計算 DI 相序（`hall_di`）與 AI 相序（`hall_voltages` 經閾值編碼），兩組結果一併傳入面板；`ui/result_panel.py` 的 `HallLivePanel` 底部改為**並列顯示 AI/DI 兩個相序標籤**（新增 `_seq_label_ai`、`_seq_label_di` 與共用 `_apply_seq_style()`），`update_voltages()`／`update_live_voltages()` 新增 `seq_result_ai`／`hall_seq_ai` 參數。（此為監控觀察用途，不影響高取樣診斷 PASS/FAIL） |

# 馬達測試系統 - Motor Test System

馬達測試數據量測程式，用於量測三相數位 Hall Sensor 與 Encoder (A/B) 訊號。
使用 **Advantech USB-4716** DAQ 裝置進行類比電壓量測與數位訊號讀取。

---

## 功能特色

### Hall Sensor (3.3V 系統)
- AI 通道量測三相 (U/V/W) 電壓準位（WaveformAI 硬體串流，10,000 Hz/通道）
- DI 通道讀取 H/L 數位狀態
- AI 與 DI 一致性驗證
- 電壓閾值判斷：H > 2.0V，L < 0.8V（可調整）

### Encoder (5V 系統)
- AI 通道量測 A/B 相電壓準位（WaveformAI 硬體串流，10,000 Hz/通道）
- DI 通道讀取 H/L 數位狀態
- 電壓閾值判斷：H > 3.5V，L < 1.5V（可調整）
- 軟體正交解碼（A/B 相位差 90°）
- 轉速計算（RPM）
- 旋轉方向判斷（正轉/反轉/靜止）
- 角度位置計算（度）

### GUI 介面
- PyQt5 + pyqtgraph 即時波形顯示（20 Hz 刷新）
- Hall U/V/W 電壓波形（含閾值線）
- Encoder A/B 電壓波形（AI 電壓，含閾值線）
- 即時 PASS/FAIL 結果顯示
- **倒數計時列**：顯示剩餘時間與進度條（檢測中）
- **即時統計面板**：PASS/FAIL 次數、成功率、平均 RPM（檢測中）
- 視窗高度固定 600px，波形圖滾輪縮放僅作用於 X 軸（時間軸）

### 測試場次管理（v1.1 新增）
- 連線後**立即開始監控**，操作員觀察訊號穩定後再手動觸發檢測
- 每次檢測前可輸入**馬達序號**、操作員名稱，並設定量測參數（PPR、電壓閾值）
- 預設 **5 分鐘**計時，可調整（1~60 分鐘），支援提前停止
- 結果**自動儲存至 SQLite 資料庫**，不需手動操作
- 只記錄統計摘要（成功率、不合格率、RPM），不保留全部原始數據

### 資料庫與歷史查詢（v1.1 新增）
- SQLite 資料庫，預設路徑 `data/motor_test.db`，可在 UI 中變更
- 歷史查詢視窗：表格顯示所有場次，支援序號篩選、匯出 CSV、刪除記錄
- 全域統計摘要：總場次數、整體 PASS 率、平均成功率

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
自動連線 USB-4716（連線成功後立即開始監控）
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
| **▶ 開始檢測** | 開啟場次設定對話框，輸入序號、設定參數後開始計時 |
| **⏹ 提前停止** | 提前結束檢測並儲存目前統計結果 |
| **↺ 重置計數** | 重置 Encoder 計數器 |
| **💾 匯出報表** | 匯出最近一次場次的原始數據（Excel/CSV） |
| **📋 歷史記錄** | 開啟歷史查詢視窗，查看所有場次統計 |
| **🗄 DB 路徑** | 變更 SQLite 資料庫儲存路徑 |
| **🔌 重新連線** | 重新連線 USB-4716 |

### 開始檢測對話框

點擊「▶ 開始檢測」後彈出對話框，可設定以下項目：

**測試物件資訊**
- **馬達序號**：可留空
- **操作員**：可留空

**測試設定**
- **測試時長**：1 ~ 60 分鐘（預設 5 分鐘）

**量測參數設定**（每次測試前確認）
- **Encoder PPR**：依實際 Encoder 規格設定（預設 1000 PPR）
- **Hall VH_min / VL_max**：Hall Sensor 電壓閾值
- **Encoder VH_min / VL_max**：Encoder 電壓閾值

### 歷史查詢視窗

1. 點擊「📋 歷史記錄」開啟
2. 可依序號關鍵字篩選
3. 點選任一列查看詳細資訊
4. 「💾 匯出 CSV」匯出目前顯示的所有記錄
5. 「🗑 刪除選取」刪除選取的場次記錄

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
│   └── motor_test.db              # SQLite 測試記錄資料庫
│
├── config/
│   ├── __init__.py
│   └── thresholds.py              # 電壓閾值、取樣設定、資料庫路徑
│
├── daq/
│   ├── __init__.py
│   ├── daq_controller.py          # USB-4716 裝置控制器（WaveformAI + InstantDI）
│   ├── ai_reader.py               # 類比輸入讀取（WaveformAI 事件驅動，10 kHz）
│   └── di_reader.py               # 數位輸入讀取（H/L + Encoder 軟體計數）
│
├── db/                            # 資料庫模組（v1.1 新增）
│   ├── __init__.py
│   └── database.py                # SQLite CRUD 封裝（DatabaseManager）
│
├── logic/
│   ├── __init__.py
│   ├── hall_analyzer.py           # Hall Sensor 分析邏輯
│   ├── encoder_analyzer.py        # Encoder 分析邏輯
│   └── test_session.py            # 測試場次管理 + 統計計算（v1.1 新增）
│
├── ui/
│   ├── __init__.py
│   ├── main_window.py             # PyQt5 主視窗（v1.1 重構）
│   ├── waveform_widget.py         # pyqtgraph 即時波形元件
│   ├── result_panel.py            # 測試結果顯示面板
│   ├── session_dialog.py          # 場次啟動對話框（v1.1 新增）
│   └── history_viewer.py          # 歷史查詢視窗（v1.1 新增）
│
└── report/
    ├── __init__.py
    └── report_generator.py        # CSV/Excel 報表生成
```

---

## AI 取樣架構（v1.2 改造）

### WaveformAiCtrl 硬體串流模式

v1.2 起 AI 讀取改用 `WaveformAiCtrl` 硬體緩衝串流，取代原本的 `InstantAiCtrl` 逐通道輪詢：

```
USB-4716 硬體 ADC
  │  10,000 Hz/通道（5 通道同步）
  ↓ DMA
硬體環形緩衝區（sectionLength=1000 × sectionCount=4）
  │  每累積 1000 點觸發一次 DataReady 事件（約每 100ms）
  ↓ EvtBufferedAiDataReady
Python _on_data_ready() 回呼
  │  批次取回 5000 個 F64（1000點 × 5通道），解交錯存入 deque
  ↓
波形顯示緩衝區（deque，10,000 點 ≈ 1 秒資料）
```

### 效能對比

| 項目 | v1.1（InstantAI 輪詢） | v1.2（WaveformAI 串流） |
|------|----------------------|----------------------|
| AI 取樣架構 | 逐通道 USB 往返 | 硬體 DMA 串流 |
| 實際 AI 取樣率 | ~40 Hz | **10,000 Hz/通道** |
| GUI 刷新率 | 10 Hz | **20 Hz** |
| 波形緩衝點數 | 1,000 點 | **10,000 點（~1 秒）** |
| AI 通道量程 | 雙極性 ±5V / ±10V | 單極性 0~5V / 0~10V |

### 取樣參數設定（`config/thresholds.py`）

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `ai_sample_rate` | 10,000 Hz | 每通道取樣率 |
| `section_length` | 1,000 | 每 section 樣本數（每通道） |
| `section_count` | 4 | 環形緩衝 section 數 |
| `display_update_ms` | 50 ms | GUI 刷新間隔（20 Hz） |
| `buffer_size` | 10,000 | 波形顯示緩衝點數 |

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

> 💡 AI 電壓波形已改用 WaveformAI 硬體串流（10 kHz），不受此限制影響。
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
- 可嘗試降低 `ai_sample_rate`（如改為 5000）或減少 `section_count`

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
| notes | TEXT | 備註 |

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

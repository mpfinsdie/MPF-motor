# 馬達測試系統 - Motor Test System

馬達測試數據量測程式，用於量測三相數位 Hall Sensor 與 Encoder (A/B) 訊號。
使用 **Advantech USB-4716** DAQ 裝置進行類比電壓量測與數位訊號讀取。

---

## 功能特色

### Hall Sensor (3.3V 系統)
- AI 通道量測三相 (U/V/W) 電壓準位
- DI 通道讀取 H/L 數位狀態
- AI 與 DI 一致性驗證
- 電壓閾值判斷：H > 2.0V，L < 0.8V（可調整）

### Encoder (5V 系統)
- AI 通道量測 A/B 相電壓準位
- DI 通道讀取 H/L 數位狀態
- 電壓閾值判斷：H > 3.5V，L < 1.5V（可調整）
- 軟體正交解碼（A/B 相位差 90°）
- 轉速計算（RPM）
- 旋轉方向判斷（正轉/反轉/靜止）
- 角度位置計算（度）

### GUI 介面
- PyQt5 + pyqtgraph 即時波形顯示
- Hall U/V/W 電壓波形（含閾值線）
- Encoder A/B 電壓波形 + 數位訊號波形
- 即時 PASS/FAIL 結果顯示
- 電壓閾值與 Encoder PPR 可即時調整

### 報表輸出
- Excel (.xlsx) 格式：含摘要、Hall、Encoder 三個工作表
- CSV 格式：Hall 與 Encoder 各一個檔案

---

## 硬體需求

| 項目 | 規格 |
|------|------|
| DAQ 裝置 | Advantech USB-4716 |
| Driver | DAQNavi（已安裝） |
| Hall Sensor | 3.3V 數位輸出，三相 (U/V/W) |
| Encoder | 5V 數位輸出，A/B 正交訊號 |

### 接線規劃

| 訊號 | AI 通道 | DI 通道 | 電壓系統 |
|------|---------|---------|----------|
| Hall U | AI Ch0 | DI0 | 3.3V |
| Hall V | AI Ch1 | DI1 | 3.3V |
| Hall W | AI Ch2 | DI2 | 3.3V |
| Encoder A | AI Ch3 | DI3 | 5V |
| Encoder B | AI Ch4 | DI4 | 5V |
| GND | AGND | DGND | 共地 |

> ⚠️ **注意**：USB-4716 DI 為 TTL 相容（VIH max = 5.5V），5V 訊號可直接接入。

---

## 軟體需求

- Python 3.8+
- Advantech DAQNavi SDK（已安裝）

---

## 安裝步驟

### Step 1：複製 DAQNavi Python Wrapper

從 DAQNavi 安裝目錄複製以下兩個檔案到專案根目錄：

```
C:\Program Files (x86)\Advantech\DAQNavi\Examples\Python\Automation.py
C:\Program Files (x86)\Advantech\DAQNavi\Examples\Python\bdaqctrl.py
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

> 💡 **模擬模式**：若未安裝 DAQNavi SDK 或未連接硬體，程式會自動進入模擬模式，使用模擬訊號進行測試。

---

## 操作說明

1. **啟動程式** → 自動嘗試連線 USB-4716
2. **調整設定**（右側面板）：
   - Encoder PPR：依實際 Encoder 規格設定（預設 1000 PPR）
   - Hall/Encoder 電壓閾值：可即時調整
3. **點擊「▶ 開始量測」** → 開始即時波形顯示與分析
4. **觀察結果面板**：
   - 綠色 PASS / 紅色 FAIL 即時顯示
   - 電壓值、準位、DI 狀態、一致性
   - Encoder 計數、方向、RPM、位置
5. **點擊「↺ 重置計數」** → 重置 Encoder 計數器
6. **點擊「■ 停止」** → 停止量測
7. **點擊「💾 匯出報表」** → 選擇 Excel 或 CSV 格式儲存

---

## 專案結構

```
MPF-motor/
├── main.py                        # 程式進入點
├── requirements.txt               # Python 相依套件
├── README.md                      # 本文件
├── Automation.py                  # DAQNavi wrapper（需手動複製）
├── bdaqctrl.py                    # DAQNavi wrapper（需手動複製）
│
├── config/
│   ├── __init__.py
│   └── thresholds.py              # 電壓閾值與取樣設定
│
├── daq/
│   ├── __init__.py
│   ├── daq_controller.py          # USB-4716 裝置控制器
│   ├── ai_reader.py               # 類比輸入讀取（電壓量測）
│   └── di_reader.py               # 數位輸入讀取（H/L + Encoder 計數）
│
├── logic/
│   ├── __init__.py
│   ├── hall_analyzer.py           # Hall Sensor 分析邏輯
│   └── encoder_analyzer.py        # Encoder 分析邏輯
│
├── ui/
│   ├── __init__.py
│   ├── main_window.py             # PyQt5 主視窗
│   ├── waveform_widget.py         # pyqtgraph 即時波形元件
│   └── result_panel.py            # 測試結果顯示面板
│
└── report/
    ├── __init__.py
    └── report_generator.py        # CSV/Excel 報表生成
```

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

USB-4716 **無硬體計數器**，Encoder 使用 Python 軟體輪詢計數。

| 參數 | 說明 |
|------|------|
| 輪詢間隔 | 0.1 ms（約 10 kHz） |
| 可靠最高頻率 | ~1~5 kHz（依系統負載） |
| 建議最高轉速 | 300 RPM @ 1000 PPR |

若需更高轉速量測，建議降低 Encoder PPR 或使用具硬體計數器的 DAQ 模組。

---

## 常見問題

**Q: 程式啟動後顯示「連線失敗」**
- 確認 USB-4716 已插入並被 Windows 識別
- 確認 DAQNavi driver 已正確安裝
- 嘗試點擊「🔌 重新連線」按鈕

**Q: 程式進入模擬模式**
- 確認 `Automation.py` 與 `bdaqctrl.py` 已複製到專案根目錄
- 確認 DAQNavi 安裝路徑正確

**Q: Encoder RPM 讀值不穩定**
- 軟體計數受系統負載影響，屬正常現象
- 可降低 AI 取樣率（`config/thresholds.py` 中的 `ai_sample_rate`）以減少 CPU 負載

---

## 版本記錄

| 版本 | 日期 | 說明 |
|------|------|------|
| 1.0.0 | 2026-08-14 | 初始版本 |

"""
電壓閾值設定模組
Hall Sensor (3.3V 系統) 與 Encoder (5V 系統) 的判斷閾值
"""

import os
from pathlib import Path

# ─── 硬體規格常數 ────────────────────────────────────────────────────────────────
# Advantech USB-4716 硬體最高取樣率（單通道，WaveformAiCtrl 模式）
# 多通道同時採樣時為總取樣率共享；診斷模式為單通道，可達此上限
HW_MAX_SAMPLE_RATE = 200_000   # 200 kS/s（每通道最高）

# Hall Sensor 閾值設定（3.3V 系統）
HALL_THRESHOLDS = {
    "system_voltage": 3.3,
    "vh_min": 2.0,      # H 準位最低電壓 (V)
    "vl_max": 0.8,      # L 準位最高電壓 (V)
    "channels": {
        "U": 0,         # AI Channel 0
        "V": 1,         # AI Channel 1
        "W": 2,         # AI Channel 2
    },
    "di_channels": {
        "U": 0,         # DI Channel 0
        "V": 1,         # DI Channel 1
        "W": 2,         # DI Channel 2
    },
}

# Encoder 閾值設定（5V 系統）
ENCODER_THRESHOLDS = {
    "system_voltage": 5.0,
    "vh_min": 3.5,      # H 準位最低電壓 (V)
    "vl_max": 1.5,      # L 準位最高電壓 (V)
    "channels": {
        "A": 3,         # AI Channel 3
        "B": 4,         # AI Channel 4
    },
    "di_channels": {
        "A": 3,         # DI Channel 3
        "B": 4,         # DI Channel 4
    },
    "ppr": 1000,        # Pulses Per Revolution（每轉脈波數，依實際 Encoder 規格修改）
}

# AI 量程設定（WaveformAiCtrl 通道量程，對應 ValueRange 枚舉）
AI_RANGE = {
    "hall":    "V_0To5",   # 0~5V 單極性（Hall 3.3V 訊號）
    "encoder": "V_0To10",  # 0~10V 單極性（Encoder 5V 訊號）
}

# ─── 即時監控取樣設定（InstantAiCtrl 輪詢模式）────────────────────────────────
# 注意：InstantAiCtrl 為逐次輪詢架構，非硬體連續採樣，
#       ai_sample_rate 僅作為文件標示常數（10 kHz），實際輪詢速率受 OS 排程限制（約 100~1000 Hz）
#       即時監控模式預設關閉，需手動按「監控開關」按鈕啟動，僅供初步觀察使用
SAMPLING = {
    "ai_sample_rate":    10_000,  # 即時監控標示取樣率 (Hz)，10 kHz（僅文件標示，非硬體連續採樣）
                                  # 實際 InstantAiCtrl 輪詢速率約 100 Hz（每 10ms 一次）
    "section_length":    20_000,  # WaveformAI 每 section 樣本數（每通道）
                                  # DataReady 觸發間隔 = section_length / ai_sample_rate
                                  # = 20000 / 200000 = 0.1s（維持 10 Hz 回呼頻率）
    "section_count":     8,       # WaveformAI 環形緩衝 section 數
                                  # 總緩衝深度 = 8 × 20000 = 160,000 點/通道（0.8s）
    "di_poll_interval":  0.0001,  # DI 輪詢間隔 (秒) = 10 kHz（DI 不受 AI 取樣率影響）
    "display_update_ms": 50,      # GUI 更新間隔 (ms)，20 Hz 刷新
    "buffer_size":       10_000,  # 波形顯示緩衝點數（10kHz × 1s = 10,000 點）
}

# ─── 高取樣率診斷設定（WaveformAiCtrl 單通道高速串流）────────────────────────
# 每通道資料量：200,000 Hz × 10s = 2,000,000 點 ≈ 7.6 MB (float32)
# 5 通道 × 2 輪 = 20,000,000 點 ≈ 76 MB（壓縮後約 10~20 MB）
DIAGNOSTIC = {
    "sample_rate":       200_000, # 每通道取樣率 (Hz)，200kHz（硬體最高）
    "seconds_per_ch":    10,      # 每個通道採樣秒數
    "rounds":            2,       # 總輪數（跑完所有 CH 為 1 輪）
    "chunk_size":        20_000,  # 每次分段讀取點數
                                  # = 20000 / 200000 = 0.1s/段（維持 10 Hz 回呼頻率）
                                  # 避免 200kHz 下回呼過於頻繁造成 UI 卡頓
    "section_count":     8,       # WaveformAI 環形緩衝 section 數（僅供模擬模式參考）
                                  # 真實硬體模式：rec.sectionCount = 0（無限循環），
                                  # 此值不再傳入 WaveformAiCtrl，避免硬體在 8 段後自動停止
    "display_window":    100_000, # 即時波形顯示視窗點數（200kHz × 0.5s = 100,000 點）
                                  # 繪圖時自動 decimation 降採樣，維持 UI 流暢
    "channels": [                 # 診斷通道清單（依序輪流採樣）
        {"ch": 0, "name": "Hall U",    "vh_min": None, "vl_max": None, "y_range": (-0.2, 3.8)},
        {"ch": 1, "name": "Hall V",    "vh_min": None, "vl_max": None, "y_range": (-0.2, 3.8)},
        {"ch": 2, "name": "Hall W",    "vh_min": None, "vl_max": None, "y_range": (-0.2, 3.8)},
        {"ch": 3, "name": "Encoder A", "vh_min": None, "vl_max": None, "y_range": (-0.5, 6.0)},
        {"ch": 4, "name": "Encoder B", "vh_min": None, "vl_max": None, "y_range": (-0.5, 6.0)},
    ],
    "diag_dir":          "data/diagnostics",  # 診斷 npz 儲存目錄（相對於專案根目錄）

    # ─── 高速數據診斷判斷參數（供 DiagAnalyzer 使用）────────────────────────
    # 以下參數用於對高速波形做 PASS/FAIL 判斷，可依實際馬達規格調整
    "analysis": {
        # H/L 準位比例容許範圍（佔全部樣本的比例）
        # 正常方波訊號 H 與 L 各約 50%，允許 ±30% 偏差（20%~80%）
        "hl_ratio_min":         0.05,   # H 準位樣本比例下限（低於此值視為訊號異常）
        "hl_ratio_max":         0.95,   # H 準位樣本比例上限（高於此值視為訊號異常）

        # 不定態（X 準位，介於 VL_max 與 VH_min 之間）比例上限
        # 超過此比例表示訊號品質差（雜訊過大或準位不穩定）
        "undefined_ratio_max":  0.20,   # 不定態樣本比例上限（超過 20% 視為 FAIL）

        # 最少邊緣數（上升沿 + 下降沿）
        # 10 秒內至少要有此數量的邊緣，才表示訊號有在切換（馬達有在轉）
        # Hall 50Hz × 10s × 2（上升+下降）= 1000 邊緣；Encoder 500Hz × 10s × 2 = 10000
        # 設定較寬鬆的下限，允許低速運轉
        "min_edges_hall":       10,     # Hall 通道最少邊緣數（10 秒內）
        "min_edges_encoder":    20,     # Encoder 通道最少邊緣數（10 秒內）

        # 主頻率容許範圍 (Hz)
        # Hall 訊號頻率 = 馬達電氣頻率（極對數 × 機械轉速）
        # Encoder 訊號頻率 = PPR × 機械轉速 / 60
        # 設定為 0 表示不做頻率範圍檢查（僅做邊緣數量檢查）
        "freq_min_hall":        0.0,    # Hall 主頻率下限 (Hz)，0 = 不限制
        "freq_max_hall":        0.0,    # Hall 主頻率上限 (Hz)，0 = 不限制
        "freq_min_encoder":     0.0,    # Encoder 主頻率下限 (Hz)，0 = 不限制
        "freq_max_encoder":     0.0,    # Encoder 主頻率上限 (Hz)，0 = 不限制

        # 輪次間一致性：多輪採樣的主頻率差異容許比例
        # 例如 0.20 表示兩輪頻率差異不超過 20% 才算一致
        "round_freq_diff_max":  0.20,   # 輪次間頻率差異上限（比例）

        # 最少有效樣本數（低於此值的通道跳過分析，視為資料不足）
        "min_samples":          1000,   # 最少有效樣本數
    },
}

# 資料庫設定
_DEFAULT_DB_DIR = str(Path(__file__).parent.parent / "data")
DATABASE = {
    "db_path": str(Path(_DEFAULT_DB_DIR) / "motor_test.db"),
    # 整體 PASS 門檻（Hall 與 Encoder 成功率都需 >= 此值）
    "pass_threshold": 0.95,
    # 預設測試時長（秒）
    "default_duration_s": 300,
}

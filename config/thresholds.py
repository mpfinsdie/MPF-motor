"""
電壓閾值設定模組
Hall Sensor (3.3V 系統) 與 Encoder (5V 系統) 的判斷閾值
"""

import os
from pathlib import Path

# 硬體通道對應（使用者可透過 UI 或 config/channel_map.json 調整）
from config.channel_config import CHANNEL_CONFIG

# ─── 硬體規格常數 ────────────────────────────────────────────────────────────────
# Advantech USB-4716 硬體最高取樣率（單通道，WaveformAiCtrl 模式）
# 多通道同時採樣時為總取樣率共享；診斷模式為單通道，可達此上限
HW_MAX_SAMPLE_RATE = 200_000   # 200 kS/s（每通道最高）

# Hall Sensor 閾值設定（3.3V 系統）
# 注意：channels / di_channels 由 CHANNEL_CONFIG 動態填入，
#       使用者可透過 UI「硬體通道設定」或直接編輯 config/channel_map.json 調整
HALL_THRESHOLDS = {
    "system_voltage": 3.3,
    "vh_min": 2.0,              # H 準位最低電壓 (V)
    "vl_max": 0.8,              # L 準位最高電壓 (V)
    "channels":    CHANNEL_CONFIG.hall_ai_channels(),   # {"U":0,"V":1,"W":2}（動態）
    "di_channels": CHANNEL_CONFIG.hall_di_channels(),   # {"U":0,"V":1,"W":2}（動態）
    # ── 馬達規格參數（可在「參數設置」對話框調整）────────────────────────────
    # Hall Sensor 每相每轉產生的 H-L 週期數（脈波數）
    # 例：本馬達每相每轉 90 次 High-Low，即 90 個週期
    "hall_pulses_per_rev": 90,  # 每轉週期數（依實際馬達 Hall Sensor 規格修改）
}

# Encoder 閾值設定（5V 系統）
# 注意：channels / di_channels 由 CHANNEL_CONFIG 動態填入
ENCODER_THRESHOLDS = {
    "system_voltage": 5.0,
    "vh_min": 3.5,              # H 準位最低電壓 (V)
    "vl_max": 1.5,              # L 準位最高電壓 (V)
    "channels":    CHANNEL_CONFIG.encoder_ai_channels(),  # {"A":3,"B":4}（動態）
    "di_channels": CHANNEL_CONFIG.encoder_di_channels(),  # {"A":3,"B":4}（動態）
    # ── Encoder 規格參數（可在「參數設置」對話框調整）────────────────────────
    # resolution_bits：Encoder 解析度位元數
    #   11 bits → 每轉總計數 2^11 = 2048 counts（四倍頻後）
    #   每相 PPR = 2048 / 4 = 512
    "resolution_bits": 11,      # Encoder 解析度（bits），顯示與推算 PPR 用
    "ppr": 512,                 # Pulses Per Revolution（每相每轉脈波數）
                                # = 2^resolution_bits / 4（四倍頻正交解碼）
                                # 依實際 Encoder 規格修改
}

# AI 量程設定（WaveformAiCtrl 通道量程，對應 ValueRange 枚舉）
# 由 CHANNEL_CONFIG 動態填入，使用者可調整
AI_RANGE = {
    "hall":    CHANNEL_CONFIG.value_range_name("hall"),     # 0~5V 單極性（Hall 3.3V 訊號）
    "encoder": CHANNEL_CONFIG.value_range_name("encoder"),  # 0~10V 單極性（Encoder 5V 訊號）
}

# ─── 即時監控取樣設定（WaveformAiCtrl 多通道連續串流模式，v1.9）──────────────
# v1.9 起即時監控改用 WaveformAiCtrl 多通道硬體 DMA 連續串流，
# 每個通道實際以 ai_sample_rate（20 kHz）硬體取樣，不再是 InstantAiCtrl 逐次輪詢。
#   硬體 ADC → DMA → 環形緩衝區 → 背景執行緒 getDataF64 → 解交錯分配各通道 → UI 顯示
# 監控模式預設關閉，需手動按「監控開關」按鈕啟動，僅供初步觀察，不做 PASS/FAIL 判斷。
#
# 多通道總取樣率 = ai_sample_rate × 通道數（5 CH × 20kHz = 100 kS/s），
# 仍在 USB-4716 硬體總頻寬（HW_MAX_SAMPLE_RATE = 200 kS/s）之內。
SAMPLING = {
    "ai_sample_rate":    20_000,  # 即時監控每通道取樣率 (Hz)，20 kHz（WaveformAiCtrl 硬體連續採樣）
                                  # 多通道總取樣率 = 20kHz × 通道數，需 ≤ HW_MAX_SAMPLE_RATE
    "monitor_chunk_size": 2_000,  # 監控串流每通道分段讀取點數
                                  # DataReady 觸發間隔 = monitor_chunk_size / ai_sample_rate
                                  # = 2000 / 20000 = 0.1s（維持 10 Hz 回呼頻率，避免 UI 卡頓）
    "section_length":    2_000,   # WaveformAI 每 section 樣本數（每通道），與 monitor_chunk_size 對齊
    "section_count":     8,       # WaveformAI 環形緩衝 section 數
                                  # 總緩衝深度 = 8 × 2000 = 16,000 點/通道（0.8s @ 20kHz）
    "di_poll_interval":  0.0001,  # DI 輪詢間隔 (秒) = 10 kHz（DI 不受 AI 取樣率影響）
    "display_update_ms": 50,      # GUI 更新間隔 (ms)，20 Hz 刷新
    "buffer_size":       20_000,  # 波形顯示緩衝點數（20kHz × 1s = 20,000 點/通道）
    "display_max_points": 4_000,  # 繪圖降採樣上限（超過則 decimation，維持 UI 流暢）
}

# ─── 高取樣率診斷設定（WaveformAiCtrl 單通道高速串流）────────────────────────
# 每通道資料量：200,000 Hz × 2s = 400,000 點 ≈ 1.5 MB (float32)
# 5 通道 × 2 輪 = 4,000,000 點 ≈ 16 MB（壓縮後約 2~4 MB）
DIAGNOSTIC = {
    "sample_rate":       200_000, # 每通道取樣率 (Hz)，200kHz（硬體最高）
    "seconds_per_ch":    2,       # 每個通道採樣秒數
                                  # 60 RPM 時 Hall 頻率 = 90 Hz，2 秒可採集 180 週期，
                                  # 遠超統計所需最低值（100 週期），且大幅縮短採集時間
    "rounds":            2,       # 總輪數（跑完所有 CH 為 1 輪）
    "chunk_size":        20_000,  # 每次分段讀取點數
                                  # = 20000 / 200000 = 0.1s/段（維持 10 Hz 回呼頻率）
                                  # 避免 200kHz 下回呼過於頻繁造成 UI 卡頓
    "section_count":     8,       # WaveformAI 環形緩衝 section 數（僅供模擬模式參考）
                                  # 真實硬體模式：rec.sectionCount = 0（無限循環），
                                  # 此值不再傳入 WaveformAiCtrl，避免硬體在 8 段後自動停止
    "display_window":    80_000,  # 即時波形顯示視窗點數（200kHz × 0.4s = 80,000 點）
                                  # = 2 秒採集的 20%，繪圖時自動 decimation 降採樣，維持 UI 流暢
    # 診斷通道清單（依序輪流採樣）由 CHANNEL_CONFIG 動態產生，
    # 每項含 ch/name/kind/y_range，使用者可透過 UI 或 channel_map.json 調整
    "channels": CHANNEL_CONFIG.diagnostic_channels(),
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
        # 2 秒內至少要有此數量的邊緣，才表示訊號有在切換（馬達有在轉）
        # Hall 90Hz × 2s × 2（上升+下降）= 360 邊緣；Encoder 512Hz × 2s × 2 = 2048
        # 設定較寬鬆的下限，允許低速運轉（例如 10 RPM 時 Hall 仍有 30 邊緣）
        "min_edges_hall":       20,     # Hall 通道最少邊緣數（2 秒內）
        "min_edges_encoder":    40,     # Encoder 通道最少邊緣數（2 秒內）

        # 主頻率容許範圍 (Hz)
        # Hall 訊號頻率 = hall_pulses_per_rev × 機械轉速 / 60
        # Encoder 訊號頻率 = ppr × 機械轉速 / 60
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

        # ── Hall / Encoder 脈波比值交叉驗證 ──────────────────────────────────
        # 原理：Hall 與 Encoder 同軸，頻率比為固定常數：
        #   理論比值 = ppr / hall_pulses_per_rev = 512 / 90 ≈ 5.689
        # 無論轉速多少，實測 f_encoder / f_hall_相 應落在理論比值 ±容差內。
        # 每一相 Hall（U/V/W）都單獨與 Encoder 平均頻率做比值檢查：
        #   - 某相 Hall 掉脈波 → 該相頻率偏低 → 比值偏高 → FAIL
        #   - Encoder 掉脈波  → Encoder 頻率偏低 → 比值偏低 → FAIL
        #   - 某相無訊號      → 頻率為 0 → 直接 FAIL
        "enable_ratio_check":   True,   # 是否啟用比值交叉驗證（False = 跳過此項）
        "ratio_tolerance":      0.15,   # 比值容差（±15%），超出則 FAIL
                                        # 例：理論比值 5.689，容差 15%
                                        # 允許範圍：5.689 × (1±0.15) = [4.836, 6.542]
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


# ─── 通道對應熱更新 ──────────────────────────────────────────────────────────────
def refresh_channel_map():
    """
    依 CHANNEL_CONFIG 目前狀態，就地更新各設定字典的通道對應。

    使用者透過 UI「硬體通道設定」對話框修改通道後呼叫此函式，
    讓 HALL_THRESHOLDS / ENCODER_THRESHOLDS / AI_RANGE / DIAGNOSTIC["channels"]
    立即反映新設定（就地更新，維持既有物件參照有效）。
    """
    HALL_THRESHOLDS["channels"]    = CHANNEL_CONFIG.hall_ai_channels()
    HALL_THRESHOLDS["di_channels"] = CHANNEL_CONFIG.hall_di_channels()
    ENCODER_THRESHOLDS["channels"]    = CHANNEL_CONFIG.encoder_ai_channels()
    ENCODER_THRESHOLDS["di_channels"] = CHANNEL_CONFIG.encoder_di_channels()
    AI_RANGE["hall"]    = CHANNEL_CONFIG.value_range_name("hall")
    AI_RANGE["encoder"] = CHANNEL_CONFIG.value_range_name("encoder")
    # DIAGNOSTIC["channels"] 需就地替換內容（保留 list 物件參照）
    DIAGNOSTIC["channels"][:] = CHANNEL_CONFIG.diagnostic_channels()

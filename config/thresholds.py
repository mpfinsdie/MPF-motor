"""
電壓閾值設定模組
Hall Sensor (3.3V 系統) 與 Encoder (5V 系統) 的判斷閾值
"""

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

# AI 量程設定
AI_RANGE = {
    "hall": "Bipolar5V",    # ±5V 量程（Hall 3.3V 訊號，精度較高）
    "encoder": "Bipolar10V", # ±10V 量程（Encoder 5V 訊號）
}

# 取樣設定
SAMPLING = {
    "ai_sample_rate": 10000,    # AI 取樣率 (Hz)
    "di_poll_interval": 0.0001, # DI 輪詢間隔 (秒) = 10 kHz
    "display_update_ms": 100,   # GUI 更新間隔 (ms)
    "buffer_size": 1000,        # 波形顯示緩衝點數
}

"""
數位輸入讀取模組
負責從 USB-4716 DI 通道讀取 Hall Sensor H/L 狀態與 Encoder 脈波
支援軟體計數器（Encoder A/B 正交解碼）

通道對應：
  由 config.channel_config.CHANNEL_CONFIG 動態提供，使用者可透過 UI
  「硬體通道設定」或直接編輯 config/channel_map.json 調整 DI 通道，
  不再固定為 DI0~4。呼叫 refresh_channels() 可於執行期套用新設定。
"""

import time
import threading
import numpy as np
from collections import deque
from typing import Callable, Optional

from config.thresholds import HALL_THRESHOLDS, ENCODER_THRESHOLDS, SAMPLING
from config.channel_config import CHANNEL_CONFIG


class DIReader:
    """
    數位輸入讀取器
    - 讀取 Hall U/V/W 的 H/L 狀態
    - 讀取 Encoder A/B 並進行軟體正交解碼（計數、方向、RPM）

    通道對應由 CHANNEL_CONFIG 動態提供，可用 refresh_channels() 熱更新。
    """

    # 正交解碼狀態機查表（A_prev, B_prev, A_curr, B_curr）→ 計數增量
    QUADRATURE_TABLE = {
        (0, 0, 0, 1): +1,
        (0, 1, 1, 1): +1,
        (1, 1, 1, 0): +1,
        (1, 0, 0, 0): +1,
        (0, 0, 1, 0): -1,
        (1, 0, 1, 1): -1,
        (1, 1, 0, 1): -1,
        (0, 1, 0, 0): -1,
    }

    def __init__(self, daq_controller):
        """
        Args:
            daq_controller: DAQController 實例
        """
        self._daq = daq_controller
        self._poll_interval = SAMPLING["di_poll_interval"]
        self._buffer_size = SAMPLING["buffer_size"]
        self._ppr = ENCODER_THRESHOLDS["ppr"]

        # 執行緒控制
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # 回呼
        self._on_data_callback: Optional[Callable] = None

        # 依 CHANNEL_CONFIG 建立通道結構與狀態
        self._build_channel_state()

    # ─── 通道結構建立 / 熱更新 ──────────────────────────────────────────────────

    def _build_channel_state(self):
        """依 CHANNEL_CONFIG 目前設定建立 DI 通道清單、緩衝與狀態"""
        self._hall_di_channels    = [CHANNEL_CONFIG.hall_di(s) for s in ("U", "V", "W")]
        self._encoder_di_channels = [CHANNEL_CONFIG.encoder_di(s) for s in ("A", "B")]
        self._di_port = CHANNEL_CONFIG.di_port()

        # Hall 狀態緩衝
        self._hall_buffers: dict[int, deque] = {
            ch: deque(maxlen=self._buffer_size) for ch in self._hall_di_channels
        }
        self._hall_latest: dict[int, bool] = {
            ch: False for ch in self._hall_di_channels
        }

        # Encoder 狀態
        self._enc_count: int = 0          # 累計脈波計數
        self._enc_direction: int = 0      # +1=正轉, -1=反轉, 0=靜止
        self._enc_rpm: float = 0.0        # 轉速 (RPM)
        self._enc_a_prev: int = 0
        self._enc_b_prev: int = 0

        # Encoder 緩衝
        self._enc_a_buffer: deque = deque(maxlen=self._buffer_size)
        self._enc_b_buffer: deque = deque(maxlen=self._buffer_size)
        self._enc_count_buffer: deque = deque(maxlen=self._buffer_size)

        # RPM 計算用
        self._rpm_window_counts: deque = deque(maxlen=100)  # 最近 100 次計數差
        self._rpm_window_times: deque = deque(maxlen=100)   # 對應時間戳
        self._last_count_for_rpm: int = 0
        self._last_time_for_rpm: float = time.time()

        # 時間戳記
        self._timestamps: deque = deque(maxlen=self._buffer_size)

    def refresh_channels(self):
        """
        於執行期套用新的通道設定（使用者透過 UI 修改通道後呼叫）。
        會停止目前讀取（若正在執行）、重建通道結構後重啟。
        """
        was_running = self._running
        if was_running:
            self.stop()
        with self._lock:
            self._build_channel_state()
        print(
            f"[DIReader] 通道設定已更新 | "
            f"Hall DI={self._hall_di_channels} | "
            f"Encoder DI={self._encoder_di_channels} | Port={self._di_port}"
        )
        if was_running:
            self.start()

    # 相容屬性（供外部參考目前通道）
    @property
    def HALL_DI_CHANNELS(self):
        return self._hall_di_channels

    @property
    def ENCODER_DI_CHANNELS(self):
        return self._encoder_di_channels

    def set_data_callback(self, callback: Callable):
        """設定資料更新回呼函式"""
        self._on_data_callback = callback

    def start(self):
        """啟動背景讀取執行緒"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        print("[DIReader] 已啟動背景讀取")

    def stop(self):
        """停止背景讀取執行緒"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        print("[DIReader] 已停止")

    def reset_encoder(self):
        """重置 Encoder 計數器"""
        with self._lock:
            self._enc_count = 0
            self._enc_direction = 0
            self._enc_rpm = 0.0
            self._enc_count_buffer.clear()
            self._rpm_window_counts.clear()
            self._rpm_window_times.clear()
            self._last_count_for_rpm = 0
            self._last_time_for_rpm = time.time()
        print("[DIReader] Encoder 計數器已重置")

    def _read_loop(self):
        """背景讀取迴圈"""
        while self._running:
            try:
                t = time.time()
                port_data = self._daq.read_di_port(self._di_port)

                # 解析各通道
                hall_states = {}
                for ch in self._hall_di_channels:
                    hall_states[ch] = bool((port_data >> ch) & 0x01)

                enc_a = int((port_data >> self._encoder_di_channels[0]) & 0x01)
                enc_b = int((port_data >> self._encoder_di_channels[1]) & 0x01)

                with self._lock:
                    # 更新 Hall 狀態
                    self._timestamps.append(t)
                    for ch, state in hall_states.items():
                        self._hall_buffers[ch].append(int(state))
                        self._hall_latest[ch] = state

                    # 正交解碼
                    key = (self._enc_a_prev, self._enc_b_prev, enc_a, enc_b)
                    delta = self.QUADRATURE_TABLE.get(key, 0)
                    if delta != 0:
                        self._enc_count += delta
                        self._enc_direction = delta

                    self._enc_a_prev = enc_a
                    self._enc_b_prev = enc_b

                    # 更新 Encoder 緩衝
                    self._enc_a_buffer.append(enc_a)
                    self._enc_b_buffer.append(enc_b)
                    self._enc_count_buffer.append(self._enc_count)

                    # 計算 RPM（每 0.1 秒更新一次）
                    elapsed = t - self._last_time_for_rpm
                    if elapsed >= 0.1:
                        count_diff = self._enc_count - self._last_count_for_rpm
                        # RPM = (脈波數 / PPR) × (60 / 時間秒)
                        self._enc_rpm = (abs(count_diff) / self._ppr) * (60.0 / elapsed)
                        if count_diff < 0:
                            self._enc_rpm = -self._enc_rpm
                        self._last_count_for_rpm = self._enc_count
                        self._last_time_for_rpm = t

                if self._on_data_callback:
                    self._on_data_callback({
                        "hall": hall_states,
                        "enc_a": enc_a,
                        "enc_b": enc_b,
                        "enc_count": self._enc_count,
                        "enc_direction": self._enc_direction,
                        "enc_rpm": self._enc_rpm,
                    })

            except Exception as e:
                print(f"[DIReader] 讀取錯誤: {e}")

            time.sleep(self._poll_interval)

    # ─── 狀態查詢方法 ──────────────────────────────────────────────────────────

    def get_hall_states(self) -> dict:
        """
        取得三相 Hall Sensor 最新 H/L 狀態
        Returns:
            dict: {"U": bool, "V": bool, "W": bool}
        """
        with self._lock:
            return {
                "U": self._hall_latest.get(CHANNEL_CONFIG.hall_di("U"), False),
                "V": self._hall_latest.get(CHANNEL_CONFIG.hall_di("V"), False),
                "W": self._hall_latest.get(CHANNEL_CONFIG.hall_di("W"), False),
            }

    def get_encoder_state(self) -> dict:
        """
        取得 Encoder 最新狀態
        Returns:
            dict: {
                "A": bool,
                "B": bool,
                "count": int,
                "direction": int,  # +1=正轉, -1=反轉, 0=靜止
                "rpm": float,
                "position_deg": float,  # 角度位置 (度)
            }
        """
        with self._lock:
            position_deg = (self._enc_count % self._ppr) / self._ppr * 360.0
            return {
                "A": bool(self._enc_a_prev),
                "B": bool(self._enc_b_prev),
                "count": self._enc_count,
                "direction": self._enc_direction,
                "rpm": self._enc_rpm,
                "position_deg": position_deg,
            }

    def get_hall_buffer(self, channel: int) -> np.ndarray:
        """取得指定 Hall DI 通道的波形緩衝（通道不存在時回傳空陣列）"""
        with self._lock:
            if channel not in self._hall_buffers:
                return np.array([])
            return np.array(list(self._hall_buffers[channel]))

    def get_encoder_a_buffer(self) -> np.ndarray:
        """取得 Encoder A 波形緩衝"""
        with self._lock:
            return np.array(list(self._enc_a_buffer))

    def get_encoder_b_buffer(self) -> np.ndarray:
        """取得 Encoder B 波形緩衝"""
        with self._lock:
            return np.array(list(self._enc_b_buffer))

    def get_encoder_count_buffer(self) -> np.ndarray:
        """取得 Encoder 計數緩衝"""
        with self._lock:
            return np.array(list(self._enc_count_buffer))

    def get_timestamps(self) -> np.ndarray:
        """取得時間戳記陣列"""
        with self._lock:
            return np.array(list(self._timestamps))

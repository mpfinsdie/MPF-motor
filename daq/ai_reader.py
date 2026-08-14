"""
類比輸入讀取模組
負責從 USB-4716 AI 通道讀取 Hall Sensor 與 Encoder 的電壓值
"""

import time
import threading
import numpy as np
from collections import deque
from typing import Callable, Optional

from config.thresholds import HALL_THRESHOLDS, ENCODER_THRESHOLDS, SAMPLING


class AIReader:
    """
    類比輸入讀取器
    持續從 AI 通道讀取電壓，並維護滾動緩衝區供波形顯示使用
    """

    # 所有需要讀取的 AI 通道
    HALL_CHANNELS = list(HALL_THRESHOLDS["channels"].values())    # [0, 1, 2]
    ENCODER_CHANNELS = list(ENCODER_THRESHOLDS["channels"].values())  # [3, 4]
    ALL_CHANNELS = HALL_CHANNELS + ENCODER_CHANNELS               # [0, 1, 2, 3, 4]

    CHANNEL_NAMES = {
        0: "Hall U",
        1: "Hall V",
        2: "Hall W",
        3: "Encoder A",
        4: "Encoder B",
    }

    def __init__(self, daq_controller):
        """
        Args:
            daq_controller: DAQController 實例
        """
        self._daq = daq_controller
        self._buffer_size = SAMPLING["buffer_size"]
        self._poll_interval = 1.0 / SAMPLING["ai_sample_rate"]

        # 各通道滾動緩衝區
        self._buffers: dict[int, deque] = {
            ch: deque(maxlen=self._buffer_size) for ch in self.ALL_CHANNELS
        }
        self._timestamps: deque = deque(maxlen=self._buffer_size)

        # 最新讀值
        self._latest: dict[int, float] = {ch: 0.0 for ch in self.ALL_CHANNELS}

        # 執行緒控制
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # 資料更新回呼
        self._on_data_callback: Optional[Callable] = None

    def set_data_callback(self, callback: Callable):
        """設定資料更新回呼函式，每次讀取後呼叫"""
        self._on_data_callback = callback

    def start(self):
        """啟動背景讀取執行緒"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        print("[AIReader] 已啟動背景讀取")

    def stop(self):
        """停止背景讀取執行緒"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        print("[AIReader] 已停止")

    def _read_loop(self):
        """背景讀取迴圈"""
        while self._running:
            try:
                t = time.time()
                readings = {}
                for ch in self.ALL_CHANNELS:
                    readings[ch] = self._daq.read_ai_channel(ch)

                with self._lock:
                    self._timestamps.append(t)
                    for ch, val in readings.items():
                        self._buffers[ch].append(val)
                        self._latest[ch] = val

                if self._on_data_callback:
                    self._on_data_callback(readings)

            except Exception as e:
                print(f"[AIReader] 讀取錯誤: {e}")

            time.sleep(self._poll_interval)

    def get_latest(self, channel: int) -> float:
        """
        取得指定通道的最新電壓值
        Args:
            channel: AI 通道編號
        Returns:
            float: 最新電壓值 (V)
        """
        with self._lock:
            return self._latest.get(channel, 0.0)

    def get_all_latest(self) -> dict:
        """
        取得所有通道的最新電壓值
        Returns:
            dict: {channel: voltage}
        """
        with self._lock:
            return dict(self._latest)

    def get_buffer(self, channel: int) -> np.ndarray:
        """
        取得指定通道的波形緩衝資料
        Args:
            channel: AI 通道編號
        Returns:
            np.ndarray: 電壓值陣列
        """
        with self._lock:
            return np.array(list(self._buffers[channel]))

    def get_timestamps(self) -> np.ndarray:
        """取得時間戳記陣列"""
        with self._lock:
            return np.array(list(self._timestamps))

    def get_hall_voltages(self) -> dict:
        """
        取得三相 Hall Sensor 最新電壓
        Returns:
            dict: {"U": v, "V": v, "W": v}
        """
        with self._lock:
            return {
                "U": self._latest[HALL_THRESHOLDS["channels"]["U"]],
                "V": self._latest[HALL_THRESHOLDS["channels"]["V"]],
                "W": self._latest[HALL_THRESHOLDS["channels"]["W"]],
            }

    def get_encoder_voltages(self) -> dict:
        """
        取得 Encoder A/B 最新電壓
        Returns:
            dict: {"A": v, "B": v}
        """
        with self._lock:
            return {
                "A": self._latest[ENCODER_THRESHOLDS["channels"]["A"]],
                "B": self._latest[ENCODER_THRESHOLDS["channels"]["B"]],
            }

    def read_snapshot(self, num_samples: int = 100) -> dict:
        """
        同步讀取指定數量的樣本（用於報表生成）
        Args:
            num_samples: 要讀取的樣本數
        Returns:
            dict: {channel: [voltage_list]}
        """
        data = {ch: [] for ch in self.ALL_CHANNELS}
        for _ in range(num_samples):
            for ch in self.ALL_CHANNELS:
                data[ch].append(self._daq.read_ai_channel(ch))
            time.sleep(self._poll_interval)
        return data

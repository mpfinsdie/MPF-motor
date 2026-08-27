"""
類比輸入讀取模組（InstantAiCtrl 輪詢版）
使用 InstantAiCtrl.readDataF64() 定時輪詢，穩定可靠

架構：
  真實硬體：InstantAiCtrl 輪詢執行緒
    背景執行緒每 10ms 呼叫 readDataF64(0, 5) → 取得 5 通道即時電壓
    → 存入 deque → 觸發 UI callback

  模擬模式：保留舊的輪詢執行緒（無硬體時 UI 測試用）
    time.sleep 輪詢 → _simulate_ai() → deque
"""

import time
import math
import threading
import numpy as np
from collections import deque
from typing import Callable, Optional

from config.thresholds import HALL_THRESHOLDS, ENCODER_THRESHOLDS, SAMPLING


# ─── 通道定義 ───────────────────────────────────────────────────────────────────
_HALL_CHS    = list(HALL_THRESHOLDS["channels"].values())     # [0, 1, 2]
_ENCODER_CHS = list(ENCODER_THRESHOLDS["channels"].values())  # [3, 4]
_ALL_CHS     = _HALL_CHS + _ENCODER_CHS                       # [0, 1, 2, 3, 4]
_CH_COUNT    = len(_ALL_CHS)                                   # 5

_CHANNEL_NAMES = {
    0: "Hall U",
    1: "Hall V",
    2: "Hall W",
    3: "Encoder A",
    4: "Encoder B",
}


class AIReader:
    """
    類比輸入讀取器（InstantAiCtrl 輪詢版）

    真實硬體模式：
      - 背景執行緒每 10ms 呼叫 InstantAiCtrl.readDataF64(0, 5)
      - 取得 5 通道即時電壓後存入 deque 並觸發 UI callback
      - 穩定連續，不受 WaveformAI cycles 限制

    模擬模式：
      - 啟動背景執行緒以 ~100 Hz 產生模擬波形資料
    """

    # 通道常數（供外部參考）
    HALL_CHANNELS    = _HALL_CHS
    ENCODER_CHANNELS = _ENCODER_CHS
    ALL_CHANNELS     = _ALL_CHS
    CHANNEL_NAMES    = _CHANNEL_NAMES

    def __init__(self, daq_controller):
        """
        Args:
            daq_controller: DAQController 實例
        """
        self._daq         = daq_controller
        self._buffer_size = SAMPLING["buffer_size"]

        # 各通道滾動緩衝區
        self._buffers: dict[int, deque] = {
            ch: deque(maxlen=self._buffer_size) for ch in _ALL_CHS
        }
        self._timestamps: deque = deque(maxlen=self._buffer_size)

        # 最新讀值
        self._latest: dict[int, float] = {ch: 0.0 for ch in _ALL_CHS}

        # 執行緒控制
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # 資料更新回呼
        self._on_data_callback: Optional[Callable] = None

    def set_data_callback(self, callback: Callable):
        """設定資料更新回呼函式，每次收到新資料後呼叫"""
        self._on_data_callback = callback

    # ─── 啟動 / 停止 ────────────────────────────────────────────────────────────

    def start(self):
        """啟動 AI 讀取（真實硬體：InstantAI 輪詢；模擬：模擬輪詢）"""
        if self._running:
            return
        self._running = True

        if self._daq.is_simulation:
            self._start_simulation()
        else:
            self._start_instant_ai()

    def stop(self):
        """停止 AI 讀取"""
        if not self._running:
            return
        self._running = False

        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

        if self._daq.is_simulation:
            print("[AIReader] 模擬模式已停止")
        else:
            print("[AIReader] InstantAI 輪詢已停止")

    # ─── 真實硬體：InstantAiCtrl 輪詢 ───────────────────────────────────────────

    def _start_instant_ai(self):
        """啟動 InstantAI 輪詢執行緒"""
        try:
            from Automation.BDaq import ValueRange
            from Automation.BDaq.BDaqApi import BioFailed

            ai = self._daq.get_instant_ai_ctrl()
            if ai is None:
                raise RuntimeError("InstantAiCtrl 未初始化")

            # ── 設定各通道量程 ────────────────────────────────────────────────
            # Hall ch0~2：0~5V 單極性（Hall 3.3V 訊號）
            for i in range(3):
                ai.channels[i].valueRange = ValueRange.V_0To5
            # Encoder ch3~4：0~10V 單極性（Encoder 5V 訊號）
            for i in range(3, 5):
                ai.channels[i].valueRange = ValueRange.V_0To10

            # ── 啟動輪詢執行緒 ────────────────────────────────────────────────
            self._thread = threading.Thread(
                target=self._instant_ai_loop, daemon=True
            )
            self._thread.start()

            print(
                f"[AIReader] InstantAI 輪詢已啟動 | "
                f"通道數: {_CH_COUNT} | "
                f"輪詢間隔: 10ms (100 Hz)"
            )

        except Exception as e:
            print(f"[AIReader] InstantAI 啟動失敗: {e}")
            raise

    def _instant_ai_loop(self):
        """
        InstantAI 輪詢執行緒
        每 10ms 讀取一次 5 通道電壓，存入 deque 並觸發 callback
        """
        from Automation.BDaq.BDaqApi import BioFailed

        ai = self._daq.get_instant_ai_ctrl()
        interval = 0.01  # 10ms = 100 Hz

        while self._running:
            t_start = time.time()
            try:
                ret, data = ai.readDataF64(0, _CH_COUNT)

                if BioFailed(ret) or not data:
                    time.sleep(interval)
                    continue

                t_now = time.time()
                with self._lock:
                    self._timestamps.append(t_now)
                    for col, ch in enumerate(_ALL_CHS):
                        val = float(data[col])
                        self._buffers[ch].append(val)
                        self._latest[ch] = val

                if self._on_data_callback:
                    latest_snapshot = {ch: self._latest[ch] for ch in _ALL_CHS}
                    self._on_data_callback(latest_snapshot)

            except Exception as e:
                if self._running:
                    print(f"[AIReader] InstantAI 讀取錯誤: {e}")

            # 精確控制輪詢間隔
            elapsed = time.time() - t_start
            sleep_time = interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    # ─── 模擬模式：輪詢執行緒 ───────────────────────────────────────────────────

    def _start_simulation(self):
        """啟動模擬模式背景執行緒（約 100 Hz 產生假資料）"""
        self._thread = threading.Thread(target=self._sim_loop, daemon=True)
        self._thread.start()
        print("[AIReader] 模擬模式已啟動（~100 Hz）")

    def _sim_loop(self):
        """模擬模式讀取迴圈（每 10ms 產生一筆資料）"""
        interval = 0.01  # 100 Hz
        while self._running:
            try:
                t = time.time()
                readings = {ch: self._simulate_ai(ch, t) for ch in _ALL_CHS}

                with self._lock:
                    self._timestamps.append(t)
                    for ch, val in readings.items():
                        self._buffers[ch].append(val)
                        self._latest[ch] = val

                if self._on_data_callback:
                    self._on_data_callback(readings)

            except Exception as e:
                print(f"[AIReader] 模擬讀取錯誤: {e}")

            time.sleep(interval)

    def _simulate_ai(self, channel: int, t: float) -> float:
        """模擬 AI 電壓讀取（用於無硬體時測試）"""
        # Hall (ch0~2): 3.3V 方波模擬，三相相差 120 度
        if channel < 3:
            return 3.3 if math.sin(2 * math.pi * 2 * t + channel * 2.094) > 0 else 0.0
        # Encoder A (ch3): 5V 方波模擬
        elif channel == 3:
            return 5.0 if math.sin(2 * math.pi * 10 * t) > 0 else 0.0
        # Encoder B (ch4): 5V 方波模擬，A/B 相差 90 度
        elif channel == 4:
            return 5.0 if math.sin(2 * math.pi * 10 * t - math.pi / 2) > 0 else 0.0
        return 0.0

    # ─── 資料查詢方法 ────────────────────────────────────────────────────────────

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
        從現有緩衝區取最新的 num_samples 筆資料
        Args:
            num_samples: 要讀取的樣本數
        Returns:
            dict: {channel: [voltage_list]}
        """
        with self._lock:
            result = {}
            for ch in _ALL_CHS:
                buf = list(self._buffers[ch])
                result[ch] = buf[-num_samples:] if len(buf) >= num_samples else buf
            return result

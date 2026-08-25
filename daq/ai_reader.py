"""
類比輸入讀取模組（WaveformAiCtrl 版）
使用硬體緩衝串流模式取代 InstantAI 輪詢，大幅提升實際取樣率

架構：
  真實硬體：WaveformAiCtrl 事件驅動
    硬體 ADC → DMA → 環形緩衝 → DataReady 事件 → _on_data_ready() → deque
    取樣率：10,000 Hz/通道，每 0.1s 觸發一次（section_length=1000）

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


# ─── WaveformAI 事件參數物件 ────────────────────────────────────────────────────
# DaqCtrlBase.addEventHandler 要求 userParam 必須有 .Sender 屬性
class _EventParam:
    """addEventHandler 所需的 userParam 物件"""
    Sender = 0


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
    類比輸入讀取器（WaveformAiCtrl 事件驅動版）

    真實硬體模式：
      - 呼叫 start() 後設定 WaveformAiCtrl 參數並啟動硬體串流
      - SDK 每累積 section_length 個點觸發一次 EvtBufferedAiDataReady
      - _on_data_ready() 批次取回資料並解交錯存入 deque

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

        # 執行緒控制（模擬模式用）
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # WaveformAI 事件參數物件（真實硬體用）
        self._event_param: Optional[_EventParam] = None

        # 資料更新回呼
        self._on_data_callback: Optional[Callable] = None

    def set_data_callback(self, callback: Callable):
        """設定資料更新回呼函式，每次收到新資料後呼叫"""
        self._on_data_callback = callback

    # ─── 啟動 / 停止 ────────────────────────────────────────────────────────────

    def start(self):
        """啟動 AI 讀取（真實硬體：WaveformAI 事件驅動；模擬：輪詢執行緒）"""
        if self._running:
            return

        # 必須在啟動執行緒/串流之前設為 True，
        # 否則 _sim_loop() 的 while self._running 在執行緒啟動瞬間就會因 False 而立即結束
        self._running = True

        if self._daq.is_simulation:
            self._start_simulation()
        else:
            self._start_waveform_ai()

    def stop(self):
        """停止 AI 讀取"""
        if not self._running:
            return
        self._running = False

        if self._daq.is_simulation:
            # 停止模擬執行緒
            if self._thread:
                self._thread.join(timeout=2.0)
                self._thread = None
            print("[AIReader] 模擬模式已停止")
        else:
            # 停止 WaveformAI 串流
            try:
                wfm = self._daq.get_wfm_ai_ctrl()
                if wfm is not None:
                    wfm.stop()
                    if self._event_param is not None:
                        try:
                            from Automation.BDaq import EventId
                            wfm.removeEventHandler(
                                EventId.EvtBufferedAiDataReady,
                                self._on_data_ready,
                                self._event_param
                            )
                        except Exception:
                            pass
            except Exception as e:
                print(f"[AIReader] 停止 WaveformAI 時發生錯誤: {e}")
            print("[AIReader] WaveformAI 已停止")

    # ─── 真實硬體：WaveformAiCtrl 設定與啟動 ────────────────────────────────────

    def _start_waveform_ai(self):
        """設定並啟動 WaveformAiCtrl 硬體串流"""
        try:
            from Automation.BDaq import EventId, ValueRange
            from Automation.BDaq.BDaqApi import BioFailed

            wfm = self._daq.get_wfm_ai_ctrl()
            if wfm is None:
                raise RuntimeError("WaveformAiCtrl 未初始化")

            # ── 設定取樣參數 ──────────────────────────────────────────────────
            conv = wfm.conversion
            conv.channelStart = 0
            conv.channelCount = _CH_COUNT                          # 5 通道 (ch0~ch4)
            conv.clockRate    = float(SAMPLING["ai_sample_rate"])  # 10,000 Hz/通道

            # ── 設定環形緩衝區 ────────────────────────────────────────────────
            rec = wfm.record
            rec.sectionLength = SAMPLING["section_length"]  # 1000 點/通道/section
            rec.sectionCount  = SAMPLING["section_count"]   # 4 sections 環形緩衝
            rec.cycles        = 0                           # 0 = 連續採集

            # ── 設定各通道量程 ────────────────────────────────────────────────
            # Hall ch0~2：0~5V 單極性（Hall 3.3V 訊號）
            for i in range(3):
                wfm.channels[i].valueRange = ValueRange.V_0To5
            # Encoder ch3~4：0~10V 單極性（Encoder 5V 訊號）
            for i in range(3, 5):
                wfm.channels[i].valueRange = ValueRange.V_0To10

            # ── 註冊 DataReady 事件 ───────────────────────────────────────────
            self._event_param = _EventParam()
            wfm.addEventHandler(
                EventId.EvtBufferedAiDataReady,
                self._on_data_ready,
                self._event_param
            )

            # ── 準備並啟動 ────────────────────────────────────────────────────
            ret = wfm.prepare()
            if BioFailed(ret):
                raise RuntimeError(f"WaveformAI prepare 失敗，錯誤碼: 0x{ret.value:X}")

            ret = wfm.start()
            if BioFailed(ret):
                raise RuntimeError(f"WaveformAI start 失敗，錯誤碼: 0x{ret.value:X}")

            print(
                f"[AIReader] WaveformAI 已啟動 | "
                f"取樣率: {SAMPLING['ai_sample_rate']} Hz/ch | "
                f"通道數: {_CH_COUNT} | "
                f"DataReady 間隔: {SAMPLING['section_length'] / SAMPLING['ai_sample_rate'] * 1000:.0f} ms"
            )

        except Exception as e:
            print(f"[AIReader] WaveformAI 啟動失敗: {e}")
            raise

    # ─── WaveformAI DataReady 事件回呼 ──────────────────────────────────────────

    def _on_data_ready(self, sender, args, userParam):
        """
        硬體每累積 section_length 個點觸發一次（約每 100ms）
        資料格式（交錯）：[ch0_s0, ch1_s0, ch2_s0, ch3_s0, ch4_s0,
                           ch0_s1, ch1_s1, ch2_s1, ch3_s1, ch4_s1, ...]
        每次取回 section_length × ch_count = 1000 × 5 = 5000 個 F64 值
        """
        try:
            from Automation.BDaq.BDaqApi import BioFailed

            wfm = self._daq.get_wfm_ai_ctrl()
            if wfm is None:
                return

            count = SAMPLING["section_length"] * _CH_COUNT  # 5000

            ret, returned, data, *_ = wfm.getDataF64(count, timeout=500)
            if BioFailed(ret) or returned == 0:
                if BioFailed(ret):
                    print(f"[AIReader] getDataF64 失敗，錯誤碼: 0x{ret.value:X}")
                return

            # 解交錯：將 1D 陣列重塑為 (樣本數, 通道數)
            actual_samples = returned // _CH_COUNT
            if actual_samples == 0:
                return

            arr = np.array(data[:actual_samples * _CH_COUNT], dtype=np.float64)
            arr = arr.reshape(actual_samples, _CH_COUNT)

            # 產生對應時間戳（等間距，以當前時間為基準往前推算）
            t_now = time.time()
            dt = 1.0 / SAMPLING["ai_sample_rate"]
            timestamps = [t_now - (actual_samples - 1 - i) * dt for i in range(actual_samples)]

            with self._lock:
                self._timestamps.extend(timestamps)
                for col, ch in enumerate(_ALL_CHS):
                    self._buffers[ch].extend(arr[:, col].tolist())
                    self._latest[ch] = float(arr[-1, col])

            if self._on_data_callback:
                latest_snapshot = {ch: self._latest[ch] for ch in _ALL_CHS}
                self._on_data_callback(latest_snapshot)

        except Exception as e:
            print(f"[AIReader] DataReady 回呼錯誤: {e}")

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

"""
類比輸入讀取模組（InstantAiCtrl 輪詢版）
使用 InstantAiCtrl.readDataF64() 定時輪詢，穩定可靠

架構：
  真實硬體：InstantAiCtrl 輪詢執行緒
    背景執行緒每 10ms 呼叫 readDataF64(start, count) → 取得涵蓋範圍通道即時電壓
    → 從中取出所需通道 → 存入 deque → 觸發 UI callback

  模擬模式：保留舊的輪詢執行緒（無硬體時 UI 測試用）
    time.sleep 輪詢 → _simulate_ai() → deque

通道對應：
  由 config.channel_config.CHANNEL_CONFIG 動態提供，使用者可透過 UI
  「硬體通道設定」或直接編輯 config/channel_map.json 調整 AI 通道，
  不再固定為 AI0~4。呼叫 refresh_channels() 可於執行期套用新設定。
"""

import time
import math
import threading
import numpy as np
from collections import deque
from typing import Callable, Optional

from config.thresholds import HALL_THRESHOLDS, ENCODER_THRESHOLDS, SAMPLING
from config.channel_config import CHANNEL_CONFIG


class AIReader:
    """
    類比輸入讀取器（InstantAiCtrl 輪詢版）

    真實硬體模式：
      - 背景執行緒每 10ms 呼叫 InstantAiCtrl.readDataF64(start, count)
        （start~count 涵蓋所有使用者設定的 AI 通道）
      - 取得涵蓋範圍電壓後取出所需通道存入 deque 並觸發 UI callback
      - 穩定連續，不受 WaveformAI cycles 限制

    模擬模式：
      - 啟動背景執行緒以 ~100 Hz 產生模擬波形資料

    通道對應由 CHANNEL_CONFIG 動態提供，可用 refresh_channels() 熱更新。
    """

    def __init__(self, daq_controller):
        """
        Args:
            daq_controller: DAQController 實例
        """
        self._daq         = daq_controller
        self._buffer_size = SAMPLING["buffer_size"]

        # 執行緒控制
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # 資料更新回呼
        self._on_data_callback: Optional[Callable] = None

        # 依 CHANNEL_CONFIG 建立通道結構
        self._build_channel_state()

    # ─── 通道結構建立 / 熱更新 ──────────────────────────────────────────────────

    def _build_channel_state(self):
        """
        依 CHANNEL_CONFIG 目前設定建立通道清單、緩衝區與讀取範圍。

        通道可能非連續（例如使用者設定 AI0,1,2,5,6），因此以 min~max
        涵蓋範圍呼叫 readDataF64，再依實際通道編號取值。
        """
        self._hall_chs    = [CHANNEL_CONFIG.hall_ai(s) for s in ("U", "V", "W")]
        self._encoder_chs = [CHANNEL_CONFIG.encoder_ai(s) for s in ("A", "B")]
        self._all_chs     = self._hall_chs + self._encoder_chs

        # 讀取涵蓋範圍（含中間未使用的通道，一次讀取後再挑選）
        self._read_start = min(self._all_chs)
        self._read_count = max(self._all_chs) - self._read_start + 1

        self._channel_names = CHANNEL_CONFIG.channel_names()

        # 各通道滾動緩衝區
        self._buffers: dict[int, deque] = {
            ch: deque(maxlen=self._buffer_size) for ch in self._all_chs
        }
        self._timestamps: deque = deque(maxlen=self._buffer_size)

        # 最新讀值
        self._latest: dict[int, float] = {ch: 0.0 for ch in self._all_chs}

    def refresh_channels(self):
        """
        於執行期套用新的通道設定（使用者透過 UI 修改通道後呼叫）。

        會停止目前讀取（若正在執行）、重建通道結構，並在真實硬體模式下
        重新設定量程後重啟輪詢。
        """
        was_running = self._running
        if was_running:
            self.stop()
        with self._lock:
            self._build_channel_state()
        print(
            f"[AIReader] 通道設定已更新 | "
            f"Hall AI={self._hall_chs} | Encoder AI={self._encoder_chs}"
        )
        if was_running:
            self.start()

    # 相容屬性（供外部參考目前通道）
    @property
    def HALL_CHANNELS(self):
        return self._hall_chs

    @property
    def ENCODER_CHANNELS(self):
        return self._encoder_chs

    @property
    def ALL_CHANNELS(self):
        return self._all_chs

    @property
    def CHANNEL_NAMES(self):
        return self._channel_names

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
            from Automation.BDaq.BDaqApi import BioFailed

            ai = self._daq.get_instant_ai_ctrl()
            if ai is None:
                raise RuntimeError("InstantAiCtrl 未初始化")

            # ── 設定各通道量程（依 CHANNEL_CONFIG）────────────────────────────
            # Hall 通道：hall 量程（預設 0~5V，Hall 3.3V 訊號）
            hall_vr = CHANNEL_CONFIG.value_range("hall")
            for ch in self._hall_chs:
                ai.channels[ch].valueRange = hall_vr
            # Encoder 通道：encoder 量程（預設 0~10V，Encoder 5V 訊號）
            enc_vr = CHANNEL_CONFIG.value_range("encoder")
            for ch in self._encoder_chs:
                ai.channels[ch].valueRange = enc_vr

            # ── 啟動輪詢執行緒 ────────────────────────────────────────────────
            self._thread = threading.Thread(
                target=self._instant_ai_loop, daemon=True
            )
            self._thread.start()

            print(
                f"[AIReader] InstantAI 輪詢已啟動 | "
                f"通道: {self._all_chs} | "
                f"讀取範圍: start={self._read_start}, count={self._read_count} | "
                f"輪詢間隔: 10ms (100 Hz)"
            )

        except Exception as e:
            print(f"[AIReader] InstantAI 啟動失敗: {e}")
            raise

    def _instant_ai_loop(self):
        """
        InstantAI 輪詢執行緒
        每 10ms 讀取一次涵蓋範圍通道電壓，取出所需通道存入 deque 並觸發 callback
        """
        from Automation.BDaq.BDaqApi import BioFailed

        ai = self._daq.get_instant_ai_ctrl()
        interval = 0.01  # 10ms = 100 Hz

        while self._running:
            t_start = time.time()
            try:
                ret, data = ai.readDataF64(self._read_start, self._read_count)

                if BioFailed(ret) or not data:
                    time.sleep(interval)
                    continue

                t_now = time.time()
                with self._lock:
                    self._timestamps.append(t_now)
                    for ch in self._all_chs:
                        # data 索引 = 實際通道 - 讀取起始通道
                        col = ch - self._read_start
                        val = float(data[col])
                        self._buffers[ch].append(val)
                        self._latest[ch] = val

                if self._on_data_callback:
                    latest_snapshot = {ch: self._latest[ch] for ch in self._all_chs}
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
                readings = {ch: self._simulate_ai(ch, t) for ch in self._all_chs}

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
        """
        模擬 AI 電壓讀取（用於無硬體時測試）

        依通道所屬類型（Hall / Encoder）產生對應模擬波形，
        不再依賴固定通道編號，支援使用者自訂通道。
        """
        # Hall 通道：3.3V 方波，三相相差 120 度
        if channel in self._hall_chs:
            phase_idx = self._hall_chs.index(channel)
            return 3.3 if math.sin(2 * math.pi * 2 * t + phase_idx * 2.094) > 0 else 0.0
        # Encoder 通道：5V 方波，A/B 相差 90 度
        elif channel in self._encoder_chs:
            enc_idx = self._encoder_chs.index(channel)
            phase = 0.0 if enc_idx == 0 else -math.pi / 2
            return 5.0 if math.sin(2 * math.pi * 10 * t + phase) > 0 else 0.0
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
            np.ndarray: 電壓值陣列（通道不存在時回傳空陣列）
        """
        with self._lock:
            if channel not in self._buffers:
                return np.array([])
            return np.array(list(self._buffers[channel]))

    def get_timestamps(self) -> np.ndarray:
        """取得時間戳記陣列"""
        with self._lock:
            return np.array(list(self._timestamps))

    def clear_buffers(self):
        """清除所有通道的波形緩衝與最新讀值（不影響讀取執行緒運行）"""
        with self._lock:
            for ch in self._all_chs:
                self._buffers[ch].clear()
                self._latest[ch] = 0.0
            self._timestamps.clear()
        print("[AIReader] 波形緩衝已清除")

    def get_hall_voltages(self) -> dict:
        """
        取得三相 Hall Sensor 最新電壓
        Returns:
            dict: {"U": v, "V": v, "W": v}
        """
        with self._lock:
            return {
                "U": self._latest.get(CHANNEL_CONFIG.hall_ai("U"), 0.0),
                "V": self._latest.get(CHANNEL_CONFIG.hall_ai("V"), 0.0),
                "W": self._latest.get(CHANNEL_CONFIG.hall_ai("W"), 0.0),
            }

    def get_encoder_voltages(self) -> dict:
        """
        取得 Encoder A/B 最新電壓
        Returns:
            dict: {"A": v, "B": v}
        """
        with self._lock:
            return {
                "A": self._latest.get(CHANNEL_CONFIG.encoder_ai("A"), 0.0),
                "B": self._latest.get(CHANNEL_CONFIG.encoder_ai("B"), 0.0),
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
            for ch in self._all_chs:
                buf = list(self._buffers[ch])
                result[ch] = buf[-num_samples:] if len(buf) >= num_samples else buf
            return result

"""
類比輸入讀取模組（WaveformAiCtrl 多通道連續串流版）

架構：
  真實硬體：WaveformAiCtrl 多通道硬體 DMA 連續串流
    conversion.channelStart/channelCount 涵蓋所有使用者 AI 通道（min~max 範圍），
    conversion.clockRate = ai_sample_rate（每通道 50kHz），
    record.sectionLength = monitor_chunk_size（每通道分段點數），sectionCount = 0（無限循環）。
    背景執行緒每次 getDataF64 取回一段「交錯（interleaved）」資料，
    解交錯後依實際通道編號存入各自 deque 並觸發 UI callback。

  模擬模式：背景執行緒以相同節奏分段產生模擬波形資料（每通道 50kHz）。

即時監控範圍：
  即時監控僅量測三相 Hall（U/V/W），Encoder 與 DI 已於監控模式移除。
  H/L/X 準位判斷改由 AI 類比電壓直接判定（不再依賴 DI 數位訊號）。
  Encoder 量測與比值交叉驗證仍保留於「高取樣診斷」模式，不受此影響。

通道對應：
  由 config.channel_config.CHANNEL_CONFIG 動態提供，使用者可透過 UI
  「硬體通道設定」或直接編輯 config/channel_map.json 調整 Hall AI 通道。
  呼叫 refresh_channels() 可於執行期套用新設定。
"""

import time
import math
import threading
import numpy as np
from collections import deque
from typing import Callable, Optional

from config.thresholds import HALL_THRESHOLDS, SAMPLING
from config.channel_config import CHANNEL_CONFIG


class AIReader:
    """
    類比輸入讀取器（WaveformAiCtrl 多通道連續串流版）

    真實硬體模式：
      - 建立監控用 WaveformAiCtrl，設定多通道 conversion 與 record 後啟動硬體串流
      - 背景執行緒分段 getDataF64 取回交錯資料，解交錯分配至各通道 deque
      - 每個 Hall 通道實際以 ai_sample_rate（50kHz）硬體採樣

    模擬模式：
      - 啟動背景執行緒以相同節奏產生模擬波形資料（每通道 50kHz）

    僅讀取三相 Hall（U/V/W），通道對應由 CHANNEL_CONFIG 動態提供，
    可用 refresh_channels() 熱更新。
    """

    def __init__(self, daq_controller):
        """
        Args:
            daq_controller: DAQController 實例
        """
        self._daq         = daq_controller
        self._buffer_size  = SAMPLING["buffer_size"]
        self._sample_rate  = SAMPLING["ai_sample_rate"]        # 每通道取樣率 (Hz)，20kHz
        self._chunk_size   = SAMPLING["monitor_chunk_size"]    # 每通道每段點數，2000
        self._section_len  = SAMPLING["section_length"]        # 每通道 section 長度
        self._section_cnt  = SAMPLING["section_count"]

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

        即時監控僅讀取三相 Hall（U/V/W）。通道可能非連續
        （例如使用者設定 AI0,1,5），因此以 min~max 涵蓋範圍設定
        WaveformAiCtrl 的 channelStart/channelCount，取回交錯資料後
        再依實際通道編號解交錯取值。
        """
        self._hall_chs    = [CHANNEL_CONFIG.hall_ai(s) for s in ("U", "V", "W")]
        self._all_chs     = list(self._hall_chs)

        # 掃描涵蓋範圍（含中間未使用的通道，硬體連續掃描後再解交錯挑選）
        self._scan_start = min(self._all_chs)
        self._scan_count = max(self._all_chs) - self._scan_start + 1

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
        重新以新通道範圍設定 WaveformAiCtrl 後重啟串流。
        """
        was_running = self._running
        if was_running:
            self.stop()
        with self._lock:
            self._build_channel_state()
        print(
            f"[AIReader] 通道設定已更新 | Hall AI={self._hall_chs}"
        )
        if was_running:
            self.start()

    # 相容屬性（供外部參考目前通道）
    @property
    def HALL_CHANNELS(self):
        return self._hall_chs

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
        """啟動 AI 讀取（真實硬體：WaveformAI 多通道串流；模擬：模擬串流）"""
        if self._running:
            return
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

        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

        if self._daq.is_simulation:
            print("[AIReader] 模擬模式已停止")
        else:
            # 釋放監控用 WaveformAiCtrl（讓後續診斷 / InstantAI 可獨占硬體）
            try:
                self._daq.release_monitor_wfm_ctrl()
            except Exception as e:
                print(f"[AIReader] 釋放監控 WaveformAiCtrl 失敗: {e}")
            print("[AIReader] WaveformAI 多通道串流已停止")

    # ─── 真實硬體：WaveformAiCtrl 多通道連續串流 ────────────────────────────────

    def _start_waveform_ai(self):
        """建立並啟動監控用 WaveformAiCtrl 多通道連續串流"""
        try:
            from Automation.BDaq.BDaqApi import BioFailed

            wfm = self._daq.create_monitor_wfm_ctrl()
            if wfm is None:
                raise RuntimeError("監控 WaveformAiCtrl 未建立")

            # ── 設定各通道量程（依 CHANNEL_CONFIG）────────────────────────────
            hall_vr = CHANNEL_CONFIG.value_range("hall")
            for ch in self._hall_chs:
                wfm.channels[ch].valueRange = hall_vr

            # ── 設定 conversion（多通道掃描）──────────────────────────────────
            # clockRate 為每通道取樣率；clamp 確保不超過硬體上限
            # 硬體總取樣率 = clockRate × channelCount，須在硬體總頻寬內
            actual_rate = self._daq.clamp_clock_rate(float(self._sample_rate))
            conv = wfm.conversion
            conv.channelStart = self._scan_start
            conv.channelCount = self._scan_count
            conv.clockRate    = actual_rate
            self._actual_rate = actual_rate

            # ── 設定 record（環形緩衝，無限循環）──────────────────────────────
            rec = wfm.record
            rec.sectionLength = self._chunk_size   # 每通道每段點數
            rec.sectionCount  = 0                  # 0 = 無限循環，不自動停止

            # ── prepare & start ──────────────────────────────────────────────
            err = wfm.prepare()
            if BioFailed(err):
                raise RuntimeError(f"監控 WaveformAiCtrl.prepare 失敗: {err}")

            err = wfm.start()
            if BioFailed(err):
                raise RuntimeError(f"監控 WaveformAiCtrl.start 失敗: {err}")

            # ── 啟動讀取執行緒 ────────────────────────────────────────────────
            self._thread = threading.Thread(
                target=self._waveform_ai_loop, daemon=True
            )
            self._thread.start()

            print(
                f"[AIReader] WaveformAI 多通道串流已啟動 | "
                f"通道: {self._all_chs} | "
                f"掃描範圍: start={self._scan_start}, count={self._scan_count} | "
                f"每通道取樣率: {actual_rate:,.0f} Hz | "
                f"chunk: {self._chunk_size} 點/通道 "
                f"({self._chunk_size / actual_rate * 1000:.1f}ms/段)"
            )

        except Exception as e:
            print(f"[AIReader] WaveformAI 啟動失敗: {e}")
            self._running = False
            try:
                self._daq.release_monitor_wfm_ctrl()
            except Exception:
                pass
            raise

    def _waveform_ai_loop(self):
        """
        WaveformAI 多通道串流讀取執行緒

        每次 getDataF64 取回一段交錯（interleaved）資料，長度 =
        chunk_size × scan_count，依 scan_count 解交錯後取出所需通道存入 deque。
        """
        from Automation.BDaq.BDaqApi import BioFailed

        wfm = self._daq.get_monitor_wfm_ctrl()
        if wfm is None:
            print("[AIReader] 讀取執行緒啟動失敗：WaveformAiCtrl 為 None")
            self._running = False
            return

        total_count = self._chunk_size * self._scan_count
        # timeout = chunk 採集時間 × 5 倍安全係數
        chunk_duration_ms = self._chunk_size / self._actual_rate * 1000.0
        timeout_ms = max(500, int(chunk_duration_ms * 5))

        while self._running:
            try:
                err, returned, data, *_ = wfm.getDataF64(total_count, timeout_ms)

                if BioFailed(err) or returned == 0 or not data:
                    continue

                # 解交錯：data 為 [ch0,ch1,...,chN, ch0,ch1,...] 排列
                # 完整掃描組數 = returned // scan_count
                arr = np.asarray(data[:returned], dtype=np.float32)
                groups = returned // self._scan_count
                if groups == 0:
                    continue
                arr = arr[:groups * self._scan_count].reshape(groups, self._scan_count)

                t_now = time.time()
                with self._lock:
                    self._timestamps.append(t_now)
                    for ch in self._all_chs:
                        col = ch - self._scan_start        # 交錯欄位索引
                        samples = arr[:, col]
                        self._buffers[ch].extend(samples.tolist())
                        self._latest[ch] = float(samples[-1])

                if self._on_data_callback:
                    latest_snapshot = {ch: self._latest[ch] for ch in self._all_chs}
                    self._on_data_callback(latest_snapshot)

            except Exception as e:
                if self._running:
                    print(f"[AIReader] WaveformAI 讀取錯誤: {e}")
                    time.sleep(0.05)

    # ─── 模擬模式：多通道串流 ───────────────────────────────────────────────────

    def _start_simulation(self):
        """啟動模擬模式背景執行緒（每通道 20kHz，分段產生假資料）"""
        self._actual_rate = float(self._sample_rate)
        self._thread = threading.Thread(target=self._sim_loop, daemon=True)
        self._thread.start()
        print(
            f"[AIReader] 模擬模式已啟動（每通道 {self._sample_rate:,} Hz，"
            f"{self._chunk_size} 點/段）"
        )

    def _sim_loop(self):
        """
        模擬模式讀取迴圈（每段產生 chunk_size 點/通道，節奏對齊硬體）
        """
        chunk_duration = self._chunk_size / self._sample_rate  # 0.1 秒/段
        t_base = time.time()
        sample_idx = 0

        while self._running:
            # 等待一段時間模擬硬體採樣節奏
            time.sleep(chunk_duration)
            if not self._running:
                break

            try:
                # 產生本段每通道 chunk_size 點的時間軸
                t_start = sample_idx / self._sample_rate
                t_arr = t_start + np.arange(self._chunk_size) / self._sample_rate
                sample_idx += self._chunk_size

                t_now = time.time()
                with self._lock:
                    self._timestamps.append(t_now)
                    for ch in self._all_chs:
                        samples = self._simulate_ai_chunk(ch, t_arr)
                        self._buffers[ch].extend(samples.tolist())
                        self._latest[ch] = float(samples[-1])

                if self._on_data_callback:
                    snapshot = {ch: self._latest[ch] for ch in self._all_chs}
                    self._on_data_callback(snapshot)

            except Exception as e:
                print(f"[AIReader] 模擬讀取錯誤: {e}")

    def _simulate_ai_chunk(self, channel: int, t_arr: np.ndarray) -> np.ndarray:
        """
        向量化產生一段模擬 AI 電壓（用於無硬體時測試）

        僅模擬三相 Hall 方波，不再依賴固定通道編號，支援使用者自訂通道。
        """
        # Hall 通道：3.3V 方波，三相相差 120 度，基頻 2 Hz
        if channel in self._hall_chs:
            phase_idx = self._hall_chs.index(channel)
            wave = np.sin(2 * math.pi * 2 * t_arr + phase_idx * 2.094)
            return np.where(wave > 0, 3.3, 0.0).astype(np.float32)
        return np.zeros(len(t_arr), dtype=np.float32)

    def _simulate_ai(self, channel: int, t: float) -> float:
        """
        模擬單一取樣點（相容保留，供其他模組呼叫）
        """
        arr = self._simulate_ai_chunk(channel, np.array([t], dtype=np.float64))
        return float(arr[0])

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
        """取得時間戳記陣列（每段一個，非每點）"""
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

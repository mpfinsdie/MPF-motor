"""
高取樣率診斷掃描器模組

功能：
  - 一次專注採樣 1 個 AI 通道，以 200kHz 連續採 10 秒
  - 依序輪流 CH0→CH1→CH2→CH3→CH4，跑滿 2 輪後自動結束
  - 支援使用者提早結束
  - 每 0.1 秒（20,000 點）分段串流回呼，供 UI 即時繪製波形
  - 全部資料合併存成單一 .npz 檔案，含 metadata

資料量估算（200kHz × 10s × 5CH × 2輪）：
  每通道：200,000 × 10 = 2,000,000 點 ≈ 7.6 MB (float32)
  全部：  5 × 2 × 7.6 MB ≈ 76 MB（壓縮後約 10~20 MB）

架構：
  真實硬體：WaveformAiCtrl 單通道高速採樣
    conversion.channelStart = ch, channelCount = 1
    conv.clockRate = clamp(sample_rate, hw_max)  ← 自動 clamp 至硬體上限
    record.sectionLength = chunk_size (20000), sectionCount = section_count (8)
    prepare → start → getDataF64(chunk_size) × N → stop → release

  模擬模式：背景執行緒以相同節奏產生假波形資料

回呼介面：
  chunk_callback(ch_idx, round_idx, chunk_data, elapsed_s)
    → 每段 chunk 資料（20,000 點，約 0.1s），供 UI 即時繪製
  progress_callback(ch_idx, round_idx, elapsed_s, remaining_s, ch_name)
    → 每段更新進度資訊
  done_callback(result_dict)
    → 診斷完成，result_dict 含 npz 路徑與 metadata
"""

import time
import math
import threading
import numpy as np
from pathlib import Path
from typing import Callable, Optional, List, Dict, Any
import sys

from config.thresholds import DIAGNOSTIC, HALL_THRESHOLDS, ENCODER_THRESHOLDS


def _get_diag_dir() -> Path:
    """取得診斷 npz 儲存目錄（支援打包執行檔模式）"""
    if getattr(sys, 'frozen', False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).parent.parent
    return base / DIAGNOSTIC["diag_dir"]


# ─── 通道閾值對照（從 thresholds 動態填入）────────────────────────────────────
def _build_channel_list() -> List[Dict[str, Any]]:
    """建立診斷通道清單，填入對應閾值"""
    channels = []
    for ch_def in DIAGNOSTIC["channels"]:
        ch = dict(ch_def)
        idx = ch["ch"]
        if idx < 3:  # Hall U/V/W
            ch["vh_min"] = HALL_THRESHOLDS["vh_min"]
            ch["vl_max"] = HALL_THRESHOLDS["vl_max"]
        else:        # Encoder A/B
            ch["vh_min"] = ENCODER_THRESHOLDS["vh_min"]
            ch["vl_max"] = ENCODER_THRESHOLDS["vl_max"]
        channels.append(ch)
    return channels


class DiagnosticScanner:
    """
    高取樣率診斷掃描器

    使用方式：
        scanner = DiagnosticScanner(daq_controller)
        scanner.set_chunk_callback(on_chunk)       # 每段資料回呼（即時繪波）
        scanner.set_progress_callback(on_progress) # 進度回呼
        scanner.set_done_callback(on_done)         # 完成回呼
        scanner.start()
        # 使用者提早結束：
        scanner.stop()
    """

    def __init__(self, daq_controller):
        """
        Args:
            daq_controller: DAQController 實例（已進入診斷模式）
        """
        self._daq = daq_controller
        self._channels = _build_channel_list()
        self._ch_count  = len(self._channels)

        # 設定參數
        self._sample_rate    = DIAGNOSTIC["sample_rate"]       # 200,000 Hz
        self._seconds_per_ch = DIAGNOSTIC["seconds_per_ch"]    # 10 秒
        self._rounds         = DIAGNOSTIC["rounds"]            # 2 輪
        self._chunk_size     = DIAGNOSTIC["chunk_size"]        # 20,000 點/段（0.1s）
        self._section_count  = DIAGNOSTIC["section_count"]     # 8 sections（0.8s 緩衝）
        self._diag_dir       = _get_diag_dir()

        # 每個 CH 總點數（200,000 Hz × 10s = 2,000,000 點）
        self._total_pts_per_ch = self._sample_rate * self._seconds_per_ch

        # 執行緒控制
        self._running = False
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # 回呼函式
        self._chunk_callback:    Optional[Callable] = None
        self._progress_callback: Optional[Callable] = None
        self._done_callback:     Optional[Callable] = None

        # 結果儲存：results[round_idx][ch_idx] = np.ndarray
        self._results: List[List[Optional[np.ndarray]]] = [
            [None] * self._ch_count for _ in range(self._rounds)
        ]

    # ─── 回呼設定 ──────────────────────────────────────────────────────────────

    def set_chunk_callback(self, callback: Callable):
        """
        設定分段資料回呼（每 chunk_size 點觸發一次）
        callback(ch_idx: int, round_idx: int, chunk: np.ndarray, elapsed_s: float)
        """
        self._chunk_callback = callback

    def set_progress_callback(self, callback: Callable):
        """
        設定進度回呼（每段觸發一次）
        callback(ch_idx: int, round_idx: int, elapsed_s: float,
                 remaining_s: float, ch_name: str)
        """
        self._progress_callback = callback

    def set_done_callback(self, callback: Callable):
        """
        設定完成回呼（診斷結束後觸發）
        callback(result: dict)
          result = {
            'npz_path': str,
            'completed': bool,   # True=跑完2輪, False=提早結束
            'rounds_done': int,
            'channels': list,
          }
        """
        self._done_callback = callback

    # ─── 啟動 / 停止 ────────────────────────────────────────────────────────────

    def start(self):
        """啟動診斷掃描（背景執行緒）"""
        if self._running:
            print("[DiagScanner] 已在執行中，忽略重複啟動")
            return

        self._running = True
        self._stop_event.clear()

        # 清空結果
        self._results = [
            [None] * self._ch_count for _ in range(self._rounds)
        ]

        self._thread = threading.Thread(target=self._scan_loop, daemon=True)
        self._thread.start()
        print(
            f"[DiagScanner] 診斷開始 | "
            f"{self._ch_count} CH × {self._seconds_per_ch}s × {self._rounds} 輪 | "
            f"取樣率 {self._sample_rate} Hz"
        )

    def stop(self):
        """提早停止診斷（使用者主動停止）"""
        if not self._running:
            return
        print("[DiagScanner] 使用者提早停止")
        self._stop_event.set()

    @property
    def is_running(self) -> bool:
        return self._running

    # ─── 主掃描迴圈 ─────────────────────────────────────────────────────────────

    def _scan_loop(self):
        """診斷掃描主迴圈（背景執行緒）"""
        completed = True

        for round_idx in range(self._rounds):
            if self._stop_event.is_set():
                completed = False
                break

            print(f"[DiagScanner] 第 {round_idx + 1}/{self._rounds} 輪開始")

            for ch_idx, ch_def in enumerate(self._channels):
                if self._stop_event.is_set():
                    completed = False
                    break

                ch_num  = ch_def["ch"]
                ch_name = ch_def["name"]
                print(f"[DiagScanner]   CH{ch_num} {ch_name} 開始採樣 {self._seconds_per_ch}s")

                if self._daq.is_simulation:
                    data = self._scan_channel_sim(ch_idx, round_idx, ch_def)
                else:
                    data = self._scan_channel_hw(ch_idx, round_idx, ch_def)

                if data is not None:
                    self._results[round_idx][ch_idx] = data
                    print(
                        f"[DiagScanner]   CH{ch_num} {ch_name} 完成 "
                        f"({len(data)} 點)"
                    )
                else:
                    print(f"[DiagScanner]   CH{ch_num} {ch_name} 採樣中止")
                    completed = False

            if self._stop_event.is_set():
                completed = False
                break

        self._running = False

        # 儲存結果
        npz_path = self._save_results()

        result = {
            "npz_path":       npz_path,
            "completed":      completed,
            "rounds_done":    self._count_rounds_done(),
            "channels":       self._channels,
            "sample_rate":    self._sample_rate,
            "seconds_per_ch": self._seconds_per_ch,
            # 附帶記憶體中的原始資料陣列，供 DiagAnalyzer 直接分析（不需重讀 npz）
            # raw_results[round_idx][ch_idx] = np.ndarray 或 None
            "raw_results":    [list(r) for r in self._results],
        }

        print(
            f"[DiagScanner] 診斷結束 | "
            f"完成={'是' if completed else '否（提早停止）'} | "
            f"npz={npz_path}"
        )

        if self._done_callback:
            try:
                self._done_callback(result)
            except Exception as e:
                print(f"[DiagScanner] done_callback 錯誤: {e}")

    # ─── 真實硬體採樣 ────────────────────────────────────────────────────────────

    def _scan_channel_hw(
        self,
        ch_idx: int,
        round_idx: int,
        ch_def: Dict[str, Any]
    ) -> Optional[np.ndarray]:
        """
        使用 WaveformAiCtrl 採樣單一通道（200kHz 高速模式）

        取樣率會透過 DAQController.clamp_clock_rate() 自動 clamp 至硬體上限，
        確保即使設定值超過硬體能力也不會導致 prepare() 失敗。

        Args:
            ch_idx:   通道索引（0~4）
            round_idx: 輪次索引（0~1）
            ch_def:   通道定義 dict

        Returns:
            np.ndarray: 完整採樣資料（float32），提早停止時回傳已採部分
        """
        try:
            from Automation.BDaq import ValueRange
            from Automation.BDaq.BDaqApi import BioFailed

            wfm = self._daq.get_wfm_ai_ctrl()
            if wfm is None:
                raise RuntimeError("WaveformAiCtrl 未初始化")

            ch_num = ch_def["ch"]

            # ── 設定通道量程 ──────────────────────────────────────────────────
            if ch_num < 3:
                wfm.channels[ch_num].valueRange = ValueRange.V_0To5
            else:
                wfm.channels[ch_num].valueRange = ValueRange.V_0To10

            # ── 設定 conversion（單通道）────────────────────────────────────
            # clamp_clock_rate 確保不超過硬體上限（enter_diag_mode 已查詢）
            actual_rate = self._daq.clamp_clock_rate(float(self._sample_rate))
            conv = wfm.conversion
            conv.channelStart = ch_num
            conv.channelCount = 1
            conv.clockRate    = actual_rate

            # ── 設定 record（環形緩衝，Cyclic 模式）────────────────────────
            # sectionLength 需與 chunk_size 對齊，確保 getDataF64 每次能取到完整段
            # sectionCount = 0 → 無限循環（Cyclic）模式，由程式碼的 chunks_needed
            # 迴圈控制結束時機，避免硬體在 sectionCount 段後自動停止（WarningFuncStopped）
            rec = wfm.record
            rec.sectionLength = self._chunk_size   # 20,000 點/段（0.1s @ 200kHz）
            rec.sectionCount  = 0                  # 0 = 無限循環，不自動停止

            # ── prepare & start ──────────────────────────────────────────────
            err = wfm.prepare()
            if BioFailed(err):
                raise RuntimeError(f"WaveformAiCtrl.prepare 失敗: {err}")

            err = wfm.start()
            if BioFailed(err):
                raise RuntimeError(f"WaveformAiCtrl.start 失敗: {err}")

            print(
                f"[DiagScanner] CH{ch_num} 開始採樣 | "
                f"取樣率: {actual_rate:,.0f} Hz | "
                f"chunk: {self._chunk_size} 點 ({self._chunk_size/actual_rate*1000:.1f}ms/段)"
            )

            # ── 分段讀取 ─────────────────────────────────────────────────────
            all_data = []
            chunks_needed = self._total_pts_per_ch // self._chunk_size
            ch_start_time = time.time()

            for chunk_i in range(chunks_needed):
                if self._stop_event.is_set():
                    break

                # timeout_ms = chunk 採集時間 × 5 倍安全係數
                # 200kHz × 20000 點 = 0.1s → timeout = 500ms
                chunk_duration_ms = self._chunk_size / actual_rate * 1000.0
                timeout_ms = max(500, int(chunk_duration_ms * 5))
                err, returned, data, *_ = wfm.getDataF64(
                    self._chunk_size, timeout_ms
                )

                if BioFailed(err) or returned == 0:
                    print(
                        f"[DiagScanner] getDataF64 失敗或無資料: "
                        f"err={err}, returned={returned}, chunk={chunk_i}"
                    )
                    break

                chunk_arr = np.array(data[:returned], dtype=np.float32)
                all_data.append(chunk_arr)

                elapsed_s   = time.time() - ch_start_time
                remaining_s = max(0.0, self._seconds_per_ch - elapsed_s)

                # 觸發 chunk 回呼（即時繪波）
                if self._chunk_callback:
                    try:
                        self._chunk_callback(ch_idx, round_idx, chunk_arr, elapsed_s)
                    except Exception as e:
                        print(f"[DiagScanner] chunk_callback 錯誤: {e}")

                # 觸發進度回呼
                if self._progress_callback:
                    try:
                        self._progress_callback(
                            ch_idx, round_idx, elapsed_s, remaining_s, ch_def["name"]
                        )
                    except Exception as e:
                        print(f"[DiagScanner] progress_callback 錯誤: {e}")

            # ── stop ─────────────────────────────────────────────────────────
            try:
                wfm.stop()
            except Exception:
                pass

            total_pts = sum(len(d) for d in all_data)
            print(
                f"[DiagScanner] CH{ch_num} 採樣完成 | "
                f"{total_pts:,} 點 | "
                f"{total_pts / actual_rate:.2f}s"
            )
            return np.concatenate(all_data) if all_data else None

        except Exception as e:
            print(f"[DiagScanner] 硬體採樣錯誤 CH{ch_def['ch']}: {e}")
            try:
                wfm = self._daq.get_wfm_ai_ctrl()
                if wfm:
                    wfm.stop()
            except Exception:
                pass
            return None

    # ─── 模擬模式採樣 ────────────────────────────────────────────────────────────

    def _scan_channel_sim(
        self,
        ch_idx: int,
        round_idx: int,
        ch_def: Dict[str, Any]
    ) -> Optional[np.ndarray]:
        """
        模擬模式：以相同節奏分段產生假波形資料

        Args:
            ch_idx:   通道索引
            round_idx: 輪次索引
            ch_def:   通道定義 dict

        Returns:
            np.ndarray: 模擬採樣資料（float32）
        """
        ch_num = ch_def["ch"]
        all_data = []
        chunks_needed = self._total_pts_per_ch // self._chunk_size
        chunk_duration = self._chunk_size / self._sample_rate  # 0.1 秒/段
        ch_start_time = time.time()

        for chunk_i in range(chunks_needed):
            if self._stop_event.is_set():
                break

            # 等待 chunk_duration 秒（模擬硬體採樣節奏）
            self._stop_event.wait(timeout=chunk_duration)
            if self._stop_event.is_set():
                break

            # 產生模擬波形
            t_offset = chunk_i * chunk_duration
            chunk_arr = self._generate_sim_chunk(ch_num, t_offset, round_idx)
            all_data.append(chunk_arr)

            elapsed_s   = time.time() - ch_start_time
            remaining_s = max(0.0, self._seconds_per_ch - elapsed_s)

            # 觸發 chunk 回呼（即時繪波）
            if self._chunk_callback:
                try:
                    self._chunk_callback(ch_idx, round_idx, chunk_arr, elapsed_s)
                except Exception as e:
                    print(f"[DiagScanner] chunk_callback 錯誤: {e}")

            # 觸發進度回呼
            if self._progress_callback:
                try:
                    self._progress_callback(
                        ch_idx, round_idx, elapsed_s, remaining_s, ch_def["name"]
                    )
                except Exception as e:
                    print(f"[DiagScanner] progress_callback 錯誤: {e}")

        return np.concatenate(all_data) if all_data else None

    def _generate_sim_chunk(
        self,
        ch_num: int,
        t_offset: float,
        round_idx: int
    ) -> np.ndarray:
        """
        產生模擬波形 chunk（高取樣率，含雜訊）

        Args:
            ch_num:    AI 通道編號（0~4）
            t_offset:  此 chunk 的起始時間偏移（秒）
            round_idx: 輪次（不同輪次略微不同頻率）

        Returns:
            np.ndarray: float32 陣列，長度 = chunk_size
        """
        t = np.linspace(
            t_offset,
            t_offset + self._chunk_size / self._sample_rate,
            self._chunk_size,
            endpoint=False,
            dtype=np.float64
        )

        # 頻率隨輪次略有不同（模擬真實馬達轉速變化）
        freq_factor = 1.0 + round_idx * 0.05

        if ch_num < 3:
            # Hall U/V/W：3.3V 方波，三相相差 120 度
            phase = ch_num * 2.094  # 120 度
            freq  = 50.0 * freq_factor  # 50 Hz 基頻
            signal = np.where(
                np.sin(2 * math.pi * freq * t + phase) > 0,
                3.3, 0.0
            )
            # 加入上升/下降邊緣模糊（RC 濾波效果）
            noise = np.random.normal(0, 0.02, self._chunk_size)
            signal = signal + noise
            signal = np.clip(signal, 0.0, 3.5).astype(np.float32)

        elif ch_num == 3:
            # Encoder A：5V 方波，較高頻
            freq = 500.0 * freq_factor  # 500 Hz
            signal = np.where(
                np.sin(2 * math.pi * freq * t) > 0,
                5.0, 0.0
            )
            noise = np.random.normal(0, 0.03, self._chunk_size)
            signal = signal + noise
            signal = np.clip(signal, 0.0, 5.5).astype(np.float32)

        else:
            # Encoder B：5V 方波，與 A 相差 90 度
            freq = 500.0 * freq_factor
            signal = np.where(
                np.sin(2 * math.pi * freq * t - math.pi / 2) > 0,
                5.0, 0.0
            )
            noise = np.random.normal(0, 0.03, self._chunk_size)
            signal = signal + noise
            signal = np.clip(signal, 0.0, 5.5).astype(np.float32)

        return signal

    # ─── 結果儲存 ────────────────────────────────────────────────────────────────

    def _save_results(self) -> Optional[str]:
        """
        將所有 CH × 輪次資料合併存成單一 .npz 檔案

        npz 格式：
          ch{i}_round{j}:  np.ndarray float32，長度 = total_pts_per_ch（或更短若提早停止）
                           200kHz × 10s = 2,000,000 點/通道（約 7.6 MB float32）
          sample_rate:     np.array([200000])
          seconds_per_ch:  np.array([10])
          rounds:          np.array([2])
          ch_count:        np.array([5])
          channel_names:   np.array(['Hall U', 'Hall V', ...])
          channel_nums:    np.array([0, 1, 2, 3, 4])
          diag_type:       np.array(['sequential_ch'])  ← 識別為診斷格式

        Returns:
            str: 儲存的檔案路徑，失敗時回傳 None
        """
        try:
            self._diag_dir.mkdir(parents=True, exist_ok=True)

            ts_str   = time.strftime("%Y%m%d_%H%M%S")
            filename = f"diag_{ts_str}.npz"
            filepath = self._diag_dir / filename

            save_dict = {}

            # 各 CH × 輪次資料
            for round_idx in range(self._rounds):
                for ch_idx, ch_def in enumerate(self._channels):
                    key  = f"ch{ch_idx}_round{round_idx}"
                    data = self._results[round_idx][ch_idx]
                    if data is not None:
                        save_dict[key] = data
                    else:
                        # 提早停止時，用空陣列佔位
                        save_dict[key] = np.array([], dtype=np.float32)

            # Metadata
            save_dict["sample_rate"]    = np.array([self._sample_rate],    dtype=np.int32)
            save_dict["seconds_per_ch"] = np.array([self._seconds_per_ch], dtype=np.int32)
            save_dict["rounds"]         = np.array([self._rounds],         dtype=np.int32)
            save_dict["ch_count"]       = np.array([self._ch_count],       dtype=np.int32)
            save_dict["channel_names"]  = np.array(
                [ch["name"] for ch in self._channels]
            )
            save_dict["channel_nums"]   = np.array(
                [ch["ch"] for ch in self._channels], dtype=np.int32
            )
            save_dict["diag_type"]      = np.array(["sequential_ch"])

            np.savez_compressed(str(filepath), **save_dict)

            size_kb = filepath.stat().st_size / 1024
            print(
                f"[DiagScanner] 診斷資料已儲存: {filepath}  "
                f"({size_kb:.1f} KB)"
            )
            return str(filepath)

        except Exception as e:
            print(f"[DiagScanner] 儲存失敗: {e}")
            return None

    # ─── 輔助方法 ────────────────────────────────────────────────────────────────

    def _count_rounds_done(self) -> int:
        """計算已完成的輪數（所有 CH 都有資料才算完成一輪）"""
        done = 0
        for round_idx in range(self._rounds):
            if all(
                self._results[round_idx][ch_idx] is not None
                and len(self._results[round_idx][ch_idx]) > 0
                for ch_idx in range(self._ch_count)
            ):
                done += 1
        return done

    @property
    def channels(self) -> List[Dict[str, Any]]:
        """取得通道定義清單"""
        return self._channels

    @property
    def total_steps(self) -> int:
        """總步驟數（CH 數 × 輪數）"""
        return self._ch_count * self._rounds

    # ─── 靜態工具：載入診斷 npz ─────────────────────────────────────────────────

    @staticmethod
    def load(filepath: str) -> Dict[str, Any]:
        """
        載入診斷 npz 檔案

        Args:
            filepath: .npz 檔案路徑

        Returns:
            dict: {
                'diag_type':      str,
                'sample_rate':    int,
                'seconds_per_ch': int,
                'rounds':         int,
                'ch_count':       int,
                'channel_names':  list[str],
                'channel_nums':   list[int],
                'data':           dict { 'ch{i}_round{j}': np.ndarray }
            }
        """
        raw = np.load(filepath, allow_pickle=True)

        diag_type = str(raw["diag_type"][0]) if "diag_type" in raw else "unknown"
        sample_rate    = int(raw["sample_rate"][0])    if "sample_rate"    in raw else 200_000
        seconds_per_ch = int(raw["seconds_per_ch"][0]) if "seconds_per_ch" in raw else 10
        rounds         = int(raw["rounds"][0])         if "rounds"         in raw else 2
        ch_count       = int(raw["ch_count"][0])       if "ch_count"       in raw else 5
        channel_names  = list(raw["channel_names"])    if "channel_names"  in raw else []
        channel_nums   = list(raw["channel_nums"])     if "channel_nums"   in raw else []

        data = {}
        for round_idx in range(rounds):
            for ch_idx in range(ch_count):
                key = f"ch{ch_idx}_round{round_idx}"
                if key in raw:
                    data[key] = raw[key]

        return {
            "diag_type":      diag_type,
            "sample_rate":    sample_rate,
            "seconds_per_ch": seconds_per_ch,
            "rounds":         rounds,
            "ch_count":       ch_count,
            "channel_names":  channel_names,
            "channel_nums":   channel_nums,
            "data":           data,
        }

    @staticmethod
    def is_diag_npz(filepath: str) -> bool:
        """
        判斷 npz 檔案是否為診斷格式（含 diag_type 欄位）

        Args:
            filepath: .npz 檔案路徑

        Returns:
            bool: True = 診斷格式，False = 舊版 FAIL 波形格式
        """
        try:
            raw = np.load(filepath, allow_pickle=True)
            return "diag_type" in raw
        except Exception:
            return False

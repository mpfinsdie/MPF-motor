"""
波形錄製模組
在測試期間以降頻方式錄製原始 AI 電壓數據
FAIL 時儲存為 .npz 檔案，PASS 時丟棄
"""

import time
import threading
import numpy as np
from pathlib import Path
from typing import Optional
import sys


def _get_waveform_dir() -> Path:
    """取得波形儲存目錄（支援打包執行檔模式）"""
    if getattr(sys, 'frozen', False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).parent.parent
    return base / "data" / "waveforms"


class WaveformRecorder:
    """
    測試期間波形錄製器

    使用方式：
        recorder = WaveformRecorder(downsample_factor=10)
        recorder.start()
        # 在 _update_analysis 迴圈中呼叫：
        recorder.append(hall_u, hall_v, hall_w, enc_a, enc_b)
        # 測試結束後：
        path = recorder.save_if_fail(session_id, stats)  # FAIL 才儲存
        # 或
        recorder.discard()  # PASS 時丟棄

    降頻策略：
        display_update_ms 預設 50ms → 每秒 20 筆
        測試 5 分鐘 = 300 秒 → 最多 6,000 筆
        每筆 5 通道 float32 → 約 120 KB，非常輕量
    """

    def __init__(self, downsample_factor: int = 1, waveform_dir: Optional[Path] = None):
        """
        Args:
            downsample_factor: 降頻倍數（每 N 次 append 才實際儲存一筆）
                               預設 1 = 每次都儲存（display buffer 已是降頻後的資料）
            waveform_dir:      波形檔案儲存目錄（None 使用預設路徑）
        """
        self._downsample_factor = max(1, downsample_factor)
        self._waveform_dir = waveform_dir or _get_waveform_dir()

        # 錄製緩衝區（list，最後轉 numpy）
        self._hall_u: list = []
        self._hall_v: list = []
        self._hall_w: list = []
        self._enc_a:  list = []
        self._enc_b:  list = []
        self._timestamps: list = []

        self._call_count: int = 0
        self._is_recording: bool = False
        self._lock = threading.Lock()

    # ─── 控制方法 ──────────────────────────────────────────────────────────────

    def start(self):
        """開始錄製，清除舊資料"""
        with self._lock:
            self._hall_u.clear()
            self._hall_v.clear()
            self._hall_w.clear()
            self._enc_a.clear()
            self._enc_b.clear()
            self._timestamps.clear()
            self._call_count = 0
            self._is_recording = True
        print("[WaveformRecorder] 開始錄製")

    def stop(self):
        """停止錄製（不清除資料，等待 save_if_fail 或 discard）"""
        with self._lock:
            self._is_recording = False
        print(f"[WaveformRecorder] 停止錄製，共 {len(self._timestamps)} 筆")

    def discard(self):
        """丟棄錄製資料（PASS 時呼叫）"""
        with self._lock:
            self._clear_buffers()
            self._is_recording = False
        print("[WaveformRecorder] 資料已丟棄（PASS）")

    # ─── 資料累積 ──────────────────────────────────────────────────────────────

    def append(
        self,
        hall_u: np.ndarray,
        hall_v: np.ndarray,
        hall_w: np.ndarray,
        enc_a:  np.ndarray,
        enc_b:  np.ndarray,
    ):
        """
        累積一筆波形快照（在 _update_analysis 迴圈中呼叫）
        每次傳入的是當前 display buffer 的完整陣列，
        此處只取最後一個點（最新值）作為時序記錄點。

        Args:
            hall_u: Hall U 電壓陣列（取最後一點）
            hall_v: Hall V 電壓陣列
            hall_w: Hall W 電壓陣列
            enc_a:  Encoder A 電壓陣列
            enc_b:  Encoder B 電壓陣列
        """
        if not self._is_recording:
            return

        with self._lock:
            self._call_count += 1
            if self._call_count % self._downsample_factor != 0:
                return

            # 取最後一個點（最新值）
            def last(arr):
                if arr is None or len(arr) == 0:
                    return 0.0
                return float(arr[-1])

            self._hall_u.append(last(hall_u))
            self._hall_v.append(last(hall_v))
            self._hall_w.append(last(hall_w))
            self._enc_a.append(last(enc_a))
            self._enc_b.append(last(enc_b))
            self._timestamps.append(time.time())

    def append_snapshot(
        self,
        hall_u: float,
        hall_v: float,
        hall_w: float,
        enc_a:  float,
        enc_b:  float,
        ts:     Optional[float] = None,
    ):
        """
        直接累積單點數值（已是純量時使用）

        Args:
            hall_u ~ enc_b: 各通道當前電壓值
            ts: 時間戳（None 使用 time.time()）
        """
        if not self._is_recording:
            return

        with self._lock:
            self._call_count += 1
            if self._call_count % self._downsample_factor != 0:
                return

            self._hall_u.append(float(hall_u))
            self._hall_v.append(float(hall_v))
            self._hall_w.append(float(hall_w))
            self._enc_a.append(float(enc_a))
            self._enc_b.append(float(enc_b))
            self._timestamps.append(ts if ts is not None else time.time())

    # ─── 儲存 ──────────────────────────────────────────────────────────────────

    def save_if_fail(self, session_id: int, overall_pass: bool) -> Optional[str]:
        """
        若 overall_pass=False 則儲存波形檔案，否則丟棄

        Args:
            session_id:   對應的 DB 場次 ID
            overall_pass: 整體判定結果

        Returns:
            str: 儲存的檔案路徑（FAIL 時）
            None: PASS 時或儲存失敗時
        """
        with self._lock:
            self._is_recording = False

            if overall_pass:
                self._clear_buffers()
                print("[WaveformRecorder] PASS，資料已丟棄")
                return None

            if not self._timestamps:
                print("[WaveformRecorder] 無錄製資料，跳過儲存")
                return None

            # 轉換為 numpy 陣列
            hall_u = np.array(self._hall_u, dtype=np.float32)
            hall_v = np.array(self._hall_v, dtype=np.float32)
            hall_w = np.array(self._hall_w, dtype=np.float32)
            enc_a  = np.array(self._enc_a,  dtype=np.float32)
            enc_b  = np.array(self._enc_b,  dtype=np.float32)
            timestamps = np.array(self._timestamps, dtype=np.float64)

            self._clear_buffers()

        # 確保目錄存在
        self._waveform_dir.mkdir(parents=True, exist_ok=True)

        # 檔名：session_{id}_{timestamp}.npz
        ts_str = time.strftime("%Y%m%d_%H%M%S")
        filename = f"session_{session_id}_{ts_str}.npz"
        filepath = self._waveform_dir / filename

        try:
            np.savez_compressed(
                str(filepath),
                hall_u=hall_u,
                hall_v=hall_v,
                hall_w=hall_w,
                enc_a=enc_a,
                enc_b=enc_b,
                timestamps=timestamps,
            )
            print(
                f"[WaveformRecorder] FAIL 波形已儲存: {filepath}  "
                f"({len(timestamps)} 筆, "
                f"{filepath.stat().st_size / 1024:.1f} KB)"
            )
            return str(filepath)
        except Exception as e:
            print(f"[WaveformRecorder] 儲存失敗: {e}")
            return None

    # ─── 查詢 ──────────────────────────────────────────────────────────────────

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    @property
    def sample_count(self) -> int:
        """目前已錄製的樣本數"""
        return len(self._timestamps)

    # ─── 靜態工具 ──────────────────────────────────────────────────────────────

    @staticmethod
    def load(filepath: str) -> dict:
        """
        載入波形檔案

        Args:
            filepath: .npz 檔案路徑

        Returns:
            dict: {
                'hall_u', 'hall_v', 'hall_w': np.ndarray (float32),
                'enc_a', 'enc_b':             np.ndarray (float32),
                'timestamps':                 np.ndarray (float64),
                'duration_s':                 float,
                'sample_count':               int,
            }
        """
        data = np.load(filepath)
        timestamps = data["timestamps"]
        duration_s = float(timestamps[-1] - timestamps[0]) if len(timestamps) > 1 else 0.0

        return {
            "hall_u":       data["hall_u"],
            "hall_v":       data["hall_v"],
            "hall_w":       data["hall_w"],
            "enc_a":        data["enc_a"],
            "enc_b":        data["enc_b"],
            "timestamps":   timestamps,
            "duration_s":   duration_s,
            "sample_count": len(timestamps),
        }

    # ─── 內部方法 ──────────────────────────────────────────────────────────────

    def _clear_buffers(self):
        """清除所有緩衝區（需在 _lock 內呼叫）"""
        self._hall_u.clear()
        self._hall_v.clear()
        self._hall_w.clear()
        self._enc_a.clear()
        self._enc_b.clear()
        self._timestamps.clear()
        self._call_count = 0

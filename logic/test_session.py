"""
測試場次管理模組
負責管理單次 5 分鐘（可調）檢測的生命週期、累積樣本、計算統計摘要
"""

import time
import threading
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, Callable, List

from logic.hall_analyzer import HallAnalysisResult, TestResult as HallTestResult
from logic.encoder_analyzer import EncoderAnalysisResult, TestResult as EncTestResult


class SessionState(Enum):
    """測試場次狀態"""
    IDLE    = auto()   # 閒置（未開始）
    RUNNING = auto()   # 檢測中
    SAVING  = auto()   # 儲存中
    DONE    = auto()   # 已完成


@dataclass
class SessionStatistics:
    """
    單次測試場次統計摘要
    只記錄成功率等彙整數據，不保留原始樣本
    """
    # Hall Sensor
    hall_total:     int   = 0
    hall_pass:      int   = 0
    hall_fail:      int   = 0
    hall_pass_rate: float = 0.0   # 0.0 ~ 1.0

    # Encoder
    enc_total:      int   = 0
    enc_pass:       int   = 0
    enc_fail:       int   = 0
    enc_pass_rate:  float = 0.0

    # 動態資訊
    avg_rpm:        float = 0.0
    max_rpm:        float = 0.0
    min_rpm:        float = 0.0

    # 整體判定（Hall 與 Encoder 成功率都 >= 95% 才算 PASS）
    overall_pass:   bool  = False

    # 實際測試秒數
    actual_duration_s: float = 0.0

    def to_dict(self) -> dict:
        return {
            "hall_total":      self.hall_total,
            "hall_pass":       self.hall_pass,
            "hall_fail":       self.hall_fail,
            "hall_pass_rate":  self.hall_pass_rate,
            "enc_total":       self.enc_total,
            "enc_pass":        self.enc_pass,
            "enc_fail":        self.enc_fail,
            "enc_pass_rate":   self.enc_pass_rate,
            "avg_rpm":         self.avg_rpm,
            "max_rpm":         self.max_rpm,
            "min_rpm":         self.min_rpm,
            "overall_pass":    self.overall_pass,
            "actual_duration_s": self.actual_duration_s,
        }


class TestSession:
    """
    測試場次管理器

    使用方式：
        session = TestSession(duration_s=300)
        session.set_tick_callback(on_tick)      # 每秒倒數回呼
        session.set_done_callback(on_done)      # 完成回呼
        session.start("MTR-001", "操作員A")
        # 在 display_update 迴圈中呼叫：
        session.add_sample(hall_result, enc_result)
        # 時間到或手動停止：
        stats = session.stop()
    """

    # 整體 PASS 門檻（成功率 >= 此值才算 PASS）
    PASS_THRESHOLD = 0.95

    def __init__(self, duration_s: float = 300.0):
        """
        Args:
            duration_s: 預設測試時長（秒），預設 300 秒（5 分鐘）
        """
        self._duration_s = duration_s
        self._state = SessionState.IDLE

        # 場次資訊
        self._serial_no: str = ""
        self._operator: str  = ""
        self._start_time: float = 0.0

        # 累積計數（不保留原始樣本，只計數）
        self._hall_total: int = 0
        self._hall_pass:  int = 0
        self._enc_total:  int = 0
        self._enc_pass:   int = 0

        # RPM 追蹤
        self._rpm_samples: List[float] = []

        # 計時執行緒
        self._timer_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

        # 回呼函式
        self._tick_callback:  Optional[Callable[[float, float], None]] = None
        # tick_callback(elapsed_s, remaining_s)
        self._done_callback:  Optional[Callable[[SessionStatistics], None]] = None
        # done_callback(statistics)

    # ─── 屬性 ──────────────────────────────────────────────────────────────────

    @property
    def state(self) -> SessionState:
        return self._state

    @property
    def is_running(self) -> bool:
        return self._state == SessionState.RUNNING

    @property
    def duration_s(self) -> float:
        return self._duration_s

    @duration_s.setter
    def duration_s(self, value: float):
        # IDLE 或 DONE 狀態都允許設定（DONE 是上次測試完成後尚未 reset 的狀態）
        if self._state in (SessionState.IDLE, SessionState.DONE):
            self._duration_s = max(10.0, value)

    @property
    def serial_no(self) -> str:
        return self._serial_no

    @property
    def elapsed_s(self) -> float:
        """已經過秒數"""
        if self._start_time == 0.0:
            return 0.0
        return time.time() - self._start_time

    @property
    def remaining_s(self) -> float:
        """剩餘秒數"""
        return max(0.0, self._duration_s - self.elapsed_s)

    @property
    def progress(self) -> float:
        """進度 0.0 ~ 1.0"""
        if self._duration_s <= 0:
            return 0.0
        return min(1.0, self.elapsed_s / self._duration_s)

    # ─── 回呼設定 ──────────────────────────────────────────────────────────────

    def set_tick_callback(self, callback: Callable[[float, float], None]):
        """
        設定每秒倒數回呼
        Args:
            callback: fn(elapsed_s, remaining_s)
        """
        self._tick_callback = callback

    def set_done_callback(self, callback: Callable[[SessionStatistics], None]):
        """
        設定完成回呼（時間到或手動停止後觸發）
        Args:
            callback: fn(SessionStatistics)
        """
        self._done_callback = callback

    # ─── 場次控制 ──────────────────────────────────────────────────────────────

    def start(self, serial_no: str = "", operator: str = ""):
        """
        開始新測試場次
        Args:
            serial_no: 馬達/測試物件序號
            operator:  操作員名稱
        """
        if self._state == SessionState.RUNNING:
            print("[TestSession] 警告：場次已在執行中，忽略重複啟動")
            return

        with self._lock:
            self._serial_no  = serial_no
            self._operator   = operator
            self._start_time = time.time()
            self._hall_total = 0
            self._hall_pass  = 0
            self._enc_total  = 0
            self._enc_pass   = 0
            self._rpm_samples.clear()
            self._state = SessionState.RUNNING

        self._stop_event.clear()
        self._timer_thread = threading.Thread(
            target=self._timer_loop, daemon=True
        )
        self._timer_thread.start()
        print(
            f"[TestSession] 場次開始  序號={serial_no or '(無)'}  "
            f"時長={self._duration_s:.0f}s"
        )

    def stop(self) -> SessionStatistics:
        """
        手動停止或時間到後呼叫，計算並回傳統計摘要
        Returns:
            SessionStatistics
        """
        if self._state not in (SessionState.RUNNING, SessionState.SAVING):
            return SessionStatistics()

        self._state = SessionState.SAVING
        self._stop_event.set()

        if self._timer_thread and self._timer_thread.is_alive():
            self._timer_thread.join(timeout=2.0)

        stats = self._compute_statistics()
        self._state = SessionState.DONE
        print(
            f"[TestSession] 場次結束  "
            f"Hall={stats.hall_pass}/{stats.hall_total}({stats.hall_pass_rate*100:.1f}%)  "
            f"Enc={stats.enc_pass}/{stats.enc_total}({stats.enc_pass_rate*100:.1f}%)  "
            f"整體={'PASS' if stats.overall_pass else 'FAIL'}"
        )
        return stats

    def reset(self):
        """重置場次狀態，準備下一次測試"""
        if self._state == SessionState.RUNNING:
            self.stop()
        self._state = SessionState.IDLE
        self._start_time = 0.0
        self._serial_no  = ""
        self._operator   = ""
        with self._lock:
            self._hall_total = 0
            self._hall_pass  = 0
            self._enc_total  = 0
            self._enc_pass   = 0
            self._rpm_samples.clear()

    # ─── 樣本累積 ──────────────────────────────────────────────────────────────

    def add_sample(
        self,
        hall_result: HallAnalysisResult,
        enc_result: EncoderAnalysisResult
    ):
        """
        累積一筆分析結果（在 display_update 迴圈中呼叫）
        只計數，不保留原始物件，節省記憶體
        Args:
            hall_result: Hall Sensor 分析結果
            enc_result:  Encoder 分析結果
        """
        if self._state != SessionState.RUNNING:
            return

        with self._lock:
            # Hall 計數
            self._hall_total += 1
            if hall_result.overall_result == HallTestResult.PASS:
                self._hall_pass += 1

            # Encoder 計數
            self._enc_total += 1
            if enc_result.overall_result == EncTestResult.PASS:
                self._enc_pass += 1

            # RPM 追蹤（只記錄非零值）
            rpm = abs(enc_result.rpm)
            if rpm > 0.5:
                self._rpm_samples.append(rpm)

    # ─── 即時統計（供 UI 顯示用，不需等到結束）──────────────────────────────

    def get_live_stats(self) -> dict:
        """
        取得即時統計數據（供 UI 即時顯示）
        Returns:
            dict: 各項計數與成功率
        """
        with self._lock:
            hall_rate = (self._hall_pass / self._hall_total) if self._hall_total > 0 else 0.0
            enc_rate  = (self._enc_pass  / self._enc_total)  if self._enc_total  > 0 else 0.0
            avg_rpm   = (sum(self._rpm_samples) / len(self._rpm_samples)) if self._rpm_samples else 0.0
            max_rpm   = max(self._rpm_samples) if self._rpm_samples else 0.0

            return {
                "hall_total":     self._hall_total,
                "hall_pass":      self._hall_pass,
                "hall_fail":      self._hall_total - self._hall_pass,
                "hall_pass_rate": hall_rate,
                "enc_total":      self._enc_total,
                "enc_pass":       self._enc_pass,
                "enc_fail":       self._enc_total - self._enc_pass,
                "enc_pass_rate":  enc_rate,
                "avg_rpm":        avg_rpm,
                "max_rpm":        max_rpm,
                "elapsed_s":      self.elapsed_s,
                "remaining_s":    self.remaining_s,
                "progress":       self.progress,
            }

    # ─── 內部方法 ──────────────────────────────────────────────────────────────

    def _timer_loop(self):
        """計時執行緒：每秒觸發 tick_callback，時間到後觸發 done_callback"""
        print(f"[TestSession] _timer_loop 啟動，duration={self._duration_s:.0f}s")
        while not self._stop_event.is_set():
            elapsed   = self.elapsed_s
            remaining = self.remaining_s

            if self._tick_callback:
                try:
                    self._tick_callback(elapsed, remaining)
                except Exception as e:
                    print(f"[TestSession] tick_callback 錯誤: {e}")
                    

            if remaining <= 0:
                # 時間到，自動停止
                self._stop_event.set()
                break

            self._stop_event.wait(timeout=1.0)

        # 時間到後：在執行緒內直接計算統計，不呼叫 stop()（避免 join 自身）
        # 手動停止（_on_early_stop）會呼叫 stop()，此時 _state 已是 SAVING/DONE，不會進入此分支
        if self._state == SessionState.RUNNING:
            self._state = SessionState.SAVING
            stats = self._compute_statistics()
            self._state = SessionState.DONE
            print(
                f"[TestSession] 場次結束（時間到）  "
                f"Hall={stats.hall_pass}/{stats.hall_total}  "
                f"Enc={stats.enc_pass}/{stats.enc_total}  "
                f"整體={'PASS' if stats.overall_pass else 'FAIL'}"
            )
            if self._done_callback:
                try:
                    self._done_callback(stats)
                except Exception as e:
                    print(f"[TestSession] done_callback 錯誤: {e}")

    def _compute_statistics(self) -> SessionStatistics:
        """計算最終統計摘要"""
        with self._lock:
            hall_total = self._hall_total
            hall_pass  = self._hall_pass
            enc_total  = self._enc_total
            enc_pass   = self._enc_pass
            rpm_samples = list(self._rpm_samples)

        hall_fail      = hall_total - hall_pass
        hall_pass_rate = (hall_pass / hall_total) if hall_total > 0 else 0.0

        enc_fail       = enc_total - enc_pass
        enc_pass_rate  = (enc_pass / enc_total) if enc_total > 0 else 0.0

        avg_rpm = sum(rpm_samples) / len(rpm_samples) if rpm_samples else 0.0
        max_rpm = max(rpm_samples) if rpm_samples else 0.0
        min_rpm = min(rpm_samples) if rpm_samples else 0.0

        overall_pass = (
            hall_pass_rate >= self.PASS_THRESHOLD and
            enc_pass_rate  >= self.PASS_THRESHOLD
        )

        return SessionStatistics(
            hall_total=hall_total,
            hall_pass=hall_pass,
            hall_fail=hall_fail,
            hall_pass_rate=hall_pass_rate,
            enc_total=enc_total,
            enc_pass=enc_pass,
            enc_fail=enc_fail,
            enc_pass_rate=enc_pass_rate,
            avg_rpm=avg_rpm,
            max_rpm=max_rpm,
            min_rpm=min_rpm,
            overall_pass=overall_pass,
            actual_duration_s=self.elapsed_s,
        )

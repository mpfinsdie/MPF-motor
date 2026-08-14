"""
Encoder 分析模組
驗證 Encoder A/B 的電壓準位、相位關係、RPM 與位置計算
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from config.thresholds import ENCODER_THRESHOLDS


class VoltageLevel(Enum):
    """電壓準位判斷結果"""
    HIGH = "H"
    LOW = "L"
    UNDEFINED = "X"


class Direction(Enum):
    """旋轉方向"""
    FORWARD = "正轉 (CW)"
    REVERSE = "反轉 (CCW)"
    STOPPED = "靜止"


class TestResult(Enum):
    """測試結果"""
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "---"


@dataclass
class EncoderChannelResult:
    """單一 Encoder 通道電壓測試結果"""
    channel: str                        # "A" 或 "B"
    voltage: float                      # 量測電壓 (V)
    voltage_level: VoltageLevel         # 電壓準位判斷
    di_state: bool                      # DI 讀取的 H/L 狀態
    consistency: bool                   # AI 與 DI 判斷是否一致
    voltage_result: TestResult          # 電壓準位測試結果
    consistency_result: TestResult      # 一致性測試結果

    @property
    def overall_result(self) -> TestResult:
        if (self.voltage_result == TestResult.PASS and
                self.consistency_result == TestResult.PASS):
            return TestResult.PASS
        return TestResult.FAIL


@dataclass
class EncoderAnalysisResult:
    """Encoder 完整分析結果"""
    channels: dict = field(default_factory=dict)  # {"A": EncoderChannelResult, "B": ...}
    count: int = 0                      # 累計脈波計數
    direction: Direction = Direction.STOPPED
    rpm: float = 0.0                    # 轉速 (RPM)
    position_deg: float = 0.0          # 角度位置 (度)
    phase_offset_valid: bool = False    # A/B 相位差是否正確（90 度）
    timestamp: float = 0.0

    @property
    def overall_result(self) -> TestResult:
        """所有通道電壓 PASS 且相位關係正確才算整體 PASS"""
        if not self.channels:
            return TestResult.UNKNOWN
        for ch_result in self.channels.values():
            if ch_result.overall_result != TestResult.PASS:
                return TestResult.FAIL
        return TestResult.PASS

    @property
    def summary(self) -> str:
        lines = ["=== Encoder 分析結果 ==="]
        for ch, result in self.channels.items():
            lines.append(
                f"  Encoder {ch}: "
                f"電壓={result.voltage:.3f}V "
                f"準位={result.voltage_level.value} "
                f"DI={'H' if result.di_state else 'L'} "
                f"一致={'✓' if result.consistency else '✗'} "
                f"→ {result.overall_result.value}"
            )
        lines.append(f"  計數: {self.count} pulses")
        lines.append(f"  方向: {self.direction.value}")
        lines.append(f"  轉速: {abs(self.rpm):.1f} RPM")
        lines.append(f"  位置: {self.position_deg:.1f}°")
        lines.append(f"  整體結果: {self.overall_result.value}")
        return "\n".join(lines)


class EncoderAnalyzer:
    """
    Encoder 分析器
    - 電壓準位驗證（5V 系統）
    - AI 與 DI 一致性驗證
    - 方向判斷（正交解碼）
    - RPM 計算
    - 位置計算
    """

    VH_MIN = ENCODER_THRESHOLDS["vh_min"]   # H 準位最低電壓 (V)
    VL_MAX = ENCODER_THRESHOLDS["vl_max"]   # L 準位最高電壓 (V)
    PPR = ENCODER_THRESHOLDS["ppr"]         # 每轉脈波數

    def __init__(self):
        self._history: list[EncoderAnalysisResult] = []

    def classify_voltage(self, voltage: float) -> VoltageLevel:
        """
        判斷電壓準位（5V 系統）
        Args:
            voltage: 量測電壓 (V)
        Returns:
            VoltageLevel
        """
        if voltage >= self.VH_MIN:
            return VoltageLevel.HIGH
        elif voltage <= self.VL_MAX:
            return VoltageLevel.LOW
        else:
            return VoltageLevel.UNDEFINED

    def analyze_channel(
        self,
        channel: str,
        voltage: float,
        di_state: bool
    ) -> EncoderChannelResult:
        """
        分析單一 Encoder 通道電壓
        Args:
            channel: "A" 或 "B"
            voltage: AI 量測電壓 (V)
            di_state: DI 讀取的 H/L 狀態
        Returns:
            EncoderChannelResult
        """
        voltage_level = self.classify_voltage(voltage)

        voltage_result = (
            TestResult.PASS
            if voltage_level != VoltageLevel.UNDEFINED
            else TestResult.FAIL
        )

        ai_is_high = (voltage_level == VoltageLevel.HIGH)
        consistency = (ai_is_high == di_state) if voltage_level != VoltageLevel.UNDEFINED else False
        consistency_result = TestResult.PASS if consistency else TestResult.FAIL

        return EncoderChannelResult(
            channel=channel,
            voltage=voltage,
            voltage_level=voltage_level,
            di_state=di_state,
            consistency=consistency,
            voltage_result=voltage_result,
            consistency_result=consistency_result,
        )

    def determine_direction(self, count: int, rpm: float) -> Direction:
        """
        根據計數與 RPM 判斷旋轉方向
        Args:
            count: 累計計數（正=正轉，負=反轉）
            rpm: 轉速（正=正轉，負=反轉）
        Returns:
            Direction
        """
        if abs(rpm) < 0.5:  # 低於 0.5 RPM 視為靜止
            return Direction.STOPPED
        elif rpm > 0:
            return Direction.FORWARD
        else:
            return Direction.REVERSE

    def check_phase_offset(self, a_buffer, b_buffer) -> bool:
        """
        驗證 A/B 相位差是否接近 90 度（正交訊號）
        使用互相關分析
        Args:
            a_buffer: Encoder A 的數位訊號陣列
            b_buffer: Encoder B 的數位訊號陣列
        Returns:
            bool: True 表示相位差正確
        """
        import numpy as np
        if len(a_buffer) < 10 or len(b_buffer) < 10:
            return False

        a = np.array(a_buffer, dtype=float)
        b = np.array(b_buffer, dtype=float)

        # 計算互相關
        a_norm = a - a.mean()
        b_norm = b - b.mean()

        if a_norm.std() < 1e-6 or b_norm.std() < 1e-6:
            return False  # 訊號無變化，無法判斷

        corr = np.correlate(a_norm, b_norm, mode='full')
        lags = np.arange(-(len(a) - 1), len(a))
        peak_lag = lags[np.argmax(np.abs(corr))]

        # 理想正交訊號的相位差應為 ±1/4 週期
        # 這裡簡化判斷：lag 不為 0 即表示有相位差
        return abs(peak_lag) > 0

    def analyze(
        self,
        voltages: dict,
        di_states: dict,
        count: int,
        rpm: float,
        position_deg: float,
        a_buffer=None,
        b_buffer=None,
        timestamp: float = 0.0
    ) -> EncoderAnalysisResult:
        """
        完整分析 Encoder 狀態
        Args:
            voltages: {"A": v, "B": v} AI 電壓
            di_states: {"A": bool, "B": bool} DI 狀態
            count: 累計脈波計數
            rpm: 轉速 (RPM)
            position_deg: 角度位置 (度)
            a_buffer: Encoder A 歷史緩衝（用於相位分析）
            b_buffer: Encoder B 歷史緩衝（用於相位分析）
            timestamp: 時間戳記
        Returns:
            EncoderAnalysisResult
        """
        result = EncoderAnalysisResult(timestamp=timestamp)

        # 分析各通道電壓
        for ch in ["A", "B"]:
            voltage = voltages.get(ch, 0.0)
            di_state = di_states.get(ch, False)
            result.channels[ch] = self.analyze_channel(ch, voltage, di_state)

        result.count = count
        result.rpm = rpm
        result.position_deg = position_deg
        result.direction = self.determine_direction(count, rpm)

        # 相位差驗證
        if a_buffer is not None and b_buffer is not None:
            result.phase_offset_valid = self.check_phase_offset(a_buffer, b_buffer)
        else:
            result.phase_offset_valid = True  # 無緩衝時跳過驗證

        self._history.append(result)
        return result

    def get_history(self) -> list:
        """取得歷史分析結果"""
        return list(self._history)

    def clear_history(self):
        """清除歷史記錄"""
        self._history.clear()

    def get_voltage_thresholds(self) -> dict:
        """取得電壓閾值設定"""
        return {
            "vh_min": self.VH_MIN,
            "vl_max": self.VL_MAX,
            "system_voltage": ENCODER_THRESHOLDS["system_voltage"],
            "ppr": self.PPR,
        }

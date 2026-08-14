"""
Hall Sensor 分析模組
驗證三相 Hall Sensor 的電壓準位與 H/L 狀態一致性
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from config.thresholds import HALL_THRESHOLDS


class VoltageLevel(Enum):
    """電壓準位判斷結果"""
    HIGH = "H"          # 高準位（PASS）
    LOW = "L"           # 低準位（PASS）
    UNDEFINED = "X"     # 不定態（FAIL）


class TestResult(Enum):
    """測試結果"""
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "---"


@dataclass
class HallChannelResult:
    """單一 Hall 通道測試結果"""
    phase: str                          # "U", "V", "W"
    voltage: float                      # 量測電壓 (V)
    voltage_level: VoltageLevel         # 電壓準位判斷
    di_state: bool                      # DI 讀取的 H/L 狀態
    consistency: bool                   # AI 與 DI 判斷是否一致
    voltage_result: TestResult          # 電壓準位測試結果
    consistency_result: TestResult      # 一致性測試結果

    @property
    def overall_result(self) -> TestResult:
        """整體測試結果（電壓 + 一致性都 PASS 才算 PASS）"""
        if (self.voltage_result == TestResult.PASS and
                self.consistency_result == TestResult.PASS):
            return TestResult.PASS
        return TestResult.FAIL


@dataclass
class HallAnalysisResult:
    """三相 Hall Sensor 完整分析結果"""
    channels: dict = field(default_factory=dict)  # {"U": HallChannelResult, ...}
    timestamp: float = 0.0

    @property
    def overall_result(self) -> TestResult:
        """所有通道都 PASS 才算整體 PASS"""
        if not self.channels:
            return TestResult.UNKNOWN
        for ch_result in self.channels.values():
            if ch_result.overall_result != TestResult.PASS:
                return TestResult.FAIL
        return TestResult.PASS

    @property
    def summary(self) -> str:
        """產生摘要字串"""
        lines = ["=== Hall Sensor 分析結果 ==="]
        for phase, result in self.channels.items():
            lines.append(
                f"  Hall {phase}: "
                f"電壓={result.voltage:.3f}V "
                f"準位={result.voltage_level.value} "
                f"DI={'H' if result.di_state else 'L'} "
                f"一致={'✓' if result.consistency else '✗'} "
                f"→ {result.overall_result.value}"
            )
        lines.append(f"  整體結果: {self.overall_result.value}")
        return "\n".join(lines)


class HallAnalyzer:
    """
    Hall Sensor 分析器
    根據 AI 電壓與 DI 狀態進行雙重驗證
    """

    VH_MIN = HALL_THRESHOLDS["vh_min"]   # H 準位最低電壓 (V)
    VL_MAX = HALL_THRESHOLDS["vl_max"]   # L 準位最高電壓 (V)

    def __init__(self):
        self._history: list[HallAnalysisResult] = []

    def classify_voltage(self, voltage: float) -> VoltageLevel:
        """
        判斷電壓準位
        Args:
            voltage: 量測電壓 (V)
        Returns:
            VoltageLevel: HIGH / LOW / UNDEFINED
        """
        if voltage >= self.VH_MIN:
            return VoltageLevel.HIGH
        elif voltage <= self.VL_MAX:
            return VoltageLevel.LOW
        else:
            return VoltageLevel.UNDEFINED

    def analyze_channel(
        self,
        phase: str,
        voltage: float,
        di_state: bool
    ) -> HallChannelResult:
        """
        分析單一 Hall 通道
        Args:
            phase: 相別 "U", "V", "W"
            voltage: AI 量測電壓 (V)
            di_state: DI 讀取的 H/L 狀態 (True=H, False=L)
        Returns:
            HallChannelResult
        """
        voltage_level = self.classify_voltage(voltage)

        # 電壓準位測試
        voltage_result = (
            TestResult.PASS
            if voltage_level != VoltageLevel.UNDEFINED
            else TestResult.FAIL
        )

        # AI 與 DI 一致性驗證
        ai_is_high = (voltage_level == VoltageLevel.HIGH)
        consistency = (ai_is_high == di_state) if voltage_level != VoltageLevel.UNDEFINED else False
        consistency_result = TestResult.PASS if consistency else TestResult.FAIL

        return HallChannelResult(
            phase=phase,
            voltage=voltage,
            voltage_level=voltage_level,
            di_state=di_state,
            consistency=consistency,
            voltage_result=voltage_result,
            consistency_result=consistency_result,
        )

    def analyze(
        self,
        voltages: dict,
        di_states: dict,
        timestamp: float = 0.0
    ) -> HallAnalysisResult:
        """
        分析三相 Hall Sensor
        Args:
            voltages: {"U": v, "V": v, "W": v} AI 電壓
            di_states: {"U": bool, "V": bool, "W": bool} DI 狀態
            timestamp: 時間戳記
        Returns:
            HallAnalysisResult
        """
        result = HallAnalysisResult(timestamp=timestamp)
        for phase in ["U", "V", "W"]:
            voltage = voltages.get(phase, 0.0)
            di_state = di_states.get(phase, False)
            result.channels[phase] = self.analyze_channel(phase, voltage, di_state)

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
            "system_voltage": HALL_THRESHOLDS["system_voltage"],
        }

"""
測試結果面板
顯示三相 Hall Sensor 的即時電壓值與 H/L/X 準位（僅供初步觀察）

注意：
  - 即時監控模式不做 PASS/FAIL 判斷。
  - 即時監控僅量測三相 Hall（U/V/W）；Encoder 與 DI 已於監控模式移除。
  - H/L/X 準位與相序判斷皆改由 AI 類比電壓直接判定（不再依賴 DI 數位訊號）。
  - PASS/FAIL 診斷改由高速取樣（DiagnosticScanner + DiagAnalyzer）完成。
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QGroupBox, QFrame, QSizePolicy
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QColor

from config.thresholds import HALL_THRESHOLDS


# ─── 樣式常數 ──────────────────────────────────────────────────────────────────
STYLE_PASS = "background-color: #1A6B1A; color: #00FF00; border-radius: 4px; padding: 2px 8px; font-weight: bold;"
STYLE_FAIL = "background-color: #6B1A1A; color: #FF4444; border-radius: 4px; padding: 2px 8px; font-weight: bold;"
STYLE_UNKNOWN = "background-color: #3A3A3A; color: #AAAAAA; border-radius: 4px; padding: 2px 8px;"
STYLE_HIGH = "background-color: #1A3A6B; color: #44AAFF; border-radius: 4px; padding: 2px 8px; font-weight: bold;"
STYLE_LOW = "background-color: #2A2A2A; color: #888888; border-radius: 4px; padding: 2px 8px;"
STYLE_UNDEF = "background-color: #6B3A1A; color: #FFAA44; border-radius: 4px; padding: 2px 8px; font-weight: bold;"

LABEL_STYLE = "color: #CCCCCC; font-size: 11px;"
VALUE_STYLE = "color: #FFFFFF; font-size: 12px; font-weight: bold;"
GROUP_STYLE = """
    QGroupBox {
        color: #AAAAAA;
        border: 1px solid #444444;
        border-radius: 6px;
        margin-top: 8px;
        padding-top: 4px;
        font-size: 11px;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 8px;
        padding: 0 4px;
    }
"""


def make_label(text: str, style: str = LABEL_STYLE) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(style)
    lbl.setAlignment(Qt.AlignCenter)
    return lbl


def make_status_label(text: str = "---") -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(STYLE_UNKNOWN)
    lbl.setAlignment(Qt.AlignCenter)
    lbl.setMinimumWidth(60)
    return lbl


class HallLivePanel(QGroupBox):
    """
    三相 Hall Sensor 即時電壓顯示面板（僅供初步觀察）

    不做 PASS/FAIL 判斷，僅顯示即時電壓與由 AI 電壓判定的 H/L/X 準位，
    並依 AI 電壓判斷相序（CW / CCW / Error）。
    """

    PHASES = ["U", "V", "W"]
    PHASE_COLORS = {"U": "#FF4444", "V": "#44FF44", "W": "#4444FF"}

    def __init__(self, parent=None):
        super().__init__("Hall Sensor (3.3V 系統) — 即時觀察", parent)
        self.setStyleSheet(GROUP_STYLE)
        self._vh_min = HALL_THRESHOLDS["vh_min"]
        self._vl_max = HALL_THRESHOLDS["vl_max"]
        self._setup_ui()

    def _classify_level(self, voltage: float) -> str:
        """依 AI 電壓判定準位：H / L / X（不定態）"""
        if voltage >= self._vh_min:
            return "H"
        if voltage <= self._vl_max:
            return "L"
        return "X"

    def _setup_ui(self):
        grid = QGridLayout(self)
        grid.setSpacing(6)

        # 表頭（H/L/X 準位由 AI 類比電壓直接判定）
        headers = ["相別", "電壓 (V)", "準位 (H/L/X)"]
        for col, h in enumerate(headers):
            lbl = make_label(h)
            lbl.setStyleSheet("color: #888888; font-size: 10px;")
            grid.addWidget(lbl, 0, col)

        # 分隔線
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #444444;")
        grid.addWidget(line, 1, 0, 1, 3)

        # 各相資料列
        self._voltage_labels = {}
        self._level_labels   = {}

        for row, phase in enumerate(self.PHASES, start=2):
            color = self.PHASE_COLORS[phase]
            phase_lbl = make_label(f"Hall {phase}")
            phase_lbl.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 12px;")
            grid.addWidget(phase_lbl, row, 0)

            # 電壓數值（AI 類比）
            self._voltage_labels[phase] = make_label("---")
            self._voltage_labels[phase].setStyleSheet(VALUE_STYLE)
            grid.addWidget(self._voltage_labels[phase], row, 1)

            # 準位（依 AI 電壓判定 H/L/X）
            self._level_labels[phase] = make_status_label()
            grid.addWidget(self._level_labels[phase], row, 2)

        # ── 相序判斷（顯示於面板底部，依 AI 電壓判斷）────────────────────────
        seq_row = len(self.PHASES) + 2
        seq_sep = QFrame()
        seq_sep.setFrameShape(QFrame.HLine)
        seq_sep.setStyleSheet("color: #444444;")
        grid.addWidget(seq_sep, seq_row, 0, 1, 3)

        seq_hdr = make_label("相序判斷（AI）")
        seq_hdr.setStyleSheet("color: #888888; font-size: 10px;")
        grid.addWidget(seq_hdr, seq_row + 1, 0, 1, 2)

        seq_font = QFont("Arial", 13, QFont.Bold)

        # AI 相序標籤（依 AI 類比電壓經中點閾值編碼判斷）
        self._seq_label_ai = QLabel("---")
        self._seq_label_ai.setAlignment(Qt.AlignCenter)
        self._seq_label_ai.setStyleSheet(STYLE_UNKNOWN)
        self._seq_label_ai.setMinimumWidth(70)
        self._seq_label_ai.setFont(seq_font)
        grid.addWidget(self._seq_label_ai, seq_row + 1, 2)

        # 說明提示（AI 電壓判斷準位與相序）
        thresh_lbl = make_label(
            f"AI 電壓判定準位 H≥{self._vh_min}V L≤{self._vl_max}V  |  PASS/FAIL 請用「高取樣診斷」"
        )
        thresh_lbl.setStyleSheet("color: #666666; font-size: 10px;")
        grid.addWidget(thresh_lbl, seq_row + 2, 0, 1, 3)

    @staticmethod
    def _apply_seq_style(label, seq_result: str):
        """依相序判斷結果套用文字與樣式（CW/CCW/Error/---）"""
        if seq_result == "CW":
            label.setText("✓ CW")
            label.setStyleSheet(STYLE_PASS)
        elif seq_result == "CCW":
            label.setText("✓ CCW")
            label.setStyleSheet(STYLE_HIGH)
        elif seq_result == "Error":
            label.setText("✗ Error")
            label.setStyleSheet(STYLE_FAIL)
        else:
            label.setText("---")
            label.setStyleSheet(STYLE_UNKNOWN)

    def _apply_level_style(self, label, level: str):
        """依 H/L/X 準位套用文字與樣式"""
        label.setText(level)
        if level == "H":
            label.setStyleSheet(STYLE_HIGH)
        elif level == "L":
            label.setStyleSheet(STYLE_LOW)
        else:  # X（不定態）
            label.setStyleSheet(STYLE_UNDEF)

    def update_voltages(
        self,
        hall_voltages: dict,
        seq_result_ai: str = "---"
    ):
        """
        更新即時電壓顯示

        Args:
            hall_voltages: {"U": v, "V": v, "W": v}（AI 類比，供顯示、準位與相序判斷）
            seq_result_ai: AI 相序判斷結果 "CW" / "CCW" / "Error" / "---"
        """
        for phase in self.PHASES:
            # 電壓數值（AI 類比）
            v = hall_voltages.get(phase, 0.0)
            self._voltage_labels[phase].setText(f"{v:.3f} V")

            # 準位（依 AI 電壓判定 H/L/X）
            self._apply_level_style(self._level_labels[phase], self._classify_level(v))

        # ── 相序判斷結果顯示（依 AI 電壓）────────────────────────────────────
        self._apply_seq_style(self._seq_label_ai, seq_result_ai)


class ResultPanel(QWidget):
    """
    即時電壓顯示面板（監控模式，僅供初步觀察）

    僅包含三相 Hall Sensor 子面板；Encoder 即時面板已於監控模式移除。
    注意：不做 PASS/FAIL 判斷，診斷請使用「高取樣診斷」功能。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        # 標題
        title = QLabel("即時觀察（50 kHz/通道 連續串流）")
        title.setFont(QFont("Arial", 11, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color: #CCCCCC; padding: 4px;")
        layout.addWidget(title)

        # 說明標籤
        note_lbl = QLabel("⚠ 即時監控僅供初步觀察，不做 PASS/FAIL 判斷\n   診斷請使用「🔬 高取樣診斷」按鈕")
        note_lbl.setStyleSheet("color: #888844; font-size: 10px; padding: 2px 4px;")
        note_lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(note_lbl)

        # Hall 即時面板
        self._hall_panel = HallLivePanel()
        layout.addWidget(self._hall_panel)

        layout.addStretch()

    def update_live_voltages(
        self,
        hall_voltages: dict,
        hall_seq_ai: str = "---"
    ):
        """
        更新即時電壓顯示（由 _update_analysis 每 50ms 呼叫）

        Args:
            hall_voltages: {"U": v, "V": v, "W": v}（AI 類比）
            hall_seq_ai:   AI 相序判斷結果 "CW" / "CCW" / "Error" / "---"
        """
        self._hall_panel.update_voltages(hall_voltages, seq_result_ai=hall_seq_ai)

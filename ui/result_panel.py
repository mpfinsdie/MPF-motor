"""
測試結果面板
顯示 Hall Sensor 與 Encoder 的即時測試結果、電壓值與狀態指示燈
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QGroupBox, QFrame, QSizePolicy
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QColor

from logic.hall_analyzer import HallAnalysisResult, TestResult as HallTestResult, VoltageLevel as HallVoltageLevel
from logic.encoder_analyzer import EncoderAnalysisResult, TestResult as EncTestResult, Direction


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


class HallResultPanel(QGroupBox):
    """三相 Hall Sensor 測試結果面板"""

    PHASES = ["U", "V", "W"]
    PHASE_COLORS = {"U": "#FF4444", "V": "#44FF44", "W": "#4444FF"}

    def __init__(self, parent=None):
        super().__init__("Hall Sensor (3.3V 系統)", parent)
        self.setStyleSheet(GROUP_STYLE)
        self._setup_ui()

    def _setup_ui(self):
        grid = QGridLayout(self)
        grid.setSpacing(6)

        # 表頭
        headers = ["相別", "電壓 (V)", "AI 準位", "DI 狀態", "一致性", "結果"]
        for col, h in enumerate(headers):
            lbl = make_label(h)
            lbl.setStyleSheet("color: #888888; font-size: 10px;")
            grid.addWidget(lbl, 0, col)

        # 分隔線
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #444444;")
        grid.addWidget(line, 1, 0, 1, 6)

        # 各相資料列
        self._voltage_labels = {}
        self._level_labels = {}
        self._di_labels = {}
        self._consistency_labels = {}
        self._result_labels = {}

        for row, phase in enumerate(self.PHASES, start=2):
            color = self.PHASE_COLORS[phase]
            phase_lbl = make_label(f"Hall {phase}")
            phase_lbl.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 12px;")
            grid.addWidget(phase_lbl, row, 0)

            self._voltage_labels[phase] = make_label("---")
            self._voltage_labels[phase].setStyleSheet(VALUE_STYLE)
            grid.addWidget(self._voltage_labels[phase], row, 1)

            self._level_labels[phase] = make_status_label()
            grid.addWidget(self._level_labels[phase], row, 2)

            self._di_labels[phase] = make_status_label()
            grid.addWidget(self._di_labels[phase], row, 3)

            self._consistency_labels[phase] = make_status_label()
            grid.addWidget(self._consistency_labels[phase], row, 4)

            self._result_labels[phase] = make_status_label()
            grid.addWidget(self._result_labels[phase], row, 5)

        # 整體結果
        line2 = QFrame()
        line2.setFrameShape(QFrame.HLine)
        line2.setStyleSheet("color: #444444;")
        grid.addWidget(line2, len(self.PHASES) + 2, 0, 1, 6)

        overall_lbl = make_label("整體結果")
        overall_lbl.setStyleSheet("color: #CCCCCC; font-weight: bold;")
        grid.addWidget(overall_lbl, len(self.PHASES) + 3, 0, 1, 4)

        self._overall_label = make_status_label()
        self._overall_label.setStyleSheet(STYLE_UNKNOWN)
        grid.addWidget(self._overall_label, len(self.PHASES) + 3, 4, 1, 2)

    def update_result(self, result: HallAnalysisResult):
        """更新顯示結果"""
        for phase, ch_result in result.channels.items():
            # 電壓
            self._voltage_labels[phase].setText(f"{ch_result.voltage:.3f} V")

            # AI 準位
            level = ch_result.voltage_level
            if level == HallVoltageLevel.HIGH:
                self._level_labels[phase].setText("H")
                self._level_labels[phase].setStyleSheet(STYLE_HIGH)
            elif level == HallVoltageLevel.LOW:
                self._level_labels[phase].setText("L")
                self._level_labels[phase].setStyleSheet(STYLE_LOW)
            else:
                self._level_labels[phase].setText("X")
                self._level_labels[phase].setStyleSheet(STYLE_UNDEF)

            # DI 狀態
            di_text = "H" if ch_result.di_state else "L"
            di_style = STYLE_HIGH if ch_result.di_state else STYLE_LOW
            self._di_labels[phase].setText(di_text)
            self._di_labels[phase].setStyleSheet(di_style)

            # 一致性
            if ch_result.consistency:
                self._consistency_labels[phase].setText("✓")
                self._consistency_labels[phase].setStyleSheet(STYLE_PASS)
            else:
                self._consistency_labels[phase].setText("✗")
                self._consistency_labels[phase].setStyleSheet(STYLE_FAIL)

            # 結果
            if ch_result.overall_result == HallTestResult.PASS:
                self._result_labels[phase].setText("PASS")
                self._result_labels[phase].setStyleSheet(STYLE_PASS)
            else:
                self._result_labels[phase].setText("FAIL")
                self._result_labels[phase].setStyleSheet(STYLE_FAIL)

        # 整體結果
        if result.overall_result == HallTestResult.PASS:
            self._overall_label.setText("PASS")
            self._overall_label.setStyleSheet(STYLE_PASS)
        else:
            self._overall_label.setText("FAIL")
            self._overall_label.setStyleSheet(STYLE_FAIL)


class EncoderResultPanel(QGroupBox):
    """Encoder 測試結果面板"""

    def __init__(self, parent=None):
        super().__init__("Encoder (5V 系統)", parent)
        self.setStyleSheet(GROUP_STYLE)
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(6)

        # ── 電壓準位表格 ──────────────────────────────────────────────────────
        grid = QGridLayout()
        grid.setSpacing(6)

        headers = ["通道", "電壓 (V)", "AI 準位", "DI 狀態", "一致性", "結果"]
        for col, h in enumerate(headers):
            lbl = make_label(h)
            lbl.setStyleSheet("color: #888888; font-size: 10px;")
            grid.addWidget(lbl, 0, col)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #444444;")
        grid.addWidget(line, 1, 0, 1, 6)

        CHANNEL_COLORS = {"A": "#FFAA00", "B": "#AA00FF"}
        self._voltage_labels = {}
        self._level_labels = {}
        self._di_labels = {}
        self._consistency_labels = {}
        self._result_labels = {}

        for row, ch in enumerate(["A", "B"], start=2):
            color = CHANNEL_COLORS[ch]
            ch_lbl = make_label(f"Encoder {ch}")
            ch_lbl.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 12px;")
            grid.addWidget(ch_lbl, row, 0)

            self._voltage_labels[ch] = make_label("---")
            self._voltage_labels[ch].setStyleSheet(VALUE_STYLE)
            grid.addWidget(self._voltage_labels[ch], row, 1)

            self._level_labels[ch] = make_status_label()
            grid.addWidget(self._level_labels[ch], row, 2)

            self._di_labels[ch] = make_status_label()
            grid.addWidget(self._di_labels[ch], row, 3)

            self._consistency_labels[ch] = make_status_label()
            grid.addWidget(self._consistency_labels[ch], row, 4)

            self._result_labels[ch] = make_status_label()
            grid.addWidget(self._result_labels[ch], row, 5)

        main_layout.addLayout(grid)

        # ── 動態資訊 ──────────────────────────────────────────────────────────
        info_layout = QGridLayout()
        info_layout.setSpacing(8)

        info_items = [
            ("計數", "count"),
            ("方向", "direction"),
            ("轉速", "rpm"),
            ("位置", "position"),
        ]

        self._info_labels = {}
        for col, (label_text, key) in enumerate(info_items):
            lbl = make_label(label_text)
            lbl.setStyleSheet("color: #888888; font-size: 10px;")
            info_layout.addWidget(lbl, 0, col)

            val_lbl = make_label("---")
            val_lbl.setStyleSheet(VALUE_STYLE)
            self._info_labels[key] = val_lbl
            info_layout.addWidget(val_lbl, 1, col)

        main_layout.addLayout(info_layout)

        # ── 整體結果 ──────────────────────────────────────────────────────────
        result_layout = QHBoxLayout()
        result_layout.addWidget(make_label("整體結果："))
        self._overall_label = make_status_label()
        result_layout.addWidget(self._overall_label)
        result_layout.addStretch()
        main_layout.addLayout(result_layout)

    def update_result(self, result: EncoderAnalysisResult):
        """更新顯示結果"""
        from logic.encoder_analyzer import VoltageLevel as EncVoltageLevel

        for ch, ch_result in result.channels.items():
            self._voltage_labels[ch].setText(f"{ch_result.voltage:.3f} V")

            level = ch_result.voltage_level
            if level == EncVoltageLevel.HIGH:
                self._level_labels[ch].setText("H")
                self._level_labels[ch].setStyleSheet(STYLE_HIGH)
            elif level == EncVoltageLevel.LOW:
                self._level_labels[ch].setText("L")
                self._level_labels[ch].setStyleSheet(STYLE_LOW)
            else:
                self._level_labels[ch].setText("X")
                self._level_labels[ch].setStyleSheet(STYLE_UNDEF)

            di_text = "H" if ch_result.di_state else "L"
            di_style = STYLE_HIGH if ch_result.di_state else STYLE_LOW
            self._di_labels[ch].setText(di_text)
            self._di_labels[ch].setStyleSheet(di_style)

            if ch_result.consistency:
                self._consistency_labels[ch].setText("✓")
                self._consistency_labels[ch].setStyleSheet(STYLE_PASS)
            else:
                self._consistency_labels[ch].setText("✗")
                self._consistency_labels[ch].setStyleSheet(STYLE_FAIL)

            if ch_result.overall_result == EncTestResult.PASS:
                self._result_labels[ch].setText("PASS")
                self._result_labels[ch].setStyleSheet(STYLE_PASS)
            else:
                self._result_labels[ch].setText("FAIL")
                self._result_labels[ch].setStyleSheet(STYLE_FAIL)

        # 動態資訊
        self._info_labels["count"].setText(str(result.count))
        self._info_labels["direction"].setText(result.direction.value)
        self._info_labels["rpm"].setText(f"{abs(result.rpm):.1f} RPM")
        self._info_labels["position"].setText(f"{result.position_deg:.1f}°")

        # 整體結果
        if result.overall_result == EncTestResult.PASS:
            self._overall_label.setText("PASS")
            self._overall_label.setStyleSheet(STYLE_PASS)
        else:
            self._overall_label.setText("FAIL")
            self._overall_label.setStyleSheet(STYLE_FAIL)


class ResultPanel(QWidget):
    """
    完整測試結果面板
    包含 Hall Sensor 與 Encoder 兩個子面板
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        # 標題
        title = QLabel("測試結果")
        title.setFont(QFont("Arial", 11, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color: #CCCCCC; padding: 4px;")
        layout.addWidget(title)

        # Hall 結果面板
        self._hall_panel = HallResultPanel()
        layout.addWidget(self._hall_panel)

        # Encoder 結果面板
        self._enc_panel = EncoderResultPanel()
        layout.addWidget(self._enc_panel)

        layout.addStretch()

    def update_hall(self, result: HallAnalysisResult):
        """更新 Hall Sensor 結果"""
        self._hall_panel.update_result(result)

    def update_encoder(self, result: EncoderAnalysisResult):
        """更新 Encoder 結果"""
        self._enc_panel.update_result(result)

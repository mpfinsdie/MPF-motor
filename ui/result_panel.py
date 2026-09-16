"""
測試結果面板
顯示 Hall Sensor 與 Encoder 的即時電壓值與 DI 狀態（僅供初步觀察）

注意：即時監控模式不做 PASS/FAIL 判斷。
      PASS/FAIL 診斷改由高速取樣（DiagnosticScanner + DiagAnalyzer）完成。
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QGroupBox, QFrame, QSizePolicy
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QColor

from config.thresholds import HALL_THRESHOLDS, ENCODER_THRESHOLDS


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
    不做 PASS/FAIL 判斷，僅顯示即時電壓與 H/L/X 準位
    """

    PHASES = ["U", "V", "W"]
    PHASE_COLORS = {"U": "#FF4444", "V": "#44FF44", "W": "#4444FF"}

    def __init__(self, parent=None):
        super().__init__("Hall Sensor (3.3V 系統) — 即時觀察", parent)
        self.setStyleSheet(GROUP_STYLE)
        self._vh_min = HALL_THRESHOLDS["vh_min"]
        self._vl_max = HALL_THRESHOLDS["vl_max"]
        self._setup_ui()

    def _setup_ui(self):
        grid = QGridLayout(self)
        grid.setSpacing(6)

        # 表頭（AI 類比僅顯示電壓數值供參考，判斷以 DI 狀態為準）
        headers = ["相別", "電壓 (V)", "DI 狀態"]
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
        self._di_labels      = {}

        for row, phase in enumerate(self.PHASES, start=2):
            color = self.PHASE_COLORS[phase]
            phase_lbl = make_label(f"Hall {phase}")
            phase_lbl.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 12px;")
            grid.addWidget(phase_lbl, row, 0)

            # 電壓數值（AI 類比僅供參考顯示，不做 H/L/X 準位判斷）
            self._voltage_labels[phase] = make_label("---")
            self._voltage_labels[phase].setStyleSheet(VALUE_STYLE)
            grid.addWidget(self._voltage_labels[phase], row, 1)

            # DI 狀態（相序判斷依據）
            self._di_labels[phase] = make_status_label()
            grid.addWidget(self._di_labels[phase], row, 2)

        # ── 相序判斷（獨立顯示於面板底部，AI 與 DI 各自獨立判斷）──────────
        seq_row = len(self.PHASES) + 2
        seq_sep = QFrame()
        seq_sep.setFrameShape(QFrame.HLine)
        seq_sep.setStyleSheet("color: #444444;")
        grid.addWidget(seq_sep, seq_row, 0, 1, 3)

        # 相序小標題：欄1=標題、欄1(AI) / 欄2(DI) 並列顯示
        seq_hdr = make_label("相序判斷")
        seq_hdr.setStyleSheet("color: #888888; font-size: 10px;")
        grid.addWidget(seq_hdr, seq_row + 1, 0, 1, 1)

        ai_hdr = make_label("AI 類比")
        ai_hdr.setStyleSheet("color: #888888; font-size: 10px;")
        grid.addWidget(ai_hdr, seq_row + 1, 1)

        di_hdr = make_label("DI 數位")
        di_hdr.setStyleSheet("color: #888888; font-size: 10px;")
        grid.addWidget(di_hdr, seq_row + 1, 2)

        seq_font = QFont("Arial", 13, QFont.Bold)

        # AI 相序標籤（依 AI 類比電壓經中點閾值編碼判斷）
        self._seq_label_ai = QLabel("---")
        self._seq_label_ai.setAlignment(Qt.AlignCenter)
        self._seq_label_ai.setStyleSheet(STYLE_UNKNOWN)
        self._seq_label_ai.setMinimumWidth(70)
        self._seq_label_ai.setFont(seq_font)
        grid.addWidget(self._seq_label_ai, seq_row + 2, 1)

        # DI 相序標籤（依 DI 數位狀態判斷）
        self._seq_label_di = QLabel("---")
        self._seq_label_di.setAlignment(Qt.AlignCenter)
        self._seq_label_di.setStyleSheet(STYLE_UNKNOWN)
        self._seq_label_di.setMinimumWidth(70)
        self._seq_label_di.setFont(seq_font)
        grid.addWidget(self._seq_label_di, seq_row + 2, 2)

        # 說明提示（AI / DI 雙相序獨立判斷，AI 電壓仍供波形/數值參考）
        thresh_lbl = make_label(
            "AI/DI 各自獨立判斷相序  |  PASS/FAIL 請用「高取樣診斷」"
        )
        thresh_lbl.setStyleSheet("color: #666666; font-size: 10px;")
        grid.addWidget(thresh_lbl, seq_row + 3, 0, 1, 3)

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

    def update_voltages(
        self,
        hall_voltages: dict,
        di_states: dict = None,
        seq_result: str = "---",
        seq_result_ai: str = "---"
    ):
        """
        更新即時電壓顯示

        Args:
            hall_voltages: {"U": v, "V": v, "W": v}（AI 類比，同時供顯示與 AI 相序判斷）
            di_states:     {"U": bool, "V": bool, "W": bool}（DI 狀態，DI 相序判斷依據）
            seq_result:    DI 相序判斷結果 "CW" / "CCW" / "Error" / "---"
            seq_result_ai: AI 相序判斷結果 "CW" / "CCW" / "Error" / "---"
        """
        for phase in self.PHASES:
            # 電壓數值（AI 類比，供參考顯示，同時作為 AI 相序判斷來源）
            v = hall_voltages.get(phase, 0.0)
            self._voltage_labels[phase].setText(f"{v:.3f} V")

            # DI 狀態（DI 相序判斷依據）
            if di_states is not None:
                di_val = di_states.get(phase, False)
                self._di_labels[phase].setText("H" if di_val else "L")
                self._di_labels[phase].setStyleSheet(STYLE_HIGH if di_val else STYLE_LOW)
            else:
                self._di_labels[phase].setText("---")
                self._di_labels[phase].setStyleSheet(STYLE_UNKNOWN)

        # ── 相序判斷結果顯示（AI / DI 各自獨立）──────────────────────────
        self._apply_seq_style(self._seq_label_ai, seq_result_ai)
        self._apply_seq_style(self._seq_label_di, seq_result)


class EncoderLivePanel(QGroupBox):
    """
    Encoder 即時電壓顯示面板（僅供初步觀察）
    不做 PASS/FAIL 判斷，僅顯示即時電壓、DI 狀態與 RPM
    """

    def __init__(self, parent=None):
        super().__init__("Encoder (5V 系統) — 即時觀察", parent)
        self.setStyleSheet(GROUP_STYLE)
        self._vh_min = ENCODER_THRESHOLDS["vh_min"]
        self._vl_max = ENCODER_THRESHOLDS["vl_max"]
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(6)

        # ── 電壓準位表格 ──────────────────────────────────────────────────────
        grid = QGridLayout()
        grid.setSpacing(6)

        # 表頭（AI 類比僅顯示電壓數值供參考，計數/RPM 以 DI 為準）
        headers = ["通道", "電壓 (V)", "DI 狀態"]
        for col, h in enumerate(headers):
            lbl = make_label(h)
            lbl.setStyleSheet("color: #888888; font-size: 10px;")
            grid.addWidget(lbl, 0, col)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #444444;")
        grid.addWidget(line, 1, 0, 1, 3)

        CHANNEL_COLORS = {"A": "#FFAA00", "B": "#AA00FF"}
        self._voltage_labels = {}
        self._di_labels      = {}

        for row, ch in enumerate(["A", "B"], start=2):
            color = CHANNEL_COLORS[ch]
            ch_lbl = make_label(f"Encoder {ch}")
            ch_lbl.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 12px;")
            grid.addWidget(ch_lbl, row, 0)

            # 電壓數值（AI 類比僅供參考顯示，不做 H/L/X 準位判斷）
            self._voltage_labels[ch] = make_label("---")
            self._voltage_labels[ch].setStyleSheet(VALUE_STYLE)
            grid.addWidget(self._voltage_labels[ch], row, 1)

            # DI 狀態（計數/方向/RPM 依據）
            self._di_labels[ch] = make_status_label()
            grid.addWidget(self._di_labels[ch], row, 2)

        main_layout.addLayout(grid)

        # ── 動態資訊（RPM / 計數 / 位置）────────────────────────────────────
        info_layout = QGridLayout()
        info_layout.setSpacing(8)

        info_items = [("計數", "count"), ("轉速", "rpm"), ("位置", "position")]
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

        # 說明提示（DI 判斷計數/RPM、AI 僅波形/數值參考）
        thresh_lbl = make_label(
            "DI 判斷計數/RPM · AI 電壓僅供參考  |  PASS/FAIL 請用「高取樣診斷」"
        )
        thresh_lbl.setStyleSheet("color: #666666; font-size: 10px;")
        main_layout.addWidget(thresh_lbl)

    def update_voltages(self, enc_voltages: dict, enc_state: dict = None):
        """
        更新即時電壓顯示

        Args:
            enc_voltages: {"A": v, "B": v}（AI 類比，僅供參考顯示）
            enc_state:    {"A": bool, "B": bool, "count": int, "rpm": float, "position_deg": float}
                          （DI 正交解碼結果，計數/方向/RPM 判斷依據）
        """
        for ch in ["A", "B"]:
            # 電壓數值（AI 類比，僅供參考顯示，不做 H/L/X 準位判斷）
            v = enc_voltages.get(ch, 0.0)
            self._voltage_labels[ch].setText(f"{v:.3f} V")

            # DI 狀態（計數/方向/RPM 依據）
            if enc_state is not None:
                di_val = enc_state.get(ch, False)
                self._di_labels[ch].setText("H" if di_val else "L")
                self._di_labels[ch].setStyleSheet(STYLE_HIGH if di_val else STYLE_LOW)
            else:
                self._di_labels[ch].setText("---")
                self._di_labels[ch].setStyleSheet(STYLE_UNKNOWN)

        if enc_state is not None:
            self._info_labels["count"].setText(str(enc_state.get("count", 0)))
            rpm = enc_state.get("rpm", 0.0)
            self._info_labels["rpm"].setText(f"{abs(rpm):.1f} RPM")
            pos = enc_state.get("position_deg", 0.0)
            self._info_labels["position"].setText(f"{pos:.1f}°")


class ResultPanel(QWidget):
    """
    即時電壓顯示面板（監控模式，僅供初步觀察）
    包含 Hall Sensor 與 Encoder 兩個子面板
    注意：不做 PASS/FAIL 判斷，診斷請使用「高取樣診斷」功能
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        # 標題
        title = QLabel("即時觀察（20 kHz/通道 連續串流）")
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

        # Encoder 即時面板
        self._enc_panel = EncoderLivePanel()
        layout.addWidget(self._enc_panel)

        layout.addStretch()

    def update_live_voltages(
        self,
        hall_voltages: dict,
        enc_voltages: dict,
        enc_state: dict = None,
        di_states: dict = None,
        hall_seq: str = "---",
        hall_seq_ai: str = "---"
    ):
        """
        更新即時電壓顯示（由 _update_analysis 每 50ms 呼叫）

        Args:
            hall_voltages: {"U": v, "V": v, "W": v}
            enc_voltages:  {"A": v, "B": v}
            enc_state:     {"A": bool, "B": bool, "count": int, "rpm": float, "position_deg": float}
            di_states:     {"U": bool, "V": bool, "W": bool}（Hall DI 狀態，可選）
            hall_seq:      DI 相序判斷結果 "CW" / "CCW" / "Error" / "---"
            hall_seq_ai:   AI 相序判斷結果 "CW" / "CCW" / "Error" / "---"
        """
        self._hall_panel.update_voltages(
            hall_voltages, di_states, seq_result=hall_seq, seq_result_ai=hall_seq_ai
        )
        self._enc_panel.update_voltages(enc_voltages, enc_state)

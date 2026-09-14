"""
硬體通道設定對話框

讓使用者自行調整硬體端接線對應：
  - Hall U/V/W → AI / DI 通道
  - Encoder A/B → AI / DI 通道
  - AI 量程（Hall / Encoder）
  - DI Port 編號

設定會存回 config/channel_map.json，並可即時套用（重啟 AI/DI 讀取器）。

使用方式：
    dlg = ChannelConfigDialog(parent=self)
    if dlg.exec_() == QDialog.Accepted:
        new_map = dlg.get_channel_map()
        CHANNEL_CONFIG.set_map(new_map)   # 存檔
        refresh_channel_map()             # 更新 thresholds
        ai_reader.refresh_channels()      # 即時套用
        di_reader.refresh_channels()
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QSpinBox, QComboBox, QPushButton,
    QGroupBox, QFrame, QMessageBox
)
from PyQt5.QtCore import Qt

from config.channel_config import CHANNEL_CONFIG


DIALOG_STYLE = """
    QDialog {
        background-color: #1E1E1E;
        color: #CCCCCC;
    }
    QLabel {
        color: #CCCCCC;
        font-size: 12px;
    }
    QLabel#lbl_title {
        color: #4AABFF;
        font-size: 15px;
        font-weight: bold;
    }
    QLabel#lbl_hint {
        color: #888888;
        font-size: 11px;
    }
    QSpinBox, QComboBox {
        background-color: #2A2A2A;
        color: #FFFFFF;
        border: 1px solid #555555;
        border-radius: 4px;
        padding: 4px 6px;
        font-size: 12px;
        min-width: 90px;
    }
    QComboBox::drop-down { border: none; }
    QComboBox QAbstractItemView {
        background-color: #2A2A2A;
        color: #FFFFFF;
        selection-background-color: #2D5A8E;
    }
    QGroupBox {
        color: #AAAAAA;
        border: 1px solid #444444;
        border-radius: 6px;
        margin-top: 10px;
        padding-top: 6px;
        font-size: 11px;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 8px;
        padding: 0 4px;
    }
    QPushButton {
        background-color: #2D5A8E;
        color: #FFFFFF;
        border: none;
        border-radius: 4px;
        padding: 7px 20px;
        font-size: 12px;
        font-weight: bold;
        min-width: 90px;
    }
    QPushButton:hover { background-color: #3A72B0; }
    QPushButton#btn_apply {
        background-color: #2D8E2D;
        font-size: 13px;
        padding: 8px 24px;
    }
    QPushButton#btn_apply:hover { background-color: #3AAA3A; }
    QPushButton#btn_cancel { background-color: #5A3A3A; }
    QPushButton#btn_cancel:hover { background-color: #7A4A4A; }
    QPushButton#btn_reset { background-color: #5A5A3A; }
    QPushButton#btn_reset:hover { background-color: #7A7A4A; }
    QFrame#separator { background-color: #444444; }
"""

# 可選擇的 AI 量程（ValueRange 常見選項）
VALUE_RANGE_OPTIONS = [
    "V_0To5",
    "V_0To10",
    "V_Neg5To5",
    "V_Neg10To10",
    "V_0To2point5",
    "V_Neg2point5To2point5",
]

# USB-4716 AI/DI 通道數上限（AI 0~15，DI 0~7）
_AI_MAX = 15
_DI_MAX = 7


class ChannelConfigDialog(QDialog):
    """硬體通道設定對話框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("硬體通道設定")
        self.setModal(True)
        self.setFixedWidth(460)
        self.setStyleSheet(DIALOG_STYLE)

        # 讀取目前設定作為初始值
        self._map = CHANNEL_CONFIG.get_map()

        self._setup_ui()
        self._load_values()

    # ─── UI 建立 ───────────────────────────────────────────────────────────────

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        # 標題
        title = QLabel("🔌  硬體通道設定")
        title.setObjectName("lbl_title")
        layout.addWidget(title)

        sep = QFrame()
        sep.setObjectName("separator")
        sep.setFrameShape(QFrame.HLine)
        sep.setFixedHeight(1)
        layout.addWidget(sep)

        # 說明
        desc = QLabel(
            "設定各訊號對應的硬體 AI / DI 通道編號，\n"
            "可依實際接線自由調整，不必固定 AI0~4 / DI0~4。"
        )
        desc.setObjectName("lbl_hint")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # ── Hall Sensor 通道 ──────────────────────────────────────────────────
        hall_group = QGroupBox("Hall Sensor 通道對應")
        hall_form = QFormLayout(hall_group)
        hall_form.setSpacing(8)
        hall_form.setLabelAlignment(Qt.AlignRight)

        self._hall_ai_spins = {}
        self._hall_di_spins = {}
        for sig in ("U", "V", "W"):
            row, ai_spin, di_spin = self._build_ch_row(_AI_MAX, _DI_MAX)
            self._hall_ai_spins[sig] = ai_spin
            self._hall_di_spins[sig] = di_spin
            hall_form.addRow(f"Hall {sig}：", row)
        layout.addWidget(hall_group)

        # ── Encoder 通道 ──────────────────────────────────────────────────────
        enc_group = QGroupBox("Encoder 通道對應")
        enc_form = QFormLayout(enc_group)
        enc_form.setSpacing(8)
        enc_form.setLabelAlignment(Qt.AlignRight)

        self._enc_ai_spins = {}
        self._enc_di_spins = {}
        for sig in ("A", "B"):
            row, ai_spin, di_spin = self._build_ch_row(_AI_MAX, _DI_MAX)
            self._enc_ai_spins[sig] = ai_spin
            self._enc_di_spins[sig] = di_spin
            enc_form.addRow(f"Encoder {sig}：", row)
        layout.addWidget(enc_group)

        # ── 量程與 Port ───────────────────────────────────────────────────────
        misc_group = QGroupBox("量程與 Port 設定")
        misc_form = QFormLayout(misc_group)
        misc_form.setSpacing(8)
        misc_form.setLabelAlignment(Qt.AlignRight)

        self._hall_vr_combo = QComboBox()
        self._hall_vr_combo.addItems(VALUE_RANGE_OPTIONS)
        self._hall_vr_combo.setToolTip("Hall 通道 AI 量程（Hall 3.3V 訊號通常用 V_0To5）")
        misc_form.addRow("Hall 量程：", self._hall_vr_combo)

        self._enc_vr_combo = QComboBox()
        self._enc_vr_combo.addItems(VALUE_RANGE_OPTIONS)
        self._enc_vr_combo.setToolTip("Encoder 通道 AI 量程（Encoder 5V 訊號通常用 V_0To10）")
        misc_form.addRow("Encoder 量程：", self._enc_vr_combo)

        self._di_port_spin = QSpinBox()
        self._di_port_spin.setRange(0, 7)
        self._di_port_spin.setToolTip("DI 讀取的 Port 編號（USB-4716 通常為 0）")
        misc_form.addRow("DI Port：", self._di_port_spin)

        layout.addWidget(misc_group)

        # 提示
        hint = QLabel(
            "💡 按「套用」後設定會存入 channel_map.json 並即時生效。\n"
            "   注意：請避免多個訊號共用同一 AI（或同一 DI）通道。"
        )
        hint.setObjectName("lbl_hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # ── 按鈕列 ────────────────────────────────────────────────────────────
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        btn_cancel = QPushButton("取消")
        btn_cancel.setObjectName("btn_cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        btn_reset = QPushButton("恢復預設")
        btn_reset.setObjectName("btn_reset")
        btn_reset.clicked.connect(self._on_reset_default)
        btn_layout.addWidget(btn_reset)

        btn_layout.addStretch()

        btn_apply = QPushButton("✔  套用")
        btn_apply.setObjectName("btn_apply")
        btn_apply.setDefault(True)
        btn_apply.clicked.connect(self._on_apply)
        btn_layout.addWidget(btn_apply)

        layout.addLayout(btn_layout)

    def _build_ch_row(self, ai_max: int, di_max: int):
        """
        建立單一訊號的「AI + DI」通道選擇列

        Returns:
            (row_widget, ai_spin, di_spin)
        """
        row = QFrame()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)

        row_layout.addWidget(QLabel("AI"))
        ai_spin = QSpinBox()
        ai_spin.setRange(0, ai_max)
        row_layout.addWidget(ai_spin)

        row_layout.addSpacing(12)

        row_layout.addWidget(QLabel("DI"))
        di_spin = QSpinBox()
        di_spin.setRange(0, di_max)
        row_layout.addWidget(di_spin)

        row_layout.addStretch()
        return row, ai_spin, di_spin

    # ─── 值載入 / 收集 ──────────────────────────────────────────────────────────

    def _load_values(self):
        """將目前設定載入至各控制項"""
        for sig in ("U", "V", "W"):
            self._hall_ai_spins[sig].setValue(self._map["hall"][sig]["ai"])
            self._hall_di_spins[sig].setValue(self._map["hall"][sig]["di"])
        for sig in ("A", "B"):
            self._enc_ai_spins[sig].setValue(self._map["encoder"][sig]["ai"])
            self._enc_di_spins[sig].setValue(self._map["encoder"][sig]["di"])

        self._set_combo(self._hall_vr_combo, self._map["value_range"].get("hall", "V_0To5"))
        self._set_combo(self._enc_vr_combo, self._map["value_range"].get("encoder", "V_0To10"))
        self._di_port_spin.setValue(self._map.get("di_port", 0))

    def _set_combo(self, combo: QComboBox, value: str):
        """設定下拉選單至指定值（不存在時新增）"""
        idx = combo.findText(value)
        if idx < 0:
            combo.addItem(value)
            idx = combo.findText(value)
        combo.setCurrentIndex(idx)

    def get_channel_map(self) -> dict:
        """
        收集使用者輸入，回傳新的通道對應字典

        Returns:
            dict: 符合 channel_map.json 結構的完整設定
        """
        return {
            "hall": {
                sig: {
                    "ai": self._hall_ai_spins[sig].value(),
                    "di": self._hall_di_spins[sig].value(),
                }
                for sig in ("U", "V", "W")
            },
            "encoder": {
                sig: {
                    "ai": self._enc_ai_spins[sig].value(),
                    "di": self._enc_di_spins[sig].value(),
                }
                for sig in ("A", "B")
            },
            "value_range": {
                "hall": self._hall_vr_combo.currentText(),
                "encoder": self._enc_vr_combo.currentText(),
            },
            "y_range": self._map.get("y_range", {
                "hall": [-0.2, 3.8],
                "encoder": [-0.5, 6.0],
            }),
            "di_port": self._di_port_spin.value(),
        }

    # ─── 事件 ──────────────────────────────────────────────────────────────────

    def _on_reset_default(self):
        """恢復預設通道對應"""
        from config.channel_config import DEFAULT_CHANNEL_MAP
        import copy
        self._map = copy.deepcopy(DEFAULT_CHANNEL_MAP)
        self._load_values()

    def _on_apply(self):
        """套用前驗證通道不重複，通過後 accept"""
        new_map = self.get_channel_map()

        # 檢查 AI 通道是否重複
        ai_list = [new_map["hall"][s]["ai"] for s in ("U", "V", "W")] + \
                  [new_map["encoder"][s]["ai"] for s in ("A", "B")]
        di_list = [new_map["hall"][s]["di"] for s in ("U", "V", "W")] + \
                  [new_map["encoder"][s]["di"] for s in ("A", "B")]

        if len(set(ai_list)) != len(ai_list):
            QMessageBox.warning(
                self, "通道重複",
                f"AI 通道有重複：{sorted(ai_list)}\n"
                "請確認每個訊號使用不同的 AI 通道。"
            )
            return
        if len(set(di_list)) != len(di_list):
            QMessageBox.warning(
                self, "通道重複",
                f"DI 通道有重複：{sorted(di_list)}\n"
                "請確認每個訊號使用不同的 DI 通道。"
            )
            return

        self.accept()

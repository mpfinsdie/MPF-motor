"""
測試場次啟動對話框
操作員在開始檢測前輸入馬達序號、測試時長等資訊
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QSpinBox, QPushButton,
    QGroupBox, QDialogButtonBox, QFrame
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

from config.thresholds import DATABASE


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
    QLineEdit {
        background-color: #2A2A2A;
        color: #FFFFFF;
        border: 1px solid #555555;
        border-radius: 4px;
        padding: 5px 8px;
        font-size: 13px;
    }
    QLineEdit:focus {
        border: 1px solid #4AABFF;
    }
    QSpinBox {
        background-color: #2A2A2A;
        color: #FFFFFF;
        border: 1px solid #555555;
        border-radius: 4px;
        padding: 4px 6px;
        font-size: 12px;
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
    QPushButton:hover {
        background-color: #3A72B0;
    }
    QPushButton#btn_start {
        background-color: #2D8E2D;
        font-size: 13px;
        padding: 8px 24px;
    }
    QPushButton#btn_start:hover {
        background-color: #3AAA3A;
    }
    QPushButton#btn_cancel {
        background-color: #5A3A3A;
    }
    QPushButton#btn_cancel:hover {
        background-color: #7A4A4A;
    }
    QFrame#separator {
        background-color: #444444;
    }
"""


class SessionStartDialog(QDialog):
    """
    測試場次啟動對話框

    使用方式：
        dlg = SessionStartDialog(parent=self, default_duration_min=5)
        if dlg.exec_() == QDialog.Accepted:
            info = dlg.get_session_info()
            # info = {"serial_no": str, "operator": str, "duration_s": float}
    """

    def __init__(self, parent=None, default_duration_min: int = None):
        super().__init__(parent)
        self.setWindowTitle("開始檢測")
        self.setModal(True)
        self.setFixedWidth(420)
        self.setStyleSheet(DIALOG_STYLE)

        _default_min = default_duration_min or (
            DATABASE.get("default_duration_s", 300) // 60
        )
        self._default_duration_min = max(1, _default_min)

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        # ── 標題 ──────────────────────────────────────────────────────────────
        title = QLabel("▶  開始新測試場次")
        title.setObjectName("lbl_title")
        layout.addWidget(title)

        sep = QFrame()
        sep.setObjectName("separator")
        sep.setFrameShape(QFrame.HLine)
        sep.setFixedHeight(1)
        layout.addWidget(sep)

        # ── 測試物件資訊 ──────────────────────────────────────────────────────
        info_group = QGroupBox("測試物件資訊")
        form = QFormLayout(info_group)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignRight)

        self._serial_edit = QLineEdit()
        self._serial_edit.setPlaceholderText("例：MTR-2026-001（可留空）")
        self._serial_edit.setMaxLength(64)
        form.addRow("馬達序號：", self._serial_edit)

        self._operator_edit = QLineEdit()
        self._operator_edit.setPlaceholderText("操作員姓名（可留空）")
        self._operator_edit.setMaxLength(32)
        form.addRow("操作員：", self._operator_edit)

        layout.addWidget(info_group)

        # ── 測試設定 ──────────────────────────────────────────────────────────
        setting_group = QGroupBox("測試設定")
        setting_form = QFormLayout(setting_group)
        setting_form.setSpacing(10)
        setting_form.setLabelAlignment(Qt.AlignRight)

        self._duration_spin = QSpinBox()
        self._duration_spin.setRange(1, 60)
        self._duration_spin.setValue(self._default_duration_min)
        self._duration_spin.setSuffix(" 分鐘")
        self._duration_spin.setToolTip("測試時長（1 ~ 60 分鐘），時間到後自動停止並儲存結果")
        setting_form.addRow("測試時長：", self._duration_spin)

        layout.addWidget(setting_group)

        # ── 提示文字 ──────────────────────────────────────────────────────────
        hint = QLabel(
            "💡 提示：請確認訊號已穩定後再按「開始檢測」\n"
            "   測試期間可隨時按「提前停止」結束並儲存結果"
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

        btn_layout.addStretch()

        btn_start = QPushButton("▶  開始檢測")
        btn_start.setObjectName("btn_start")
        btn_start.setDefault(True)
        btn_start.clicked.connect(self.accept)
        btn_layout.addWidget(btn_start)

        layout.addLayout(btn_layout)

        # 讓序號欄位自動取得焦點
        self._serial_edit.setFocus()

    # ─── 公開介面 ──────────────────────────────────────────────────────────────

    def get_session_info(self) -> dict:
        """
        取得使用者輸入的場次資訊
        Returns:
            dict: {
                "serial_no":   str,   馬達序號
                "operator":    str,   操作員
                "duration_s":  float, 測試秒數
                "duration_min": int,  測試分鐘數
            }
        """
        duration_min = self._duration_spin.value()
        return {
            "serial_no":    self._serial_edit.text().strip(),
            "operator":     self._operator_edit.text().strip(),
            "duration_s":   float(duration_min * 60),
            "duration_min": duration_min,
        }

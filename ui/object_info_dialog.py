"""
測試物件資訊對話框

操作員輸入測試物件的馬達序號與操作員名稱。
此對話框由主畫面「🏷 測試物件」按鈕開啟，與量測參數設置（SessionStartDialog）分離。
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QGroupBox, QFrame
)
from PyQt5.QtCore import Qt


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
    QPushButton#btn_apply {
        background-color: #2D8E2D;
        font-size: 13px;
        padding: 8px 24px;
    }
    QPushButton#btn_apply:hover {
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


class ObjectInfoDialog(QDialog):
    """
    測試物件資訊對話框

    使用方式：
        dlg = ObjectInfoDialog(parent=self, serial_no="MTR-001", operator="王小明")
        if dlg.exec_() == QDialog.Accepted:
            info = dlg.get_object_info()
            # info = {"serial_no": str, "operator": str}
    """

    def __init__(self, parent=None, serial_no: str = "", operator: str = ""):
        super().__init__(parent)
        self.setWindowTitle("測試物件資訊")
        self.setModal(True)
        self.setFixedWidth(420)
        self.setStyleSheet(DIALOG_STYLE)

        self._init_serial   = serial_no or ""
        self._init_operator = operator or ""

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        # ── 標題 ──────────────────────────────────────────────────────────────
        title = QLabel("🏷  測試物件資訊")
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
        self._serial_edit.setText(self._init_serial)
        form.addRow("馬達序號：", self._serial_edit)

        self._operator_edit = QLineEdit()
        self._operator_edit.setPlaceholderText("操作員姓名（可留空）")
        self._operator_edit.setMaxLength(32)
        self._operator_edit.setText(self._init_operator)
        form.addRow("操作員：", self._operator_edit)

        layout.addWidget(info_group)

        # ── 提示文字 ──────────────────────────────────────────────────────────
        hint = QLabel(
            "💡 提示：序號與操作員會記錄於診斷場次，\n"
            "   量測參數請於「⚙ 參數設置」中設定。"
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

        btn_apply = QPushButton("✓  確定")
        btn_apply.setObjectName("btn_apply")
        btn_apply.setDefault(True)
        btn_apply.clicked.connect(self.accept)
        btn_layout.addWidget(btn_apply)

        layout.addLayout(btn_layout)

        # 讓序號欄位自動取得焦點
        self._serial_edit.setFocus()

    # ─── 公開介面 ──────────────────────────────────────────────────────────────

    def get_object_info(self) -> dict:
        """
        取得使用者輸入的測試物件資訊

        Returns:
            dict: {
                "serial_no": str,   馬達序號
                "operator":  str,   操作員
            }
        """
        return {
            "serial_no": self._serial_edit.text().strip(),
            "operator":  self._operator_edit.text().strip(),
        }

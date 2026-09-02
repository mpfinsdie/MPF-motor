"""
量測參數設置對話框
操作員在開始診斷前輸入馬達序號、操作員名稱及量測參數
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QSpinBox, QDoubleSpinBox, QPushButton,
    QGroupBox, QFrame
)
from PyQt5.QtCore import Qt

from config.thresholds import HALL_THRESHOLDS, ENCODER_THRESHOLDS, DIAGNOSTIC


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
    QSpinBox, QDoubleSpinBox {
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


class SessionStartDialog(QDialog):
    """
    量測參數設置對話框

    使用方式：
        dlg = SessionStartDialog(parent=self)
        if dlg.exec_() == QDialog.Accepted:
            info = dlg.get_session_info()
            # info = {"serial_no": str, "operator": str,
            #         "ppr": int, "hall_vh_min": float, "hall_vl_max": float,
            #         "enc_vh_min": float, "enc_vl_max": float}
    """

    def __init__(self, parent=None, default_duration_min: int = None):
        # default_duration_min 保留參數簽章相容性，但不再使用
        super().__init__(parent)
        self.setWindowTitle("參數設置")
        self.setModal(True)
        self.setFixedWidth(420)
        self.setStyleSheet(DIALOG_STYLE)

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        # ── 標題 ──────────────────────────────────────────────────────────────
        title = QLabel("⚙  量測參數設置")
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

        # ── 量測參數設定 ───────────────────────────────────────────────────────
        param_group = QGroupBox("量測參數設定")
        param_form = QFormLayout(param_group)
        param_form.setSpacing(8)
        param_form.setLabelAlignment(Qt.AlignRight)

        # ── Hall 規格 ─────────────────────────────────────────────────────────
        # Hall 每轉週期數
        self._hall_ppr_spin = QSpinBox()
        self._hall_ppr_spin.setRange(1, 10000)
        self._hall_ppr_spin.setValue(HALL_THRESHOLDS.get("hall_pulses_per_rev", 90))
        self._hall_ppr_spin.setSuffix(" 週期/轉")
        self._hall_ppr_spin.setToolTip(
            "Hall Sensor 每相每轉產生的 H-L 週期數\n"
            "例：本馬達每相每轉 90 次 High-Low = 90 週期/轉"
        )
        param_form.addRow("Hall 週期/轉：", self._hall_ppr_spin)

        # Hall VH_min
        self._hall_vh_spin = QDoubleSpinBox()
        self._hall_vh_spin.setRange(0.0, 5.0)
        self._hall_vh_spin.setSingleStep(0.1)
        self._hall_vh_spin.setDecimals(2)
        self._hall_vh_spin.setValue(HALL_THRESHOLDS["vh_min"])
        self._hall_vh_spin.setSuffix(" V")
        self._hall_vh_spin.setToolTip("Hall Sensor 高電位最低閾值")
        param_form.addRow("Hall VH_min：", self._hall_vh_spin)

        # Hall VL_max
        self._hall_vl_spin = QDoubleSpinBox()
        self._hall_vl_spin.setRange(0.0, 5.0)
        self._hall_vl_spin.setSingleStep(0.1)
        self._hall_vl_spin.setDecimals(2)
        self._hall_vl_spin.setValue(HALL_THRESHOLDS["vl_max"])
        self._hall_vl_spin.setSuffix(" V")
        self._hall_vl_spin.setToolTip("Hall Sensor 低電位最高閾值")
        param_form.addRow("Hall VL_max：", self._hall_vl_spin)

        # ── Encoder 規格 ──────────────────────────────────────────────────────
        # Encoder 解析度 bits（自動帶出 PPR 建議值）
        self._enc_bits_spin = QSpinBox()
        self._enc_bits_spin.setRange(1, 24)
        self._enc_bits_spin.setValue(ENCODER_THRESHOLDS.get("resolution_bits", 11))
        self._enc_bits_spin.setSuffix(" bits")
        self._enc_bits_spin.setToolTip(
            "Encoder 解析度位元數\n"
            "11 bits → 每轉 2^11 = 2048 counts（四倍頻後）\n"
            "每相 PPR = 2^bits / 4（自動帶入下方 PPR 欄位）"
        )
        self._enc_bits_spin.valueChanged.connect(self._on_enc_bits_changed)
        param_form.addRow("Encoder 解析度：", self._enc_bits_spin)

        # Encoder PPR（可手動覆蓋，也可由 bits 自動帶出）
        self._ppr_spin = QSpinBox()
        self._ppr_spin.setRange(1, 100000)
        self._ppr_spin.setValue(ENCODER_THRESHOLDS.get("ppr", 512))
        self._ppr_spin.setSuffix(" PPR")
        self._ppr_spin.setToolTip(
            "Encoder 每相每轉脈波數（Pulses Per Revolution）\n"
            "= 2^解析度bits / 4（四倍頻正交解碼）\n"
            "可手動覆蓋，不受解析度 bits 限制"
        )
        param_form.addRow("Encoder PPR：", self._ppr_spin)

        # Encoder VH_min
        self._enc_vh_spin = QDoubleSpinBox()
        self._enc_vh_spin.setRange(0.0, 10.0)
        self._enc_vh_spin.setSingleStep(0.1)
        self._enc_vh_spin.setDecimals(2)
        self._enc_vh_spin.setValue(ENCODER_THRESHOLDS["vh_min"])
        self._enc_vh_spin.setSuffix(" V")
        self._enc_vh_spin.setToolTip("Encoder 高電位最低閾值")
        param_form.addRow("Encoder VH_min：", self._enc_vh_spin)

        # Encoder VL_max
        self._enc_vl_spin = QDoubleSpinBox()
        self._enc_vl_spin.setRange(0.0, 10.0)
        self._enc_vl_spin.setSingleStep(0.1)
        self._enc_vl_spin.setDecimals(2)
        self._enc_vl_spin.setValue(ENCODER_THRESHOLDS["vl_max"])
        self._enc_vl_spin.setSuffix(" V")
        self._enc_vl_spin.setToolTip("Encoder 低電位最高閾值")
        param_form.addRow("Encoder VL_max：", self._enc_vl_spin)

        # ── 比值交叉驗證容差 ──────────────────────────────────────────────────
        self._ratio_tol_spin = QDoubleSpinBox()
        self._ratio_tol_spin.setRange(0.01, 0.50)
        self._ratio_tol_spin.setSingleStep(0.05)
        self._ratio_tol_spin.setDecimals(2)
        self._ratio_tol_spin.setValue(
            DIAGNOSTIC.get("analysis", {}).get("ratio_tolerance", 0.15)
        )
        self._ratio_tol_spin.setSuffix("  （±%）")
        self._ratio_tol_spin.setToolTip(
            "Hall/Encoder 脈波比值交叉驗證容差\n"
            "理論比值 = Encoder PPR / Hall 週期/轉\n"
            "實測比值超出理論值 ±此比例時判為 FAIL\n"
            "例：0.15 = ±15%"
        )
        # 顯示用標籤（含理論比值提示，隨 PPR/Hall 週期數變動更新）
        self._ratio_hint_lbl = QLabel(self._calc_ratio_hint())
        self._ratio_hint_lbl.setObjectName("lbl_hint")
        self._ratio_hint_lbl.setWordWrap(True)
        self._hall_ppr_spin.valueChanged.connect(self._update_ratio_hint)
        self._ppr_spin.valueChanged.connect(self._update_ratio_hint)
        self._ratio_tol_spin.valueChanged.connect(self._update_ratio_hint)

        param_form.addRow("比值容差：", self._ratio_tol_spin)
        param_form.addRow("", self._ratio_hint_lbl)

        layout.addWidget(param_group)

        # ── 提示文字 ──────────────────────────────────────────────────────────
        hint = QLabel(
            "💡 提示：設定完成後按「套用參數」，\n"
            "   再按「高取樣診斷」開始高速採樣檢測"
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

        btn_apply = QPushButton("⚙  套用參數")
        btn_apply.setObjectName("btn_apply")
        btn_apply.setDefault(True)
        btn_apply.clicked.connect(self.accept)
        btn_layout.addWidget(btn_apply)

        layout.addLayout(btn_layout)

        # 讓序號欄位自動取得焦點
        self._serial_edit.setFocus()

    # ─── 公開介面 ──────────────────────────────────────────────────────────────

    def get_session_info(self) -> dict:
        """
        取得使用者輸入的參數資訊
        Returns:
            dict: {
                "serial_no":           str,   馬達序號
                "operator":            str,   操作員
                "hall_pulses_per_rev": int,   Hall 每相每轉週期數
                "ppr":                 int,   Encoder 每相每轉脈波數
                "resolution_bits":     int,   Encoder 解析度位元數
                "hall_vh_min":         float, Hall VH_min (V)
                "hall_vl_max":         float, Hall VL_max (V)
                "enc_vh_min":          float, Encoder VH_min (V)
                "enc_vl_max":          float, Encoder VL_max (V)
                "ratio_tolerance":     float, 比值交叉驗證容差（比例）
            }
        """
        return {
            "serial_no":           self._serial_edit.text().strip(),
            "operator":            self._operator_edit.text().strip(),
            "hall_pulses_per_rev": self._hall_ppr_spin.value(),
            "ppr":                 self._ppr_spin.value(),
            "resolution_bits":     self._enc_bits_spin.value(),
            "hall_vh_min":         self._hall_vh_spin.value(),
            "hall_vl_max":         self._hall_vl_spin.value(),
            "enc_vh_min":          self._enc_vh_spin.value(),
            "enc_vl_max":          self._enc_vl_spin.value(),
            "ratio_tolerance":     self._ratio_tol_spin.value(),
        }

    # ─── 私有輔助方法 ──────────────────────────────────────────────────────────

    def _on_enc_bits_changed(self, bits: int):
        """
        Encoder 解析度 bits 變更時，自動帶出 PPR 建議值
        PPR = 2^bits / 4（四倍頻正交解碼）
        """
        suggested_ppr = max(1, (2 ** bits) // 4)
        self._ppr_spin.setValue(suggested_ppr)

    def _calc_ratio_hint(self) -> str:
        """計算並回傳比值提示文字"""
        hall_ppr = self._hall_ppr_spin.value() if hasattr(self, '_hall_ppr_spin') else 90
        enc_ppr  = self._ppr_spin.value()       if hasattr(self, '_ppr_spin')      else 512
        tol      = self._ratio_tol_spin.value() if hasattr(self, '_ratio_tol_spin') else 0.15
        if hall_ppr <= 0:
            return "（Hall 週期/轉不可為 0）"
        ratio = enc_ppr / hall_ppr
        low   = ratio * (1 - tol)
        high  = ratio * (1 + tol)
        return (
            f"理論比值 = {enc_ppr} / {hall_ppr} = {ratio:.3f}\n"
            f"允許範圍：[{low:.3f} ~ {high:.3f}]"
        )

    def _update_ratio_hint(self):
        """更新比值提示標籤"""
        if hasattr(self, '_ratio_hint_lbl'):
            self._ratio_hint_lbl.setText(self._calc_ratio_hint())

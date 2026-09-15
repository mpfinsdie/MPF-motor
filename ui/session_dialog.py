"""
量測參數設置對話框

操作員在此設定量測參數（Hall 週期/轉、Encoder 解析度/PPR、Hall/Encoder 電壓閾值、
比值容差），並可將設定存成具名的「馬達型號 profile」，方便為不同馬達切換套用。

（測試物件的馬達序號 / 操作員已移至獨立的 ObjectInfoDialog）
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QSpinBox, QDoubleSpinBox, QPushButton,
    QGroupBox, QFrame, QComboBox, QMessageBox, QInputDialog
)
from PyQt5.QtCore import Qt

from config.thresholds import HALL_THRESHOLDS, ENCODER_THRESHOLDS, DIAGNOSTIC
from config.motor_profiles import MOTOR_PROFILES


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
    QComboBox {
        background-color: #2A2A2A;
        color: #FFFFFF;
        border: 1px solid #555555;
        border-radius: 4px;
        padding: 4px 8px;
        font-size: 12px;
        min-width: 160px;
    }
    QComboBox:focus {
        border: 1px solid #4AABFF;
    }
    QComboBox QAbstractItemView {
        background-color: #2A2A2A;
        color: #FFFFFF;
        selection-background-color: #2D5A8E;
        border: 1px solid #555555;
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
    QPushButton#btn_profile {
        background-color: #444444;
        font-size: 11px;
        padding: 5px 12px;
        min-width: 60px;
    }
    QPushButton#btn_profile:hover {
        background-color: #555555;
    }
    QPushButton#btn_profile_del {
        background-color: #6A3A3A;
        font-size: 11px;
        padding: 5px 12px;
        min-width: 60px;
    }
    QPushButton#btn_profile_del:hover {
        background-color: #8A4A4A;
    }
    QFrame#separator {
        background-color: #444444;
    }
"""


class SessionStartDialog(QDialog):
    """
    量測參數設置對話框（含馬達型號 profile 管理）

    使用方式：
        dlg = SessionStartDialog(parent=self)
        if dlg.exec_() == QDialog.Accepted:
            info = dlg.get_session_info()
            # info 包含各量測參數，以及最終選用的 profile 名稱
    """

    def __init__(self, parent=None, default_duration_min: int = None):
        # default_duration_min 保留參數簽章相容性，但不再使用
        super().__init__(parent)
        self.setWindowTitle("參數設置")
        self.setModal(True)
        self.setFixedWidth(440)
        self.setStyleSheet(DIALOG_STYLE)

        # 目前選用的 profile 名稱（用於套用後回報主視窗記錄 active）
        self._current_profile_name = MOTOR_PROFILES.get_active_name()

        self._setup_ui()

        # 依 active profile 帶入初始欄位值
        self._load_profile_into_fields(self._current_profile_name)

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

        # ── 馬達型號 Profile ──────────────────────────────────────────────────
        profile_group = QGroupBox("馬達型號設定檔（Profile）")
        profile_layout = QVBoxLayout(profile_group)
        profile_layout.setSpacing(8)

        # Profile 下拉選單列
        combo_row = QHBoxLayout()
        combo_row.setSpacing(8)
        combo_row.addWidget(QLabel("套用設定："))

        self._profile_combo = QComboBox()
        self._refresh_profile_combo()
        self._profile_combo.currentIndexChanged.connect(self._on_profile_changed)
        combo_row.addWidget(self._profile_combo, stretch=1)
        profile_layout.addLayout(combo_row)

        # Profile 操作按鈕列（儲存 / 另存 / 刪除）
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._btn_save_profile = QPushButton("💾 儲存")
        self._btn_save_profile.setObjectName("btn_profile")
        self._btn_save_profile.setToolTip("將目前欄位值存回目前選取的 profile")
        self._btn_save_profile.clicked.connect(self._on_save_profile)
        btn_row.addWidget(self._btn_save_profile)

        self._btn_saveas_profile = QPushButton("➕ 另存新檔")
        self._btn_saveas_profile.setObjectName("btn_profile")
        self._btn_saveas_profile.setToolTip("將目前欄位值另存成新的具名 profile")
        self._btn_saveas_profile.clicked.connect(self._on_saveas_profile)
        btn_row.addWidget(self._btn_saveas_profile)

        self._btn_del_profile = QPushButton("🗑 刪除")
        self._btn_del_profile.setObjectName("btn_profile_del")
        self._btn_del_profile.setToolTip("刪除目前選取的 profile（至少保留一組）")
        self._btn_del_profile.clicked.connect(self._on_delete_profile)
        btn_row.addWidget(self._btn_del_profile)

        btn_row.addStretch()
        profile_layout.addLayout(btn_row)

        layout.addWidget(profile_group)

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
            "💡 提示：可用上方 profile 切換不同馬達設定；\n"
            "   修改欄位後按「💾 儲存」或「➕ 另存新檔」保留設定，\n"
            "   按「⚙ 套用參數」立即生效（並記為預設載入的 profile）。"
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
        btn_apply.clicked.connect(self._on_apply)
        btn_layout.addWidget(btn_apply)

        layout.addLayout(btn_layout)

    # ─── 公開介面 ──────────────────────────────────────────────────────────────

    def get_session_info(self) -> dict:
        """
        取得使用者輸入的參數資訊
        Returns:
            dict: {
                "profile_name":        str,   最終選用的 profile 名稱
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
        info = self._collect_fields()
        info["profile_name"] = self._current_profile_name
        return info

    # ─── Profile 管理 ──────────────────────────────────────────────────────────

    def _refresh_profile_combo(self, select_name: str = None):
        """
        重建 profile 下拉選單內容。

        Args:
            select_name: 重建後要選取的 profile 名稱（None = 使用目前 active）
        """
        target = select_name or self._current_profile_name
        # 暫時阻斷 currentIndexChanged 訊號，避免重建時誤觸切換帶入
        self._profile_combo.blockSignals(True)
        self._profile_combo.clear()
        names = MOTOR_PROFILES.list_profiles()
        self._profile_combo.addItems(names)
        if target in names:
            self._profile_combo.setCurrentText(target)
        self._profile_combo.blockSignals(False)

    def _on_profile_changed(self, _index: int):
        """使用者從下拉選單切換 profile → 帶入該 profile 的欄位值"""
        name = self._profile_combo.currentText()
        if not name:
            return
        self._current_profile_name = name
        self._load_profile_into_fields(name)

    def _load_profile_into_fields(self, name: str):
        """將指定 profile 的參數帶入各輸入欄位"""
        params = MOTOR_PROFILES.get_profile(name)
        # 阻斷 valueChanged（避免 enc_bits 變更觸發 PPR 自動覆蓋）
        self._enc_bits_spin.blockSignals(True)
        self._hall_ppr_spin.setValue(int(params["hall_pulses_per_rev"]))
        self._hall_vh_spin.setValue(float(params["hall_vh_min"]))
        self._hall_vl_spin.setValue(float(params["hall_vl_max"]))
        self._enc_bits_spin.setValue(int(params["resolution_bits"]))
        self._ppr_spin.setValue(int(params["ppr"]))
        self._enc_vh_spin.setValue(float(params["enc_vh_min"]))
        self._enc_vl_spin.setValue(float(params["enc_vl_max"]))
        self._ratio_tol_spin.setValue(float(params["ratio_tolerance"]))
        self._enc_bits_spin.blockSignals(False)
        self._update_ratio_hint()

    def _on_save_profile(self):
        """將目前欄位值存回目前選取的 profile"""
        name = self._current_profile_name
        params = self._collect_fields()
        if MOTOR_PROFILES.save_profile(name, params, set_active=True):
            self._refresh_profile_combo(select_name=name)
            QMessageBox.information(
                self, "已儲存",
                f"已將目前參數存回 profile：\n「{name}」"
            )
        else:
            QMessageBox.warning(self, "儲存失敗", "無法儲存 profile，請檢查名稱是否有效。")

    def _on_saveas_profile(self):
        """將目前欄位值另存成新的具名 profile"""
        name, ok = QInputDialog.getText(
            self, "另存新檔", "請輸入新的馬達型號 profile 名稱："
        )
        if not ok:
            return
        name = (name or "").strip()
        if not name:
            QMessageBox.warning(self, "名稱無效", "profile 名稱不可為空白。")
            return
        # 若同名詢問是否覆蓋
        if MOTOR_PROFILES.has_profile(name):
            reply = QMessageBox.question(
                self, "名稱已存在",
                f"profile「{name}」已存在，是否覆蓋？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

        params = self._collect_fields()
        if MOTOR_PROFILES.save_profile(name, params, set_active=True):
            self._current_profile_name = name
            self._refresh_profile_combo(select_name=name)
            QMessageBox.information(
                self, "已另存",
                f"已新增 profile：\n「{name}」"
            )
        else:
            QMessageBox.warning(self, "儲存失敗", "無法建立 profile，請檢查名稱是否有效。")

    def _on_delete_profile(self):
        """刪除目前選取的 profile"""
        name = self._current_profile_name
        if len(MOTOR_PROFILES.list_profiles()) <= 1:
            QMessageBox.warning(
                self, "無法刪除",
                "至少需保留一組 profile，無法刪除最後一組。"
            )
            return
        reply = QMessageBox.question(
            self, "確認刪除",
            f"確定要刪除 profile「{name}」？\n此操作無法復原。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        if MOTOR_PROFILES.delete_profile(name):
            # 切換到剩餘的 active profile
            self._current_profile_name = MOTOR_PROFILES.get_active_name()
            self._refresh_profile_combo(select_name=self._current_profile_name)
            self._load_profile_into_fields(self._current_profile_name)
            QMessageBox.information(
                self, "已刪除",
                f"已刪除 profile「{name}」，\n"
                f"目前套用：「{self._current_profile_name}」"
            )
        else:
            QMessageBox.warning(self, "刪除失敗", "無法刪除該 profile。")

    def _on_apply(self):
        """按「套用參數」：將目前選取 profile 設為 active 並關閉對話框"""
        # 確保選取的 profile 記為 active（供下次啟動自動載入）
        name = self._current_profile_name
        if MOTOR_PROFILES.has_profile(name):
            MOTOR_PROFILES.set_active(name)
        self.accept()

    # ─── 私有輔助方法 ──────────────────────────────────────────────────────────

    def _collect_fields(self) -> dict:
        """從各輸入欄位收集參數（不含 profile 名稱）"""
        return {
            "hall_pulses_per_rev": self._hall_ppr_spin.value(),
            "ppr":                 self._ppr_spin.value(),
            "resolution_bits":     self._enc_bits_spin.value(),
            "hall_vh_min":         self._hall_vh_spin.value(),
            "hall_vl_max":         self._hall_vl_spin.value(),
            "enc_vh_min":          self._enc_vh_spin.value(),
            "enc_vl_max":          self._enc_vl_spin.value(),
            "ratio_tolerance":     self._ratio_tol_spin.value(),
        }

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

"""
主視窗模組（重構版）
整合波形顯示、測試結果面板與控制按鈕
流程：連線後立即監控 → 操作員確認穩定 → 開始檢測（預設5分鐘）→ 自動儲存至 SQLite
"""

import time
import os
from pathlib import Path

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QSplitter, QStatusBar,
    QMessageBox, QFileDialog, QGroupBox, QSpinBox,
    QDoubleSpinBox, QFormLayout, QFrame, QProgressBar,
    QLineEdit, QInputDialog
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont

from config.thresholds import SAMPLING, HALL_THRESHOLDS, ENCODER_THRESHOLDS, DATABASE
from daq.daq_controller import DAQController
from daq.ai_reader import AIReader
from daq.di_reader import DIReader
from logic.hall_analyzer import HallAnalyzer
from logic.encoder_analyzer import EncoderAnalyzer
from logic.test_session import TestSession, SessionState
from ui.waveform_widget import WaveformWidget
from ui.result_panel import ResultPanel
from ui.session_dialog import SessionStartDialog
from ui.history_viewer import HistoryViewer
from report.report_generator import ReportGenerator
from db.database import DatabaseManager


# ─── 樣式 ──────────────────────────────────────────────────────────────────────
MAIN_STYLE = """
    QMainWindow, QWidget {
        background-color: #1E1E1E;
        color: #CCCCCC;
    }
    QPushButton {
        background-color: #2D5A8E;
        color: #FFFFFF;
        border: none;
        border-radius: 4px;
        padding: 6px 16px;
        font-size: 12px;
        font-weight: bold;
        min-width: 80px;
    }
    QPushButton:hover { background-color: #3A72B0; }
    QPushButton:pressed { background-color: #1E3F6B; }
    QPushButton:disabled { background-color: #3A3A3A; color: #666666; }
    QPushButton#btn_stop { background-color: #8E2D2D; }
    QPushButton#btn_stop:hover { background-color: #B03A3A; }
    QPushButton#btn_export { background-color: #2D7A3A; }
    QPushButton#btn_export:hover { background-color: #3A9A4A; }
    QPushButton#btn_history { background-color: #5A3A7A; }
    QPushButton#btn_history:hover { background-color: #7A4AAA; }
    QStatusBar {
        background-color: #252525;
        color: #AAAAAA;
        font-size: 11px;
    }
    QSplitter::handle { background-color: #444444; }
    QSpinBox, QDoubleSpinBox, QLineEdit {
        background-color: #2A2A2A;
        color: #CCCCCC;
        border: 1px solid #444444;
        border-radius: 3px;
        padding: 2px 4px;
    }
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
    QProgressBar {
        background-color: #2A2A2A;
        border: 1px solid #444444;
        border-radius: 4px;
        text-align: center;
        color: #FFFFFF;
        font-size: 11px;
    }
    QProgressBar::chunk {
        background-color: #2D8E2D;
        border-radius: 3px;
    }
"""

BTN_START_STYLE  = "background-color: #2D8E2D; color: #FFFFFF; border-radius: 4px; padding: 6px 16px; font-weight: bold; min-width: 100px;"
BTN_STOP_STYLE   = "background-color: #8E2D2D; color: #FFFFFF; border-radius: 4px; padding: 6px 16px; font-weight: bold; min-width: 100px;"
BTN_EARLY_STYLE  = "background-color: #7A5A00; color: #FFFFFF; border-radius: 4px; padding: 6px 16px; font-weight: bold; min-width: 100px;"


class MainWindow(QMainWindow):
    """
    馬達測試程式主視窗（重構版）

    狀態機：
        IDLE       → 程式啟動，尚未連線
        MONITORING → 連線成功，持續讀取 AI/DI，顯示即時波形
        TESTING    → 操作員按「開始檢測」，5 分鐘倒數計時
        SAVING     → 時間到或提前停止，寫入 DB
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("馬達測試系統 - Hall Sensor & Encoder 量測")
        self.setMinimumSize(1280, 820)
        self.setStyleSheet(MAIN_STYLE)

        # ── 核心 DAQ 元件 ─────────────────────────────────────────────────────
        self._daq          = DAQController()
        self._ai_reader    = AIReader(self._daq)
        self._di_reader    = DIReader(self._daq)
        self._hall_analyzer = HallAnalyzer()
        self._enc_analyzer  = EncoderAnalyzer()
        self._report_gen    = ReportGenerator()

        # ── 資料庫 ────────────────────────────────────────────────────────────
        self._db = DatabaseManager(DATABASE["db_path"])

        # ── 測試場次 ──────────────────────────────────────────────────────────
        self._session = TestSession(
            duration_s=float(DATABASE.get("default_duration_s", 300))
        )
        self._session.set_tick_callback(self._on_session_tick)
        self._session.set_done_callback(self._on_session_done)
        self._current_session_id: int = -1

        # ── 狀態旗標 ──────────────────────────────────────────────────────────
        self._is_monitoring = False   # 是否正在讀取 AI/DI（監控模式）
        self._last_hall_result = None
        self._last_enc_result  = None

        # ── UI ────────────────────────────────────────────────────────────────
        self._setup_ui()
        self._setup_timer()
        self._setup_status_bar()

        # 嘗試連線（連線成功後自動進入監控模式）
        self._connect_device()

    # ─── UI 建立 ───────────────────────────────────────────────────────────────

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        # 頂部工具列
        main_layout.addWidget(self._build_toolbar())

        # 檢測進度列（預設隱藏，檢測中才顯示）
        main_layout.addWidget(self._build_progress_bar())

        # 主要內容區（左：波形，右：結果 + 即時統計）
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(4)

        self._waveform_widget = WaveformWidget()
        splitter.addWidget(self._waveform_widget)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        self._result_panel = ResultPanel()
        right_layout.addWidget(self._result_panel)

        # 即時統計面板（檢測中顯示）
        right_layout.addWidget(self._build_live_stats_panel())

        right_layout.addWidget(self._build_settings_panel())

        splitter.addWidget(right_panel)
        splitter.setSizes([820, 460])

        main_layout.addWidget(splitter)

    def _build_toolbar(self) -> QWidget:
        """建立頂部工具列"""
        toolbar = QWidget()
        toolbar.setFixedHeight(52)
        toolbar.setStyleSheet("background-color: #252525; border-radius: 4px;")
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        # 標題
        title_lbl = QLabel("馬達測試系統")
        title_lbl.setFont(QFont("Arial", 14, QFont.Bold))
        title_lbl.setStyleSheet("color: #4AABFF;")
        layout.addWidget(title_lbl)

        # 裝置狀態
        self._device_status_lbl = QLabel("● 未連線")
        self._device_status_lbl.setStyleSheet("color: #FF4444; font-size: 12px;")
        layout.addWidget(self._device_status_lbl)

        layout.addStretch()

        # ── 控制按鈕 ──────────────────────────────────────────────────────────
        # 開始檢測（監控模式下可用）
        self._btn_start = QPushButton("▶ 開始檢測")
        self._btn_start.setStyleSheet(BTN_START_STYLE)
        self._btn_start.setEnabled(False)
        self._btn_start.clicked.connect(self._on_start_test)
        layout.addWidget(self._btn_start)

        # 提前停止（檢測中才可用）
        self._btn_early_stop = QPushButton("⏹ 提前停止")
        self._btn_early_stop.setStyleSheet(BTN_EARLY_STYLE)
        self._btn_early_stop.setEnabled(False)
        self._btn_early_stop.clicked.connect(self._on_early_stop)
        layout.addWidget(self._btn_early_stop)

        self._btn_reset_enc = QPushButton("↺ 重置計數")
        self._btn_reset_enc.clicked.connect(self._on_reset_encoder)
        layout.addWidget(self._btn_reset_enc)

        self._btn_export = QPushButton("💾 匯出報表")
        self._btn_export.setObjectName("btn_export")
        self._btn_export.clicked.connect(self._on_export)
        layout.addWidget(self._btn_export)

        self._btn_history = QPushButton("📋 歷史記錄")
        self._btn_history.setObjectName("btn_history")
        self._btn_history.clicked.connect(self._on_show_history)
        layout.addWidget(self._btn_history)

        self._btn_db_path = QPushButton("🗄 DB 路徑")
        self._btn_db_path.clicked.connect(self._on_change_db_path)
        layout.addWidget(self._btn_db_path)

        self._btn_reconnect = QPushButton("🔌 重新連線")
        self._btn_reconnect.clicked.connect(self._connect_device)
        layout.addWidget(self._btn_reconnect)

        return toolbar

    def _build_progress_bar(self) -> QWidget:
        """建立檢測進度列（含倒數計時與序號顯示）"""
        self._progress_container = QWidget()
        self._progress_container.setFixedHeight(48)
        self._progress_container.setStyleSheet(
            "background-color: #1A2A1A; border-radius: 4px; border: 1px solid #2D5A2D;"
        )
        self._progress_container.setVisible(False)

        layout = QHBoxLayout(self._progress_container)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(10)

        self._session_info_lbl = QLabel("🔵 檢測中")
        self._session_info_lbl.setStyleSheet("color: #44FF44; font-weight: bold; font-size: 13px;")
        layout.addWidget(self._session_info_lbl)

        self._serial_display_lbl = QLabel("")
        self._serial_display_lbl.setStyleSheet("color: #AAAAAA; font-size: 12px;")
        layout.addWidget(self._serial_display_lbl)

        layout.addStretch()

        self._countdown_lbl = QLabel("05:00")
        self._countdown_lbl.setStyleSheet(
            "color: #FFFF44; font-size: 16px; font-weight: bold; font-family: Consolas;"
        )
        layout.addWidget(self._countdown_lbl)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 1000)
        self._progress_bar.setValue(0)
        self._progress_bar.setFixedWidth(200)
        self._progress_bar.setTextVisible(False)
        layout.addWidget(self._progress_bar)

        return self._progress_container

    def _build_live_stats_panel(self) -> QGroupBox:
        """建立即時統計面板"""
        self._live_stats_group = QGroupBox("即時統計")
        self._live_stats_group.setVisible(False)
        layout = QVBoxLayout(self._live_stats_group)
        layout.setSpacing(4)

        # Hall 統計列
        hall_row = QHBoxLayout()
        hall_row.addWidget(QLabel("Hall:"))
        self._hall_pass_lbl  = QLabel("PASS: 0")
        self._hall_pass_lbl.setStyleSheet("color: #44FF44;")
        self._hall_fail_lbl  = QLabel("FAIL: 0")
        self._hall_fail_lbl.setStyleSheet("color: #FF4444;")
        self._hall_rate_lbl  = QLabel("成功率: ---%")
        self._hall_rate_lbl.setStyleSheet("color: #FFFF44; font-weight: bold;")
        hall_row.addWidget(self._hall_pass_lbl)
        hall_row.addWidget(self._hall_fail_lbl)
        hall_row.addWidget(self._hall_rate_lbl)
        hall_row.addStretch()
        layout.addLayout(hall_row)

        # Encoder 統計列
        enc_row = QHBoxLayout()
        enc_row.addWidget(QLabel("Enc: "))
        self._enc_pass_lbl   = QLabel("PASS: 0")
        self._enc_pass_lbl.setStyleSheet("color: #44FF44;")
        self._enc_fail_lbl   = QLabel("FAIL: 0")
        self._enc_fail_lbl.setStyleSheet("color: #FF4444;")
        self._enc_rate_lbl   = QLabel("成功率: ---%")
        self._enc_rate_lbl.setStyleSheet("color: #FFFF44; font-weight: bold;")
        enc_row.addWidget(self._enc_pass_lbl)
        enc_row.addWidget(self._enc_fail_lbl)
        enc_row.addWidget(self._enc_rate_lbl)
        enc_row.addStretch()
        layout.addLayout(enc_row)

        # RPM 列
        rpm_row = QHBoxLayout()
        self._avg_rpm_lbl = QLabel("平均 RPM: ---")
        self._avg_rpm_lbl.setStyleSheet("color: #AAAAFF;")
        self._max_rpm_lbl = QLabel("最高: ---")
        self._max_rpm_lbl.setStyleSheet("color: #AAAAFF;")
        rpm_row.addWidget(self._avg_rpm_lbl)
        rpm_row.addWidget(self._max_rpm_lbl)
        rpm_row.addStretch()
        layout.addLayout(rpm_row)

        return self._live_stats_group

    def _build_settings_panel(self) -> QGroupBox:
        """建立設定面板"""
        group = QGroupBox("設定")
        form = QFormLayout(group)
        form.setSpacing(6)

        # Encoder PPR 設定
        self._ppr_spin = QSpinBox()
        self._ppr_spin.setRange(1, 100000)
        self._ppr_spin.setValue(ENCODER_THRESHOLDS["ppr"])
        self._ppr_spin.setSuffix(" PPR")
        self._ppr_spin.valueChanged.connect(self._on_ppr_changed)
        form.addRow("Encoder PPR:", self._ppr_spin)

        # Hall VH_min 設定
        self._hall_vh_spin = QDoubleSpinBox()
        self._hall_vh_spin.setRange(0.0, 5.0)
        self._hall_vh_spin.setSingleStep(0.1)
        self._hall_vh_spin.setDecimals(2)
        self._hall_vh_spin.setValue(HALL_THRESHOLDS["vh_min"])
        self._hall_vh_spin.setSuffix(" V")
        self._hall_vh_spin.valueChanged.connect(self._on_hall_threshold_changed)
        form.addRow("Hall VH_min:", self._hall_vh_spin)

        # Hall VL_max 設定
        self._hall_vl_spin = QDoubleSpinBox()
        self._hall_vl_spin.setRange(0.0, 5.0)
        self._hall_vl_spin.setSingleStep(0.1)
        self._hall_vl_spin.setDecimals(2)
        self._hall_vl_spin.setValue(HALL_THRESHOLDS["vl_max"])
        self._hall_vl_spin.setSuffix(" V")
        self._hall_vl_spin.valueChanged.connect(self._on_hall_threshold_changed)
        form.addRow("Hall VL_max:", self._hall_vl_spin)

        # Encoder VH_min 設定
        self._enc_vh_spin = QDoubleSpinBox()
        self._enc_vh_spin.setRange(0.0, 10.0)
        self._enc_vh_spin.setSingleStep(0.1)
        self._enc_vh_spin.setDecimals(2)
        self._enc_vh_spin.setValue(ENCODER_THRESHOLDS["vh_min"])
        self._enc_vh_spin.setSuffix(" V")
        self._enc_vh_spin.valueChanged.connect(self._on_enc_threshold_changed)
        form.addRow("Encoder VH_min:", self._enc_vh_spin)

        # Encoder VL_max 設定
        self._enc_vl_spin = QDoubleSpinBox()
        self._enc_vl_spin.setRange(0.0, 10.0)
        self._enc_vl_spin.setSingleStep(0.1)
        self._enc_vl_spin.setDecimals(2)
        self._enc_vl_spin.setValue(ENCODER_THRESHOLDS["vl_max"])
        self._enc_vl_spin.setSuffix(" V")
        self._enc_vl_spin.valueChanged.connect(self._on_enc_threshold_changed)
        form.addRow("Encoder VL_max:", self._enc_vl_spin)

        return group

    def _setup_timer(self):
        """設定 GUI 更新計時器（監控模式持續運行）"""
        self._update_timer = QTimer(self)
        self._update_timer.setInterval(SAMPLING["display_update_ms"])
        self._update_timer.timeout.connect(self._update_display)

    def _setup_status_bar(self):
        """設定狀態列"""
        self._status_bar = self.statusBar()
        self._status_bar.showMessage("就緒 | 請連線裝置，連線後將自動開始監控")

    # ─── 裝置連線 ──────────────────────────────────────────────────────────────

    def _connect_device(self):
        """連線到 DAQ 裝置，成功後自動進入監控模式"""
        # 若已在監控中，先停止
        if self._is_monitoring:
            self._stop_monitoring()

        success, error_msg = self._daq.connect()

        if success:
            # 真實硬體或已是模擬模式 → 直接進入監控
            mode = "模擬模式" if self._daq.is_simulation else "USB-4716"
            self._device_status_lbl.setText(f"● 已連線 ({mode})")
            self._device_status_lbl.setStyleSheet("color: #44FF44; font-size: 12px;")
            self._status_bar.showMessage(f"裝置已連線: {mode} | 監控中，訊號穩定後按「開始檢測」")
            self._start_monitoring()

        else:
            # 有 SDK 但裝置未偵測到 → 詢問是否切換模擬模式
            reply = QMessageBox.question(
                self,
                "裝置未偵測到",
                f"無法連線到 {self._daq.device_description}\n\n"
                f"錯誤原因：{error_msg}\n\n"
                f"是否切換至【模擬模式】繼續？\n"
                f"（模擬模式使用假資料，僅供 UI 操作確認，不代表真實量測結果）",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )

            if reply == QMessageBox.Yes:
                # 使用者同意 → 強制切換模擬模式
                self._daq._simulation_mode = True
                self._daq._connected = True
                self._device_status_lbl.setText("● 已連線 (模擬模式)")
                self._device_status_lbl.setStyleSheet("color: #FFAA00; font-size: 12px;")
                self._status_bar.showMessage("⚠ 模擬模式 | 使用假資料，僅供 UI 確認")
                print("[MainWindow] 使用者選擇切換至模擬模式")
                self._start_monitoring()
            else:
                # 使用者拒絕 → 保持未連線狀態
                self._device_status_lbl.setText("● 連線失敗")
                self._device_status_lbl.setStyleSheet("color: #FF4444; font-size: 12px;")
                self._status_bar.showMessage("裝置連線失敗，請檢查 USB-4716 連接後重新連線")
                self._btn_start.setEnabled(False)

    def _start_monitoring(self):
        """啟動監控模式：持續讀取 AI/DI，顯示即時波形"""
        if self._is_monitoring:
            return
        self._is_monitoring = True
        self._ai_reader.start()
        self._di_reader.start()
        self._update_timer.start()
        self._btn_start.setEnabled(True)
        print("[MainWindow] 監控模式已啟動")

    def _stop_monitoring(self):
        """停止監控模式"""
        self._is_monitoring = False
        self._update_timer.stop()
        self._ai_reader.stop()
        self._di_reader.stop()
        self._btn_start.setEnabled(False)
        print("[MainWindow] 監控模式已停止")

    # ─── 檢測控制事件 ──────────────────────────────────────────────────────────

    def _on_start_test(self):
        """操作員按「開始檢測」：開啟對話框輸入序號，然後啟動場次"""
        if not self._daq.is_connected:
            QMessageBox.warning(self, "警告", "裝置未連線，請先連線 USB-4716")
            return
        if self._session.is_running:
            QMessageBox.warning(self, "警告", "檢測已在進行中")
            return

        # 開啟場次啟動對話框
        dlg = SessionStartDialog(
            parent=self,
            default_duration_min=int(DATABASE.get("default_duration_s", 300) // 60)
        )
        if dlg.exec_() != SessionStartDialog.Accepted:
            return

        info = dlg.get_session_info()
        serial_no   = info["serial_no"]
        operator    = info["operator"]
        duration_s  = info["duration_s"]

        # 更新場次時長
        self._session.duration_s = duration_s

        # 在 DB 建立場次記錄
        try:
            self._current_session_id = self._db.create_session(
                serial_no=serial_no,
                operator=operator
            )
        except Exception as e:
            QMessageBox.critical(self, "DB 錯誤", f"無法建立場次記錄：\n{e}")
            return

        # 清除分析歷史（監控期間累積的不算）
        self._hall_analyzer.clear_history()
        self._enc_analyzer.clear_history()
        self._report_gen.clear()

        # 啟動場次
        self._session.start(serial_no=serial_no, operator=operator)

        # 更新 UI 狀態
        self._btn_start.setEnabled(False)
        self._btn_early_stop.setEnabled(True)
        self._progress_container.setVisible(True)
        self._live_stats_group.setVisible(True)

        serial_display = f"序號: {serial_no}" if serial_no else "序號: (未輸入)"
        self._session_info_lbl.setText("🔵 檢測中")
        self._serial_display_lbl.setText(serial_display)

        total_min = int(duration_s // 60)
        self._status_bar.showMessage(
            f"檢測中 | {serial_display} | 時長: {total_min} 分鐘"
        )

    def _on_early_stop(self):
        """操作員提前停止檢測"""
        if not self._session.is_running:
            return
        reply = QMessageBox.question(
            self, "確認提前停止",
            "確定要提前停止檢測並儲存目前結果？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        stats = self._session.stop()
        self._save_session_result(stats)

    def _on_session_tick(self, elapsed_s: float, remaining_s: float):
        """場次計時回呼（每秒觸發，來自背景執行緒，需透過 QTimer 更新 UI）"""
        # 使用 QTimer.singleShot 確保在主執行緒更新 UI
        from PyQt5.QtCore import QTimer as _QTimer
        _QTimer.singleShot(0, lambda: self._update_countdown(elapsed_s, remaining_s))

    def _update_countdown(self, elapsed_s: float, remaining_s: float):
        """在主執行緒更新倒數計時 UI"""
        mins = int(remaining_s) // 60
        secs = int(remaining_s) % 60
        self._countdown_lbl.setText(f"{mins:02d}:{secs:02d}")

        # 進度條（0~1000）
        if self._session.duration_s > 0:
            progress = int(elapsed_s / self._session.duration_s * 1000)
            self._progress_bar.setValue(min(1000, progress))

        # 即時統計
        live = self._session.get_live_stats()
        self._hall_pass_lbl.setText(f"PASS: {live['hall_pass']}")
        self._hall_fail_lbl.setText(f"FAIL: {live['hall_fail']}")
        hall_rate = live['hall_pass_rate'] * 100
        self._hall_rate_lbl.setText(f"成功率: {hall_rate:.1f}%")

        self._enc_pass_lbl.setText(f"PASS: {live['enc_pass']}")
        self._enc_fail_lbl.setText(f"FAIL: {live['enc_fail']}")
        enc_rate = live['enc_pass_rate'] * 100
        self._enc_rate_lbl.setText(f"成功率: {enc_rate:.1f}%")

        self._avg_rpm_lbl.setText(f"平均 RPM: {live['avg_rpm']:.1f}")
        self._max_rpm_lbl.setText(f"最高: {live['max_rpm']:.1f}")

    def _on_session_done(self, stats):
        """場次完成回呼（時間到後由背景執行緒觸發）"""
        from PyQt5.QtCore import QTimer as _QTimer
        _QTimer.singleShot(0, lambda: self._save_session_result(stats))

    def _save_session_result(self, stats):
        """儲存場次結果至 DB 並更新 UI"""
        try:
            # 關閉場次
            self._db.close_session(
                self._current_session_id,
                duration_s=stats.actual_duration_s
            )
            # 儲存統計結果
            self._db.save_result(
                session_id=self._current_session_id,
                hall_total=stats.hall_total,
                hall_pass=stats.hall_pass,
                enc_total=stats.enc_total,
                enc_pass=stats.enc_pass,
                avg_rpm=stats.avg_rpm,
                max_rpm=stats.max_rpm,
                min_rpm=stats.min_rpm,
            )
        except Exception as e:
            QMessageBox.critical(self, "DB 錯誤", f"儲存結果失敗：\n{e}")

        # 恢復 UI 狀態
        self._btn_start.setEnabled(True)
        self._btn_early_stop.setEnabled(False)
        self._progress_container.setVisible(False)
        self._live_stats_group.setVisible(False)
        self._progress_bar.setValue(0)

        # 顯示結果摘要
        overall = "✔ PASS" if stats.overall_pass else "✘ FAIL"
        serial  = self._session.serial_no or "(無序號)"
        msg = (
            f"檢測完成！\n\n"
            f"序號：{serial}\n"
            f"實際時長：{stats.actual_duration_s:.0f} 秒\n\n"
            f"Hall Sensor：{stats.hall_pass}/{stats.hall_total} "
            f"({stats.hall_pass_rate*100:.1f}%)\n"
            f"Encoder：{stats.enc_pass}/{stats.enc_total} "
            f"({stats.enc_pass_rate*100:.1f}%)\n\n"
            f"整體結果：{overall}\n\n"
            f"結果已自動儲存至資料庫"
        )
        QMessageBox.information(self, "檢測完成", msg)

        self._status_bar.showMessage(
            f"檢測完成 | {serial} | Hall {stats.hall_pass_rate*100:.1f}% | "
            f"Enc {stats.enc_pass_rate*100:.1f}% | {overall} | 監控中..."
        )

        # 重置場次，回到監控模式
        self._session.reset()

    def _on_reset_encoder(self):
        """重置 Encoder 計數器"""
        self._di_reader.reset_encoder()
        self._status_bar.showMessage("Encoder 計數器已重置")

    def _on_export(self):
        """匯出最近一次場次的原始報表（若有）"""
        if not self._hall_analyzer.get_history() and not self._enc_analyzer.get_history():
            QMessageBox.information(self, "提示", "尚無測試資料，請先進行量測")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "儲存報表", f"motor_test_{time.strftime('%Y%m%d_%H%M%S')}",
            "Excel 檔案 (*.xlsx);;CSV 檔案 (*.csv)"
        )
        if not path:
            return

        try:
            if path.endswith(".xlsx"):
                self._report_gen.export_excel(
                    path,
                    self._hall_analyzer.get_history(),
                    self._enc_analyzer.get_history()
                )
            else:
                self._report_gen.export_csv(
                    path,
                    self._hall_analyzer.get_history(),
                    self._enc_analyzer.get_history()
                )
            self._status_bar.showMessage(f"報表已匯出: {path}")
            QMessageBox.information(self, "成功", f"報表已儲存至:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "錯誤", f"匯出失敗:\n{e}")

    def _on_show_history(self):
        """開啟歷史記錄查詢視窗"""
        viewer = HistoryViewer(db_manager=self._db, parent=self)
        viewer.exec_()

    def _on_change_db_path(self):
        """變更資料庫儲存路徑"""
        current_path = self._db.get_db_path()
        new_path, _ = QFileDialog.getSaveFileName(
            self, "選擇資料庫路徑",
            current_path,
            "SQLite 資料庫 (*.db);;所有檔案 (*)"
        )
        if not new_path:
            return
        if not new_path.endswith(".db"):
            new_path += ".db"
        try:
            self._db.set_db_path(new_path)
            DATABASE["db_path"] = new_path
            self._status_bar.showMessage(f"資料庫路徑已變更: {new_path}")
            QMessageBox.information(self, "成功", f"資料庫路徑已變更至：\n{new_path}")
        except Exception as e:
            QMessageBox.critical(self, "錯誤", f"變更路徑失敗：\n{e}")

    # ─── 設定變更 ──────────────────────────────────────────────────────────────

    def _on_ppr_changed(self, value: int):
        """更新 Encoder PPR"""
        ENCODER_THRESHOLDS["ppr"] = value
        self._di_reader._ppr = value
        self._enc_analyzer.PPR = value

    def _on_hall_threshold_changed(self):
        """更新 Hall 電壓閾值"""
        HALL_THRESHOLDS["vh_min"] = self._hall_vh_spin.value()
        HALL_THRESHOLDS["vl_max"] = self._hall_vl_spin.value()
        self._hall_analyzer.VH_MIN = HALL_THRESHOLDS["vh_min"]
        self._hall_analyzer.VL_MAX = HALL_THRESHOLDS["vl_max"]

    def _on_enc_threshold_changed(self):
        """更新 Encoder 電壓閾值"""
        ENCODER_THRESHOLDS["vh_min"] = self._enc_vh_spin.value()
        ENCODER_THRESHOLDS["vl_max"] = self._enc_vl_spin.value()
        self._enc_analyzer.VH_MIN = ENCODER_THRESHOLDS["vh_min"]
        self._enc_analyzer.VL_MAX = ENCODER_THRESHOLDS["vl_max"]

    # ─── 顯示更新 ──────────────────────────────────────────────────────────────

    def _update_display(self):
        """定時更新 GUI 顯示（由 QTimer 觸發，監控模式持續運行）"""
        try:
            self._update_waveforms()
            self._update_analysis()
        except Exception as e:
            print(f"[MainWindow] 顯示更新錯誤: {e}")

    def _update_waveforms(self):
        """更新波形顯示"""
        # Hall AI 波形
        u_buf = self._ai_reader.get_buffer(HALL_THRESHOLDS["channels"]["U"])
        v_buf = self._ai_reader.get_buffer(HALL_THRESHOLDS["channels"]["V"])
        w_buf = self._ai_reader.get_buffer(HALL_THRESHOLDS["channels"]["W"])
        self._waveform_widget.update_hall_waveform(u_buf, v_buf, w_buf)

        # Encoder AI + DI 波形
        a_ai = self._ai_reader.get_buffer(ENCODER_THRESHOLDS["channels"]["A"])
        b_ai = self._ai_reader.get_buffer(ENCODER_THRESHOLDS["channels"]["B"])
        a_di = self._di_reader.get_encoder_a_buffer()
        b_di = self._di_reader.get_encoder_b_buffer()
        self._waveform_widget.update_encoder_waveform(a_ai, b_ai, a_di, b_di)

    def _update_analysis(self):
        """更新分析結果顯示，並在檢測中時累積樣本"""
        t = time.time()

        # Hall 分析
        hall_voltages      = self._ai_reader.get_hall_voltages()
        hall_di_states_raw = self._di_reader.get_hall_states()
        hall_result = self._hall_analyzer.analyze(
            voltages=hall_voltages,
            di_states=hall_di_states_raw,
            timestamp=t
        )
        self._last_hall_result = hall_result
        self._result_panel.update_hall(hall_result)

        # Encoder 分析
        enc_voltages = self._ai_reader.get_encoder_voltages()
        enc_state    = self._di_reader.get_encoder_state()
        enc_result   = self._enc_analyzer.analyze(
            voltages=enc_voltages,
            di_states={"A": enc_state["A"], "B": enc_state["B"]},
            count=enc_state["count"],
            rpm=enc_state["rpm"],
            position_deg=enc_state["position_deg"],
            a_buffer=self._di_reader.get_encoder_a_buffer(),
            b_buffer=self._di_reader.get_encoder_b_buffer(),
            timestamp=t
        )
        self._last_enc_result = enc_result
        self._result_panel.update_encoder(enc_result)

        # 若場次正在執行，累積樣本（不保留原始資料，只計數）
        if self._session.is_running:
            self._session.add_sample(hall_result, enc_result)

        # 報表原始資料（供手動匯出用）
        self._report_gen.add_record(hall_result, enc_result)

    # ─── 視窗關閉 ──────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        """視窗關閉時釋放資源"""
        # 若場次正在執行，先停止並儲存
        if self._session.is_running:
            stats = self._session.stop()
            try:
                self._db.close_session(
                    self._current_session_id,
                    duration_s=stats.actual_duration_s
                )
                self._db.save_result(
                    session_id=self._current_session_id,
                    hall_total=stats.hall_total,
                    hall_pass=stats.hall_pass,
                    enc_total=stats.enc_total,
                    enc_pass=stats.enc_pass,
                    avg_rpm=stats.avg_rpm,
                    max_rpm=stats.max_rpm,
                    min_rpm=stats.min_rpm,
                )
            except Exception as e:
                print(f"[MainWindow] 關閉時儲存失敗: {e}")

        self._stop_monitoring()
        self._daq.disconnect()
        event.accept()

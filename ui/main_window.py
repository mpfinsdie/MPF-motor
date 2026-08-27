"""
主視窗模組（重構版）
整合波形顯示、測試結果面板與控制按鈕
流程：連線後監控預設關閉 → 手動按「監控開關」啟動即時觀察（10 kHz 標示）
      → 操作員確認穩定 → 開始高取樣診斷（200kHz 高速採樣 5CH × 2輪）
      → 診斷完成後自動分析 PASS/FAIL，存成 npz 並寫入 DB 歷史記錄

即時監控模式（預設關閉）：
  - 使用 InstantAiCtrl 輪詢（約 100 Hz），標示為 10 kHz
  - 僅供初步觀察，不做 PASS/FAIL 判斷
  - 手動按「監控開關」按鈕啟停

高取樣率診斷模式：
  - 一次專注採樣 1 個 AI 通道，200kHz × 10 秒，輪流 5 CH，跑 2 輪
  - 診斷期間暫停監控，即時顯示當前 CH 高取樣波形
  - 完成後由 DiagAnalyzer 分析 PASS/FAIL，存成 npz，寫入 DB 歷史記錄
"""

import time
import os
from pathlib import Path

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QSplitter, QStatusBar,
    QMessageBox, QFileDialog, QGroupBox, QSpinBox,
    QDoubleSpinBox, QFormLayout, QFrame, QProgressBar,
    QLineEdit, QInputDialog, QStackedWidget
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont

from config.thresholds import SAMPLING, HALL_THRESHOLDS, ENCODER_THRESHOLDS, DATABASE, DIAGNOSTIC
from daq.daq_controller import DAQController
from daq.ai_reader import AIReader
from daq.di_reader import DIReader
from logic.hall_analyzer import HallAnalyzer
from logic.encoder_analyzer import EncoderAnalyzer
from logic.test_session import TestSession, SessionState
from logic.waveform_recorder import WaveformRecorder
from logic.diagnostic_scanner import DiagnosticScanner
from logic.diag_analyzer import DiagAnalyzer
from ui.waveform_widget import WaveformWidget
from ui.diagnostic_widget import DiagnosticWidget
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

BTN_START_STYLE      = "background-color: #2D8E2D; color: #FFFFFF; border-radius: 4px; padding: 6px 16px; font-weight: bold; min-width: 100px;"
BTN_STOP_STYLE       = "background-color: #8E2D2D; color: #FFFFFF; border-radius: 4px; padding: 6px 16px; font-weight: bold; min-width: 100px;"
BTN_EARLY_STYLE      = "background-color: #7A5A00; color: #FFFFFF; border-radius: 4px; padding: 6px 16px; font-weight: bold; min-width: 100px;"
BTN_DIAG_STYLE       = "background-color: #2D5A8E; color: #FFFFFF; border-radius: 4px; padding: 6px 16px; font-weight: bold; min-width: 110px;"
BTN_DIAG_STOP_STYLE  = "background-color: #8E2D5A; color: #FFFFFF; border-radius: 4px; padding: 6px 16px; font-weight: bold; min-width: 110px;"
BTN_MON_ON_STYLE     = "background-color: #2D7A3A; color: #FFFFFF; border-radius: 4px; padding: 6px 16px; font-weight: bold; min-width: 110px;"
BTN_MON_OFF_STYLE    = "background-color: #5A5A00; color: #FFFFFF; border-radius: 4px; padding: 6px 16px; font-weight: bold; min-width: 110px;"


class MainWindow(QMainWindow):
    """
    馬達測試程式主視窗（重構版）

    狀態機：
        IDLE       → 程式啟動，尚未連線
        MONITORING → 連線成功，持續讀取 AI/DI，顯示即時波形
        TESTING    → 操作員按「開始檢測」，5 分鐘倒數計時
        SAVING     → 時間到或提前停止，寫入 DB
    """

    # Qt Signal：場次完成時由背景執行緒 emit，確保 _save_session_result 在主執行緒執行
    _session_done_signal = pyqtSignal(object)

    # Qt Signals：診斷用（確保背景執行緒資料在主執行緒更新 UI）
    _diag_chunk_signal    = pyqtSignal(int, int, object, float)   # ch_idx, round_idx, chunk, elapsed_s
    _diag_progress_signal = pyqtSignal(int, int, float, float, str)  # ch_idx, round_idx, elapsed_s, remaining_s, ch_name
    _diag_done_signal     = pyqtSignal(object)                    # result dict

    def __init__(self):
        super().__init__()
        self.setWindowTitle("馬達測試系統 - Hall Sensor & Encoder 量測")
        self.setMinimumSize(1280, 600)
        self.setMaximumHeight(600)
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

        # ── 波形錄製器（FAIL 時儲存 .npz）────────────────────────────────────
        self._waveform_recorder = WaveformRecorder()

        # ── 診斷掃描器 ────────────────────────────────────────────────────────
        self._diag_scanner: DiagnosticScanner = None
        self._diag_session_id: int = -1
        self._diag_start_time: float = 0.0
        self._is_diagnosing: bool = False

        # 連接 signal：確保場次完成時在主執行緒執行 _save_session_result
        self._session_done_signal.connect(self._save_session_result)

        # 連接診斷 signals（確保在主執行緒更新 UI）
        self._diag_chunk_signal.connect(self._on_diag_chunk)
        self._diag_progress_signal.connect(self._on_diag_progress)
        self._diag_done_signal.connect(self._on_diag_done)

        # ── 狀態旗標 ──────────────────────────────────────────────────────────
        self._is_monitoring = False   # 是否正在讀取 AI/DI（監控模式，預設關閉）
        self._last_hall_result = None
        self._last_enc_result  = None
        self._last_diag_round  = -1   # 上次診斷輪次（用於偵測通道切換）

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

        # 診斷進度列（預設隱藏，診斷中才顯示）
        main_layout.addWidget(self._build_diag_progress_bar())

        # ── 主要內容區（QStackedWidget 切換監控/診斷視圖）────────────────────
        self._content_stack = QStackedWidget()

        # Page 0：監控模式（左：波形，右：結果 + 即時統計）
        monitor_page = QWidget()
        monitor_layout = QVBoxLayout(monitor_page)
        monitor_layout.setContentsMargins(0, 0, 0, 0)

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

        splitter.addWidget(right_panel)
        splitter.setSizes([820, 460])
        monitor_layout.addWidget(splitter)

        self._content_stack.addWidget(monitor_page)   # index 0

        # Page 1：診斷模式（全寬高取樣波形圖）
        self._diag_widget = DiagnosticWidget()
        self._content_stack.addWidget(self._diag_widget)  # index 1

        main_layout.addWidget(self._content_stack)

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
        # 監控開關（預設關閉，手動啟停即時監控）
        self._btn_monitor = QPushButton("📡 監控：關")
        self._btn_monitor.setStyleSheet(BTN_MON_OFF_STYLE)
        self._btn_monitor.setEnabled(False)   # 連線後才啟用
        self._btn_monitor.setToolTip(
            f"即時監控（InstantAI 輪詢，標示 {SAMPLING['ai_sample_rate']:,} Hz）\n"
            "預設關閉，僅供初步觀察，不做 PASS/FAIL 判斷"
        )
        self._btn_monitor.clicked.connect(self._on_toggle_monitor)
        layout.addWidget(self._btn_monitor)

        # 開始檢測（連線後可用，不需監控開啟）
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

        # 高取樣診斷（連線後可用，不需監控開啟）
        self._btn_diag = QPushButton("🔬 高取樣診斷")
        self._btn_diag.setStyleSheet(BTN_DIAG_STYLE)
        self._btn_diag.setEnabled(False)
        self._btn_diag.setToolTip(
            f"逐一採樣 5 個 AI 通道，每 CH {DIAGNOSTIC['seconds_per_ch']}s × {DIAGNOSTIC['sample_rate']:,}Hz，"
            f"共 {DIAGNOSTIC['rounds']} 輪，結果存成 npz 並自動分析 PASS/FAIL"
        )
        self._btn_diag.clicked.connect(self._on_start_diag)
        layout.addWidget(self._btn_diag)

        # 提早結束診斷（診斷中才可用）
        self._btn_diag_stop = QPushButton("⏹ 結束診斷")
        self._btn_diag_stop.setStyleSheet(BTN_DIAG_STOP_STYLE)
        self._btn_diag_stop.setEnabled(False)
        self._btn_diag_stop.setToolTip("提早結束診斷，已採資料仍會儲存並分析")
        self._btn_diag_stop.clicked.connect(self._on_stop_diag)
        layout.addWidget(self._btn_diag_stop)

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

    def _build_diag_progress_bar(self) -> QWidget:
        """建立診斷進度列（診斷中才顯示）"""
        self._diag_progress_container = QWidget()
        self._diag_progress_container.setFixedHeight(48)
        self._diag_progress_container.setStyleSheet(
            "background-color: #1A1A2A; border-radius: 4px; border: 1px solid #2D2D5A;"
        )
        self._diag_progress_container.setVisible(False)

        layout = QHBoxLayout(self._diag_progress_container)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(10)

        # 診斷標示
        diag_lbl = QLabel("🔬 高取樣診斷")
        diag_lbl.setStyleSheet("color: #4AABFF; font-weight: bold; font-size: 13px;")
        layout.addWidget(diag_lbl)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.VLine)
        sep1.setStyleSheet("background-color: #444444;")
        sep1.setFixedWidth(1)
        layout.addWidget(sep1)

        # 當前通道名稱
        self._diag_ch_lbl = QLabel("—")
        self._diag_ch_lbl.setStyleSheet("color: #FFAA44; font-weight: bold; font-size: 13px;")
        layout.addWidget(self._diag_ch_lbl)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.VLine)
        sep2.setStyleSheet("background-color: #444444;")
        sep2.setFixedWidth(1)
        layout.addWidget(sep2)

        # 輪次
        self._diag_round_lbl = QLabel("第 — / — 輪")
        self._diag_round_lbl.setStyleSheet("color: #FFFF44; font-size: 12px;")
        layout.addWidget(self._diag_round_lbl)

        layout.addStretch()

        # 單 CH 倒數
        self._diag_countdown_lbl = QLabel("⏱ --.-s")
        self._diag_countdown_lbl.setStyleSheet(
            "color: #FF8844; font-size: 14px; font-weight: bold; font-family: Consolas;"
        )
        layout.addWidget(self._diag_countdown_lbl)

        sep3 = QFrame()
        sep3.setFrameShape(QFrame.VLine)
        sep3.setStyleSheet("background-color: #444444;")
        sep3.setFixedWidth(1)
        layout.addWidget(sep3)

        # 整體進度條
        self._diag_progress_bar = QProgressBar()
        self._diag_progress_bar.setRange(0, 1000)
        self._diag_progress_bar.setValue(0)
        self._diag_progress_bar.setFixedWidth(180)
        self._diag_progress_bar.setTextVisible(False)
        self._diag_progress_bar.setStyleSheet(
            "QProgressBar::chunk { background-color: #2D5A8E; border-radius: 3px; }"
        )
        layout.addWidget(self._diag_progress_bar)

        # 整體進度文字
        self._diag_progress_lbl = QLabel("0 / 0")
        self._diag_progress_lbl.setStyleSheet("color: #AAAAAA; font-size: 11px;")
        layout.addWidget(self._diag_progress_lbl)

        return self._diag_progress_container

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
        """連線到 DAQ 裝置，成功後啟用按鈕（監控預設關閉，不自動啟動）"""
        # 若已在監控中，先停止
        if self._is_monitoring:
            self._stop_monitoring()

        success, error_msg = self._daq.connect()

        if success:
            # 真實硬體或已是模擬模式 → 啟用按鈕，但不自動啟動監控
            mode = "模擬模式" if self._daq.is_simulation else "USB-4716"
            self._device_status_lbl.setText(f"● 已連線 ({mode})")
            self._device_status_lbl.setStyleSheet("color: #44FF44; font-size: 12px;")
            self._status_bar.showMessage(
                f"裝置已連線: {mode} | 監控預設關閉，按「監控：關」啟動即時觀察，或直接按「高取樣診斷」"
            )
            # 連線後啟用監控開關、開始檢測、高取樣診斷按鈕
            self._btn_monitor.setEnabled(True)
            self._btn_start.setEnabled(True)
            self._btn_diag.setEnabled(True)

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
                self._status_bar.showMessage("⚠ 模擬模式 | 監控預設關閉，按「監控：關」啟動即時觀察")
                print("[MainWindow] 使用者選擇切換至模擬模式")
                self._btn_monitor.setEnabled(True)
                self._btn_start.setEnabled(True)
                self._btn_diag.setEnabled(True)
            else:
                # 使用者拒絕 → 保持未連線狀態
                self._device_status_lbl.setText("● 連線失敗")
                self._device_status_lbl.setStyleSheet("color: #FF4444; font-size: 12px;")
                self._status_bar.showMessage("裝置連線失敗，請檢查 USB-4716 連接後重新連線")
                self._btn_monitor.setEnabled(False)
                self._btn_start.setEnabled(False)
                self._btn_diag.setEnabled(False)

    def _on_toggle_monitor(self):
        """監控開關按鈕：切換即時監控啟停"""
        if self._is_monitoring:
            self._stop_monitoring()
        else:
            self._start_monitoring()

    def _start_monitoring(self):
        """啟動監控模式：持續讀取 AI/DI，顯示即時波形（手動啟動）"""
        if self._is_monitoring:
            return
        self._is_monitoring = True
        self._ai_reader.start()
        self._di_reader.start()
        self._update_timer.start()
        # 更新監控按鈕狀態
        self._btn_monitor.setText("📡 監控：開")
        self._btn_monitor.setStyleSheet(BTN_MON_ON_STYLE)
        self._status_bar.showMessage(
            f"即時監控已啟動（{SAMPLING['ai_sample_rate']:,} Hz 標示）| 僅供初步觀察，診斷請用「高取樣診斷」"
        )
        print("[MainWindow] 監控模式已啟動（手動）")

    def _stop_monitoring(self):
        """停止監控模式"""
        self._is_monitoring = False
        self._update_timer.stop()
        self._ai_reader.stop()
        self._di_reader.stop()
        # 更新監控按鈕狀態
        self._btn_monitor.setText("📡 監控：關")
        self._btn_monitor.setStyleSheet(BTN_MON_OFF_STYLE)
        print("[MainWindow] 監控模式已停止")

    # ─── 診斷控制事件 ──────────────────────────────────────────────────────────

    def _on_start_diag(self):
        """使用者按「高取樣診斷」：暫停監控（若有），切換到診斷視圖，啟動掃描器"""
        if not self._daq.is_connected:
            QMessageBox.warning(self, "警告", "裝置未連線，請先連線 USB-4716")
            return
        if self._is_diagnosing:
            QMessageBox.warning(self, "警告", "診斷已在進行中")
            return
        if self._session.is_running:
            QMessageBox.warning(self, "警告", "檢測進行中，請先停止檢測再啟動診斷")
            return

        # 確認對話框
        ch_count = len(DIAGNOSTIC["channels"])
        total_s  = ch_count * DIAGNOSTIC["seconds_per_ch"] * DIAGNOSTIC["rounds"]
        reply = QMessageBox.question(
            self, "啟動高取樣率診斷",
            f"即將啟動高取樣率診斷：\n\n"
            f"  • {ch_count} 個通道，每通道 {DIAGNOSTIC['seconds_per_ch']} 秒\n"
            f"  • 取樣率：{DIAGNOSTIC['sample_rate']:,} Hz\n"
            f"  • 共 {DIAGNOSTIC['rounds']} 輪，預計 {total_s} 秒\n\n"
            f"診斷期間將暫停即時監控（若已開啟）。\n"
            f"完成後自動分析 PASS/FAIL，資料存成 npz 並寫入歷史記錄。\n\n"
            f"確定開始？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        if reply != QMessageBox.Yes:
            return

        # ── 1. 停止監控（若有開啟），釋放 InstantAI ──────────────────────────
        if self._is_monitoring:
            self._stop_monitoring()

        # ── 2. 進入診斷模式（建立 WaveformAiCtrl）────────────────────────────
        if not self._daq.enter_diag_mode():
            QMessageBox.critical(self, "錯誤", "無法進入診斷模式，請重新連線後再試")
            self._start_monitoring()
            return

        # ── 3. 在 DB 建立診斷場次記錄 ─────────────────────────────────────────
        try:
            self._diag_session_id = self._db.create_diagnostic_session(
                operator="",
                notes=f"高取樣診斷 {DIAGNOSTIC['sample_rate']}Hz × {DIAGNOSTIC['seconds_per_ch']}s × {DIAGNOSTIC['rounds']}輪"
            )
        except Exception as e:
            print(f"[MainWindow] 建立診斷場次失敗: {e}")
            self._diag_session_id = -1

        # ── 4. 切換到診斷視圖 ─────────────────────────────────────────────────
        self._content_stack.setCurrentIndex(1)   # 顯示 DiagnosticWidget
        self._diag_widget.reset_idle()

        # ── 5. 顯示診斷進度列 ─────────────────────────────────────────────────
        self._diag_progress_container.setVisible(True)
        self._diag_progress_bar.setValue(0)
        total_steps = len(DIAGNOSTIC["channels"]) * DIAGNOSTIC["rounds"]
        self._diag_progress_lbl.setText(f"0 / {total_steps}")
        self._diag_ch_lbl.setText("準備中...")
        self._diag_round_lbl.setText(f"第 1 / {DIAGNOSTIC['rounds']} 輪")
        self._diag_countdown_lbl.setText(f"⏱ {DIAGNOSTIC['seconds_per_ch']}.0s")

        # ── 6. 更新按鈕狀態 ───────────────────────────────────────────────────
        self._btn_diag.setEnabled(False)
        self._btn_diag_stop.setEnabled(True)
        self._btn_start.setEnabled(False)
        self._btn_early_stop.setEnabled(False)
        self._btn_monitor.setEnabled(False)   # 診斷中禁用監控開關

        # ── 7. 建立並啟動診斷掃描器 ───────────────────────────────────────────
        self._is_diagnosing = True
        self._diag_start_time = time.time()

        self._diag_scanner = DiagnosticScanner(self._daq)
        self._diag_scanner.set_chunk_callback(
            lambda ch_idx, round_idx, chunk, elapsed_s:
                self._diag_chunk_signal.emit(ch_idx, round_idx, chunk, elapsed_s)
        )
        self._diag_scanner.set_progress_callback(
            lambda ch_idx, round_idx, elapsed_s, remaining_s, ch_name:
                self._diag_progress_signal.emit(ch_idx, round_idx, elapsed_s, remaining_s, ch_name)
        )
        self._diag_scanner.set_done_callback(
            lambda result: self._diag_done_signal.emit(result)
        )
        self._diag_scanner.start()

        self._status_bar.showMessage(
            f"🔬 高取樣診斷進行中 | {DIAGNOSTIC['sample_rate']:,} Hz | "
            f"{len(DIAGNOSTIC['channels'])} CH × {DIAGNOSTIC['seconds_per_ch']}s × {DIAGNOSTIC['rounds']} 輪"
        )
        print("[MainWindow] 高取樣診斷已啟動")

    def _on_stop_diag(self):
        """使用者按「結束診斷」：提早停止掃描器"""
        if not self._is_diagnosing or self._diag_scanner is None:
            return
        reply = QMessageBox.question(
            self, "確認提早結束診斷",
            "確定要提早結束診斷？\n已採集的資料仍會儲存。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        self._diag_scanner.stop()
        self._btn_diag_stop.setEnabled(False)
        self._status_bar.showMessage("🔬 診斷提早結束，等待資料儲存...")

    def _on_diag_chunk(self, ch_idx: int, round_idx: int, chunk, elapsed_s: float):
        """
        診斷 chunk 資料回呼（主執行緒）
        將 chunk 資料推送給 DiagnosticWidget 即時繪製
        """
        try:
            import numpy as np
            chunk_arr = np.array(chunk, dtype=np.float32)
            self._diag_widget.append_chunk(chunk_arr)
        except Exception as e:
            print(f"[MainWindow] _on_diag_chunk 錯誤: {e}")

    def _on_diag_progress(
        self,
        ch_idx: int,
        round_idx: int,
        elapsed_s: float,
        remaining_s: float,
        ch_name: str
    ):
        """
        診斷進度回呼（主執行緒）
        更新進度列與 DiagnosticWidget 的進度顯示
        """
        try:
            ch_count    = len(DIAGNOSTIC["channels"])
            total_steps = ch_count * DIAGNOSTIC["rounds"]
            # 當前步驟 = 已完成輪次 × CH 數 + 當前 CH 索引
            current_step = round_idx * ch_count + ch_idx

            # 整體進度（含當前 CH 內部進度）
            ch_progress = elapsed_s / DIAGNOSTIC["seconds_per_ch"]
            overall_progress = (current_step + ch_progress) / total_steps
            self._diag_progress_bar.setValue(int(overall_progress * 1000))
            self._diag_progress_lbl.setText(f"{current_step + 1} / {total_steps}")

            # 進度列標籤
            self._diag_ch_lbl.setText(ch_name)
            self._diag_round_lbl.setText(f"第 {round_idx + 1} / {DIAGNOSTIC['rounds']} 輪")
            self._diag_countdown_lbl.setText(f"⏱ {remaining_s:.1f}s")

            # 若切換到新 CH，更新 DiagnosticWidget 通道設定
            ch_def = DIAGNOSTIC["channels"][ch_idx]
            if ch_idx != self._diag_widget._current_ch_idx or round_idx != getattr(self, '_last_diag_round', -1):
                self._last_diag_round = round_idx
                self._diag_widget.set_channel(
                    ch_idx=ch_idx,
                    ch_name=ch_name,
                    y_range=ch_def["y_range"],
                    vh_min=ch_def.get("vh_min"),
                    vl_max=ch_def.get("vl_max"),
                )

            # 更新 DiagnosticWidget 進度
            self._diag_widget.set_progress(
                round_idx=round_idx,
                elapsed_s=elapsed_s,
                remaining_s=remaining_s,
                total_rounds=DIAGNOSTIC["rounds"]
            )

        except Exception as e:
            print(f"[MainWindow] _on_diag_progress 錯誤: {e}")

    def _on_diag_done(self, result: dict):
        """
        診斷完成回呼（主執行緒）
        呼叫 DiagAnalyzer 分析高速資料 → 計算 PASS/FAIL → 寫 DB → 恢復監控
        """
        self._is_diagnosing = False
        duration_s = time.time() - self._diag_start_time

        npz_path    = result.get("npz_path")
        completed   = result.get("completed", False)
        rounds_done = result.get("rounds_done", 0)
        raw_results = result.get("raw_results", [])
        channels    = result.get("channels", [])
        sample_rate = result.get("sample_rate", DIAGNOSTIC["sample_rate"])

        # ── 1. 高速數據診斷分析（DiagAnalyzer）──────────────────────────────
        diag_analysis = None
        diag_pass     = None
        diag_ch_json  = ""
        try:
            if raw_results and channels:
                analyzer     = DiagAnalyzer()
                diag_analysis = analyzer.analyze_all(raw_results, channels, sample_rate)
                diag_pass    = diag_analysis.overall_pass
                # 序列化各通道結果為 JSON 字串（供 DB 儲存）
                import json
                ch_summary_simple = {
                    ch_name: {
                        "pass":     info["pass"],
                        "avg_freq": round(info["avg_freq"], 2),
                    }
                    for ch_name, info in diag_analysis.ch_summary.items()
                }
                diag_ch_json = json.dumps(ch_summary_simple, ensure_ascii=False)
                print(
                    f"[MainWindow] 診斷分析完成 | "
                    f"整體={'PASS' if diag_pass else 'FAIL'} | "
                    f"{diag_analysis.pass_count}/{diag_analysis.total_count} 通道×輪次 PASS"
                )
            else:
                print("[MainWindow] 無原始資料可分析（raw_results 為空）")
        except Exception as e:
            print(f"[MainWindow] DiagAnalyzer 分析失敗: {e}")

        # ── 2. 寫入 DB 診斷場次記錄（含 PASS/FAIL）──────────────────────────
        if self._diag_session_id > 0:
            try:
                self._db.close_diagnostic_session(
                    session_id=self._diag_session_id,
                    duration_s=duration_s,
                    npz_path=npz_path or "",
                    completed=completed,
                    rounds_done=rounds_done,
                    diag_pass=diag_pass,
                    diag_ch_results=diag_ch_json,
                )
            except Exception as e:
                print(f"[MainWindow] 寫入診斷 DB 失敗: {e}")

        # ── 3. 離開診斷模式（重建 InstantAiCtrl）─────────────────────────────
        self._daq.exit_diag_mode()

        # ── 4. 恢復監控視圖 ───────────────────────────────────────────────────
        self._content_stack.setCurrentIndex(0)   # 切回監控波形
        self._diag_progress_container.setVisible(False)
        self._diag_widget.clear()

        # ── 5. 恢復按鈕狀態（監控維持關閉，讓使用者自行決定是否開啟）────────
        self._btn_diag_stop.setEnabled(False)
        self._btn_early_stop.setEnabled(False)
        self._btn_monitor.setEnabled(True)
        self._btn_start.setEnabled(True)
        self._btn_diag.setEnabled(True)

        # ── 6. 顯示診斷結果摘要（含 PASS/FAIL 分析）─────────────────────────
        status = "✔ 完成" if completed else "⚠ 提早結束"
        npz_note = f"\n\n📁 資料已儲存：\n{npz_path}" if npz_path else "\n\n⚠ 資料儲存失敗"

        if diag_analysis is not None:
            overall_str = "✔ PASS" if diag_pass else "✘ FAIL"
            analysis_note = (
                f"\n\n─── 診斷分析結果 ───\n"
                f"{diag_analysis.summary_text}"
            )
        else:
            overall_str   = "— 未分析"
            analysis_note = "\n\n（無原始資料可分析）"

        QMessageBox.information(
            self, "診斷完成",
            f"高取樣率診斷{status}\n\n"
            f"已完成輪數：{rounds_done} / {DIAGNOSTIC['rounds']}\n"
            f"實際時長：{duration_s:.0f} 秒\n"
            f"取樣率：{DIAGNOSTIC['sample_rate']:,} Hz\n"
            f"診斷結果：{overall_str}"
            f"{analysis_note}"
            f"{npz_note}\n\n"
            f"可在「歷史記錄」中回看診斷波形。"
        )

        self._status_bar.showMessage(
            f"診斷{status} | {rounds_done}/{DIAGNOSTIC['rounds']} 輪 | "
            f"診斷={overall_str} | "
            f"{'npz 已儲存' if npz_path else '儲存失敗'} | 監控關閉"
        )
        print(f"[MainWindow] 診斷完成，監控維持關閉狀態")

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

        # 套用參數設定
        ENCODER_THRESHOLDS["ppr"] = info["ppr"]
        self._di_reader._ppr = info["ppr"]
        self._enc_analyzer.PPR = info["ppr"]

        HALL_THRESHOLDS["vh_min"] = info["hall_vh_min"]
        HALL_THRESHOLDS["vl_max"] = info["hall_vl_max"]
        self._hall_analyzer.VH_MIN = info["hall_vh_min"]
        self._hall_analyzer.VL_MAX = info["hall_vl_max"]

        ENCODER_THRESHOLDS["vh_min"] = info["enc_vh_min"]
        ENCODER_THRESHOLDS["vl_max"] = info["enc_vl_max"]
        self._enc_analyzer.VH_MIN = info["enc_vh_min"]
        self._enc_analyzer.VL_MAX = info["enc_vl_max"]

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

        # 啟動場次 & 開始錄製波形
        self._session.start(serial_no=serial_no, operator=operator)
        self._waveform_recorder.start()

        # 更新 UI 狀態
        self._btn_start.setEnabled(False)
        self._btn_early_stop.setEnabled(True)
        self._progress_container.setVisible(True)
        self._live_stats_group.setVisible(True)

        serial_display = f"序號: {serial_no}" if serial_no else "序號: (未輸入)"
        self._session_info_lbl.setText("🔵 檢測中")
        self._serial_display_lbl.setText(serial_display)

        # 立即更新倒數顯示（不等第一次 tick，避免顯示舊的初始值）
        total_min = int(duration_s // 60)
        total_sec = int(duration_s) % 60
        self._countdown_lbl.setText(f"{total_min:02d}:{total_sec:02d}")
        self._progress_bar.setValue(0)

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
        """場次計時回呼（每秒觸發，來自背景執行緒）
        倒數 UI 已改由主執行緒 QTimer (_update_display) 直接更新，此回呼保留供未來擴充用。
        """
        pass  # 不再透過 singleShot 更新 UI，避免跨執行緒排程延遲問題

    def _on_session_done(self, stats):
        """場次完成回呼（時間到後由背景執行緒觸發）
        透過 pyqtSignal 確保 _save_session_result 在主執行緒執行，
        避免 QTimer.singleShot 在非主執行緒呼叫時可能失效的問題。
        """
        self._session_done_signal.emit(stats)

    def _save_session_result(self, stats):
        """儲存場次結果至 DB 並更新 UI"""
        # ── 停止錄製，FAIL 時儲存波形 ─────────────────────────────────────────
        self._waveform_recorder.stop()
        waveform_path = self._waveform_recorder.save_if_fail(
            session_id=self._current_session_id,
            overall_pass=stats.overall_pass,
        )

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
            # 若有波形檔，更新路徑至 DB
            if waveform_path:
                self._db.update_waveform_path(
                    self._current_session_id, waveform_path
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
        wf_note = (
            f"\n\n⚠ FAIL：波形數據已儲存\n可在歷史記錄中回看波形"
            if waveform_path else ""
        )
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
            f"{wf_note}"
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

    # ─── 顯示更新 ──────────────────────────────────────────────────────────────

    def _update_display(self):
        """定時更新 GUI 顯示（由 QTimer 觸發，監控模式持續運行）"""
        try:
            self._update_waveforms()
            self._update_analysis()
            # 若場次正在執行，在主執行緒直接更新倒數計時與即時統計
            # 不依賴背景執行緒的 singleShot，避免跨執行緒排程延遲
            if self._session.is_running:
                self._update_session_ui()
        except Exception as e:
            print(f"[MainWindow] 顯示更新錯誤: {e}")

    def _update_session_ui(self):
        """在主執行緒更新倒數計時與即時統計（由 _update_display 每 50ms 呼叫）"""
        elapsed_s   = self._session.elapsed_s
        remaining_s = self._session.remaining_s

        # 倒數計時
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

    def _update_waveforms(self):
        """更新波形顯示（即時監控開啟時才有資料）"""
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
        """
        更新即時顯示（監控模式）
        注意：即時監控不做 PASS/FAIL 判斷，僅顯示即時電壓與 DI 狀態供初步觀察。
        PASS/FAIL 診斷改由高速取樣（DiagnosticScanner + DiagAnalyzer）完成。
        """
        # ── 即時電壓顯示（不做 PASS/FAIL 判斷）─────────────────────────────
        hall_voltages = self._ai_reader.get_hall_voltages()
        enc_voltages  = self._ai_reader.get_encoder_voltages()
        enc_state     = self._di_reader.get_encoder_state()

        # 更新 ResultPanel 即時電壓顯示（不傳入 PASS/FAIL 結果）
        self._result_panel.update_live_voltages(
            hall_voltages=hall_voltages,
            enc_voltages=enc_voltages,
            enc_state=enc_state,
        )

        # ── 若場次正在執行，錄製波形快照（供 FAIL 時儲存）──────────────────
        if self._session.is_running:
            self._waveform_recorder.append(
                hall_u=self._ai_reader.get_buffer(HALL_THRESHOLDS["channels"]["U"]),
                hall_v=self._ai_reader.get_buffer(HALL_THRESHOLDS["channels"]["V"]),
                hall_w=self._ai_reader.get_buffer(HALL_THRESHOLDS["channels"]["W"]),
                enc_a=self._ai_reader.get_buffer(ENCODER_THRESHOLDS["channels"]["A"]),
                enc_b=self._ai_reader.get_buffer(ENCODER_THRESHOLDS["channels"]["B"]),
            )

    # ─── 視窗關閉 ──────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        """視窗關閉時釋放資源"""
        # 若診斷正在執行，先強制停止
        if self._is_diagnosing and self._diag_scanner is not None:
            self._diag_scanner.stop()
            self._is_diagnosing = False
            try:
                self._daq.exit_diag_mode()
            except Exception:
                pass

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

"""
主視窗模組（重構版）
整合波形顯示、測試結果面板與控制按鈕
流程：連線後監控預設關閉 → 手動按「監控開關」啟動即時觀察（10 kHz 標示）
      → 操作員按「參數設置」設定量測參數（PPR、閾值）並輸入序號/操作員
      → 按「高取樣診斷」開始高速採樣（200kHz 高速採樣 5CH × 2輪）
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

from config.thresholds import (
    SAMPLING, HALL_THRESHOLDS, ENCODER_THRESHOLDS, DATABASE, DIAGNOSTIC,
    refresh_channel_map,
)
from config.channel_config import CHANNEL_CONFIG
from daq.daq_controller import DAQController
from daq.ai_reader import AIReader
from daq.di_reader import DIReader
from logic.hall_analyzer import HallAnalyzer
from logic.encoder_analyzer import EncoderAnalyzer
from logic.diagnostic_scanner import DiagnosticScanner
from logic.diag_analyzer import DiagAnalyzer
from ui.waveform_widget import WaveformWidget
from ui.diagnostic_widget import DiagnosticWidget
from ui.result_panel import ResultPanel
from ui.session_dialog import SessionStartDialog
from ui.channel_config_dialog import ChannelConfigDialog
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
        DIAGNOSING → 操作員按「高取樣診斷」，高速採樣 5CH × 2輪
    """

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

        # ── 參數設置暫存（由「參數設置」對話框帶入，供診斷場次使用）──────────
        self._param_serial_no: str = ""
        self._param_operator:  str = ""

        # ── 診斷掃描器 ────────────────────────────────────────────────────────
        self._diag_scanner: DiagnosticScanner = None
        self._diag_session_id: int = -1
        self._diag_start_time: float = 0.0
        self._is_diagnosing: bool = False

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

        # 參數設置（連線後可用，不需監控開啟）
        self._btn_start = QPushButton("⚙ 參數設置")
        self._btn_start.setStyleSheet(BTN_START_STYLE)
        self._btn_start.setEnabled(False)
        self._btn_start.setToolTip("設定量測參數（PPR、Hall/Encoder 閾值）及馬達序號/操作員")
        self._btn_start.clicked.connect(self._on_open_param_settings)
        layout.addWidget(self._btn_start)

        # 硬體通道設定（連線後可用，調整 AI/DI 通道對應）
        self._btn_channel = QPushButton("🔌 硬體通道")
        self._btn_channel.setToolTip(
            "設定各訊號（Hall U/V/W、Encoder A/B）對應的硬體 AI / DI 通道，\n"
            "可依實際接線自由調整，不必固定 AI0~4 / DI0~4"
        )
        self._btn_channel.clicked.connect(self._on_open_channel_settings)
        layout.addWidget(self._btn_channel)

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

        # 確認對話框
        ch_count = len(DIAGNOSTIC["channels"])
        total_s  = ch_count * DIAGNOSTIC["seconds_per_ch"] * DIAGNOSTIC["rounds"]
        serial_hint = f"序號：{self._param_serial_no}" if self._param_serial_no else "（序號未設定，可先按「參數設置」輸入）"
        reply = QMessageBox.question(
            self, "啟動高取樣率診斷",
            f"即將啟動高取樣率診斷：\n\n"
            f"  • {ch_count} 個通道，每通道 {DIAGNOSTIC['seconds_per_ch']} 秒\n"
            f"  • 取樣率：{DIAGNOSTIC['sample_rate']:,} Hz\n"
            f"  • 共 {DIAGNOSTIC['rounds']} 輪，預計 {total_s} 秒\n"
            f"  • {serial_hint}\n\n"
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

        # ── 3. 在 DB 建立診斷場次記錄（帶入參數設置的序號/操作員）────────────
        try:
            self._diag_session_id = self._db.create_diagnostic_session(
                operator=self._param_operator,
                serial_no=self._param_serial_no,
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
        diag_analysis   = None
        diag_pass       = None
        diag_ch_json    = ""
        diag_summary    = ""
        try:
            if raw_results and channels:
                analyzer      = DiagAnalyzer()
                diag_analysis = analyzer.analyze_all(raw_results, channels, sample_rate)
                diag_pass     = diag_analysis.overall_pass
                diag_summary  = diag_analysis.summary_text   # 完整摘要（含比值交叉驗證、fail 原因）
                # 序列化各通道結果為 JSON 字串（供 DB 儲存，保留舊格式相容）
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

        # ── 2. 寫入 DB 診斷場次記錄（含 PASS/FAIL 與完整摘要）──────────────
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
                    diag_summary=diag_summary,
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
        self._btn_monitor.setEnabled(True)
        self._btn_start.setEnabled(True)
        self._btn_diag.setEnabled(True)

        # ── 6. 顯示診斷結果摘要（含 PASS/FAIL 分析，可捲動對話框）────────────
        status = "✔ 完成" if completed else "⚠ 提早結束"
        npz_note = f"\n📁 資料已儲存：\n{npz_path}" if npz_path else "\n⚠ 資料儲存失敗"

        if diag_analysis is not None:
            overall_str  = "✔ PASS" if diag_pass else "✘ FAIL"
            analysis_note = (
                f"\n─── 診斷分析結果 ───\n"
                f"{diag_analysis.summary_text}"
            )
        else:
            overall_str   = "— 未分析"
            analysis_note = "\n（無原始資料可分析）"

        full_text = (
            f"高取樣率診斷{status}\n\n"
            f"已完成輪數：{rounds_done} / {DIAGNOSTIC['rounds']}\n"
            f"實際時長：{duration_s:.0f} 秒\n"
            f"取樣率：{DIAGNOSTIC['sample_rate']:,} Hz\n"
            f"診斷結果：{overall_str}"
            f"{analysis_note}"
            f"{npz_note}\n\n"
            f"可在「歷史記錄」中回看診斷波形。"
        )
        self._show_diag_result_dialog("診斷完成", full_text)

        self._status_bar.showMessage(
            f"診斷{status} | {rounds_done}/{DIAGNOSTIC['rounds']} 輪 | "
            f"診斷={overall_str} | "
            f"{'npz 已儲存' if npz_path else '儲存失敗'} | 監控關閉"
        )
        print(f"[MainWindow] 診斷完成，監控維持關閉狀態")

    # ─── 診斷結果可捲動對話框 ──────────────────────────────────────────────────

    def _show_diag_result_dialog(self, title: str, text: str):
        """
        顯示可捲動的診斷結果對話框。

        診斷報告（含比值交叉驗證）文字較長，使用 QDialog + QTextEdit
        取代 QMessageBox，讓使用者可以上下捲動閱讀完整報告。

        Args:
            title: 對話框標題
            text:  報告全文（純文字）
        """
        from PyQt5.QtWidgets import (
            QDialog, QVBoxLayout, QTextEdit, QDialogButtonBox
        )
        from PyQt5.QtGui import QFont

        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.setMinimumSize(560, 480)
        dlg.resize(620, 560)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # 可捲動文字區域（唯讀）
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setPlainText(text)
        text_edit.setFont(QFont("Consolas", 10))
        text_edit.setStyleSheet(
            "QTextEdit {"
            "  background-color: #1E1E1E;"
            "  color: #CCCCCC;"
            "  border: 1px solid #444444;"
            "  border-radius: 4px;"
            "}"
            "QScrollBar:vertical {"
            "  background: #2A2A2A;"
            "  width: 12px;"
            "}"
            "QScrollBar::handle:vertical {"
            "  background: #555555;"
            "  border-radius: 6px;"
            "}"
        )
        layout.addWidget(text_edit)

        # 確認按鈕
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok)
        btn_box.accepted.connect(dlg.accept)
        btn_box.setStyleSheet(
            "QPushButton {"
            "  background-color: #2A2A2A;"
            "  color: #CCCCCC;"
            "  border: 1px solid #555555;"
            "  border-radius: 4px;"
            "  padding: 6px 20px;"
            "}"
            "QPushButton:hover { background-color: #3A3A3A; }"
            "QPushButton:pressed { background-color: #1A1A1A; }"
        )
        layout.addWidget(btn_box)

        # 捲動至頂部
        text_edit.moveCursor(text_edit.textCursor().Start)

        dlg.exec_()

    # ─── 參數設置事件 ──────────────────────────────────────────────────────────

    def _on_open_param_settings(self):
        """操作員按「參數設置」：開啟對話框設定量測參數並暫存序號/操作員"""
        dlg = SessionStartDialog(parent=self)
        if dlg.exec_() != SessionStartDialog.Accepted:
            return

        info = dlg.get_session_info()

        # 暫存序號/操作員（供下次診斷場次使用）
        self._param_serial_no = info["serial_no"]
        self._param_operator  = info["operator"]

        # 套用量測參數設定

        # ── Hall 規格 ─────────────────────────────────────────────────────────
        HALL_THRESHOLDS["hall_pulses_per_rev"] = info["hall_pulses_per_rev"]
        HALL_THRESHOLDS["vh_min"] = info["hall_vh_min"]
        HALL_THRESHOLDS["vl_max"] = info["hall_vl_max"]
        self._hall_analyzer.VH_MIN = info["hall_vh_min"]
        self._hall_analyzer.VL_MAX = info["hall_vl_max"]

        # ── Encoder 規格 ──────────────────────────────────────────────────────
        ENCODER_THRESHOLDS["ppr"]             = info["ppr"]
        ENCODER_THRESHOLDS["resolution_bits"] = info["resolution_bits"]
        ENCODER_THRESHOLDS["vh_min"]          = info["enc_vh_min"]
        ENCODER_THRESHOLDS["vl_max"]          = info["enc_vl_max"]
        self._di_reader._ppr       = info["ppr"]
        self._enc_analyzer.PPR     = info["ppr"]
        self._enc_analyzer.VH_MIN  = info["enc_vh_min"]
        self._enc_analyzer.VL_MAX  = info["enc_vl_max"]

        # ── 比值交叉驗證容差 ──────────────────────────────────────────────────
        DIAGNOSTIC["analysis"]["ratio_tolerance"] = info["ratio_tolerance"]

        # 計算理論比值（供狀態列顯示）
        hall_ppr = info["hall_pulses_per_rev"]
        enc_ppr  = info["ppr"]
        theory_ratio = enc_ppr / hall_ppr if hall_ppr > 0 else 0.0

        serial_display = f"序號: {self._param_serial_no}" if self._param_serial_no else "序號: (未輸入)"
        self._status_bar.showMessage(
            f"參數已套用 | {serial_display} | "
            f"Hall {hall_ppr}週期/轉 | "
            f"Enc PPR={enc_ppr}({info['resolution_bits']}bits) | "
            f"理論比值={theory_ratio:.3f} ±{info['ratio_tolerance']*100:.0f}% | "
            f"Hall VH≥{info['hall_vh_min']:.2f}V VL≤{info['hall_vl_max']:.2f}V | "
            f"Enc VH≥{info['enc_vh_min']:.2f}V VL≤{info['enc_vl_max']:.2f}V"
        )
        print(
            f"[MainWindow] 參數設置已套用 | {serial_display} | "
            f"Hall {hall_ppr}週期/轉 | Enc PPR={enc_ppr}({info['resolution_bits']}bits) | "
            f"理論比值={theory_ratio:.3f} ±{info['ratio_tolerance']*100:.0f}%"
        )

    def _on_open_channel_settings(self):
        """
        操作員按「硬體通道」：開啟對話框調整 AI/DI 通道對應並即時套用

        流程：
          1. 診斷中禁止調整（避免影響進行中的採樣）
          2. 開啟 ChannelConfigDialog 讓使用者設定
          3. 存回 channel_map.json → refresh_channel_map() 更新 thresholds
          4. 重建 AI/DI 讀取器通道結構（若監控中會自動重啟套用）
        """
        if self._is_diagnosing:
            QMessageBox.warning(self, "警告", "診斷進行中，無法變更硬體通道設定")
            return

        dlg = ChannelConfigDialog(parent=self)
        if dlg.exec_() != ChannelConfigDialog.Accepted:
            return

        new_map = dlg.get_channel_map()

        # ── 1. 存檔並更新中央設定 ─────────────────────────────────────────────
        CHANNEL_CONFIG.set_map(new_map, save=True)

        # ── 2. 更新 thresholds 內的通道字典（就地更新，維持既有參照）─────────
        refresh_channel_map()

        # ── 3. 重建讀取器通道結構（refresh 會自動處理啟停）──────────────────
        try:
            self._ai_reader.refresh_channels()
            self._di_reader.refresh_channels()
        except Exception as e:
            print(f"[MainWindow] 套用通道設定時發生錯誤: {e}")
            QMessageBox.warning(self, "警告", f"套用通道設定時發生錯誤：\n{e}")
            return

        # ── 4. 更新狀態列顯示 ─────────────────────────────────────────────────
        hall_ai = CHANNEL_CONFIG.hall_ai_channels()
        enc_ai  = CHANNEL_CONFIG.encoder_ai_channels()
        hall_di = CHANNEL_CONFIG.hall_di_channels()
        enc_di  = CHANNEL_CONFIG.encoder_di_channels()
        self._status_bar.showMessage(
            f"硬體通道已更新 | "
            f"Hall AI={list(hall_ai.values())} DI={list(hall_di.values())} | "
            f"Enc AI={list(enc_ai.values())} DI={list(enc_di.values())}"
        )
        QMessageBox.information(
            self, "成功",
            "硬體通道設定已套用並儲存至 channel_map.json。\n\n"
            f"Hall  AI: U={hall_ai['U']} V={hall_ai['V']} W={hall_ai['W']}  "
            f"DI: U={hall_di['U']} V={hall_di['V']} W={hall_di['W']}\n"
            f"Encoder AI: A={enc_ai['A']} B={enc_ai['B']}  "
            f"DI: A={enc_di['A']} B={enc_di['B']}"
        )
        print(
            f"[MainWindow] 硬體通道已更新 | "
            f"Hall AI={hall_ai} DI={hall_di} | Enc AI={enc_ai} DI={enc_di}"
        )

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
        except Exception as e:
            print(f"[MainWindow] 顯示更新錯誤: {e}")

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

        self._stop_monitoring()
        self._daq.disconnect()
        event.accept()

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
from collections import deque
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
from config.motor_profiles import MOTOR_PROFILES
from daq.daq_controller import DAQController
from daq.ai_reader import AIReader
from daq.di_reader import DIReader
from logic.hall_analyzer import HallAnalyzer, HallSequenceDetector
from logic.encoder_analyzer import EncoderAnalyzer
from logic.diagnostic_scanner import DiagnosticScanner
from logic.diag_analyzer import DiagAnalyzer
from ui.waveform_widget import WaveformWidget
from ui.diagnostic_widget import DiagnosticWidget
from ui.result_panel import ResultPanel
from ui.session_dialog import SessionStartDialog
from ui.object_info_dialog import ObjectInfoDialog
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
        # 即時監控相序偵測器（依 AI 類比電壓判斷；DI 已於監控模式移除）
        self._hall_seq_detector_ai = HallSequenceDetector()
        # 持久化狀態序列歷史（跨幀累積，供 debug 顯示最近 N 個有效 Hall 狀態編碼）
        # 每次僅在偵測到「新的」狀態轉換時 append，低速無轉換時仍保留舊序列不清空
        self._hall_state_history: deque = deque(maxlen=16)
        self._hall_last_seq_state: int = -1   # 上次累積的最後狀態（跨幀去重用）
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

        # 啟動時載入上次使用的量測參數 profile 並套用（下次開啟不需重設）
        self._load_active_profile()

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
        monitor_layout.setSpacing(4)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(4)

        # ── 左側欄：控制列（監控開關 + 清除）＋ 波形圖 ──────────────────────
        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        # 波形監測控制列（置於 WaveformWidget 正上方）
        left_layout.addWidget(self._build_monitor_ctrl_bar())

        self._waveform_widget = WaveformWidget()
        left_layout.addWidget(self._waveform_widget)

        splitter.addWidget(left_container)

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

    def _build_monitor_ctrl_bar(self) -> QWidget:
        """
        建立即時波形監測區上方的控制列。

        包含：
          - 📡 監控開關（由頂部工具列移至此，靠近波形）
          - 🗑 清除波形（清空目前顯示的即時波形與緩衝）
        """
        bar = QWidget()
        bar.setFixedHeight(40)
        bar.setStyleSheet("background-color: #252525; border-radius: 4px;")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        section_lbl = QLabel("即時波形監測")
        section_lbl.setStyleSheet("color: #4AABFF; font-weight: bold; font-size: 12px;")
        layout.addWidget(section_lbl)

        layout.addStretch()

        # 監控開關（預設關閉，手動啟停即時監控）
        self._btn_monitor = QPushButton("📡 監控：關")
        self._btn_monitor.setStyleSheet(BTN_MON_OFF_STYLE)
        self._btn_monitor.setEnabled(False)   # 連線後才啟用
        self._btn_monitor.setToolTip(
            f"即時監控（WaveformAI 多通道連續串流，{SAMPLING['ai_sample_rate']:,} Hz/通道）\n"
            "預設關閉，僅供初步觀察，不做 PASS/FAIL 判斷"
        )
        self._btn_monitor.clicked.connect(self._on_toggle_monitor)
        layout.addWidget(self._btn_monitor)

        # 清除波形（清空目前顯示的即時波形與緩衝）
        self._btn_clear_wave = QPushButton("🗑 清除")
        self._btn_clear_wave.setToolTip("清除目前顯示的即時波形與資料緩衝（不影響監控啟停）")
        self._btn_clear_wave.clicked.connect(self._on_clear_waveform)
        layout.addWidget(self._btn_clear_wave)

        return bar

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
        # 注意：監控開關（📡 監控）已移至波形監測區上方的控制列（見 _build_monitor_page）
        # 注意：測試物件（馬達序號/操作員）已移至「高取樣診斷」按下後跳出的輸入視窗

        # 參數設置（連線後可用，不需監控開啟）
        self._btn_start = QPushButton("⚙ 參數設置")
        self._btn_start.setStyleSheet(BTN_START_STYLE)
        self._btn_start.setEnabled(False)
        self._btn_start.setToolTip("設定量測參數（PPR、Hall/Encoder 閾值），可存成馬達型號 profile 切換套用")
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

        # self._btn_export = QPushButton("💾 匯出報表")
        # self._btn_export.setObjectName("btn_export")
        # self._btn_export.clicked.connect(self._on_export)
        # layout.addWidget(self._btn_export)

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
            # 連線後啟用監控開關、參數設置、高取樣診斷按鈕
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
        """啟動監控模式：持續讀取 Hall AI 三通道，顯示即時波形（手動啟動）"""
        if self._is_monitoring:
            return
        # 重置狀態序列 debug 歷史（新一次監控從乾淨序列開始累積）
        self._hall_state_history.clear()
        self._hall_last_seq_state = -1
        # 啟動讀取器（若硬體資源尚未就緒可能拋例外，需正確還原狀態）
        try:
            self._ai_reader.start()
        except Exception as e:
            # 啟動失敗 → 還原狀態，避免按鈕顯示「開」但實際無資料
            print(f"[MainWindow] 啟動監控失敗: {e}")
            try:
                self._ai_reader.stop()
            except Exception:
                pass
            self._is_monitoring = False
            self._btn_monitor.setText("📡 監控：關")
            self._btn_monitor.setStyleSheet(BTN_MON_OFF_STYLE)
            self._status_bar.showMessage(f"⚠ 啟動監控失敗：{e}（請重新連線後再試）")
            QMessageBox.warning(
                self, "監控啟動失敗",
                f"無法啟動即時監控：\n{e}\n\n"
                f"若剛結束高取樣診斷，請稍候再試或按「重新連線」。"
            )
            return

        self._is_monitoring = True
        self._update_timer.start()
        # 更新監控按鈕狀態
        self._btn_monitor.setText("📡 監控：開")
        self._btn_monitor.setStyleSheet(BTN_MON_ON_STYLE)
        self._status_bar.showMessage(
            f"即時監控已啟動（WaveformAI 連續串流 {SAMPLING['ai_sample_rate']:,} Hz/通道）"
            f"| 僅供初步觀察，診斷請用「高取樣診斷」"
        )
        print("[MainWindow] 監控模式已啟動（手動）")

    def _stop_monitoring(self):
        """停止監控模式"""
        self._is_monitoring = False
        self._update_timer.stop()
        self._ai_reader.stop()
        # 更新監控按鈕狀態
        self._btn_monitor.setText("📡 監控：關")
        self._btn_monitor.setStyleSheet(BTN_MON_OFF_STYLE)
        print("[MainWindow] 監控模式已停止")

    # ─── 診斷控制事件 ──────────────────────────────────────────────────────────

    def _on_start_diag(self):
        """使用者按「高取樣診斷」：先輸入測試物件資訊，暫停監控（若有），切換到診斷視圖，啟動掃描器"""
        if not self._daq.is_connected:
            QMessageBox.warning(self, "警告", "裝置未連線，請先連線 USB-4716")
            return
        if self._is_diagnosing:
            QMessageBox.warning(self, "警告", "診斷已在進行中")
            return

        # ── 先跳出「測試物件資訊」輸入視窗（取代原確認對話框）────────────────
        # 使用者輸入馬達序號/操作員後按確定即立即開始診斷；取消則中止。
        obj_dlg = ObjectInfoDialog(
            parent=self,
            serial_no=self._param_serial_no,
            operator=self._param_operator,
        )
        if obj_dlg.exec_() != ObjectInfoDialog.Accepted:
            return

        obj_info = obj_dlg.get_object_info()
        self._param_serial_no = obj_info["serial_no"]
        self._param_operator  = obj_info["operator"]

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

    def _on_clear_waveform(self):
        """清除即時波形顯示與讀值緩衝（不影響監控啟停狀態）"""
        try:
            self._waveform_widget.clear_all()
        except Exception as e:
            print(f"[MainWindow] 清除波形顯示失敗: {e}")
        try:
            self._ai_reader.clear_buffers()
        except Exception as e:
            print(f"[MainWindow] 清除 AI 緩衝失敗: {e}")
        # 一併清除狀態序列 debug 歷史（避免顯示已清除波形前的舊序列）
        self._hall_state_history.clear()
        self._hall_last_seq_state = -1
        self._status_bar.showMessage("🗑 即時波形與緩衝已清除")
        print("[MainWindow] 即時波形與緩衝已清除")

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
        self._btn_monitor.setEnabled(True)
        self._btn_start.setEnabled(True)
        self._btn_diag.setEnabled(True)

        # ── 6. 顯示診斷結果（僅 PASS / FAIL，詳細文字與波型請至歷史記錄查閱）─
        status = "✔ 完成" if completed else "⚠ 提早結束"

        if diag_analysis is not None:
            overall_str = "PASS" if diag_pass else "FAIL"
        else:
            overall_str = "— 未分析"

        self._show_diag_pass_fail_dialog(diag_pass, diag_analysis is not None)

        self._status_bar.showMessage(
            f"診斷{status} | {rounds_done}/{DIAGNOSTIC['rounds']} 輪 | "
            f"診斷={overall_str} | "
            f"{'npz 已儲存' if npz_path else '儲存失敗'} | 監控關閉"
        )
        print(f"[MainWindow] 診斷完成，監控維持關閉狀態")

    # ─── 診斷結果 PASS / FAIL 對話框 ───────────────────────────────────────────

    def _show_diag_pass_fail_dialog(self, diag_pass, analyzed: bool):
        """
        顯示診斷結果對話框（僅 PASS / FAIL）。

        依需求，診斷完成後只顯示大字的 PASS 或 FAIL 結果，
        詳細分析文字與波型請至「歷史記錄」查閱。

        Args:
            diag_pass: 是否 PASS（True/False；None 代表未分析）
            analyzed:  是否有進行分析（無原始資料時為 False）
        """
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QDialogButtonBox
        from PyQt5.QtGui import QFont

        dlg = QDialog(self)
        dlg.setWindowTitle("診斷完成")
        dlg.setMinimumSize(320, 220)
        dlg.setStyleSheet("QDialog { background-color: #1E1E1E; }")

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(16)

        if not analyzed or diag_pass is None:
            result_text  = "— 未分析"
            result_color = "#AAAAAA"
        elif diag_pass:
            result_text  = "PASS"
            result_color = "#44DD44"
        else:
            result_text  = "FAIL"
            result_color = "#FF4444"

        result_lbl = QLabel(result_text)
        result_lbl.setAlignment(Qt.AlignCenter)
        result_lbl.setFont(QFont("Arial", 48, QFont.Bold))
        result_lbl.setStyleSheet(f"color: {result_color};")
        layout.addWidget(result_lbl)

        hint_lbl = QLabel("詳細分析文字與波型請至「歷史記錄」查閱")
        hint_lbl.setAlignment(Qt.AlignCenter)
        hint_lbl.setStyleSheet("color: #888888; font-size: 12px;")
        hint_lbl.setWordWrap(True)
        layout.addWidget(hint_lbl)

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok)
        btn_box.accepted.connect(dlg.accept)
        btn_box.setStyleSheet(
            "QPushButton {"
            "  background-color: #2A2A2A;"
            "  color: #CCCCCC;"
            "  border: 1px solid #555555;"
            "  border-radius: 4px;"
            "  padding: 6px 24px;"
            "}"
            "QPushButton:hover { background-color: #3A3A3A; }"
            "QPushButton:pressed { background-color: #1A1A1A; }"
        )
        layout.addWidget(btn_box)

        dlg.exec_()

    # ─── 參數設置事件 ──────────────────────────────────────────────────────────

    def _apply_measurement_params(self, info: dict, announce: bool = True):
        """
        將量測參數套用至 thresholds 字典與各 analyzer / reader。

        供「參數設置」對話框套用與程式啟動載入 active profile 共用。

        Args:
            info:     量測參數字典（欄位同 MotorProfileManager 的 profile）
            announce: 是否更新狀態列並輸出 log（啟動時可設 False 靜默套用）
        """
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

        if not announce:
            return

        # 計算理論比值（供狀態列顯示）
        hall_ppr = info["hall_pulses_per_rev"]
        enc_ppr  = info["ppr"]
        theory_ratio = enc_ppr / hall_ppr if hall_ppr > 0 else 0.0

        profile_name = info.get("profile_name", "")
        profile_display = f"profile: {profile_name}" if profile_name else "profile: —"
        self._status_bar.showMessage(
            f"參數已套用 | {profile_display} | "
            f"Hall {hall_ppr}週期/轉 | "
            f"Enc PPR={enc_ppr}({info['resolution_bits']}bits) | "
            f"理論比值={theory_ratio:.3f} ±{info['ratio_tolerance']*100:.0f}% | "
            f"Hall VH≥{info['hall_vh_min']:.2f}V VL≤{info['hall_vl_max']:.2f}V | "
            f"Enc VH≥{info['enc_vh_min']:.2f}V VL≤{info['enc_vl_max']:.2f}V"
        )
        print(
            f"[MainWindow] 參數設置已套用 | {profile_display} | "
            f"Hall {hall_ppr}週期/轉 | Enc PPR={enc_ppr}({info['resolution_bits']}bits) | "
            f"理論比值={theory_ratio:.3f} ±{info['ratio_tolerance']*100:.0f}%"
        )

    def _load_active_profile(self):
        """程式啟動時載入 active profile 並靜默套用（不覆寫狀態列訊息）"""
        try:
            params = MOTOR_PROFILES.get_active_profile()
            params["profile_name"] = MOTOR_PROFILES.get_active_name()
            self._apply_measurement_params(params, announce=False)
            print(
                f"[MainWindow] 已載入 active profile: {params['profile_name']} | "
                f"Hall {params['hall_pulses_per_rev']}週期/轉 | "
                f"Enc PPR={params['ppr']}({params['resolution_bits']}bits)"
            )
        except Exception as e:
            print(f"[MainWindow] 載入 active profile 失敗（使用預設值）: {e}")

    def _on_open_param_settings(self):
        """操作員按「參數設置」：開啟對話框設定量測參數（可切換/儲存馬達型號 profile）"""
        dlg = SessionStartDialog(parent=self)
        if dlg.exec_() != SessionStartDialog.Accepted:
            return

        info = dlg.get_session_info()
        self._apply_measurement_params(info, announce=True)

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
        # Hall AI 三通道波形（50 kHz/通道 連續串流）
        u_buf = self._ai_reader.get_buffer(HALL_THRESHOLDS["channels"]["U"])
        v_buf = self._ai_reader.get_buffer(HALL_THRESHOLDS["channels"]["V"])
        w_buf = self._ai_reader.get_buffer(HALL_THRESHOLDS["channels"]["W"])
        self._waveform_widget.update_hall_waveform(u_buf, v_buf, w_buf)

    def _update_analysis(self):
        """
        更新即時顯示（監控模式）
        注意：即時監控不做 PASS/FAIL 判斷，僅顯示即時 Hall 電壓與由 AI 判定的
        H/L/X 準位供初步觀察。PASS/FAIL 診斷改由高速取樣
        （DiagnosticScanner + DiagAnalyzer）完成。

        相序判斷改良（修正高速/極低速誤判 Error）：
          舊做法每 50ms 只取一個瞬時快照喂給偵測器，等於用 20Hz 稀疏取樣去
          追蹤最高可達數百 Hz 的 Hall 電氣週期，狀態會大幅跳躍造成非法轉換
          （Error），且高速時看似「停住」。
          新做法改為每次從波形緩衝區取最近一段真實時序樣本（RECENT_N 點，
          50kHz 下約 20ms），以中點閾值向量化編碼為 UVW 狀態，找出實際發生的
          狀態轉換點後依序喂給偵測器，能正確反映真實相序。

        狀態序列 debug 顯示（跨幀持久累積）：
          RECENT_N 窗口（20ms）小於 GUI 更新間隔（50ms），兩幀資料不重疊，
          低速時單一窗口內可能完全沒有狀態轉換。若每幀重算局部序列，畫面會
          頻繁被清空（顯示 "--------"）而無法觀看完整序列。
          因此改用持久化 deque（self._hall_state_history）跨幀累積，只在偵測到
          「與上次累積的最後狀態不同」的新狀態時才 append（跨幀去重），
          低速或無轉換時序列保持不變，畫面不再被清空。
        """
        import numpy as np

        # ── 即時電壓顯示（不做 PASS/FAIL 判斷）─────────────────────────────
        hall_voltages = self._ai_reader.get_hall_voltages()

        # 取三相 Hall 波形緩衝區（真實時序樣本）
        u_buf = self._ai_reader.get_buffer(HALL_THRESHOLDS["channels"]["U"])
        v_buf = self._ai_reader.get_buffer(HALL_THRESHOLDS["channels"]["V"])
        w_buf = self._ai_reader.get_buffer(HALL_THRESHOLDS["channels"]["W"])

        RECENT_N = 1000          # 相序判斷取樣點數（50kHz 下約 20ms）
        DISP_N = 50              # H/L/X 顯示電壓平均點數（去抖動）
        SEQ_DISPLAY_N = 8        # debug 顯示最近幾個有效狀態編碼

        n = min(RECENT_N, len(u_buf), len(v_buf), len(w_buf))

        hall_seq_ai = "---"

        if n > 0:
            midpoint = (HALL_THRESHOLDS["vh_min"] + HALL_THRESHOLDS["vl_max"]) / 2.0

            u_s = np.asarray(u_buf[-n:]) >= midpoint
            v_s = np.asarray(v_buf[-n:]) >= midpoint
            w_s = np.asarray(w_buf[-n:]) >= midpoint

            # UVW → 狀態編碼（U=bit0, V=bit1, W=bit2）
            states = (
                u_s.astype(np.int8)
                | (v_s.astype(np.int8) << 1)
                | (w_s.astype(np.int8) << 2)
            )

            # 找出狀態轉換點（含第一個）
            change_idx = np.where(np.diff(states) != 0)[0] + 1
            idx_list = np.concatenate(([0], change_idx))

            # 重新從最新一段時序資料判斷相序（避免累積舊稀疏快照）
            self._hall_seq_detector_ai.reset()
            for i in idx_list:
                hall_seq_ai = self._hall_seq_detector_ai.update(
                    bool(u_s[i]), bool(v_s[i]), bool(w_s[i])
                )

            # ── 狀態序列跨幀累積（含跨幀去重）──────────────────────────────
            # 只把本窗口內「新出現」的有效狀態（1~6）append 到持久化歷史。
            # 跨幀去重：與上次累積的最後狀態相同者略過，避免同一狀態被重複記錄
            # （例如相鄰兩幀窗口都以同一狀態結尾/開頭）。
            for i in idx_list:
                s = int(states[i])
                if s in (0, 7):          # 無效狀態（三相全同）忽略
                    continue
                if s == self._hall_last_seq_state:  # 與上次累積相同 → 去重
                    continue
                self._hall_state_history.append(s)
                self._hall_last_seq_state = s

            # H/L/X 顯示電壓改用最近 DISP_N 點平均（避免瞬時快照導致顯示靜止）
            for phase in ("U", "V", "W"):
                ch = HALL_THRESHOLDS["channels"][phase]
                buf = self._ai_reader.get_buffer(ch)
                if len(buf) >= DISP_N:
                    hall_voltages[phase] = float(np.mean(buf[-DISP_N:]))

        # debug 狀態序列字串（如 "51326451"）— 取持久化歷史最近 SEQ_DISPLAY_N 個
        # 跨幀保留，低速或本幀無新轉換時仍顯示先前累積的序列，不會被清空
        hall_seq_states = "".join(
            str(s) for s in list(self._hall_state_history)[-SEQ_DISPLAY_N:]
        )

        # 更新 ResultPanel 即時電壓顯示（H/L/X 準位由 AI 電壓判定）
        self._result_panel.update_live_voltages(
            hall_voltages=hall_voltages,
            hall_seq_ai=hall_seq_ai,
            hall_seq_states=hall_seq_states,
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

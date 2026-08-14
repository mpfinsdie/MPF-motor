"""
主視窗模組
整合波形顯示、測試結果面板與控制按鈕
"""

import time
import numpy as np
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QSplitter, QStatusBar,
    QMessageBox, QFileDialog, QGroupBox, QSpinBox,
    QDoubleSpinBox, QFormLayout, QFrame
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QThread
from PyQt5.QtGui import QFont, QIcon

from config.thresholds import SAMPLING, HALL_THRESHOLDS, ENCODER_THRESHOLDS
from daq.daq_controller import DAQController
from daq.ai_reader import AIReader
from daq.di_reader import DIReader
from logic.hall_analyzer import HallAnalyzer
from logic.encoder_analyzer import EncoderAnalyzer
from ui.waveform_widget import WaveformWidget
from ui.result_panel import ResultPanel
from report.report_generator import ReportGenerator


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
    QPushButton:hover {
        background-color: #3A72B0;
    }
    QPushButton:pressed {
        background-color: #1E3F6B;
    }
    QPushButton:disabled {
        background-color: #3A3A3A;
        color: #666666;
    }
    QPushButton#btn_stop {
        background-color: #8E2D2D;
    }
    QPushButton#btn_stop:hover {
        background-color: #B03A3A;
    }
    QPushButton#btn_export {
        background-color: #2D7A3A;
    }
    QPushButton#btn_export:hover {
        background-color: #3A9A4A;
    }
    QStatusBar {
        background-color: #252525;
        color: #AAAAAA;
        font-size: 11px;
    }
    QSplitter::handle {
        background-color: #444444;
    }
    QSpinBox, QDoubleSpinBox {
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
"""

BTN_START_STYLE = "background-color: #2D8E2D; color: #FFFFFF; border-radius: 4px; padding: 6px 16px; font-weight: bold;"
BTN_STOP_STYLE = "background-color: #8E2D2D; color: #FFFFFF; border-radius: 4px; padding: 6px 16px; font-weight: bold;"


class MainWindow(QMainWindow):
    """
    馬達測試程式主視窗
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("馬達測試系統 - Hall Sensor & Encoder 量測")
        self.setMinimumSize(1280, 800)
        self.setStyleSheet(MAIN_STYLE)

        # ── 核心元件 ──────────────────────────────────────────────────────────
        self._daq = DAQController()
        self._ai_reader = AIReader(self._daq)
        self._di_reader = DIReader(self._daq)
        self._hall_analyzer = HallAnalyzer()
        self._enc_analyzer = EncoderAnalyzer()
        self._report_gen = ReportGenerator()

        self._is_running = False
        self._last_hall_result = None
        self._last_enc_result = None

        # ── UI ────────────────────────────────────────────────────────────────
        self._setup_ui()
        self._setup_timer()
        self._setup_status_bar()

        # 嘗試連線
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

        # 主要內容區（左：波形，右：結果）
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

        # 控制按鈕
        self._btn_start = QPushButton("▶ 開始量測")
        self._btn_start.setStyleSheet(BTN_START_STYLE)
        self._btn_start.clicked.connect(self._on_start)
        layout.addWidget(self._btn_start)

        self._btn_stop = QPushButton("■ 停止")
        self._btn_stop.setStyleSheet(BTN_STOP_STYLE)
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self._on_stop)
        layout.addWidget(self._btn_stop)

        self._btn_reset_enc = QPushButton("↺ 重置計數")
        self._btn_reset_enc.clicked.connect(self._on_reset_encoder)
        layout.addWidget(self._btn_reset_enc)

        self._btn_export = QPushButton("💾 匯出報表")
        self._btn_export.setObjectName("btn_export")
        self._btn_export.clicked.connect(self._on_export)
        layout.addWidget(self._btn_export)

        self._btn_reconnect = QPushButton("🔌 重新連線")
        self._btn_reconnect.clicked.connect(self._connect_device)
        layout.addWidget(self._btn_reconnect)

        return toolbar

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
        """設定 GUI 更新計時器"""
        self._update_timer = QTimer(self)
        self._update_timer.setInterval(SAMPLING["display_update_ms"])
        self._update_timer.timeout.connect(self._update_display)

    def _setup_status_bar(self):
        """設定狀態列"""
        self._status_bar = self.statusBar()
        self._status_bar.showMessage("就緒 | 請連線裝置後開始量測")

    # ─── 裝置連線 ──────────────────────────────────────────────────────────────

    def _connect_device(self):
        """連線到 DAQ 裝置"""
        success = self._daq.connect()
        if success:
            mode = "模擬模式" if self._daq.is_simulation else "USB-4716"
            self._device_status_lbl.setText(f"● 已連線 ({mode})")
            self._device_status_lbl.setStyleSheet("color: #44FF44; font-size: 12px;")
            self._status_bar.showMessage(f"裝置已連線: {mode}")
        else:
            self._device_status_lbl.setText("● 連線失敗")
            self._device_status_lbl.setStyleSheet("color: #FF4444; font-size: 12px;")
            self._status_bar.showMessage("裝置連線失敗，請檢查 USB-4716 連接")

    # ─── 控制事件 ──────────────────────────────────────────────────────────────

    def _on_start(self):
        """開始量測"""
        if not self._daq.is_connected:
            QMessageBox.warning(self, "警告", "裝置未連線，請先連線 USB-4716")
            return

        self._is_running = True
        self._ai_reader.start()
        self._di_reader.start()
        self._update_timer.start()

        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._status_bar.showMessage("量測中...")
        self._hall_analyzer.clear_history()
        self._enc_analyzer.clear_history()
        self._report_gen.clear()

    def _on_stop(self):
        """停止量測"""
        self._is_running = False
        self._update_timer.stop()
        self._ai_reader.stop()
        self._di_reader.stop()

        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._status_bar.showMessage(
            f"量測已停止 | Hall 記錄: {len(self._hall_analyzer.get_history())} 筆 | "
            f"Encoder 記錄: {len(self._enc_analyzer.get_history())} 筆"
        )

    def _on_reset_encoder(self):
        """重置 Encoder 計數器"""
        self._di_reader.reset_encoder()
        self._status_bar.showMessage("Encoder 計數器已重置")

    def _on_export(self):
        """匯出測試報表"""
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
        """定時更新 GUI 顯示（由 QTimer 觸發）"""
        try:
            self._update_waveforms()
            self._update_analysis()
        except Exception as e:
            print(f"[MainWindow] 顯示更新錯誤: {e}")

    def _update_waveforms(self):
        """更新波形顯示"""
        from config.thresholds import HALL_THRESHOLDS as HT, ENCODER_THRESHOLDS as ET

        # Hall AI 波形
        u_buf = self._ai_reader.get_buffer(HT["channels"]["U"])
        v_buf = self._ai_reader.get_buffer(HT["channels"]["V"])
        w_buf = self._ai_reader.get_buffer(HT["channels"]["W"])
        self._waveform_widget.update_hall_waveform(u_buf, v_buf, w_buf)

        # Encoder AI + DI 波形
        a_ai = self._ai_reader.get_buffer(ET["channels"]["A"])
        b_ai = self._ai_reader.get_buffer(ET["channels"]["B"])
        a_di = self._di_reader.get_encoder_a_buffer()
        b_di = self._di_reader.get_encoder_b_buffer()
        self._waveform_widget.update_encoder_waveform(a_ai, b_ai, a_di, b_di)

    def _update_analysis(self):
        """更新分析結果顯示"""
        t = time.time()

        # Hall 分析
        hall_voltages = self._ai_reader.get_hall_voltages()
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
        enc_state = self._di_reader.get_encoder_state()
        enc_di_states = {"A": enc_state["A"], "B": enc_state["B"]}
        enc_result = self._enc_analyzer.analyze(
            voltages=enc_voltages,
            di_states=enc_di_states,
            count=enc_state["count"],
            rpm=enc_state["rpm"],
            position_deg=enc_state["position_deg"],
            a_buffer=self._di_reader.get_encoder_a_buffer(),
            b_buffer=self._di_reader.get_encoder_b_buffer(),
            timestamp=t
        )
        self._last_enc_result = enc_result
        self._result_panel.update_encoder(enc_result)

        # 收集報表資料
        self._report_gen.add_record(hall_result, enc_result)

    # ─── 視窗關閉 ──────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        """視窗關閉時釋放資源"""
        if self._is_running:
            self._on_stop()
        self._daq.disconnect()
        event.accept()

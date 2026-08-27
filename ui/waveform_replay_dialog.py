"""
波形回放對話框
載入 FAIL 場次儲存的 .npz 波形檔案，以靜態方式顯示完整波形
支援時間軸滑動、分段瀏覽
"""

import os
from pathlib import Path
from typing import Dict, Any, Optional

import numpy as np
import pyqtgraph as pg
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSlider, QGroupBox, QWidget, QSizePolicy, QMessageBox,
    QSpinBox, QFrame
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QColor

from config.thresholds import HALL_THRESHOLDS, ENCODER_THRESHOLDS
from logic.waveform_recorder import WaveformRecorder


REPLAY_STYLE = """
    QDialog {
        background-color: #1A1A1A;
        color: #CCCCCC;
    }
    QLabel {
        color: #CCCCCC;
        font-size: 12px;
    }
    QLabel#lbl_title {
        color: #FF8844;
        font-size: 14px;
        font-weight: bold;
    }
    QLabel#lbl_info {
        color: #AAAAAA;
        font-size: 11px;
    }
    QPushButton {
        background-color: #2D5A8E;
        color: #FFFFFF;
        border: none;
        border-radius: 4px;
        padding: 6px 14px;
        font-size: 12px;
        font-weight: bold;
        min-width: 70px;
    }
    QPushButton:hover { background-color: #3A72B0; }
    QPushButton:disabled { background-color: #3A3A3A; color: #666666; }
    QPushButton#btn_play {
        background-color: #2D8E2D;
        min-width: 90px;
    }
    QPushButton#btn_play:hover { background-color: #3AAA3A; }
    QPushButton#btn_play:checked {
        background-color: #8E6A00;
    }
    QSlider::groove:horizontal {
        height: 6px;
        background: #333333;
        border-radius: 3px;
    }
    QSlider::handle:horizontal {
        background: #4AABFF;
        width: 14px;
        height: 14px;
        margin: -4px 0;
        border-radius: 7px;
    }
    QSlider::sub-page:horizontal {
        background: #2D5A8E;
        border-radius: 3px;
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
    QSpinBox {
        background-color: #2A2A2A;
        color: #CCCCCC;
        border: 1px solid #444444;
        border-radius: 3px;
        padding: 2px 4px;
    }
    QFrame#separator {
        background-color: #444444;
    }
"""

# 波形顏色
COLORS = {
    "Hall U":    "#FF4444",
    "Hall V":    "#44FF44",
    "Hall W":    "#4488FF",
    "Encoder A": "#FFAA00",
    "Encoder B": "#AA44FF",
}

# 每次顯示的樣本點數（視窗寬度）
DEFAULT_WINDOW_SIZE = 200


class WaveformReplayDialog(QDialog):
    """
    FAIL 波形回放對話框

    功能：
    - 載入 .npz 波形檔案
    - 顯示完整 Hall U/V/W 與 Encoder A/B 波形
    - 支援時間軸滑動（Slider）瀏覽
    - 支援自動播放（逐格前進）
    - 顯示場次基本資訊
    """

    def __init__(
        self,
        waveform_path: str,
        session_info: Optional[Dict[str, Any]] = None,
        parent=None
    ):
        """
        Args:
            waveform_path: .npz 波形檔案路徑
            session_info:  場次資訊 dict（來自 DB query_sessions）
            parent:        父視窗
        """
        super().__init__(parent)
        self._waveform_path = waveform_path
        self._session_info  = session_info or {}
        self._waveform_data: Optional[Dict] = None

        # 播放狀態
        self._play_timer = QTimer(self)
        self._play_timer.setInterval(100)   # 100ms 每格 → 約 10x 速
        self._play_timer.timeout.connect(self._on_play_tick)
        self._is_playing = False

        # 視窗大小（每次顯示的樣本點數）
        self._window_size = DEFAULT_WINDOW_SIZE
        self._current_pos = 0   # 目前視窗起始索引

        self.setWindowTitle("波形回放 — FAIL 場次")
        self.setMinimumSize(1100, 680)
        self.setStyleSheet(REPLAY_STYLE)

        self._setup_ui()
        self._load_waveform()

    # ─── UI 建立 ───────────────────────────────────────────────────────────────

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        # 標題 + 場次資訊
        layout.addWidget(self._build_header())

        # 波形圖區
        layout.addWidget(self._build_plot_area(), stretch=1)

        # 播放控制列
        layout.addWidget(self._build_playback_controls())

        # 底部關閉按鈕
        layout.addWidget(self._build_bottom_bar())

    def _build_header(self) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(16)

        title = QLabel("📈  FAIL 波形回放")
        title.setObjectName("lbl_title")
        h.addWidget(title)

        sep = QFrame()
        sep.setObjectName("separator")
        sep.setFrameShape(QFrame.VLine)
        sep.setFixedWidth(1)
        h.addWidget(sep)

        # 場次資訊
        info = self._session_info
        session_id = info.get("id", "---")
        serial     = info.get("serial_no") or "(無序號)"
        operator   = info.get("operator")  or "(無)"
        started    = info.get("started_at", "---")
        hall_rate  = (info.get("hall_pass_rate") or 0) * 100
        enc_rate   = (info.get("enc_pass_rate")  or 0) * 100

        info_lbl = QLabel(
            f"場次 #{session_id}  |  序號: {serial}  |  操作員: {operator}  |  "
            f"開始: {started}  |  "
            f"Hall: {hall_rate:.1f}%  Enc: {enc_rate:.1f}%"
        )
        info_lbl.setObjectName("lbl_info")
        h.addWidget(info_lbl)
        h.addStretch()

        # 檔案路徑
        path_lbl = QLabel(f"📁 {Path(self._waveform_path).name}")
        path_lbl.setObjectName("lbl_info")
        path_lbl.setToolTip(self._waveform_path)
        h.addWidget(path_lbl)

        return w

    def _build_plot_area(self) -> QWidget:
        """建立 pyqtgraph 波形圖區（Hall + Encoder 兩個子圖）"""
        self._graphics_layout = pg.GraphicsLayoutWidget()
        self._graphics_layout.setBackground("#1E1E1E")

        # ── Hall Sensor 波形 ──────────────────────────────────────────────────
        self._hall_plot = self._graphics_layout.addPlot(
            row=0, col=0, title="Hall Sensor 電壓 (3.3V 系統)"
        )
        self._hall_plot.setLabel("left", "電壓 (V)")
        self._hall_plot.setLabel("bottom", "樣本點")
        self._hall_plot.setYRange(-0.2, 3.8)
        self._hall_plot.showGrid(x=True, y=True, alpha=0.3)
        self._hall_plot.addLegend(offset=(10, 10))
        self._hall_plot.getViewBox().setMouseEnabled(x=True, y=False)

        # Hall 閾值線
        vh_min = HALL_THRESHOLDS["vh_min"]
        vl_max = HALL_THRESHOLDS["vl_max"]
        self._hall_plot.addItem(pg.InfiniteLine(
            pos=vh_min, angle=0,
            pen=pg.mkPen("#FFFFFF", width=1, style=Qt.DashLine),
            label=f"VH_min={vh_min}V",
            labelOpts={"color": "#FFFFFF", "position": 0.95}
        ))
        self._hall_plot.addItem(pg.InfiniteLine(
            pos=vl_max, angle=0,
            pen=pg.mkPen("#888888", width=1, style=Qt.DashLine),
            label=f"VL_max={vl_max}V",
            labelOpts={"color": "#888888", "position": 0.95}
        ))

        # Hall 曲線（初始空資料）
        self._hall_curves = {
            "U": self._hall_plot.plot(pen=pg.mkPen(COLORS["Hall U"],    width=2), name="Hall U"),
            "V": self._hall_plot.plot(pen=pg.mkPen(COLORS["Hall V"],    width=2), name="Hall V"),
            "W": self._hall_plot.plot(pen=pg.mkPen(COLORS["Hall W"],    width=2), name="Hall W"),
        }

        # ── Encoder 波形 ──────────────────────────────────────────────────────
        self._enc_plot = self._graphics_layout.addPlot(
            row=1, col=0, title="Encoder 電壓 (5V 系統)"
        )
        self._enc_plot.setLabel("left", "電壓 (V)")
        self._enc_plot.setLabel("bottom", "樣本點")
        self._enc_plot.setYRange(-0.5, 6.0)
        self._enc_plot.showGrid(x=True, y=True, alpha=0.3)
        self._enc_plot.addLegend(offset=(10, 10))
        self._enc_plot.getViewBox().setMouseEnabled(x=True, y=False)

        # Encoder 閾值線
        enc_vh = ENCODER_THRESHOLDS["vh_min"]
        enc_vl = ENCODER_THRESHOLDS["vl_max"]
        self._enc_plot.addItem(pg.InfiniteLine(
            pos=enc_vh, angle=0,
            pen=pg.mkPen("#FFFFFF", width=1, style=Qt.DashLine),
            label=f"VH_min={enc_vh}V",
            labelOpts={"color": "#FFFFFF", "position": 0.95}
        ))
        self._enc_plot.addItem(pg.InfiniteLine(
            pos=enc_vl, angle=0,
            pen=pg.mkPen("#888888", width=1, style=Qt.DashLine),
            label=f"VL_max={enc_vl}V",
            labelOpts={"color": "#888888", "position": 0.95}
        ))

        # Encoder 曲線
        self._enc_curves = {
            "A": self._enc_plot.plot(pen=pg.mkPen(COLORS["Encoder A"], width=2), name="Encoder A"),
            "B": self._enc_plot.plot(pen=pg.mkPen(COLORS["Encoder B"], width=2), name="Encoder B"),
        }

        # 連結 X 軸
        self._enc_plot.setXLink(self._hall_plot)

        # 高度比例
        self._graphics_layout.ci.layout.setRowStretchFactor(0, 1)
        self._graphics_layout.ci.layout.setRowStretchFactor(1, 1)

        return self._graphics_layout

    def _build_playback_controls(self) -> QGroupBox:
        """建立播放控制列（滑桿 + 播放/暫停 + 視窗大小）"""
        group = QGroupBox("播放控制")
        layout = QVBoxLayout(group)
        layout.setSpacing(6)

        # 時間資訊列
        info_row = QHBoxLayout()
        self._pos_lbl = QLabel("位置: 0 / 0")
        self._pos_lbl.setStyleSheet("color: #FFFF44; font-family: Consolas; font-size: 12px;")
        info_row.addWidget(self._pos_lbl)

        info_row.addStretch()

        self._time_lbl = QLabel("時間: 0.00 s")
        self._time_lbl.setStyleSheet("color: #AAAAFF; font-family: Consolas; font-size: 12px;")
        info_row.addWidget(self._time_lbl)

        self._total_lbl = QLabel("總時長: --- s")
        self._total_lbl.setStyleSheet("color: #AAAAAA; font-size: 11px;")
        info_row.addWidget(self._total_lbl)

        layout.addLayout(info_row)

        # 滑桿列
        slider_row = QHBoxLayout()
        slider_row.addWidget(QLabel("◀"))

        self._slider = QSlider(Qt.Horizontal)
        self._slider.setMinimum(0)
        self._slider.setMaximum(0)
        self._slider.setValue(0)
        self._slider.setTickInterval(1)
        self._slider.valueChanged.connect(self._on_slider_changed)
        slider_row.addWidget(self._slider, stretch=1)

        slider_row.addWidget(QLabel("▶"))
        layout.addLayout(slider_row)

        # 按鈕列
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        # 跳到開頭
        btn_begin = QPushButton("⏮ 開頭")
        btn_begin.clicked.connect(self._on_go_begin)
        btn_row.addWidget(btn_begin)

        # 後退一格
        btn_prev = QPushButton("◀ 後退")
        btn_prev.clicked.connect(self._on_step_back)
        btn_row.addWidget(btn_prev)

        # 播放/暫停
        self._btn_play = QPushButton("▶ 播放")
        self._btn_play.setObjectName("btn_play")
        self._btn_play.setCheckable(True)
        self._btn_play.clicked.connect(self._on_toggle_play)
        btn_row.addWidget(self._btn_play)

        # 前進一格
        btn_next = QPushButton("前進 ▶")
        btn_next.clicked.connect(self._on_step_forward)
        btn_row.addWidget(btn_next)

        # 跳到結尾
        btn_end = QPushButton("結尾 ⏭")
        btn_end.clicked.connect(self._on_go_end)
        btn_row.addWidget(btn_end)

        btn_row.addStretch()

        # 顯示全部波形按鈕
        btn_all = QPushButton("📊 顯示全部")
        btn_all.clicked.connect(self._on_show_all)
        btn_row.addWidget(btn_all)

        btn_row.addWidget(QLabel("視窗大小:"))
        self._window_spin = QSpinBox()
        self._window_spin.setRange(50, 5000)
        self._window_spin.setValue(DEFAULT_WINDOW_SIZE)
        self._window_spin.setSingleStep(50)
        self._window_spin.setSuffix(" 點")
        self._window_spin.setFixedWidth(90)
        self._window_spin.valueChanged.connect(self._on_window_size_changed)
        btn_row.addWidget(self._window_spin)

        # 播放速度
        btn_row.addWidget(QLabel("速度:"))
        self._speed_spin = QSpinBox()
        self._speed_spin.setRange(1, 20)
        self._speed_spin.setValue(5)
        self._speed_spin.setSuffix(" 格/次")
        self._speed_spin.setFixedWidth(80)
        btn_row.addWidget(self._speed_spin)

        layout.addLayout(btn_row)
        return group

    def _build_bottom_bar(self) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)

        # 樣本資訊
        self._sample_info_lbl = QLabel("")
        self._sample_info_lbl.setObjectName("lbl_info")
        h.addWidget(self._sample_info_lbl)

        h.addStretch()

        btn_close = QPushButton("關閉")
        btn_close.clicked.connect(self.accept)
        h.addWidget(btn_close)

        return w

    # ─── 資料載入 ──────────────────────────────────────────────────────────────

    def _load_waveform(self):
        """載入 .npz 波形檔案並初始化顯示"""
        if not os.path.isfile(self._waveform_path):
            QMessageBox.critical(
                self, "錯誤",
                f"波形檔案不存在：\n{self._waveform_path}"
            )
            return

        try:
            self._waveform_data = WaveformRecorder.load(self._waveform_path)
        except Exception as e:
            QMessageBox.critical(self, "錯誤", f"載入波形檔案失敗：\n{e}")
            return

        n = self._waveform_data["sample_count"]
        duration = self._waveform_data["duration_s"]

        # 更新 UI 資訊
        self._total_lbl.setText(f"總時長: {duration:.2f} s")
        self._sample_info_lbl.setText(
            f"共 {n} 筆樣本  |  時長 {duration:.2f} 秒  |  "
            f"取樣率約 {n/duration:.1f} Hz" if duration > 0 else f"共 {n} 筆樣本"
        )

        # 設定滑桿範圍
        max_pos = max(0, n - self._window_size)
        self._slider.setMaximum(max_pos)
        self._slider.setValue(0)

        # 顯示第一個視窗
        self._current_pos = 0
        self._refresh_plot()

    # ─── 波形更新 ──────────────────────────────────────────────────────────────

    def _refresh_plot(self):
        """根據 _current_pos 更新波形顯示"""
        if self._waveform_data is None:
            return

        data = self._waveform_data
        n    = data["sample_count"]
        pos  = self._current_pos
        end  = min(pos + self._window_size, n)

        x = np.arange(pos, end)

        # Hall 波形
        self._hall_curves["U"].setData(x, data["hall_u"][pos:end])
        self._hall_curves["V"].setData(x, data["hall_v"][pos:end])
        self._hall_curves["W"].setData(x, data["hall_w"][pos:end])

        # Encoder 波形
        self._enc_curves["A"].setData(x, data["enc_a"][pos:end])
        self._enc_curves["B"].setData(x, data["enc_b"][pos:end])

        # 更新 X 軸範圍
        self._hall_plot.setXRange(pos, end, padding=0.02)

        # 更新位置標籤
        self._pos_lbl.setText(f"位置: {pos} ~ {end} / {n}")

        # 更新時間標籤
        timestamps = data["timestamps"]
        if len(timestamps) > pos:
            t_start = timestamps[0]
            t_cur   = timestamps[min(pos, len(timestamps)-1)]
            self._time_lbl.setText(f"時間: {t_cur - t_start:.2f} s")

        # 同步滑桿（避免遞迴觸發）
        self._slider.blockSignals(True)
        self._slider.setValue(pos)
        self._slider.blockSignals(False)

    def _show_all_waveform(self):
        """顯示完整波形（不分段）"""
        if self._waveform_data is None:
            return

        data = self._waveform_data
        n    = data["sample_count"]
        x    = np.arange(n)

        self._hall_curves["U"].setData(x, data["hall_u"])
        self._hall_curves["V"].setData(x, data["hall_v"])
        self._hall_curves["W"].setData(x, data["hall_w"])
        self._enc_curves["A"].setData(x, data["enc_a"])
        self._enc_curves["B"].setData(x, data["enc_b"])

        self._hall_plot.setXRange(0, n, padding=0.02)
        self._pos_lbl.setText(f"位置: 0 ~ {n} / {n}（全部）")

    # ─── 播放控制事件 ──────────────────────────────────────────────────────────

    def _on_slider_changed(self, value: int):
        """滑桿拖動時更新波形"""
        self._current_pos = value
        self._refresh_plot()

    def _on_toggle_play(self, checked: bool):
        """播放/暫停切換"""
        if checked:
            self._btn_play.setText("⏸ 暫停")
            self._is_playing = True
            self._play_timer.start()
        else:
            self._btn_play.setText("▶ 播放")
            self._is_playing = False
            self._play_timer.stop()

    def _on_play_tick(self):
        """播放計時器觸發：前進 N 格"""
        if self._waveform_data is None:
            return

        n     = self._waveform_data["sample_count"]
        step  = self._speed_spin.value()
        new_pos = self._current_pos + step

        if new_pos >= n - self._window_size:
            # 播放到結尾，自動停止
            new_pos = max(0, n - self._window_size)
            self._btn_play.setChecked(False)
            self._on_toggle_play(False)

        self._current_pos = new_pos
        self._refresh_plot()

    def _on_step_forward(self):
        """前進一格"""
        if self._waveform_data is None:
            return
        n = self._waveform_data["sample_count"]
        step = self._speed_spin.value()
        self._current_pos = min(self._current_pos + step, max(0, n - self._window_size))
        self._refresh_plot()

    def _on_step_back(self):
        """後退一格"""
        step = self._speed_spin.value()
        self._current_pos = max(0, self._current_pos - step)
        self._refresh_plot()

    def _on_go_begin(self):
        """跳到開頭"""
        self._current_pos = 0
        self._refresh_plot()

    def _on_go_end(self):
        """跳到結尾"""
        if self._waveform_data is None:
            return
        n = self._waveform_data["sample_count"]
        self._current_pos = max(0, n - self._window_size)
        self._refresh_plot()

    def _on_show_all(self):
        """顯示全部波形"""
        self._show_all_waveform()

    def _on_window_size_changed(self, value: int):
        """視窗大小改變時更新滑桿範圍並重繪"""
        self._window_size = value
        if self._waveform_data:
            n = self._waveform_data["sample_count"]
            max_pos = max(0, n - self._window_size)
            self._slider.setMaximum(max_pos)
            self._current_pos = min(self._current_pos, max_pos)
        self._refresh_plot()

    # ─── 視窗關閉 ──────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        """關閉時停止播放計時器"""
        self._play_timer.stop()
        super().closeEvent(event)

    def reject(self):
        self._play_timer.stop()
        super().reject()

    def accept(self):
        self._play_timer.stop()
        super().accept()

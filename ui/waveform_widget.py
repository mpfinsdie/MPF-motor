"""
即時波形顯示元件
使用 pyqtgraph 繪製 Hall Sensor 與 Encoder 的即時波形
"""

import numpy as np
import pyqtgraph as pg
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

from config.thresholds import HALL_THRESHOLDS, ENCODER_THRESHOLDS, SAMPLING

# 波形顏色設定
COLORS = {
    "Hall U":     "#FF4444",   # 紅
    "Hall V":     "#44FF44",   # 綠
    "Hall W":     "#4444FF",   # 藍
    "Encoder A":  "#FFAA00",   # 橙
    "Encoder B":  "#AA00FF",   # 紫
    "Threshold H": "#FFFFFF",  # 白（閾值線）
    "Threshold L": "#888888",  # 灰（閾值線）
}


class WaveformWidget(QWidget):
    """
    即時波形顯示元件
    包含兩個子圖：
    - 上方：Hall Sensor AI 電壓波形（3.3V 系統）
    - 下方：Encoder AI 電壓波形（5V 系統）
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._buffer_size = SAMPLING["buffer_size"]
        self._setup_ui()
        self._setup_plots()

    def _setup_ui(self):
        """建立 UI 佈局"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # 標題
        title = QLabel("即時波形監測")
        title.setFont(QFont("Arial", 11, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color: #CCCCCC; padding: 4px;")
        layout.addWidget(title)

        # pyqtgraph 圖形視窗
        self._graphics_layout = pg.GraphicsLayoutWidget()
        self._graphics_layout.setBackground("#1E1E1E")
        layout.addWidget(self._graphics_layout)

    def _setup_plots(self):
        """建立波形圖"""
        gl = self._graphics_layout

        # ── Hall Sensor 電壓波形 ──────────────────────────────────────────────
        self._hall_plot = gl.addPlot(row=0, col=0, title="Hall Sensor 電壓 (3.3V 系統)")
        self._hall_plot.setLabel("left", "電壓 (V)")
        self._hall_plot.setLabel("bottom", "樣本點")
        self._hall_plot.setYRange(-0.2, 3.8)
        self._hall_plot.showGrid(x=True, y=True, alpha=0.3)
        self._hall_plot.addLegend(offset=(10, 10))
        # 滾輪只縮放 X 軸，Y 軸固定
        self._hall_plot.getViewBox().setMouseEnabled(x=True, y=False)

        # Hall 閾值線
        vh_min = HALL_THRESHOLDS["vh_min"]
        vl_max = HALL_THRESHOLDS["vl_max"]
        self._hall_plot.addItem(
            pg.InfiniteLine(pos=vh_min, angle=0, pen=pg.mkPen("#FFFFFF", width=1, style=Qt.DashLine),
                            label=f"VH_min={vh_min}V", labelOpts={"color": "#FFFFFF", "position": 0.95})
        )
        self._hall_plot.addItem(
            pg.InfiniteLine(pos=vl_max, angle=0, pen=pg.mkPen("#888888", width=1, style=Qt.DashLine),
                            label=f"VL_max={vl_max}V", labelOpts={"color": "#888888", "position": 0.95})
        )

        # Hall 波形曲線
        x = np.arange(self._buffer_size)
        self._hall_curves = {
            "U": self._hall_plot.plot(x, np.zeros(self._buffer_size),
                                       pen=pg.mkPen(COLORS["Hall U"], width=2), name="Hall U"),
            "V": self._hall_plot.plot(x, np.zeros(self._buffer_size),
                                       pen=pg.mkPen(COLORS["Hall V"], width=2), name="Hall V"),
            "W": self._hall_plot.plot(x, np.zeros(self._buffer_size),
                                       pen=pg.mkPen(COLORS["Hall W"], width=2), name="Hall W"),
        }

        # ── Encoder 電壓波形 ──────────────────────────────────────────────────
        self._enc_plot = gl.addPlot(row=1, col=0, title="Encoder 電壓 (5V 系統)")
        self._enc_plot.setLabel("left", "電壓 (V)")
        self._enc_plot.setLabel("bottom", "樣本點")
        self._enc_plot.setYRange(-0.5, 6.0)
        self._enc_plot.showGrid(x=True, y=True, alpha=0.3)
        self._enc_plot.addLegend(offset=(10, 10))
        # 滾輪只縮放 X 軸，Y 軸固定
        self._enc_plot.getViewBox().setMouseEnabled(x=True, y=False)

        # Encoder 閾值線
        enc_vh_min = ENCODER_THRESHOLDS["vh_min"]
        enc_vl_max = ENCODER_THRESHOLDS["vl_max"]
        self._enc_plot.addItem(
            pg.InfiniteLine(pos=enc_vh_min, angle=0, pen=pg.mkPen("#FFFFFF", width=1, style=Qt.DashLine),
                            label=f"VH_min={enc_vh_min}V", labelOpts={"color": "#FFFFFF", "position": 0.95})
        )
        self._enc_plot.addItem(
            pg.InfiniteLine(pos=enc_vl_max, angle=0, pen=pg.mkPen("#888888", width=1, style=Qt.DashLine),
                            label=f"VL_max={enc_vl_max}V", labelOpts={"color": "#888888", "position": 0.95})
        )

        # Encoder 波形曲線
        self._enc_curves = {
            "A": self._enc_plot.plot(x, np.zeros(self._buffer_size),
                                      pen=pg.mkPen(COLORS["Encoder A"], width=2), name="Encoder A"),
            "B": self._enc_plot.plot(x, np.zeros(self._buffer_size),
                                      pen=pg.mkPen(COLORS["Encoder B"], width=2), name="Encoder B"),
        }

        # 連結 X 軸縮放
        self._enc_plot.setXLink(self._hall_plot)

        # 調整各圖高度比例
        gl.ci.layout.setRowStretchFactor(0, 1)
        gl.ci.layout.setRowStretchFactor(1, 1)

    def update_hall_waveform(self, u_data: np.ndarray, v_data: np.ndarray, w_data: np.ndarray):
        """
        更新 Hall Sensor 波形
        Args:
            u_data: Hall U 電壓陣列
            v_data: Hall V 電壓陣列
            w_data: Hall W 電壓陣列
        """
        n = len(u_data)
        if n == 0:
            return
        x = np.arange(n)
        self._hall_curves["U"].setData(x, u_data)
        self._hall_curves["V"].setData(x, v_data)
        self._hall_curves["W"].setData(x, w_data)

    def update_encoder_waveform(
        self,
        a_voltage: np.ndarray,
        b_voltage: np.ndarray,
        a_di: np.ndarray = None,
        b_di: np.ndarray = None
    ):
        """
        更新 Encoder 波形（僅顯示 AI 電壓，DI 數位訊號已移除）
        Args:
            a_voltage: Encoder A AI 電壓陣列
            b_voltage: Encoder B AI 電壓陣列
            a_di: 保留參數（不使用）
            b_di: 保留參數（不使用）
        """
        n = len(a_voltage)
        if n == 0:
            return
        x = np.arange(n)
        self._enc_curves["A"].setData(x, a_voltage)
        self._enc_curves["B"].setData(x, b_voltage)

    def clear_all(self):
        """清除所有波形"""
        empty = np.zeros(self._buffer_size)
        x = np.arange(self._buffer_size)
        for curve in self._hall_curves.values():
            curve.setData(x, empty)
        for curve in self._enc_curves.values():
            curve.setData(x, empty)

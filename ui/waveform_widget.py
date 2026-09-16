"""
即時波形顯示元件
使用 pyqtgraph 繪製三相 Hall Sensor 的即時波形（50 kHz/通道 連續串流）

即時監控僅顯示 Hall（U/V/W）AI 電壓波形；Encoder 與 DI 已於監控模式移除，
Encoder 波形觀察請使用「高取樣診斷」模式。
"""

import numpy as np
import pyqtgraph as pg
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QSizePolicy
from PyQt5.QtCore import Qt

from config.thresholds import HALL_THRESHOLDS, SAMPLING

# 波形顏色設定
COLORS = {
    "Hall U":     "#FF4444",   # 紅
    "Hall V":     "#44FF44",   # 綠
    "Hall W":     "#4444FF",   # 藍
    "Threshold H": "#FFFFFF",  # 白（閾值線）
    "Threshold L": "#888888",  # 灰（閾值線）
}


class WaveformWidget(QWidget):
    """
    即時波形顯示元件（僅三相 Hall Sensor）

    單一波形圖：Hall Sensor AI 電壓波形（3.3V 系統），含 VH_min / VL_max 閾值線。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._buffer_size = SAMPLING["buffer_size"]
        # 繪圖降採樣上限：50kHz 監控下每通道緩衝達 50,000 點，
        # 直接繪製 3 條曲線會拖累 UI，超過此上限時等間距抽稀（decimation）
        self._max_plot_points = SAMPLING.get("display_max_points", 4_000)
        self._setup_ui()
        self._setup_plots()

    def _decimate(self, data: np.ndarray):
        """
        繪圖降採樣：資料點數超過 _max_plot_points 時等間距抽稀。

        Returns:
            (x, y)：抽稀後的 X 軸索引與 Y 值（維持原始 X 座標尺度）
        """
        n = len(data)
        if n > self._max_plot_points:
            step = max(1, n // self._max_plot_points)
            y = data[::step]
            x = np.arange(0, n, step)[:len(y)]
            return x, y
        return np.arange(n), data

    def _setup_ui(self):
        """建立 UI 佈局"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # 注意：標題「即時波形監測」已移至外層控制列（見 MainWindow._build_monitor_ctrl_bar），
        # 此處不再重複顯示標題。

        # pyqtgraph 圖形視窗
        self._graphics_layout = pg.GraphicsLayoutWidget()
        self._graphics_layout.setBackground("#1E1E1E")
        layout.addWidget(self._graphics_layout)

    def _setup_plots(self):
        """建立 Hall 波形圖（佔滿整個版面）"""
        gl = self._graphics_layout

        # ── Hall Sensor 電壓波形 ──────────────────────────────────────────────
        self._hall_plot = gl.addPlot(row=0, col=0, title="Hall Sensor 電壓 (3.3V 系統) — 50 kHz/通道")
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

    def update_hall_waveform(self, u_data: np.ndarray, v_data: np.ndarray, w_data: np.ndarray):
        """
        更新 Hall Sensor 波形
        Args:
            u_data: Hall U 電壓陣列
            v_data: Hall V 電壓陣列
            w_data: Hall W 電壓陣列
        """
        if len(u_data) == 0:
            return
        xu, yu = self._decimate(u_data)
        xv, yv = self._decimate(v_data)
        xw, yw = self._decimate(w_data)
        self._hall_curves["U"].setData(xu, yu)
        self._hall_curves["V"].setData(xv, yv)
        self._hall_curves["W"].setData(xw, yw)

    def clear_all(self):
        """清除所有波形"""
        empty = np.zeros(self._buffer_size)
        x = np.arange(self._buffer_size)
        for curve in self._hall_curves.values():
            curve.setData(x, empty)

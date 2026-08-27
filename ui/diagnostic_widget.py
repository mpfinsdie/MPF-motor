"""
高取樣率診斷即時波形元件

功能：
  - 顯示單一 AI 通道的高取樣率即時波形（200kHz）
  - 滾動視窗模式：保留最近 N 點，隨 chunk 資料持續更新
  - 顯示當前通道名稱、閾值線、採樣進度
  - 支援切換通道時清空並重設 Y 軸範圍
  - 自動繪圖降採樣（decimation）：200kHz 資料點過多時自動抽稀，
    維持 UI 流暢（目標繪圖點數 ≤ PLOT_MAX_POINTS）
"""

import numpy as np
import pyqtgraph as pg
from collections import deque

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

from config.thresholds import DIAGNOSTIC, HALL_THRESHOLDS, ENCODER_THRESHOLDS


# 通道顏色
CH_COLORS = {
    0: "#FF4444",   # Hall U  紅
    1: "#44FF44",   # Hall V  綠
    2: "#4488FF",   # Hall W  藍
    3: "#FFAA00",   # Enc A   橙
    4: "#AA44FF",   # Enc B   紫
}

DIAG_WIDGET_STYLE = """
    QWidget {
        background-color: #1A1A1A;
        color: #CCCCCC;
    }
    QLabel {
        color: #CCCCCC;
        font-size: 12px;
    }
    QLabel#lbl_ch_name {
        color: #4AABFF;
        font-size: 15px;
        font-weight: bold;
    }
    QLabel#lbl_round {
        color: #FFFF44;
        font-size: 13px;
        font-weight: bold;
    }
    QLabel#lbl_progress {
        color: #AAAAAA;
        font-size: 11px;
    }
    QFrame#separator {
        background-color: #444444;
    }
"""


class DiagnosticWidget(QWidget):
    """
    高取樣率診斷即時波形元件

    使用方式：
        widget = DiagnosticWidget()
        widget.set_channel(ch_idx=0, ch_name="Hall U", y_range=(-0.2, 3.8),
                           vh_min=2.0, vl_max=0.8)
        widget.append_chunk(chunk_data)   # 每段 1000 點
        widget.set_progress(round_idx=0, elapsed_s=3.5, remaining_s=6.5)
    """

    # 繪圖最大點數（超過此值自動 decimation，避免 pyqtgraph 卡頓）
    PLOT_MAX_POINTS = 5_000

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(DIAG_WIDGET_STYLE)

        self._display_window = DIAGNOSTIC["display_window"]  # 100,000 點（0.5s @ 200kHz）
        self._sample_rate    = DIAGNOSTIC["sample_rate"]     # 200,000 Hz

        # 滾動緩衝區（保留最近 display_window 點的原始資料）
        self._buffer: deque = deque(maxlen=self._display_window)

        # 當前通道資訊
        self._current_ch_idx  = -1
        self._current_ch_name = ""
        self._current_y_range = (-0.5, 6.0)
        self._current_vh_min  = None
        self._current_vl_max  = None

        # 閾值線物件（可動態更新）
        self._vh_line = None
        self._vl_line = None

        self._setup_ui()
        self._setup_plot()

    # ─── UI 建立 ───────────────────────────────────────────────────────────────

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # ── 頂部資訊列 ────────────────────────────────────────────────────────
        info_bar = QWidget()
        info_bar.setFixedHeight(36)
        info_bar.setStyleSheet("background-color: #252525; border-radius: 4px;")
        info_layout = QHBoxLayout(info_bar)
        info_layout.setContentsMargins(10, 4, 10, 4)
        info_layout.setSpacing(12)

        # 通道名稱
        self._lbl_ch_name = QLabel("— 等待診斷開始 —")
        self._lbl_ch_name.setObjectName("lbl_ch_name")
        info_layout.addWidget(self._lbl_ch_name)

        sep1 = QFrame()
        sep1.setObjectName("separator")
        sep1.setFrameShape(QFrame.VLine)
        sep1.setFixedWidth(1)
        info_layout.addWidget(sep1)

        # 輪次
        self._lbl_round = QLabel("")
        self._lbl_round.setObjectName("lbl_round")
        info_layout.addWidget(self._lbl_round)

        sep2 = QFrame()
        sep2.setObjectName("separator")
        sep2.setFrameShape(QFrame.VLine)
        sep2.setFixedWidth(1)
        info_layout.addWidget(sep2)

        # 倒數計時
        self._lbl_countdown = QLabel("")
        self._lbl_countdown.setStyleSheet(
            "color: #FF8844; font-size: 14px; font-weight: bold; font-family: Consolas;"
        )
        info_layout.addWidget(self._lbl_countdown)

        info_layout.addStretch()

        # 取樣率標示
        self._lbl_sr = QLabel(f"取樣率: {self._sample_rate:,} Hz")
        self._lbl_sr.setObjectName("lbl_progress")
        info_layout.addWidget(self._lbl_sr)

        sep3 = QFrame()
        sep3.setObjectName("separator")
        sep3.setFrameShape(QFrame.VLine)
        sep3.setFixedWidth(1)
        info_layout.addWidget(sep3)

        # 已採點數
        self._lbl_pts = QLabel("已採: 0 點")
        self._lbl_pts.setObjectName("lbl_progress")
        info_layout.addWidget(self._lbl_pts)

        layout.addWidget(info_bar)

        # ── pyqtgraph 波形圖 ──────────────────────────────────────────────────
        self._graphics_layout = pg.GraphicsLayoutWidget()
        self._graphics_layout.setBackground("#1E1E1E")
        layout.addWidget(self._graphics_layout, stretch=1)

    def _setup_plot(self):
        """建立波形圖"""
        self._plot = self._graphics_layout.addPlot(row=0, col=0)
        self._plot.setLabel("left", "電壓 (V)")
        self._plot.setLabel("bottom", "樣本點（最近）")
        self._plot.showGrid(x=True, y=True, alpha=0.3)
        self._plot.getViewBox().setMouseEnabled(x=True, y=False)
        self._plot.setYRange(-0.5, 6.0)

        # 波形曲線（初始空資料）
        self._curve = self._plot.plot(
            pen=pg.mkPen("#AAAAAA", width=1.5),
            name="—"
        )

        # 閾值線（初始隱藏）
        self._vh_line = pg.InfiniteLine(
            pos=2.0, angle=0,
            pen=pg.mkPen("#FFFFFF", width=1, style=Qt.DashLine),
            label="VH_min",
            labelOpts={"color": "#FFFFFF", "position": 0.95}
        )
        self._vl_line = pg.InfiniteLine(
            pos=0.8, angle=0,
            pen=pg.mkPen("#888888", width=1, style=Qt.DashLine),
            label="VL_max",
            labelOpts={"color": "#888888", "position": 0.95}
        )
        self._plot.addItem(self._vh_line)
        self._plot.addItem(self._vl_line)
        self._vh_line.setVisible(False)
        self._vl_line.setVisible(False)

    # ─── 公開介面 ──────────────────────────────────────────────────────────────

    def set_channel(
        self,
        ch_idx: int,
        ch_name: str,
        y_range: tuple,
        vh_min: float = None,
        vl_max: float = None,
        color: str = None
    ):
        """
        切換到新通道：清空緩衝區、更新標題與閾值線

        Args:
            ch_idx:  通道索引（0~4）
            ch_name: 通道名稱（如 "Hall U"）
            y_range: Y 軸範圍 tuple (min, max)
            vh_min:  H 準位最低電壓（None = 不顯示閾值線）
            vl_max:  L 準位最高電壓（None = 不顯示閾值線）
            color:   波形顏色（None = 依通道索引自動選色）
        """
        self._current_ch_idx  = ch_idx
        self._current_ch_name = ch_name
        self._current_y_range = y_range
        self._current_vh_min  = vh_min
        self._current_vl_max  = vl_max

        # 清空緩衝區
        self._buffer.clear()

        # 更新通道名稱標籤
        self._lbl_ch_name.setText(f"📡  {ch_name}")

        # 更新波形顏色
        pen_color = color or CH_COLORS.get(ch_idx, "#AAAAAA")
        self._curve.setPen(pg.mkPen(pen_color, width=1.5))

        # 更新 Y 軸範圍
        self._plot.setYRange(y_range[0], y_range[1])

        # 更新圖表標題
        self._plot.setTitle(
            f"<span style='color:#4AABFF; font-size:13px;'>{ch_name}</span>"
            f"  <span style='color:#888888; font-size:11px;'>高取樣率即時波形 ({self._sample_rate:,} Hz)</span>"
        )

        # 更新閾值線
        if vh_min is not None:
            self._vh_line.setPos(vh_min)
            self._vh_line.label.setFormat(f"VH_min={vh_min}V")
            self._vh_line.setVisible(True)
        else:
            self._vh_line.setVisible(False)

        if vl_max is not None:
            self._vl_line.setPos(vl_max)
            self._vl_line.label.setFormat(f"VL_max={vl_max}V")
            self._vl_line.setVisible(True)
        else:
            self._vl_line.setVisible(False)

        # 清空波形
        self._curve.setData([], [])
        self._lbl_pts.setText("已採: 0 點")

    def append_chunk(self, chunk: np.ndarray):
        """
        追加一段 chunk 資料並更新波形顯示

        200kHz 下每段 chunk 為 20,000 點（0.1s），display_window 為 100,000 點（0.5s）。
        直接繪製 100,000 點會使 pyqtgraph 卡頓，因此自動 decimation 至 PLOT_MAX_POINTS。

        Args:
            chunk: np.ndarray，長度 = chunk_size（20,000 點 @ 200kHz）
        """
        self._buffer.extend(chunk.tolist())

        buf_arr = np.array(self._buffer, dtype=np.float32)
        n = len(buf_arr)

        # ── 繪圖降採樣（decimation）────────────────────────────────────────
        # 當緩衝點數超過 PLOT_MAX_POINTS 時，等間距抽稀後再繪圖
        if n > self.PLOT_MAX_POINTS:
            step = max(1, n // self.PLOT_MAX_POINTS)
            plot_arr = buf_arr[::step]
            plot_x   = np.arange(0, n, step, dtype=np.int32)[:len(plot_arr)]
        else:
            plot_arr = buf_arr
            plot_x   = np.arange(n, dtype=np.int32)

        self._curve.setData(plot_x, plot_arr)

        # 自動滾動到最右側（以原始點數為 X 軸單位）
        self._plot.setXRange(max(0, n - self._display_window), n, padding=0.02)

        # 更新已採點數
        self._lbl_pts.setText(f"已採: {n:,} 點")

    def set_progress(
        self,
        round_idx: int,
        elapsed_s: float,
        remaining_s: float,
        total_rounds: int = 2
    ):
        """
        更新進度顯示

        Args:
            round_idx:    當前輪次索引（0-based）
            elapsed_s:    當前 CH 已採秒數
            remaining_s:  當前 CH 剩餘秒數
            total_rounds: 總輪數
        """
        self._lbl_round.setText(
            f"第 {round_idx + 1} / {total_rounds} 輪"
        )
        self._lbl_countdown.setText(
            f"⏱ {remaining_s:.1f}s"
        )

    def clear(self):
        """清空波形與狀態（診斷結束後呼叫）"""
        self._buffer.clear()
        self._curve.setData([], [])
        self._lbl_ch_name.setText("— 診斷已完成 —")
        self._lbl_round.setText("")
        self._lbl_countdown.setText("")
        self._lbl_pts.setText("")
        self._vh_line.setVisible(False)
        self._vl_line.setVisible(False)
        self._plot.setTitle("")

    def reset_idle(self):
        """重設為等待狀態"""
        self._buffer.clear()
        self._curve.setData([], [])
        self._lbl_ch_name.setText("— 等待診斷開始 —")
        self._lbl_round.setText("")
        self._lbl_countdown.setText("")
        self._lbl_pts.setText("")
        self._vh_line.setVisible(False)
        self._vl_line.setVisible(False)
        self._plot.setTitle("高取樣率診斷波形")
        self._plot.setYRange(-0.5, 6.0)

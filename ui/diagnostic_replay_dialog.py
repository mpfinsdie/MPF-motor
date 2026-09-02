"""
診斷波形回放對話框

載入高取樣率診斷 .npz 檔案（diag_type='sequential_ch'），
以靜態方式顯示各通道各輪次的完整波形。

功能：
  - 左側選擇器：選擇通道（CH0~CH4）與輪次（Round 0~1）
  - 右側大圖：顯示選定 CH × 輪次的完整波形
  - 支援時間軸滑動、顯示閾值線
  - 顯示取樣率、點數、時長等 metadata
"""

import os
from pathlib import Path
from typing import Dict, Any, Optional, List

import numpy as np
import pyqtgraph as pg
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSlider, QGroupBox, QWidget, QSizePolicy, QMessageBox,
    QSpinBox, QFrame, QListWidget, QListWidgetItem, QSplitter
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QColor

from config.thresholds import HALL_THRESHOLDS, ENCODER_THRESHOLDS
from logic.diagnostic_scanner import DiagnosticScanner


DIAG_REPLAY_STYLE = """
    QDialog {
        background-color: #1A1A1A;
        color: #CCCCCC;
    }
    QLabel {
        color: #CCCCCC;
        font-size: 12px;
    }
    QLabel#lbl_title {
        color: #4AABFF;
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
    QListWidget {
        background-color: #1E1E1E;
        color: #CCCCCC;
        border: 1px solid #444444;
        border-radius: 4px;
        font-size: 12px;
    }
    QListWidget::item {
        padding: 6px 8px;
    }
    QListWidget::item:selected {
        background-color: #2D5A8E;
        color: #FFFFFF;
    }
    QListWidget::item:hover {
        background-color: #2A2A3A;
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
"""

# 通道顏色
CH_COLORS = {
    0: "#FF4444",   # Hall U
    1: "#44FF44",   # Hall V
    2: "#4488FF",   # Hall W
    3: "#FFAA00",   # Enc A
    4: "#AA44FF",   # Enc B
}

DEFAULT_WINDOW_SIZE = 200_000  # 顯示最近 1 秒（200kHz × 1s）


class DiagnosticReplayDialog(QDialog):
    """
    診斷波形回放對話框

    支援格式：diag_type='sequential_ch' 的 .npz 檔案
    """

    def __init__(
        self,
        waveform_path: str,
        session_info: Optional[Dict[str, Any]] = None,
        parent=None
    ):
        super().__init__(parent)
        self._waveform_path = waveform_path
        self._session_info  = session_info or {}
        self._diag_data: Optional[Dict] = None

        # 當前選擇
        self._current_ch_idx    = 0
        self._current_round_idx = 0
        self._current_pos       = 0
        self._window_size       = DEFAULT_WINDOW_SIZE
        self._show_all_mode     = False   # 是否處於「顯示全部」模式

        # 播放
        self._play_timer = QTimer(self)
        self._play_timer.setInterval(100)
        self._play_timer.timeout.connect(self._on_play_tick)
        self._is_playing = False

        self.setWindowTitle("診斷波形回放 — 高取樣率診斷")
        self.setMinimumSize(1200, 700)
        self.setStyleSheet(DIAG_REPLAY_STYLE)

        self._setup_ui()
        self._load_data()

    # ─── UI 建立 ───────────────────────────────────────────────────────────────

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        # 標題
        layout.addWidget(self._build_header())

        # 主體：左側選擇器 + 右側波形圖
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(4)

        splitter.addWidget(self._build_selector_panel())
        splitter.addWidget(self._build_plot_area())
        splitter.setSizes([200, 1000])

        layout.addWidget(splitter, stretch=1)

        # 播放控制
        layout.addWidget(self._build_playback_controls())

        # 底部
        layout.addWidget(self._build_bottom_bar())

    def _build_header(self) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(16)

        title = QLabel("🔬  診斷波形回放")
        title.setObjectName("lbl_title")
        h.addWidget(title)

        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("background-color: #444444;")
        sep.setFixedWidth(1)
        h.addWidget(sep)

        info = self._session_info
        session_id = info.get("id", "---")
        started    = info.get("started_at", "---")
        duration   = info.get("duration_s")
        dur_str    = f"{duration:.0f}s" if duration else "---"

        info_lbl = QLabel(
            f"場次 #{session_id}  |  開始: {started}  |  時長: {dur_str}"
        )
        info_lbl.setObjectName("lbl_info")
        h.addWidget(info_lbl)
        h.addStretch()

        path_lbl = QLabel(f"📁 {Path(self._waveform_path).name}")
        path_lbl.setObjectName("lbl_info")
        path_lbl.setToolTip(self._waveform_path)
        h.addWidget(path_lbl)

        return w

    def _build_selector_panel(self) -> QGroupBox:
        """左側：通道 × 輪次選擇器"""
        group = QGroupBox("選擇通道 / 輪次")
        layout = QVBoxLayout(group)
        layout.setSpacing(6)

        layout.addWidget(QLabel("通道："))
        self._ch_list = QListWidget()
        self._ch_list.setMaximumHeight(180)
        self._ch_list.currentRowChanged.connect(self._on_ch_selected)
        layout.addWidget(self._ch_list)

        layout.addWidget(QLabel("輪次："))
        self._round_list = QListWidget()
        self._round_list.setMaximumHeight(100)
        self._round_list.currentRowChanged.connect(self._on_round_selected)
        layout.addWidget(self._round_list)

        layout.addStretch()

        # metadata 顯示
        self._meta_lbl = QLabel("")
        self._meta_lbl.setObjectName("lbl_info")
        self._meta_lbl.setWordWrap(True)
        layout.addWidget(self._meta_lbl)

        return group

    def _build_plot_area(self) -> QWidget:
        """右側：波形圖"""
        self._graphics_layout = pg.GraphicsLayoutWidget()
        self._graphics_layout.setBackground("#1E1E1E")

        self._plot = self._graphics_layout.addPlot(row=0, col=0)
        self._plot.setLabel("left", "電壓 (V)")
        self._plot.setLabel("bottom", "樣本點")
        self._plot.showGrid(x=True, y=True, alpha=0.3)
        self._plot.addLegend(offset=(10, 10))
        self._plot.getViewBox().setMouseEnabled(x=True, y=False)

        # 監聽使用者用滾輪/拖曳改變 X 軸範圍，同步更新 _current_pos 並離開全部顯示模式
        self._plot.getViewBox().sigXRangeChanged.connect(self._on_xrange_changed)
        self._xrange_updating = False   # 防止 _refresh_plot 觸發的 setXRange 造成遞迴

        # 波形曲線（初始空）
        self._curve = self._plot.plot(
            pen=pg.mkPen("#AAAAAA", width=1),
            name="—"
        )

        # 閾值線
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

        return self._graphics_layout

    def _build_playback_controls(self) -> QGroupBox:
        group = QGroupBox("播放控制")
        layout = QVBoxLayout(group)
        layout.setSpacing(6)

        # 位置資訊列
        info_row = QHBoxLayout()
        self._pos_lbl = QLabel("位置: 0 / 0")
        self._pos_lbl.setStyleSheet("color: #FFFF44; font-family: Consolas; font-size: 12px;")
        info_row.addWidget(self._pos_lbl)
        info_row.addStretch()
        self._time_lbl = QLabel("時間: 0.000 s")
        self._time_lbl.setStyleSheet("color: #AAAAFF; font-family: Consolas; font-size: 12px;")
        info_row.addWidget(self._time_lbl)
        self._total_lbl = QLabel("總點數: ---")
        self._total_lbl.setStyleSheet("color: #AAAAAA; font-size: 11px;")
        info_row.addWidget(self._total_lbl)
        layout.addLayout(info_row)

        # 滑桿
        slider_row = QHBoxLayout()
        slider_row.addWidget(QLabel("◀"))
        self._slider = QSlider(Qt.Horizontal)
        self._slider.setMinimum(0)
        self._slider.setMaximum(0)
        self._slider.setValue(0)
        self._slider.valueChanged.connect(self._on_slider_changed)
        slider_row.addWidget(self._slider, stretch=1)
        slider_row.addWidget(QLabel("▶"))
        layout.addLayout(slider_row)

        # 按鈕列
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        btn_begin = QPushButton("⏮ 開頭")
        btn_begin.clicked.connect(lambda: self._go_to(0))
        btn_row.addWidget(btn_begin)

        btn_prev = QPushButton("◀ 後退")
        btn_prev.clicked.connect(self._on_step_back)
        btn_row.addWidget(btn_prev)

        self._btn_play = QPushButton("▶ 播放")
        self._btn_play.setCheckable(True)
        self._btn_play.clicked.connect(self._on_toggle_play)
        btn_row.addWidget(self._btn_play)

        btn_next = QPushButton("前進 ▶")
        btn_next.clicked.connect(self._on_step_forward)
        btn_row.addWidget(btn_next)

        btn_end = QPushButton("結尾 ⏭")
        btn_end.clicked.connect(self._on_go_end)
        btn_row.addWidget(btn_end)

        btn_row.addStretch()

        btn_all = QPushButton("📊 顯示全部")
        btn_all.clicked.connect(self._show_all)
        btn_row.addWidget(btn_all)

        btn_row.addWidget(QLabel("視窗大小:"))
        self._window_spin = QSpinBox()
        # 200kHz × 0.05s = 10,000 點（最小）；200kHz × 10s = 2,000,000 點（最大）
        self._window_spin.setRange(10_000, 2_000_000)
        self._window_spin.setValue(DEFAULT_WINDOW_SIZE)
        self._window_spin.setSingleStep(20_000)   # 每步 0.1s @ 200kHz
        self._window_spin.setSuffix(" 點")
        self._window_spin.setFixedWidth(120)
        self._window_spin.valueChanged.connect(self._on_window_size_changed)
        btn_row.addWidget(self._window_spin)

        btn_row.addWidget(QLabel("速度:"))
        self._speed_spin = QSpinBox()
        # 200kHz 下每次移動 20,000 點 = 0.1s；最大 200,000 點 = 1s
        self._speed_spin.setRange(1_000, 200_000)
        self._speed_spin.setValue(20_000)
        self._speed_spin.setSingleStep(10_000)
        self._speed_spin.setSuffix(" 點/次")
        self._speed_spin.setFixedWidth(120)
        btn_row.addWidget(self._speed_spin)

        layout.addLayout(btn_row)
        return group

    def _build_bottom_bar(self) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)

        self._sample_info_lbl = QLabel("")
        self._sample_info_lbl.setObjectName("lbl_info")
        h.addWidget(self._sample_info_lbl)
        h.addStretch()

        btn_close = QPushButton("關閉")
        btn_close.clicked.connect(self.accept)
        h.addWidget(btn_close)

        return w

    # ─── 資料載入 ──────────────────────────────────────────────────────────────

    def _load_data(self):
        """載入診斷 npz 並初始化選擇器"""
        if not os.path.isfile(self._waveform_path):
            QMessageBox.critical(self, "錯誤", f"診斷波形檔案不存在：\n{self._waveform_path}")
            return

        try:
            self._diag_data = DiagnosticScanner.load(self._waveform_path)
        except Exception as e:
            QMessageBox.critical(self, "錯誤", f"載入診斷波形失敗：\n{e}")
            return

        d = self._diag_data
        sr   = d["sample_rate"]
        spch = d["seconds_per_ch"]
        rds  = d["rounds"]
        chs  = d["ch_count"]

        # 更新 metadata 標籤
        self._meta_lbl.setText(
            f"取樣率: {sr:,} Hz\n"
            f"每 CH: {spch} 秒\n"
            f"輪數: {rds}\n"
            f"通道數: {chs}\n"
            f"每 CH 點數: {sr * spch:,}"
        )

        # 填入通道清單
        self._ch_list.clear()
        for i, name in enumerate(d["channel_names"]):
            item = QListWidgetItem(f"CH{d['channel_nums'][i]}  {name}")
            item.setForeground(QColor(CH_COLORS.get(int(d["channel_nums"][i]), "#AAAAAA")))
            self._ch_list.addItem(item)

        # 填入輪次清單
        self._round_list.clear()
        for r in range(rds):
            self._round_list.addItem(f"第 {r + 1} 輪")

        # 預設選第一個
        self._ch_list.setCurrentRow(0)
        self._round_list.setCurrentRow(0)

    # ─── 波形更新 ──────────────────────────────────────────────────────────────

    def _refresh_plot(self):
        """根據當前選擇更新波形顯示"""
        if self._diag_data is None:
            return

        key  = f"ch{self._current_ch_idx}_round{self._current_round_idx}"
        data = self._diag_data["data"].get(key)

        if data is None or len(data) == 0:
            self._curve.setData([], [])
            self._pos_lbl.setText("無資料")
            return

        n = len(data)

        # 防止 setXRange 觸發 sigXRangeChanged 造成遞迴
        self._xrange_updating = True
        try:
            if self._show_all_mode:
                # 全部顯示模式：畫出完整波形
                x = np.arange(n)
                self._curve.setData(x, data)
                self._plot.setXRange(0, n, padding=0.02)
                self._pos_lbl.setText(f"位置: 0 ~ {n:,} / {n:,}（全部）")
                self._time_lbl.setText("時間: 0.000 s")
                self._slider.blockSignals(True)
                self._slider.setValue(0)
                self._slider.blockSignals(False)
            else:
                # 視窗模式：只顯示 window_size 範圍
                pos = self._current_pos
                end = min(pos + self._window_size, n)
                x   = np.arange(pos, end)

                self._curve.setData(x, data[pos:end])
                self._plot.setXRange(pos, end, padding=0.02)

                # 更新位置標籤
                self._pos_lbl.setText(f"位置: {pos:,} ~ {end:,} / {n:,}")

                # 更新時間標籤（基於取樣率）
                sr = self._diag_data["sample_rate"]
                t_s = pos / sr
                self._time_lbl.setText(f"時間: {t_s:.3f} s")

                # 同步滑桿
                self._slider.blockSignals(True)
                self._slider.setValue(pos)
                self._slider.blockSignals(False)
        finally:
            self._xrange_updating = False

    def _update_channel_display(self):
        """切換通道時更新圖表設定（顏色、閾值線、Y 軸），並重繪波形"""
        if self._diag_data is None:
            return

        ch_idx   = self._current_ch_idx
        ch_names = self._diag_data["channel_names"]
        ch_nums  = self._diag_data["channel_nums"]

        if ch_idx >= len(ch_names):
            return

        ch_name = str(ch_names[ch_idx])
        ch_num  = int(ch_nums[ch_idx])

        # 更新顏色與圖例名稱
        color = CH_COLORS.get(ch_num, "#AAAAAA")
        self._curve.setPen(pg.mkPen(color, width=1))
        # PlotDataItem 無 setName()，透過 opts 更新後重設 legend
        self._curve.opts["name"] = ch_name
        legend = self._plot.legend
        if legend is not None:
            legend.removeItem(self._curve)
            legend.addItem(self._curve, ch_name)

        # 更新 Y 軸與閾值線
        if ch_num < 3:  # Hall
            self._plot.setYRange(-0.2, 3.8)
            vh = HALL_THRESHOLDS["vh_min"]
            vl = HALL_THRESHOLDS["vl_max"]
        else:           # Encoder
            self._plot.setYRange(-0.5, 6.0)
            vh = ENCODER_THRESHOLDS["vh_min"]
            vl = ENCODER_THRESHOLDS["vl_max"]

        self._vh_line.setPos(vh)
        self._vh_line.label.setFormat(f"VH_min={vh}V")
        self._vh_line.setVisible(True)
        self._vl_line.setPos(vl)
        self._vl_line.label.setFormat(f"VL_max={vl}V")
        self._vl_line.setVisible(True)

        # 更新圖表標題
        self._plot.setTitle(
            f"<span style='color:{color}; font-size:13px;'>{ch_name}</span>"
            f"  <span style='color:#888888; font-size:11px;'>"
            f"第 {self._current_round_idx + 1} 輪  |  "
            f"{self._diag_data['sample_rate']:,} Hz</span>"
        )

        # 取得新通道資料長度
        key  = f"ch{ch_idx}_round{self._current_round_idx}"
        data = self._diag_data["data"].get(key)
        n    = len(data) if data is not None else 0

        self._total_lbl.setText(f"總點數: {n:,}")
        self._sample_info_lbl.setText(
            f"{ch_name}  第 {self._current_round_idx + 1} 輪  |  "
            f"{n:,} 點  |  "
            f"{n / self._diag_data['sample_rate']:.2f} 秒  |  "
            f"取樣率 {self._diag_data['sample_rate']:,} Hz"
        )

        # 更新滑桿範圍，保留目前位置（clamp 到合法範圍）
        max_pos = max(0, n - self._window_size)
        self._current_pos = min(self._current_pos, max_pos)

        self._slider.blockSignals(True)
        self._slider.setMaximum(max_pos)
        self._slider.setValue(self._current_pos)
        self._slider.blockSignals(False)

        # 直接重繪波形（_show_all_mode 狀態由 _refresh_plot 自行判斷）
        self._refresh_plot()

    def _show_all(self):
        """顯示完整波形，並進入「全部顯示」模式"""
        if self._diag_data is None:
            return
        self._show_all_mode = True   # 設定旗標，切換 channel 後仍維持全部顯示
        self._refresh_plot()

    # ─── 事件處理 ──────────────────────────────────────────────────────────────

    def _on_ch_selected(self, row: int):
        if row < 0:
            return
        self._current_ch_idx = row
        # 不重設 _current_pos，保留目前觀看位置
        self._update_channel_display()

    def _on_round_selected(self, row: int):
        if row < 0:
            return
        self._current_round_idx = row
        # 不重設 _current_pos，保留目前觀看位置
        self._update_channel_display()

    def _on_xrange_changed(self, view_box, x_range):
        """使用者用滾輪或拖曳改變 X 軸範圍時，同步 _current_pos/_window_size 並離開全部顯示模式"""
        if self._xrange_updating:
            return   # 由 _refresh_plot 觸發的 setXRange，忽略
        if self._diag_data is None:
            return

        x_min, x_max = x_range
        new_pos      = max(0, int(x_min))
        # 同步視窗大小為目前視圖寬度，clamp 到 SpinBox 合法範圍
        new_win_size = max(
            self._window_spin.minimum(),
            min(self._window_spin.maximum(), int(x_max - x_min))
        )

        key  = f"ch{self._current_ch_idx}_round{self._current_round_idx}"
        data = self._diag_data["data"].get(key)
        n    = len(data) if data is not None else 0

        self._show_all_mode = False   # 使用者手動縮放，離開全部顯示模式
        self._window_size   = new_win_size
        self._current_pos   = min(new_pos, max(0, n - new_win_size))

        # 同步 SpinBox（不觸發 _on_window_size_changed）
        self._window_spin.blockSignals(True)
        self._window_spin.setValue(new_win_size)
        self._window_spin.blockSignals(False)

        # 同步滑桿（不觸發 _on_slider_changed）
        max_pos = max(0, n - new_win_size)
        self._slider.blockSignals(True)
        self._slider.setMaximum(max_pos)
        self._slider.setValue(self._current_pos)
        self._slider.blockSignals(False)

        # 更新位置標籤
        if n > 0:
            end = min(self._current_pos + new_win_size, n)
            self._pos_lbl.setText(f"位置: {self._current_pos:,} ~ {end:,} / {n:,}")
            sr = self._diag_data["sample_rate"]
            self._time_lbl.setText(f"時間: {self._current_pos / sr:.3f} s")

    def _on_slider_changed(self, value: int):
        self._show_all_mode = False   # 拖動滑桿時離開全部顯示模式
        self._current_pos = value
        self._refresh_plot()

    def _on_toggle_play(self, checked: bool):
        if checked:
            self._btn_play.setText("⏸ 暫停")
            self._is_playing = True
            self._play_timer.start()
        else:
            self._btn_play.setText("▶ 播放")
            self._is_playing = False
            self._play_timer.stop()

    def _on_play_tick(self):
        if self._diag_data is None:
            return
        key  = f"ch{self._current_ch_idx}_round{self._current_round_idx}"
        data = self._diag_data["data"].get(key)
        if data is None:
            return
        n       = len(data)
        step    = self._speed_spin.value()
        new_pos = self._current_pos + step
        if new_pos >= n - self._window_size:
            new_pos = max(0, n - self._window_size)
            self._btn_play.setChecked(False)
            self._on_toggle_play(False)
        self._current_pos = new_pos
        self._refresh_plot()

    def _on_step_forward(self):
        if self._diag_data is None:
            return
        key  = f"ch{self._current_ch_idx}_round{self._current_round_idx}"
        data = self._diag_data["data"].get(key)
        if data is None:
            return
        n    = len(data)
        step = self._speed_spin.value()
        self._show_all_mode = False   # 前進時離開全部顯示模式
        self._current_pos = min(self._current_pos + step, max(0, n - self._window_size))
        self._refresh_plot()

    def _on_step_back(self):
        self._show_all_mode = False   # 後退時離開全部顯示模式
        step = self._speed_spin.value()
        self._current_pos = max(0, self._current_pos - step)
        self._refresh_plot()

    def _go_to(self, pos: int):
        self._show_all_mode = False   # 跳至指定位置時離開全部顯示模式
        self._current_pos = pos
        self._refresh_plot()

    def _on_go_end(self):
        if self._diag_data is None:
            return
        key  = f"ch{self._current_ch_idx}_round{self._current_round_idx}"
        data = self._diag_data["data"].get(key)
        if data is None:
            return
        n = len(data)
        self._show_all_mode = False   # 跳至結尾時離開全部顯示模式
        self._current_pos = max(0, n - self._window_size)
        self._refresh_plot()

    def _on_window_size_changed(self, value: int):
        self._window_size = value
        if self._diag_data:
            key  = f"ch{self._current_ch_idx}_round{self._current_round_idx}"
            data = self._diag_data["data"].get(key)
            if data is not None:
                n       = len(data)
                max_pos = max(0, n - self._window_size)
                self._slider.setMaximum(max_pos)
                self._current_pos = min(self._current_pos, max_pos)
        self._refresh_plot()

    # ─── 視窗關閉 ──────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        self._play_timer.stop()
        super().closeEvent(event)

    def reject(self):
        self._play_timer.stop()
        super().reject()

    def accept(self):
        self._play_timer.stop()
        super().accept()

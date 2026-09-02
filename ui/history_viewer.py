"""
歷史記錄查詢視窗
顯示所有測試場次的統計摘要，支援篩選與匯出
診斷場次若有診斷波形，可點擊「🔬 回看診斷」開啟診斷回放對話框
"""

import os
import time
import csv
import json
from pathlib import Path
from typing import List, Dict, Any

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QLabel, QLineEdit, QPushButton, QHeaderView, QAbstractItemView,
    QGroupBox, QFormLayout, QMessageBox, QFileDialog, QFrame,
    QSplitter, QTextEdit, QWidget, QSizePolicy, QDialogButtonBox
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QColor, QBrush

from db.database import DatabaseManager
from ui.diagnostic_replay_dialog import DiagnosticReplayDialog
from logic.diagnostic_scanner import DiagnosticScanner


VIEWER_STYLE = """
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
    QLabel#lbl_stats {
        color: #AAAAAA;
        font-size: 11px;
    }
    QLineEdit {
        background-color: #2A2A2A;
        color: #FFFFFF;
        border: 1px solid #555555;
        border-radius: 4px;
        padding: 4px 8px;
        font-size: 12px;
    }
    QLineEdit:focus {
        border: 1px solid #4AABFF;
    }
    QTableWidget {
        background-color: #1E1E1E;
        color: #CCCCCC;
        border: 1px solid #444444;
        gridline-color: #333333;
        font-size: 12px;
        selection-background-color: #2D5A8E;
    }
    QTableWidget::item {
        padding: 4px 6px;
    }
    QHeaderView::section {
        background-color: #2D3A4A;
        color: #AAAAFF;
        border: none;
        border-right: 1px solid #444444;
        border-bottom: 1px solid #444444;
        padding: 5px 6px;
        font-size: 11px;
        font-weight: bold;
    }
    QPushButton {
        background-color: #2D5A8E;
        color: #FFFFFF;
        border: none;
        border-radius: 4px;
        padding: 6px 14px;
        font-size: 12px;
        font-weight: bold;
        min-width: 80px;
    }
    QPushButton:hover {
        background-color: #3A72B0;
    }
    QPushButton#btn_refresh {
        background-color: #2D5A5A;
    }
    QPushButton#btn_export {
        background-color: #2D7A3A;
    }
    QPushButton#btn_export:hover {
        background-color: #3A9A4A;
    }
    QPushButton#btn_edit {
        background-color: #5A5A2D;
    }
    QPushButton#btn_edit:hover {
        background-color: #7A7A3A;
    }
    QPushButton#btn_delete {
        background-color: #7A2D2D;
    }
    QPushButton#btn_delete:hover {
        background-color: #9A3A3A;
    }
    QTextEdit {
        background-color: #1A1A2A;
        color: #CCCCCC;
        border: 1px solid #444444;
        border-radius: 4px;
        font-size: 12px;
        font-family: "Consolas", monospace;
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
    QFrame#separator {
        background-color: #444444;
    }
"""

# 欄位定義：(欄位名稱, DB key, 寬度, 對齊)
COLUMNS = [
    ("ID",        "id",            45,  Qt.AlignCenter),
    ("類型",       "session_type",  70,  Qt.AlignCenter),
    ("開始時間",   "started_at",   145,  Qt.AlignLeft),
    ("馬達序號",   "serial_no",    140,  Qt.AlignLeft),
    ("操作員",     "operator",      90,  Qt.AlignCenter),
    ("時長(秒)",   "duration_s",    70,  Qt.AlignCenter),
    ("整體結果",   "overall_pass",  90,  Qt.AlignCenter),
    ("診斷波形",   "waveform_path", 70,  Qt.AlignCenter),
]


class HistoryViewer(QDialog):
    """
    歷史測試記錄查詢視窗
    """

    def __init__(self, db_manager: DatabaseManager, parent=None):
        super().__init__(parent)
        self._db = db_manager
        self._records: List[Dict[str, Any]] = []

        self.setWindowTitle("歷史測試記錄")
        self.setMinimumSize(1000, 620)
        self.setStyleSheet(VIEWER_STYLE)

        self._setup_ui()
        self._load_data()

    # ─── UI 建立 ───────────────────────────────────────────────────────────────

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        # 標題列
        layout.addWidget(self._build_header())

        # 篩選列
        layout.addWidget(self._build_filter_bar())

        # 主體：表格 + 詳細資訊
        splitter = QSplitter(Qt.Vertical)
        splitter.setHandleWidth(4)

        self._table = self._build_table()
        splitter.addWidget(self._table)

        self._detail_box = self._build_detail_box()
        splitter.addWidget(self._detail_box)
        splitter.setSizes([420, 160])

        layout.addWidget(splitter)

        # 底部按鈕列
        layout.addWidget(self._build_bottom_bar())

    def _build_header(self) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)

        title = QLabel("📋  歷史測試記錄")
        title.setObjectName("lbl_title")
        h.addWidget(title)

        h.addStretch()

        self._stats_lbl = QLabel("")
        self._stats_lbl.setObjectName("lbl_stats")
        h.addWidget(self._stats_lbl)

        return w

    def _build_filter_bar(self) -> QGroupBox:
        group = QGroupBox("篩選")
        h = QHBoxLayout(group)
        h.setSpacing(10)

        h.addWidget(QLabel("序號搜尋："))
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("輸入序號關鍵字（空白=全部）")
        self._search_edit.setMaximumWidth(220)
        self._search_edit.returnPressed.connect(self._load_data)
        h.addWidget(self._search_edit)

        btn_search = QPushButton("🔍 搜尋")
        btn_search.setObjectName("btn_refresh")
        btn_search.clicked.connect(self._load_data)
        h.addWidget(btn_search)

        btn_refresh = QPushButton("↺ 重新整理")
        btn_refresh.setObjectName("btn_refresh")
        btn_refresh.clicked.connect(self._on_refresh)
        h.addWidget(btn_refresh)

        h.addStretch()
        return group

    def _build_table(self) -> QTableWidget:
        table = QTableWidget()
        table.setColumnCount(len(COLUMNS))
        table.setHorizontalHeaderLabels([c[0] for c in COLUMNS])
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.setSortingEnabled(True)

        # 欄寬
        for col_idx, (_, _, width, _) in enumerate(COLUMNS):
            table.setColumnWidth(col_idx, width)
        table.horizontalHeader().setStretchLastSection(True)

        table.itemSelectionChanged.connect(self._on_row_selected)
        return table

    def _build_detail_box(self) -> QGroupBox:
        group = QGroupBox("詳細資訊")
        layout = QVBoxLayout(group)
        self._detail_text = QTextEdit()
        self._detail_text.setReadOnly(True)
        self._detail_text.setMaximumHeight(150)
        self._detail_text.setPlaceholderText("點選上方記錄以查看詳細資訊...")
        layout.addWidget(self._detail_text)
        return group

    def _build_bottom_bar(self) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        btn_export = QPushButton("💾 匯出 CSV")
        btn_export.setObjectName("btn_export")
        btn_export.clicked.connect(self._on_export_csv)
        h.addWidget(btn_export)

        btn_edit = QPushButton("✏ 編輯資訊")
        btn_edit.setObjectName("btn_edit")
        btn_edit.clicked.connect(self._on_edit)
        h.addWidget(btn_edit)

        btn_delete = QPushButton("🗑 刪除選取")
        btn_delete.setObjectName("btn_delete")
        btn_delete.clicked.connect(self._on_delete)
        h.addWidget(btn_delete)

        # 回看診斷按鈕（診斷場次且有診斷 npz 時啟用）
        self._btn_diag_waveform = QPushButton("🔬 回看診斷")
        self._btn_diag_waveform.setObjectName("btn_diag_waveform")
        self._btn_diag_waveform.setEnabled(False)
        self._btn_diag_waveform.setToolTip("選取診斷場次且有診斷波形時可用")
        self._btn_diag_waveform.clicked.connect(self._on_view_diag_waveform)
        self._btn_diag_waveform.setStyleSheet(
            "QPushButton#btn_diag_waveform { background-color: #2D4A7A; }"
            "QPushButton#btn_diag_waveform:hover { background-color: #3A6AAA; }"
            "QPushButton#btn_diag_waveform:disabled { background-color: #3A3A3A; color: #666666; }"
        )
        h.addWidget(self._btn_diag_waveform)

        h.addStretch()

        btn_close = QPushButton("關閉")
        btn_close.clicked.connect(self.accept)
        h.addWidget(btn_close)

        return w

    # ─── 資料載入 ──────────────────────────────────────────────────────────────

    def _load_data(self):
        """從 DB 載入資料並填入表格"""
        serial_filter = self._search_edit.text().strip() if hasattr(self, "_search_edit") else ""
        try:
            self._records = self._db.query_sessions(limit=500, serial_filter=serial_filter)
        except Exception as e:
            QMessageBox.critical(self, "錯誤", f"讀取資料庫失敗：\n{e}")
            return

        self._populate_table()
        self._update_stats_label()

    def _populate_table(self):
        """填入表格資料"""
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(self._records))

        for row_idx, rec in enumerate(self._records):
            is_diag = (rec.get("session_type") == "diagnostic")

            for col_idx, (_, key, _, align) in enumerate(COLUMNS):
                value = rec.get(key)
                display = self._format_value(key, value)
                item = QTableWidgetItem(display)
                item.setTextAlignment(align | Qt.AlignVCenter)

                # 類型欄著色
                if key == "session_type":
                    if is_diag:
                        item.setForeground(QBrush(QColor("#4AABFF")))
                        item.setText("🔬 診斷")
                        item.setToolTip("高取樣率診斷場次")
                    else:
                        item.setForeground(QBrush(QColor("#AAAAAA")))
                        item.setText("📋 測試")
                        item.setToolTip("一般測試場次")

                # 整體結果著色
                elif key == "overall_pass":
                    if is_diag:
                        # 診斷場次：顯示 diag_pass 欄位
                        diag_pass = rec.get("diag_pass", -1)
                        if diag_pass == 1:
                            item.setForeground(QBrush(QColor("#44FF44")))
                            item.setText("✔ PASS")
                            item.setToolTip("高速診斷判定：PASS")
                        elif diag_pass == 0:
                            item.setForeground(QBrush(QColor("#FF4444")))
                            item.setText("✘ FAIL")
                            item.setToolTip("高速診斷判定：FAIL")
                        else:
                            item.setForeground(QBrush(QColor("#888888")))
                            item.setText("—")
                            item.setToolTip("尚未分析或診斷未完成")
                    elif value == 1:
                        item.setForeground(QBrush(QColor("#44FF44")))
                        item.setText("✔ PASS")
                    elif value == 0 and rec.get("hall_total") is not None:
                        item.setForeground(QBrush(QColor("#FF4444")))
                        item.setText("✘ FAIL")
                    else:
                        item.setForeground(QBrush(QColor("#888888")))
                        item.setText("---")

                # 診斷波形欄著色（僅診斷場次顯示有/無）
                elif key == "waveform_path":
                    wf = rec.get("waveform_path") or ""
                    if is_diag:
                        if wf and os.path.isfile(wf):
                            item.setForeground(QBrush(QColor("#4AABFF")))
                            item.setText("🔬 有")
                            item.setToolTip(wf)
                        elif wf:
                            item.setForeground(QBrush(QColor("#FF8844")))
                            item.setText("⚠ 遺失")
                            item.setToolTip(f"檔案不存在：{wf}")
                        else:
                            item.setForeground(QBrush(QColor("#555555")))
                            item.setText("—")
                    else:
                        item.setForeground(QBrush(QColor("#555555")))
                        item.setText("—")

                self._table.setItem(row_idx, col_idx, item)

        self._table.setSortingEnabled(True)

    def _format_value(self, key: str, value) -> str:
        """格式化顯示值"""
        if value is None:
            return "---"
        if key == "duration_s":
            return f"{float(value):.0f}" if value else "---"
        if key == "overall_pass":
            return "PASS" if value == 1 else ("FAIL" if value == 0 else "---")
        if key == "waveform_path":
            # 波形欄由 _populate_table 直接設定文字，此處回傳空字串作為初始值
            return ""
        return str(value) if value else ""

    def _update_stats_label(self):
        """更新頂部統計摘要標籤"""
        try:
            total  = len(self._records)
            # 診斷場次：diag_pass=1 為 PASS；一般測試場次：overall_pass=1 為 PASS
            passed = sum(
                1 for r in self._records
                if (r.get("session_type") == "diagnostic" and r.get("diag_pass") == 1)
                or (r.get("session_type") != "diagnostic" and r.get("overall_pass") == 1)
            )
            diag_count = sum(1 for r in self._records if r.get("session_type") == "diagnostic")
            self._stats_lbl.setText(
                f"共 {total} 筆  |  PASS: {passed} 筆  |  診斷場次: {diag_count} 筆"
            )
        except Exception:
            pass

    # ─── 事件處理 ──────────────────────────────────────────────────────────────

    def _on_refresh(self):
        self._search_edit.clear()
        self._load_data()

    def _on_row_selected(self):
        """點選列時顯示詳細資訊，並更新「回看診斷」按鈕狀態"""
        selected = self._table.selectedItems()
        if not selected:
            self._btn_diag_waveform.setEnabled(False)
            return

        row = self._table.currentRow()
        if row < 0 or row >= len(self._records):
            self._btn_diag_waveform.setEnabled(False)
            return

        rec = self._records[row]
        self._show_detail(rec)

        wf_path  = rec.get("waveform_path") or ""
        is_diag  = (rec.get("session_type") == "diagnostic")
        has_file = bool(wf_path) and os.path.isfile(wf_path)

        if is_diag:
            can_diag = has_file and DiagnosticScanner.is_diag_npz(wf_path)
            self._btn_diag_waveform.setEnabled(can_diag)
            if can_diag:
                self._btn_diag_waveform.setToolTip(f"點擊回看診斷波形：{wf_path}")
            else:
                self._btn_diag_waveform.setToolTip("無診斷波形數據或檔案遺失")
        else:
            self._btn_diag_waveform.setEnabled(False)
            self._btn_diag_waveform.setToolTip("此為一般測試場次，無診斷波形")

    def _show_detail(self, rec: Dict[str, Any]):
        """在詳細資訊框顯示單筆記錄"""
        is_diag  = (rec.get("session_type") == "diagnostic")
        duration = rec.get("duration_s")
        dur_str  = f"{duration:.0f} 秒 ({duration/60:.1f} 分鐘)" if duration else "---"

        # 波形資訊
        wf_path = rec.get("waveform_path") or ""
        if wf_path and os.path.isfile(wf_path):
            wf_str = f"🔬 有診斷波形（{Path(wf_path).name}）" if is_diag else f"📈 有波形數據（{Path(wf_path).name}）"
        elif wf_path:
            wf_str = f"⚠ 波形檔案遺失（{wf_path}）"
        else:
            wf_str = "— 無波形數據"

        if is_diag:
            # 診斷場次詳細資訊
            notes = rec.get("session_notes") or rec.get("notes") or ""

            # 診斷 PASS/FAIL
            diag_pass = rec.get("diag_pass", -1)
            if diag_pass == 1:
                diag_result_str = "✔ PASS（高速診斷通過）"
            elif diag_pass == 0:
                diag_result_str = "✘ FAIL（高速診斷未通過）"
            else:
                diag_result_str = "— 尚未分析"

            # 優先顯示完整診斷摘要（diag_summary），fallback 到舊格式 diag_ch_results
            diag_summary = rec.get("diag_summary") or ""
            if diag_summary:
                # 新格式：完整摘要文字（含比值交叉驗證、fail 原因）
                detail_block = f"\n─── 診斷分析報告 ───\n{diag_summary}"
            else:
                # 舊格式 fallback：逐通道簡表
                diag_ch_results = rec.get("diag_ch_results") or ""
                if diag_ch_results:
                    try:
                        ch_data = json.loads(diag_ch_results)
                        lines = []
                        for ch_name, info in ch_data.items():
                            ch_pass = "✔" if info.get("pass") else "✘"
                            freq    = info.get("avg_freq", 0)
                            lines.append(f"  {ch_pass} {ch_name:<12}  主頻: {freq:.1f} Hz")
                        detail_block = "\n各通道摘要（舊格式）：\n" + "\n".join(lines)
                    except (json.JSONDecodeError, Exception):
                        detail_block = ""
                else:
                    detail_block = "\n（無詳細分析資料）"

            text = (
                f"🔬 診斷場次 #{rec.get('id')}  |  序號: {rec.get('serial_no') or '(無)'}  "
                f"|  操作員: {rec.get('operator') or '(無)'}\n"
                f"開始: {rec.get('started_at', '---')}  |  "
                f"結束: {rec.get('ended_at', '---')}  |  時長: {dur_str}\n"
                f"診斷說明：{notes}\n"
                f"診斷結果：{diag_result_str}"
                f"{detail_block}\n"
                f"\n波形數據：{wf_str}"
            )
        else:
            # 一般測試場次詳細資訊（精簡版，無成功率/RPM）
            overall = "✔ PASS" if rec.get("overall_pass") == 1 else (
                      "✘ FAIL" if rec.get("hall_total") is not None else "---")
            text = (
                f"場次 #{rec.get('id')}  |  序號: {rec.get('serial_no') or '(無)'}  "
                f"|  操作員: {rec.get('operator') or '(無)'}\n"
                f"開始: {rec.get('started_at', '---')}  |  "
                f"結束: {rec.get('ended_at', '---')}  |  時長: {dur_str}\n"
                f"\n整體結果：{overall}"
            )
        self._detail_text.setPlainText(text)

    def _on_view_diag_waveform(self):
        """開啟診斷波形回放對話框"""
        row = self._table.currentRow()
        if row < 0 or row >= len(self._records):
            QMessageBox.information(self, "提示", "請先選取要回看的記錄")
            return

        rec = self._records[row]
        wf_path = rec.get("waveform_path") or ""

        if not wf_path:
            QMessageBox.information(
                self, "提示",
                "此診斷場次無波形數據。"
            )
            return

        if not os.path.isfile(wf_path):
            QMessageBox.warning(
                self, "警告",
                f"診斷波形檔案不存在：\n{wf_path}\n\n"
                "檔案可能已被移動或刪除。"
            )
            return

        try:
            dlg = DiagnosticReplayDialog(
                waveform_path=wf_path,
                session_info=rec,
                parent=self
            )
            dlg.exec_()
        except Exception as e:
            QMessageBox.critical(self, "錯誤", f"開啟診斷波形回放失敗：\n{e}")

    def _on_export_csv(self):
        """匯出目前顯示的記錄為 CSV"""
        if not self._records:
            QMessageBox.information(self, "提示", "沒有可匯出的資料")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "匯出 CSV",
            f"motor_history_{time.strftime('%Y%m%d_%H%M%S')}.csv",
            "CSV 檔案 (*.csv)"
        )
        if not path:
            return

        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                # 標頭
                writer.writerow([
                    "ID", "類型", "開始時間", "結束時間", "馬達序號", "操作員",
                    "時長(秒)", "整體結果", "診斷摘要"
                ])
                for rec in self._records:
                    is_diag = (rec.get("session_type") == "diagnostic")
                    if is_diag:
                        diag_pass = rec.get("diag_pass", -1)
                        result_str = "PASS" if diag_pass == 1 else ("FAIL" if diag_pass == 0 else "未分析")
                        # 匯出完整摘要（換行轉為空格，避免 CSV 格式問題）
                        summary = (rec.get("diag_summary") or "").replace("\n", " | ")
                    else:
                        result_str = "PASS" if rec.get("overall_pass") == 1 else "FAIL"
                        summary = ""
                    writer.writerow([
                        rec.get("id", ""),
                        "診斷" if is_diag else "測試",
                        rec.get("started_at", ""),
                        rec.get("ended_at", ""),
                        rec.get("serial_no", ""),
                        rec.get("operator", ""),
                        rec.get("duration_s", ""),
                        result_str,
                        summary,
                    ])
            QMessageBox.information(self, "成功", f"已匯出 {len(self._records)} 筆記錄至：\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "錯誤", f"匯出失敗：\n{e}")

    def _on_edit(self):
        """編輯選取場次的序號與操作員（允許事後補填）"""
        row = self._table.currentRow()
        if row < 0 or row >= len(self._records):
            QMessageBox.information(self, "提示", "請先選取要編輯的記錄")
            return

        rec = self._records[row]
        session_id = rec.get("id")

        # 建立編輯對話框
        dlg = QDialog(self)
        dlg.setWindowTitle(f"編輯場次 #{session_id} 資訊")
        dlg.setModal(True)
        dlg.setFixedWidth(380)
        dlg.setStyleSheet("""
            QDialog { background-color: #1E1E1E; color: #CCCCCC; }
            QLabel { color: #CCCCCC; font-size: 12px; }
            QLineEdit {
                background-color: #2A2A2A; color: #FFFFFF;
                border: 1px solid #555555; border-radius: 4px;
                padding: 5px 8px; font-size: 13px;
            }
            QLineEdit:focus { border: 1px solid #4AABFF; }
            QGroupBox {
                color: #AAAAAA; border: 1px solid #444444;
                border-radius: 6px; margin-top: 10px; padding-top: 6px;
                font-size: 11px;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
            QPushButton {
                background-color: #2D5A8E; color: #FFFFFF; border: none;
                border-radius: 4px; padding: 7px 20px; font-size: 12px;
                font-weight: bold; min-width: 80px;
            }
            QPushButton:hover { background-color: #3A72B0; }
            QPushButton#btn_save { background-color: #2D8E2D; }
            QPushButton#btn_save:hover { background-color: #3AAA3A; }
        """)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        group = QGroupBox("測試物件資訊")
        form = QFormLayout(group)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignRight)

        serial_edit = QLineEdit(rec.get("serial_no") or "")
        serial_edit.setPlaceholderText("例：MTR-2026-001")
        serial_edit.setMaxLength(64)
        form.addRow("馬達序號：", serial_edit)

        operator_edit = QLineEdit(rec.get("operator") or "")
        operator_edit.setPlaceholderText("操作員姓名")
        operator_edit.setMaxLength(32)
        form.addRow("操作員：", operator_edit)

        layout.addWidget(group)

        btn_layout = QHBoxLayout()
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(dlg.reject)
        btn_layout.addWidget(btn_cancel)
        btn_layout.addStretch()
        btn_save = QPushButton("💾 儲存")
        btn_save.setObjectName("btn_save")
        btn_save.setDefault(True)
        btn_save.clicked.connect(dlg.accept)
        btn_layout.addWidget(btn_save)
        layout.addLayout(btn_layout)

        serial_edit.setFocus()

        if dlg.exec_() != QDialog.Accepted:
            return

        new_serial   = serial_edit.text().strip()
        new_operator = operator_edit.text().strip()

        try:
            self._db.update_session_info(
                session_id=session_id,
                serial_no=new_serial,
                operator=new_operator
            )
            # 重新載入資料並保持選取列
            self._load_data()
            # 嘗試重新選取同一筆（依 ID 找回列號）
            for r in range(self._table.rowCount()):
                item = self._table.item(r, 0)
                if item and item.text() == str(session_id):
                    self._table.selectRow(r)
                    break
            QMessageBox.information(
                self, "成功",
                f"場次 #{session_id} 資訊已更新\n"
                f"序號：{new_serial or '(無)'}\n"
                f"操作員：{new_operator or '(無)'}"
            )
        except Exception as e:
            QMessageBox.critical(self, "錯誤", f"更新失敗：\n{e}")

    def _on_delete(self):
        """刪除選取的場次記錄"""
        row = self._table.currentRow()
        if row < 0 or row >= len(self._records):
            QMessageBox.information(self, "提示", "請先選取要刪除的記錄")
            return

        rec = self._records[row]
        session_id = rec.get("id")
        serial = rec.get("serial_no") or "(無序號)"

        reply = QMessageBox.question(
            self, "確認刪除",
            f"確定要刪除場次 #{session_id}（序號：{serial}）？\n此操作無法復原。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        try:
            self._db.delete_session(session_id)
            self._load_data()
            self._detail_text.clear()
            QMessageBox.information(self, "成功", f"場次 #{session_id} 已刪除")
        except Exception as e:
            QMessageBox.critical(self, "錯誤", f"刪除失敗：\n{e}")

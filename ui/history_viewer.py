"""
歷史記錄查詢視窗
顯示所有測試場次的統計摘要，支援篩選與匯出
"""

import time
import csv
from pathlib import Path
from typing import List, Dict, Any

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QLabel, QLineEdit, QPushButton, QHeaderView, QAbstractItemView,
    QGroupBox, QFormLayout, QMessageBox, QFileDialog, QFrame,
    QSplitter, QTextEdit, QWidget, QSizePolicy
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QColor, QBrush

from db.database import DatabaseManager


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
    ("ID",          "id",             45,  Qt.AlignCenter),
    ("開始時間",     "started_at",    145,  Qt.AlignLeft),
    ("馬達序號",     "serial_no",     120,  Qt.AlignLeft),
    ("操作員",       "operator",       80,  Qt.AlignCenter),
    ("時長(秒)",     "duration_s",     70,  Qt.AlignCenter),
    ("Hall 成功率",  "hall_pass_rate", 90,  Qt.AlignCenter),
    ("Enc 成功率",   "enc_pass_rate",  90,  Qt.AlignCenter),
    ("平均 RPM",     "avg_rpm",        80,  Qt.AlignCenter),
    ("最高 RPM",     "max_rpm",        80,  Qt.AlignCenter),
    ("整體結果",     "overall_pass",   80,  Qt.AlignCenter),
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

        btn_delete = QPushButton("🗑 刪除選取")
        btn_delete.setObjectName("btn_delete")
        btn_delete.clicked.connect(self._on_delete)
        h.addWidget(btn_delete)

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
            for col_idx, (_, key, _, align) in enumerate(COLUMNS):
                value = rec.get(key)
                display = self._format_value(key, value)
                item = QTableWidgetItem(display)
                item.setTextAlignment(align | Qt.AlignVCenter)

                # 整體結果著色
                if key == "overall_pass":
                    if value == 1:
                        item.setForeground(QBrush(QColor("#44FF44")))
                        item.setText("✔ PASS")
                    elif value == 0 and rec.get("hall_total") is not None:
                        item.setForeground(QBrush(QColor("#FF4444")))
                        item.setText("✘ FAIL")
                    else:
                        item.setForeground(QBrush(QColor("#888888")))
                        item.setText("---")

                # 成功率著色
                elif key in ("hall_pass_rate", "enc_pass_rate") and value is not None:
                    rate = float(value)
                    if rate >= 0.95:
                        item.setForeground(QBrush(QColor("#44FF44")))
                    elif rate >= 0.80:
                        item.setForeground(QBrush(QColor("#FFAA00")))
                    else:
                        item.setForeground(QBrush(QColor("#FF4444")))

                self._table.setItem(row_idx, col_idx, item)

        self._table.setSortingEnabled(True)

    def _format_value(self, key: str, value) -> str:
        """格式化顯示值"""
        if value is None:
            return "---"
        if key in ("hall_pass_rate", "enc_pass_rate"):
            return f"{float(value)*100:.1f}%"
        if key in ("avg_rpm", "max_rpm", "min_rpm"):
            return f"{float(value):.1f}"
        if key == "duration_s":
            return f"{float(value):.0f}" if value else "---"
        if key == "overall_pass":
            return "PASS" if value == 1 else ("FAIL" if value == 0 else "---")
        return str(value) if value else ""

    def _update_stats_label(self):
        """更新頂部統計摘要標籤"""
        try:
            stats = self._db.get_summary_stats()
            total = stats.get("total_sessions") or 0
            passed = stats.get("pass_sessions") or 0
            avg_hall = (stats.get("avg_hall_pass_rate") or 0) * 100
            avg_enc  = (stats.get("avg_enc_pass_rate")  or 0) * 100
            self._stats_lbl.setText(
                f"共 {total} 筆  |  整體 PASS: {passed} 筆  |  "
                f"平均 Hall 成功率: {avg_hall:.1f}%  |  "
                f"平均 Enc 成功率: {avg_enc:.1f}%"
            )
        except Exception:
            pass

    # ─── 事件處理 ──────────────────────────────────────────────────────────────

    def _on_refresh(self):
        self._search_edit.clear()
        self._load_data()

    def _on_row_selected(self):
        """點選列時顯示詳細資訊"""
        selected = self._table.selectedItems()
        if not selected:
            return

        row = self._table.currentRow()
        if row < 0 or row >= len(self._records):
            return

        rec = self._records[row]
        self._show_detail(rec)

    def _show_detail(self, rec: Dict[str, Any]):
        """在詳細資訊框顯示單筆記錄"""
        hall_rate = (rec.get("hall_pass_rate") or 0) * 100
        enc_rate  = (rec.get("enc_pass_rate")  or 0) * 100
        overall   = "✔ PASS" if rec.get("overall_pass") == 1 else (
                    "✘ FAIL" if rec.get("hall_total") is not None else "---")

        duration = rec.get("duration_s")
        dur_str = f"{duration:.0f} 秒 ({duration/60:.1f} 分鐘)" if duration else "---"

        text = (
            f"場次 #{rec.get('id')}  |  序號: {rec.get('serial_no') or '(無)'}  "
            f"|  操作員: {rec.get('operator') or '(無)'}\n"
            f"開始: {rec.get('started_at', '---')}  |  "
            f"結束: {rec.get('ended_at', '---')}  |  時長: {dur_str}\n"
            f"\n"
            f"Hall Sensor：\n"
            f"  總採樣 {rec.get('hall_total', 0)} 次  |  "
            f"PASS {rec.get('hall_pass', 0)} 次  |  "
            f"FAIL {rec.get('hall_fail', 0)} 次  |  "
            f"成功率 {hall_rate:.2f}%\n"
            f"\n"
            f"Encoder：\n"
            f"  總採樣 {rec.get('enc_total', 0)} 次  |  "
            f"PASS {rec.get('enc_pass', 0)} 次  |  "
            f"FAIL {rec.get('enc_fail', 0)} 次  |  "
            f"成功率 {enc_rate:.2f}%\n"
            f"\n"
            f"轉速：平均 {rec.get('avg_rpm', 0):.1f} RPM  |  "
            f"最高 {rec.get('max_rpm', 0):.1f} RPM  |  "
            f"最低 {rec.get('min_rpm', 0):.1f} RPM\n"
            f"\n"
            f"整體結果：{overall}"
        )
        self._detail_text.setPlainText(text)

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
                    "ID", "開始時間", "結束時間", "馬達序號", "操作員",
                    "時長(秒)",
                    "Hall 總採樣", "Hall PASS", "Hall FAIL", "Hall 成功率(%)",
                    "Enc 總採樣",  "Enc PASS",  "Enc FAIL",  "Enc 成功率(%)",
                    "平均 RPM", "最高 RPM", "最低 RPM", "整體結果"
                ])
                for rec in self._records:
                    writer.writerow([
                        rec.get("id", ""),
                        rec.get("started_at", ""),
                        rec.get("ended_at", ""),
                        rec.get("serial_no", ""),
                        rec.get("operator", ""),
                        rec.get("duration_s", ""),
                        rec.get("hall_total", 0),
                        rec.get("hall_pass", 0),
                        rec.get("hall_fail", 0),
                        f"{(rec.get('hall_pass_rate') or 0)*100:.2f}",
                        rec.get("enc_total", 0),
                        rec.get("enc_pass", 0),
                        rec.get("enc_fail", 0),
                        f"{(rec.get('enc_pass_rate') or 0)*100:.2f}",
                        f"{rec.get('avg_rpm', 0):.1f}",
                        f"{rec.get('max_rpm', 0):.1f}",
                        f"{rec.get('min_rpm', 0):.1f}",
                        "PASS" if rec.get("overall_pass") == 1 else "FAIL",
                    ])
            QMessageBox.information(self, "成功", f"已匯出 {len(self._records)} 筆記錄至：\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "錯誤", f"匯出失敗：\n{e}")

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

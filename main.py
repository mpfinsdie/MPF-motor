"""
馬達測試系統 - 主程式入口
Hall Sensor (3.3V) 與 Encoder (5V) 量測程式
使用 Advantech USB-4716 DAQ 裝置
"""

import sys
import os

# 確保專案根目錄在 Python 路徑中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

from ui.main_window import MainWindow


def main():
    # 高 DPI 支援
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationName("馬達測試系統")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("MPF")

    # 全域字型
    font = QFont("Microsoft JhengHei UI", 10)
    app.setFont(font)

    window = MainWindow()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()

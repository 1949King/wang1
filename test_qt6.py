#!/usr/bin/env python3
"""
测试PyQt6环境
"""

import sys
from PyQt6.QtWidgets import QApplication, QMainWindow, QLabel

class TestWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PyQt6测试")
        self.setGeometry(100, 100, 400, 300)
        
        label = QLabel("PyQt6环境正常！", self)
        label.setGeometry(100, 100, 200, 50)

if __name__ == "__main__":
    print("启动PyQt6测试...")
    app = QApplication(sys.argv)
    window = TestWindow()
    window.show()
    print("窗口已显示")
    sys.exit(app.exec())

#!/usr/bin/env python3
"""
测试登录窗口
"""

import sys
from PyQt6.QtWidgets import QApplication
from login_window import LoginWindow

def on_login_success():
    print("登录成功！")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    login_window = LoginWindow(on_login_success=on_login_success)
    login_window.show()
    sys.exit(app.exec())

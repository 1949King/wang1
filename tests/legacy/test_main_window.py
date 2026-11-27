#!/usr/bin/env python3
"""
测试主程序窗口
"""

import sys
from PySide6.QtWidgets import QApplication
from license.license_manager import get_license_manager
from main_qt6 import MainProgramWindow

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # 获取授权管理器
    license_manager = get_license_manager()
    print(f"授权管理器: {license_manager}")
    
    # 创建主程序窗口
    main_window = MainProgramWindow(license_manager)
    print(f"主程序窗口: {main_window}")
    
    main_window.show()
    print("主程序窗口已显示")
    
    sys.exit(app.exec())

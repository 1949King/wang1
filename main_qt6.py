#!/usr/bin/env python3
"""
Qt6 主应用入口
集成授权管理系统和登录窗口
"""

import sys
import os
from PyQt6.QtWidgets import QApplication, QMainWindow, QMessageBox, QVBoxLayout, QHBoxLayout, QWidget, QLabel, QPushButton, QGridLayout
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QIcon

# 导入独立授权管理模块
from license.license_manager import LicenseManager, LicenseDialog, get_license_manager, check_permission

# 导入主窗口
from app.modules.lego.main_window import MainWindow

# 导入登录窗口
from app.modules.lego.login_window import LoginWindow, ActivationWindow

class AppStartupThread(QThread):
    """应用启动线程"""
    startup_finished = pyqtSignal()
    
    def run(self):
        # 模拟启动过程
        import time
        time.sleep(1)  # 模拟初始化时间
        self.startup_finished.emit()


class AIShortDramaEditorApp:
    """AI短剧编辑器主应用"""
    
    def __init__(self, app):
        print("AIShortDramaEditorApp初始化开始...")
        self.app = app
        # 初始化授权管理器
        self.license_manager = get_license_manager()
        print(f"授权管理器初始化完成: {self.license_manager}")
        
        # 初始化窗口
        self.login_window = None
        self.activation_window = None
        self.main_window = None
        
        # 直接显示主窗口
        self._show_main_window()

    def _show_login_window(self):
        """显示登录窗口"""
        print("创建LoginWindow...")
        self.login_window = LoginWindow()
        self.login_window.login_success.connect(self._on_login_success)
        self.login_window.show()
        print("LoginWindow已显示")

    def _on_login_success(self):
        """登录成功处理"""
        print("登录成功，显示主窗口")
        # 关闭登录窗口
        if self.login_window:
            self.login_window.close()
            self.login_window = None
        
        # 显示主窗口
        self._show_main_window()

    def _show_main_window(self):
        """显示主窗口"""
        print("创建MainWindow...")
        self.main_window = MainWindow()
        # 连接主窗口的关闭信号
        self.main_window.destroyed.connect(self._on_main_window_closed)
        self.main_window.show()
        print("MainWindow已显示")

    def _on_main_window_closed(self):
        """主窗口关闭处理"""
        print("主窗口已关闭，退出应用")
        # 关闭所有窗口
        if self.login_window:
            self.login_window.close()
        if self.activation_window:
            self.activation_window.close()
        # 退出应用
        self.app.quit()


def main():
    """主函数"""
    app = QApplication(sys.argv)
    
    # 设置应用图标
    icon_path = "icon.png"
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    
    # 启动应用
    editor_app = AIShortDramaEditorApp(app)
    
    # 将editor_app保存到app的属性中，防止被垃圾回收
    app.editor_app = editor_app
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

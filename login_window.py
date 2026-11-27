#!/usr/bin/env python3
"""
登录窗口模块
集成授权信息查看功能
"""

import sys
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QLineEdit, QMessageBox, QStackedWidget, QFormLayout,
    QComboBox, QTabWidget
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon

from license.license_manager import LicenseManager, LicenseDialog, get_license_manager


class LoginWidget(QWidget):
    """登录组件"""
    
    def __init__(self, parent=None, on_login_success=None):
        super().__init__(parent)
        self.on_login_success = on_login_success
        self._setup_ui()
    
    def _setup_ui(self):
        """设置界面"""
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(20)
        
        # 标题
        title_label = QLabel("AI短剧编辑器")
        title_label.setStyleSheet("font-size: 24px; font-weight: bold; color: #1e6bde;")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)
        
        # 副标题
        subtitle_label = QLabel("登录以使用完整功能")
        subtitle_label.setStyleSheet("font-size: 14px; color: #666;")
        subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle_label)
        
        # 登录表单
        form_widget = QWidget()
        form_layout = QFormLayout(form_widget)
        form_layout.setSpacing(15)
        
        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText("请输入用户名")
        form_layout.addRow("用户名:", self.username_edit)
        
        self.password_edit = QLineEdit()
        self.password_edit.setPlaceholderText("请输入密码")
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form_layout.addRow("密码:", self.password_edit)
        
        layout.addWidget(form_widget)
        
        # 登录按钮
        login_button = QPushButton("登录")
        login_button.setMinimumSize(200, 40)
        login_button.setStyleSheet("background-color: #1e6bde; color: white; font-size: 14px;")
        login_button.clicked.connect(self._login)
        layout.addWidget(login_button)
        
        # 底部链接
        bottom_widget = QWidget()
        bottom_layout = QHBoxLayout(bottom_widget)
        bottom_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        register_link = QLabel("<a href='#'>注册账号</a>")
        register_link.setOpenExternalLinks(False)
        register_link.linkActivated.connect(lambda: self.parent().parent().stacked_widget.setCurrentWidget(self.parent().parent().register_widget))
        
        license_link = QLabel("<a href='#'>授权管理</a>")
        license_link.setOpenExternalLinks(False)
        license_link.linkActivated.connect(self._show_license_dialog)
        
        bottom_layout.addWidget(register_link)
        bottom_layout.addWidget(QLabel(" | "))
        bottom_layout.addWidget(license_link)
        
        layout.addWidget(bottom_widget)
    
    def _login(self):
        """登录处理"""
        username = self.username_edit.text().strip()
        password = self.password_edit.text().strip()
        
        if not username or not password:
            QMessageBox.warning(self, "错误", "请输入用户名和密码")
            return
        
        try:
            from app.modules.lego.auth import AuthService
            auth = AuthService()
            result = auth.authenticate(username, password)
            if result.get("success"):
                QMessageBox.information(self, "成功", "登录成功！")
                if self.on_login_success:
                    self.on_login_success()
            else:
                QMessageBox.warning(self, "错误", result.get("message", "用户名或密码错误"))
        except ImportError:
            # 认证模块不可用时的安全回退
            QMessageBox.warning(self, "错误", "认证服务暂不可用，请联系管理员")
    
    def _show_license_dialog(self):
        """显示授权管理对话框"""
        license_manager = get_license_manager()
        dialog = LicenseDialog(license_manager, self)
        dialog.exec()


class RegisterWidget(QWidget):
    """注册组件"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
    
    def _setup_ui(self):
        """设置界面"""
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(20)
        
        # 标题
        title_label = QLabel("注册账号")
        title_label.setStyleSheet("font-size: 24px; font-weight: bold; color: #1e6bde;")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)
        
        # 注册表单
        form_widget = QWidget()
        form_layout = QFormLayout(form_widget)
        form_layout.setSpacing(15)
        
        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText("请输入用户名")
        form_layout.addRow("用户名:", self.username_edit)
        
        self.email_edit = QLineEdit()
        self.email_edit.setPlaceholderText("请输入邮箱")
        form_layout.addRow("邮箱:", self.email_edit)
        
        self.password_edit = QLineEdit()
        self.password_edit.setPlaceholderText("请输入密码")
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form_layout.addRow("密码:", self.password_edit)
        
        self.confirm_password_edit = QLineEdit()
        self.confirm_password_edit.setPlaceholderText("请确认密码")
        self.confirm_password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form_layout.addRow("确认密码:", self.confirm_password_edit)
        
        layout.addWidget(form_widget)
        
        # 注册按钮
        register_button = QPushButton("注册")
        register_button.setMinimumSize(200, 40)
        register_button.setStyleSheet("background-color: #1e6bde; color: white; font-size: 14px;")
        register_button.clicked.connect(self._register)
        layout.addWidget(register_button)
        
        # 返回登录
        back_button = QPushButton("返回登录")
        back_button.clicked.connect(lambda: self.parent().parent().stacked_widget.setCurrentWidget(self.parent().parent().login_widget))
        layout.addWidget(back_button)
    
    def _register(self):
        """注册处理"""
        username = self.username_edit.text().strip()
        email = self.email_edit.text().strip()
        password = self.password_edit.text().strip()
        confirm_password = self.confirm_password_edit.text().strip()
        
        if not username or not email or not password:
            QMessageBox.warning(self, "错误", "请填写完整信息")
            return
        
        if password != confirm_password:
            QMessageBox.warning(self, "错误", "两次输入的密码不一致")
            return
        
        QMessageBox.information(self, "成功", "注册成功！")
        self.parent().setCurrentWidget(self.parent().login_widget)


class LoginWindow(QMainWindow):
    """登录窗口"""
    
    def __init__(self, on_login_success=None):
        super().__init__()
        self.setWindowTitle("AI短剧编辑器 - 登录")
        self.setMinimumSize(400, 500)
        
        self.on_login_success = on_login_success
        
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 创建堆叠窗口
        self.stacked_widget = QStackedWidget()
        
        # 创建登录和注册组件
        self.login_widget = LoginWidget(self.stacked_widget, self._on_login_success)
        self.register_widget = RegisterWidget(self.stacked_widget)
        
        # 添加到堆叠窗口
        self.stacked_widget.addWidget(self.login_widget)
        self.stacked_widget.addWidget(self.register_widget)
        
        # 布局
        layout = QVBoxLayout(central_widget)
        layout.addWidget(self.stacked_widget)
    
    def _on_login_success(self):
        """登录成功处理"""
        if self.on_login_success:
            self.on_login_success()
        self.close()


def main():
    """主函数"""
    from PySide6.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    
    # 测试登录窗口
    def on_login():
        print("登录成功，打开主程序")
    
    login_window = LoginWindow(on_login)
    login_window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
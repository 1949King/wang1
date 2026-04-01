"""
登录/注册界面 (LoginWindow)
==========================
Qt6 实现的现代化登录界面
支持：手机号登录、QQ邮箱登录、注册、设备管理
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QLineEdit, QPushButton, QStackedWidget, QFrame,
    QMessageBox, QCheckBox, QTabWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QDialog, QSpacerItem,
    QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPropertyAnimation, QEasingCurve, QSize
from PyQt6.QtGui import QFont, QIcon, QPixmap, QColor, QPainter, QLinearGradient

from .auth import AuthService, DeviceFingerprint
from .email_service import email_service
from typing import Optional


class ModernLineEdit(QLineEdit):
    """现代化输入框"""
    
    def __init__(self, placeholder: str = "", echo_mode: QLineEdit.EchoMode = QLineEdit.EchoMode.Normal):
        super().__init__()
        self.setPlaceholderText(placeholder)
        self.setEchoMode(echo_mode)
        self.setMinimumHeight(44)
        self.setStyleSheet("""
            QLineEdit {
                background-color: #1a1a1a;
                color: #ffffff;
                border: 2px solid #333333;
                border-radius: 8px;
                padding: 10px 16px;
                font-size: 14px;
            }
            QLineEdit:focus {
                border-color: #1e6bde;
            }
            QLineEdit::placeholder {
                color: #666666;
            }
        """)


class ModernButton(QPushButton):
    """现代化按钮"""
    
    def __init__(self, text: str, primary: bool = True):
        super().__init__(text)
        self.setMinimumHeight(44)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        if primary:
            self.setStyleSheet("""
                QPushButton {
                    background-color: #1e6bde;
                    color: #ffffff;
                    border: none;
                    border-radius: 8px;
                    font-size: 14px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #1a5bc4;
                }
                QPushButton:pressed {
                    background-color: #154aa8;
                }
                QPushButton:disabled {
                    background-color: #333333;
                    color: #666666;
                }
            """)
        else:
            self.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    color: #1e6bde;
                    border: 2px solid #1e6bde;
                    border-radius: 8px;
                    font-size: 14px;
                }
                QPushButton:hover {
                    background-color: rgba(30, 107, 222, 0.1);
                }
                QPushButton:pressed {
                    background-color: rgba(30, 107, 222, 0.2);
                }
            """)


class LogoWidget(QWidget):
    """Logo 组件"""
    
    def __init__(self):
        super().__init__()
        self.setFixedSize(120, 120)
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        gradient = QLinearGradient(0, 0, self.width(), self.height())
        gradient.setColorAt(0, QColor("#1e6bde"))
        gradient.setColorAt(1, QColor("#6366f1"))
        
        painter.setBrush(gradient)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, 0, self.width(), self.height(), 24, 24)
        
        painter.setPen(QColor("#ffffff"))
        font = QFont("Microsoft YaHei", 32, QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "AI")


class LoginWidget(QWidget):
    """登录面板"""
    
    login_success = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        self._auth = AuthService()
        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(0, 0, 0, 0)
        
        title = QLabel("欢迎回来")
        title.setStyleSheet("font-size: 28px; font-weight: bold; color: #ffffff;")
        layout.addWidget(title)
        
        subtitle = QLabel("登录您的账号继续使用")
        subtitle.setStyleSheet("font-size: 14px; color: #808080;")
        layout.addWidget(subtitle)
        
        layout.addSpacing(20)
        
        self._tab_widget = QTabWidget()
        self._tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: none;
                background-color: transparent;
            }
            QTabBar::tab {
                background-color: #1a1a1a;
                color: #808080;
                border: none;
                padding: 12px 24px;
                font-size: 14px;
                border-radius: 8px 8px 0 0;
            }
            QTabBar::tab:selected {
                color: #1e6bde;
                background-color: #252525;
            }
            QTabBar::tab:hover:!selected {
                color: #ffffff;
            }
        """)
        
        phone_tab = self._create_phone_login_tab()
        email_tab = self._create_email_login_tab()
        
        self._tab_widget.addTab(phone_tab, "📱 手机号登录")
        self._tab_widget.addTab(email_tab, "📧 邮箱登录")
        
        layout.addWidget(self._tab_widget)
        
        layout.addSpacing(16)
        
        self._remember_check = QCheckBox("记住登录状态")
        self._remember_check.setChecked(True)
        self._remember_check.setStyleSheet("color: #808080; font-size: 13px;")
        layout.addWidget(self._remember_check)
        
        layout.addStretch()
    
    def _create_phone_login_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)
        
        self._phone_input = ModernLineEdit("请输入手机号")
        layout.addWidget(self._phone_input)
        
        self._phone_password_input = ModernLineEdit("请输入密码", QLineEdit.EchoMode.Password)
        layout.addWidget(self._phone_password_input)
        
        self._phone_login_btn = ModernButton("登 录")
        self._phone_login_btn.clicked.connect(self._do_phone_login)
        layout.addWidget(self._phone_login_btn)
        
        return widget
    
    def _create_email_login_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)
        
        self._email_input = ModernLineEdit("请输入QQ邮箱")
        layout.addWidget(self._email_input)
        
        self._email_password_input = ModernLineEdit("请输入密码", QLineEdit.EchoMode.Password)
        layout.addWidget(self._email_password_input)
        
        self._email_login_btn = ModernButton("登 录")
        self._email_login_btn.clicked.connect(self._do_email_login)
        layout.addWidget(self._email_login_btn)
        
        return widget
    
    def _do_phone_login(self):
        phone = self._phone_input.text().strip()
        password = self._phone_password_input.text()
        
        if not phone:
            self._show_error("请输入手机号")
            return
        if not password:
            self._show_error("请输入密码")
            return
        
        self._phone_login_btn.setText("登录中...")
        self._phone_login_btn.setEnabled(False)
        
        success, message = self._auth.login_with_phone(phone, password)
        
        if success:
            if self._remember_check.isChecked():
                self._auth.save_session()
            self._show_success(message)
            self.login_success.emit()
        else:
            self._show_error(message)
            self._phone_login_btn.setText("登 录")
            self._phone_login_btn.setEnabled(True)
    
    def _do_email_login(self):
        email = self._email_input.text().strip()
        password = self._email_password_input.text()
        
        if not email:
            self._show_error("请输入邮箱")
            return
        if not password:
            self._show_error("请输入密码")
            return
        
        self._email_login_btn.setText("登录中...")
        self._email_login_btn.setEnabled(False)
        
        success, message = self._auth.login_with_email(email, password)
        
        if success:
            if self._remember_check.isChecked():
                self._auth.save_session()
            self._show_success(message)
            self.login_success.emit()
        else:
            self._show_error(message)
            self._email_login_btn.setText("登 录")
            self._email_login_btn.setEnabled(True)
    
    def _show_error(self, message: str):
        QMessageBox.warning(self, "登录失败", message)
    
    def _show_success(self, message: str):
        pass


class RegisterWidget(QWidget):
    """注册面板"""
    
    register_success = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        self._auth = AuthService()
        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(0, 0, 0, 0)
        
        title = QLabel("创建账号")
        title.setStyleSheet("font-size: 28px; font-weight: bold; color: #ffffff;")
        layout.addWidget(title)
        
        subtitle = QLabel("注册新账号开始使用")
        subtitle.setStyleSheet("font-size: 14px; color: #808080;")
        layout.addWidget(subtitle)
        
        layout.addSpacing(20)
        
        self._tab_widget = QTabWidget()
        self._tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: none;
                background-color: transparent;
            }
            QTabBar::tab {
                background-color: #1a1a1a;
                color: #808080;
                border: none;
                padding: 12px 24px;
                font-size: 14px;
                border-radius: 8px 8px 0 0;
            }
            QTabBar::tab:selected {
                color: #1e6bde;
                background-color: #252525;
            }
            QTabBar::tab:hover:!selected {
                color: #ffffff;
            }
        """)
        
        phone_tab = self._create_phone_register_tab()
        email_tab = self._create_email_register_tab()
        
        self._tab_widget.addTab(phone_tab, "📱 手机号注册")
        self._tab_widget.addTab(email_tab, "📧 邮箱注册")
        
        layout.addWidget(self._tab_widget)
        layout.addStretch()
    
    def _create_phone_register_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)
        
        self._reg_phone_input = ModernLineEdit("请输入手机号")
        layout.addWidget(self._reg_phone_input)
        
        # 验证码输入框和发送按钮
        code_layout = QHBoxLayout()
        self._reg_phone_code = ModernLineEdit("请输入验证码")
        code_layout.addWidget(self._reg_phone_code, 2)
        
        self._reg_phone_send_code_btn = ModernButton("发送验证码", primary=False)
        self._reg_phone_send_code_btn.setMinimumHeight(44)
        self._reg_phone_send_code_btn.clicked.connect(self._send_phone_code)
        code_layout.addWidget(self._reg_phone_send_code_btn, 1)
        layout.addLayout(code_layout)
        
        self._reg_phone_password = ModernLineEdit("请设置密码（至少6位）", QLineEdit.EchoMode.Password)
        layout.addWidget(self._reg_phone_password)
        
        self._reg_phone_password2 = ModernLineEdit("请再次输入密码", QLineEdit.EchoMode.Password)
        layout.addWidget(self._reg_phone_password2)
        
        self._reg_phone_nickname = ModernLineEdit("昵称（可选）")
        layout.addWidget(self._reg_phone_nickname)
        
        self._reg_phone_btn = ModernButton("注 册")
        self._reg_phone_btn.clicked.connect(self._do_phone_register)
        layout.addWidget(self._reg_phone_btn)
        
        # 验证码倒计时
        self._phone_code_timer = QTimer(self)
        self._phone_code_timer.timeout.connect(self._update_phone_code_timer)
        self._phone_code_remaining = 0
        
        return widget
    
    def _create_email_register_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)
        
        self._reg_email_input = ModernLineEdit("请输入QQ邮箱")
        layout.addWidget(self._reg_email_input)
        
        # 验证码输入框和发送按钮
        code_layout = QHBoxLayout()
        self._reg_email_code = ModernLineEdit("请输入验证码")
        code_layout.addWidget(self._reg_email_code, 2)
        
        self._reg_email_send_code_btn = ModernButton("发送验证码", primary=False)
        self._reg_email_send_code_btn.setMinimumHeight(44)
        self._reg_email_send_code_btn.clicked.connect(self._send_email_code)
        code_layout.addWidget(self._reg_email_send_code_btn, 1)
        layout.addLayout(code_layout)
        
        self._reg_email_password = ModernLineEdit("请设置密码（至少6位）", QLineEdit.EchoMode.Password)
        layout.addWidget(self._reg_email_password)
        
        self._reg_email_password2 = ModernLineEdit("请再次输入密码", QLineEdit.EchoMode.Password)
        layout.addWidget(self._reg_email_password2)
        
        self._reg_email_nickname = ModernLineEdit("昵称（可选）")
        layout.addWidget(self._reg_email_nickname)
        
        self._reg_email_btn = ModernButton("注 册")
        self._reg_email_btn.clicked.connect(self._do_email_register)
        layout.addWidget(self._reg_email_btn)
        
        # 验证码倒计时
        self._email_code_timer = QTimer(self)
        self._email_code_timer.timeout.connect(self._update_email_code_timer)
        self._email_code_remaining = 0
        
        return widget
    
    def _do_phone_register(self):
        phone = self._reg_phone_input.text().strip()
        password = self._reg_phone_password.text()
        password2 = self._reg_phone_password2.text()
        nickname = self._reg_phone_nickname.text().strip()
        
        if not phone:
            self._show_error("请输入手机号")
            return
        if not password:
            self._show_error("请设置密码")
            return
        if password != password2:
            self._show_error("两次密码不一致")
            return
        
        self._reg_phone_btn.setText("注册中...")
        self._reg_phone_btn.setEnabled(False)
        
        success, message = self._auth.register_with_phone(phone, password, nickname)
        
        if success:
            self._show_success(message + "，请登录")
            self.register_success.emit()
        else:
            self._show_error(message)
        
        self._reg_phone_btn.setText("注 册")
        self._reg_phone_btn.setEnabled(True)
    
    def _send_phone_code(self):
        phone = self._reg_phone_input.text().strip()
        if not phone:
            self._show_error("请输入手机号")
            return
        
        # 调用AuthService发送短信验证码
        success, message = self._auth.send_phone_verification(phone)
        if success:
            self._start_phone_code_timer()
            QMessageBox.information(self, "提示", message)
        else:
            self._show_error(message)
    
    def _send_email_code(self):
        email = self._reg_email_input.text().strip()
        if not email:
            self._show_error("请输入邮箱")
            return
        
        success, message = email_service.send_verification_code(email)
        if success:
            self._start_email_code_timer()
            QMessageBox.information(self, "提示", message)
        else:
            self._show_error(message)
    
    def _start_phone_code_timer(self):
        self._phone_code_remaining = 60
        self._reg_phone_send_code_btn.setEnabled(False)
        self._phone_code_timer.start(1000)
    
    def _start_email_code_timer(self):
        self._email_code_remaining = 60
        self._reg_email_send_code_btn.setEnabled(False)
        self._email_code_timer.start(1000)
    
    def _update_phone_code_timer(self):
        if self._phone_code_remaining > 0:
            self._phone_code_remaining -= 1
            self._reg_phone_send_code_btn.setText(f"{self._phone_code_remaining}秒后重发")
        else:
            self._phone_code_timer.stop()
            self._reg_phone_send_code_btn.setEnabled(True)
            self._reg_phone_send_code_btn.setText("发送验证码")
    
    def _update_email_code_timer(self):
        if self._email_code_remaining > 0:
            self._email_code_remaining -= 1
            self._reg_email_send_code_btn.setText(f"{self._email_code_remaining}秒后重发")
        else:
            self._email_code_timer.stop()
            self._reg_email_send_code_btn.setEnabled(True)
            self._reg_email_send_code_btn.setText("发送验证码")
    
    def _do_phone_register(self):
        phone = self._reg_phone_input.text().strip()
        code = self._reg_phone_code.text().strip()
        password = self._reg_phone_password.text()
        password2 = self._reg_phone_password2.text()
        nickname = self._reg_phone_nickname.text().strip()
        
        if not phone:
            self._show_error("请输入手机号")
            return
        if not code:
            self._show_error("请输入验证码")
            return
        if not password:
            self._show_error("请设置密码")
            return
        if password != password2:
            self._show_error("两次密码不一致")
            return
        
        self._reg_phone_btn.setText("注册中...")
        self._reg_phone_btn.setEnabled(False)
        
        # 调用带验证码的注册方法
        success, message = self._auth.register_with_phone(phone, password, code, nickname)
        
        if success:
            self._show_success(message + "，请登录")
            self.register_success.emit()
        else:
            self._show_error(message)
        
        self._reg_phone_btn.setText("注 册")
        self._reg_phone_btn.setEnabled(True)
    
    def _do_email_register(self):
        email = self._reg_email_input.text().strip()
        code = self._reg_email_code.text().strip()
        password = self._reg_email_password.text()
        password2 = self._reg_email_password2.text()
        nickname = self._reg_email_nickname.text().strip()
        
        if not email:
            self._show_error("请输入邮箱")
            return
        if not code:
            self._show_error("请输入验证码")
            return
        if not password:
            self._show_error("请设置密码")
            return
        if password != password2:
            self._show_error("两次密码不一致")
            return
        
        # 验证邮箱验证码
        verify_success, verify_message = email_service.verify_code(email, code)
        if not verify_success:
            self._show_error(verify_message)
            return
        
        self._reg_email_btn.setText("注册中...")
        self._reg_email_btn.setEnabled(False)
        
        success, message = self._auth.register_with_email(email, password, code, nickname)
        
        if success:
            self._show_success(message + "，请登录")
            self.register_success.emit()
        else:
            self._show_error(message)
        
        self._reg_email_btn.setText("注 册")
        self._reg_email_btn.setEnabled(True)
    
    def _show_error(self, message: str):
        QMessageBox.warning(self, "注册失败", message)
    
    def _show_success(self, message: str):
        QMessageBox.information(self, "注册成功", message)


class DeviceManagerDialog(QDialog):
    """设备管理对话框"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._auth = AuthService()
        self._device_fp = DeviceFingerprint()
        self._init_ui()
    
    def _init_ui(self):
        self.setWindowTitle("设备管理")
        self.setMinimumSize(500, 400)
        self.setStyleSheet("""
            QDialog {
                background-color: #1a1a1a;
            }
            QLabel {
                color: #ffffff;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        
        title = QLabel("已绑定设备")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)
        
        info = QLabel(f"每个账号最多可绑定 {AuthService.MAX_DEVICES} 台设备")
        info.setStyleSheet("color: #808080; font-size: 13px;")
        layout.addWidget(info)
        
        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["设备名称", "首次绑定", "最后使用", "操作"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.setStyleSheet("""
            QTableWidget {
                background-color: #252525;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                gridline-color: #333333;
            }
            QTableWidget::item {
                padding: 8px;
            }
            QHeaderView::section {
                background-color: #1a1a1a;
                color: #808080;
                padding: 10px;
                border: none;
                border-bottom: 1px solid #333333;
            }
        """)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self._table)
        
        self._load_devices()
        
        close_btn = ModernButton("关闭", primary=False)
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)
    
    def _load_devices(self):
        devices = self._auth.get_my_devices()
        current_device = self._device_fp.generate()
        
        self._table.setRowCount(len(devices))
        
        for i, device in enumerate(devices):
            from datetime import datetime
            
            self._table.setItem(i, 0, QTableWidgetItem(device.device_name))
            self._table.setItem(i, 1, QTableWidgetItem(
                datetime.fromtimestamp(device.first_seen).strftime("%Y-%m-%d %H:%M")
            ))
            self._table.setItem(i, 2, QTableWidgetItem(
                datetime.fromtimestamp(device.last_seen).strftime("%Y-%m-%d %H:%M")
            ))
            
            if device.device_id == current_device:
                label = QLabel("当前设备")
                label.setStyleSheet("color: #1e6bde;")
                self._table.setCellWidget(i, 3, label)
            else:
                btn = QPushButton("解绑")
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: #dc2626;
                        color: white;
                        border: none;
                        border-radius: 4px;
                        padding: 6px 12px;
                    }
                    QPushButton:hover {
                        background-color: #b91c1c;
                    }
                """)
                btn.clicked.connect(lambda checked, d=device.device_id: self._remove_device(d))
                self._table.setCellWidget(i, 3, btn)
    
    def _remove_device(self, device_id: str):
        reply = QMessageBox.question(
            self, "确认解绑", "确定要解绑此设备吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            success, message = self._auth.remove_device(device_id)
            if success:
                self._load_devices()
            else:
                QMessageBox.warning(self, "解绑失败", message)


class LoginWindow(QWidget):
    """登录窗口"""
    
    login_success = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        self._auth = AuthService()
        self._init_ui()
    
    def _init_ui(self):
        self.setWindowTitle("拾光剪影 - 登录")
        self.setMinimumSize(900, 600)
        self.setStyleSheet("""
            QWidget {
                background-color: #0a0a0a;
            }
        """)
        
        layout = QHBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)
        
        left_panel = self._create_left_panel()
        layout.addWidget(left_panel, 1)
        
        right_panel = self._create_right_panel()
        layout.addWidget(right_panel, 1)
    
    def _create_left_panel(self) -> QWidget:
        panel = QWidget()
        panel.setStyleSheet("""
            QWidget {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #1e6bde, stop:1 #6366f1);
            }
        """)
        
        layout = QVBoxLayout(panel)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        logo_container = QWidget()
        logo_layout = QVBoxLayout(logo_container)
        logo_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        logo = LogoWidget()
        logo_layout.addWidget(logo, alignment=Qt.AlignmentFlag.AlignCenter)
        
        app_name = QLabel("拾光剪影")
        app_name.setStyleSheet("""
            font-size: 32px;
            font-weight: bold;
            color: white;
            margin-top: 20px;
        """)
        app_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_layout.addWidget(app_name)
        
        app_desc = QLabel("专业级短视频创作工具")
        app_desc.setStyleSheet("""
            font-size: 16px;
            color: rgba(255, 255, 255, 0.8);
            margin-top: 10px;
        """)
        app_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_layout.addWidget(app_desc)
        
        features = QLabel("🎬 智能剪辑  ✍️ AI文案  📊 数据分析  🔌 插件扩展")
        features.setStyleSheet("""
            font-size: 14px;
            color: rgba(255, 255, 255, 0.6);
            margin-top: 30px;
        """)
        features.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_layout.addWidget(features)
        
        layout.addWidget(logo_container)
        
        return panel
    
    def _create_right_panel(self) -> QWidget:
        panel = QWidget()
        panel.setStyleSheet("background-color: #0a0a0a;")
        
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(60, 40, 60, 40)
        
        self._stack = QStackedWidget()
        
        self._login_widget = LoginWidget()
        self._login_widget.login_success.connect(self._on_login_success)
        
        self._register_widget = RegisterWidget()
        self._register_widget.register_success.connect(self._switch_to_login)
        
        self._stack.addWidget(self._login_widget)
        self._stack.addWidget(self._register_widget)
        
        layout.addWidget(self._stack)
        
        switch_layout = QHBoxLayout()
        switch_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self._switch_label = QLabel("还没有账号？")
        self._switch_label.setStyleSheet("color: #808080; font-size: 13px;")
        switch_layout.addWidget(self._switch_label)
        
        self._switch_btn = QPushButton("立即注册")
        self._switch_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #1e6bde;
                border: none;
                font-size: 13px;
                text-decoration: underline;
            }
            QPushButton:hover {
                color: #3b82f6;
            }
        """)
        self._switch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._switch_btn.clicked.connect(self._toggle_panel)
        switch_layout.addWidget(self._switch_btn)
        
        layout.addLayout(switch_layout)
        
        return panel
    
    def _toggle_panel(self):
        if self._stack.currentIndex() == 0:
            self._stack.setCurrentIndex(1)
            self._switch_label.setText("已有账号？")
            self._switch_btn.setText("立即登录")
        else:
            self._stack.setCurrentIndex(0)
            self._switch_label.setText("还没有账号？")
            self._switch_btn.setText("立即注册")
    
    def _switch_to_login(self):
        self._stack.setCurrentIndex(0)
        self._switch_label.setText("还没有账号？")
        self._switch_btn.setText("立即注册")
    
    def _on_login_success(self):
        self.login_success.emit()
    
    def try_auto_login(self) -> bool:
        """尝试自动登录"""
        return self._auth.try_auto_login()
    
    def show_device_manager(self):
        """显示设备管理"""
        dialog = DeviceManagerDialog(self)
        dialog.exec()


class ActivationWindow(QWidget):
    """授权激活窗口"""
    
    activation_success = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        self._auth = AuthService()
        self._init_ui()
    
    def _init_ui(self):
        self.setWindowTitle("拾光剪影 - 授权激活")
        self.setMinimumSize(600, 400)
        self.setStyleSheet("""
            QWidget {
                background-color: #0a0a0a;
            }
            QLabel {
                color: #ffffff;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)
        
        title = QLabel("授权激活")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #ffffff;")
        layout.addWidget(title)
        
        subtitle = QLabel("输入激活码以解锁全部功能")
        subtitle.setStyleSheet("font-size: 14px; color: #808080;")
        layout.addWidget(subtitle)
        
        layout.addSpacing(20)
        
        # 激活码输入
        code_layout = QVBoxLayout()
        code_layout.setSpacing(10)
        
        code_label = QLabel("激活码:")
        code_label.setStyleSheet("font-size: 13px; color: #ffffff;")
        code_layout.addWidget(code_label)
        
        self._code_input = ModernLineEdit("请输入16位激活码")
        code_layout.addWidget(self._code_input)
        
        layout.addLayout(code_layout)
        
        # 激活按钮
        self._activate_btn = ModernButton("激 活")
        self._activate_btn.clicked.connect(self._do_activate)
        layout.addWidget(self._activate_btn)
        
        # 提示信息
        hint = QLabel("提示：激活码将绑定当前设备，每个激活码最多可激活3台设备")
        hint.setStyleSheet("font-size: 12px; color: #666666;")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        
        layout.addStretch()
    
    def _do_activate(self):
        code = self._code_input.text().strip()
        
        if not code:
            QMessageBox.warning(self, "激活失败", "请输入激活码")
            return
        
        if len(code) != 16:
            QMessageBox.warning(self, "激活失败", "激活码格式不正确，请输入16位激活码")
            return
        
        # 这里应该调用实际的激活逻辑
        # 暂时模拟激活成功
        self._activate_btn.setText("激活中...")
        self._activate_btn.setEnabled(False)
        
        # 模拟激活过程
        import time
        time.sleep(1)
        
        # 模拟激活成功
        QMessageBox.information(self, "激活成功", "授权激活成功！")
        self.activation_success.emit()
        self.close()

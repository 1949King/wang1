"""0
设置模块 (SettingsModule)
=========================
包含快捷键设置、主题设置、字体大小调节等功能
"""

import os
import json
from typing import Dict, Optional, List, Any
from dataclasses import dataclass
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QGridLayout, QComboBox, QSpinBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
    QFormLayout, QCheckBox, QMessageBox, QDialog, QDialogButtonBox,
    QKeySequenceEdit, QColorDialog, QSlider, QTabWidget, QLineEdit
)
from PyQt6.QtCore import Qt, pyqtSignal, QSettings
from PyQt6.QtGui import QFont, QColor, QKeySequence


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


@dataclass
class ShortcutItem:
    """快捷键项"""
    name: str
    action: str
    default_shortcut: str
    current_shortcut: str = ""
    
    def __post_init__(self):
        if not self.current_shortcut:
            self.current_shortcut = self.default_shortcut


class ShortcutEditor(QKeySequenceEdit):
    """快捷键编辑器"""
    
    def __init__(self, shortcut: str = "", parent=None):
        super().__init__(parent)
        if shortcut:
            self.setKeySequence(QKeySequence(shortcut))
        self.setMinimumWidth(150)
        self.setStyleSheet("""
            QKeySequenceEdit {
                background-color: #1a1a1a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 6px 10px;
            }
            QKeySequenceEdit:focus {
                border-color: #1e6bde;
            }
        """)


class SettingsModule(QWidget):
    """设置模块"""
    
    settings_changed = pyqtSignal(str, object)
    
    DEFAULT_SHORTCUTS = [
        ShortcutItem("剪切", "cut", "Ctrl+X"),
        ShortcutItem("复制", "copy", "Ctrl+C"),
        ShortcutItem("粘贴", "paste", "Ctrl+V"),
        ShortcutItem("删除", "delete", "Delete"),
        ShortcutItem("切割", "split", "Ctrl+B"),
        ShortcutItem("导入", "import", "Ctrl+I"),
        ShortcutItem("导出", "export", "Ctrl+E"),
        ShortcutItem("保存", "save", "Ctrl+S"),
        ShortcutItem("撤销", "undo", "Ctrl+Z"),
        ShortcutItem("重做", "redo", "Ctrl+Y"),
        ShortcutItem("全选", "select_all", "Ctrl+A"),
        ShortcutItem("查找", "find", "Ctrl+F"),
        ShortcutItem("播放/暂停", "play_pause", "Space"),
        ShortcutItem("上一帧", "prev_frame", "Left"),
        ShortcutItem("下一帧", "next_frame", "Right"),
        ShortcutItem("跳转开头", "go_start", "Home"),
        ShortcutItem("跳转结尾", "go_end", "End"),
        ShortcutItem("标记入点", "mark_in", "I"),
        ShortcutItem("标记出点", "mark_out", "O"),
        ShortcutItem("清除标记", "clear_mark", "C"),
    ]
    
    THEMES = {
        "dark": "深色主题",
        "light": "浅色主题",
        "auto": "跟随系统"
    }
    
    FONT_SIZES = [10, 11, 12, 13, 14, 15, 16, 18, 20, 22, 24]
    
    def __init__(self):
        super().__init__()
        self._settings = QSettings("拾光剪影", "Settings")
        self._shortcuts: Dict[str, ShortcutItem] = {}
        self._shortcut_editors: Dict[str, ShortcutEditor] = {}
        self._init_ui()
        self._load_settings()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        header = QFrame()
        header.setStyleSheet("background-color: #1a1a1a; border-bottom: 1px solid #333333;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 15, 20, 15)
        
        title = QLabel("⚙️ 设置")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        header_layout.addWidget(title)
        
        header_layout.addStretch()
        
        layout.addWidget(header)
        
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet("""
            QTabWidget::pane {
                border: none;
                background-color: #0a0a0a;
            }
            QTabBar::tab {
                background-color: #1a1a1a;
                color: #ffffff;
                border: none;
                padding: 12px 24px;
                font-size: 14px;
            }
            QTabBar::tab:selected {
                color: #1e6bde;
                background-color: #0a0a0a;
                border-bottom: 2px solid #1e6bde;
            }
            QTabBar::tab:hover:!selected {
                color: #ffffff;
            }
        """)
        
        scroll1 = QScrollArea()
        scroll1.setWidgetResizable(True)
        scroll1.setWidget(self._create_shortcut_tab())
        self._tabs.addTab(scroll1, "⌨️ 快捷键")
        
        scroll2 = QScrollArea()
        scroll2.setWidgetResizable(True)
        scroll2.setWidget(self._create_theme_tab())
        self._tabs.addTab(scroll2, "🎨 主题")
        
        scroll3 = QScrollArea()
        scroll3.setWidgetResizable(True)
        scroll3.setWidget(self._create_font_tab())
        self._tabs.addTab(scroll3, "🔤 字体")
        
        scroll4 = QScrollArea()
        scroll4.setWidgetResizable(True)
        scroll4.setWidget(self._create_general_tab())
        self._tabs.addTab(scroll4, "⚙️ 常规")
        
        scroll5 = QScrollArea()
        scroll5.setWidgetResizable(True)
        scroll5.setWidget(self._create_account_tab())
        self._tabs.addTab(scroll5, "👤 账号")
        
        scroll6 = QScrollArea()
        scroll6.setWidgetResizable(True)
        scroll6.setWidget(self._create_email_tab())
        self._tabs.addTab(scroll6, "📧 邮箱设置")
        
        layout.addWidget(self._tabs)
        
        bottom_bar = QFrame()
        bottom_bar.setStyleSheet("background-color: #1a1a1a; border-top: 1px solid #333333;")
        bottom_layout = QHBoxLayout(bottom_bar)
        bottom_layout.setContentsMargins(20, 10, 20, 10)
        
        reset_btn = QPushButton("恢复默认")
        reset_btn.clicked.connect(self._reset_all)
        reset_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 6px;
                padding: 8px 20px;
            }
            QPushButton:hover {
                background-color: #2a2a2a;
                color: #ffffff;
            }
        """)
        bottom_layout.addWidget(reset_btn)
        
        bottom_layout.addStretch()
        
        save_btn = QPushButton("保存设置")
        save_btn.clicked.connect(self._save_settings)
        save_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e6bde;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 24px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1a5bc4;
            }
        """)
        bottom_layout.addWidget(save_btn)
        
        layout.addWidget(bottom_bar)
    
    def _create_shortcut_tab(self) -> QWidget:
        """创建快捷键设置标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        desc = QLabel("双击快捷键区域可以修改快捷键，按 Esc 取消修改")
        desc.setStyleSheet("color: #ffffff; font-size: 13px;")
        layout.addWidget(desc)
        
        self._shortcut_table = QTableWidget()
        self._shortcut_table.setColumnCount(4)
        self._shortcut_table.setHorizontalHeaderLabels(["操作", "快捷键", "默认值", "操作"])
        self._shortcut_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._shortcut_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self._shortcut_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._shortcut_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self._shortcut_table.setColumnWidth(1, 180)
        self._shortcut_table.setColumnWidth(2, 120)
        self._shortcut_table.setColumnWidth(3, 100)
        self._shortcut_table.setStyleSheet("""
            QTableWidget {
                background-color: #1a1a1a;
                color: #ffffff;
                gridline-color: #333333;
                border: 1px solid #333333;
                border-radius: 8px;
            }
            QTableWidget::item {
                padding: 8px;
            }
            QTableWidget::item:selected {
                background-color: #1e6bde;
            }
            QHeaderView::section {
                background-color: #2a2a2a;
                color: #ffffff;
                padding: 10px;
                border: none;
                border-bottom: 1px solid #333333;
            }
        """)
        
        self._shortcut_table.setRowCount(len(self.DEFAULT_SHORTCUTS))
        
        for i, item in enumerate(self.DEFAULT_SHORTCUTS):
            self._shortcuts[item.action] = ShortcutItem(
                name=item.name,
                action=item.action,
                default_shortcut=item.default_shortcut,
                current_shortcut=item.current_shortcut
            )
            
            name_item = QTableWidgetItem(item.name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._shortcut_table.setItem(i, 0, name_item)
            
            shortcut_editor = ShortcutEditor(item.default_shortcut)
            self._shortcut_editors[item.action] = shortcut_editor
            self._shortcut_table.setCellWidget(i, 1, shortcut_editor)
            
            default_item = QTableWidgetItem(item.default_shortcut)
            default_item.setFlags(default_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            default_item.setForeground(QColor("#ffffff"))
            self._shortcut_table.setItem(i, 2, default_item)
            
            reset_btn = QPushButton("重置")
            reset_btn.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    color: #1e6bde;
                    border: none;
                }
                QPushButton:hover {
                    color: #3b82f6;
                }
            """)
            reset_btn.clicked.connect(lambda checked, a=item.action, s=item.default_shortcut: self._reset_shortcut(a, s))
            self._shortcut_table.setCellWidget(i, 3, reset_btn)
        
        layout.addWidget(self._shortcut_table)
        
        return widget
    
    def _create_theme_tab(self) -> QWidget:
        """创建主题设置标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)
        
        theme_group = QGroupBox("主题设置")
        theme_group.setStyleSheet("color: #ffffff;")
        theme_layout = QFormLayout(theme_group)
        
        self._theme_combo = QComboBox()
        self._theme_combo.addItems(self.THEMES.values())
        self._theme_combo.setCurrentIndex(0)
        self._theme_combo.setMinimumWidth(200)
        self._theme_combo.setStyleSheet("color: #ffffff; background-color: #1a1a1a; border: 1px solid #333333;")
        theme_layout.addRow("主题:", self._theme_combo)
        
        layout.addWidget(theme_group)
        
        color_group = QGroupBox("自定义颜色")
        color_group.setStyleSheet("color: #ffffff;")
        color_layout = QGridLayout(color_group)
        
        colors = [
            ("主色调", "primary", "#1e6bde"),
            ("背景色", "background", "#0a0a0a"),
            ("文字颜色", "text", "#ffffff"),
            ("边框颜色", "border", "#333333"),
            ("高亮颜色", "highlight", "#2a2a2a"),
            ("警告颜色", "warning", "#f59e0b"),
            ("成功颜色", "success", "#22c55e"),
            ("错误颜色", "error", "#ef4444"),
        ]
        
        self._color_buttons: Dict[str, QPushButton] = {}
        
        for i, (name, key, default) in enumerate(colors):
            row = i // 2
            col = i % 2
            
            color_widget = QWidget()
            color_h_layout = QHBoxLayout(color_widget)
            color_h_layout.setContentsMargins(0, 0, 0, 0)
            
            label = QLabel(name)
            label.setMinimumWidth(80)
            label.setStyleSheet("color: #ffffff;")
            color_h_layout.addWidget(label)
            
            color_btn = QPushButton()
            color_btn.setFixedSize(60, 30)
            color_btn.setStyleSheet(f"background-color: {default}; border: 1px solid #333333; border-radius: 4px;")
            color_btn.clicked.connect(lambda checked, k=key, b=color_btn: self._pick_color(k, b))
            color_h_layout.addWidget(color_btn)
            
            self._color_buttons[key] = color_btn
            color_layout.addWidget(color_widget, row, col)
        
        layout.addWidget(color_group)
        
        layout.addStretch()
        
        return widget
    
    def _create_font_tab(self) -> QWidget:
        """创建字体设置标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)
        
        font_group = QGroupBox("字体设置")
        font_group.setStyleSheet("color: #ffffff;")
        font_layout = QFormLayout(font_group)
        
        self._font_size_combo = QComboBox()
        self._font_size_combo.addItems([str(s) for s in self.FONT_SIZES])
        self._font_size_combo.setCurrentIndex(4)
        self._font_size_combo.setMinimumWidth(100)
        self._font_size_combo.setStyleSheet("color: #ffffff; background-color: #1a1a1a; border: 1px solid #333333;")
        font_layout.addRow("字体大小:", self._font_size_combo)
        
        self._font_family_combo = QComboBox()
        self._font_family_combo.addItems([
            "Microsoft YaHei",
            "Segoe UI",
            "PingFang SC",
            "Source Han Sans",
            "Noto Sans CJK",
            "Arial",
            "Helvetica"
        ])
        self._font_family_combo.setMinimumWidth(200)
        self._font_family_combo.setStyleSheet("color: #ffffff; background-color: #1a1a1a; border: 1px solid #333333;")
        font_layout.addRow("字体:", self._font_family_combo)
        
        layout.addWidget(font_group)
        
        preview_group = QGroupBox("预览")
        preview_group.setStyleSheet("color: #ffffff;")
        preview_layout = QVBoxLayout(preview_group)
        
        self._preview_label = QLabel("这是一段预览文字\nThe quick brown fox jumps over the lazy dog")
        self._preview_label.setStyleSheet("font-size: 14px; padding: 20px; color: #ffffff;")
        preview_layout.addWidget(self._preview_label)
        
        layout.addWidget(preview_group)
        
        self._font_size_combo.currentIndexChanged.connect(self._update_preview)
        self._font_family_combo.currentIndexChanged.connect(self._update_preview)
        
        layout.addStretch()
        
        return widget
    
    def _create_general_tab(self) -> QWidget:
        """创建常规设置标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)
        
        startup_group = QGroupBox("启动设置")
        startup_group.setStyleSheet("color: #ffffff;")
        startup_layout = QFormLayout(startup_group)
        
        self._auto_start_check = QCheckBox("开机自动启动")
        self._auto_start_check.setStyleSheet("color: #ffffff;")
        startup_layout.addRow(self._auto_start_check)
        
        self._auto_login_check = QCheckBox("自动登录")
        self._auto_login_check.setChecked(True)
        self._auto_login_check.setStyleSheet("color: #ffffff;")
        startup_layout.addRow(self._auto_login_check)
        
        self._remember_window_check = QCheckBox("记住窗口大小和位置")
        self._remember_window_check.setChecked(True)
        self._remember_window_check.setStyleSheet("color: #ffffff;")
        startup_layout.addRow(self._remember_window_check)
        
        layout.addWidget(startup_group)
        
        project_group = QGroupBox("项目设置")
        project_group.setStyleSheet("color: #ffffff;")
        project_layout = QFormLayout(project_group)
        
        self._auto_save_check = QCheckBox("自动保存")
        self._auto_save_check.setChecked(True)
        self._auto_save_check.setStyleSheet("color: #ffffff;")
        project_layout.addRow(self._auto_save_check)
        
        self._auto_save_interval = QSpinBox()
        self._auto_save_interval.setRange(30, 600)
        self._auto_save_interval.setValue(300)
        self._auto_save_interval.setSuffix(" 秒")
        self._auto_save_interval.setStyleSheet("color: #ffffff; background-color: #1a1a1a; border: 1px solid #333333;")
        project_layout.addRow("保存间隔:", self._auto_save_interval)
        
        layout.addWidget(project_group)
        
        performance_group = QGroupBox("性能设置")
        performance_group.setStyleSheet("color: #ffffff;")
        performance_layout = QFormLayout(performance_group)
        
        self._max_threads_spin = QSpinBox()
        self._max_threads_spin.setRange(1, 32)
        self._max_threads_spin.setValue(15)
        self._max_threads_spin.setStyleSheet("color: #ffffff; background-color: #1a1a1a; border: 1px solid #333333;")
        performance_layout.addRow("最大线程数:", self._max_threads_spin)
        
        self._gpu_accel_check = QCheckBox("启用 GPU 加速")
        self._gpu_accel_check.setChecked(True)
        self._gpu_accel_check.setStyleSheet("color: #ffffff;")
        performance_layout.addRow(self._gpu_accel_check)
        
        self._cache_size_spin = QSpinBox()
        self._cache_size_spin.setRange(100, 10000)
        self._cache_size_spin.setValue(1000)
        self._cache_size_spin.setSuffix(" MB")
        self._cache_size_spin.setStyleSheet("color: #ffffff; background-color: #1a1a1a; border: 1px solid #333333;")
        performance_layout.addRow("缓存大小:", self._cache_size_spin)
        
        layout.addWidget(performance_group)
        
        layout.addStretch()
        
        return widget
    
    def _create_account_tab(self) -> QWidget:
        """创建账号管理标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)
        
        from .auth import auth_service
        
        user = auth_service.current_user
        
        account_group = QGroupBox("账号信息")
        account_layout = QFormLayout(account_group)
        
        if user:
            self._user_id_label = QLabel(user.id[:8] + "...")
            account_layout.addRow("用户ID:", self._user_id_label)
            
            account_type = "手机号" if user.phone else "邮箱"
            account_value = user.phone if user.phone else user.email
            self._account_label = QLabel(account_value)
            account_layout.addRow(f"{account_type}:", self._account_label)
            
            self._nickname_label = QLabel(user.nickname or "未设置")
            account_layout.addRow("昵称:", self._nickname_label)
            
            vip_status = "VIP会员" if user.is_vip else "普通用户"
            self._vip_label = QLabel(vip_status)
            self._vip_label.setStyleSheet("color: #f59e0b;" if user.is_vip else "color: #ffffff;")
            account_layout.addRow("会员状态:", self._vip_label)
        else:
            self._user_id_label = QLabel("未登录")
            account_layout.addRow("状态:", self._user_id_label)
        
        layout.addWidget(account_group)
        
        device_group = QGroupBox("设备管理")
        device_layout = QVBoxLayout(device_group)
        
        device_info = QLabel(f"每个账号最多可绑定 {3} 台设备")
        device_info.setStyleSheet("color: #ffffff; font-size: 13px;")
        device_layout.addWidget(device_info)
        
        self._device_table = QTableWidget()
        self._device_table.setColumnCount(3)
        self._device_table.setHorizontalHeaderLabels(["设备名称", "最后活跃", "操作"])
        self._device_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._device_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._device_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._device_table.setColumnWidth(2, 80)
        self._device_table.setStyleSheet("""
            QTableWidget {
                background-color: #1a1a1a;
                color: #ffffff;
                gridline-color: #333333;
                border: 1px solid #333333;
                border-radius: 6px;
            }
            QTableWidget::item {
                padding: 8px;
            }
            QHeaderView::section {
                background-color: #2a2a2a;
                color: #ffffff;
                padding: 8px;
                border: none;
                border-bottom: 1px solid #333333;
            }
        """)
        
        if user and user.devices:
            self._device_table.setRowCount(len(user.devices))
            for i, device_id in enumerate(user.devices):
                name_item = QTableWidgetItem(f"设备 {i+1}")
                name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._device_table.setItem(i, 0, name_item)
                
                time_item = QTableWidgetItem("当前设备" if i == 0 else "其他设备")
                time_item.setFlags(time_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._device_table.setItem(i, 1, time_item)
                
                if i > 0:
                    unbind_btn = QPushButton("解绑")
                    unbind_btn.setStyleSheet("""
                        QPushButton {
                            background-color: transparent;
                            color: #ef4444;
                            border: none;
                        }
                        QPushButton:hover {
                            color: #f87171;
                        }
                    """)
                    unbind_btn.clicked.connect(lambda checked, d=device_id: self._unbind_device(d))
                    self._device_table.setCellWidget(i, 2, unbind_btn)
                else:
                    current_label = QLabel("当前")
                    current_label.setStyleSheet("color: #22c55e;")
                    current_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    self._device_table.setCellWidget(i, 2, current_label)
        else:
            self._device_table.setRowCount(1)
            no_device = QTableWidgetItem("暂无绑定设备")
            no_device.setFlags(no_device.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._device_table.setItem(0, 0, no_device)
            self._device_table.setSpan(0, 0, 1, 3)
        
        device_layout.addWidget(self._device_table)
        layout.addWidget(device_group)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        if user:
            logout_btn = QPushButton("退出登录")
            logout_btn.clicked.connect(self._logout)
            logout_btn.setStyleSheet("""
                QPushButton {
                    background-color: #ef4444;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    padding: 10px 24px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #dc2626;
                }
            """)
            btn_layout.addWidget(logout_btn)
        else:
            login_btn = QPushButton("登录账号")
            login_btn.clicked.connect(self._show_login)
            login_btn.setStyleSheet("""
                QPushButton {
                    background-color: #1e6bde;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    padding: 10px 24px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #1a5bc4;
                }
            """)
            btn_layout.addWidget(login_btn)
        
        layout.addLayout(btn_layout)
        layout.addStretch()
        
        return widget
    
    def _unbind_device(self, device_id: str):
        """解绑设备"""
        from .auth import auth_service
        
        reply = QMessageBox.question(
            self, "确认解绑",
            "确定要解绑此设备吗？解绑后该设备将无法使用此账号。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            success = auth_service.unbind_device(device_id)
            if success:
                QMessageBox.information(self, "成功", "设备已解绑")
                self._refresh_account_tab()
            else:
                QMessageBox.warning(self, "失败", "解绑失败，请重试")
    
    def _logout(self):
        """退出登录"""
        from .auth import auth_service
        
        reply = QMessageBox.question(
            self, "确认退出",
            "确定要退出登录吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            auth_service.logout()
            QMessageBox.information(self, "已退出", "已退出登录，部分功能将受限")
            self._refresh_account_tab()
    
    def _show_login(self):
        """显示登录窗口"""
        from .login_window import LoginWindow
        from .auth import auth_service
        
        self._login_window = LoginWindow()
        
        login_done = [False]
        login_success = [False]
        
        def on_login_success():
            login_success[0] = True
            self._login_window.close()
        
        def on_finished():
            login_done[0] = True
        
        self._login_window.login_success.connect(on_login_success)
        self._login_window.finished.connect(on_finished)
        self._login_window.show()
        
        while not login_done[0]:
            from PyQt6.QtWidgets import QApplication
            QApplication.processEvents()
        
        if login_success[0]:
            self._refresh_account_tab()
    
    def _refresh_account_tab(self):
        """刷新账号标签页"""
        scroll = self._tabs.widget(4)
        if scroll:
            old_widget = scroll.takeWidget()
            if old_widget:
                old_widget.deleteLater()
            scroll.setWidget(self._create_account_tab())
    
    def _pick_color(self, key: str, button: QPushButton):
        """选择颜色"""
        current_color = button.palette().button().color()
        color = QColorDialog.getColor(current_color, self, "选择颜色")
        if color.isValid():
            button.setStyleSheet(f"background-color: {color.name()}; border: 1px solid #333333; border-radius: 4px;")
    
    def _update_preview(self):
        """更新字体预览"""
        size = int(self._font_size_combo.currentText())
        family = self._font_family_combo.currentText()
        self._preview_label.setStyleSheet(f"font-size: {size}px; font-family: '{family}'; padding: 20px;")
    
    def _reset_shortcut(self, action: str, default: str):
        """重置单个快捷键"""
        if action in self._shortcut_editors:
            self._shortcut_editors[action].setKeySequence(QKeySequence(default))
    
    def _reset_all(self):
        """重置所有设置"""
        reply = QMessageBox.question(
            self, "确认重置",
            "确定要恢复所有设置为默认值吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            for action, editor in self._shortcut_editors.items():
                default = self._shortcuts[action].default_shortcut
                editor.setKeySequence(QKeySequence(default))
            
            self._theme_combo.setCurrentIndex(0)
            self._font_size_combo.setCurrentIndex(4)
            self._font_family_combo.setCurrentIndex(0)
            
            QMessageBox.information(self, "成功", "已恢复默认设置")
    
    def _load_settings(self):
        """加载设置"""
        theme = self._settings.value("theme", "dark")
        if theme in self.THEMES:
            index = list(self.THEMES.keys()).index(theme)
            self._theme_combo.setCurrentIndex(index)
        
        font_size = self._settings.value("font_size", 14, type=int)
        index = self.FONT_SIZES.index(font_size) if font_size in self.FONT_SIZES else 4
        self._font_size_combo.setCurrentIndex(index)
        
        font_family = self._settings.value("font_family", "Microsoft YaHei")
        index = self._font_family_combo.findText(font_family)
        if index >= 0:
            self._font_family_combo.setCurrentIndex(index)
        
        shortcuts = self._settings.value("shortcuts", {})
        if shortcuts:
            for action, shortcut in shortcuts.items():
                if action in self._shortcut_editors:
                    self._shortcut_editors[action].setKeySequence(QKeySequence(shortcut))
    
    def _save_settings(self):
        """保存设置"""
        theme_key = list(self.THEMES.keys())[self._theme_combo.currentIndex()]
        self._settings.setValue("theme", theme_key)
        
        font_size = int(self._font_size_combo.currentText())
        self._settings.setValue("font_size", font_size)
        
        font_family = self._font_family_combo.currentText()
        self._settings.setValue("font_family", font_family)
        
        shortcuts = {}
        for action, editor in self._shortcut_editors.items():
            shortcuts[action] = editor.keySequence().toString()
        self._settings.setValue("shortcuts", shortcuts)
        
        self._settings.setValue("auto_login", self._auto_login_check.isChecked())
        self._settings.setValue("auto_save", self._auto_save_check.isChecked())
        self._settings.setValue("auto_save_interval", self._auto_save_interval.value())
        self._settings.setValue("max_threads", self._max_threads_spin.value())
        self._settings.setValue("gpu_accel", self._gpu_accel_check.isChecked())
        
        self.settings_changed.emit("all", {
            "theme": theme_key,
            "font_size": font_size,
            "font_family": font_family,
            "shortcuts": shortcuts
        })
        
        QMessageBox.information(self, "成功", "设置已保存，部分设置需要重启应用生效")
    
    def get_shortcut(self, action: str) -> str:
        """获取快捷键"""
        if action in self._shortcut_editors:
            return self._shortcut_editors[action].keySequence().toString()
        return ""
    
    def get_theme(self) -> str:
        """获取主题"""
        return list(self.THEMES.keys())[self._theme_combo.currentIndex()]
    
    def get_font_size(self) -> int:
        """获取字体大小"""
        return int(self._font_size_combo.currentText())
    
    def get_font_family(self) -> str:
        """获取字体"""
        return self._font_family_combo.currentText()
    
    def _create_email_tab(self) -> QWidget:
        """创建邮箱设置标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)
        
        from .email_verify import email_verification_service, SMTP_PRESETS
        
        email_group = QGroupBox("邮箱验证设置")
        email_group.setStyleSheet("color: #ffffff;")
        email_layout = QFormLayout(email_group)
        
        # 预设选择
        self._smtp_preset_combo = QComboBox()
        self._smtp_preset_combo.addItems(list(SMTP_PRESETS.keys()))
        self._smtp_preset_combo.setMinimumWidth(200)
        self._smtp_preset_combo.setStyleSheet("color: #ffffff; background-color: #1a1a1a; border: 1px solid #333333;")
        self._smtp_preset_combo.currentIndexChanged.connect(self._on_smtp_preset_changed)
        email_layout.addRow("邮箱服务商:", self._smtp_preset_combo)
        
        # SMTP服务器
        self._smtp_host_input = ModernLineEdit("SMTP服务器地址")
        email_layout.addRow("SMTP服务器:", self._smtp_host_input)
        
        # 端口
        self._smtp_port_spin = QSpinBox()
        self._smtp_port_spin.setRange(1, 65535)
        self._smtp_port_spin.setValue(465)
        self._smtp_port_spin.setStyleSheet("color: #ffffff; background-color: #1a1a1a; border: 1px solid #333333;")
        email_layout.addRow("端口:", self._smtp_port_spin)
        
        # 用户名
        self._smtp_username_input = ModernLineEdit("邮箱账号")
        email_layout.addRow("邮箱账号:", self._smtp_username_input)
        
        # 密码
        self._smtp_password_input = ModernLineEdit("邮箱密码/授权码", QLineEdit.EchoMode.Password)
        email_layout.addRow("密码/授权码:", self._smtp_password_input)
        
        # 发件人名称
        self._smtp_sender_input = ModernLineEdit("发件人名称")
        email_layout.addRow("发件人名称:", self._smtp_sender_input)
        
        # SSL选项
        self._smtp_ssl_check = QCheckBox("使用SSL")
        self._smtp_ssl_check.setChecked(True)
        self._smtp_ssl_check.setStyleSheet("color: #ffffff;")
        email_layout.addRow(self._smtp_ssl_check)
        
        layout.addWidget(email_group)
        
        # 测试按钮
        test_btn = QPushButton("测试连接")
        test_btn.clicked.connect(self._test_smtp_connection)
        test_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e6bde;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 24px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1a5bc4;
            }
        """)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(test_btn)
        layout.addLayout(btn_layout)
        
        # 状态信息
        self._smtp_status_label = QLabel("SMTP 配置状态: 未配置")
        self._smtp_status_label.setStyleSheet("color: #f59e0b; font-size: 13px;")
        layout.addWidget(self._smtp_status_label)
        
        # 加载现有配置
        self._load_smtp_config()
        
        layout.addStretch()
        
        return widget
    
    def _on_smtp_preset_changed(self):
        """处理SMTP预设变更"""
        from .email_verify import SMTP_PRESETS
        
        preset_name = self._smtp_preset_combo.currentText()
        if preset_name in SMTP_PRESETS:
            preset = SMTP_PRESETS[preset_name]
            self._smtp_host_input.setText(preset.host)
            self._smtp_port_spin.setValue(preset.port)
            self._smtp_sender_input.setText(preset.sender_name)
            self._smtp_ssl_check.setChecked(preset.use_ssl)
    
    def _load_smtp_config(self):
        """加载SMTP配置"""
        from .email_verify import email_verification_service
        
        if email_verification_service._config:
            config = email_verification_service._config
            self._smtp_host_input.setText(config.host)
            self._smtp_port_spin.setValue(config.port)
            self._smtp_username_input.setText(config.username)
            self._smtp_password_input.setText(config.password)
            self._smtp_sender_input.setText(config.sender_name)
            self._smtp_ssl_check.setChecked(config.use_ssl)
            self._smtp_status_label.setText("SMTP 配置状态: 已配置")
            self._smtp_status_label.setStyleSheet("color: #22c55e; font-size: 13px;")
    
    def _test_smtp_connection(self):
        """测试SMTP连接"""
        from .email_verify import email_verification_service, SMTPConfig
        
        host = self._smtp_host_input.text().strip()
        port = self._smtp_port_spin.value()
        username = self._smtp_username_input.text().strip()
        password = self._smtp_password_input.text()
        sender_name = self._smtp_sender_input.text().strip()
        use_ssl = self._smtp_ssl_check.isChecked()
        
        if not host or not username or not password:
            QMessageBox.warning(self, "测试失败", "请填写完整的SMTP配置")
            return
        
        # 保存配置
        config = SMTPConfig(
            host=host,
            port=port,
            username=username,
            password=password,
            sender_name=sender_name or "AI短剧编辑器",
            use_ssl=use_ssl
        )
        
        if email_verification_service.save_config(config):
            QMessageBox.information(self, "测试成功", "SMTP配置保存成功，连接测试通过！")
            self._smtp_status_label.setText("SMTP 配置状态: 已配置")
            self._smtp_status_label.setStyleSheet("color: #22c55e; font-size: 13px;")
        else:
            QMessageBox.warning(self, "测试失败", "SMTP配置保存失败，请检查配置信息")
    
    def _save_settings(self):
        """保存设置"""
        theme_key = list(self.THEMES.keys())[self._theme_combo.currentIndex()]
        self._settings.setValue("theme", theme_key)
        
        font_size = int(self._font_size_combo.currentText())
        self._settings.setValue("font_size", font_size)
        
        font_family = self._font_family_combo.currentText()
        self._settings.setValue("font_family", font_family)
        
        shortcuts = {}
        for action, editor in self._shortcut_editors.items():
            shortcuts[action] = editor.keySequence().toString()
        self._settings.setValue("shortcuts", shortcuts)
        
        self._settings.setValue("auto_login", self._auto_login_check.isChecked())
        self._settings.setValue("auto_save", self._auto_save_check.isChecked())
        self._settings.setValue("auto_save_interval", self._auto_save_interval.value())
        self._settings.setValue("max_threads", self._max_threads_spin.value())
        self._settings.setValue("gpu_accel", self._gpu_accel_check.isChecked())
        
        # 保存SMTP配置
        from .email_verify import email_verification_service, SMTPConfig
        
        host = self._smtp_host_input.text().strip()
        port = self._smtp_port_spin.value()
        username = self._smtp_username_input.text().strip()
        password = self._smtp_password_input.text()
        sender_name = self._smtp_sender_input.text().strip()
        use_ssl = self._smtp_ssl_check.isChecked()
        
        if host and username and password:
            config = SMTPConfig(
                host=host,
                port=port,
                username=username,
                password=password,
                sender_name=sender_name or "AI短剧编辑器",
                use_ssl=use_ssl
            )
            email_verification_service.save_config(config)
        
        self.settings_changed.emit("all", {
            "theme": theme_key,
            "font_size": font_size,
            "font_family": font_family,
            "shortcuts": shortcuts
        })
        
        QMessageBox.information(self, "成功", "设置已保存，部分设置需要重启应用生效")


class HelpModule(QWidget):
    """帮助模块"""
    
    def __init__(self):
        super().__init__()
        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        header = QFrame()
        header.setStyleSheet("background-color: #1a1a1a; border-bottom: 1px solid #333333;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 15, 20, 15)
        
        title = QLabel("❓ 帮助")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        header_layout.addWidget(title)
        
        header_layout.addStretch()
        
        api_doc_btn = QPushButton("📚 API文档")
        api_doc_btn.clicked.connect(self._open_api_documentation)
        api_doc_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e6bde;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1a5bc4;
            }
        """)
        header_layout.addWidget(api_doc_btn)
        
        layout.addWidget(header)
        
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet("""
            QTabWidget::pane {
                border: none;
                background-color: #0a0a0a;
            }
            QTabBar::tab {
                background-color: #1a1a1a;
                color: #ffffff;
                border: none;
                padding: 12px 24px;
                font-size: 14px;
            }
            QTabBar::tab:selected {
                color: #1e6bde;
                background-color: #0a0a0a;
                border-bottom: 2px solid #1e6bde;
            }
            QTabBar::tab:hover:!selected {
                color: #ffffff;
            }
        """)
        
        scroll1 = QScrollArea()
        scroll1.setWidgetResizable(True)
        scroll1.setWidget(self._create_quick_start_tab())
        self._tabs.addTab(scroll1, "🚀 快速入门")
        
        scroll2 = QScrollArea()
        scroll2.setWidgetResizable(True)
        scroll2.setWidget(self._create_features_tab())
        self._tabs.addTab(scroll2, "📖 功能说明")
        
        scroll3 = QScrollArea()
        scroll3.setWidgetResizable(True)
        scroll3.setWidget(self._create_faq_tab())
        self._tabs.addTab(scroll3, "❓ 常见问题")
        
        scroll4 = QScrollArea()
        scroll4.setWidgetResizable(True)
        scroll4.setWidget(self._create_api_resource_tab())
        self._tabs.addTab(scroll4, "🔗 API资源")
        
        scroll5 = QScrollArea()
        scroll5.setWidgetResizable(True)
        scroll5.setWidget(self._create_about_tab())
        self._tabs.addTab(scroll5, "ℹ️ 关于")
        
        layout.addWidget(self._tabs)
    
    def _create_quick_start_tab(self) -> QWidget:
        """创建快速入门标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(15)
        
        # 文档标题
        title_label = QLabel("🚀 快速入门指南")
        title_label.setStyleSheet("font-size: 20px; font-weight: bold; color: #333333;")
        layout.addWidget(title_label)
        
        # 简介
        intro_label = QLabel("本指南将帮助您快速上手AI短剧编辑器，从账号注册到视频发布的完整流程。")
        intro_label.setStyleSheet("color: #666666; font-size: 14px;")
        intro_label.setWordWrap(True)
        layout.addWidget(intro_label)
        
        # 可折叠的步骤
        class CollapsibleSection(QWidget):
            def __init__(self, title, content, parent=None):
                super().__init__(parent)
                self._is_expanded = False
                self._setup_ui(title, content)
            
            def _setup_ui(self, title, content):
                layout = QVBoxLayout(self)
                layout.setContentsMargins(0, 0, 0, 0)
                layout.setSpacing(0)
                
                # 标题栏
                self._header = QWidget()
                self._header.setStyleSheet("""
                    QWidget {
                        background-color: #ffffff;
                        border: 1px solid #e8e8e8;
                        border-radius: 8px;
                        padding: 12px 16px;
                    }
                """)
                header_layout = QHBoxLayout(self._header)
                header_layout.setContentsMargins(0, 0, 0, 0)
                header_layout.setSpacing(10)
                
                self._title_label = QLabel(title)
                self._title_label.setStyleSheet("font-size: 14px; font-weight: 600; color: #333333;")
                header_layout.addWidget(self._title_label)
                
                self._toggle_btn = QPushButton("▼")
                self._toggle_btn.setStyleSheet("""
                    QPushButton {
                        background: transparent;
                        color: #666666;
                        border: none;
                        font-size: 12px;
                        padding: 0;
                        min-width: 20px;
                    }
                """)
                self._toggle_btn.clicked.connect(self._toggle)
                header_layout.addStretch()
                header_layout.addWidget(self._toggle_btn)
                
                # 内容区域
                self._content = QWidget()
                self._content.setStyleSheet("""
                    QWidget {
                        background-color: #ffffff;
                        border: 1px solid #e8e8e8;
                        border-top: none;
                        border-bottom-left-radius: 8px;
                        border-bottom-right-radius: 8px;
                        padding: 16px;
                    }
                """)
                content_layout = QVBoxLayout(self._content)
                
                content_label = QLabel(content)
                content_label.setStyleSheet("color: #666666; font-size: 14px;")
                content_label.setWordWrap(True)
                content_layout.addWidget(content_label)
                
                layout.addWidget(self._header)
                layout.addWidget(self._content)
                
                self._content.hide()
            
            def _toggle(self):
                self._is_expanded = not self._is_expanded
                if self._is_expanded:
                    self._toggle_btn.setText("▲")
                    self._content.show()
                else:
                    self._toggle_btn.setText("▼")
                    self._content.hide()
        
        steps = [
            (
                "1️⃣ 登录账号", 
                "首次使用需要注册账号，支持手机号或QQ邮箱注册。每个账号最多绑定3台设备。\n\n"  
                "**操作步骤：**\n"  
                "1. 点击左上角的用户头像或「账号运营」模块\n"  
                "2. 点击「登录/注册」按钮\n"  
                "3. 选择注册方式（手机号或邮箱）\n"  
                "4. 输入验证码并设置密码\n"  
                "5. 完成注册后自动登录"  
                "\n**注意事项：**\n"  
                "- 每个账号最多可绑定3台设备\n"  
                "- 设备绑定后可在「设置」→「账号」中查看和解绑"
            ),
            (
                "2️⃣ API配置向导", 
                "通过向导流程快速配置云端API，获取最新接口信息并测试连接。\n\n"  
                "**操作步骤：**\n"  
                "1. 点击左侧导航栏的「帮助」模块\n"  
                "2. 点击顶部的「📚 API文档」按钮查看官方文档\n"  
                "3. 在「API资源」标签页中找到需要的API服务\n"  
                "4. 点击「复制地址」按钮复制API接口地址\n"  
                "5. 点击「跳转文档」按钮查看详细文档\n"  
                "6. 在「模型管理」→「云端API」中粘贴API地址并填写密钥\n"  
                "7. 点击「测试连接」验证配置是否成功"  
                "\n**配置技巧：**\n"  
                "- 复制地址后直接粘贴到配置框，避免手动输入错误\n"  
                "- 查看API示例了解正确的调用格式\n"  
                "- 保存模板以便下次快速配置" 
            ),
            (
                "3️⃣ Ollama 本地模型配置", 
                "Ollama 是一个开源的本地大模型运行工具，支持多种AI模型在本地运行。\n\n"
                "**下载安装：**\n"
                "1. 访问 Ollama 官网：https://ollama.com\n"
                "2. 根据操作系统下载对应版本：\n"
                "   - Windows：下载 .exe 安装包\n"
                "   - macOS：下载 .dmg 安装包\n"
                "   - Linux：使用命令 curl -fsSL https://ollama.com/install.sh | sh\n"
                "3. 安装完成后，Ollama 会自动在后台运行\n\n"
                "**模型拉取：**\n"
                "1. 打开命令行终端\n"
                "2. 拉取模型：ollama pull llama3（或其他模型）\n"
                "3. 查看已安装模型：ollama list\n"
                "4. 测试模型：ollama run llama3\n\n"
                "**在软件中配置：**\n"
                "1. 点击左侧导航栏的「模型管理」\n"
                "2. 点击「检测 Ollama 服务」按钮\n"
                "3. 系统会自动识别已安装的模型\n"
                "4. 选择需要的模型进行使用\n\n"
                "**推荐模型：**\n"
                "- llama3：通用对话模型，适合文案生成\n"
                "- deepseek-coder：代码生成模型\n"
                "- qwen：中文优化模型\n"
                "- mistral：轻量级高效模型\n\n"
                "**注意事项：**\n"
                "- 本地模型需要足够的内存（建议16GB以上）\n"
                "- 首次拉取模型需要下载，可能需要较长时间\n"
                "- 模型文件存储在 ~/.ollama/models 目录"
            ),
            (
                "4️⃣ OpenClaw 自动化配置", 
                "OpenClaw 是一个强大的自动化工具，支持多平台账号管理和自动化操作。\n\n"
                "**下载安装：**\n"
                "1. 访问 OpenClaw 官方仓库或下载页面\n"
                "2. 下载最新版本的 OpenClaw\n"
                "3. 解压到本地目录\n"
                "4. 运行安装脚本或配置环境变量\n\n"
                "**基础配置：**\n"
                "1. 在软件中点击「模型管理」→「OpenClaw」标签页\n"
                "2. 配置 OpenClaw 路径：\n"
                "   - Windows：C:\\Program Files\\OpenClaw\\openclaw.exe\n"
                "   - macOS：/usr/local/bin/openclaw\n"
                "   - Linux：/usr/bin/openclaw\n"
                "3. 点击「检测服务」验证安装\n"
                "4. 配置自动化参数\n\n"
                "**账号绑定：**\n"
                "1. 在「账号运营」模块中添加平台账号\n"
                "2. 选择要绑定的平台（抖音、快手、小红书等）\n"
                "3. 扫码或输入账号信息完成绑定\n"
                "4. OpenClaw 会自动管理账号状态\n\n"
                "**自动化任务：**\n"
                "- 自动发布：定时发布内容到多个平台\n"
                "- 数据采集：自动采集账号运营数据\n"
                "- 评论管理：自动回复评论\n"
                "- 粉丝互动：自动点赞、关注等操作\n\n"
                "**安全提示：**\n"
                "- 不要在公共网络环境下使用自动化功能\n"
                "- 定期更新 OpenClaw 到最新版本\n"
                "- 遵守各平台的使用规范，避免账号被封"
            ),
            (
                "5️⃣ 云端 API 配置", 
                "配置云端AI服务API，享受更强大的AI能力，无需本地硬件支持。\n\n"
                "**支持的平台：**\n"
                "- DeepSeek：国产大模型，性价比高\n"
                "- 豆包（字节跳动）：中文优化，适合内容创作\n"
                "- 智谱AI：通用大模型，功能全面\n"
                "- 通义千问（阿里）：中文理解能力强\n"
                "- 文心一言（百度）：知识问答能力强\n\n"
                "**配置步骤：**\n"
                "1. 注册对应平台账号\n"
                "2. 获取 API Key：\n"
                "   - 登录平台官网\n"
                "   - 进入开发者中心或API管理页面\n"
                "   - 创建新的API Key\n"
                "3. 在软件中配置：\n"
                "   - 点击「模型管理」→「云端API」\n"
                "   - 选择对应平台\n"
                "   - 输入API Key和接口地址\n"
                "   - 点击「测试连接」验证\n\n"
                "**API地址格式：**\n"
                "- DeepSeek：https://api.deepseek.com/v1\n"
                "- 豆包：https://ark.cn-beijing.volces.com/api/v3\n"
                "- 智谱：https://open.bigmodel.cn/api/paas/v4\n\n"
                "**费用说明：**\n"
                "- DeepSeek：按token计费，新用户有免费额度\n"
                "- 豆包：按调用次数计费，有免费试用\n"
                "- 智谱：按token计费，新用户赠送tokens\n\n"
                "**使用建议：**\n"
                "- 文案生成：推荐豆包或DeepSeek\n"
                "- 代码生成：推荐DeepSeek或智谱\n"
                "- 知识问答：推荐文心一言或智谱"
            ),
            (
                "6️⃣ 导入素材", 
                "在「素材库」中导入视频、音频、图片等素材文件。\n\n"  
                "**操作步骤：**\n"  
                "1. 点击左侧导航栏的「素材库」\n"  
                "2. 点击「导入本地素材」按钮\n"  
                "3. 选择要导入的素材文件（支持 MP4、AVI、MOV、MP3、JPG、PNG 等格式）\n"  
                "4. 素材会自动分类到对应的标签页中"  
                "\n**素材类型：**\n"  
                "- 视频素材\n"  
                "- 音频素材（背景音乐、音效）\n"  
                "- 图片素材（封面、水印）\n"  
                "- 字幕素材（SRT 文件）\n"  
                "- 模板素材（预设效果）" 
            ),
            (
                "7️⃣ 开始剪辑", 
                "在「剪辑」模块中进行视频剪辑、添加字幕、应用滤镜等操作。\n\n"  
                "**操作步骤：**\n"  
                "1. 点击左侧导航栏的「剪辑」\n"  
                "2. 从素材库中拖拽视频到时间线\n"  
                "3. 使用工具栏进行剪辑操作：\n"  
                "   - 剪切（Ctrl+X）\n"  
                "   - 复制（Ctrl+C）\n"  
                "   - 粘贴（Ctrl+V）\n"  
                "   - 切割（Ctrl+B）\n"  
                "   - 删除（Delete）\n"  
                "4. 在右侧工具栏中调整视频参数、添加滤镜、转场效果等"  
                "\n**核心功能：**\n"  
                "- 时间线编辑\n"  
                "- 视频调节（亮度、对比度、饱和度）\n"  
                "- 音频处理（音量、淡入淡出）\n"  
                "- 字幕添加与编辑\n"  
                "- 滤镜与转场效果" 
            ),
            (
                "8️⃣ AI 辅助", 
                "使用「文案生成」模块自动生成标题、描述、脚本等内容。\n\n"  
                "**操作步骤：**\n"  
                "1. 点击左侧导航栏的「文案生成」\n"  
                "2. 输入视频内容描述或关键词\n"  
                "3. 选择目标平台（抖音、快手、视频号等）\n"  
                "4. 选择内容风格（爆款、剧情、解说等）\n"  
                "5. 选择 AI 模型\n"  
                "6. 点击「生成文案」按钮"  
                "\n**生成内容：**\n"  
                "- 吸引人的标题\n"  
                "- 详细的视频描述\n"  
                "- 相关话题标签\n"  
                "- 完整的视频脚本" 
            ),
            (
                "9️⃣ 导出发布", 
                "完成编辑后导出视频，或使用「账号运营」模块自动发布到各平台。\n\n"  
                "**导出步骤：**\n"  
                "1. 在「剪辑」模块中点击「导出」按钮\n"  
                "2. 选择输出模式（30秒爆款、90秒剧情、8分钟长视频）\n"  
                "3. 选择分辨率和目标平台\n"  
                "4. 点击「开始导出」\n"  
                "\n**发布步骤：**\n"  
                "1. 点击左侧导航栏的「账号运营」\n"  
                "2. 在「内容发布」标签页中选择视频文件\n"  
                "3. 填写标题、描述等信息\n"  
                "4. 选择要发布的平台\n"  
                "5. 点击「发布内容」按钮" 
            ),
        ]
        
        for title, content in steps:
            section = CollapsibleSection(title, content)
            layout.addWidget(section)
        
        layout.addStretch()
        
        return widget
    
    def _create_features_tab(self) -> QWidget:
        """创建功能说明标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(15)
        
        features = [
            (
                "🏠 首页", 
                "**功能说明：**\n"  
                "- 快速入口：一键访问各个功能模块\n"  
                "- 统计仪表盘：显示今日处理视频数、生成文案数等统计数据\n"  
                "- 最近项目：快速打开最近编辑的项目\n"  
                "- 模板中心：提供预设的视频模板\n"  
                "\n**操作指南：**\n"  
                "- 点击模块图标进入对应功能\n"  
                "- 查看统计数据了解工作进展\n"  
                "- 点击最近项目快速恢复编辑"
            ),
            (
                "🎬 剪辑", 
                "**功能说明：**\n"  
                "- 视频剪辑：切割、删除、复制、粘贴视频片段\n"  
                "- 音频剪辑：音量调节、淡入淡出、音频增强\n"  
                "- 字幕编辑：AI生成字幕、手动添加字幕\n"  
                "- 特效滤镜：应用各种视频滤镜和转场效果\n"  
                "- 时间轴：可视化编辑界面\n"  
                "\n**操作指南：**\n"  
                "- 拖拽素材到时间线\n"  
                "- 使用快捷键进行剪辑操作\n"  
                "- 在右侧面板调整视频参数\n"  
                "- 预览窗口实时查看效果"
            ),
            (
                "✍️ 文案生成", 
                "**功能说明：**\n"  
                "- AI文案：基于视频内容生成吸引人的文案\n"  
                "- 标题生成：创建爆款标题\n"  
                "- 脚本生成：自动生成视频脚本\n"  
                "- 多平台适配：针对不同平台优化内容\n"  
                "\n**操作指南：**\n"  
                "- 输入视频内容描述\n"  
                "- 选择目标平台和风格\n"  
                "- 点击生成按钮获取AI文案\n"  
                "- 复制生成的内容到剪贴板"
            ),
            (
                "📋 多任务", 
                "**功能说明：**\n"  
                "- 批量处理：同时处理多个视频\n"  
                "- 任务队列：管理待处理任务\n"  
                "- 进度监控：实时查看任务进度\n"  
                "- 错误处理：自动处理和报告错误\n"  
                "\n**操作指南：**\n"  
                "- 点击「新建任务」创建新任务\n"  
                "- 选择任务类型和参数\n"  
                "- 查看任务列表和进度\n"  
                "- 暂停或取消正在执行的任务"
            ),
            (
                "🎭 短剧筛选", 
                "**功能说明：**\n"  
                "- 剧单管理：浏览和管理短剧资源\n"  
                "- 热度分析：查看短剧热度数据\n"  
                "- 佣金统计：显示短剧推广佣金\n"  
                "- 推荐系统：基于数据推荐优质短剧\n"  
                "\n**操作指南：**\n"  
                "- 选择平台和分类筛选短剧\n"  
                "- 按热度、播放量等排序\n"  
                "- 搜索特定短剧\n"  
                "- 查看短剧详情和佣金信息"
            ),
            (
                "👤 账号运营", 
                "**功能说明：**\n"  
                "- 多平台管理：管理多个平台账号\n"  
                "- 矩阵发布：一键发布到多个平台\n"  
                "- 数据采集：收集账号运营数据\n"  
                "- 智能回复：自动回复评论\n"  
                "\n**操作指南：**\n"  
                "- 绑定各平台账号\n"  
                "- 配置发布参数\n"  
                "- 查看账号数据看板\n"  
                "- 设置智能回复规则"
            ),
            (
                "📁 素材库", 
                "**功能说明：**\n"  
                "- 素材分类：按类型组织素材\n"  
                "- 预览：查看素材内容\n"  
                "- 搜索：快速找到需要的素材\n"  
                "- 标签管理：为素材添加标签\n"  
                "\n**操作指南：**\n"  
                "- 导入本地素材\n"  
                "- 浏览在线素材库\n"  
                "- 使用搜索功能查找素材\n"  
                "- 拖拽素材到剪辑模块"
            ),
            (
                "🧩 插件商店", 
                "**功能说明：**\n"  
                "- 插件/Skill浏览：查看可用的插件\n"  
                "- 安装：添加新插件\n"  
                "- 卸载：移除不需要的插件\n"  
                "- 导入：导入本地插件\n"  
                "\n**操作指南：**\n"  
                "- 浏览插件列表\n"  
                "- 点击安装按钮添加插件\n"  
                "- 启用或禁用插件\n"  
                "- 配置插件参数"
            ),
            (
                "📊 性能监控", 
                "**功能说明：**\n"  
                "- CPU/内存/GPU监控：实时监控系统资源使用\n"  
                "- 任务状态：查看当前任务状态\n"  
                "- 日志查看：查看系统运行日志\n"  
                "\n**操作指南：**\n"  
                "- 查看资源使用情况\n"  
                "- 分析系统性能瓶颈\n"  
                "- 查看运行日志排查问题\n"  
                "- 优化系统设置提高性能"
            ),
            (
                "🤖 模型管理", 
                "**功能说明：**\n"  
                "- Ollama本地模型：管理本地AI模型\n"  
                "- 云端API：配置云端AI服务\n"  
                "- OpenClaw自动化：设置自动化工作流\n"  
                "\n**操作指南：**\n"  
                "- 检测和管理Ollama服务\n"  
                "- 拉取和更新本地模型\n"  
                "- 配置云端API密钥\n"  
                "- 测试模型连接状态"
            ),
        ]
        
        for icon_name, desc in features:
            feature_frame = QFrame()
            feature_frame.setStyleSheet("""
                QFrame {
                    background-color: #1a1a1a;
                    border-radius: 6px;
                    padding: 12px;
                }
            """)
            feature_layout = QHBoxLayout(feature_frame)
            
            name_label = QLabel(icon_name)
            name_label.setStyleSheet("font-size: 14px; font-weight: bold;")
            name_label.setMinimumWidth(120)
            feature_layout.addWidget(name_label)
            
            desc_label = QLabel(desc)
            desc_label.setStyleSheet("color: #ffffff; font-size: 13px;")
            desc_label.setWordWrap(True)
            feature_layout.addWidget(desc_label)
            
            layout.addWidget(feature_frame)
        
        layout.addStretch()
        
        return widget
    
    def _create_faq_tab(self) -> QWidget:
        """创建常见问题标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(15)
        
        faqs = [
            (
                "Q: 如何使用本地大模型？", 
                "A: **详细步骤：**\n"  
                "1. 下载并安装 Ollama（官网：https://ollama.com）\n"  
                "2. 启动 Ollama 服务\n"  
                "3. 在软件中点击「模型管理」模块\n"  
                "4. 点击「检测 Ollama 服务」按钮\n"  
                "5. 在模型列表中选择需要的模型（如 llama3、deepseek-coder 等）\n"  
                "6. 点击「拉取模型」按钮等待下载完成\n"  
                "7. 模型下载完成后即可在各模块中使用"  
                "\n**注意事项：**\n"  
                "- 本地模型需要足够的磁盘空间\n"  
                "- 首次使用需要下载模型，可能需要较长时间\n"  
                "- 大模型对系统配置要求较高，建议至少 16GB 内存"
            ),
            (
                "Q: 如何配置云端 API？", 
                "A: **详细步骤：**\n"  
                "1. 注册对应 AI 平台账号（如 DeepSeek、豆包、智谱等）\n"  
                "2. 在平台获取 API Key\n"  
                "3. 在软件中点击「模型管理」模块\n"  
                "4. 切换到「云端 API」标签页\n"  
                "5. 选择要配置的平台\n"  
                "6. 输入 API Key\n"  
                "7. 点击「测试连接」按钮验证配置是否成功"  
                "\n**推荐平台：**\n"  
                "- DeepSeek：代码和文案生成能力强\n"  
                "- 豆包：中文理解能力优秀\n"  
                "- 智谱：多模态能力出色"
            ),
            (
                "Q: 视频导出失败怎么办？", 
                "A: **排查步骤：**\n"  
                "1. 检查 FFmpeg 是否正确安装：\n"  
                "   - 下载 FFmpeg 并添加到系统环境变量\n"  
                "   - 或在设置中指定 FFmpeg 路径\n"  
                "2. 查看错误日志：\n"  
                "   - 点击「性能监控」模块\n"  
                "   - 在「运行日志」中查看详细错误信息\n"  
                "3. 常见问题及解决方案：\n"  
                "   - 内存不足：关闭其他应用程序\n"  
                "   - 磁盘空间不足：清理磁盘空间\n"  
                "   - 视频编码问题：尝试不同的输出格式\n"  
                "   - 权限问题：以管理员身份运行软件"
            ),
            (
                "Q: 如何添加更多设备？", 
                "A: **详细步骤：**\n"  
                "1. 每个账号最多可绑定 3 台设备\n"  
                "2. 解绑设备流程：\n"  
                "   - 点击「设置」模块\n"  
                "   - 切换到「账号」标签页\n"  
                "   - 在「设备管理」中找到要解绑的设备\n"  
                "   - 点击「解绑」按钮\n"  
                "   - 确认解绑操作\n"  
                "3. 解绑后即可在新设备上登录"  
                "\n**注意事项：**\n"  
                "- 解绑设备后，该设备上的账号将被登出\n"  
                "- 请确保解绑的是不需要的设备"
            ),
            (
                "Q: 插件安装后无法使用？", 
                "A: **排查步骤：**\n"  
                "1. 检查插件状态：\n"  
                "   - 点击「插件中心」模块\n"  
                "   - 确认插件状态为「已启用」\n"  
                "2. 检查依赖要求：\n"  
                "   - 查看插件详情页的依赖说明\n"  
                "   - 安装缺少的依赖包\n"  
                "3. 重启软件：\n"  
                "   - 有些插件需要重启后才能生效\n"  
                "4. 检查日志：\n"  
                "   - 查看「性能监控」中的运行日志\n"  
                "   - 寻找插件相关的错误信息"  
                "\n**常见问题：**\n"  
                "- Python 依赖缺失：使用 pip 安装所需包\n"  
                "- 权限不足：以管理员身份运行软件\n"  
                "- 版本不兼容：更新插件到最新版本"
            ),
            (
                "Q: 如何自定义快捷键？", 
                "A: **详细步骤：**\n"  
                "1. 点击左下角「设置」按钮\n"  
                "2. 切换到「快捷键」标签页\n"  
                "3. 找到要修改的操作\n"  
                "4. 双击「快捷键」列的对应单元格\n"  
                "5. 按下新的快捷键组合\n"  
                "6. 按 Enter 确认修改\n"  
                "7. 点击「保存设置」按钮"  
                "\n**注意事项：**\n"  
                "- 避免与系统快捷键冲突\n"  
                "- 可以使用 Ctrl、Shift、Alt 组合键\n"  
                "- 按 Esc 取消修改"
            ),
            (
                "Q: 如何提高视频编辑性能？", 
                "A: **优化建议：**\n"  
                "1. 硬件优化：\n"  
                "   - 启用 GPU 加速（设置 → 常规 → 性能设置）\n"  
                "   - 增加内存（建议 16GB 以上）\n"  
                "   - 使用 SSD 存储\n"  
                "2. 软件设置：\n"  
                "   - 调整缓存大小（设置 → 常规 → 性能设置）\n"  
                "   - 优化线程数（根据 CPU 核心数调整）\n"  
                "   - 降低预览质量（编辑时）\n"  
                "3. 编辑技巧：\n"  
                "   - 分段编辑长视频\n"  
                "   - 合理使用代理文件\n"  
                "   - 及时清理无用素材"
            ),
            (
                "Q: 如何使用 AI 工具进行视频处理？", 
                "A: **详细步骤：**\n"  
                "1. 在「剪辑」模块中导入视频\n"  
                "2. 切换到右侧工具栏的「AI工具」标签页\n"  
                "3. 选择要使用的 AI 工具：\n"  
                "   - FunClip：自动剪辑、智能分段、生成字幕\n"  
                "   - AutoClip：高光识别、多镜头组接\n"  
                "   - VideoFusion：视频修复、增强\n"  
                "   - LoRA Edit：创意编辑、物体替换\n"  
                "4. 点击「开始处理」按钮\n"  
                "5. 等待处理完成后查看效果"  
                "\n**注意事项：**\n"  
                "- AI 处理可能需要较长时间\n"  
                "- 处理效果取决于原始视频质量\n"  
                "- 建议在处理前备份原始视频"
            ),
        ]
        
        for question, answer in faqs:
            faq_frame = QFrame()
            faq_frame.setStyleSheet("""
                QFrame {
                    background-color: #1a1a1a;
                    border-radius: 8px;
                    padding: 15px;
                }
            """)
            faq_layout = QVBoxLayout(faq_frame)
            
            q_label = QLabel(question)
            q_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #1e6bde;")
            faq_layout.addWidget(q_label)
            
            a_label = QLabel(answer)
            a_label.setStyleSheet("color: #ffffff; font-size: 13px;")
            a_label.setWordWrap(True)
            faq_layout.addWidget(a_label)
            
            layout.addWidget(faq_frame)
        
        layout.addStretch()
        
        return widget
    
    def _open_api_documentation(self):
        """打开API文档"""
        import webbrowser
        webbrowser.open("https://api.shortplayai.com/docs")
    
    def _create_api_resource_tab(self) -> QWidget:
        """创建API资源标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)
        
        # API资源汇总标题
        title = QLabel("API资源汇总")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)
        
        # API资源列表
        api_resources = [
            {
                "name": "DeepSeek API",
                "url": "https://api.deepseek.com/v1/chat/completions",
                "docs": "https://platform.deepseek.com/docs/api",
                "apply": "https://platform.deepseek.com/account/api-keys",
                "examples": """curl -X POST https://api.deepseek.com/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{"model": "deepseek-chat", "messages": [{"role": "user", "content": "Hello"}]}'""",
                "errors": """401: Unauthorized - API Key无效\n429: Too Many Requests - 调用频率过高\n500: Internal Server Error - 服务器错误"""
            },
            {
                "name": "豆包 API",
                "url": "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
                "docs": "https://www.doubao.com/docs/api",
                "apply": "https://www.doubao.com/console/apikeys",
                "examples": """curl -X POST https://ark.cn-beijing.volces.com/api/v3/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{"model": "ep-20240101123456-abcde", "messages": [{"role": "user", "content": "Hello"}]}'""",
                "errors": """401: Unauthorized - API Key无效\n429: Too Many Requests - 调用频率过高\n500: Internal Server Error - 服务器错误"""
            },
            {
                "name": "OpenAI API",
                "url": "https://api.openai.com/v1/chat/completions",
                "docs": "https://platform.openai.com/docs/api-reference/chat",
                "apply": "https://platform.openai.com/api-keys",
                "examples": """curl -X POST https://api.openai.com/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{"model": "gpt-3.5-turbo", "messages": [{"role": "user", "content": "Hello"}]}'""",
                "errors": """401: Unauthorized - API Key无效\n429: Too Many Requests - 调用频率过高\n500: Internal Server Error - 服务器错误"""
            },
            {
                "name": "智谱 AI API",
                "url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
                "docs": "https://bigmodel.cn/docs/api",
                "apply": "https://bigmodel.cn/usercenter/apikeys",
                "examples": """curl -X POST https://open.bigmodel.cn/api/paas/v4/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{"model": "glm-4", "messages": [{"role": "user", "content": "Hello"}]}'""",
                "errors": """401: Unauthorized - API Key无效\n429: Too Many Requests - 调用频率过高\n500: Internal Server Error - 服务器错误"""
            },
            {
                "name": "通义千问 API",
                "url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
                "docs": "https://help.aliyun.com/zh/dashscope/developer-reference/api-details",
                "apply": "https://dashscope.console.aliyun.com/apiKey",
                "examples": """curl -X POST https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{"model": "qwen-turbo", "messages": [{"role": "user", "content": "Hello"}]}'""",
                "errors": """401: Unauthorized - API Key无效\n429: Too Many Requests - 调用频率过高\n500: Internal Server Error - 服务器错误"""
            },
            {
                "name": "文心一言 API",
                "url": "https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat/eb-instant",
                "docs": "https://cloud.baidu.com/doc/WENXINWORKSHOP/s/alj562vvu",
                "apply": "https://console.bce.baidu.com/ai/#/ai/wenxinworkshop/overview/resource/getApiKey",
                "examples": """curl -X POST https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat/eb-instant \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{"messages": [{"role": "user", "content": "Hello"}]}'""",
                "errors": """401: Unauthorized - API Key无效\n429: Too Many Requests - 调用频率过高\n500: Internal Server Error - 服务器错误"""
            },
            {
                "name": "讯飞星火 API",
                "url": "https://spark-api-open.xf-yun.com/v1/chat/completions",
                "docs": "https://www.xfyun.cn/doc/spark/Web.html",
                "apply": "https://console.xfyun.cn/services/cbm",
                "examples": """curl -X POST https://spark-api-open.xf-yun.com/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{"model": "generalv3.5", "messages": [{"role": "user", "content": "Hello"}]}'""",
                "errors": """401: Unauthorized - API Key无效\n429: Too Many Requests - 调用频率过高\n500: Internal Server Error - 服务器错误"""
            },
            {
                "name": "Kimi API",
                "url": "https://api.moonshot.cn/v1/chat/completions",
                "docs": "https://platform.moonshot.cn/docs/api",
                "apply": "https://platform.moonshot.cn/console/api-keys",
                "examples": """curl -X POST https://api.moonshot.cn/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{"model": "moonshot-v1-8k", "messages": [{"role": "user", "content": "Hello"}]}'""",
                "errors": """401: Unauthorized - API Key无效\n429: Too Many Requests - 调用频率过高\n500: Internal Server Error - 服务器错误"""
            },
            {
                "name": "百川 API",
                "url": "https://api.baichuan-ai.com/v1/chat/completions",
                "docs": "https://platform.baichuan-ai.com/docs/api",
                "apply": "https://platform.baichuan-ai.com/console/apikey",
                "examples": """curl -X POST https://api.baichuan-ai.com/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{"model": "Baichuan4", "messages": [{"role": "user", "content": "Hello"}]}'""",
                "errors": """401: Unauthorized - API Key无效\n429: Too Many Requests - 调用频率过高\n500: Internal Server Error - 服务器错误"""
            },
            {
                "name": "MiniMax API",
                "url": "https://api.minimax.chat/v1/chat/completions",
                "docs": "https://api.minimax.chat/docs/chat/completions",
                "apply": "https://platform.minimax.chat/apikeys",
                "examples": """curl -X POST https://api.minimax.chat/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{"model": "abab6.5-chat", "messages": [{"role": "user", "content": "Hello"}]}'""",
                "errors": """401: Unauthorized - API Key无效\n429: Too Many Requests - 调用频率过高\n500: Internal Server Error - 服务器错误"""
            },
            {
                "name": "Claude API",
                "url": "https://api.anthropic.com/v1/messages",
                "docs": "https://docs.anthropic.com/claude/reference/messages_post",
                "apply": "https://console.anthropic.com/settings/keys",
                "examples": """curl -X POST https://api.anthropic.com/v1/messages \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{"model": "claude-3-5-sonnet-20241022", "messages": [{"role": "user", "content": "Hello"}]}'""",
                "errors": """401: Unauthorized - API Key无效\n429: Too Many Requests - 调用频率过高\n500: Internal Server Error - 服务器错误"""
            },
            {
                "name": "Groq API",
                "url": "https://api.groq.com/openai/v1/chat/completions",
                "docs": "https://docs.groq.com/reference/chat-completions",
                "apply": "https://console.groq.com/keys",
                "examples": """curl -X POST https://api.groq.com/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{"model": "llama-3.3-70b-versatile", "messages": [{"role": "user", "content": "Hello"}]}'""",
                "errors": """401: Unauthorized - API Key无效\n429: Too Many Requests - 调用频率过高\n500: Internal Server Error - 服务器错误"""
            },
            {
                "name": "硅基流动 API",
                "url": "https://api.siliconflow.cn/v1/chat/completions",
                "docs": "https://cloud.siliconflow.cn/docs/api",
                "apply": "https://cloud.siliconflow.cn/account/api-keys",
                "examples": """curl -X POST https://api.siliconflow.cn/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{"model": "Qwen/Qwen2.5-72B-Instruct", "messages": [{"role": "user", "content": "Hello"}]}'""",
                "errors": """401: Unauthorized - API Key无效\n429: Too Many Requests - 调用频率过高\n500: Internal Server Error - 服务器错误"""
            },
            {
                "name": "阶跃星辰 API",
                "url": "https://api.stepfun.com/v1/chat/completions",
                "docs": "https://platform.stepfun.com/docs/api",
                "apply": "https://platform.stepfun.com/console/apikeys",
                "examples": """curl -X POST https://api.stepfun.com/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{"model": "step-1-8k", "messages": [{"role": "user", "content": "Hello"}]}'""",
                "errors": """401: Unauthorized - API Key无效\n429: Too Many Requests - 调用频率过高\n500: Internal Server Error - 服务器错误"""
            },
            {
                "name": "零一万物 API",
                "url": "https://api.lingyiwanwu.com/v1/chat/completions",
                "docs": "https://platform.lingyiwanwu.com/docs/api",
                "apply": "https://platform.lingyiwanwu.com/console/apikeys",
                "examples": """curl -X POST https://api.lingyiwanwu.com/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{"model": "yi-lightning", "messages": [{"role": "user", "content": "Hello"}]}'""",
                "errors": """401: Unauthorized - API Key无效\n429: Too Many Requests - 调用频率过高\n500: Internal Server Error - 服务器错误"""
            }
        ]
        
        for api in api_resources:
            api_frame = QFrame()
            api_frame.setStyleSheet("""
                QFrame {
                    background-color: #1a1a1a;
                    border-radius: 8px;
                    padding: 15px;
                }
            """)
            api_layout = QVBoxLayout(api_frame)
            
            # API名称
            api_name = QLabel(f"📡 {api['name']}")
            api_name.setStyleSheet("font-size: 16px; font-weight: bold;")
            api_layout.addWidget(api_name)
            
            # API地址
            url_layout = QHBoxLayout()
            url_label = QLabel("接口地址:")
            url_label.setStyleSheet("color: #ffffff; font-size: 14px;")
            url_label.setMinimumWidth(80)
            url_layout.addWidget(url_label)
            
            url_value = QLabel(api['url'])
            url_value.setStyleSheet("color: #ffffff; font-size: 14px;")
            url_value.setWordWrap(True)
            url_layout.addWidget(url_value)
            api_layout.addLayout(url_layout)
            
            # 操作按钮
            btn_layout = QHBoxLayout()
            btn_layout.setSpacing(10)
            
            # 跳转文档按钮
            doc_btn = QPushButton("跳转文档")
            doc_btn.clicked.connect(lambda checked, url=api['docs']: self._open_api_docs(url))
            doc_btn.setStyleSheet("""
                QPushButton {
                    background-color: #1e6bde;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 6px 12px;
                    font-size: 12px;
                }
                QPushButton:hover {
                    background-color: #1a5bc4;
                }
            """)
            btn_layout.addWidget(doc_btn)
            
            # 复制地址按钮
            copy_btn = QPushButton("复制地址")
            copy_btn.clicked.connect(lambda checked, url=api['url']: self._copy_api_url(url))
            copy_btn.setStyleSheet("""
                QPushButton {
                    background-color: #22c55e;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 6px 12px;
                    font-size: 12px;
                }
                QPushButton:hover {
                    background-color: #16a34a;
                }
            """)
            btn_layout.addWidget(copy_btn)
            
            # 查看示例按钮
            example_btn = QPushButton("查看示例")
            example_btn.clicked.connect(lambda checked, api=api: self._show_api_example(api))
            example_btn.setStyleSheet("""
                QPushButton {
                    background-color: #f59e0b;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 6px 12px;
                    font-size: 12px;
                }
                QPushButton:hover {
                    background-color: #d97706;
                }
            """)
            btn_layout.addWidget(example_btn)
            
            btn_layout.addStretch()
            api_layout.addLayout(btn_layout)
            
            layout.addWidget(api_frame)
        
        layout.addStretch()
        
        return widget
    
    def _open_api_docs(self, url):
        """打开API文档"""
        import webbrowser
        webbrowser.open(url)
    
    def _copy_api_url(self, url):
        """复制API地址"""
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(url)
        QMessageBox.information(self, "成功", "API地址已复制到剪贴板")
    
    def _show_api_example(self, api):
        """显示API调用示例和错误码"""
        dialog = QDialog(self)
        dialog.setWindowTitle(f"API示例 - {api['name']}")
        dialog.setMinimumWidth(600)
        dialog.setMinimumHeight(400)
        
        layout = QVBoxLayout(dialog)
        
        # 调用示例
        example_group = QGroupBox("调用示例")
        example_group.setStyleSheet("color: #ffffff;")
        example_layout = QVBoxLayout(example_group)
        
        example_text = QLabel(api['examples'])
        example_text.setStyleSheet("color: #ffffff; font-family: Consolas, Monaco, monospace; font-size: 12px;")
        example_text.setWordWrap(True)
        example_layout.addWidget(example_text)
        layout.addWidget(example_group)
        
        # 常见错误码
        error_group = QGroupBox("常见错误码")
        error_group.setStyleSheet("color: #ffffff;")
        error_layout = QVBoxLayout(error_group)
        
        error_text = QLabel(api['errors'])
        error_text.setStyleSheet("color: #ffffff; font-size: 13px;")
        error_text.setWordWrap(True)
        error_layout.addWidget(error_text)
        layout.addWidget(error_group)
        
        # 按钮
        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        btn_box.accepted.connect(dialog.accept)
        layout.addWidget(btn_box)
        
        dialog.exec()
    
    def _create_about_tab(self) -> QWidget:
        """创建关于标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        logo = QLabel("🎬 拾光剪影")
        logo.setStyleSheet("font-size: 28px; font-weight: bold;")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(logo)
        
        version = QLabel("版本: v3.0 Qt6版")
        version.setStyleSheet("color: #ffffff; font-size: 14px;")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version)
        
        layout.addSpacing(20)
        
        info_frame = QFrame()
        info_frame.setStyleSheet("""
            QFrame {
                background-color: #1a1a1a;
                border-radius: 8px;
                padding: 20px;
            }
        """)
        info_layout = QVBoxLayout(info_frame)
        
        info_items = [
            ("开发框架", "PyQt6 + Python 3.10+"),
            ("视频处理", "FFmpeg 6.0+"),
            ("AI 引擎", "Ollama / DeepSeek / 豆包 / OpenAI / 智谱"),
            ("自动化", "OpenClaw"),
            ("数据存储", "SQLite 本地数据库"),
        ]
        
        for name, value in info_items:
            item_layout = QHBoxLayout()
            name_label = QLabel(f"{name}:")
            name_label.setStyleSheet("color: #ffffff;")
            name_label.setMinimumWidth(100)
            item_layout.addWidget(name_label)
            
            value_label = QLabel(value)
            value_label.setStyleSheet("color: #ffffff;")
            item_layout.addWidget(value_label)
            
            item_layout.addStretch()
            info_layout.addLayout(item_layout)
        
        layout.addWidget(info_frame)
        
        layout.addSpacing(20)
        
        copyright_label = QLabel("© 2026 拾光剪影团队")
        copyright_label.setStyleSheet("color: #ffffff; font-size: 12px;")
        copyright_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(copyright_label)
        
        layout.addStretch()
        
        return widget

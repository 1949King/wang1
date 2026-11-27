"""0
设置模块 (SettingsModule)
=========================
包含快捷键设置、主题设置、字体大小调节等功能
"""

import json
import logging
import os
from typing import Dict, Optional, List, Any
from dataclasses import dataclass
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QGridLayout, QComboBox, QSpinBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
    QFormLayout, QCheckBox, QMessageBox, QDialog, QDialogButtonBox,
    QKeySequenceEdit, QColorDialog, QLineEdit, QListWidget, QListWidgetItem,
    QStackedWidget
)
from PySide6.QtCore import Qt, Signal, QSettings, QThread, QPoint, QPointF
from PySide6.QtGui import QFont, QColor, QKeySequence, QPainter, QImage, QPen, QBrush, QConicalGradient, QRadialGradient
import math
import re
import webbrowser

from .module_registry import get_registry, ModuleTier, reload_registry
from .base_module import BaseModule

logger = logging.getLogger(__name__)


def _safe_import_core(name):
    """按分层约定引入 core 层检测能力；缺失时返回 None，避免设置页崩溃"""
    try:
        return __import__("app.core." + name, fromlist=["*"])
    except Exception:
        try:
            return __import__("core." + name, fromlist=["*"])
        except Exception:
            return None


class ModernLineEdit(QLineEdit):
    """现代化输入框"""
    
    def __init__(self, placeholder: str = "", echo_mode: QLineEdit.EchoMode = QLineEdit.EchoMode.Normal):
        super().__init__()
        self.setPlaceholderText(placeholder)
        self.setEchoMode(echo_mode)
        self.setMinimumHeight(44)
        # 样式由全局 QSS (theme_manager.py) 统一管理，此处不写死颜色


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
        # 样式由全局 QSS 统一管理


class ColorWheel(QWidget):
    """自定义调色轮盘 - 大圆形 HSV 色环
    
    用法:
        wheel = ColorWheel()
        wheel.color_changed.connect(lambda hex_color: print(hex_color))
        wheel.set_theme("dark")  # 或 "light"
    """
    color_changed = Signal(str)  # 发射十六进制颜色字符串 "#rrggbb"

    def __init__(self, initial_color: str = "#ffffff", size: int = 200, parent=None):
        super().__init__(parent)
        self._color = QColor(initial_color)
        self._wheel_size = size
        self._indicator_radius = 8
        self._theme = "dark"  # 默认深色主题
        self._border_color = QColor("#444444")
        self._indicator_outer = QColor("#ffffff")
        self._indicator_inner = QColor("#000000")
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._render_wheel()
        # 根据初始颜色计算指示器位置
        self._update_indicator_from_color()

    def set_theme(self, theme: str):
        """设置主题，深色主题用白色边框，浅色主题用深色边框"""
        self._theme = theme
        if theme == "light":
            self._border_color = QColor("#888888")
            self._indicator_outer = QColor("#333333")
            self._indicator_inner = QColor("#666666")
        else:
            self._border_color = QColor("#444444")
            self._indicator_outer = QColor("#ffffff")
            self._indicator_inner = QColor("#000000")
        self.update()

    def _render_wheel(self):
        """预渲染色轮图像"""
        s = self._wheel_size
        self._wheel_img = QImage(s, s, QImage.Format.Format_ARGB32)
        self._wheel_img.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(self._wheel_img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        center = s / 2
        radius = s / 2 - 2
        
        # 使用锥形渐变绘制色相环
        gradient = QConicalGradient(QPointF(center, center), -90)
        for i in range(360):
            hue_color = QColor()
            hue_color.setHsv(i, 255, 255)
            gradient.setColorAt(i / 360.0, hue_color)
        
        painter.setBrush(QBrush(gradient))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(center, center), radius, radius)
        
        # 中心覆盖白色到透明渐变，形成饱和度效果
        # 使用叠加模式，使中心白色渐变与底层色相混合
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Overlay)
        
        # 创建径向渐变：中心白色（高饱和度遮挡）到边缘透明
        sat_gradient = QRadialGradient(QPointF(center, center), radius)
        sat_gradient.setColorAt(0, QColor(255, 255, 255, 255))  # 中心白色
        sat_gradient.setColorAt(1, QColor(255, 255, 255, 0))    # 边缘透明
        
        painter.setBrush(QBrush(sat_gradient))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(center, center), radius, radius)
        
        painter.end()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # 背景圆盘
        painter.drawImage(0, 0, self._wheel_img)
        
        # 边框（主题感知）
        center = self._wheel_size / 2
        radius = self._wheel_size / 2 - 2
        pen = QPen(self._border_color, 2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(center, center), radius, radius)
        
        # 当前选中指示器（外圈+颜色圆点，主题感知）
        h, s, v, _ = self._color.getHsv()
        angle_rad = math.radians(h)  # HSV hue: 0=red, goes clockwise
        dist = radius * s / 255.0
        ix = center + dist * math.cos(angle_rad)
        iy = center - dist * math.sin(angle_rad)
        
        # 外圈（主题感知）
        painter.setPen(QPen(self._indicator_outer, 2.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(ix, iy), self._indicator_radius, self._indicator_radius)
        # 内圈（主题感知）
        painter.setPen(QPen(self._indicator_inner, 1.5))
        painter.drawEllipse(QPointF(ix, iy), self._indicator_radius + 1, self._indicator_radius + 1)
        # 当前颜色填充
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(self._color))
        painter.drawEllipse(QPointF(ix, iy), self._indicator_radius - 1, self._indicator_radius - 1)
        
        painter.end()

    def mousePressEvent(self, event):
        self._pick(event.position().toPoint())

    def mouseMoveEvent(self, event):
        self._pick(event.position().toPoint())

    def _pick(self, pos: QPoint):
        center = self._wheel_size / 2
        dx = pos.x() - center
        dy = center - pos.y()  # Y轴翻转
        radius = self._wheel_size / 2 - 2
        dist = math.sqrt(dx * dx + dy * dy)
        
        if dist <= radius:
            # 计算色相 (角度)
            angle = math.degrees(math.atan2(dy, dx))
            if angle < 0:
                angle += 360
            hue = int(angle)
            
            # 计算饱和度 (距离中心的距离)
            saturation = min(255, int(dist / radius * 255))
            value = 255  # 保持亮度最大
            
            self._color.setHsv(hue, saturation, value)
            self._update_indicator_from_color()
            self.update()
            self.color_changed.emit(self._color.name())

    def _update_indicator_from_color(self):
        """根据当前颜色更新指示器位置（由 setColor 调用的辅助方法）"""
        pass  # 位置在 paintEvent 中动态计算

    def set_color(self, hex_color: str):
        """外部设置颜色"""
        c = QColor(hex_color)
        if c.isValid():
            self._color = c
            self.update()
            
    def get_color(self) -> str:
        return self._color.name()


class SettingsModule(BaseModule):
    """设置模块"""
    
    module_id = "settings"
    module_name = "设置"
    module_icon = "⚙️"
    settings_changed = Signal(str, object)
    
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
        self._settings = QSettings("拾光剪影", "Settings")
        self._shortcuts: Dict[str, ShortcutItem] = {}
        self._shortcut_editors: Dict[str, ShortcutEditor] = {}
        self._module_toggle_widgets: Dict[str, QCheckBox] = {}  # 功能开关映射
        super().__init__()  # BaseModule.__init__() → 设置 EventBus 等 + 调用 _setup_ui()
        self._load_settings()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # ── 顶部标题栏 ──
        self._header = QFrame()
        self._header.setStyleSheet("background-color: #1a1a1a; border-bottom: 1px solid #333333;")
        header_layout = QHBoxLayout(self._header)
        header_layout.setContentsMargins(20, 15, 20, 15)
        
        title = QLabel("⚙️ 设置")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        header_layout.addWidget(title)
        
        header_layout.addStretch()
        
        layout.addWidget(self._header)
        
        # ── 主体：左侧竖向导航 + 右侧内容区 ──
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        
        # --- 左侧导航栏 ---
        self._sidebar = QFrame()
        self._sidebar.setObjectName("sideBar")
        self._sidebar.setFixedWidth(200)
        self._sidebar.setStyleSheet("QFrame { background-color: #0d0d0d; border-right: 1px solid #1a1a1a; }")
        sidebar_layout = QVBoxLayout(self._sidebar)
        sidebar_layout.setContentsMargins(8, 10, 8, 10)
        sidebar_layout.setSpacing(2)
        
        self._sidebar_title = QLabel("  设置分类")
        self._sidebar_title.setObjectName("hintLabel")
        self._sidebar_title.setStyleSheet("color: #666666; font-size: 11px; font-weight: bold; padding: 6px 4px;")
        sidebar_layout.addWidget(self._sidebar_title)
        
        # 导航项定义：(图标, 名称, key, 创建方法)
        self._nav_categories = [
            ("⌨️", "快捷键", "shortcut", self._create_shortcut_tab),
            ("🎨", "外观", "appearance", self._create_appearance_tab),
            ("⚙️", "常规", "general", self._create_general_tab),
            ("👤", "账号", "account", self._create_account_tab),
            ("📧", "邮箱设置", "email", self._create_email_tab),
            ("🗑️", "缓存", "cache", self._create_cache_tab),
            ("🌐", "语言", "language", self._create_language_tab),
            ("🧩", "功能开关", "modules", self._create_module_toggle_tab),
            ("👥", "团队协作", "team", self._create_team_tab),
            ("ℹ️", "关于", "about", self._create_about_tab),
        ]
        
        self._nav_buttons: Dict[str, QPushButton] = {}
        self._page_indices: Dict[str, int] = {}
        
        for i, (icon, name, key, _) in enumerate(self._nav_categories):
            btn = QPushButton(f"  {icon}  {name}")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet("""
                QPushButton {
                    background: transparent;
                    color: #888888;
                    border: none;
                    border-radius: 8px;
                    padding: 10px 12px;
                    font-size: 13px;
                    text-align: left;
                }
                QPushButton:hover {
                    background: #1a1a1a;
                    color: #cccccc;
                }
                QPushButton[active="true"] {
                    background: #1a2a4a;
                    color: #3b82f6;
                    font-weight: bold;
                    border-left: 3px solid #3b82f6;
                }
            """)
            btn.clicked.connect(lambda checked, k=key: self._switch_settings_page(k))
            sidebar_layout.addWidget(btn)
            self._nav_buttons[key] = btn
            self._page_indices[key] = i
        
        sidebar_layout.addStretch()
        
        # --- 右侧内容区（堆叠式页面切换） ---
        self._content_stack = QStackedWidget()
        self._content_stack.setStyleSheet("QStackedWidget { background-color: #0a0a0a; }")
        
        for _, _, key, create_fn in self._nav_categories:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setStyleSheet("QScrollArea { background-color: #0a0a0a; border: none; }")
            scroll.setWidget(create_fn())
            self._content_stack.addWidget(scroll)
        
        body.addWidget(self._sidebar)
        body.addWidget(self._content_stack, 1)
        layout.addLayout(body, 1)
        
        self._update_nav_button_theme(self._is_light_theme())

        # 默认选中第一个
        self._switch_settings_page("shortcut")
        
        # ── 底部操作栏 ──
        self._bottom_bar = QFrame()
        self._bottom_bar.setStyleSheet("background-color: #1a1a1a; border-top: 1px solid #333333;")
        bottom_layout = QHBoxLayout(self._bottom_bar)
        bottom_layout.setContentsMargins(20, 10, 20, 10)
        
        reset_btn = QPushButton("恢复默认")
        reset_btn.setObjectName("resetBtn")
        reset_btn.clicked.connect(self._reset_all)
        bottom_layout.addWidget(reset_btn)

        import_btn = QPushButton("📥 导入设置")
        import_btn.setObjectName("resetBtn")
        import_btn.clicked.connect(self._import_settings)
        bottom_layout.addWidget(import_btn)

        export_btn = QPushButton("📤 导出设置")
        export_btn.setObjectName("resetBtn")
        export_btn.clicked.connect(self._export_settings)
        bottom_layout.addWidget(export_btn)
        
        bottom_layout.addStretch()
        
        save_btn = QPushButton("保存设置")
        save_btn.setObjectName("primaryBtn")
        save_btn.clicked.connect(self._save_settings)
        bottom_layout.addWidget(save_btn)
        
        layout.addWidget(self._bottom_bar)
    
    def _switch_settings_page(self, key: str):
        """切换到指定的设置分类页面"""
        # 更新导航按钮高亮状态
        for k, btn in self._nav_buttons.items():
            btn.setProperty("active", "true" if k == key else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        
        # 切换内容堆栈
        if key in self._page_indices:
            self._content_stack.setCurrentIndex(self._page_indices[key])
    
    def _create_shortcut_tab(self) -> QWidget:
        """创建快捷键设置标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        desc = QLabel("双击快捷键区域可以修改快捷键，按 Esc 取消修改")
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
        # 表格样式由全局 QSS 统一管理
        
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
    
    def _create_appearance_tab(self) -> QWidget:
        """外观设置标签页：AI-Canvas 风格预设卡墙 + 主题模式（顶部）
        + 既有导航栏模式 / 自定义颜色 / 字体设置（保留在下）

        V4.43.1：顶部区块抽到 settings_canvas_pages.build_appearance_top_block
        （settings_module.py 已超规模守卫基线，禁止继续变大）
        """
        from .settings_canvas_pages import build_appearance_top_block

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # ═══ 〇、AI-Canvas 风格顶部区块（头部 + 工具 + 大预览 + 预设卡墙 + 主题模式）═══
        layout.addWidget(build_appearance_top_block(self))

        # ═══════════════════════════════════════════════════════
        # 一、主题设置（保留既有导航栏模式 / 当前生效，主题下拉隐藏由分段驱动）
        # ═══════════════════════════════════════════════════════
        theme_group = QGroupBox("主题设置")
        theme_layout = QFormLayout(theme_group)

        self._theme_combo = QComboBox(theme_group)   # 有 parent 防 GC
        self._theme_combo.addItems(self.THEMES.values())
        self._theme_combo.setCurrentIndex(0)
        self._theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        self._theme_combo.setVisible(False)          # 由顶部「主题模式」分段控件驱动

        # 导航栏显示模式：图标+名称 / 仅图标（悬浮显示名称）
        self._nav_mode_combo = QComboBox()
        self._nav_mode_combo.addItem("显示图标和名称", "full")
        self._nav_mode_combo.addItem("仅显示图标（悬浮出名称）", "compact")
        self._nav_mode_combo.setMinimumWidth(200)
        self._nav_mode_combo.currentIndexChanged.connect(self._on_nav_mode_changed)
        theme_layout.addRow("导航栏:", self._nav_mode_combo)

        self._theme_status_label = QLabel("")
        self._theme_status_label.setObjectName("hintLabel")
        theme_layout.addRow("当前生效:", self._theme_status_label)

        layout.addWidget(theme_group)

        color_group = QGroupBox("自定义颜色")
        color_layout = QGridLayout(color_group)
        color_layout.setHorizontalSpacing(24)
        color_layout.setVerticalSpacing(16)

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
        self._color_labels: Dict[str, QLabel] = {}

        is_light = self._is_light_theme()

        for i, (name, key, default) in enumerate(colors):
            row = i // 2
            col = i % 2

            color_widget = QWidget()
            color_h_layout = QHBoxLayout(color_widget)
            color_h_layout.setContentsMargins(0, 0, 0, 0)
            color_h_layout.setSpacing(8)

            label = QLabel(name)
            label.setMinimumWidth(70)
            label.setObjectName(f"colorLabel_{key}")
            color_h_layout.addWidget(label)

            color_btn = QPushButton()
            color_btn.setFixedSize(56, 28)
            color_btn.setObjectName(f"colorSwatch_{key}")
            color_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            color_btn.setToolTip(f"点击修改 {name}")
            color_btn.clicked.connect(lambda checked, k=key, b=color_btn: self._pick_color(k, b))
            color_h_layout.addWidget(color_btn)

            value_label = QLabel(default)
            value_label.setObjectName(f"colorValue_{key}")
            value_label.setFont(QFont("Consolas", 10))
            value_label.setMinimumWidth(70)
            color_h_layout.addWidget(value_label)
            color_h_layout.addStretch()

            self._color_buttons[key] = color_btn
            self._color_labels[key] = value_label
            self._update_swatch_style(color_btn, default, is_light)
            color_layout.addWidget(color_widget, row, col)

        self._update_color_labels(is_light)
        layout.addWidget(color_group)

        # ═══════════════════════════════════════════════════════
        # 二、分隔线
        # ═══════════════════════════════════════════════════════
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("QFrame { color: #333333; }")
        layout.addWidget(sep)

        # ═══════════════════════════════════════════════════════
        # 三、字体设置
        # ═══════════════════════════════════════════════════════
        font_section = QLabel("字体设置")
        font_section.setStyleSheet("font-size: 15px; font-weight: bold; color: #cccccc; padding: 4px 0;")
        layout.addWidget(font_section)

        # 上部：设置 + 调色轮盘 左右分栏
        top_row = QHBoxLayout()
        top_row.setSpacing(24)

        # 左侧：字体参数设置
        font_group = QGroupBox("字体参数")
        font_layout = QFormLayout(font_group)
        font_layout.setSpacing(14)

        self._font_size_combo = QComboBox()
        self._font_size_combo.addItems([str(s) for s in self.FONT_SIZES])
        self._font_size_combo.setCurrentIndex(4)
        self._font_size_combo.setMinimumWidth(160)
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
        self._font_family_combo.setMinimumWidth(160)
        font_layout.addRow("字体:", self._font_family_combo)

        self._font_bold_check = QCheckBox("粗体")
        self._font_bold_check.toggled.connect(self._update_preview)
        font_layout.addRow("字体样式:", self._font_bold_check)

        top_row.addWidget(font_group)

        # 右侧：调色轮盘
        color_group = QGroupBox("文字颜色")
        color_layout = QVBoxLayout(color_group)
        color_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._color_wheel = ColorWheel(size=180)
        self._color_wheel.color_changed.connect(self._on_wheel_color_changed)
        color_layout.addWidget(self._color_wheel, alignment=Qt.AlignmentFlag.AlignCenter)

        # 颜色值显示
        self._font_color_label = QLabel("#ffffff")
        self._font_color_label.setStyleSheet("""
            color: #cccccc; font-size: 14px; font-family: monospace;
            padding: 8px 16px; background-color: #1a1a1a;
            border: 1px solid #333333; border-radius: 6px;
        """)
        self._font_color_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        color_layout.addWidget(self._font_color_label)

        top_row.addWidget(color_group)
        top_row.addStretch()
        layout.addLayout(top_row)

        # 下部：预览
        preview_group = QGroupBox("预览")
        preview_layout = QVBoxLayout(preview_group)

        self._preview_label = QLabel("这是一段预览文字\nThe quick brown fox jumps over the lazy dog")
        preview_layout.addWidget(self._preview_label)

        layout.addWidget(preview_group)

        self._font_size_combo.currentIndexChanged.connect(self._update_preview)
        self._font_family_combo.currentIndexChanged.connect(self._update_preview)

        # 初始化颜色状态
        self._font_color = "#ffffff"

        layout.addStretch()
        return widget
    
    def _create_general_tab(self) -> QWidget:
        """常规设置标签页：AI-Canvas 风格 6 开关分组（顶部）+ 既有启动/项目/性能（保留在下）

        V4.43.1：顶部区块抽到 settings_canvas_pages.build_general_top_block
        （settings_module.py 已超规模守卫基线，禁止继续变大）
        """
        from .settings_canvas_pages import build_general_top_block

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # ═══ AI-Canvas 风格顶部区块（节点工具栏分段 + 6 个 .sidebar-pref-card 开关）═══
        layout.addWidget(build_general_top_block(self))

        startup_group = QGroupBox("启动设置")
        startup_group
        startup_layout = QFormLayout(startup_group)
        
        self._auto_start_check = QCheckBox("开机自动启动")
        self._auto_start_check
        startup_layout.addRow(self._auto_start_check)
        
        self._auto_login_check = QCheckBox("自动登录")
        self._auto_login_check.setChecked(True)
        self._auto_login_check
        startup_layout.addRow(self._auto_login_check)
        
        self._remember_window_check = QCheckBox("记住窗口大小和位置")
        self._remember_window_check.setChecked(True)
        self._remember_window_check
        startup_layout.addRow(self._remember_window_check)
        
        layout.addWidget(startup_group)
        
        project_group = QGroupBox("项目设置")
        project_group
        project_layout = QFormLayout(project_group)
        
        self._auto_save_check = QCheckBox("自动保存")
        self._auto_save_check.setChecked(True)
        self._auto_save_check
        project_layout.addRow(self._auto_save_check)
        
        self._auto_save_interval = QSpinBox()
        self._auto_save_interval.setRange(30, 600)
        self._auto_save_interval.setValue(300)
        self._auto_save_interval.setSuffix(" 秒")
        self._auto_save_interval
        project_layout.addRow("保存间隔:", self._auto_save_interval)
        
        layout.addWidget(project_group)
        
        performance_group = QGroupBox("性能设置")
        performance_group
        performance_layout = QFormLayout(performance_group)
        
        self._max_threads_spin = QSpinBox()
        self._max_threads_spin.setRange(1, 32)
        self._max_threads_spin.setValue(15)
        self._max_threads_spin
        performance_layout.addRow("最大线程数:", self._max_threads_spin)
        
        self._gpu_accel_check = QCheckBox("启用 GPU 加速")
        self._gpu_accel_check.setChecked(True)
        self._gpu_accel_check
        performance_layout.addRow(self._gpu_accel_check)
        
        self._cache_size_spin = QSpinBox()
        self._cache_size_spin.setRange(100, 10000)
        self._cache_size_spin.setValue(1000)
        self._cache_size_spin.setSuffix(" MB")
        self._cache_size_spin
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
        device_info
        device_layout.addWidget(device_info)
        
        self._device_table = QTableWidget()
        self._device_table.setColumnCount(3)
        self._device_table.setHorizontalHeaderLabels(["设备名称", "最后活跃", "操作"])
        self._device_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._device_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._device_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._device_table.setColumnWidth(2, 80)
        # 表格样式由全局 QSS 统一管理
        
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
                    unbind_btn.setObjectName("dangerBtn")
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
            from PySide6.QtWidgets import QApplication
            QApplication.processEvents()
        
        if login_success[0]:
            self._refresh_account_tab()
    
    def _refresh_account_tab(self):
        """刷新账号标签页"""
        account_index = self._page_indices.get("account", -1)
        if account_index < 0:
            return
        old_scroll = self._content_stack.widget(account_index)
        if old_scroll:
            old_widget = old_scroll.takeWidget()
            if old_widget:
                old_widget.deleteLater()
            new_scroll = QScrollArea()
            new_scroll.setWidgetResizable(True)
            new_scroll.setStyleSheet("QScrollArea { background-color: #0a0a0a; border: none; }")
            new_scroll.setWidget(self._create_account_tab())
            self._content_stack.insertWidget(account_index, new_scroll)
            self._content_stack.removeWidget(old_scroll)
            old_scroll.deleteLater()
    
    def _pick_font_color(self):
        """选择字体颜色（通过QColorDialog）"""
        current = QColor(self._font_color)
        color = QColorDialog.getColor(current, self, "选择字体颜色")
        if color.isValid():
            self._font_color = color.name()
            self._font_color_label.setText(self._font_color)
            self._color_wheel.set_color(self._font_color)
            self._update_preview()

    def _pick_color(self, key: str, button: QPushButton):
        """选择颜色"""
        current_color = button.palette().button().color()
        color = QColorDialog.getColor(current_color, self, "选择颜色")
        if color.isValid():
            self._update_swatch_style(button, color.name(), self._is_light_theme())
            value_label = self._color_labels.get(key)
            if value_label:
                value_label.setText(color.name())
    
    def _update_preview(self):
        """更新字体预览（自动根据主题调整对比背景）"""
        size = int(self._font_size_combo.currentText())
        family = self._font_family_combo.currentText()
        bold = "bold" if self._font_bold_check.isChecked() else "normal"
        color = self._font_color
        is_light = self._is_light_theme()
        # 使用不会被主题映射替换的颜色作为预览背景
        # #1e1e1e 和 #333333 不在 _DARK_BG_MAP 中，所以不会被替换
        preview_bg = "#1e1e1e" if is_light else "#333333"
        self._preview_label.setStyleSheet(
            f"font-size: {size}px; font-family: '{family}'; font-weight: {bold}; "
            f"color: {color}; padding: 20px; background-color: {preview_bg}; "
            f"border-radius: 8px; min-height: 60px;"
        )
    
    def _is_light_theme(self) -> bool:
        """根据 ThemeManager 的实际主题判断当前是否为浅色主题。"""
        try:
            from .theme_manager import ThemeManager
            return ThemeManager.instance().current_theme == "light"
        except Exception:
            cs = self._content_stack.styleSheet()
            return bool(cs and ("#f5f5f5" in cs or "#e8e8e8" in cs or "#ffffff" in cs))
    
    def _update_swatch_style(self, button: QPushButton, color: str, is_light: bool) -> None:
        """设置颜色样本按钮样式，边框颜色会随主题自动切换"""
        border = "#888888" if is_light else "#555555"
        button.setStyleSheet(
            f"background-color: {color}; border: 1px solid {border}; border-radius: 4px;"
        )
    
    def _update_color_labels(self, is_light: bool) -> None:
        """更新颜色值标签的文字颜色，使其在不同主题下都可读"""
        text_color = "#222222" if is_light else "#aaaaaa"
        for label in self._color_labels.values():
            label.setStyleSheet(f"color: {text_color}; font-family: Consolas; font-size: 10px;")
    
    def _update_color_swatches(self, is_light: bool) -> None:
        """更新颜色样本按钮边框与颜色值标签，使其适应明/暗主题"""
        border = "#888888" if is_light else "#555555"
        for button in self._color_buttons.values():
            ss = button.styleSheet()
            new_ss = re.sub(r"border\s*:\s*1px\s+solid\s+#[0-9a-fA-F]{6};", f"border: 1px solid {border};", ss)
            if new_ss != ss:
                button.setStyleSheet(new_ss)
        self._update_color_labels(is_light)
    
    def _on_wheel_color_changed(self, hex_color: str):
        """调色轮盘颜色变化处理"""
        self._font_color = hex_color
        self._font_color_label.setText(hex_color)
        self._update_preview()
    
    def _reset_shortcut(self, action: str, default: str):
        """重置单个快捷键"""
        if action in self._shortcut_editors:
            self._shortcut_editors[action].setKeySequence(QKeySequence(default))
    
    def _reset_all(self):
        """重置所有设置"""
        reply = QMessageBox.question(
            self, "确认重置",
            "确定要恢复所有设置为默认值吗？\n（包括功能开关也会恢复为默认值）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            for action, editor in self._shortcut_editors.items():
                default = self._shortcuts[action].default_shortcut
                editor.setKeySequence(QKeySequence(default))
            
            self._theme_combo.setCurrentIndex(0)
            self._font_size_combo.setCurrentIndex(4)
            self._font_family_combo.setCurrentIndex(0)
            
            # 重置字体颜色和粗体
            self._font_color = "#ffffff"
            self._font_color_label.setText("#ffffff")
            self._color_wheel.set_color("#ffffff")
            self._font_bold_check.setChecked(False)
            self._update_preview()

            # 重置功能开关为默认值
            registry = get_registry()
            registry.reset_all()
            reload_registry()
            for mid, cb in self._module_toggle_widgets.items():
                defn = registry.get_definition(mid)
                if defn is not None:
                    cb.setChecked(bool(defn.get("default_enabled", False)))

            QMessageBox.information(self, "成功", "已恢复默认设置")

    def _export_settings(self):
        """导出所有设置为 JSON 文件"""
        import json
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getSaveFileName(
            self, "导出设置", "拾光剪影_设置备份.json", "JSON 文件 (*.json)"
        )
        if not path:
            return

        try:
            data = {}
            # 导出 QSettings 中的所有键
            for key in self._settings.allKeys():
                data[key] = self._settings.value(key)

            # 同时导出功能开关状态
            registry = get_registry()
            switches = {}
            for mid, cb in self._module_toggle_widgets.items():
                switches[mid] = cb.isChecked()
            data["_module_switches"] = switches

            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            QMessageBox.information(self, "导出成功", f"设置已导出到:\n{path}")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))

    def _import_settings(self):
        """从 JSON 文件导入设置"""
        import json
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            self, "导入设置", "", "JSON 文件 (*.json)"
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            switches = data.pop("_module_switches", {})

            # 写入 QSettings
            for key, value in data.items():
                self._settings.setValue(key, value)

            # 恢复功能开关
            if switches:
                registry = get_registry()
                for mid, checked in switches.items():
                    if mid in self._module_toggle_widgets:
                        self._module_toggle_widgets[mid].setChecked(checked)
                        registry.toggle(mid, checked)
                reload_registry()

            # 重新加载界面
            self._load_settings()
            QMessageBox.information(self, "导入成功",
                f"设置已从备份恢复:\n{path}\n\n提示：部分设置需重启后生效。")
        except Exception as e:
            QMessageBox.warning(self, "导入失败", f"文件格式错误或损坏:\n{str(e)}")
    
    def _set_windows_autostart(self, enabled: bool) -> bool:
        """将「开机自动启动」写入 Windows 注册表 Run 键（仅 Windows 生效）。

        修复：此前该开关只是个 UI 摆设，勾选后没有任何系统级效果——用户
        以为已经设置了开机自启，实际上从没注册过。这里做最小可用的真实
        实现：写入 HKCU\\...\\Run，取消勾选时删除对应键值。
        """
        import sys
        if sys.platform != "win32":
            return False
        try:
            import winreg
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            app_name = "拾光剪影AI短剧编辑器"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
                if enabled:
                    if getattr(sys, "frozen", False):
                        cmd = f'"{sys.executable}"'
                    else:
                        entry = os.path.abspath(
                            os.path.join(os.path.dirname(__file__), "..", "..", "..", "main_qt6.py")
                        )
                        if not os.path.exists(entry):
                            entry = os.path.abspath(
                                os.path.join(os.path.dirname(__file__), "..", "..", "main_qt6.py")
                            )
                        cmd = f'"{sys.executable}" "{entry}"'
                    winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, cmd)
                else:
                    try:
                        winreg.DeleteValue(key, app_name)
                    except FileNotFoundError:
                        logger.debug("忽略异常（原为 pass）: settings_module.py", exc_info=True)
            return True
        except Exception as e:
            logger.warning(f"设置开机自启动注册表失败: {e}")
            return False

    def _load_settings(self):
        """加载设置"""
        theme = self._settings.value("theme", "dark")
        if theme in self.THEMES:
            index = list(self.THEMES.keys()).index(theme)
            self._theme_combo.blockSignals(True)
            self._theme_combo.setCurrentIndex(index)
            self._theme_combo.blockSignals(False)
        # 启动时按 ThemeManager 的当前主题刷新自身内联样式（单一机制：不再独立
        # 读取第二份主题状态，避免与全局主题脱节；不触发全局事件）
        from .theme_manager import ThemeManager
        self.set_theme(ThemeManager.instance().theme_preference)

        # 导航栏显示模式回填（不触发即时生效事件）
        nav_mode = self._settings.value("nav_mode", "full")
        nav_idx = self._nav_mode_combo.findData("compact" if nav_mode == "compact" else "full")
        if nav_idx >= 0:
            self._nav_mode_combo.blockSignals(True)
            self._nav_mode_combo.setCurrentIndex(nav_idx)
            self._nav_mode_combo.blockSignals(False)

        font_size = self._settings.value("font_size", 14, type=int)
        index = self.FONT_SIZES.index(font_size) if font_size in self.FONT_SIZES else 4
        self._font_size_combo.setCurrentIndex(index)
        
        font_family = self._settings.value("font_family", "Microsoft YaHei")
        index = self._font_family_combo.findText(font_family)
        if index >= 0:
            self._font_family_combo.setCurrentIndex(index)
        
        font_color = self._settings.value("font_color", "#ffffff")
        self._font_color = font_color
        self._font_color_label.setText(font_color)
        self._color_wheel.set_color(font_color)
        
        font_bold = self._settings.value("font_bold", False, type=bool)
        self._font_bold_check.setChecked(font_bold)
        self._update_preview()
        
        shortcuts = self._settings.value("shortcuts", {})
        if shortcuts:
            for action, shortcut in shortcuts.items():
                if action in self._shortcut_editors:
                    self._shortcut_editors[action].setKeySequence(QKeySequence(shortcut))

        # 修复：常规设置标签页的一批开关此前只保存不加载（或既不保存也不加载），
        # 每次重启设置页都会回到写死的默认值，用户勾选的状态"看起来"没有生效
        self._auto_start_check.setChecked(self._settings.value("auto_start", False, type=bool))
        self._remember_window_check.setChecked(self._settings.value("remember_window", True, type=bool))
        self._auto_login_check.setChecked(self._settings.value("auto_login", True, type=bool))
        self._auto_save_check.setChecked(self._settings.value("auto_save", True, type=bool))
        self._auto_save_interval.setValue(self._settings.value("auto_save_interval", 300, type=int))
        self._max_threads_spin.setValue(self._settings.value("max_threads", 15, type=int))
        self._gpu_accel_check.setChecked(self._settings.value("gpu_accel", True, type=bool))
        self._cache_size_spin.setValue(self._settings.value("cache_size", 1000, type=int))
    
    def _save_settings(self):
        """
        保存设置（合并版：通用设置 + SMTP + 功能开关）

        【重要】此前该类中存在两个同名 _save_settings() 方法（Python 类中后定义的
        方法会覆盖前面的定义），导致功能开关持久化逻辑被静默跳过 —— 这正是
        "功能开关勾选后重启看不到" 问题的根因。

        现已将两处逻辑合并为单一方法，涵盖以下三大块：
        ┌─────────────────────────────────────────────────┐
        │ 1. 通用设置  →  theme / font / shortcuts /...   │
        │ 2. 功能开关  →  registry.toggle() 双保险写入   │
        │ 3. SMTP 配置 →  email_verification_service      │
        └─────────────────────────────────────────────────┘

        数据流：
          UI 控件 → self._settings (QSettings/注册表)
                  → registry.toggle() (QSettings + JSON 文件双保险)
                  → EventBus.MODULE_CONFIG_CHANGED (通知主窗口刷新)
                  → email_verification_service (SMTP 持久化)
        """
        # ── 第1步：保存通用设置到 QSettings（Windows 注册表） ──
        theme_key = list(self.THEMES.keys())[self._theme_combo.currentIndex()]
        self._settings.setValue("theme", theme_key)
        # 主题只走 ThemeManager 单一机制：偏好有变才发 THEME_CHANGED，由主窗口应用
        # 全局 QSS 并回调本模块 set_theme（直接调 set_theme 会让全局与设置页脱节）
        from .theme_manager import ThemeManager
        if theme_key != ThemeManager.instance().theme_preference:
            self._on_theme_changed(self._theme_combo.currentIndex())

        # 导航栏显示模式（full=图标+名称 / compact=仅图标悬浮显名）
        if hasattr(self, "_nav_mode_combo"):
            self._settings.setValue("nav_mode", self._nav_mode_combo.currentData() or "full")

        font_size = int(self._font_size_combo.currentText())
        self._settings.setValue("font_size", font_size)
        
        font_family = self._font_family_combo.currentText()
        self._settings.setValue("font_family", font_family)
        
        self._settings.setValue("font_color", self._font_color)
        self._settings.setValue("font_bold", self._font_bold_check.isChecked())
        
        shortcuts = {}
        for action, editor in self._shortcut_editors.items():
            shortcuts[action] = editor.keySequence().toString()

        # ── 快捷键冲突检测 ──
        # 构建 快捷键字符串 → 操作列表 的映射，检测同一快捷键被多个操作使用
        conflict_map: Dict[str, List[str]] = {}
        for action, ks in shortcuts.items():
            if not ks.strip():
                continue  # 空快捷键跳过
            conflict_map.setdefault(ks, []).append(action)

        conflicts_found = False
        conflict_lines = []
        for ks, actions in conflict_map.items():
            if len(actions) > 1:
                conflicts_found = True
                # 获取操作的中文名
                action_names = []
                for a in actions:
                    si = self._shortcuts.get(a)
                    action_names.append(si.name if si else a)
                conflict_lines.append(
                    f"快捷键 \"{ks}\" 被同时分配给了："
                    + "、".join(action_names)
                )

        if conflicts_found:
            # 弹出警告对话框，让用户选择忽略冲突或返回修改
            reply = QMessageBox.warning(
                self,
                "快捷键冲突警告",
                "检测到以下快捷键冲突：\n\n"
                + "\n".join(conflict_lines)
                + "\n\n点击「忽略」继续保存（后覆盖前），\n"
                + "点击「取消」返回修改。",
                QMessageBox.StandardButton.Ignore | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Cancel:
                QMessageBox.information(self, "提示", "已取消保存，请修改冲突的快捷键后重试。")
                return

        self._settings.setValue("shortcuts", shortcuts)
        
        self._settings.setValue("auto_login", self._auto_login_check.isChecked())
        self._settings.setValue("auto_save", self._auto_save_check.isChecked())
        self._settings.setValue("auto_save_interval", self._auto_save_interval.value())
        self._settings.setValue("max_threads", self._max_threads_spin.value())
        self._settings.setValue("gpu_accel", self._gpu_accel_check.isChecked())

        # 修复：以下三项此前只创建了控件，_save_settings 里完全没有出现过，
        # 勾选/调整后无论重启多少次都不会生效——现在补上持久化，
        # "记住窗口大小和位置" 由 main_window._save_window_geometry 读取，
        # "缓存大小" 供 cache_system 等读取上限，"开机自动启动" 额外做真实的
        # 系统级注册（Windows 注册表 Run 键），而不是只存一个没人用的布尔值。
        self._settings.setValue("remember_window", self._remember_window_check.isChecked())
        self._settings.setValue("cache_size", self._cache_size_spin.value())
        auto_start = self._auto_start_check.isChecked()
        self._settings.setValue("auto_start", auto_start)
        if not self._set_windows_autostart(auto_start):
            logger.debug("开机自动启动系统注册未生效（非 Windows 或注册表写入失败）")

        # ── 连接自动保存间隔到 ProjectManager ──
        try:
            from core.project_manager import project_manager
            project_manager.autosave_interval = self._auto_save_interval.value()
        except Exception as e:
            logger.debug("自动保存间隔设置失败: %s", e)

        # ── 第2步：功能开关持久化（双保险：注册表 + JSON 文件） ──
        # 遍历所有功能开关复选框，调用 registry.toggle() 进行增量比对：
        #   - 若值 == 默认值 → 从 _overrides 移除（不存脏数据）
        #   - 若值 ≠ 默认值 → 写入 _overrides 并同步到 QSettings + JSON
        # toggle() 返回 True 表示该项发生了实际变化
        registry = get_registry()
        changed = False
        for mid, cb in self._module_toggle_widgets.items():
            if registry.toggle(mid, cb.isChecked()):
                changed = True

        # ── 第3步：SMTP 邮箱配置保存 ──
        smtp_saved = False
        try:
            from .email_verify import email_verification_service, SMTPConfig
            host = self._smtp_host_input.text().strip()
            port = self._smtp_port_spin.value()
            username = self._smtp_username_input.text().strip()
            password = self._smtp_password_input.text()
            sender_name = self._smtp_sender_input.text().strip()
            use_ssl = self._smtp_ssl_check.isChecked()
            if host and username and password:
                config = SMTPConfig(
                    host=host, port=port, username=username,
                    password=password,
                    sender_name=sender_name or "AI短剧编辑器",
                    use_ssl=use_ssl
                )
                email_verification_service.save_config(config)
                smtp_saved = True
        except Exception as e:
            logger.error(f'[Settings] SMTP 保存失败: {e}')

        # ── 第4步：发射 settings_changed 信号，通知外部监听者 ──
        self.settings_changed.emit("all", {
            "theme": theme_key,
            "font_size": font_size,
            "font_family": font_family,
            "font_color": self._font_color,
            "font_bold": self._font_bold_check.isChecked(),
            "shortcuts": shortcuts
        })

        # ── 第5步：如有功能开关变更，通知主窗口动态刷新导航栏 ──
        # EventBus 是应用级事件总线（发布-订阅模式），MainWindow 监听
        # MODULE_CONFIG_CHANGED 事件后调用 apply_module_changes() 实时更新
        # 左侧导航栏的可见性，无需重启或刷新页面
        if changed:
            from .core import EventBus, EventType
            EventBus.get_instance().emit(EventType.MODULE_CONFIG_CHANGED,
                                         {"source": "settings_module"})

        # ── 第6步：汇总提示信息 ──
        parts = ["设置已保存"]
        if changed:
            parts.append("导航栏已同步更新")
        if smtp_saved:
            parts.append("SMTP 配置已保存")
        QMessageBox.information(self, "成功", "，".join(parts))
    
    def get_shortcut(self, action: str) -> str:
        """获取快捷键"""
        if action in self._shortcut_editors:
            return self._shortcut_editors[action].keySequence().toString()
        return ""

    def _on_module_toggle_changed(self, module_id: str, checked: bool):
        """
        功能开关即时响应：勾选/取消立即持久化 + 刷新导航栏

        与「保存设置」按钮的区别：
          - 本方法：每个复选框 toggled 信号触发，实时生效，无需用户点保存
          - 保存按钮：批量遍历所有复选框，统一写入（保留作为兜底）

        执行流程：
          1. 调用 registry.toggle(module_id, checked)
             → 将变更写入 QSettings 注册表 + JSON 文件（双保险）
             → 返回 True 表示实际有变更，False 表示值未变
          2. 若有变更，通过 EventBus 发射 MODULE_CONFIG_CHANGED 事件
             → MainWindow.apply_module_changes() 收到事件后动态刷新左侧导航栏
             → 被关闭的模块立即可见地从导航栏消失，开启的模块立即出现

        为什么需要 instant 标记？
          - 保存按钮也发射 MODULE_CONFIG_CHANGED 事件，源头为 "settings_module"
          - 添加 instant=True 帮助 MainWindow 区分是即时响应还是批量保存
          - 即时响应场景下 MainWindow 可以跳过某些重型检查
        """
        registry = get_registry()
        if registry.toggle(module_id, checked):
            from .core import EventBus, EventType
            EventBus.get_instance().emit(EventType.MODULE_CONFIG_CHANGED,
                                         {"source": "settings_module", "instant": True})
    
    # ─────────────── 主题切换系统 ───────────────
    
    def set_theme(self, theme_key: str):
        """按主题刷新设置面板自身 UI（纯视图刷新：不发事件、不写 theme 属性）
        
        重要：不再在 set_theme 内部 emit THEME_CHANGED 事件！
        因为 main_window 的 _on_theme_changed 会反过来调用所有模块的 set_theme，
        形成 set_theme → emit → main_window._apply_theme → set_theme 死循环。
        
        现在的流程是：
        1. 用户在设置面板切换主题 → _on_theme_changed(idx) 触发
        2. _on_theme_changed 直接 emit THEME_CHANGED 事件（一次）
        3. main_window._on_theme_changed 接收事件 → _apply_theme
        4. _apply_theme 调用 ThemeManager.apply_theme + 给所有模块 setProperty
        5. ThemeManager 内置 _applying 标志位防止二次触发
        """
        # 契约（2026-11-27 单一机制）：本方法只负责「把本页内联样式画成指定主题」，
        # 由 ThemeManager.apply_theme → 主窗口 refresh_module_themes 统一回调；
        # 切换入口（标题栏按钮 / 本页下拉框 / 保存 / 按时间切换 / 画布设置页）
        # 一律只走 ThemeManager，禁止在本方法里再触发全局切换或自行决定主题状态。
        #
        # NOTE: 不要根据 current_theme 提前返回。set_theme 的职责是更新设置面板
        # 自身的局部样式（header、sidebar、content_stack 等），即使 ThemeManager 已经
        # 把全局主题应用过，这些局部样式仍然需要更新。
        
        from .theme_manager import ThemeManager
        actual_theme = ThemeManager.resolve_theme(theme_key)
        is_light = actual_theme == "light"
        
        # 整体容器色
        colors = ThemeManager.COLORS_LIGHT if is_light else ThemeManager.COLORS_DARK
        bg = colors["bg_main"]
        sec_bg = colors["bg_secondary"]
        
        self._header.setStyleSheet(
            f"background-color: {sec_bg}; border-bottom: 1px solid {colors['border_light']};"
        )
        self._sidebar.setStyleSheet(
            f"QFrame#sideBar {{ background-color: {sec_bg}; border-right: 1px solid {colors['border_light']}; }}"
        )
        if hasattr(self, "_sidebar_title"):
            self._sidebar_title.setStyleSheet(
                f"color: {colors['text_disabled']}; font-size: 11px; font-weight: bold; padding: 6px 4px;"
            )
        self._content_stack.setStyleSheet(
            f"QStackedWidget {{ background-color: {bg}; }}"
        )
        self._bottom_bar.setStyleSheet(
            f"background-color: {sec_bg}; border-top: 1px solid {colors['border_light']};"
        )
        
        # 遍历所有页面，智能替换子控件颜色（保留语义色）
        for idx in range(self._content_stack.count()):
            scroll_area = self._content_stack.widget(idx)
            if isinstance(scroll_area, QScrollArea):
                scroll_area.setStyleSheet(
                    f"QScrollArea {{ background-color: {bg}; border: none; }}"
                )
                inner = scroll_area.widget()
                if inner:
                    inner.setStyleSheet(f"background-color: {bg};")
                    self._force_theme_on_children(inner, is_light)
        
        # 更新左侧导航按钮样式
        self._update_nav_button_theme(is_light)
        
        # 刷新字体预览（让预览区域适配当前主题的对比背景）
        self._update_preview()
        
        # 更新底部按钮样式
        self._update_bottom_button_theme(is_light)
        
        # 刷新颜色样本与颜色值标签
        self._update_color_swatches(is_light)
        
        # theme 属性与 repolish 统一交给 ThemeManager 的同一个例程（属性没变则跳过）：
        # 本模块是懒加载的，创建时全局主题早已应用，新控件的 theme 属性必须在这里补上，
        # 否则全局 QSS 的 [theme="..."] 选择器匹配不到（深色下出现黑字）。
        ThemeManager._apply_theme_property(self, actual_theme)
        # 主题下拉框跟随 ThemeManager 的偏好（单一真相源）：标题栏主题按钮、
        # 按时间自动切换等入口改了主题后，这里只同步显示，不触发任何事件。
        preference = ThemeManager.instance().theme_preference
        combo = getattr(self, "_theme_combo", None)
        if combo is not None and preference in self.THEMES:
            if list(self.THEMES.keys())[combo.currentIndex()] != preference:
                combo.blockSignals(True)
                combo.setCurrentIndex(list(self.THEMES.keys()).index(preference))
                combo.blockSignals(False)

        if hasattr(self, "_theme_status_label"):
            display = "浅色" if actual_theme == "light" else "深色"
            suffix = "（自动解析）" if theme_key == "auto" else ""
            self._theme_status_label.setText(f"{display}{suffix}")
        
        # 注意：不再 emit THEME_CHANGED 事件！
        # 事件由 _on_theme_changed(idx) 在 combo 框变化时统一 emit，避免循环触发
    
    # 需要映射的深色背景色（→浅色），只替换这些，保留蓝/橙/绿/红等语义色
    _DARK_BG_MAP = {
        "#0a0a0a": "#f5f5f5", "#0d0d0d": "#e8e8e8",
        "#1a1a1a": "#ffffff",  "#2a2a2a": "#f0f0f0",
        # 关于页面专用深色背景
        "#14192d": "#dce4f5", "#1a1030": "#ece0f5",
        "#141820": "#eef0f4", "#1a1e28": "#e8eaf0",
        "#1a1e2e": "#e8eaef",
    }
    # 深色模式下白色文字 → 浅色模式深色文字
    _LIGHT_TEXT_MAP = {
        "#ffffff": "#222222", "#eeeeee": "#333333",
        "#cccccc": "#555555", "#888888": "#666666",
        # 关于页面专用浅色文字
        "#e0e0ff": "#2a2a4a", "#7b8cbf": "#4a5590",
        "#6c9fff": "#2a5cd0", "#8a8fa0": "#555860",
        "#c8ccd8": "#3a3e48", "#a0a6b8": "#4a5060",
        "#404860": "#8888a0", "#ccc": "#555555",
        "#999": "#777777",
    }
    # 深色边框 → 浅色边框
    _DARK_BORDER_MAP = {
        "#333333": "#dddddd", "#1a1a1a": "#cccccc",
        # 关于页面专用深色边框
        "#2a2a40": "#c8cce0", "#2a2f3a": "#ccd0dc",
    }
    # 2026-11-27：原 _GROUPBOX_COLOR_MAP 已移除 —— 它的键写成 "color:#fff"（无空格），
    # 而源样式是 "color: #ffffff"（有空格），从未匹配成功，分组标题在浅色下一直是 #cccccc。
    # GroupBox 与其它控件一样走下方 _map_declarations 的逐声明映射。

    @classmethod
    def _map_declarations(cls, ss: str, is_light: bool) -> str:
        """把内联样式表里的颜色声明按主题逐条映射（可逆：切回时原样还原）。

        只改「该声明自己的」十六进制色值：color 属文字色，background*/border* 属
        底色/边框色。2026-11-27 之前是对整段样式表做子串替换，文字色与同值的
        边框键互相污染（如 #333333 既是 #eeeeee 的浅色文字，又是深色边框键），
        深浅来回切换后颜色错乱、切不回原样。
        """
        hex_token = re.compile(r"#[0-9a-fA-F]{3,8}")
        # (声明属性判定, 依次使用的映射表名)
        families = (
            (lambda prop: prop == "color", ("_LIGHT_TEXT_MAP",)),
            (lambda prop: prop.startswith(("background", "border", "outline", "gridline")),
             ("_DARK_BG_MAP", "_DARK_BORDER_MAP")),
        )
        # 浅色：深色键 → 浅色值；深色：浅色值 → 深色键
        tables = {}
        for name in ("_LIGHT_TEXT_MAP", "_DARK_BG_MAP", "_DARK_BORDER_MAP"):
            table = getattr(cls, name)
            tables[name] = ({k.lower(): v for k, v in table.items()} if is_light
                            else {v.lower(): k for k, v in table.items()})

        def _map_decl(match):
            prop, lead, val = match.group("prop"), match.group("lead"), match.group("val")
            for is_family, names in families:
                if not is_family(prop):
                    continue
                for name in names:
                    lookup = tables[name]

                    def _replace(token, _lookup=lookup):
                        return _lookup.get(token.group(0).lower(), token.group(0))

                    val = hex_token.sub(_replace, val)
                break
            return f"{prop}{lead}{val}"

        return re.sub(r"(?P<prop>[a-zA-Z-]+)(?P<lead>\s*:\s*)(?P<val>[^;{}]*)", _map_decl, ss)
    
    def _force_theme_on_children(self, root: QWidget, is_light: bool):
        """智能递归替换：只换背景/文字/边框色，保留语义颜色(蓝#1e6bde/橙#f59e0b/绿#22c55e/红#ef4444)"""
        children = root.findChildren(QWidget)
        for w in children:
            # ColorWheel单独处理主题
            if isinstance(w, ColorWheel):
                w.set_theme("light" if is_light else "dark")
                continue
            # 预览标签跳过，因为它有自己的颜色处理逻辑
            if w is self._preview_label:
                continue
            # QGroupBox 不再特殊处理：其内联颜色走下方通用的逐声明映射
            if hasattr(w, 'objectName'):
                name = w.objectName()
                if name and ("navBtn" in name or "saveBtn" in name or "resetBtn" in name or name.startswith("colorSwatch_")):
                    continue
            
            ss = w.styleSheet()
            if not ss:
                continue
            
            # 按声明逐条映射（可逆）；不再对整段样式表做子串替换
            new_ss = self._map_declarations(ss, is_light)
            if new_ss != ss:
                w.setStyleSheet(new_ss)
    
    def _update_nav_button_theme(self, is_light: bool):
        """更新左侧导航按钮的明/暗主题样式"""
        from .theme_manager import ThemeManager
        colors = ThemeManager.COLORS_LIGHT if is_light else ThemeManager.COLORS_DARK
        if is_light:
            nav_ss = """
                QPushButton {
                    background: transparent;
                    color: %(text_secondary)s;
                    border: 1px solid transparent;
                    border-radius: 8px;
                    padding: 10px 12px;
                    font-size: 13px;
                    text-align: left;
                }
                QPushButton:hover {
                    background: %(bg_hover)s;
                    color: %(text_primary)s;
                    border: 1px solid %(border)s;
                }
                QPushButton[active="true"] {
                    background: %(accent_soft)s;
                    color: %(accent)s;
                    font-weight: bold;
                    border-left: 3px solid %(accent)s;
                }
            """ % colors
        else:
            nav_ss = """
                QPushButton {
                    background: transparent;
                    color: %(text_secondary)s;
                    border: 1px solid transparent;
                    border-radius: 8px;
                    padding: 10px 12px;
                    font-size: 13px;
                    text-align: left;
                }
                QPushButton:hover {
                    background: %(bg_hover)s;
                    color: %(text_primary)s;
                    border: 1px solid %(border)s;
                }
                QPushButton[active="true"] {
                    background: %(accent_soft)s;
                    color: %(accent)s;
                    font-weight: bold;
                    border-left: 3px solid %(accent)s;
                }
            """ % colors
        for btn in self._nav_buttons.values():
            btn.setStyleSheet(nav_ss)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
    
    def _update_bottom_button_theme(self, is_light: bool):
        """更新底部重置/保存按钮的明/暗主题样式"""
        # 遍历底部栏的子控件找到按钮
        for child in self._bottom_bar.children():
            if isinstance(child, QPushButton):
                text = child.text()
                if "恢复" in text:
                    if is_light:
                        child.setStyleSheet("""
                            QPushButton {
                                background-color: transparent;
                                color: #333333;
                                border: 1px solid #cccccc;
                                border-radius: 6px;
                                padding: 8px 20px;
                            }
                            QPushButton:hover {
                                background-color: #e0e0e0;
                                color: #222222;
                            }
                        """)
                    else:
                        child.setStyleSheet("""
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
                elif "保存" in text:
                    # 保存按钮保持蓝色，只调整细微差别
                    if is_light:
                        child.setStyleSheet("""
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
                    else:
                        child.setStyleSheet("""
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
    
    def _on_theme_changed(self, idx: int):
        """主题下拉框变化时：先 emit 事件让主窗口统一处理，再更新自身"""
        if idx < 0:
            return
        theme_key = list(self.THEMES.keys())[idx]
        from .theme_manager import ThemeManager
        actual_theme = ThemeManager.resolve_theme(theme_key)
        self._settings.setValue("theme", theme_key)
        self._settings.setValue("resolved_theme", actual_theme)

        # 1. 发送 THEME_CHANGED 事件，main_window 接收后会：
        #    - 调用 ThemeManager.apply_theme() 应用全局 QSS
        #    - 遍历所有模块设置 theme 属性
        #    - 回调本模块的 set_theme()（由 _applying 标志位防止二次触发）
        try:
            from .core import EventBus, EventType
            EventBus.get_instance().emit(EventType.THEME_CHANGED,
                                         {"theme": theme_key, "resolved_theme": actual_theme}, "settings_module")
        except Exception as e:
            logger.debug("主题变更事件发送失败: %s", e)

        # 2. 自身内联样式不在此直接刷新：主窗口 → ThemeManager.apply_theme →
        #    回调 refresh_module_themes → 本模块 set_theme，保证全局与本页同一次生效

    def _on_nav_mode_changed(self, idx: int):
        """导航栏显示模式变化：持久化 + 即时通知主窗口应用（full=图标+名称 / compact=仅图标）"""
        if idx < 0:
            return
        mode = self._nav_mode_combo.currentData() or "full"
        self._settings.setValue("nav_mode", mode)
        # settings_changed 信号已连到 main_window._on_settings_changed（即时生效）
        self.settings_changed.emit("nav_mode", {"nav_mode": mode})
    
    # ─────────────── 主题切换系统 END ───────────────
    
    def get_theme(self) -> str:
        """获取主题"""
        return list(self.THEMES.keys())[self._theme_combo.currentIndex()]
    
    def get_font_size(self) -> int:
        """获取字体大小"""
        return int(self._font_size_combo.currentText())
    
    def get_font_family(self) -> str:
        """获取字体"""
        return self._font_family_combo.currentText()
    
    def _create_module_toggle_tab(self) -> QWidget:
        """
        功能开关标签页：按 core/advanced/experimental 三层分组展示

        ┌────────────────────────────────────────────────────┐
        │ 架构说明：                                          │
        │                                                    │
        │  ModuleTier.CORE        → 默认开启，不可关闭（锁）  │
        │  ModuleTier.ADVANCED    → 默认关闭，可手动开启      │
        │  ModuleTier.EXPERIMENTAL → 默认关闭，不稳定测试      │
        │                                                    │
        │ 即时响应机制：                                       │
        │   每个可切换的复选框连接 toggled 信号 →               │
        │   _on_module_toggle_changed() →                    │
        │   registry.toggle() 持久化 →                       │
        │   EventBus.MODULE_CONFIG_CHANGED →                 │
        │   MainWindow 导航栏实时刷新                         │
        └────────────────────────────────────────────────────┘
        """
        registry = get_registry()
        all_modules = registry.all_modules()

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)

        # 顶部说明：向用户解释三层模块的含义和即时生效机制
        intro = QLabel(
            "控制左侧导航栏中显示的功能模块。\n"
            "• 核心功能：默认开启，不可关闭\n"
            "• 高级功能：面向进阶用户，手动开启\n"
            "• 实验功能：不稳定，仅用于测试\n"
            "\n勾选/取消即生效，导航栏实时更新。"
        )
        intro.setStyleSheet("color: #cccccc; font-size: 13px; padding: 10px;"
                            "background-color: #1a1a1a; border-radius: 8px;")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        # 按 tier 分组遍历，每个 tier 生成一个 QGroupBox
        tier_groups = [
            (ModuleTier.CORE, "🔒 核心功能（默认开启，不可关闭）"),
            (ModuleTier.ADVANCED, "⚡ 高级功能（手动开启）"),
            (ModuleTier.EXPERIMENTAL, "🧪 实验功能（不稳定）"),
        ]

        for tier, title in tier_groups:
            mods_in_tier = [m for m in all_modules if m["tier"] == tier]
            if not mods_in_tier:
                continue

            group = QGroupBox(title)
            group.setStyleSheet("""
                QGroupBox {
                    color: #ffffff;
                    border: 1px solid #333333;
                    border-radius: 8px;
                    margin-top: 12px;
                    padding: 12px;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    padding: 0 8px;
                    color: #cccccc;
                }
            """)
            group_layout = QVBoxLayout(group)
            group_layout.setSpacing(8)

            for mod in mods_in_tier:
                row = QHBoxLayout()
                row.setSpacing(12)

                name = mod["name"]
                icon = mod.get("icon", "")
                desc = mod.get("description", "")
                module_id = mod["id"]
                enabled = mod["enabled"]
                can_toggle = mod.get("can_disable", False)

                label_text = f"{icon} {name}" if icon else name
                label = QLabel(label_text)
                label
                label.setMinimumWidth(140)

                desc_label = QLabel(desc)
                desc_label.setStyleSheet("color: #888888; font-size: 12px;")
                desc_label.setWordWrap(True)

                left_col = QVBoxLayout()
                left_col.setSpacing(2)
                left_col.addWidget(label)
                left_col.addWidget(desc_label)

                row.addLayout(left_col, 1)

                # 复选框：核心不可关模块标记为 "必选" 并禁用交互
                checkbox = QCheckBox("开启" if can_toggle else "必选")
                checkbox.setChecked(True if (tier == ModuleTier.CORE and not can_toggle) else enabled)
                if not can_toggle:
                    # 核心模块不可关，置灰 + 禁用点击
                    checkbox.setEnabled(False)
                    checkbox.setStyleSheet("""
                        QCheckBox { color: #666666; }
                        QCheckBox::indicator {
                            width: 18px; height: 18px;
                            border-radius: 4px;
                            background-color: #333333;
                            border: 1px solid #555555;
                        }
                        QCheckBox::indicator:checked {
                            background-color: #1e6bde;
                            border: 1px solid #1e6bde;
                        }
                    """)
                else:
                    checkbox.setStyleSheet("""
                        QCheckBox { color: #ffffff; font-size: 13px; spacing: 8px; }
                        QCheckBox::indicator {
                            width: 18px; height: 18px;
                            border-radius: 4px;
                            background-color: #1a1a1a;
                            border: 2px solid #555555;
                        }
                        QCheckBox::indicator:checked {
                            background-color: #1e6bde;
                            border: 2px solid #1e6bde;
                        }
                        QCheckBox::indicator:hover {
                            border-color: #3b82f6;
                        }
                    """)

                # 登记到映射表，后续 _save_settings 和 _reset_all 需要遍历
                self._module_toggle_widgets[module_id] = checkbox
                # ✅ 即时响应：勾选/取消立刻写入注册表 + 刷新导航栏
                # 每个复选框的 toggled 信号连接 _on_module_toggle_changed，
                # 实现用户在复选框点击瞬间就完成持久化 + UI 刷新，
                # 无需额外点击「保存设置」按钮
                checkbox.toggled.connect(
                    lambda checked, mid=module_id: self._on_module_toggle_changed(mid, checked)
                )
                # 实验功能模块添加风险提示 tooltip
                if tier == ModuleTier.EXPERIMENTAL:
                    checkbox.setToolTip(
                        f"⚠️ 实验功能 - {desc}\n"
                        "该功能仍在开发中，可能存在不稳定或数据不完整的情况。\n"
                        "开启后如遇问题，请关闭此开关或反馈给开发团队。"
                    )
                    desc_label.setToolTip(
                        f"实验功能说明: {desc}\n"
                        "此模块尚在测试阶段，开启使用需评估风险。"
                    )
                row.addWidget(checkbox)

                group_layout.addLayout(row)

            layout.addWidget(group)

        layout.addStretch()
        return widget

    def _create_email_tab(self) -> QWidget:
        """创建邮箱设置标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)
        
        from .email_verify import email_verification_service, SMTP_PRESETS
        
        email_group = QGroupBox("邮箱验证设置")
        email_group
        email_layout = QFormLayout(email_group)
        
        # 预设选择
        self._smtp_preset_combo = QComboBox()
        self._smtp_preset_combo.addItems(list(SMTP_PRESETS.keys()))
        self._smtp_preset_combo.setMinimumWidth(200)
        self._smtp_preset_combo
        self._smtp_preset_combo.currentIndexChanged.connect(self._on_smtp_preset_changed)
        email_layout.addRow("邮箱服务商:", self._smtp_preset_combo)
        
        # SMTP服务器
        self._smtp_host_input = ModernLineEdit("SMTP服务器地址")
        email_layout.addRow("SMTP服务器:", self._smtp_host_input)
        
        # 端口
        self._smtp_port_spin = QSpinBox()
        self._smtp_port_spin.setRange(1, 65535)
        self._smtp_port_spin.setValue(465)
        self._smtp_port_spin
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
        self._smtp_ssl_check
        email_layout.addRow(self._smtp_ssl_check)
        
        layout.addWidget(email_group)
        
        # 测试按钮
        test_btn = QPushButton("测试连接")
        test_btn.clicked.connect(self._test_smtp_connection)
        # 修复：_test_smtp_connection 里通过 self._smtp_test_btn 禁用/改文案按钮，
        # 但此前从未把 test_btn 赋值给该属性，点击测试后必定 AttributeError 崩溃
        self._smtp_test_btn = test_btn
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
        """测试SMTP连接（QThread异步，防止UI卡死）"""
        from .email_verify import email_verification_service, SMTPConfig
        port = self._smtp_port_spin.value()
        host = self._smtp_host_input.text().strip()
        username = self._smtp_username_input.text().strip()
        password = self._smtp_password_input.text()
        sender_name = self._smtp_sender_input.text().strip()
        use_ssl = self._smtp_ssl_check.isChecked()
        
        if not host or not username or not password:
            QMessageBox.warning(self, "测试失败", "请填写完整的SMTP配置")
            return
        
        # 禁用测试按钮防止重复点击
        self._smtp_test_btn.setEnabled(False)
        self._smtp_test_btn.setText("⏳ 测试中...")
        self._smtp_status_label.setText("SMTP 配置状态: 正在测试...")
        self._smtp_status_label.setStyleSheet("color: #ff9800; font-size: 13px;")
        
        # 构建配置对象
        config = SMTPConfig(
            host=host, port=port, username=username, password=password,
            sender_name=sender_name or "AI短剧编辑器", use_ssl=use_ssl
        )
        
        # QThread 异步测试（5秒超时）
        class _SMTPTestWorker(QThread):
            result = Signal(bool, str)  # (success, message)
            
            def __init__(self, config, verification_service):
                super().__init__()
                self._config = config
                self._service = verification_service
                self._timeout = 5.0  # 5秒超时
            
            def run(self):
                import socket
                import smtplib
                import ssl
                start_time = __import__('time').time()
                try:
                    # 修复真实性问题：此前只做 TCP socket 连通性检查就弹"测试成功"，
                    # 用户名/密码错误、SSL/TLS 配置错误等真正会导致发信失败的场景
                    # 完全测不出来。这里改为真正走 smtplib 登录握手（不发送邮件），
                    # 才能验证账号密码/加密方式是否真的可用。
                    if self._config.use_ssl:
                        context = ssl.create_default_context()
                        with smtplib.SMTP_SSL(self._config.host, self._config.port, timeout=5, context=context) as server:
                            server.login(self._config.username, self._config.password)
                    else:
                        with smtplib.SMTP(self._config.host, self._config.port, timeout=5) as server:
                            server.starttls()
                            server.login(self._config.username, self._config.password)

                    ok = self._service.save_config(self._config)
                    elapsed = __import__('time').time() - start_time
                    if ok:
                        self.result.emit(True, f"SMTP 登录验证通过并已保存配置（耗时 {elapsed:.1f}秒）")
                    else:
                        self.result.emit(False, "登录验证通过，但配置保存失败，请检查磁盘权限")
                except smtplib.SMTPAuthenticationError:
                    self.result.emit(False, "SMTP 认证失败，请检查用户名和密码（部分服务商需使用「授权码」而非登录密码）")
                except smtplib.SMTPException as e:
                    self.result.emit(False, f"SMTP 协议错误: {e}")
                except socket.timeout:
                    self.result.emit(False, "连接超时（超过5秒），请检查SMTP服务器地址和端口")
                except socket.gaierror:
                    self.result.emit(False, f"无法解析主机名: {self._config.host}")
                except ConnectionRefusedError:
                    self.result.emit(False, f"连接被拒绝: {self._config.host}:{self._config.port}")
                except Exception as e:
                    self.result.emit(False, f"测试失败: {str(e)}")
        
        self._smtp_worker = _SMTPTestWorker(config, email_verification_service)
        
        def on_result(success: bool, message: str):
            self._smtp_test_btn.setEnabled(True)
            self._smtp_test_btn.setText("🧪 测试连接")
            if success:
                QMessageBox.information(self, "测试成功", message)
                self._smtp_status_label.setText("SMTP 配置状态: 已配置")
                self._smtp_status_label.setStyleSheet("color: #22c55e; font-size: 13px;")
            else:
                QMessageBox.warning(self, "测试失败", message)
                self._smtp_status_label.setText("SMTP 配置状态: 未配置")
                self._smtp_status_label.setStyleSheet("color: #ef4444; font-size: 13px;")
        
        self._smtp_worker.result.connect(on_result)
        self._smtp_worker.start()
    
    def _create_cache_tab(self) -> QWidget:
        # 2026-11-13 重做：可展开、按项清理（原实现一行一类 + 整类全删）。
        # 正文独立成文件，避免本文件顶破单文件规模守卫。
        from app.modules.lego.settings_cache_tab import build_cache_tab

        return build_cache_tab(self)

    def _create_team_tab(self) -> QWidget:
        # 正文单独成文件：本文件已顶到单文件规模守卫（基线 2823 / 容差 30）
        from app.modules.lego.settings_team_tab import build_team_tab
        return build_team_tab(self)

    def _create_language_tab(self) -> QWidget:
        """语言切换标签页 - 使用下拉框，像正常软件一样"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)

        title = QLabel("🌐 语言切换")
        layout.addWidget(title)

        desc = QLabel("选择界面显示语言，切换后即时生效")
        desc.setStyleSheet("color: #999; font-size: 13px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        lang_group = QGroupBox("界面语言")
        lang_layout = QFormLayout(lang_group)
        lang_layout.setSpacing(12)

        self._lang_combo = QComboBox()
        self._lang_combo.setMinimumWidth(280)
        self._lang_combo.setStyleSheet("""
            QComboBox {
                color: #ffffff;
                background-color: #1a1a1a;
                border: 2px solid #333333;
                border-radius: 8px;
                padding: 12px 16px;
                font-size: 14px;
                min-height: 20px;
            }
            QComboBox:hover {
                border-color: #555555;
            }
            QComboBox:focus {
                border-color: #1e6bde;
            }
            QComboBox::drop-down {
                border: none;
                width: 36px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 6px solid #888888;
                margin-right: 8px;
            }
            QComboBox QAbstractItemView {
                background-color: #1a1a1a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 6px;
                padding: 4px;
                selection-background-color: #1e3a5f;
                selection-color: #ffffff;
                outline: none;
            }
            QComboBox QAbstractItemView::item {
                padding: 10px 16px;
                border-radius: 4px;
            }
            QComboBox QAbstractItemView::item:hover {
                background-color: #2a2a2a;
            }
        """)

        self._languages = [
            ("zh_CN", "🇨🇳  简体中文"),
            ("zh_TW", "🇹🇼  繁體中文"),
            ("en_US", "🇺🇸  English"),
            ("ja_JP", "🇯🇵  日本語"),
            ("ko_KR", "🇰🇷  한국어"),
        ]

        for code, name in self._languages:
            self._lang_combo.addItem(name, code)

        # 显示当前语言
        try:
            from app.core.i18n import _
            current_lang = getattr(_, '__self__', None)
            if hasattr(current_lang, 'locale'):
                locale = current_lang.locale
                for i, (code, _) in enumerate(self._languages):
                    if code == locale:
                        self._lang_combo.setCurrentIndex(i)
                        break
        except Exception:
            self._lang_combo.setCurrentIndex(0)

        lang_layout.addRow("选择语言:", self._lang_combo)

        layout.addWidget(lang_group)

        # 应用按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        apply_btn = QPushButton("应用语言")
        apply_btn.clicked.connect(self._apply_language)
        apply_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e6bde;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px 32px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1a5bc4;
            }
        """)
        btn_row.addWidget(apply_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        note = QLabel("💡 提示：切换语言后部分界面文字可能需重新打开模块生效")
        note.setStyleSheet("color: #666; font-size: 11px; padding-top: 10px;")
        note.setWordWrap(True)
        layout.addWidget(note)

        layout.addStretch()
        return widget

    def _apply_language(self):
        """应用选择的语言"""
        idx = self._lang_combo.currentIndex()
        if 0 <= idx < len(self._languages):
            code = self._languages[idx][0]
            try:
                from app.core.i18n import set_locale
                set_locale(code)
                QMessageBox.information(self, "语言切换", f"已切换到 {self._languages[idx][1]}\n部分模块可能需要重新进入生效")
            except Exception as e:
                QMessageBox.warning(self, "切换失败", f"无法切换语言: {e}")

    def _create_about_tab(self) -> QWidget:
        """关于拾光剪影：项目信息 + 版本号（精美版）"""
        try:
            from app.version import __version__, VERSION_INFO
        except Exception:
            __version__ = "4.7.0"
            VERSION_INFO = {
                "codename": "未知", "release_date": "未知",
                "description": "无法加载版本信息"
            }

        codename = VERSION_INFO.get('codename', '-')
        release_date = VERSION_INFO.get('release_date', '-')

        widget = QWidget()
        widget.setStyleSheet("background: transparent;")
        out = QVBoxLayout(widget)
        out.setContentsMargins(40, 36, 40, 28)
        out.setSpacing(0)

        # ═══════════════════════════════════════════════════════
        # 1. Logo + 名称 区域
        # ═══════════════════════════════════════════════════════
        logo_card = QFrame()
        logo_card.setFixedHeight(160)
        logo_card.setStyleSheet(
            "QFrame#aboutLogo {"
            "  background: qlineargradient(x1:0 y1:0, x2:1 y2:1,"
            "    stop:0 #14192d, stop:1 #1a1030);"
            "  border: 1px solid #2a2a40; border-radius: 16px;"
            "}"
        )
        logo_card.setObjectName("aboutLogo")
        logo_lo = QVBoxLayout(logo_card)
        logo_lo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_lo.setSpacing(6)

        # Logo 图标
        icon_lbl = QLabel("🎬")
        icon_lbl.setStyleSheet("font-size: 42px; background: transparent; border: none;")
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_lo.addWidget(icon_lbl)

        # 标题
        name_lbl = QLabel("拾光剪影")
        name_lbl.setStyleSheet(
            "font-size: 30px; font-weight: bold; color: #e0e0ff;"
            "background: transparent; border: none;"
        )
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_lo.addWidget(name_lbl)

        # 副标题
        tag_lbl = QLabel("AI 短剧智能编辑器")
        tag_lbl.setStyleSheet(
            "font-size: 13px; color: #7b8cbf; letter-spacing: 2px;"
            "background: transparent; border: none;"
        )
        tag_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_lo.addWidget(tag_lbl)

        out.addWidget(logo_card)
        out.addSpacing(24)

        # 1.5 代表形象「拾岚」（2026-10-20）——卡片实现独立成文件，不推高本文件行数
        from .about_mascot_card import build_about_mascot_card

        _about_mascot = build_about_mascot_card()
        if _about_mascot is not None:
            out.addWidget(_about_mascot)
            out.addSpacing(20)

        # ═══════════════════════════════════════════════════════
        # 2. 版本号徽章
        # ═══════════════════════════════════════════════════════
        ver_card = QFrame()
        ver_card.setStyleSheet(
            "QFrame#aboutVer {"
            "  background-color: #141820; border: 1px solid #2a2f3a;"
            "  border-radius: 12px; padding: 4px;"
            "}"
        )
        ver_card.setObjectName("aboutVer")
        ver_lo = QHBoxLayout(ver_card)
        ver_lo.setContentsMargins(24, 16, 24, 16)
        ver_lo.setSpacing(16)

        # 版本号大数字
        ver_num = QLabel(__version__)
        ver_num.setStyleSheet(
            "font-size: 38px; font-weight: 900; color: #6c9fff;"
            "background: transparent; border: none;"
        )
        ver_lo.addWidget(ver_num)

        # 右侧信息
        right_col = QVBoxLayout()
        right_col.setSpacing(4)

        label_style = "color: #8a8fa0; font-size: 11px; background: transparent; border: none;"
        value_style = "color: #c8ccd8; font-size: 12px; background: transparent; border: none;"

        codename_lbl = QLabel(f"代号 — {codename}")
        codename_lbl.setStyleSheet(value_style)
        right_col.addWidget(codename_lbl)

        date_lbl = QLabel(f"发布于 — {release_date}")
        date_lbl.setStyleSheet(label_style)
        right_col.addWidget(date_lbl)

        ver_lo.addLayout(right_col)
        ver_lo.addStretch()

        out.addWidget(ver_card)
        out.addSpacing(20)

        # ═══════════════════════════════════════════════════════
        # 3. 技术栈标签
        # ═══════════════════════════════════════════════════════
        tech_lbl = QLabel("技术栈")
        tech_lbl.setStyleSheet("font-size: 13px; font-weight: bold; color: #666;"
                               "background: transparent; border: none; padding: 0 4px;")
        out.addWidget(tech_lbl)
        out.addSpacing(10)

        tech_grid = QGridLayout()
        tech_grid.setHorizontalSpacing(10)
        tech_grid.setVerticalSpacing(10)

        tags = [
            ("🐍", "Python 3.12"),
            ("🖥️", "PySide6"),
            ("🤖", "OpenAI API"),
            ("🎞️", "MoviePy"),
            ("⚙️", "FFmpeg"),
            ("🔀", "librosa"),
            ("🔢", "NumPy"),
            ("📁", "Git"),
        ]
        for i, (emoji, name) in enumerate(tags):
            row, col = i // 4, i % 4
            tag = QFrame()
            tag.setStyleSheet(
                "QFrame {"
                "  background-color: #1a1e28; border: 1px solid #2a2f3a;"
                "  border-radius: 8px;"
                "}"
            )
            tag_lo = QHBoxLayout(tag)
            tag_lo.setContentsMargins(12, 8, 12, 8)
            tag_lo.setSpacing(6)

            em = QLabel(emoji)
            em.setStyleSheet("font-size: 14px; background: transparent; border: none;")
            tag_lo.addWidget(em)

            nm = QLabel(name)
            nm.setStyleSheet("font-size: 12px; color: #a0a6b8; background: transparent; border: none;")
            tag_lo.addWidget(nm)

            tech_grid.addWidget(tag, row, col)

        out.addLayout(tech_grid)
        out.addStretch()

        # ═══════════════════════════════════════════════════════
        # 4b. 一键环境诊断（复用 core 检测能力，只读不改配置）
        # ═══════════════════════════════════════════════════════
        diag_btn = QPushButton("🧰  一键环境诊断")
        diag_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        diag_btn.setStyleSheet(
            "QPushButton {"
            "  background-color: #1a2a4a; color: #6c9fff; border: 1px solid #2a3a5a;"
            "  border-radius: 10px; padding: 10px 18px; font-size: 13px; font-weight: 600;"
            "}"
            "QPushButton:hover { background-color: #223a5a; color: #8fb4ff; }"
        )
        diag_btn.clicked.connect(lambda: EnvironmentDiagnosticDialog(
            self._get_diagnostic_anchor()
        ).exec())
        out.addWidget(diag_btn)
        out.addSpacing(8)

        # ═══════════════════════════════════════════════════════
        # 4. 版权
        # ═══════════════════════════════════════════════════════
        copyright_lbl = QLabel("© 2026 拾光剪影 · 保留所有权利")
        copyright_lbl.setStyleSheet("color: #404860; font-size: 10px; background: transparent;")
        copyright_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        out.addWidget(copyright_lbl)

        return widget

    def _get_diagnostic_anchor(self):
        """返回环境诊断对话框的安全父窗口（当前模块所在顶层窗口，未找到则 None）"""
        w = self.window()
        return w if w is not None and w is not self else self


class EnvironmentDiagnosticDialog(QDialog):
    """一键环境诊断对话框 — 只读检测 FFmpeg / FFprobe / 硬件加速 / AI Provider

    复用 core 层既有检测能力（FFmpegTool、HardwareDetector、AIEngine.get_available_providers），
    不重复实现检测逻辑；结果仅供展示与引导，不修改任何配置。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🧰 环境诊断")
        self.setMinimumSize(560, 460)
        self.setStyleSheet("background-color: #0f1115; color: #d0d4df;")
        self._build_ui()
        self._run_diagnostics()

    def _build_ui(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(24, 20, 24, 16)
        lo.setSpacing(10)

        title = QLabel("🧰 环境诊断")
        title.setStyleSheet("font-size: 20px; font-weight: 900; color: #6c9fff; background: transparent;")
        lo.addWidget(title)

        tip = QLabel("检测视频剪辑与 AI 生成所需的关键依赖，只读不修改配置。")
        tip.setStyleSheet("color: #8a8fa0; font-size: 12px; background: transparent;")
        tip.setWordWrap(True)
        lo.addWidget(tip)
        lo.addSpacing(6)

        # 诊断条目容器
        self._rows: List = []
        for key, label in [
            ("ffmpeg", "FFmpeg 视频处理"),
            ("ffprobe", "FFprobe 媒体探测"),
            ("gpu", "GPU 硬件加速"),
            ("ai", "AI 能力（本地/云端模型）"),
        ]:
            row = QFrame()
            row.setStyleSheet("QFrame { background-color: #161a22; border: 1px solid #232833; border-radius: 10px; }")
            rlo = QHBoxLayout(row)
            rlo.setContentsMargins(16, 12, 16, 12)
            icon = QLabel("⏳")
            icon.setStyleSheet("font-size: 16px; background: transparent;")
            name = QLabel(label)
            name.setStyleSheet("color: #c8ccd8; font-size: 13px; font-weight: 600; background: transparent;")
            detail = QLabel("检测中…")
            detail.setWordWrap(True)
            detail.setStyleSheet("color: #8a8fa0; font-size: 11px; background: transparent;")
            rlo.addWidget(icon)
            rlo.addWidget(name, 1)
            rlo.addWidget(detail, 2)
            lo.addWidget(row)
            self._rows.append({"key": key, "icon": icon, "detail": detail})

        lo.addStretch()

        hint = QLabel("若某项显示异常，可到对应配置页补齐后重试；或点击下方 \"重新检测\"。")
        hint.setStyleSheet("color: #606878; font-size: 11px; background: transparent;")
        hint.setWordWrap(True)
        lo.addWidget(hint)

        btn_row = QHBoxLayout()
        recheck_btn = QPushButton("🔄 重新检测")
        recheck_btn.clicked.connect(self._run_diagnostics)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(recheck_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        lo.addLayout(btn_row)

        self._summary = QLabel("")
        self._summary.setStyleSheet("color: #404860; font-size: 12px; font-weight: 600; background: transparent;")
        self._summary.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lo.addWidget(self._summary)

    # ── 核心：驱动 core 层检测并渲染结果 ──
    def _run_diagnostics(self):
        for row in self._rows:
            row["icon"].setText("⏳")
            row["detail"].setText("检测中…")

        rm = _safe_import_core("render_manager")
        ai_mod = _safe_import_core("ai_engine")

        # 1. FFmpeg / FFprobe
        ffmpeg_path = ""
        if rm and hasattr(rm, "FFmpegTool"):
            try:
                ffmpeg_path = rm.FFmpegTool.find_ffmpeg() or ""
            except Exception as e:
                logger.debug("检测 ffmpeg 路径失败: %s", e)
        if ffmpeg_path:
            self._set_row("ffmpeg", "✅", f"已就绪：{ffmpeg_path}")
        else:
            self._set_row("ffmpeg", "❌", "未找到 ffmpeg，导出视频将不可用。请安装 FFmpeg 或配置其路径。")

        ffprobe_path = ""
        if rm and hasattr(rm, "FFmpegTool"):
            try:
                ffprobe_path = rm.FFmpegTool.find_ffprobe() or ""
            except Exception as e:
                logger.debug("检测 ffprobe 路径失败: %s", e)
        if ffprobe_path:
            self._set_row("ffprobe", "✅", f"已就绪：{ffprobe_path}")
        else:
            self._set_row("ffprobe", "❌", "未找到 ffprobe，媒体信息探测功能将受限。")

        # 2. GPU 硬件加速
        if rm and hasattr(rm, "HardwareDetector"):
            try:
                hw = rm.HardwareDetector.detect()
                if hw.get("has_gpu"):
                    enc = hw.get("available_encoders") or []
                    self._set_row("gpu", "✅", f"已启用硬件加速（{hw.get('gpu_vendor', 'gpu')}）· 可用编码器: {', '.join(enc) if enc else '软件编码'}")
                elif hw.get("available_encoders"):
                    self._set_row("gpu", "⚡", f"软件编码（无独立 GPU 加速卡），但可用编码器: {', '.join(hw['available_encoders'])}")
                else:
                    self._set_row("gpu", "ℹ️", "未检测到 GPU 硬件加速，将使用 CPU 软件编码（较慢但兼容性最好）。")
            except Exception as e:
                logger.debug("检测 GPU 失败: %s", e)
                self._set_row("gpu", "⚠️", "硬件加速检测失败，将回退软件编码。")
        else:
            self._set_row("gpu", "ℹ️", "检测模块不可用，无法读取硬件信息。")

        # 3. AI 能力
        if ai_mod:
            try:
                engine = ai_mod.AIEngine()
                providers = engine.get_available_providers()
                # 分离本地 / 云端便于展示
                labels = ", ".join(providers) if providers else "无"
                local = [p for p in providers if p == "ollama"]
                cloud = [p for p in providers if p != "ollama"]
                note = ""
                if local and not cloud:
                    note = "（仅本地 Ollama）"
                elif cloud and not local:
                    note = "（云端模型）"
                elif local and cloud:
                    note = "（本地 + 云端）"
                status = "✅" if providers else "❌"
                self._set_row("ai", status, f"可用模型: {labels}{note}" if providers else "未配置可用模型 — 请到模型设置中配置。")
            except Exception as e:
                logger.error("检测 AI 能力失败: %s", e, exc_info=True)
                self._set_row("ai", "⚠️", f"AI 能力检测失败：{e}")
        else:
            self._set_row("ai", "ℹ️", "AI 引擎模块不可用。")

        # 汇总
        ok = sum(1 for r in self._rows if r["icon"].text() == "✅")
        warn = sum(1 for r in self._rows if r["icon"].text() in ("⚠️", "⚡", "ℹ️"))
        bad = sum(1 for r in self._rows if r["icon"].text() == "❌")
        total = len(self._rows)
        if bad == 0:
            self._summary.setText(f"检测完成：{ok}/{total} 正常 · {warn} 项提示 · 环境基本可用")
            self._summary.setStyleSheet("color: #3fb28a; background: transparent; font-size: 12px; font-weight: 600;")
        else:
            self._summary.setText(f"检测完成：{ok}/{total} 正常 · {bad} 项缺失（可能导致导出或 AI 功能异常）")
            self._summary.setStyleSheet("color: #e0655a; background: transparent; font-size: 12px; font-weight: 600;")

    def _set_row(self, key: str, icon: str, detail: str):
        """按 key 更新某一行诊断条目的图标与详情"""
        for row in self._rows:
            if row["key"] == key:
                row["icon"].setText(icon)
                row["detail"].setText(detail)
                return

    # ── 启动时自动检测封装（供启动流程复用）──
    @staticmethod
    def startup_check(parent=None) -> bool:
        """启动时快速检测关键依赖；仅对严重缺失（无 FFmpeg）弹一次性提示。返回 True 表示环境基本可用。"""
        rm = _safe_import_core("render_manager")
        if not rm or not hasattr(rm, "FFmpegTool"):
            return True
        try:
            ffmpeg_path = rm.FFmpegTool.find_ffmpeg()
            if not ffmpeg_path:
                QMessageBox.warning(
                    parent,
                    "环境提示",
                    "未检测到 FFmpeg，导出视频功能将不可用。\n\n"
                    "建议在设置 → 关于 → 一键环境诊断中查看详情，或安装 FFmpeg 后重试。",
                )
                return False
        except Exception as e:
            logger.debug("启动时 FFmpeg 检测失败（不阻塞启动）: %s", e)
        return True








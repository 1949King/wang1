"""
全局主题管理器 (ThemeManager)
================================
解决两大历史问题：
1. 切换主题卡死 → 不再使用 findChildren + unpolish/polish 遍历
2. 子模块不响应 → 通过 QApplication 级别 QSS 一次性覆盖所有控件

核心思路：
- 全局 QSS 通过 QApplication.setStyleSheet() 应用
- 使用属性选择器（[theme="light"]/[theme="dark"]）自动响应
- 主窗口的 setProperty("theme", ...) 触发子控件级联更新
- 防递归标志位避免 EventBus 往复触发
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtCore import QSettings

logger = logging.getLogger("AI短剧编辑器.theme")


class ThemeManager:
    """
    全局主题管理单例

    使用方式：
        tm = ThemeManager.instance()
        tm.apply_theme("light")  # 应用浅色主题，自动同步所有窗口和模块
    """

    _instance: Optional["ThemeManager"] = None

    # ───── 颜色常量表 ─────
    COLORS_DARK = {
        "bg_main": "#070a12",
        "bg_secondary": "#101621",
        "bg_tertiary": "#172033",
        "bg_hover": "#1f2b42",
        "text_primary": "#edf3ff",
        "text_secondary": "#aab6cc",
        "text_disabled": "#667085",
        "text_on_accent": "#f8fbff",
        "border": "#253044",
        "border_light": "#1c2638",
        "accent": "#2f7bff",
        "accent_hover": "#4d8dff",
        "accent_soft": "#102a4d",
        "focus": "#6ba4ff",
        "success": "#2dd4bf",
        "danger": "#fb7185",
        "scrollbar_bg": "#0d1320",
        "scrollbar_handle": "#2a3650",
        "scrollbar_hover": "#3a4a68",
    }

    COLORS_LIGHT = {
        "bg_main": "#f4f7fb",
        "bg_secondary": "#fcfdff",
        "bg_tertiary": "#eaf0f7",
        "bg_hover": "#dde7f4",
        "text_primary": "#172033",
        "text_secondary": "#56657a",
        "text_disabled": "#8a97aa",
        "text_on_accent": "#f8fbff",
        "border": "#d7e0ec",
        "border_light": "#e3eaf3",
        "accent": "#2563eb",
        "accent_hover": "#1d4ed8",
        "accent_soft": "#dbeafe",
        "focus": "#3b82f6",
        "success": "#0f766e",
        "danger": "#e11d48",
        "scrollbar_bg": "#edf2f7",
        "scrollbar_handle": "#c2ccda",
        "scrollbar_hover": "#98a8bd",
    }

    # ───── 预编译的 QSS 模板 ─────
    @staticmethod
    def _build_qss(c: dict, theme_name: str) -> str:
        """根据颜色表生成完整 QSS"""
        return f"""
        /* ─────────── 全局通用样式（属性选择器 [theme="{theme_name}"]）─────────── */
        QMainWindow[theme="{theme_name}"] {{
            background-color: {c['bg_main']};
        }}
        QWidget[theme="{theme_name}"] {{
            background-color: {c['bg_main']};
            color: {c['text_primary']};
            font-family: "Microsoft YaHei UI", "Segoe UI", Arial, sans-serif;
        }}
        QWidget[theme="{theme_name}"]#contentContainer,
        QWidget[theme="{theme_name}"]#moduleContainer {{
            background-color: {c['bg_main']};
        }}

        QLabel[theme="{theme_name}"] {{
            color: {c['text_primary']};
            background-color: transparent;
        }}
        QLabel[theme="{theme_name}"]#titleLabel {{
            color: {c['text_primary']};
            font-size: 28px;
            font-weight: 700;
        }}
        QLabel[theme="{theme_name}"]#subtitleLabel {{
            color: {c['text_secondary']};
            font-size: 14px;
        }}
        QLabel[theme="{theme_name}"]#hintLabel {{
            color: {c['text_disabled']};
            font-size: 11px;
        }}

        QPushButton[theme="{theme_name}"] {{
            color: {c['text_primary']};
            background-color: {c['bg_tertiary']};
            border: 1px solid {c['border']};
            border-radius: 8px;
            padding: 8px 16px;
            font-size: 13px;
            font-weight: 500;
        }}
        QPushButton[theme="{theme_name}"]:hover {{
            background-color: {c['bg_hover']};
            border-color: {c['focus']};
        }}
        QPushButton[theme="{theme_name}"]:pressed {{
            background-color: {c['accent_soft']};
            border-color: {c['accent']};
        }}
        QPushButton[theme="{theme_name}"]:disabled {{
            color: {c['text_disabled']};
            background-color: {c['bg_tertiary']};
            border-color: {c['border_light']};
        }}
        QPushButton[theme="{theme_name}"]#primaryBtn {{
            background-color: {c['accent']};
            color: {c['text_on_accent']};
            border: none;
            font-weight: 700;
        }}
        QPushButton[theme="{theme_name}"]#primaryBtn:hover {{
            background-color: {c['accent_hover']};
        }}
        QPushButton[theme="{theme_name}"]#dangerBtn {{
            color: {c['danger']};
            background-color: transparent;
            border: none;
        }}
        QPushButton[theme="{theme_name}"]#dangerBtn:hover {{
            color: {c['danger']};
            background-color: {c['bg_hover']};
        }}

        QGroupBox[theme="{theme_name}"] {{
            color: {c['text_primary']};
            border: 1px solid {c['border']};
            border-radius: 12px;
            padding: 16px;
            margin-top: 12px;
            background-color: {c['bg_secondary']};
        }}
        QGroupBox[theme="{theme_name}"]::title {{
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 6px;
            color: {c['text_primary']};
        }}

        QComboBox[theme="{theme_name}"] {{
            background-color: {c['bg_secondary']};
            color: {c['text_primary']};
            border: 1px solid {c['border']};
            border-radius: 8px;
            padding: 6px 12px;
            min-height: 20px;
        }}
        QComboBox[theme="{theme_name}"]:hover {{
            border-color: {c['focus']};
        }}
        QComboBox[theme="{theme_name}"]:focus {{
            border-color: {c['accent']};
            background-color: {c['bg_tertiary']};
        }}
        QComboBox[theme="{theme_name}"]::drop-down {{
            border: none;
            width: 24px;
        }}
        QComboBox[theme="{theme_name}"] QAbstractItemView {{
            background-color: {c['bg_secondary']};
            color: {c['text_primary']};
            border: 1px solid {c['border']};
            selection-background-color: {c['accent']};
            selection-color: {c['text_on_accent']};
            outline: none;
        }}

        QLineEdit[theme="{theme_name}"], QTextEdit[theme="{theme_name}"], QPlainTextEdit[theme="{theme_name}"] {{
            background-color: {c['bg_secondary']};
            color: {c['text_primary']};
            border: 1px solid {c['border']};
            border-radius: 8px;
            padding: 8px 12px;
            font-size: 13px;
        }}
        QLineEdit[theme="{theme_name}"]:focus, QTextEdit[theme="{theme_name}"]:focus {{
            border-color: {c['accent']};
            background-color: {c['bg_tertiary']};
        }}

        QSpinBox[theme="{theme_name}"], QDoubleSpinBox[theme="{theme_name}"] {{
            background-color: {c['bg_secondary']};
            color: {c['text_primary']};
            border: 1px solid {c['border']};
            border-radius: 8px;
            padding: 4px 8px;
        }}

        QKeySequenceEdit[theme="{theme_name}"] {{
            background-color: {c['bg_secondary']};
            color: {c['text_primary']};
            border: 1px solid {c['border']};
            border-radius: 8px;
            padding: 6px 10px;
        }}
        QKeySequenceEdit[theme="{theme_name}"]:focus {{
            border-color: {c['accent']};
        }}

        QCheckBox[theme="{theme_name}"], QRadioButton[theme="{theme_name}"] {{
            color: {c['text_primary']};
            background-color: transparent;
            spacing: 6px;
        }}

        QTableWidget[theme="{theme_name}"], QTableView[theme="{theme_name}"], QTableWidget[theme="{theme_name}"] QTableWidget,
        QTableView[theme="{theme_name}"] QTableWidget {{
            background-color: {c['bg_secondary']};
            color: {c['text_primary']};
            gridline-color: {c['border']};
            border: 1px solid {c['border']};
            border-radius: 10px;
            alternate-background-color: {c['bg_tertiary']};
        }}
        QTableWidget[theme="{theme_name}"]::item, QTableView[theme="{theme_name}"]::item {{
            padding: 8px;
            border-bottom: 1px solid {c['border_light']};
        }}
        QTableWidget[theme="{theme_name}"]::item:selected, QTableView[theme="{theme_name}"]::item:selected {{
            background-color: {c['accent_soft']};
            color: {c['text_primary']};
        }}
        QHeaderView[theme="{theme_name}"]::section {{
            background-color: {c['bg_tertiary']};
            color: {c['text_primary']};
            padding: 8px;
            border: none;
            border-bottom: 1px solid {c['border']};
            font-weight: 600;
        }}

        QScrollArea[theme="{theme_name}"] {{
            background-color: {c['bg_main']};
            border: none;
        }}
        QScrollArea[theme="{theme_name}"] > QWidget > QWidget {{
            background-color: {c['bg_main']};
        }}

        QScrollBar:vertical {{
            background-color: {c['scrollbar_bg']};
            width: 8px;
            margin: 0;
            border-radius: 4px;
        }}
        QScrollBar::handle:vertical {{
            background-color: {c['scrollbar_handle']};
            border-radius: 4px;
            min-height: 24px;
        }}
        QScrollBar::handle:vertical:hover {{
            background-color: {c['scrollbar_hover']};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0;
        }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            background: none;
        }}
        QScrollBar:horizontal {{
            background-color: {c['scrollbar_bg']};
            height: 8px;
            margin: 0;
            border-radius: 4px;
        }}
        QScrollBar::handle:horizontal {{
            background-color: {c['scrollbar_handle']};
            border-radius: 4px;
            min-width: 24px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background-color: {c['scrollbar_hover']};
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            width: 0;
        }}
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
            background: none;
        }}

        QTabWidget[theme="{theme_name}"]::pane {{
            border: none;
            background-color: {c['bg_main']};
        }}
        QTabBar[theme="{theme_name}"]::tab {{
            background-color: {c['bg_secondary']};
            color: {c['text_secondary']};
            padding: 10px 20px;
            margin-right: 4px;
            border: 1px solid {c['border_light']};
            border-bottom: none;
            border-top-left-radius: 8px;
            border-top-right-radius: 8px;
            font-size: 13px;
        }}
        QTabBar[theme="{theme_name}"]::tab:selected {{
            background-color: {c['bg_tertiary']};
            color: {c['text_primary']};
            border-color: {c['border']};
        }}
        QTabBar[theme="{theme_name}"]::tab:hover:!selected {{
            background-color: {c['bg_hover']};
            color: {c['text_primary']};
        }}

        QFrame[theme="{theme_name}"]#sideBar,
        QWidget[theme="{theme_name}"]#sideBar {{
            background-color: {c['bg_secondary']};
            border-right: 1px solid {c['border_light']};
        }}
        QFrame[theme="{theme_name}"]#headerBar {{
            background-color: {c['bg_secondary']};
            border-bottom: 1px solid {c['border_light']};
        }}
        QFrame[theme="{theme_name}"]#bottomBar {{
            background-color: {c['bg_secondary']};
            border-top: 1px solid {c['border_light']};
        }}

        QProgressBar[theme="{theme_name}"] {{
            background-color: {c['bg_tertiary']};
            border: 1px solid {c['border_light']};
            border-radius: 6px;
            text-align: center;
            color: {c['text_primary']};
        }}
        QProgressBar[theme="{theme_name}"]::chunk {{
            background-color: {c['accent']};
            border-radius: 6px;
        }}

        QStatusBar[theme="{theme_name}"] {{
            background-color: {c['bg_secondary']};
            color: {c['text_secondary']};
        }}

        QToolTip[theme="{theme_name}"] {{
            background-color: {c['bg_tertiary']};
            color: {c['text_primary']};
            border: 1px solid {c['border']};
            border-radius: 8px;
            padding: 4px 8px;
        }}

        QMenu[theme="{theme_name}"] {{
            background-color: {c['bg_secondary']};
            color: {c['text_primary']};
            border: 1px solid {c['border']};
            border-radius: 8px;
            padding: 4px;
        }}
        QMenu[theme="{theme_name}"]::item:selected {{
            background-color: {c['accent']};
            color: {c['text_on_accent']};
            border-radius: 6px;
        }}
        """

    def __init__(self):
        self._app: Optional[QApplication] = None
        self._current_theme: str = "dark"
        self._theme_preference: str = "dark"
        self._applying: bool = False  # 防递归标志

    # ───── 单例 ─────
    @classmethod
    def instance(cls) -> "ThemeManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ───── 主题查询 ─────
    @property
    def current_theme(self) -> str:
        return self._current_theme

    @property
    def theme_preference(self) -> str:
        """返回用户选择的主题偏好，可能是 light / dark / auto。"""
        return self._theme_preference

    @property
    def is_light(self) -> bool:
        return self._current_theme == "light"

    def get_colors(self) -> dict:
        """获取当前主题的颜色表"""
        return self.COLORS_LIGHT if self.is_light else self.COLORS_DARK

    @staticmethod
    def resolve_theme(theme: str) -> str:
        """把 auto 解析为实际主题，确保 ThemeManager 只应用 light / dark。"""
        if theme == "auto":
            hour = datetime.now().hour
            return "light" if 6 <= hour < 18 else "dark"
        return "light" if theme == "light" else "dark"

    # ───── 应用主题 ─────
    def apply_theme(self, theme: str, main_window: Optional[QWidget] = None) -> None:
        """
        应用主题到整个应用程序

        参数：
            theme: "light"、"dark" 或 "auto"
            main_window: 主窗口实例（用于设置根属性，子控件级联继承）
        """
        # 防递归：避免 EventBus 往复触发导致的死循环
        if self._applying:
            return
        if theme not in ("light", "dark", "auto"):
            return
        resolved_theme = self.resolve_theme(theme)
        if (resolved_theme == self._current_theme and
                theme == self._theme_preference and main_window is None):
            return

        self._applying = True
        try:
            self._do_apply_theme(theme, resolved_theme, main_window)
        except Exception as e:
            logger.exception(f"应用主题失败: {e}")
        finally:
            self._applying = False

    def _do_apply_theme(self, preference: str, theme: str, main_window: Optional[QWidget]) -> None:
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            logger.warning("QApplication 未初始化，无法应用主题")
            return

        # 选择颜色表和 QSS
        colors = self.COLORS_LIGHT if theme == "light" else self.COLORS_DARK
        qss = self._build_qss(colors, theme)

        # 1. 设置 application 级别 QSS（一次性应用到所有窗口）
        app.setStyleSheet(qss)

        # 2. 给主窗口设置 theme 属性，让所有子控件通过属性选择器自动响应
        if main_window is not None:
            self._apply_theme_property(main_window, theme)

        # 3. 遍历所有顶层窗口（对话框、子窗口等）也设置属性
        for top in app.topLevelWidgets():
            if top is not main_window:
                self._apply_theme_property(top, theme)

        # 4. 持久化
        try:
            for org, app_name in (("AI短剧编辑器", "Theme"), ("拾光剪影", "Settings")):
                settings = QSettings(org, app_name)
                settings.setValue("theme", preference)
                settings.setValue("resolved_theme", theme)
        except Exception as e:
            logger.debug("持久化主题设置失败: %s", e)

        self._current_theme = theme
        self._theme_preference = preference
        logger.info("主题已切换: %s (preference=%s)", theme, preference)

    @staticmethod
    def _apply_theme_property(widget: QWidget, theme: str) -> None:
        """
        给 widget 及其所有子控件设置 theme 属性
        不使用 unpolish/polish（性能差），依靠 setStyleSheet 全局刷新自动生效

        关键点：只设置属性，不调用 unpolish/polish
        """
        widget.setProperty("theme", theme)
        # 直接遍历设置属性（不调用 unpolish/polish）
        for child in widget.findChildren(QWidget):
            child.setProperty("theme", theme)

    # ───── 便利方法：清除子控件的内联样式（可选） ─────
    def clear_inline_styles(self, root: QWidget, preserve_semantic: bool = True) -> None:
        """
        清除子控件的内联样式，让全局 QSS 生效

        注意：此方法会破坏有意义的内联样式，谨慎使用。
        preserve_semantic=True 时，保留包含语义色（蓝/橙/绿/红）的样式
        """
        semantic_colors = ("#1e6bde", "#1a5bc4", "#3b82f6", "#f59e0b",
                           "#22c55e", "#ef4444", "#f87171", "#4caf50")
        for child in root.findChildren(QWidget):
            ss = child.styleSheet()
            if not ss:
                continue
            if preserve_semantic and any(c in ss.lower() for c in semantic_colors):
                continue
            # 清除背景/文字/边框相关属性，保留布局相关
            child.setStyleSheet("")

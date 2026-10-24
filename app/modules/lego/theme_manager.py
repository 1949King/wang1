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

V4.43.0 升级：
- 颜色 token 从内联 dict 改为单一真相源 app.core.theme_tokens.DARK_TOKENS / LIGHT_TOKENS
- 保留所有旧 key 名（bg_main / text_primary / accent 等），无破坏性更新
- 新增 key：brand / brand_light / brand_pale / warning / info / accent_amber / glass_* 等
  → AI-Canvas-tauri (tenney95/AI-Canvas-tauri) base.css 行 12-470 直接搬运
- QSS 新增选择器：#brandBtn / #warningBtn / #infoBtn / #successBtn / #glassPanel / #chip /
  #preferenceCard（借鉴 .sidebar-pref-card 4 开关视觉）
- 项目主蓝 #2f7bff（accent）保留 —— 深度嵌入 modules.py QSS，不随 AI-Canvas 改 indigo
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtCore import QSettings

from app.core.theme_tokens import DARK_TOKENS, LIGHT_TOKENS

logger = logging.getLogger("AI短剧编辑器.theme")


class ThemeManager:
    """
    全局主题管理单例

    使用方式：
        tm = ThemeManager.instance()
        tm.apply_theme("light")  # 应用浅色主题，自动同步所有窗口和模块
    """

    _instance: Optional["ThemeManager"] = None

    # ───── 颜色常量表（V4.43.0 改为从 theme_tokens 派生，单一真相源）─────
    COLORS_DARK = DARK_TOKENS
    COLORS_LIGHT = LIGHT_TOKENS

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
        /* ── 顶栏图标按钮（🔔 通知 / 🎨 主题 / ⚙ 设置）──
           V4.43.6 补：此前只有 #headerBar 而缺 #headerBarIconBtn 样式，
           这三个按钮因此走 Qt 默认样式 —— 在深色底上图标发暗「看不清」。
           统一为透明底 + 亮色前景 + hover 高亮（对齐 .sidebar-btn-v3 手感）。 */
        QPushButton[theme="{theme_name}"]#headerBarIconBtn {{
            background-color: transparent;
            color: {c['text_primary']};
            border: 1px solid transparent;
            border-radius: 6px;
            font-size: 15px;
            padding: 0;
        }}
        QPushButton[theme="{theme_name}"]#headerBarIconBtn:hover {{
            background-color: {c['bg_hover']};
            color: {c['accent']};
            border-color: {c['border_light']};
        }}
        QPushButton[theme="{theme_name}"]#headerBarIconBtn:pressed {{
            background-color: {c['bg_tertiary']};
        }}
        /* ── 通知中心下拉面板（V4.43.12 补全）──
           此前该面板用了 **17 个 objectName 但全局 QSS 一条都没写**：浅色主题下靠
           Qt 默认的「浅底黑字」勉强可读，**深色主题下直接不可用**（用户反馈
           「深色模式下的通知中心，它里面的内容还是显示不完整」）。
           现按主题变量补全：面板/卡片底色、标题与正文的层级、按钮 hover、tab 选中态。 */
        QFrame[theme="{theme_name}"]#notificationCenterPanel {{
            background-color: {c['bg_secondary']};
            border: 1px solid {c['border']};
            border-radius: 12px;
        }}
        QFrame[theme="{theme_name}"]#notifHeader,
        QFrame[theme="{theme_name}"]#notifFilterBar,
        QFrame[theme="{theme_name}"]#notifFooter {{
            background-color: transparent;
            border: none;
        }}
        QLabel[theme="{theme_name}"]#notifHeaderTitle {{
            color: {c['text_primary']};
            font-size: 14px;
            font-weight: 700;
        }}
        QPushButton[theme="{theme_name}"]#notifHeaderBtn,
        QPushButton[theme="{theme_name}"]#notifHeaderCloseBtn,
        QPushButton[theme="{theme_name}"]#notifCardCloseBtn {{
            background-color: transparent;
            color: {c['text_secondary']};
            border: none;
            border-radius: 6px;
        }}
        QPushButton[theme="{theme_name}"]#notifHeaderBtn:hover,
        QPushButton[theme="{theme_name}"]#notifHeaderCloseBtn:hover,
        QPushButton[theme="{theme_name}"]#notifCardCloseBtn:hover {{
            background-color: {c['bg_hover']};
            color: {c['text_primary']};
        }}
        QPushButton[theme="{theme_name}"]#notifFilterTab,
        QPushButton[theme="{theme_name}"]#notifFooterBtn {{
            background-color: {c['bg_tertiary']};
            color: {c['text_secondary']};
            border: 1px solid {c['border_light']};
            border-radius: 6px;
            padding: 2px 10px;
        }}
        QPushButton[theme="{theme_name}"]#notifFilterTab:hover,
        QPushButton[theme="{theme_name}"]#notifFooterBtn:hover {{
            background-color: {c['bg_hover']};
            color: {c['text_primary']};
        }}
        QPushButton[theme="{theme_name}"]#notifFilterTab:checked {{
            background-color: {c['accent']};
            color: {c['text_on_accent']};
            border-color: {c['accent']};
        }}
        QFrame[theme="{theme_name}"]#notifCard {{
            background-color: {c['bg_tertiary']};
            border: 1px solid {c['border_light']};
            border-radius: 8px;
        }}
        QFrame[theme="{theme_name}"]#notifCard:hover {{
            background-color: {c['bg_hover']};
            border-color: {c['border_focus']};
        }}
        QLabel[theme="{theme_name}"]#notifCardTitle {{
            color: {c['text_primary']};
            font-size: 13px;
        }}
        QLabel[theme="{theme_name}"]#notifCardBody {{
            color: {c['text_secondary']};
            font-size: 12px;
        }}
        QLabel[theme="{theme_name}"]#notifCardTime {{
            color: {c['text_muted']};
            font-size: 11px;
        }}
        QLabel[theme="{theme_name}"]#notifEmpty {{
            color: {c['text_muted']};
            font-size: 12px;
        }}
        QScrollArea[theme="{theme_name}"]#notifScroll,
        QScrollArea[theme="{theme_name}"]#notifScroll > QWidget > QWidget {{
            background-color: transparent;
            border: none;
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

        /* ═══════════════════════════════════════════════════════════════════
           V4.43.0 新增 — 借鉴 AI-Canvas-tauri base.css / settings.css 的视觉
           ─────────────────────────────────────────────────────────────────── */

        /* ── 品牌色按钮（紫罗兰）—— #brandBtn 用于玻璃面板内 CTA ── */
        QPushButton[theme="{theme_name}"]#brandBtn {{
            background-color: {c['brand']};
            color: white;
            border: none;
            border-radius: 8px;
            padding: 8px 16px;
            font-weight: 600;
        }}
        QPushButton[theme="{theme_name}"]#brandBtn:hover {{
            background-color: {c['brand_light']};
        }}
        QPushButton[theme="{theme_name}"]#brandBtn:pressed {{
            background-color: {c['brand_pale']};
            color: {c['bg_main']};
        }}

        /* ── 语义按钮变体 ── */
        QPushButton[theme="{theme_name}"]#successBtn {{
            background-color: {c['success']};
            color: white;
            border: none;
            border-radius: 8px;
            padding: 8px 16px;
        }}
        QPushButton[theme="{theme_name}"]#successBtn:hover {{
            background-color: {c['success_light']};
        }}
        QPushButton[theme="{theme_name}"]#dangerBtn2 {{
            background-color: {c['danger']};
            color: white;
            border: none;
            border-radius: 8px;
            padding: 8px 16px;
        }}
        QPushButton[theme="{theme_name}"]#dangerBtn2:hover {{
            background-color: {c['danger_light']};
        }}
        QPushButton[theme="{theme_name}"]#warningBtn {{
            background-color: {c['warning']};
            color: white;
            border: none;
            border-radius: 8px;
            padding: 8px 16px;
        }}
        QPushButton[theme="{theme_name}"]#infoBtn {{
            background-color: {c['info']};
            color: white;
            border: none;
            border-radius: 8px;
            padding: 8px 16px;
        }}
        QPushButton[theme="{theme_name}"]#amberBtn {{
            background-color: {c['accent_amber']};
            color: {c['bg_main']};
            border: none;
            border-radius: 8px;
            padding: 8px 16px;
            font-weight: 600;
        }}

        /* ── 玻璃面板 #glassPanel —— 借鉴 AI-Canvas --glass-bg + --glass-ring ── */
        QFrame[theme="{theme_name}"]#glassPanel {{
            background-color: {c['glass_bg']};
            border: 1px solid {c['glass_ring']};
            border-radius: 14px;
        }}
        QFrame[theme="{theme_name}"]#glassPanelSoft {{
            background-color: {c['glass_bg_light']};
            border: 1px solid {c['glass_ring']};
            border-radius: 12px;
        }}

        /* ── Chip / Badge —— AI-Canvas 厂商徽标 + 工作流 chip ── */
        QLabel[theme="{theme_name}"]#chip {{
            background-color: {c['brand_alpha_15']};
            color: {c['brand_light']};
            border-radius: 8px;
            padding: 2px 8px;
            font-size: 11px;
            font-weight: 600;
        }}
        QLabel[theme="{theme_name}"]#chipSuccess {{
            background-color: {c['success_bg']};
            color: {c['success_text']};
            border-radius: 8px;
            padding: 2px 8px;
            font-size: 11px;
            font-weight: 600;
        }}
        QLabel[theme="{theme_name}"]#chipWarning {{
            background-color: {c['warning_bg']};
            color: {c['warning']};
            border-radius: 8px;
            padding: 2px 8px;
            font-size: 11px;
            font-weight: 600;
        }}
        QLabel[theme="{theme_name}"]#chipDanger {{
            background-color: {c['danger_bg']};
            color: {c['danger_light']};
            border-radius: 8px;
            padding: 2px 8px;
            font-size: 11px;
            font-weight: 600;
        }}
        QLabel[theme="{theme_name}"]#chipInfo {{
            background-color: {c['info_bg']};
            color: {c['info_light']};
            border-radius: 8px;
            padding: 2px 8px;
            font-size: 11px;
            font-weight: 600;
        }}
        QLabel[theme="{theme_name}"]#chipAmber {{
            background-color: {c['accent_amber_bg']};
            color: {c['accent_amber_text']};
            border-radius: 8px;
            padding: 2px 8px;
            font-size: 11px;
            font-weight: 600;
        }}
        QLabel[theme="{theme_name}"]#chipMuted {{
            background-color: {c['bg_hover']};
            color: {c['text_secondary']};
            border-radius: 8px;
            padding: 2px 8px;
            font-size: 11px;
            font-weight: 500;
        }}

        /* ── 偏好卡 —— 借鉴 AI-Canvas .sidebar-pref-card（4 开关视觉）── */
        QFrame[theme="{theme_name}"]#preferenceCard {{
            background-color: {c['bg_tertiary']};
            border: 1px solid {c['border']};
            border-radius: 12px;
        }}
        QFrame[theme="{theme_name}"]#preferenceCard:hover {{
            border-color: {c['border_focus']};
        }}

        /* ── 浮层 / 卡片（subpanel）── */
        QFrame[theme="{theme_name}"]#subpanelCard {{
            background-color: {c['card_bg']};
            border: 1px solid {c['card_border']};
            border-radius: 12px;
        }}

        /* ── 浮动 Header / Titlebar —— AI-Canvas .app-header (top-2 + backdrop-blur) ── */
        QFrame[theme="{theme_name}"]#floatingHeader {{
            background-color: {c['glass_panel_bg']};
            border: 1px solid {c['glass_ring']};
            border-radius: 14px;
        }}

        /* ── 侧边栏悬浮样式 —— 借鉴 .sidebar-floating ── */
        QFrame[theme="{theme_name}"]#floatingSidebar {{
            background-color: {c['glass_panel_bg']};
            border: 1px solid {c['glass_ring']};
            border-radius: 14px;
        }}
        QFrame[theme="{theme_name}"]#floatingSidebarCollapsed {{
            background-color: {c['glass_bg']};
            border: 1px solid {c['glass_ring']};
            border-radius: 14px;
        }}

        /* ── 工具按钮（圆形图标按钮，参考 .sidebar-btn-v3 36×36）── */
        QPushButton[theme="{theme_name}"]#toolBtn {{
            background-color: transparent;
            color: {c['text_secondary']};
            border: 1px solid transparent;
            border-radius: 8px;
            min-width: 36px;
            min-height: 36px;
            max-width: 36px;
            max-height: 36px;
            font-size: 16px;
            padding: 0;
        }}
        QPushButton[theme="{theme_name}"]#toolBtn:hover {{
            background-color: {c['bg_hover']};
            color: {c['text_primary']};
            border-color: {c['border_focus']};
        }}
        QPushButton[theme="{theme_name}"]#toolBtn:checked,
        QPushButton[theme="{theme_name}"]#toolBtnActive {{
            background-color: {c['brand_alpha_15']};
            color: {c['brand_light']};
            border-color: {c['brand']};
        }}

        /* ── 分隔线（separator）── */
        QFrame[theme="{theme_name}"]#separatorH {{
            background-color: {c['separator_color']};
            max-height: 1px;
            min-height: 1px;
            border: none;
        }}
        QFrame[theme="{theme_name}"]#separatorV {{
            background-color: {c['separator_color']};
            max-width: 1px;
            min-width: 1px;
            border: none;
        }}

        /* ═══════════════════════════════════════════════════════════════════
           V4.43.1 新增 — 设置面板（对齐 AI Canvas 外观/常规页截图）
           ─────────────────────────────────────────────────────────────────── */

        /* ── 设置导航（左 184px）── */
        QLabel[theme="{theme_name}"]#settingsNavHeader {{
            background-color: {c['bg_secondary']};
            color: {c['text_primary']};
            font-size: 15px;
            font-weight: 700;
            padding-left: 20px;
            border-bottom: 1px solid {c['border_light']};
        }}
        QWidget[theme="{theme_name}"]#settingsNavHolder {{
            background-color: {c['bg_secondary']};
            border-right: 1px solid {c['border_light']};
        }}
        QListWidget[theme="{theme_name}"]#settingsNav {{
            background-color: {c['bg_secondary']};
            border: none;
            outline: none;
            padding: 10px 8px;
        }}
        QListWidget[theme="{theme_name}"]#settingsNav::item {{
            color: {c['text_secondary']};
            border-radius: 8px;
            padding: 8px 12px;
        }}
        QListWidget[theme="{theme_name}"]#settingsNav::item:selected {{
            background-color: {c['brand_alpha_15']};
            color: {c['brand_light']};
            font-weight: 600;
        }}
        QListWidget[theme="{theme_name}"]#settingsNav::item:hover:!selected {{
            background-color: {c['bg_hover']};
        }}
        QWidget[theme="{theme_name}"]#settingsStack {{
            background-color: {c['bg_main']};
        }}
        QScrollArea[theme="{theme_name}"]#settingsContent {{
            background-color: {c['bg_main']};
            border: none;
        }}
        QScrollArea[theme="{theme_name}"]#settingsContent > QWidget > QWidget {{
            background-color: {c['bg_main']};
        }}
        QWidget[theme="{theme_name}"]#settingsPage {{
            background-color: {c['bg_main']};
        }}

        /* ── 标题 / 提示 / 分组 ── */
        QLabel[theme="{theme_name}"]#settingsBigTitle {{
            color: {c['text_primary']};
            font-size: 20px;
            font-weight: 700;
        }}
        QLabel[theme="{theme_name}"]#settingsPageHint {{
            color: {c['text_muted']};
            font-size: 12px;
        }}
        QLabel[theme="{theme_name}"]#sectionTitle {{
            color: {c['text_primary']};
            font-size: 13px;
            font-weight: 600;
        }}
        QLabel[theme="{theme_name}"]#sectionHint {{
            color: {c['text_muted']};
            font-size: 11px;
        }}
        QLabel[theme="{theme_name}"]#settingsFootnote {{
            color: {c['text_muted']};
            font-size: 11px;
            line-height: 1.5;
        }}
        QLabel[theme="{theme_name}"]#appearanceHeadIcon {{
            font-size: 20px;
        }}
        QLabel[theme="{theme_name}"]#autoSaveBadge {{
            color: {c['success_text']};
            background-color: {c['success_bg']};
            border-radius: 10px;
            padding: 3px 10px;
            font-size: 11px;
            font-weight: 600;
        }}

        /* ── 分段控件（节点工具栏 / 主题模式）── */
        QFrame[theme="{theme_name}"]#segmentedBar {{
            background-color: {c['card_bg']};
            border: 1px solid {c['card_border']};
            border-radius: 10px;
        }}
        QPushButton[theme="{theme_name}"]#segmentedBtn {{
            color: {c['text_secondary']};
            background-color: transparent;
            border: none;
            border-radius: 7px;
            padding: 8px 12px;
            font-size: 12px;
            font-weight: 500;
        }}
        QPushButton[theme="{theme_name}"]#segmentedBtn:hover {{
            background-color: {c['bg_hover']};
            color: {c['text_primary']};
        }}
        QPushButton[theme="{theme_name}"]#segmentedBtn:checked {{
            background-color: {c['brand_alpha_15']};
            color: {c['brand_light']};
            font-weight: 600;
        }}

        /* ── 偏好卡（.sidebar-pref-card）── */
        QFrame[theme="{theme_name}"]#prefCard {{
            background-color: {c['card_bg']};
            border: 1px solid {c['card_border']};
            border-radius: 10px;
        }}
        QFrame[theme="{theme_name}"]#prefCard:hover {{
            background-color: {c['bg_hover']};
        }}
        QFrame[theme="{theme_name}"]#prefCard[prefActive="true"] {{
            border-color: {c['brand_alpha_30']};
        }}
        QLabel[theme="{theme_name}"]#prefTitle {{
            color: {c['text_primary']};
            font-size: 13px;
            font-weight: 500;
        }}
        QLabel[theme="{theme_name}"]#prefDesc {{
            color: {c['text_muted']};
            font-size: 11px;
        }}

        /* ── 外观预设卡（2×2）── */
        QFrame[theme="{theme_name}"]#presetCard {{
            background-color: {c['card_bg']};
            border: 1px solid {c['card_border']};
            border-radius: 12px;
        }}
        QFrame[theme="{theme_name}"]#presetCard:hover {{
            border-color: {c['border_focus']};
        }}
        QFrame[theme="{theme_name}"]#presetCard[presetActive="true"] {{
            border: 2px solid {c['brand']};
            background-color: {c['brand_alpha_10']};
        }}
        QLabel[theme="{theme_name}"]#presetName {{
            color: {c['text_primary']};
            font-size: 12px;
            font-weight: 600;
        }}
        QLabel[theme="{theme_name}"]#presetDot {{
            font-size: 10px;
        }}
        QLabel[theme="{theme_name}"]#chipBrand {{
            background-color: {c['brand_alpha_15']};
            color: {c['brand_light']};
            border-radius: 10px;
            padding: 3px 10px;
            font-size: 11px;
            font-weight: 600;
        }}

        /* ── 外观大预览容器 ── */
        QFrame[theme="{theme_name}"]#appearancePreview {{
            background-color: {c['card_bg']};
            border: 1px solid {c['card_border']};
            border-radius: 14px;
        }}

        /* ── 工具按钮（导入 / 导出 / 保存预设 / 覆盖）── */
        QPushButton[theme="{theme_name}"]#ghostBtn {{
            color: {c['text_primary']};
            background-color: {c['bg_tertiary']};
            border: 1px solid {c['border']};
            border-radius: 8px;
            padding: 6px 14px;
            font-size: 12px;
        }}
        QPushButton[theme="{theme_name}"]#ghostBtn:hover {{
            background-color: {c['bg_hover']};
            border-color: {c['border_focus']};
        }}
        QPushButton[theme="{theme_name}"]#overrideBtn {{
            color: {c['text_disabled']};
            background-color: transparent;
            border: 1px solid {c['border_light']};
            border-radius: 8px;
            padding: 6px 14px;
            font-size: 12px;
        }}
        QPushButton[theme="{theme_name}"]#overrideBtn:disabled {{
            color: {c['text_disabled']};
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
        """给 widget 及其所有子控件设置 theme 属性，并 repolish 让属性选择器重新求值。

        ⚠️ V4.43.7 修正（重要）：
        此前本方法**只 setProperty、不 repolish**，注释写「不使用 unpolish/polish
        （性能差），依靠 setStyleSheet 全局刷新自动生效」—— **这个假设是错的**。
        Qt 中动态属性变化后，`QSS[theme="x"]` 属性选择器**不会**自动重新匹配，
        必须 unpolish + polish。实测（offscreen，QPushButton + [theme] 选择器）：

            初始 dark          → 背景 #000000
            只 setProperty     → 背景仍 #000000（期望 #ffffff，**没变**）
            unpolish+polish 后 → 背景 #ffffff（正确）

        ⇒ 这正是用户反馈「点了主题、界面不跟着切 / 再点切不回来」的根因：
          `_do_apply_theme` 先 `app.setStyleSheet(qss)`、后 `_apply_theme_property`，
          属性改动落在样式表重算之后，于是界面停留在旧主题。
        """
        def _repolish(w: QWidget) -> None:
            if w.property("theme") == theme:
                return  # 属性没变，省一次 repolish
            w.setProperty("theme", theme)
            st = w.style()
            if st is not None:
                st.unpolish(w)
                st.polish(w)

        _repolish(widget)
        for child in widget.findChildren(QWidget):
            _repolish(child)

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

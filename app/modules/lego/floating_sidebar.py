"""
浮动侧边栏 (FloatingSidebar)
================================

对标 AI-Canvas-tauri (tenney95/AI-Canvas-tauri) Sidebar.tsx 行 660-787
- 36×36 圆形工具按钮列
- 顶部 logo + 5 模块入口 + 分隔线 + 用户齿轮
- 停靠 / 半隐两种模式 (`left:12px` 停靠 / `left:-26px` 半隐)

设计纪律：
- 只暴露**信号**，业务跳转交给 main_window 接收
- 主题跟随主程序（属性选择器）
- 玻璃面板视觉（V4.43.0 新增的 #floatingSidebar + glass_bg token）
- 用户齿轮菜单三个子项：设置 / 帮助 / 关于（参考 Sidebar.tsx AvatarMenu 行 297-417）

V4.43.0 任务 #282
"""
from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve, QPoint
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QPushButton, QWidget,
    QGraphicsDropShadowEffect, QMenu, QSizePolicy,
)

from app.modules.lego.theme_manager import ThemeManager
from app.core.theme_tokens import MOTION_TOKENS

logger = logging.getLogger("AI短剧编辑器.floating_sidebar")


# ═══════════════════════════════════════════════════════════════
# 模块入口配置（单源真相）
# ═══════════════════════════════════════════════════════════════
# 顺序：logo(顶) → 5 模块按钮 → 分隔线 → 用户齿轮(底)
# 修改这里即可调整侧边栏布局

NAV_ITEMS = [
    ("home",       "🏠", "首页"),
    ("editor",     "🎬", "剪辑"),
    ("characters", "🎨", "画布"),
    ("copywriting","📝", "AI脚本"),
    ("materials",  "📁", "素材管理"),
    ("extensions", "🧩", "拓展中心"),
]

AVATAR_MENU_ITEMS = [
    ("settings", "⚙", "设置"),
    ("help",     "❓", "帮助"),
    ("about",    "ℹ", "关于"),
]


class FloatingSidebar(QFrame):
    """悬浮侧边栏（玻璃面板视觉）

    信号：
        navigate_to(str)        — 跳转到指定 module_id
        open_settings()         — 打开设置面板
        open_help()             — 打开帮助中心
        open_about()            — 打开关于对话框
        floating_changed(bool)  — 悬浮模式切换
    """

    navigate_to = Signal(str)
    open_settings = Signal()
    open_help = Signal()
    open_about = Signal()
    floating_changed = Signal(bool)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._is_floating = True      # True=停靠, False=半隐
        self._current_module: Optional[str] = None
        self._nav_buttons: dict[str, QPushButton] = {}
        self._avatar_menu: Optional[QMenu] = None

        self.setObjectName("floatingSidebar")
        self.setFixedWidth(48)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        # 阴影（毛玻璃感）
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 4)
        shadow.setColor(Qt.GlobalColor.black)
        self.setGraphicsEffect(shadow)

        self._build_ui()

        # 默认停靠
        self._apply_floating_mode(animate=False)

    # ─────────── UI 构建 ───────────
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 12, 6, 12)
        layout.setSpacing(4)

        # 顶部 logo 区（占位，避免首项太贴顶）
        logo_btn = QPushButton("✨")
        logo_btn.setObjectName("toolBtn")
        logo_btn.setToolTip("拾光剪影")
        logo_btn.setEnabled(False)  # logo 不响应点击
        layout.addWidget(logo_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(8)

        # 5 个模块按钮
        for module_id, icon, tooltip in NAV_ITEMS:
            btn = self._create_nav_button(module_id, icon, tooltip)
            self._nav_buttons[module_id] = btn
            layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignCenter)

        # 弹性占位 + 分隔线 + 用户齿轮
        layout.addStretch(1)
        self._add_separator(layout)

        self._avatar_btn = self._create_avatar_button()
        layout.addWidget(self._avatar_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        # 主题感知
        self.setProperty("theme", ThemeManager.instance().current_theme)

    def _create_nav_button(self, module_id: str, icon: str, tooltip: str) -> QPushButton:
        btn = QPushButton(icon)
        btn.setObjectName("toolBtn")
        btn.setToolTip(tooltip)
        btn.setCheckable(True)
        btn.clicked.connect(lambda _checked, mid=module_id: self._on_nav_clicked(mid))
        return btn

    def _create_avatar_button(self) -> QPushButton:
        btn = QPushButton("👤")
        btn.setObjectName("toolBtn")
        btn.setToolTip("用户中心")
        btn.clicked.connect(self._on_avatar_clicked)
        return btn

    def _add_separator(self, layout: QVBoxLayout) -> None:
        sep = QFrame()
        sep.setObjectName("separatorV")
        sep.setFixedHeight(24)
        layout.addWidget(sep, alignment=Qt.AlignmentFlag.AlignCenter)

    # ─────────── 导航交互 ───────────
    def _on_nav_clicked(self, module_id: str) -> None:
        """单击导航按钮 — 同步选中态 + 发信号"""
        for mid, btn in self._nav_buttons.items():
            btn.setChecked(mid == module_id)
        self._current_module = module_id
        logger.debug("侧边栏导航 → %s", module_id)
        self.navigate_to.emit(module_id)

    def _on_avatar_clicked(self) -> None:
        """用户齿轮 — 弹菜单（设置/帮助/关于）"""
        if self._avatar_menu is None:
            self._avatar_menu = self._build_avatar_menu()
        # 菜单出现在按钮下方
        self._avatar_menu.exec(self._avatar_btn.mapToGlobal(
            QPoint(0, self._avatar_btn.height())
        ))

    def _build_avatar_menu(self) -> QMenu:
        menu = QMenu(self)
        theme_name = ThemeManager.instance().current_theme
        menu.setProperty("theme", theme_name)
        for action_id, icon, label in AVATAR_MENU_ITEMS:
            act = menu.addAction(f"{icon}  {label}")
            if action_id == "settings":
                act.triggered.connect(self.open_settings.emit)
            elif action_id == "help":
                act.triggered.connect(self.open_help.emit)
            elif action_id == "about":
                act.triggered.connect(self.open_about.emit)
        return menu

    # ─────────── 悬浮模式 ───────────
    def set_floating(self, floating: bool) -> None:
        """外部调用：切换停靠 / 半隐模式"""
        if floating == self._is_floating:
            return
        self._is_floating = floating
        self._apply_floating_mode(animate=True)
        self.floating_changed.emit(floating)

    def _apply_floating_mode(self, animate: bool = True) -> None:
        """应用到实际位置。停靠时贴在父容器左 12px，半隐时挪到父容器左 -26px"""
        if self.parent() is None:
            return
        target_x = 12 if self._is_floating else -26
        if animate:
            # parent=self 防止动画启动后被 Python GC 回收(无 parent 的
            # QPropertyAnimation 在 start() 后即可能被回收 → 动画夭折)
            anim = QPropertyAnimation(self, b"pos", self)
            anim.setDuration(int(MOTION_TOKENS["dur_slow"]))  # 300ms
            # PySide6 没有 cubic-bezier 直传，用 OutExpo 近似 ease-out-expo
            anim.setEasingCurve(QEasingCurve.Type.OutExpo)
            anim.setStartValue(self.pos())
            anim.setEndValue(QPoint(target_x, self.y()))
            anim.start()
        else:
            self.move(target_x, self.y())

    # ─────────── 外部 API ───────────
    def set_active_module(self, module_id: str) -> None:
        """从外部同步当前选中模块（main_window 切模块时调用）"""
        for mid, btn in self._nav_buttons.items():
            btn.setChecked(mid == module_id)
        self._current_module = module_id

    def set_theme(self, theme: str) -> None:
        """主题切换（被 ThemeManager 统一调用）"""
        self.setProperty("theme", theme)
        # 子控件级联
        for child in self.findChildren(QWidget):
            child.setProperty("theme", theme)
        if self._avatar_menu is not None:
            self._avatar_menu.setProperty("theme", theme)

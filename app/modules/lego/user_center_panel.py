"""
用户中心面板 (UserCenterPanel)
==============================

对标 Trae IDE 设计：单一下拉面板，6 段式布局，挂在 main_window 顶部
headerBar 右侧的头像按钮下方弹出。

设计原则（V4.42.0 起）：
- 完全复用既有 AuthService / ThemeManager / UpdateManager，不重写业务
- 仅做 UI 编排；点击动作通过 Signal 让 main_window 接管实际导航
- 主题跟随主程序（属性选择器），关闭时由 main_window 控制生命周期
- 自动关闭：点击面板外 / focusOut / ESC

面板六段：
    [1] 头部 · 身份      头像 / 昵称 / VIP/普通徽章 / 升级权益
    [2] 通知中心 · 入口  未读徽章 + 检查更新 + 一键反馈
    [3] 设置入口         直接跳到 settings 模块（按用户要求置顶）
    [4] 主题 · 帮助 · 反馈
    [5] 退出登录         置底降级（仅登录态可见）

落点约束（2026-10-11 用户二轮反馈）：
- 这是 PySide6 主程序顶 navbar 改造的一部分，**非画布模块**
- 零冻结区触碰，零 CANVASDUAL 影响
"""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import Qt, Signal, QPoint, QEvent
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QCursor, QFontMetrics
)
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget,
    QApplication, QSizePolicy, QGraphicsDropShadowEffect
)

logger = logging.getLogger("AI短剧编辑器.user_center")


class _AvatarBadge(QLabel):
    """首字母圆形头像占位（无图网络依赖）"""

    def __init__(self, nickname: str = "?", size: int = 56, parent=None):
        super().__init__(parent)
        self._nickname = nickname or "?"
        self._size = size
        self.setFixedSize(size, size)

    def set_nickname(self, nickname: str):
        self._nickname = nickname or "?"
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        # 渐变背景（深色 / 浅色都可见的蓝紫色环）
        grad = QColor("#2f7bff")
        painter.setBrush(QBrush(grad))
        pen = QPen(QColor("#ffffff"))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawEllipse(rect.adjusted(1, 1, -1, -1))
        # 首字母
        ch = (self._nickname or "?")[0].upper()
        font = QFont("Microsoft YaHei UI", int(self._size * 0.42), QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, ch)


class _MenuRow(QPushButton):
    """菜单行：左侧 emoji + 标题，右侧副标识/箭头"""

    def __init__(self, emoji: str, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("userCenterRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(36)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setText(f"{emoji}  {title}")
        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)


class _Badge(QLabel):
    """未读徽章（小红点+数字）"""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setObjectName("userCenterBadge")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedHeight(18)
        if text:
            fm = QFontMetrics(self.font())
            w = max(18, fm.horizontalAdvance(text) + 12)
        else:
            w = 18
        self.setFixedWidth(w)


class UserCenterPanel(QFrame):
    """Trae IDE 风格用户中心下拉面板"""

    # ─────────── 业务信号 ───────────
    login_requested = Signal()
    register_requested = Signal()
    activate_requested = Signal()
    upgrade_requested = Signal()
    notifications_requested = Signal()
    check_update_requested = Signal()
    settings_requested = Signal()
    theme_requested = Signal()
    help_requested = Signal()
    feedback_requested = Signal()
    logout_requested = Signal()
    auth_state_changed = Signal(bool)  # True=已登录

    PANEL_WIDTH = 320

    def __init__(
        self,
        auth_service,
        theme_manager,
        update_manager,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._auth = auth_service
        self._tm = theme_manager
        self._um = update_manager

        # Popup 类型：无边框、不抢焦点、可被外部点击关闭
        self.setWindowFlags(
            Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setObjectName("userCenterPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setFixedWidth(self.PANEL_WIDTH)

        self._build_ui()
        self._apply_theme()
        self.refresh_state()

        # 事件过滤：点击面板外关闭
        if QApplication.instance() is not None:
            QApplication.instance().installEventFilter(self)

    # ─────────── UI 构造 ───────────
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 10, 8, 10)
        outer.setSpacing(6)

        # 阴影（仅在最外层）
        try:
            shadow = QGraphicsDropShadowEffect(self)
            shadow.setBlurRadius(20)
            shadow.setOffset(0, 4)
            shadow.setColor(QColor(0, 0, 0, 60))
            self.setGraphicsEffect(shadow)
        except Exception as e:  # 不可用就降级无阴影
            logger.debug("设置阴影失败，降级: %s", e)

        outer.addWidget(self._build_header())     # [1] 头部 · 身份
        outer.addWidget(self._build_divider())
        outer.addWidget(self._build_notifications())  # [2] 通知中心
        outer.addWidget(self._build_divider())
        outer.addLayout(self._build_action_list())  # [3][4] 设置/主题/帮助/反馈
        outer.addWidget(self._build_divider())
        outer.addWidget(self._build_logout())       # [5] 退出登录

    def _build_header(self) -> QWidget:
        box = QFrame(self)
        box.setObjectName("userCenterHeader")
        layout = QHBoxLayout(box)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(12)

        self._avatar = _AvatarBadge("?", size=52, parent=box)
        layout.addWidget(self._avatar)

        info = QVBoxLayout()
        info.setSpacing(2)

        self._nickname_label = QLabel("未登录", box)
        self._nickname_label.setObjectName("userCenterNickname")
        info.addWidget(self._nickname_label)

        self._status_label = QLabel("点击登录以解锁全部功能", box)
        self._status_label.setObjectName("userCenterStatus")
        self._status_label.setWordWrap(True)
        info.addWidget(self._status_label)

        layout.addLayout(info, 1)

        # 右侧登录/激活快捷按钮（仅未登录显示）
        self._header_login_btn = QPushButton("登录", box)
        self._header_login_btn.setObjectName("userCenterHeaderBtn")
        self._header_login_btn.setFixedHeight(28)
        self._header_login_btn.setFixedWidth(56)
        self._header_login_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header_login_btn.clicked.connect(self.login_requested.emit)
        layout.addWidget(self._header_login_btn)

        return box

    def _build_notifications(self) -> QWidget:
        box = QFrame(self)
        box.setObjectName("userCenterNotifications")
        layout = QHBoxLayout(box)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(8)

        notif_btn = _MenuRow("🔔", "通知中心", box)
        notif_btn.clicked.connect(self.notifications_requested.emit)
        layout.addWidget(notif_btn, 1)

        self._unread_badge = _Badge("", box)
        self._unread_badge.hide()
        layout.addWidget(self._unread_badge)

        update_btn = QPushButton("检查更新", box)
        update_btn.setObjectName("userCenterInlineBtn")
        update_btn.setFixedHeight(26)
        update_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        update_btn.clicked.connect(self.check_update_requested.emit)
        layout.addWidget(update_btn)

        return box

    def _build_action_list(self) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        rows = [
            ("⚙", "设置",       self.settings_requested),
            ("🎨", "切换主题",   self.theme_requested),
            ("❓", "帮助文档",   self.help_requested),
            ("💬", "意见反馈",   self.feedback_requested),
        ]
        for emoji, title, sig in rows:
            row = _MenuRow(emoji, title, self)
            row.clicked.connect(sig.emit)
            layout.addWidget(row)

        # VIP 用户额外一行：升级权益（仅普通用户有意义，但条件改由 refresh_state 控制显隐）
        self._upgrade_row = _MenuRow("👑", "升级 VIP 权益", self)
        self._upgrade_row.clicked.connect(self.upgrade_requested.emit)
        self._upgrade_row.hide()
        layout.addWidget(self._upgrade_row)

        return layout

    def _build_logout(self) -> QWidget:
        self._logout_row = _MenuRow("🚪", "退出登录", self)
        self._logout_row.setObjectName("userCenterLogout")
        self._logout_row.clicked.connect(self._on_logout_clicked)
        self._logout_row.hide()
        return self._logout_row

    def _build_divider(self) -> QFrame:
        div = QFrame(self)
        div.setObjectName("userCenterDivider")
        div.setFixedHeight(1)
        return div

    # ─────────── 状态刷新 ───────────
    def refresh_state(self):
        """根据 AuthService / UpdateManager 当前态刷新显示"""
        logged_in = bool(self._auth and self._auth.is_logged_in)
        if logged_in:
            user = self._auth.current_user
            nickname = (user.nickname if user else "") or (user.email if user else "") or "用户"
            self._avatar.set_nickname(nickname)
            self._nickname_label.setText(nickname)
            if getattr(user, "is_vip", False) and user.vip_expire > 0:
                from datetime import datetime as _dt
                expire = _dt.utcfromtimestamp(user.vip_expire).strftime("%Y-%m-%d")
                self._status_label.setText(f"VIP · 到期 {expire}")
            elif getattr(user, "is_vip", False):
                self._status_label.setText("VIP · 永久")
            else:
                self._status_label.setText("普通用户 · 升级解锁全部算力")
            self._header_login_btn.hide()
            self._upgrade_row.setVisible(not getattr(user, "is_vip", False))
            self._logout_row.show()
        else:
            self._avatar.set_nickname("?")
            self._nickname_label.setText("未登录")
            self._status_label.setText("登录后开启云端能力、积分商城、设备同步")
            self._header_login_btn.show()
            self._upgrade_row.hide()
            self._logout_row.hide()

        self._refresh_update_hint()
        self.auth_state_changed.emit(logged_in)

    def _refresh_update_hint(self):
        """从 notification_store 拉取未读数，更新右上角徽章（V4.42.1 起取代 update_manager）"""
        try:
            from app.core.notification_store import notification_store
            count = notification_store().unread_count()
        except Exception as e:
            logger.debug("读取未读通知数失败: %s", e)
            count = 0
        if count > 0:
            self._unread_badge.setText(str(count) if count < 100 else "99+")
            self._unread_badge.show()
        else:
            self._unread_badge.hide()

    def refresh_unread_badge(self):
        """公开方法：让 main_window 在通知中心变更后主动拉一次徽章"""
        self._refresh_update_hint()

    # ─────────── 主题 ───────────
    def _apply_theme(self):
        theme = "dark"
        try:
            if self._tm and hasattr(self._tm, "get_current_theme"):
                theme = self._tm.get_current_theme() or "dark"
        except Exception as e:
            logger.debug("读取当前主题失败，默认 dark: %s", e)
        self.setProperty("theme", theme)
        self.style().unpolish(self)
        self.style().polish(self)

    def on_theme_changed(self, _theme_name: str = ""):
        self._apply_theme()

    # ─────────── 弹出 / 关闭 ───────────
    def popup_below(self, anchor: QWidget):
        """挂在 anchor（一般是头像按钮）正下方，右对齐"""
        if anchor is None:
            return
        # 计算位置
        anchor_rect = anchor.rect()
        global_pos = anchor.mapToGlobal(QPoint(0, 0))
        x = global_pos.x() + anchor_rect.width() - self.PANEL_WIDTH
        y = global_pos.y() + anchor_rect.height() + 4
        # 防止超出屏幕下方
        screen = anchor.screen()
        if screen is not None:
            screen_bottom = screen.availableGeometry().bottom()
            if y + 360 > screen_bottom:
                # 改为向上弹出
                anchor_top = anchor.mapToGlobal(QPoint(0, 0)).y()
                y = max(40, anchor_top - 360 - 4)
        self.move(x, y)
        self.show()
        self.raise_()
        self.setFocus()

    def hide_panel(self):
        self.hide()

    # ─────────── 事件 ───────────
    def eventFilter(self, obj, event):
        """点击面板外关闭"""
        if event.type() == QEvent.Type.MouseButtonPress:
            if self.isVisible():
                pos = QCursor.pos()
                if not self.geometry().contains(pos):
                    self.hide()
        elif event.type() == QEvent.Type.WindowActivate and self.isVisible():
            # 当其他窗口被激活时，自动隐藏
            other = obj if hasattr(obj, "window") else None
            if other is not None and other.window() is not self:
                self.hide()
        return super().eventFilter(obj, event)

    def focusOutEvent(self, event):
        # 焦点离开时关闭，但允许父控件事件继续
        super().focusOutEvent(event)
        # 延迟隐藏，避免与点击事件竞争
        QApplication.instance().postEvent(self, QEvent(QEvent.Type.Hide))

    def customEvent(self, event):
        if event.type() == QEvent.Type.Hide:
            self.hide()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(event)

    # ─────────── 信号槽 ───────────
    def _on_logout_clicked(self):
        """退出登录：先调 AuthService，再发信号"""
        try:
            if self._auth and hasattr(self._auth, "logout"):
                self._auth.logout()
        except Exception as e:
            logger.error("退出登录失败: %s", e)
        self.logout_requested.emit()
        self.refresh_state()
        self.hide()


__all__ = ["UserCenterPanel"]
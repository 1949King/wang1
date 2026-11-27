"""
通知中心面板 (NotificationCenterPanel)
======================================

对标 Trae IDE / VSCode 通知中心设计：弹出于 headerBar 🔔 通知按钮下方，
展示系统消息 / 版本更新 / 反馈提交 / 告警四类应用内通知。

数据源：app.core.notification_store（单例 + JSON 持久化）
落点：PySide6 主程序顶 navbar（V4.42.1 起，非画布模块）

布局：
    [1] 头部 · 标题 + 全部已读 + 关闭
    [2] 过滤标签 · 全部 / 系统 / 更新 / 反馈 / 告警
    [3] 列表 · 滚动卡片（每条:级别图标 + 标题 + 正文 + 时间 + 删除）
    [4] 空状态 · 没消息时显示
    [5] 底部 · 清空全部 + 检查更新 + 反馈入口

设计纪律：
- 只读 NotificationStore，不持有任何业务状态
- 标记已读 / 删除走信号回 main_window，不直接调业务模块
- 主题跟随主程序（属性选择器）
- 自动关闭：点击外部 / focusOut / ESC
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt, Signal, QPoint, QEvent
from PySide6.QtGui import QCursor, QColor
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget,
    QApplication, QButtonGroup, QScrollArea, QGraphicsDropShadowEffect,
)

from app.core.notification_store import (
    Notification, NotificationStore,
    TYPE_SYSTEM, TYPE_UPDATE, TYPE_FEEDBACK, TYPE_ALERT, TYPE_INFO,
    LEVEL_INFO, LEVEL_SUCCESS, LEVEL_WARNING, LEVEL_ERROR,
)

logger = logging.getLogger("AI短剧编辑器.notification_center")


# ─────────── 类别 UI 映射 ───────────
_TYPE_META = {
    TYPE_SYSTEM:   ("🛠", "系统",   "#2f7bff"),
    TYPE_UPDATE:   ("🚀", "更新",   "#8b5cf6"),
    TYPE_FEEDBACK: ("💬", "反馈",   "#f97316"),
    TYPE_ALERT:    ("⚠", "告警",   "#fb7185"),
    TYPE_INFO:     ("ℹ", "信息",   "#64748b"),
}

_LEVEL_META = {
    LEVEL_INFO:    ("ℹ", "#3b82f6"),
    LEVEL_SUCCESS: ("✓", "#10b981"),
    LEVEL_WARNING: ("⚠", "#f59e0b"),
    LEVEL_ERROR:   ("✕", "#ef4444"),
}

_FILTER_LABELS = [
    ("all",      "全部", None),
    (TYPE_SYSTEM,   "系统",   _TYPE_META[TYPE_SYSTEM]),
    (TYPE_UPDATE,   "更新",   _TYPE_META[TYPE_UPDATE]),
    (TYPE_FEEDBACK, "反馈",   _TYPE_META[TYPE_FEEDBACK]),
    (TYPE_ALERT,    "告警",   _TYPE_META[TYPE_ALERT]),
]


def _format_time(ts: float) -> str:
    """把时间戳格式化成'刚刚 / N 分钟前 / HH:MM / MM-DD' 四档"""
    if not ts:
        return ""
    now = datetime.now().timestamp()
    diff = max(0, now - ts)
    if diff < 60:
        return "刚刚"
    if diff < 3600:
        return f"{int(diff // 60)} 分钟前"
    if diff < 86400:
        return datetime.fromtimestamp(ts).strftime("%H:%M")
    if diff < 86400 * 7:
        return datetime.fromtimestamp(ts).strftime("%a %H:%M")
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


# ─────────── 内部组件：单条通知卡片 ───────────
class _NotificationCard(QFrame):
    """单条通知：级别图标 + 标题 + 正文 + 时间 + 删除按钮"""

    clicked = Signal(str)              # 通知 id
    delete_requested = Signal(str)        # 通知 id

    def __init__(self, notification: Notification, parent=None):
        super().__init__(parent)
        self._n = notification
        self.setObjectName("notifCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._build_ui()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 8, 8)
        layout.setSpacing(10)

        # 级别图标
        level_glyph, level_color = _LEVEL_META.get(self._n.level, _LEVEL_META[LEVEL_INFO])
        icon = QLabel(level_glyph, self)
        icon.setObjectName("notifCardIcon")
        icon.setFixedWidth(22)
        icon.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(f"color: {level_color}; font-size: 14px; font-weight: 700;")
        layout.addWidget(icon)

        # 主体：标题 + 正文 + 时间
        body = QVBoxLayout()
        body.setSpacing(2)

        title = QLabel(self._n.title or "(无标题)", self)
        title.setObjectName("notifCardTitle")
        title.setWordWrap(True)
        if not self._n.read:
            title.setStyleSheet("font-weight: 700;")
        body.addWidget(title)

        if self._n.body:
            content = QLabel(self._n.body, self)
            content.setObjectName("notifCardBody")
            content.setWordWrap(True)
            # V4.43.12：原先硬限高 48px ⇒ 稍长的正文**被直接裁掉**（用户反馈
            # 「内容显示不完整」）。改为不设像素上限，让 wordWrap 自然撑开、由外层
            # QScrollArea 负责滚动；仅设一个宽松上限（约 6 行）防止极端长文本占满整屏。
            content.setMaximumHeight(144)
            body.addWidget(content)

        meta_row = QHBoxLayout()
        meta_row.setSpacing(8)
        type_glyph, type_label, type_color = _TYPE_META.get(
            self._n.type, _TYPE_META[TYPE_INFO]
        )
        type_tag = QLabel(f"{type_glyph} {type_label}", self)
        type_tag.setStyleSheet(f"color: {type_color}; font-size: 11px;")
        meta_row.addWidget(type_tag)

        time_label = QLabel(_format_time(self._n.created_at), self)
        time_label.setObjectName("notifCardTime")
        meta_row.addWidget(time_label)

        if not self._n.read:
            dot = QLabel("●", self)
            dot.setStyleSheet("color: #ef4444; font-size: 10px;")
            meta_row.addWidget(dot)

        meta_row.addStretch()
        body.addLayout(meta_row)

        layout.addLayout(body, 1)

        # 删除按钮
        close_btn = QPushButton("✕", self)
        close_btn.setObjectName("notifCardCloseBtn")
        close_btn.setFixedSize(20, 20)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(lambda: self.delete_requested.emit(self._n.id))
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignTop)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._n.id)
        super().mousePressEvent(event)


# ─────────── 过滤标签按钮 ───────────
class _FilterTab(QPushButton):
    def __init__(self, key: str, label: str, meta, parent=None):
        super().__init__(label, parent)
        self._key = key
        self.setObjectName("notifFilterTab")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if meta and len(meta) >= 3 and meta[2]:
            self.setText(f"{meta[1]} {meta[0]}")


# ─────────── 主面板 ───────────
class NotificationCenterPanel(QFrame):
    """Trae IDE 风格通知中心下拉面板"""

    # 业务信号
    mark_all_read_requested = Signal()
    clear_all_requested = Signal()
    check_update_requested = Signal()
    feedback_requested = Signal()
    delete_requested = Signal(str)        # 通知 id
    item_clicked = Signal(str)            # 通知 id（UI 上等同于 mark_read）

    PANEL_WIDTH = 360
    PANEL_MAX_HEIGHT = 480

    def __init__(
        self,
        notification_store: NotificationStore,
        theme_manager,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._store = notification_store
        self._tm = theme_manager
        self._current_filter = "all"

        # Popup 类型
        self.setWindowFlags(
            Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setObjectName("notificationCenterPanel")
        self.setFixedWidth(self.PANEL_WIDTH)
        self.setMaximumHeight(self.PANEL_MAX_HEIGHT)

        self._build_ui()
        self._apply_theme()
        self.refresh()

        # 订阅 store 变更（其它地方写入也能自动刷新）
        self._store.register_callback(self._on_store_changed)

        if QApplication.instance() is not None:
            QApplication.instance().installEventFilter(self)

    def __del__(self):
        try:
            if self._store is not None:
                self._store.unregister_callback(self._on_store_changed)
        except Exception as e:
            logger.debug("析构 unregister_callback 失败（已忽略）: %s", e)

    # ─────────── UI 构造 ───────────
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 10, 8, 8)
        outer.setSpacing(6)

        # 阴影
        try:
            shadow = QGraphicsDropShadowEffect(self)
            shadow.setBlurRadius(20)
            shadow.setOffset(0, 4)
            shadow.setColor(QColor(0, 0, 0, 60))
            self.setGraphicsEffect(shadow)
        except Exception as e:
            logger.debug("阴影设置失败，降级: %s", e)

        outer.addWidget(self._build_header())
        outer.addWidget(self._build_filter_tabs())
        # 列表 / 空状态互斥占位
        self._list_container = QWidget(self)
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(4)

        self._scroll = QScrollArea(self._list_container)
        self._scroll.setObjectName("notifScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._list_inner = QWidget()
        self._list_inner_layout = QVBoxLayout(self._list_inner)
        self._list_inner_layout.setContentsMargins(0, 0, 0, 0)
        self._list_inner_layout.setSpacing(4)
        self._list_inner_layout.addStretch(1)
        self._scroll.setWidget(self._list_inner)
        self._list_layout.addWidget(self._scroll)

        self._empty_label = QLabel("", self._list_container)
        self._empty_label.setObjectName("notifEmpty")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setWordWrap(True)
        self._empty_label.hide()
        self._list_layout.addWidget(self._empty_label)

        outer.addWidget(self._list_container, 1)
        outer.addWidget(self._build_footer())

    def _build_header(self) -> QWidget:
        box = QFrame(self)
        box.setObjectName("notifHeader")
        layout = QHBoxLayout(box)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(8)

        title = QLabel("通知中心", box)
        title.setObjectName("notifHeaderTitle")
        layout.addWidget(title)

        layout.addStretch()

        self._mark_all_btn = QPushButton("全部已读", box)
        self._mark_all_btn.setObjectName("notifHeaderBtn")
        self._mark_all_btn.setFixedHeight(24)
        self._mark_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mark_all_btn.clicked.connect(self._on_mark_all_clicked)
        layout.addWidget(self._mark_all_btn)

        close_btn = QPushButton("✕", box)
        close_btn.setObjectName("notifHeaderCloseBtn")
        close_btn.setFixedSize(24, 24)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.hide)
        layout.addWidget(close_btn)

        return box

    def _build_filter_tabs(self) -> QWidget:
        box = QFrame(self)
        box.setObjectName("notifFilterBar")
        layout = QHBoxLayout(box)
        layout.setContentsMargins(10, 0, 10, 4)
        layout.setSpacing(6)

        self._filter_group = QButtonGroup(box)
        self._filter_group.setExclusive(True)
        for key, label, meta in _FILTER_LABELS:
            tab = _FilterTab(key, label, meta, box)
            tab.setFixedHeight(26)
            self._filter_group.addButton(tab)
            if key == self._current_filter:
                tab.setChecked(True)
            tab.clicked.connect(lambda _checked=False, k=key: self._set_filter(k))
            layout.addWidget(tab)
        layout.addStretch()
        return box

    def _build_footer(self) -> QWidget:
        box = QFrame(self)
        box.setObjectName("notifFooter")
        layout = QHBoxLayout(box)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)

        clear_btn = QPushButton("清空全部", box)
        clear_btn.setObjectName("notifFooterBtn")
        clear_btn.setFixedHeight(26)
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.clicked.connect(self._on_clear_all_clicked)
        layout.addWidget(clear_btn)

        layout.addStretch()

        update_btn = QPushButton("检查更新", box)
        update_btn.setObjectName("notifFooterBtn")
        update_btn.setFixedHeight(26)
        update_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        update_btn.clicked.connect(self.check_update_requested.emit)
        layout.addWidget(update_btn)

        feedback_btn = QPushButton("意见反馈", box)
        feedback_btn.setObjectName("notifFooterBtn")
        feedback_btn.setFixedHeight(26)
        feedback_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        feedback_btn.clicked.connect(self.feedback_requested.emit)
        layout.addWidget(feedback_btn)

        return box

    # ─────────── 渲染 ───────────
    def refresh(self):
        """根据当前 filter 重新拉数据并渲染卡片列表"""
        type_filter = None if self._current_filter == "all" else self._current_filter
        items = self._store.list(type=type_filter, only_unread=False, limit=100)

        # 清空旧卡片
        while self._list_inner_layout.count() > 1:  # 保留最后的 stretch
            item = self._list_inner_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

        if not items:
            self._scroll.hide()
            self._empty_label.show()
            if self._current_filter == "all":
                self._empty_label.setText("📭 暂无通知\n\n系统消息、反馈提交、版本更新都会汇总到这里")
            else:
                self._empty_label.setText("📭 该分类下暂无通知")
        else:
            self._empty_label.hide()
            self._scroll.show()
            for n in items:
                card = _NotificationCard(n, self._list_inner)
                card.clicked.connect(self._on_card_clicked)
                card.delete_requested.connect(self._on_card_delete)
                self._list_inner_layout.insertWidget(
                    self._list_inner_layout.count() - 1, card
                )

        # 全部已读按钮：仅在有未读时可点
        has_unread = self._store.unread_count() > 0
        self._mark_all_btn.setEnabled(has_unread)

    def _set_filter(self, key: str):
        if key == self._current_filter:
            return
        self._current_filter = key
        self.refresh()

    # ─────────── 回调 ───────────
    def _on_mark_all_clicked(self):
        # 本地立刻标记，再发信号让 main_window 同步刷新徽章
        self._store.mark_all_read()
        self.refresh()
        self.mark_all_read_requested.emit()

    def _on_clear_all_clicked(self):
        self._store.clear()
        self.refresh()
        self.clear_all_requested.emit()

    def _on_card_clicked(self, notif_id: str):
        if self._store.mark_read(notif_id):
            self.refresh()
            self.item_clicked.emit(notif_id)

    def _on_card_delete(self, notif_id: str):
        if self._store.delete(notif_id):
            self.refresh()
            self.delete_requested.emit(notif_id)

    def _on_store_changed(self, event: str, _notification: Notification):
        # 在主线程被回调（store 写入通常也在主线程）
        try:
            self.refresh()
        except Exception as e:
            logger.debug("刷新通知列表失败: %s", e)

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
        """挂在 anchor（一般是 🔔 通知按钮）正下方，右对齐"""
        if anchor is None:
            return
        anchor_rect = anchor.rect()
        global_pos = anchor.mapToGlobal(QPoint(0, 0))
        x = global_pos.x() + anchor_rect.width() - self.PANEL_WIDTH
        y = global_pos.y() + anchor_rect.height() + 4
        # 防止超出屏幕下方
        screen = anchor.screen()
        if screen is not None:
            screen_bottom = screen.availableGeometry().bottom()
            if y + self.PANEL_MAX_HEIGHT > screen_bottom:
                anchor_top = anchor.mapToGlobal(QPoint(0, 0)).y()
                y = max(40, anchor_top - self.PANEL_MAX_HEIGHT - 4)
        self.move(x, y)
        self.show()
        self.raise_()
        self.setFocus()

    def hide_panel(self):
        self.hide()

    # ─────────── 事件 ───────────
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonPress:
            if self.isVisible():
                pos = QCursor.pos()
                if not self.geometry().contains(pos):
                    self.hide()
        return super().eventFilter(obj, event)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        QApplication.instance().postEvent(self, QEvent(QEvent.Type.Hide))

    def customEvent(self, event):
        if event.type() == QEvent.Type.Hide:
            self.hide()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(event)


__all__ = ["NotificationCenterPanel"]
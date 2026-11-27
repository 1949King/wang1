"""
项目卡片 (ProjectCard / EmptyProjectCard)
========================================

对标 AI-Canvas-tauri ProjectLibraryModal.tsx 行 1-150（项目卡片墙）
- 缩略图占位（emoji/首字圆形 fallback）
- 标题 + 修改时间
- hover 显示操作按钮（重命名 / 复制 / 删除）
- 空状态:EmptyProjectCard 「+ 新建项目」 CTA 卡（含新建/导入按钮）—— V4.43.3 新增

PySide6 实现，与 React/Tailwind 不同：
- 用 QFrame + QVBoxLayout 模拟卡片结构
- 操作按钮默认隐藏，hover 显示（mouseMoveEvent）
- 主题跟随主程序（属性选择器）

V4.43.0 任务 #275 / V4.43.3 任务 #288
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget,
    QSizePolicy, QGraphicsDropShadowEffect,
)

from app.modules.lego.theme_manager import ThemeManager

logger = logging.getLogger("AI短剧编辑器.project_card")


def _format_mtime(ts: float) -> str:
    """把时间戳格式化成'刚刚 / N分钟前 / HH:MM / MM-DD / YYYY-MM-DD' 五档"""
    if not ts:
        return ""
    now = datetime.now().timestamp()
    diff = max(0, now - ts)
    if diff < 60:
        return "刚刚"
    if diff < 3600:
        return f"{int(diff // 60)} 分钟前"
    if diff < 86400:
        return datetime.fromtimestamp(ts).strftime("今天 %H:%M")
    if diff < 86400 * 7:
        return datetime.fromtimestamp(ts).strftime("%a %H:%M")
    if diff < 86400 * 365:
        return datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


# ─────────── V4.43.3:空项目 CTA 卡 ───────────
class EmptyProjectCard(QFrame):
    """首页空项目状态卡（占位 1 格,220×180）

    信号:
        create_requested()  — 点「新建」
        import_requested()  — 点「导入」
    """

    create_requested = Signal()
    import_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("emptyProjectCard")
        self.setFixedSize(220, 180)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # 与 ProjectCard 对齐的阴影
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(12)
        shadow.setOffset(0, 2)
        shadow.setColor(QColor(0, 0, 0, 80))
        self.setGraphicsEffect(shadow)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 10)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # "+" 大圆图标
        self._plus = QLabel("+")
        self._plus.setObjectName("emptyProjectPlus")
        self._plus.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._plus.setFixedHeight(54)
        f = QFont()
        f.setPointSize(34)
        f.setBold(True)
        self._plus.setFont(f)
        layout.addWidget(self._plus)

        title = QLabel("新建项目")
        title.setObjectName("emptyProjectTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        hint = QLabel("空白工程 · 支持 .timeline / .proj")
        hint.setObjectName("emptyProjectHint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)

        # 两按钮（新建 + 导入）
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        new_btn = QPushButton("新建")
        new_btn.setObjectName("brandBtn")
        new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        new_btn.clicked.connect(self.create_requested.emit)
        btn_row.addWidget(new_btn)

        import_btn = QPushButton("导入…")
        import_btn.setObjectName("ghostBtn")
        import_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        import_btn.clicked.connect(self.import_requested.emit)
        btn_row.addWidget(import_btn)
        layout.addLayout(btn_row)

        # 整体可点 → 触发新建
        self.setProperty("theme", ThemeManager.instance().current_theme)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.create_requested.emit()
            event.accept()
        else:
            super().mousePressEvent(event)

    def set_theme(self, theme: str) -> None:
        self.setProperty("theme", theme)
        for child in self.findChildren(QWidget):
            child.setProperty("theme", theme)


class ProjectCard(QFrame):
    """单张项目卡

    信号：
        open_requested(str)         — 双击 / 单击打开 → 项目 id
        rename_requested(str)       — 重命名 → 项目 id
        duplicate_requested(str)    — 复制 → 项目 id
        delete_requested(str)       — 删除 → 项目 id
    """

    open_requested = Signal(str)
    rename_requested = Signal(str)
    duplicate_requested = Signal(str)
    delete_requested = Signal(str)

    def __init__(
        self,
        project_id: str,
        title: str,
        emoji: str = "🎬",
        mtime: float = 0.0,
        clip_count: int = 0,
        duration_sec: float = 0.0,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._project_id = project_id
        self._title = title
        self._emoji = emoji
        self._mtime = mtime
        self._clip_count = clip_count
        self._duration_sec = duration_sec

        self.setObjectName("subpanelCard")
        self.setFixedSize(220, 180)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        # 阴影
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(12)
        shadow.setOffset(0, 2)
        shadow.setColor(QColor(0, 0, 0, 80))
        self.setGraphicsEffect(shadow)

        self._build_ui()
        self._apply_theme()

    # ─────────── UI 构建 ───────────
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(6)

        # 缩略图占位（emoji 居中）
        thumb = QLabel(self._emoji)
        thumb.setObjectName("projectThumbnail")
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb.setMinimumHeight(80)
        font = QFont()
        font.setPointSize(36)
        thumb.setFont(font)
        self._thumb = thumb
        layout.addWidget(thumb)

        # 标题（单行省略）
        self._title_label = QLabel(self._title)
        self._title_label.setObjectName("projectTitle")
        self._title_label.setWordWrap(False)
        self._title_label.setTextFormat(Qt.TextFormat.PlainText)
        # 截断长标题
        fm = self._title_label.fontMetrics()
        elided = fm.elidedText(self._title, Qt.TextElideMode.ElideRight, 200)
        self._title_label.setText(elided)
        self._title_label.setToolTip(self._title)
        layout.addWidget(self._title_label)

        # 元数据行（时间 + 数量 + 时长）
        meta_text = self._build_meta_text()
        self._meta_label = QLabel(meta_text)
        self._meta_label.setObjectName("projectMeta")
        layout.addWidget(self._meta_label)

        # 操作按钮（默认隐藏，hover 显示）
        self._actions = self._build_actions()
        self._actions_widget = self._wrap_actions(self._actions)
        self._actions_widget.setVisible(False)
        layout.addWidget(self._actions_widget)

        layout.addStretch(1)

    def _build_meta_text(self) -> str:
        parts = []
        if self._mtime:
            parts.append(_format_mtime(self._mtime))
        if self._clip_count > 0:
            parts.append(f"{self._clip_count} 个片段")
        if self._duration_sec > 0:
            mins = int(self._duration_sec // 60)
            secs = int(self._duration_sec % 60)
            parts.append(f"{mins}:{secs:02d}")
        return " · ".join(parts) if parts else "空项目"

    def _build_actions(self) -> dict[str, QPushButton]:
        """三个操作按钮（重命名 / 复制 / 删除）"""
        rename_btn = QPushButton("✏ 重命名")
        rename_btn.setObjectName("projectActionBtn")
        rename_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        rename_btn.clicked.connect(lambda: self.rename_requested.emit(self._project_id))

        dup_btn = QPushButton("⎘ 复制")
        dup_btn.setObjectName("projectActionBtn")
        dup_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        dup_btn.clicked.connect(lambda: self.duplicate_requested.emit(self._project_id))

        del_btn = QPushButton("🗑 删除")
        del_btn.setObjectName("projectActionBtnDanger")
        del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_btn.clicked.connect(lambda: self.delete_requested.emit(self._project_id))

        return {"rename": rename_btn, "duplicate": dup_btn, "delete": del_btn}

    def _wrap_actions(self, actions: dict[str, QPushButton]) -> QWidget:
        wrap = QWidget()
        wrap.setObjectName("projectActions")
        h = QHBoxLayout(wrap)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        for btn in actions.values():
            h.addWidget(btn)
        return wrap

    # ─────────── 交互 ───────────
    def enterEvent(self, event):
        self._actions_widget.setVisible(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._actions_widget.setVisible(False)
        super().leaveEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.open_requested.emit(self._project_id)
        super().mouseDoubleClickEvent(event)

    # ─────────── 主题 ───────────
    def _apply_theme(self) -> None:
        theme = ThemeManager.instance().current_theme
        self.setProperty("theme", theme)
        self._thumb.setProperty("theme", theme)
        self._title_label.setProperty("theme", theme)
        self._meta_label.setProperty("theme", theme)
        self._actions_widget.setProperty("theme", theme)
        for btn in self._actions.values():
            btn.setProperty("theme", theme)

    def set_theme(self, theme: str) -> None:
        self._apply_theme()

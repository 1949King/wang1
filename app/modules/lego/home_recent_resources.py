"""
最近资源面板 (RecentResourcesPanel)
====================================

对标 AI-Canvas-tauri ProjectAssetsOverlay.tsx 行 1-100（资源库最近使用）
- 横向滚动条（流式布局 fallback 到 QHBoxLayout）
- 资源项 = emoji 图标 + 文件名 + 时间
- 点击 → 触发资源使用信号

PyQt6 实现：
- QFrame 容器 + QHBoxLayout（流式不够灵活时也能用 wrap 布局 fallback）
- 资源类型固定枚举（视频/音频/图片/项目/脚本/角色/场景）

V4.43.0 任务 #276
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget,
    QScrollArea,
)

from app.modules.lego.theme_manager import ThemeManager

logger = logging.getLogger("AI短剧编辑器.recent_resources")


# 资源类型 → (emoji, 标签色 chip)
_TYPE_META = {
    "video":     ("🎞", "chipInfo"),
    "audio":     ("🎵", "chipAmber"),
    "image":     ("🖼", "chipSuccess"),
    "project":   ("📦", "chip"),
    "script":    ("📝", "chipMuted"),
    "character": ("👤", "chipWarning"),
    "scene":     ("🏞", "chipInfo"),
}


class ResourceChip(QPushButton):
    """单条资源 chip：emoji + 文件名"""

    def __init__(
        self,
        resource_id: str,
        emoji: str,
        name: str,
        rtype: str,
        mtime: float = 0.0,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._resource_id = resource_id
        self._rtype = rtype
        self._name = name

        self.setObjectName("resourceChip")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"{name}\n类型:{rtype}\n时间:{_format_recent_time(mtime)}")

        # 文本格式: "🎞 文件名.mp4"
        text = f"{emoji}  {name}"
        self.setText(text)

    @property
    def resource_id(self) -> str:
        return self._resource_id


def _format_recent_time(ts: float) -> str:
    if not ts:
        return "未知"
    diff = max(0, datetime.now().timestamp() - ts)
    if diff < 3600:
        return f"{int(diff // 60)} 分钟前"
    if diff < 86400:
        return f"{int(diff // 3600)} 小时前"
    if diff < 86400 * 7:
        return f"{int(diff // 86400)} 天前"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


class RecentResourcesPanel(QFrame):
    """最近使用资源面板

    信号：
        resource_clicked(str)  — 点击资源 → 资源 id
    """

    resource_clicked = pyqtSignal(str)

    def __init__(
        self,
        resources: Optional[list[dict]] = None,
        max_items: int = 12,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setObjectName("subpanelCard")
        self._max_items = max_items
        self._resources: list[dict] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        # 标题行
        header = QHBoxLayout()
        title = QLabel("📚 最近使用的资源")
        title.setObjectName("panelTitle")
        header.addWidget(title)
        header.addStretch(1)
        hint = QLabel("点击跳转")
        hint.setObjectName("panelHint")
        header.addWidget(hint)
        layout.addLayout(header)

        # 滚动行
        scroll = QScrollArea()
        scroll.setObjectName("chipScrollArea")
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(48)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        chip_row = QWidget()
        self._chip_layout = QHBoxLayout(chip_row)
        self._chip_layout.setContentsMargins(0, 0, 0, 0)
        self._chip_layout.setSpacing(8)
        self._chip_layout.addStretch(1)  # 左对齐

        scroll.setWidget(chip_row)
        layout.addWidget(scroll)

        if resources:
            self.set_resources(resources)

        self.setProperty("theme", ThemeManager.instance().current_theme)

    def set_resources(self, resources: list[dict]) -> None:
        """填充资源列表（每项 {id, name, type, mtime}）"""
        # 清空除 stretch 外的所有 widget
        while self._chip_layout.count() > 1:
            item = self._chip_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        self._resources = resources[: self._max_items]
        for r in self._resources:
            rid = r.get("id", "")
            name = r.get("name", "未命名")
            rtype = r.get("type", "video")
            mtime = r.get("mtime", 0.0)
            emoji, _ = _TYPE_META.get(rtype, ("📄", "chipMuted"))
            chip = ResourceChip(rid, emoji, name, rtype, mtime)
            chip.clicked.connect(lambda _checked, r=rid: self.resource_clicked.emit(r))
            # 插入到 stretch 之前
            self._chip_layout.insertWidget(self._chip_layout.count() - 1, chip)
            chip.setProperty("theme", ThemeManager.instance().current_theme)

    def set_theme(self, theme: str) -> None:
        self.setProperty("theme", theme)
        for child in self.findChildren(QWidget):
            child.setProperty("theme", theme)

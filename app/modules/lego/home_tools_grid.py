"""
首页工具网格 (Home Tools Grid)
================================

对标 AI-Canvas-tauri Sidebar.tsx 行 660-787（侧边栏按钮组）
- 8 工具入口：项目 / 存储 / 画布 / ComfyUI / Agent / 设置 / 统计 / 帮助
- 网格布局 4×2 或流式
- 每个工具 = 图标 + 标题 + 副标题（一句话功能）

PyQt6 实现：
- QGridLayout 4 列
- 每个 tool = QPushButton（#toolBtn 风格扩展，96×96）

V4.43.0 任务 #278
"""
from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame, QGridLayout, QVBoxLayout, QLabel, QPushButton, QWidget,
)

from app.modules.lego.theme_manager import ThemeManager

logger = logging.getLogger("AI短剧编辑器.home_tools_grid")


# 工具入口配置（单源真相）
TOOLS = [
    ("projects",  "📁", "项目库",   "浏览所有项目"),
    ("storage",   "💾", "存储管理", "空间 · 回收站"),
    ("canvas",    "🎨", "AI 画布",  "节点工作流"),
    ("comfyui",   "🖥", "ComfyUI",  "图像生成后端"),
    ("agent",     "🤖", "Agent",    "AI 助手"),
    ("settings",  "⚙", "设置",     "偏好与配置"),
    ("stats",     "📊", "统计",     "使用数据"),
    ("help",      "❓", "帮助",     "快捷键 · 文档"),
]


class _ToolCard(QPushButton):
    """单个工具卡（图标 + 标题 + 副标题）"""

    def __init__(
        self,
        tool_id: str,
        icon: str,
        title: str,
        subtitle: str,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._tool_id = tool_id
        self.setObjectName("toolCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(140, 92)
        # 文字多行布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)
        icon_lbl = QLabel(icon)
        icon_lbl.setObjectName("toolCardIcon")
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(icon_lbl)
        title_lbl = QLabel(title)
        title_lbl.setObjectName("toolCardTitle")
        layout.addWidget(title_lbl)
        subtitle_lbl = QLabel(subtitle)
        subtitle_lbl.setObjectName("toolCardSubtitle")
        subtitle_lbl.setWordWrap(False)
        fm = subtitle_lbl.fontMetrics()
        subtitle_lbl.setText(fm.elidedText(subtitle, Qt.TextElideMode.ElideRight, 116))
        layout.addWidget(subtitle_lbl)
        layout.addStretch(1)

    @property
    def tool_id(self) -> str:
        return self._tool_id


class HomeToolsGrid(QFrame):
    """8 工具入口网格（4 列 × 2 行）

    信号：
        tool_clicked(str)  — 工具被点击 → tool_id
    """

    tool_clicked = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("homeToolsGrid")
        self._cards: dict[str, _ToolCard] = {}

        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(12)

        for i, (tool_id, icon, title, subtitle) in enumerate(TOOLS):
            card = _ToolCard(tool_id, icon, title, subtitle)
            card.clicked.connect(lambda _checked, t=tool_id: self.tool_clicked.emit(t))
            self._cards[tool_id] = card
            row, col = i // 4, i % 4
            grid.addWidget(card, row, col)

        self.setProperty("theme", ThemeManager.instance().current_theme)

    def set_theme(self, theme: str) -> None:
        self.setProperty("theme", theme)
        for card in self._cards.values():
            card.setProperty("theme", theme)
            for child in card.findChildren(QWidget):
                child.setProperty("theme", theme)

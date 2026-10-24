"""
关于对话框 (AboutDialog)
========================

对标 AI-Canvas-tauri Sidebar.tsx AvatarMenu 行 419-561（About 部分）
- Logo + 版本号 + 检查更新按钮
- 8 能力徽标
- 7 技术栈 chip
- 简介文字

设计纪律：
- 单例，避免重复弹窗
- 主题跟随主程序（属性选择器）
- 借 #glassPanel QSS 实现视觉

V4.43.0 任务 #285
"""
from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget,
)

from app.modules.lego.theme_manager import ThemeManager

logger = logging.getLogger("AI短剧编辑器.about_dialog")


# 8 个能力徽标（直抄 AvatarMenu）
CAPABILITIES = [
    ("🎬", "AI 剪辑"),
    ("🎨", "智能画布"),
    ("🤖", "Agent 助手"),
    ("📝", "AI 文案"),
    ("🎞", "批量处理"),
    ("🧩", "插件生态"),
    ("🔌", "MCP 通道"),
    ("📡", "ComfyUI"),
]

# 7 个技术栈 chip
TECH_STACK = [
    "PyQt6", "React Flow", "TypeScript", "Vite",
    "MCP", "YAML", "SQLite",
]


class AboutDialog(QDialog):
    """关于对话框

    信号：
        check_update_requested() — 用户点「检查更新」
    """

    check_update_requested = pyqtSignal()

    _instance: Optional["AboutDialog"] = None

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("关于 拾光剪影")
        self.setFixedSize(540, 580)
        self.setObjectName("aboutDialog")
        self.setProperty("theme", ThemeManager.instance().current_theme)
        self._build_ui()

    @classmethod
    def instance(cls, parent: Optional[QWidget] = None) -> "AboutDialog":
        if cls._instance is None:
            cls._instance = cls(parent)
        return cls._instance

    def _build_ui(self) -> None:
        from app.version import __version__, VERSION_INFO

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        # ─────────── 顶部：Logo + 标题 + 版本 + 检查更新 ───────────
        header_row = QHBoxLayout()
        header_row.setSpacing(14)

        logo = QLabel("✨")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_font = QFont()
        logo_font.setPointSize(36)
        logo.setFont(logo_font)
        logo.setFixedSize(64, 64)
        logo.setObjectName("aboutLogoBox")
        header_row.addWidget(logo)

        title_layout = QVBoxLayout()
        title_layout.setSpacing(2)
        title = QLabel("拾光剪影")
        title.setObjectName("aboutAppTitle")
        title_font = QFont()
        title_font.setPointSize(20)
        title_font.setBold(True)
        title.setFont(title_font)
        title_layout.addWidget(title)

        version = QLabel(f"V{__version__} · {VERSION_INFO.get('codename', '')}")
        version.setObjectName("aboutVersion")
        title_layout.addWidget(version)
        header_row.addLayout(title_layout)

        header_row.addStretch(1)

        check_btn = QPushButton("🚀 检查更新")
        check_btn.setObjectName("brandBtn")
        check_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        check_btn.clicked.connect(self.check_update_requested.emit)
        header_row.addWidget(check_btn)

        layout.addLayout(header_row)

        # ─────────── 简介 ───────────
        desc = QLabel(
            "AI 驱动的短剧自动化生产平台 ——\n"
            "策划 · 导演 · 美术 · 剪辑一体化，从文字到成片。\n"
            "本机优先，开源可控。"
        )
        desc.setObjectName("aboutDescription")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # ─────────── 能力徽标（8 个） ───────────
        caps_title = QLabel("核心能力")
        caps_title.setObjectName("aboutSectionTitle")
        layout.addWidget(caps_title)

        caps_grid_layout = QVBoxLayout()
        caps_grid_layout.setSpacing(6)
        # 分两行 4×2
        for row_idx in range(0, len(CAPABILITIES), 4):
            row = QHBoxLayout()
            row.setSpacing(6)
            for icon, label in CAPABILITIES[row_idx: row_idx + 4]:
                chip = QLabel(f"{icon} {label}")
                chip.setObjectName("chip")
                row.addWidget(chip)
            row.addStretch(1)
            caps_grid_layout.addLayout(row)
        layout.addLayout(caps_grid_layout)

        # ─────────── 技术栈 chip ───────────
        stack_title = QLabel("技术栈")
        stack_title.setObjectName("aboutSectionTitle")
        layout.addWidget(stack_title)

        stack_layout = QHBoxLayout()
        stack_layout.setSpacing(6)
        for label in TECH_STACK:
            chip = QLabel(label)
            chip.setObjectName("chipMuted")
            stack_layout.addWidget(chip)
        stack_layout.addStretch(1)
        layout.addLayout(stack_layout)

        # ─────────── 底部：GitHub + 关闭 ───────────
        layout.addStretch(1)
        bottom_row = QHBoxLayout()
        github_link = QLabel("🔗 github.com/1949King/shiguangjianying")
        github_link.setObjectName("aboutGithub")
        github_link.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        bottom_row.addWidget(github_link)
        bottom_row.addStretch(1)
        close_btn = QPushButton("关闭")
        close_btn.setObjectName("toolBtn")
        close_btn.clicked.connect(self.close)
        bottom_row.addWidget(close_btn)
        layout.addLayout(bottom_row)

    # ─────────── 主题 ───────────
    def set_theme(self, theme: str) -> None:
        self.setProperty("theme", theme)
        for child in self.findChildren(QWidget):
            child.setProperty("theme", theme)

    # ─────────── 关闭清理 ───────────
    def closeEvent(self, event):
        AboutDialog._instance = None
        super().closeEvent(event)

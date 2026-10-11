"""
首页摘要卡片 (Home Sub Widgets)
================================

对标 AI-Canvas-tauri ComfyUISettings.tsx + McpControlSettings.tsx 行 1-80（卡片摘要）
- ComfyUISummaryCard：状态 + 路径 + 一键启动
- McpSummaryCard：端口 + 客户端连接数 + 令牌状态

PyQt6 实现：
- 复用 V4.43.0 新增的 #subpanelCard + #chipInfo / #chipSuccess / #chipDanger
- 点击 → 触发信号给 main_window 路由到设置面板

V4.43.0 任务 #277
"""
from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget,
)

from app.modules.lego.theme_manager import ThemeManager

logger = logging.getLogger("AI短剧编辑器.home_sub_widgets")


# ─────────── ComfyUI 摘要卡 ───────────
class ComfyUISummaryCard(QFrame):
    """ComfyUI 状态摘要（路径 / 状态 / 启动按钮）"""

    open_settings_requested = pyqtSignal()
    start_requested = pyqtSignal()

    def __init__(
        self,
        installed: bool = False,
        path: str = "未安装",
        running: bool = False,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setObjectName("subpanelCard")
        self.setMinimumHeight(110)
        self._installed = installed
        self._path = path
        self._running = running
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(6)

        # 标题行
        header = QHBoxLayout()
        title = QLabel("🎨 ComfyUI")
        title.setObjectName("cardTitle")
        header.addWidget(title)
        header.addStretch(1)
        # 状态 chip
        self._status_chip = QLabel()
        self._status_chip.setObjectName("chipMuted")
        header.addWidget(self._status_chip)
        layout.addLayout(header)

        # 路径
        self._path_label = QLabel(f"📁 {self._path}")
        self._path_label.setObjectName("cardMeta")
        self._path_label.setWordWrap(False)
        fm = self._path_label.fontMetrics()
        self._path_label.setText(f"📁 {fm.elidedText(self._path, Qt.TextElideMode.ElideMiddle, 280)}")
        self._path_label.setToolTip(self._path)
        layout.addWidget(self._path_label)

        # 按钮行
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self._start_btn = QPushButton("启动")
        self._start_btn.setObjectName("brandBtn")
        self._start_btn.setEnabled(self._installed and not self._running)
        self._start_btn.clicked.connect(self.start_requested.emit)
        btn_row.addWidget(self._start_btn)

        settings_btn = QPushButton("⚙ 设置")
        # V4.43.6：改用 ghostBtn —— toolBtn 是 36×36 的「圆形图标按钮」，
        # 套在带文字的「⚙ 设置」上会把文字压成只剩一个「设」。
        settings_btn.setObjectName("ghostBtn")
        settings_btn.clicked.connect(self.open_settings_requested.emit)
        btn_row.addWidget(settings_btn)

        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        self._refresh_status()

    def _refresh_status(self) -> None:
        if not self._installed:
            self._status_chip.setText("未安装")
            self._status_chip.setObjectName("chipDanger")
        elif self._running:
            self._status_chip.setText("● 运行中")
            self._status_chip.setObjectName("chipSuccess")
        else:
            self._status_chip.setText("○ 已停止")
            self._status_chip.setObjectName("chipMuted")
        # 重新应用 chip 样式
        theme = ThemeManager.instance().current_theme
        self._status_chip.setProperty("theme", theme)
        self._status_chip.style().unpolish(self._status_chip)
        self._status_chip.style().polish(self._status_chip)

    def update_state(self, installed: bool, path: str, running: bool) -> None:
        self._installed = installed
        self._path = path
        self._running = running
        self._start_btn.setEnabled(installed and not running)
        self._refresh_status()

    def set_theme(self, theme: str) -> None:
        self.setProperty("theme", theme)
        for child in self.findChildren(QWidget):
            child.setProperty("theme", theme)


# ─────────── MCP 摘要卡 ───────────
class McpSummaryCard(QFrame):
    """MCP 控制状态摘要（端口 / 客户端数 / 启动状态）"""

    open_settings_requested = pyqtSignal()
    copy_config_requested = pyqtSignal()

    def __init__(
        self,
        port: int = 0,
        running: bool = False,
        client_count: int = 0,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setObjectName("subpanelCard")
        self.setMinimumHeight(110)
        self._port = port
        self._running = running
        self._client_count = client_count
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(6)

        # 标题行
        header = QHBoxLayout()
        title = QLabel("🔌 MCP 控制")
        title.setObjectName("cardTitle")
        header.addWidget(title)
        header.addStretch(1)
        self._status_chip = QLabel()
        header.addWidget(self._status_chip)
        layout.addLayout(header)

        # 信息行
        info_text = f"📡 端口 {self._port if self._port else '—'}   👥 {self._client_count} 客户端"
        self._info_label = QLabel(info_text)
        self._info_label.setObjectName("cardMeta")
        layout.addWidget(self._info_label)

        # 按钮行
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        copy_btn = QPushButton("📋 复制配置")
        copy_btn.setObjectName("brandBtn")
        copy_btn.setEnabled(self._running)
        copy_btn.clicked.connect(self.copy_config_requested.emit)
        btn_row.addWidget(copy_btn)

        settings_btn = QPushButton("⚙ 设置")
        # V4.43.6：改用 ghostBtn —— toolBtn 是 36×36 的「圆形图标按钮」，
        # 套在带文字的「⚙ 设置」上会把文字压成只剩一个「设」。
        settings_btn.setObjectName("ghostBtn")
        settings_btn.clicked.connect(self.open_settings_requested.emit)
        btn_row.addWidget(settings_btn)

        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        self._refresh_status()

    def _refresh_status(self) -> None:
        if self._running:
            self._status_chip.setText("● 运行中")
            self._status_chip.setObjectName("chipSuccess")
        else:
            self._status_chip.setText("○ 未启动")
            self._status_chip.setObjectName("chipMuted")
        theme = ThemeManager.instance().current_theme
        self._status_chip.setProperty("theme", theme)
        self._status_chip.style().unpolish(self._status_chip)
        self._status_chip.style().polish(self._status_chip)

    def update_state(self, port: int, running: bool, client_count: int) -> None:
        self._port = port
        self._running = running
        self._client_count = client_count
        self._info_label.setText(
            f"📡 端口 {port if port else '—'}   👥 {client_count} 客户端"
        )
        self._refresh_status()

    def set_theme(self, theme: str) -> None:
        self.setProperty("theme", theme)
        for child in self.findChildren(QWidget):
            child.setProperty("theme", theme)

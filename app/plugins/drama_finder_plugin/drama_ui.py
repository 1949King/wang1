# -*- coding: utf-8 -*-
"""短剧筛选占位界面。保留 _selected 供「发送到剪辑」接口读取。"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from .crawler.drama_crawler import UNLOADED_MSG


class DramaFinderWidget(QWidget):
    """拓展中心 / 插件宿主打开的短剧筛选壳。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._selected = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        tip = QLabel(
            "🎭 短剧筛选\n\n"
            f"{UNLOADED_MSG}\n\n"
            "仍可通过拓展中心打开本页；「发送到剪辑」接口保留，"
            "需自行指定本地成片（无榜单可选）。"
        )
        tip.setWordWrap(True)
        tip.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        tip.setStyleSheet("color:#e4e4e7;font-size:13px;line-height:1.5;")
        layout.addWidget(tip, 1)

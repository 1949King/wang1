# -*- coding: utf-8 -*-
"""短剧筛选插件壳：IPlugin 入口，无爬虫/榜单功能。"""
from __future__ import annotations

import logging

from PyQt6.QtWidgets import QWidget

from app.core.plugin_loader import IPlugin, PluginCategory, PluginInfo, PluginType

from .crawler.drama_crawler import UNLOADED_MSG
from .drama_ui import DramaFinderWidget

logger = logging.getLogger("AI短剧编辑器.drama_finder_plugin")


class Plugin(IPlugin):
    name: str = "短剧筛选"
    version: str = "1.1.1"
    description: str = UNLOADED_MSG
    category: str = "运营工具"

    def __init__(self):
        self._context: dict = {}
        self._widget: QWidget | None = None
        self._initialized: bool = False

    @property
    def plugin_info(self) -> PluginInfo:
        return PluginInfo(
            id="drama-finder",
            name=self.name,
            version=self.version,
            description=self.description,
            author="官方",
            plugin_type=PluginType.CUSTOM,
            category=PluginCategory.GENERAL,
            file_path=__file__,
            tags=["短剧", "筛选"],
            min_engine_version="4.4.0",
        )

    def initialize(self, context: dict | None = None) -> bool:
        self._context = context or {}
        if not hasattr(self, "_widget"):
            self._widget = None
        self._initialized = True
        logger.info("[DramaFinderPlugin] 接口壳已初始化（功能已卸）")
        return True

    def shutdown(self) -> bool:
        w = getattr(self, "_widget", None)
        if w is not None:
            w.deleteLater()
            self._widget = None
        self._initialized = False
        return True

    def get_ui_config(self) -> dict:
        return {
            "name": "短剧筛选",
            "icon": "🎭",
            "description": UNLOADED_MSG,
            "category": "运营工具",
            "widget_class": "DramaFinderWidget",
            "params": [],
        }

    def on_enable(self) -> None:
        return None

    def on_disable(self) -> None:
        w = getattr(self, "_widget", None)
        if w is not None:
            w.setVisible(False)

    def run(self, data=None):
        if not getattr(self, "_initialized", False):
            self.initialize(getattr(self, "_context", None) or {})
        if getattr(self, "_widget", None) is None:
            self._widget = DramaFinderWidget()
        self._widget.setVisible(True)
        return self._widget

    def cleanup(self):
        self.shutdown()

"""
账号运营插件 (AccountOpsPlugin)
================================
接口壳：IPlugin + 占位 UI。功能已卸，由拓展中心打开。
"""

from __future__ import annotations

import logging

from PyQt6.QtWidgets import QWidget

from app.core.plugin_loader import IPlugin, PluginInfo, PluginType, PluginCategory

logger = logging.getLogger("AI短剧编辑器.account_ops_plugin")


class Plugin(IPlugin):
    """账号运营 — 拓展中心插件壳"""

    name: str = "账号运营"
    version: str = "1.0.0"
    description: str = "插件功能已卸，仅保留接口"
    category: str = "运营工具"

    def __init__(self):
        self._context: dict = {}
        self._widget: QWidget | None = None
        self._initialized: bool = False

    @property
    def plugin_info(self) -> PluginInfo:
        return PluginInfo(
            id="account-ops",
            name=self.name,
            version=self.version,
            description=self.description,
            author="官方",
            plugin_type=PluginType.CUSTOM,
            category=PluginCategory.GENERAL,
            file_path=__file__,
            tags=["账号", "发布", "矩阵", "运营", "爆款"],
            min_engine_version="4.4.0",
        )

    def initialize(self, context: dict | None = None) -> bool:
        try:
            self._context = context or {}
            if not hasattr(self, "_widget"):
                self._widget = None
            self._initialized = True
            logger.info("[AccountOpsPlugin] 初始化完成")
            return True
        except Exception as e:
            logger.error(f"[AccountOpsPlugin] 初始化失败: {e}")
            self._initialized = False
            return False

    def shutdown(self) -> bool:
        try:
            w = getattr(self, "_widget", None)
            if w is not None:
                w.deleteLater()
                self._widget = None
            self._initialized = False
            logger.info("[AccountOpsPlugin] 已关闭")
            return True
        except Exception as e:
            logger.error(f"[AccountOpsPlugin] 关闭失败: {e}")
            return False

    def get_ui_config(self) -> dict:
        return {
            "name": "账号运营",
            "icon": "👤",
            "description": "插件功能已卸，仅保留接口",
            "category": "运营工具",
            "widget_class": "AccountOpsModule",
            "params": [],
        }

    def on_enable(self) -> None:
        logger.info("[AccountOpsPlugin] 已启用")

    def on_disable(self) -> None:
        w = getattr(self, "_widget", None)
        if w is not None:
            w.setVisible(False)
        logger.info("[AccountOpsPlugin] 已禁用")

    def run(self, data=None):
        """返回账号运营占位组件。"""
        if not getattr(self, "_initialized", False):
            self.initialize(getattr(self, "_context", None) or {})
        if getattr(self, "_widget", None) is None:
            from app.modules.lego.account_ops_module import AccountOpsModule

            self._widget = AccountOpsModule()
        self._widget.setVisible(True)
        return self._widget

    def cleanup(self):
        self.shutdown()

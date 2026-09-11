# -*- coding: utf-8 -*-
"""账号运营 UI 壳。功能已卸，仅保留模块/插件打开入口。"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QVBoxLayout

from .base_module import BaseModule

UNLOADED_MSG = "插件功能已卸，仅保留接口"


class AccountOpsModule(BaseModule):
    """拓展中心打开的账号运营占位页。"""

    module_id = "account"
    module_name = "账号运营"
    module_icon = "👤"

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        title = QLabel(f"{self.module_icon} {self.module_name}")
        title.setStyleSheet("font-size:20px;font-weight:bold;color:#ffffff;")
        tip = QLabel(
            f"{UNLOADED_MSG}\n\n"
            "入口仍在：拓展中心顶部「👤 账号运营」、"
            "EventBus MODULE_ACTIVATED{target:extensions, action:account_ops}。\n"
            "Agent 的 account.collect_data / account.optimize_strategy / account.publish "
            "会诚实失败，不会本地假发布。"
        )
        tip.setWordWrap(True)
        tip.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        tip.setStyleSheet("color:#a1a1aa;font-size:13px;line-height:1.5;padding-top:8px;")
        layout.addWidget(title)
        layout.addWidget(tip, 1)

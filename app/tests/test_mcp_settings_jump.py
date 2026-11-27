# -*- coding: utf-8 -*-
"""首页 MCP 卡片「设置」→ 拓展中心 MCP 服务页签（2026-11-13）。"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    a = QApplication.instance() or QApplication(["ext-test"])
    yield a


class _StubTabs:
    def __init__(self, count: int):
        self._count = count
        self.current = 0

    def count(self) -> int:
        return self._count

    def setCurrentIndex(self, i: int) -> None:  # noqa: N802（Qt 命名）
        self.current = i


def test_tab_index_mapping():
    from app.modules.lego.extensions_module_pages import TAB_INDEX

    assert TAB_INDEX["mcp"] == 2
    assert set(TAB_INDEX) == {"installed", "skill", "mcp", "store", "canvas"}


def test_handle_module_action_switches_tab():
    from app.modules.lego.extensions_module import ExtensionsModule

    mod = ExtensionsModule.__new__(ExtensionsModule)
    mod._tabs = _StubTabs(5)
    assert mod.handle_module_action("mcp") is True
    assert mod._tabs.current == 2
    assert mod.handle_module_action("skill") is True
    assert mod._tabs.current == 1


def test_unknown_action_returns_false():
    from app.modules.lego.extensions_module import ExtensionsModule

    mod = ExtensionsModule.__new__(ExtensionsModule)
    mod._tabs = _StubTabs(5)
    assert mod.handle_module_action("nope") is False
    assert mod.handle_module_action("") is False
# -*- coding: utf-8 -*-
"""帮助模块搜索（2026-11-13）：搜索**不得**制造额外顶层窗口。

历史 bug：`_clear()` 只把控件 setParent(None) 不改可见性 ⇒ 可见控件短暂变成顶层窗口，
用户看到"搜索时很多小窗反复跳动"；一次搜索实测新增 583 个顶层窗口。
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    a = QApplication.instance() or QApplication(["help-test"])
    yield a


@pytest.fixture(scope="module")
def help_module(app):
    from app.modules.lego.help_module import HelpModule

    h = HelpModule()
    h.show()
    yield h
    h.close()
    h.deleteLater()
    app.processEvents()


def test_topics_include_disclaimer(help_module):
    names = [n for _, n, _ in help_module._help_topics]
    assert any("免责声明" in n for n in names)


def test_search_creates_no_new_top_level_windows(app, help_module):
    from PySide6.QtWidgets import QApplication

    before = {id(w) for w in QApplication.topLevelWidgets()}
    help_module._help_search.setText("团队协作")
    help_module._run_help_search()
    app.processEvents()
    leaked = [w for w in QApplication.topLevelWidgets() if id(w) not in before and w.isVisible()]
    assert leaked == [], f"搜索产生了 {len(leaked)} 个可见顶层窗口: {[type(w).__name__ for w in leaked[:8]]}"


def test_same_query_second_time_hits_cache(app, help_module):
    """同一关键词第二次搜索：不再新增缓存项（说明没有重复重建页面）。"""
    help_module._help_search.setText("导出")
    help_module._run_help_search()
    app.processEvents()
    size_after_first = len(help_module._topic_text_cache)
    assert help_module._help_search_results.count() > 0
    help_module._help_search.setText("导出")  # 同值，textChanged 不一定触发
    help_module._run_help_search()
    app.processEvents()
    assert len(help_module._topic_text_cache) == size_after_first

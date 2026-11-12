# -*- coding: utf-8 -*-
"""拓展中心子页跳转（2026-11-13）。

独立成文件的原因：extensions_module.py 已顶到单文件 2000 行规模守卫，
新增逻辑一律外置（先例：settings_team_tab.py / settings_cache_tab.py）。
"""
from __future__ import annotations

from typing import Any, Dict

#: 子页 key → QTabWidget 索引
TAB_INDEX: Dict[str, int] = {"installed": 0, "skill": 1, "mcp": 2, "store": 3, "canvas": 4}


def switch_extension_tab(tabs: Any, action: str) -> bool:
    """把拓展中心的页签切到 action 指定的子页；返回是否处理。"""
    key = str(action or "").strip().lower()
    idx = TAB_INDEX.get(key)
    if tabs is None or idx is None or idx >= tabs.count():
        return False
    tabs.setCurrentIndex(idx)
    return True
# -*- coding: utf-8 -*-
"""短剧筛选插件壳。入口：拓展中心；功能已卸，仅保留接口。"""

import os as _os
import sys as _sys

try:
    from .main import Plugin
    from .drama_ui import DramaFinderWidget
except ImportError:
    _pkg_dir = _os.path.dirname(_os.path.abspath(__file__))
    if _pkg_dir not in _sys.path:
        _sys.path.insert(0, _pkg_dir)
    from main import Plugin  # type: ignore[import-not-found]
    from drama_ui import DramaFinderWidget  # type: ignore[import-not-found]

PLUGIN_INFO = {
    "name": "短剧筛选",
    "version": "1.1.1",
    "author": "官方",
    "description": "插件功能已卸，仅保留接口。入口：拓展中心。",
    "category": "operation",
    "icon": "🎭",
    "entry_point": "Plugin",
    "dependencies": [],
    "tags": ["短剧", "筛选"],
    "compatibility": {
        "min_version": "4.4.0",
        "max_version": "5.9.9",
    },
}

__all__ = ["Plugin", "DramaFinderWidget", "PLUGIN_INFO"]

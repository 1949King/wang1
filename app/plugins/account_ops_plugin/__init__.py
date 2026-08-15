"""
账号运营插件
============
多平台账号矩阵、本地发布队列、爆款建议（非平台真 API）。
入口：拓展中心 →「👤 账号运营」；不再作为主导航模块。

兼容两套加载方式:
- 标准 Python 包: from app.plugins.account_ops_plugin import Plugin
- PluginManager 扁平加载: __init__.py → main.Plugin
"""

import os as _os
import sys as _sys

try:
    from .main import Plugin
except ImportError:
    _pkg_dir = _os.path.dirname(_os.path.abspath(__file__))
    if _pkg_dir not in _sys.path:
        _sys.path.insert(0, _pkg_dir)
    from main import Plugin  # type: ignore[import-not-found]

PLUGIN_INFO = {
    "name": "账号运营",
    "version": "1.0.0",
    "author": "官方",
    "description": "多平台账号矩阵与发布队列。默认无平台真 API；失败降级本地导出。仅拓展中心入口。",
    "category": "operation",
    "icon": "👤",
    "entry_point": "Plugin",
    "dependencies": [],
    "tags": ["账号", "发布", "矩阵", "运营", "爆款"],
    "compatibility": {
        "min_version": "4.4.0",
        "max_version": "5.9.9",
    },
}

__all__ = ["Plugin", "PLUGIN_INFO"]

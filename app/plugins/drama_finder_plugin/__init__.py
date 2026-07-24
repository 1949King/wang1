"""
短剧筛选插件
============
多平台热门短剧/漫剧筛选、热度排行、佣金分析。
支持 10+ 平台数据源，双数据源策略（真实 API + 静态缓存回退）。

分类: 运营工具 (operation)
版本: 1.0.0
作者: 官方

兼容两套加载方式:
- 标准 Python 包: from app.plugins.drama_finder_plugin import Plugin
- PluginManager 加载: spec_from_file_location(__init__.py) → 扁平模块
"""

import os as _os
import sys as _sys

try:
    # 标准包导入 (相对导入)
    from .main import Plugin, DramaFinderWidget
except ImportError:
    # PluginManager 扁平模块回退 (绝对导入, 需要 main.py 的同级路径)
    _pkg_dir = _os.path.dirname(_os.path.abspath(__file__))
    if _pkg_dir not in _sys.path:
        _sys.path.insert(0, _pkg_dir)
    from main import Plugin, DramaFinderWidget  # type: ignore[import-not-found]

# 插件元信息 (符合 PLUGIN_STANDARD.md §1.2)
PLUGIN_INFO = {
    "name": "短剧筛选",
    "version": "1.0.0",
    "author": "官方",
    "description": "智能筛选热门短剧，分析热度与佣金。支持多平台榜单浏览、多维度筛选、双数据源策略。",
    "category": "operation",
    "icon": "🎭",
    "entry_point": "Plugin",
    "dependencies": ["drama_crawler"],
    "tags": ["短剧", "筛选", "数据分析", "榜单", "佣金"],
    "compatibility": {
        "min_version": "4.4.0",
        "max_version": "5.9.9"
    }
}

__all__ = ["Plugin", "DramaFinderWidget", "PLUGIN_INFO"]

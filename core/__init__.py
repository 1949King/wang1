# -*- coding: utf-8 -*-
"""Core module exports

兼容 shim（2026-09-26 修复）：历史遗留空包。仓库根先于 app/ 进入 sys.path 时
（如 pytest conftest 的插入顺序），本空包会遮蔽 app/core，导致一切
``from core.xxx import ...`` 旧式导入报 ``No module named 'core.xxx'``
（转场插件在 pytest 下曾因此全员加载失败、静默回退）。
把 ``__path__`` 扩展到 app/core，使 ``core.xxx`` 在两种路径顺序下都能解析到真身；
app/core 中不存在的子模块（如 event_bus）行为与此前一致（导入失败，走既有回退）。
"""

import os as _os

_here = _os.path.dirname(_os.path.abspath(__file__))
_app_core = _os.path.normpath(_os.path.join(_here, "..", "app", "core"))

__path__ = [_here]
if _os.path.isdir(_app_core):
    __path__.append(_app_core)

# AI 功能模块已移除
__all__ = []

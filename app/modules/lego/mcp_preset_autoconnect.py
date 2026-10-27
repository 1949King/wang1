# -*- coding: utf-8 -*-
"""Blender MCP 默认自动连接（V4.46.19）。

为什么单独成文件：``extensions_module.py`` 已 2200+ 行、超单文件规模阈值
（``_verify/check_file_size.py`` 存量棘轮），新增功能必须离开主文件。

行为约定（勿改）：
- **幂等**：已连上同名预设就不重复连；「本会话只自动尝试一次」由调用方守（``_blender_autoconnect_done``）。
- **失败静默**：只写状态栏 + debug 日志，不弹窗打断——这只是「默认帮你连」，不是用户主动操作。
  用户手动点连接时才弹详细错误（``_connect_mcp_preset`` 里按 ``preset["_auto"]`` 区分）。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("AI短剧编辑器.extensions")


def auto_connect_blender_preset(module: Any) -> None:
    """对给定的 ExtensionsModule 实例执行 Blender 预设自动连接。

    参数用 ``Any`` + 鸭子类型而非导入 ExtensionsModule：避免循环导入
    （本模块被 extensions_module 导入）。
    """
    try:
        already = any(m.get("name") == "Blender MCP" for m in module._connected_mcps)
        if already:
            return
        from app.core.mcp_client import get_mcp_preset

        preset = get_mcp_preset("blender")
        if preset is None:
            return
        preset = dict(preset)
        preset["_auto"] = True  # 标记：失败只进状态栏，不弹窗
        module._set_status("正在按默认配置连接 Blender MCP...")
        module._connect_mcp_preset(preset)
    except Exception:
        logger.debug("Blender 自动连接失败（忽略，不影响使用）", exc_info=True)

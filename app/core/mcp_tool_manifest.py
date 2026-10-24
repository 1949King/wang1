# -*- coding: utf-8 -*-
"""MCP 工具清单导出（Agent 编排演进 · 工具化第一步，2026-10-18）
==========================================================

定位（§6.8.6 工具协议「MCP 化 = 远期」的**零风险前置件**）
----------------------------------------------------------
蓝图说「把生成、感知、剪辑包装成 MCP 工具」。真接 MCP server 需要
mcp SDK + 每个能力的结构化参数 schema —— 那是第三步的事。本模块只做
第一步：**把能力目录（单一事实源）导出成 MCP ``tools/list`` 形状的工具清单**，
零新增依赖、不改任何调用方；将来真接 MCP 时，server 端直接消费本清单，
缺的参数 schema 按需补，不用重构。

形状对齐 MCP spec（2025-06-18 Tool 定义）：
  - ``name`` / ``description`` / ``inputSchema`` 三字段必备；
  - ``annotations`` 用官方提示位映射本项目 effect 语义：
      read → ``readOnlyHint=True``
      canvas_write/file_write/media_write/memory_write → ``destructiveHint=True``
    （诚实：effect 表怎么登记，注解就怎么标，不美化。）
  - ``inputSchema`` 暂为泛型 object + 说明（结构化参数表未建，如实声明，
    不伪造字段清单）。

纪律（照 gen_task_registry / media_perception 先例）
----------------------------------------------------
- 纯 core 模块：不 import Qt、不 import app 包外依赖；能力目录懒导入；
- 导出绝不抛异常：失败返回 False 只记日志；
- 落盘路径 env ``SG_MCP_MANIFEST`` 隔离（守卫/测试不污染正式产物）。
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

_MANIFEST_DEFAULT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "mcp_tool_manifest.json")
_ENV_MANIFEST = "SG_MCP_MANIFEST"

#: effect → MCP 注解映射（唯一口径，勿散写）
_READ_EFFECTS = {"read"}
_WRITE_EFFECTS = {"canvas_write", "file_write", "media_write", "memory_write"}

#: 结构化参数表未建时的诚实占位 schema（不伪造字段清单）
_GENERIC_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "description": ("参数形态见能力 handler 约定（params dict）。"
                    "结构化参数 schema 为 MCP 化第二步按需补建，此处如实留空。"),
}


def _resolve_manifest_path() -> str:
    env = os.environ.get(_ENV_MANIFEST)
    return env.strip() if env and env.strip() else _MANIFEST_DEFAULT


def build_tool_manifest() -> List[Dict[str, Any]]:
    """能力目录 → MCP tools 列表（懒导入目录，纯读操作）。

    目录不可用时返回空列表（诚实：宁缺毋假）。
    """
    try:
        from app.core.agent_capability_catalog import CAPABILITY_ROWS
    except ImportError:
        from core.agent_capability_catalog import CAPABILITY_ROWS  # type: ignore
    tools: List[Dict[str, Any]] = []
    seen = set()
    for cid, category, effect, paid, desc, hemi, label, _kw in CAPABILITY_ROWS:
        if cid in seen:
            continue
        seen.add(cid)
        tools.append({
            "name": cid,
            "description": f"{label}：{desc}" if label else desc,
            "inputSchema": dict(_GENERIC_SCHEMA),
            "annotations": {
                "readOnlyHint": effect in _READ_EFFECTS,
                "destructiveHint": effect in _WRITE_EFFECTS,
                "category": category,
                "effect": effect,
                "paid": bool(paid),
                "hemisphere": hemi,
            },
        })
    return tools


def export_manifest(path: str = "") -> bool:
    """把工具清单写到 JSON（原子写）。失败返回 False，**绝不抛出**。"""
    target = (path or "").strip() or _resolve_manifest_path()
    try:
        tools = build_tool_manifest()
        if not tools:
            logger.warning("[mcp_manifest] 能力目录为空，跳过导出")
            return False
        d = os.path.dirname(target)
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix="mcpm_", suffix=".tmp", dir=d)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"tools": tools}, f, ensure_ascii=False, indent=1)
            os.replace(tmp, target)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    logger.debug("[mcp_manifest] 临时文件清理失败", exc_info=True)
        return True
    except Exception:
        logger.debug("[mcp_manifest] 导出失败（不阻断主链路）", exc_info=True)
        return False

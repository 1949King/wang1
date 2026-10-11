"""扩展体系统一门面（ExtensionsRegistry + SkillEngine + PluginManager）
======================================================================
项目里并存**三套**扩展载体，历史上各自被不同调用点手工合并，导致行为不一致：

============================  ==========================================  ==========================
载体                          存放位置                                     真实身份
============================  ==========================================  ==========================
ExtensionsRegistry            ``app/core/extension_base.py``               统一注册表（Plugin/Skill/MCP 适配器）
SkillEngine                   ``app/modules/lego/skill_engine.py``         AI 技能（可执行）
PluginManager                 ``app/core/plugin_manager.py``               传统文件插件（AI特效工坊等）
============================  ==========================================  ==========================

已发现的**不一致**（本模块要消除的）：

* ``capability_handlers.run_extension`` 只走 ① 注册表 → ② SkillEngine，
  **够不到 PluginManager 插件** ⇒ Agent 调「AI特效工坊」这类传统插件会报「未找到扩展」；
* ``editor_agent_panel_mixin._get_agent_extensions_context`` 走三源合并，
  但同一份合并逻辑与上面各写一遍（两处都要随协议演进维护）；
* 面板里 SkillEngine 回退分支写的是 ``from .extensions_context import ...``，
  而 :class:`ExtensionsContext` 实际在 ``app.core.extensions_context`` ⇒
  该分支**恒抛 ImportError 被吞掉**，等于技能回退从来没生效过。

本门面把「列出工具 / 定位扩展 / 执行扩展」三件事收敛为唯一实现，
供 ``capability_handlers`` 与 Agent 面板共同复用。
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("AI短剧编辑器.extensions.facade")

#: 扩展来源标记
SOURCE_REGISTRY = "registry"
SOURCE_SKILL = "skill"
SOURCE_PLUGIN = "plugin"

#: 三源优先级（执行时的回退顺序）
SOURCE_ORDER = (SOURCE_REGISTRY, SOURCE_SKILL, SOURCE_PLUGIN)

_provider_lock = threading.RLock()
_plugin_manager_provider: Optional[Callable[[], Any]] = None


# ============================================================
# PluginManager 注入（避免门面反向依赖 Qt / 编辑器实例）
# ============================================================

def set_plugin_manager_provider(provider: Optional[Callable[[], Any]]) -> None:
    """注册「如何取得 PluginManager」的回调（由编辑器在懒加载处登记一次）。"""
    global _plugin_manager_provider
    with _provider_lock:
        _plugin_manager_provider = provider


def get_plugin_manager() -> Optional[Any]:
    """取当前 PluginManager；未登记或取用失败返回 None。"""
    with _provider_lock:
        provider = _plugin_manager_provider
    if provider is None:
        return None
    try:
        return provider()
    except Exception as e:
        logger.debug("获取 PluginManager 失败: %s", e)
        return None


# ============================================================
# 列工具
# ============================================================

def _skill_engine():
    try:
        from app.modules.lego.skill_engine import skill_engine

        return skill_engine
    except Exception as e:
        logger.debug("SkillEngine 不可用: %s", e)
        return None


def _iter_registry_tools() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    try:
        from app.core.extension_base import get_extensions_registry

        for ext in get_extensions_registry().list_all():
            # De Morgan 等价：跳过「既未启用也不可用」的扩展
            if not (ext.is_enabled or ext.is_available):
                continue
            for t in (ext.get_tools() or []):
                out.append({
                    "extension_id": ext.info.id,
                    "extension_name": ext.info.name,
                    "extension_type": ext.extension_type.value,
                    "tool_id": t.id,
                    "tool_name": t.name,
                    "description": t.description,
                    "source": SOURCE_REGISTRY,
                })
    except Exception as e:
        logger.debug("收集 ExtensionsRegistry 工具失败: %s", e)
    return out


def _iter_skill_tools() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    # 外部 skill 注册是幂等的（仅首次真正扫描 app/skills/external/）
    try:
        from app.skills.external_loader import ensure_external_skills_registered

        ensure_external_skills_registered()
    except Exception as e:
        logger.debug("外部 skill 注册失败（不影响内置 skill）: %s", e)
    engine = _skill_engine()
    if engine is None:
        return out
    try:
        for skill in engine.list_all():
            out.append({
                "extension_id": skill.skill_id,
                "extension_name": skill.skill_name,
                "extension_type": "skill",
                "tool_id": skill.skill_id,
                "tool_name": skill.skill_name,
                "description": getattr(skill, "skill_description", ""),
                "source": SOURCE_SKILL,
            })
    except Exception as e:
        logger.debug("收集 SkillEngine 工具失败: %s", e)
    return out


def _iter_plugin_tools(plugin_manager: Any, enabled_only: bool = True) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if plugin_manager is None:
        return out
    try:
        plugins = plugin_manager.list_plugins(enabled_only=enabled_only)
    except TypeError:  # 兼容不带 enabled_only 参数的实现
        plugins = plugin_manager.list_plugins()
    except Exception as e:
        logger.debug("列插件失败: %s", e)
        return out
    for plugin in plugins or []:
        pid = getattr(plugin, "id", None)
        if not pid:
            continue
        out.append({
            "extension_id": pid,
            "extension_name": getattr(plugin, "name", pid),
            "extension_type": "plugin",
            "tool_id": pid,
            "tool_name": getattr(plugin, "name", pid),
            "description": getattr(plugin, "description", ""),
            "source": SOURCE_PLUGIN,
        })
    return out


def list_unified_tools(
    enabled_only: bool = True,
    plugin_manager: Any = None,
    include_sources: Optional[tuple] = None,
    dedup: bool = True,
) -> List[Dict[str, Any]]:
    """三源合并后的工具列表（形状与既有调用方完全一致）。

    Args:
        enabled_only: 插件是否只要已启用的
        plugin_manager: 显式传入的管理器；None 时用全局 provider
        include_sources: 只收集这些来源（默认全部）
        dedup: 是否按 ``(extension_id, tool_id)`` 去重（保留先出现者）
    """
    want = set(include_sources) if include_sources else set(SOURCE_ORDER)
    pm = plugin_manager if plugin_manager is not None else get_plugin_manager()

    tools: List[Dict[str, Any]] = []
    if SOURCE_REGISTRY in want:
        tools.extend(_iter_registry_tools())
    if SOURCE_SKILL in want:
        tools.extend(_iter_skill_tools())
    if SOURCE_PLUGIN in want:
        tools.extend(_iter_plugin_tools(pm, enabled_only=enabled_only))

    if not dedup:
        return tools
    seen = set()
    out: List[Dict[str, Any]] = []
    for t in tools:
        key = (t.get("extension_id"), t.get("tool_id"))
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


# ============================================================
# 定位 / 执行
# ============================================================

def find_source(extension_id: str, plugin_manager: Any = None) -> Optional[str]:
    """判断某扩展 id 归属哪一源（找不到返回 None）。"""
    if not extension_id:
        return None
    try:
        from app.core.extension_base import get_extensions_registry

        if get_extensions_registry().get(extension_id) is not None:
            return SOURCE_REGISTRY
    except Exception as e:
        logger.debug("查询 ExtensionsRegistry 失败: %s", e)
    engine = _skill_engine()
    if engine is not None:
        try:
            for skill in engine.list_all():
                if skill.skill_id == extension_id:
                    return SOURCE_SKILL
        except Exception as e:
            logger.debug("查询 SkillEngine 失败: %s", e)
    pm = plugin_manager if plugin_manager is not None else get_plugin_manager()
    if pm is not None:
        try:
            if pm.get_plugin(extension_id) is not None:
                return SOURCE_PLUGIN
        except Exception as e:
            logger.debug("查询 PluginManager 失败: %s", e)
    return None


def run_unified_tool(
    extension_id: str,
    tool_id: str = "",
    params: Optional[Dict[str, Any]] = None,
    plugin_manager: Any = None,
) -> Dict[str, Any]:
    """按「注册表 → 技能 → 插件」顺序执行扩展。

    返回统一结构::

        {"ok": bool, "source": str, "name": str, "tool_id": str,
         "result": Any, "message": str}

    ``ok=False`` 时 ``message`` 一定有可读原因；绝不静默返回成功。
    """
    ext_id = str(extension_id or "").strip()
    tool = str(tool_id or ext_id)
    call_params = dict(params or {})
    if not ext_id:
        return {"ok": False, "source": "", "name": "", "tool_id": tool,
                "result": None, "message": "缺少 extension_id 参数"}

    pm = plugin_manager if plugin_manager is not None else get_plugin_manager()

    # ① ExtensionsRegistry
    try:
        from app.core.extension_base import get_extensions_registry

        ext = get_extensions_registry().get(ext_id)
        if ext is not None:
            if not ext.is_available and not ext.initialize():
                return {"ok": False, "source": SOURCE_REGISTRY, "name": ext.info.name,
                        "tool_id": tool, "result": None,
                        "message": f"扩展 {ext.info.name} 初始化失败: {ext.error}"}
            result = ext.run(tool, **call_params)
            return {"ok": True, "source": SOURCE_REGISTRY, "name": ext.info.name,
                    "tool_id": tool, "result": result, "message": ""}
    except Exception as e:
        logger.warning("[facade] ExtensionsRegistry 执行失败: %s", e)

    # ② SkillEngine
    engine = _skill_engine()
    if engine is not None:
        try:
            for skill in engine.list_all():
                if skill.skill_id != ext_id:
                    continue
                from app.core.extensions_context import ExtensionsContext

                result = skill.execute(ExtensionsContext(inputs=call_params))
                return {"ok": True, "source": SOURCE_SKILL, "name": skill.skill_name,
                        "tool_id": tool, "result": result, "message": ""}
        except Exception as e:
            logger.warning("[facade] SkillEngine 执行失败: %s", e)

    # ③ PluginManager（传统插件）
    if pm is not None:
        try:
            plugin = pm.get_plugin(ext_id)
            if plugin is not None and getattr(plugin, "enabled", False):
                name = getattr(plugin, "name", ext_id)
                # run_plugin 内部已 try/except，失败返回 None
                result = pm.run_plugin(ext_id, **call_params)
                return {"ok": True, "source": SOURCE_PLUGIN, "name": name,
                        "tool_id": tool, "result": result, "message": ""}
        except Exception as e:
            logger.warning("[facade] PluginManager 执行失败: %s", e)

    return {"ok": False, "source": "", "name": "", "tool_id": tool,
            "result": None, "message": f"未找到扩展: {ext_id}"}


def unified_summary(plugin_manager: Any = None) -> Dict[str, Any]:
    """三源各自的数量摘要（诊断 / 自检用）。"""
    pm = plugin_manager if plugin_manager is not None else get_plugin_manager()
    registry = _iter_registry_tools()
    skills = _iter_skill_tools()
    plugins = _iter_plugin_tools(pm) if pm is not None else []
    return {
        "registry": len(registry),
        "skill": len(skills),
        "plugin": len(plugins),
        "plugin_manager_available": pm is not None,
        "total_dedup": len(list_unified_tools(plugin_manager=pm)),
    }

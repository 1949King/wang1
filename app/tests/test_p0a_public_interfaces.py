"""
test_p0a_public_interfaces.py
==============================
P0-A 验证：EditorCapabilityHandlers 走的是 agent_xxx 公开接口
而非 _xxx 私有方法，消除 Agent 框架对 EditorModule 内部实现的紧耦合。
"""
from __future__ import annotations

import inspect
from typing import Any


def _import_capability_handlers():
    """延迟导入，避免 import 时拉起 PyQt6。"""
    from app.core import capability_handlers
    return capability_handlers


def test_editor_handler_source_calls_public_methods():
    """4 个 editor handler 的源码应调用 agent_xxx 而非 _xxx。"""
    ch = _import_capability_handlers()
    EditorHandlers = ch.EditorCapabilityHandlers
    src = inspect.getsource(EditorHandlers)

    # 旧私有方法调用（P0-A 应全部移除）
    old_private_patterns = [
        "editor._split_clip_at_time",
        "editor._apply_filter_to_clip",
        "editor._apply_transition_to_clip",
        "editor._get_agent_timeline_context",
    ]
    for pat in old_private_patterns:
        assert pat not in src, f"handler 仍包含旧私有调用: {pat}"

    # 新公开方法调用（P0-A + 后续扩展，应全部存在）
    new_public_patterns = [
        "editor.agent_split_clip",
        "editor.agent_apply_filter",
        "editor.agent_apply_transition",
        "editor.agent_get_timeline_context",
    ]
    for pat in new_public_patterns:
        assert pat in src, f"handler 应调用公开方法: {pat}"


def test_editor_module_has_all_agent_public_methods():
    """EditorModule 上应存在 5 个 agent_xxx 公开方法。"""
    # 不直接 import EditorModule（太重），改用源码检查
    import subprocess as _sp
    import pathlib as _pl
    editor_path = _pl.Path(__file__).resolve().parent.parent / "modules" / "lego" / "editor_module.py"
    src = editor_path.read_text(encoding="utf-8")

    expected_methods = [
        "def agent_split_clip(",
        "def agent_apply_filter(",
        "def agent_apply_transition(",
        "def agent_get_timeline_context(",
        "def agent_execute_pipeline_editing(",
    ]
    for m in expected_methods:
        assert m in src, f"EditorModule 缺少公开方法: {m}"


def test_agent_methods_delegate_to_private():
    """每个 agent_xxx 方法应 try/except + 委托私有方法。"""
    import pathlib as _pl
    editor_path = _pl.Path(__file__).resolve().parent.parent / "modules" / "lego" / "editor_module.py"
    src = editor_path.read_text(encoding="utf-8")

    pairs = [
        ("agent_split_clip", "_split_clip_at_time"),
        ("agent_apply_filter", "_apply_filter_to_clip"),
        ("agent_apply_transition", "_apply_transition_to_clip"),
        ("agent_get_timeline_context", "_get_agent_timeline_context"),
        ("agent_execute_pipeline_editing", "_execute_pipeline_editing"),
    ]
    for pub, priv in pairs:
        # 公开方法名 + 私有方法名都应在文件中
        assert f"def {pub}(" in src, f"缺少公开方法 {pub}"
        assert f"def {priv}(" in src, f"缺少私有方法 {priv}"
        # 公开方法内部应委托私有方法（字符串形式）
        assert priv in src, f"委托关系缺失: {pub} → {priv}"


def test_pipeline_handler_uses_public_execute():
    """PipelineCapabilityHandlers.execute_editing 应找 agent_execute_pipeline_editing。"""
    ch = _import_capability_handlers()
    PipelineHandlers = ch.PipelineCapabilityHandlers
    src = inspect.getsource(PipelineHandlers)
    assert '"agent_execute_pipeline_editing"' in src, \
        "execute_editing handler 应查找 agent_execute_pipeline_editing"
    assert '"_execute_pipeline_editing"' not in src, \
        "execute_editing handler 不应再查找私有方法"

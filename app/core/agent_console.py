# -*- coding: utf-8 -*-
"""Agent 控制台数据层 —— 把任务 / 大脑 / 会话 / 循环 / 记忆聚合成一张快照。

定位（Track D 的数据侧）
------------------------
Agent 各子系统（task_store / session / brain / loop / memory）各自产数据，
但没有一个「控制台」把它们汇总给用户看。本模块提供纯数据聚合（UI 无关），
产出可直接喂给 PyQt 面板或画布前端的 dict；真正的面板渲染由 UI 层消费。

设计原则：
- 只读聚合，不写任何状态、不触发任何副作用（不 reinforce、不改任务）。
- 全部 try/except 降级：任一个子系统不可用，只缺那一块，不整体失败。
- 与 agent_loop.py / agent_brain.py 同层，均锁外新增。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def collect_agent_status(
    *,
    session_id: str = "",
    task_id: str = "",
    include_memory: bool = True,
) -> Dict[str, Any]:
    """聚合 Agent 控制台所需的状态快照。

    Returns:
        {
            "session": {...},        # 预算 / 模式 / 停止·暂停
            "brain": {...},          # 神经元 / 突触 / 左右脑
            "tasks": [...],          # 会话下任务列表
            "active_loops": [...],   # 运行中的多轮循环
            "memory": {...},         # 长期记忆 / 待处理反馈（可选）
        }
    """
    out: Dict[str, Any] = {
        "session": _session_snapshot(session_id),
        "brain": _brain_snapshot(),
        "affect": _affect_snapshot(),
        "tasks": _tasks_snapshot(session_id, task_id),
        "active_loops": _loops_snapshot(),
    }
    if include_memory:
        out["memory"] = _memory_snapshot()
    return out


def _session_snapshot(session_id: str) -> Dict[str, Any]:
    try:
        from app.core.agent_session import agent_sessions
        sid = (session_id or "agent_loop").strip() or "agent_loop"
        return agent_sessions.snapshot(sid)
    except Exception as e:
        return {"error": str(e)}


def _brain_snapshot() -> Dict[str, Any]:
    try:
        from app.core.agent_brain import agent_brain
        return agent_brain.get_brain_status()
    except Exception as e:
        return {"error": str(e)}


def _affect_snapshot() -> Dict[str, Any]:
    """内心状态（affect_model）快照：pain/trust/arousal/drive/impact + 门控结论。"""
    try:
        from app.core.ai.affect_model import agent_affect
        return agent_affect.snapshot()
    except Exception as e:
        return {"error": str(e)}


def _tasks_snapshot(session_id: str, task_id: str) -> List[Dict[str, Any]]:
    try:
        from app.core.agent_task_store import agent_tasks
        if task_id:
            t = agent_tasks.get(task_id)
            return [t] if t else []
        return agent_tasks.list_for_session(session_id or "agent_loop", limit=12)
    except Exception as e:
        return [{"error": str(e)}]


def _loops_snapshot() -> List[Dict[str, Any]]:
    try:
        from app.core.agent_loop import agent_loop
        return [r.to_dict() for r in getattr(agent_loop, "_active", {}).values()]
    except Exception as e:
        return [{"error": str(e)}]


def _memory_snapshot() -> Dict[str, Any]:
    snap: Dict[str, Any] = {}
    try:
        from app.core.memory_store import memory_store
        snap["project"] = memory_store.get_project_context()
    except Exception:
        snap["project"] = {}
    try:
        from app.core.agent_feedback_bridge import agent_feedback_bridge
        snap["pending_feedback"] = agent_feedback_bridge.get_pending_feedback(limit=5)
    except Exception:
        snap["pending_feedback"] = []
    return snap

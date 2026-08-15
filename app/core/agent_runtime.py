# -*- coding: utf-8 -*-
"""轻量 Agent Runtime：从模型回复解析画布工具并经 SSE 派发。

不直接改 Zustand；写操作走 task.create → 前端 executeRemoteTask（含 B 确认）。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("AI短剧编辑器.agent_runtime")

_JSON_OBJ = re.compile(r"\{[\s\S]*\}")


def parse_canvas_tools(raw: str) -> Tuple[str, List[Dict[str, Any]]]:
    """拆出中文回复与 canvas_tools。解析失败则原文不动。"""
    text = (raw or "").strip()
    if not text:
        return "", []
    blob = None
    m = _JSON_OBJ.search(text)
    if not m:
        return text, []
    try:
        blob = json.loads(m.group(0))
    except json.JSONDecodeError:
        # 尝试最后一个 JSON 对象
        last = text.rfind("{")
        if last < 0:
            return text, []
        try:
            blob = json.loads(text[last:])
        except json.JSONDecodeError:
            return text, []
    if not isinstance(blob, dict):
        return text, []
    tools = blob.get("canvas_tools") or blob.get("tools")
    if not isinstance(tools, list):
        return text, []
    out: List[Dict[str, Any]] = []
    for item in tools:
        if not isinstance(item, dict):
            continue
        action = str(item.get("action") or item.get("tool") or "").strip()
        if not action:
            continue
        params = item.get("params") if isinstance(item.get("params"), dict) else {}
        extra = {k: v for k, v in item.items() if k not in ("action", "tool", "params")}
        params = {**extra, **params}
        out.append({"action": action, "params": params})
    clean = (text[: m.start()] + text[m.end() :]).strip() if m else text
    if blob.get("reply"):
        clean = str(blob.get("reply")).strip() or clean
    return clean or text, out


def dispatch_canvas_tools(
    tools: List[Dict[str, Any]],
    *,
    mode: str,
    session_id: str,
    task_id: str = "",
    timeout: float = 25.0,
) -> List[Dict[str, Any]]:
    """策略校验后 push task.create，等待画布回执。"""
    from app.core.agent_policy import DECISION_DENY, MODE_PLAN, decide, normalize_mode, sanitize_for_log
    from app.core.agent_session import agent_sessions
    from app.core.agent_task_store import agent_tasks
    from app.core.project_agent_host import push_to_canvas, wait_for_canvas_reply

    amode = normalize_mode(mode)
    results: List[Dict[str, Any]] = []
    if not tools:
        return results
    if amode == MODE_PLAN:
        return [{"action": t.get("action"), "ok": False, "error": "Plan 模式不派发写工具"} for t in tools]

    for item in tools:
        action = str(item.get("action") or "")
        params = item.get("params") or {}
        ok_b, err_b = agent_sessions.begin_tool_call(session_id)
        if not ok_b:
            results.append({"action": action, "ok": False, "error": err_b})
            break
        decision = decide(tool_id=action, mode=amode, approved=False)
        if decision.action == DECISION_DENY:
            results.append({"action": action, "ok": False, "error": decision.reason})
            if task_id:
                agent_tasks.add_step(task_id, title=action, status="failed", detail=decision.reason)
            continue
        if task_id:
            agent_tasks.bump_tool(task_id)
            agent_tasks.add_step(
                task_id,
                title=action,
                status="waiting_approval" if decision.action == "require_approval" else "running",
                detail=sanitize_for_log({"params": params, "policy": decision.reason}),
            )
            try:
                agent_tasks.transition(task_id, "running")
            except Exception:
                pass
        evt = push_to_canvas(
            "task.create",
            {
                "task_id": task_id,
                "action": action,
                "params": params,
            },
            ack_required=True,
        )
        reply = wait_for_canvas_reply(str(evt.get("id") or ""), timeout=timeout)
        payload = (reply or {}).get("payload") if isinstance(reply, dict) else None
        ok = bool(payload and payload.get("ok")) if payload is not None else False
        err = ""
        if reply is None:
            err = "画布未回执（超时）"
        elif not ok:
            err = str((payload or {}).get("error") or "执行失败")
        results.append({"action": action, "ok": ok, "error": err, "payload": payload})
        if task_id:
            agent_tasks.add_step(
                task_id,
                title=f"{action} 结果",
                status="succeeded" if ok else "failed",
                detail=sanitize_for_log(payload or err),
            )
    return results

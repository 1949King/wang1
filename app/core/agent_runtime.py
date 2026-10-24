# -*- coding: utf-8 -*-
"""轻量 Agent Runtime：从模型回复解析画布工具并经 SSE 派发。

不直接改 Zustand；写操作走 task.create → 前端 executeRemoteTask（含 B 确认）。
"""
from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

from app.core.agent_constants import STATUS_RUNNING, STATUS_WAITING_APPROVAL

logger = logging.getLogger("AI短剧编辑器.agent_runtime")

_JSON_OBJ = re.compile(r"\{[\s\S]*\}")

# 只读工具：无副作用，可并发派发、不参与串行保序。
# 依据 agent_policy.lookup_tool 的 effect==read 判定，但这里预置一份白名单兜底，
# 避免每次派发都要 import agent_policy 做重判定（dispatch 内部仍会二次 decide 校验）。
_READONLY_TOOL_PREFIXES = (
    "editor.inspect_media",
    "editor.get_media",
    "editor.get_timeline_context",
    "editor.suggest_cleanup",
    "editor.suggest_canvas_roundtrip",
    "canvas.query",
    "canvas.list_actions",
    "model.list_models",
    "ext.list_tools",
)

# 串行工具：写操作，必须按顺序逐个等待回执（保序，避免时间线竞争）。
_WRITE_TOOL_PREFIXES = (
    "editor.split_clip",
    "editor.apply_filter",
    "editor.add_transition",
    "editor.set_clip_properties",
    "editor.set_keyframes",
    "editor.ripple_delete_range",
    "editor.trim_clip",
    "editor.move_clip",
    "editor.send_selected_to_canvas",
    "canvas.generate_image",
    "canvas.generate_video",
    "canvas.concat_videos",
    "pipeline.",
    "workflow.",
    "account.",
)

# 并发上限：只读工具最多同时派发几个（与 agent_policy.MAX_PARALLEL_READS 对齐）。
_MAX_PARALLEL_READS = 3

# 默认回执等待超时（秒）。画布是本地前端，正常回执 1~2s 内；
# 旧的 120s 会在画布不响应时干等 2 分钟卡死整轮。
_DEFAULT_TIMEOUT = 20.0
_READ_TIMEOUT = 8.0


def _is_readonly_action(action: str) -> bool:
    a = (action or "").strip()
    for p in _READONLY_TOOL_PREFIXES:
        if a == p or a.startswith(p):
            return True
    return False


def _is_serial_action(action: str) -> bool:
    a = (action or "").strip()
    for p in _WRITE_TOOL_PREFIXES:
        if a == p or a.startswith(p):
            return True
    return False


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


def _dispatch_one_tool(
    item: Dict[str, Any],
    *,
    amode: str,
    session_id: str,
    task_id: str,
    timeout: float,
) -> Dict[str, Any]:
    """派发单个画布工具并等待回执（策略校验 + push + wait 的原子单元）。

    从串行循环里拆出来，供「只读并发 / 写串行」两种调度复用。
    """
    from app.core.agent_policy import (
        DECISION_DENY,
        DECISION_REQUIRE_APPROVAL,
        decide,
        sanitize_for_log,
    )
    from app.core.agent_session import agent_sessions
    from app.core.agent_task_store import agent_tasks
    from app.core.project_agent_host import push_to_canvas, wait_for_canvas_reply

    action = str(item.get("action") or "")
    params = item.get("params") or {}

    ok_b, err_b = agent_sessions.begin_tool_call(session_id)
    if not ok_b:
        return {"action": action, "ok": False, "error": err_b}

    decision = decide(tool_id=action, mode=amode, approved=False)
    if decision.action == DECISION_DENY:
        if task_id:
            agent_tasks.add_step(task_id, title=action, status="failed", detail=decision.reason)
        return {"action": action, "ok": False, "error": decision.reason}
    if task_id:
        agent_tasks.bump_tool(task_id)
        agent_tasks.add_step(
            task_id,
            title=action,
            status=(
                STATUS_WAITING_APPROVAL
                if decision.action == DECISION_REQUIRE_APPROVAL
                else STATUS_RUNNING
            ),
            detail=sanitize_for_log({"params": params, "policy": decision.reason}),
        )
        try:
            agent_tasks.transition(task_id, STATUS_RUNNING)
        except Exception:
            logger.debug("agent_tasks.transition(%s, RUNNING) 失败", task_id, exc_info=True)

    evt = push_to_canvas(
        "task.create",
        {"task_id": task_id, "action": action, "params": params},
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

    if task_id:
        agent_tasks.add_step(
            task_id,
            title=f"{action} 结果",
            status="succeeded" if ok else "failed",
            detail=sanitize_for_log(payload or err),
        )
    return {"action": action, "ok": ok, "error": err, "payload": payload}


def dispatch_canvas_tools(
    tools: List[Dict[str, Any]],
    *,
    mode: str,
    session_id: str,
    task_id: str = "",
    timeout: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """策略校验后 push task.create，等待画布回执。

    延迟优化（V4.18.0）：只读工具（effect=read）并发派发，写工具串行保序。
    一次「5 工具」往返从 5 次压到「读并发 + 写串行」约 2~3 次，最坏超时从 120s 收到 20s。
    """
    from app.core.agent_policy import MODE_PLAN, normalize_mode

    amode = normalize_mode(mode)
    if not tools:
        return []
    if amode == MODE_PLAN:
        return [{"action": t.get("action"), "ok": False, "error": "Plan 模式不派发写工具"} for t in tools]

    # 分类：只读（并发） vs 写/串行（保序）
    read_items: List[Dict[str, Any]] = []
    serial_items: List[Dict[str, Any]] = []
    for item in tools:
        action = str(item.get("action") or "")
        if _is_readonly_action(action):
            read_items.append(item)
        else:
            serial_items.append(item)

    results: List[Dict[str, Any]] = []
    read_timeout = timeout if timeout is not None else _READ_TIMEOUT
    serial_timeout = timeout if timeout is not None else _DEFAULT_TIMEOUT

    # 只读工具并发派发（最多 _MAX_PARALLEL_READS 个并行）
    if read_items:
        if len(read_items) == 1:
            results.append(
                _dispatch_one_tool(
                    read_items[0], amode=amode, session_id=session_id,
                    task_id=task_id, timeout=read_timeout,
                )
            )
        else:
            with ThreadPoolExecutor(max_workers=_MAX_PARALLEL_READS) as pool:
                futures = [
                    pool.submit(
                        _dispatch_one_tool, it,
                        amode=amode, session_id=session_id,
                        task_id=task_id, timeout=read_timeout,
                    )
                    for it in read_items
                ]
                for fut in futures:
                    try:
                        results.append(fut.result())
                    except Exception as e:  # pragma: no cover - 防御
                        results.append({"action": "", "ok": False, "error": f"并发派发异常: {e}"})

    # 写/串行工具按序逐个派发（保持时间线写入顺序）
    for item in serial_items:
        results.append(
            _dispatch_one_tool(
                item, amode=amode, session_id=session_id,
                task_id=task_id, timeout=serial_timeout,
            )
        )

    return results

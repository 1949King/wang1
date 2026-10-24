# -*- coding: utf-8 -*-
"""自研画布 ↔ 剪辑 Agent / ai_engine / 拓展工具 的 Python 适配层（SSE 双向通信中枢）。

画布前端经 canvas_bridge 调用本模块，复用剪辑侧栏同一套：
ai_engine + agent_action_registry + CapabilityDispatcher + SkillEngine。
不另起第五套 Agent。

⚠️ 本模块是**自研画布 Agent 的唯一后端入口**，所有 SSE 事件推送、流式对话、
工具枚举/执行都走这里。不要在别处重复封装 chat 或 SSE 推送。

三模块对照（名字像一家人但职责完全不同）：
- ``canvas_runtime.py``          → 画布前端 HTTP 服务（Python HTTP / vite，端口 3010）
- ``canvas_agent_runtime.py``    → 外部 Node MCP agent（@basketikun/canvas-agent，端口 17371）
- ``project_agent_host.py``      → **本文件**：自研画布 ↔ 剪辑 Agent 的 Python 适配层

通信路径：
- 剪辑 Agent → 画布：``push_to_canvas()`` → ``canvas_bridge.broadcast_agent_event()`` → SSE 推给前端 EventSource
- 画布 → 剪辑 Agent：前端 ``sendAgentReply()`` → POST /host/agent/reply → ``wait_for_canvas_reply()`` 配对
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("AI短剧编辑器.project_agent_host")

_editor_ref: Any = None
_editor_lock = threading.Lock()

# ── 流式推送节流（chat.delta）──
# 每 _DELTA_INTERVAL 秒或满 _DELTA_MIN_CHARS 字才推一次。
# 长文场景可调小以降低「打字机」感知延迟；短响应场景调大以减少 SSE 消息量。
_DELTA_INTERVAL = 0.08
_DELTA_MIN_CHARS = 24


# ── 画布 Agent 事件推送（走 canvas_bridge SSE） ──────────────────

def push_to_canvas(
    event_type: str,
    payload: Any,
    *,
    correlation_id: Optional[str] = None,
    ack_required: bool = False,
) -> Dict[str, Any]:
    """向画布侧广播一条事件（chat.message / task.create / task.progress / task.done 等）。

    走 canvas_bridge 内存事件总线 + SSE 长连接。剪辑 Agent 任何想主动
    通知画布的场景都调这一个函数。

    Args:
        event_type: 事件类型，如 "chat.message"、"task.create"、"canvas.query"
        payload: 业务数据（dict 或基础类型）
        correlation_id: 可选，关联上一个事件的 id（用于 task→reply 配对）
        ack_required: 是否需要画布回执

    Returns:
        构造出的事件 dict（含 id），便于后续关联
    """
    try:
        from app.core.canvas_bridge import (
            broadcast_agent_event,
            make_agent_event,
        )

        evt = make_agent_event(
            event_type,
            payload,
            from_agent="editor",
            to_agent="canvas",
            correlation_id=correlation_id,
            ack_required=ack_required,
        )
        broadcast_agent_event(evt)
        logger.debug("[push_to_canvas] type=%s id=%s", event_type, evt.get("id"))
        return evt
    except Exception as e:
        logger.warning("[push_to_canvas] 失败（桥未就绪？）: %s", e)
        return {
            "id": "",
            "error": str(e),
            "type": event_type,
            "payload": payload,
        }


def wait_for_canvas_reply(
    correlation_id: str,
    timeout: float = 10.0,
) -> Optional[Dict[str, Any]]:
    """阻塞等待画布侧对某个 correlation_id 的回执。

    用法：先 push_to_canvas("task.create", ..., ack_required=True)，
    再调 wait_for_canvas_reply(evt["id"], timeout)。

    Args:
        correlation_id: 上一条 event.id
        timeout: 最长等待秒数

    Returns:
        画布回的事件 dict；超时或桥不可用时返回 None
    """
    try:
        from app.core.canvas_bridge import (
            register_reply_queue,
            unregister_reply_queue,
        )

        q = register_reply_queue(correlation_id)
        try:
            evt = q.get(timeout=timeout)
            return evt
        except Exception:
            return None
        finally:
            unregister_reply_queue(correlation_id)
    except Exception as e:
        logger.debug("[wait_for_canvas_reply] 桥未就绪: %s", e)
        return None



def bind_editor_module(mod: Any) -> None:
    """剪辑模块创建 Agent 面板后绑定，供画布 HTTP 复用。"""
    global _editor_ref
    with _editor_lock:
        _editor_ref = mod


def get_editor_module() -> Any:
    global _editor_ref
    with _editor_lock:
        if _editor_ref is not None:
            return _editor_ref
    # 回退：从主窗口取已加载的 editor 实例
    try:
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            return None
        for w in app.topLevelWidgets():
            getter = getattr(w, "get_module_widget", None)
            if callable(getter):
                mod = getter("editor")
                if mod is not None:
                    bind_editor_module(mod)
                    return mod
    except Exception as e:
        logger.debug("find editor module failed: %s", e)
    return None


def list_chat_models() -> Dict[str, Any]:
    """与剪辑 Agent 模型下拉同源：PROVIDERS + 已配置 Key + 激活项。"""
    try:
        from app.modules.lego.model_config import (
            PROVIDERS,
            ensure_active_provider_sensible,
            load_active_provider,
            merge_local_models_into_providers,
        )

        ensure_active_provider_sensible()
        # 惰性并入本机 Ollama 已装模型：静态表里 ollama.models 一直是空列表，
        # 导致「对话模型」下拉列不出本地模型（本机装了 qwen3.5 也选不到）。
        # 带 TTL 缓存 + 失败静默，**不在 import 期执行**（保冷启动）。
        merge_local_models_into_providers()
    except Exception:
        PROVIDERS = {}
        load_active_provider = lambda: ""  # type: ignore

    try:
        from app.core.ai_engine import ai_engine

        available = set(ai_engine.get_available_providers() or [])
    except Exception:
        available = set()

    try:
        from app.modules.lego.cloud_api import cloud_api_service
    except Exception:
        cloud_api_service = None

    active = ""
    try:
        active = load_active_provider() or ""
    except Exception:
        active = ""

    providers: List[Dict[str, Any]] = []
    for provider, cfg in (PROVIDERS or {}).items():
        name = (cfg or {}).get("name", provider)
        is_local = bool((cfg or {}).get("is_local"))
        configured = False
        if is_local:
            configured = provider in available
        elif cloud_api_service is not None:
            try:
                configured = bool(cloud_api_service.is_configured(provider))
            except Exception:
                configured = provider in available
        models = list((cfg or {}).get("models") or [])
        providers.append(
            {
                "id": provider,
                "name": name,
                "models": models,
                "configured": configured,
                "is_local": is_local,
                "active": provider == active,
            }
        )

    providers.sort(key=lambda p: (0 if p["active"] else 1, 0 if p["configured"] else 2, p["name"]))
    return {
        "ok": True,
        "active_provider": active,
        "providers": providers,
        "default": f"{active}::" if active else "",
    }


def _run_on_ui(fn) -> Tuple[bool, Any, str]:
    """在 Qt 主线程执行；失败则返回错误。"""
    try:
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QApplication
    except Exception as e:
        return False, None, f"PyQt 不可用: {e}"

    app = QApplication.instance()
    if app is None:
        try:
            return True, fn(), ""
        except Exception as e:
            return False, None, str(e)

    box: Dict[str, Any] = {}
    done = threading.Event()

    def _wrap():
        try:
            box["v"] = fn()
            box["ok"] = True
        except Exception as e:
            box["ok"] = False
            box["err"] = str(e)
            logger.exception("UI thread call failed")
        finally:
            done.set()

    QTimer.singleShot(0, _wrap)
    if not done.wait(timeout=5.0):
        return False, None, "等待主线程超时"
    if not box.get("ok"):
        return False, None, str(box.get("err") or "主线程执行失败")
    return True, box.get("v"), ""


def _build_canvas_fast_messages(
    message: str,
    canvas_context: Optional[Dict[str, Any]] = None,
    agent_mode: str = "",
    history: Optional[List[Dict[str, str]]] = None,
) -> List[Dict[str, str]]:
    """画布 Agent 轻量提示：system + 历史对话 + 当前 user，不拉时间线/拓展清单。"""
    from app.core.agent_policy import canvas_tools_prompt_block, mode_prompt_block

    # 注：画布 fast 路径的 canvas_tools 经 dispatch_canvas_tools **推给前端**
    # executeRemoteTask 执行（node-level camelCase action），不走后端 dispatcher。
    # 因此这里只列「前端本地 action」，不注入后端 capability_id（否则前端不认 ⇒ 无回执）。
    # 后端全能力可达见剪辑面板路径（ai_agent_panel._apply_agent_commands_to_editor）。
    system = (
        "你是拾光剪影「导演台画布」助手（Agent-IM）。"
        "用简短中文直接回答分镜、提示词、站位、生图/生视频建议。"
        "默认 2～6 句；除非用户明确要求长文或完整脚本。"
        "若上下文里有选中节点/参考视频，优先围绕它们给可执行建议。"
        + mode_prompt_block(agent_mode)
        + canvas_tools_prompt_block(agent_mode)
    )
    user = message.strip()
    if canvas_context:
        slim = {
            k: canvas_context.get(k)
            for k in (
                "session_id",
                "selected_id",
                "selected_kind",
                "selected_title",
                "selected_prompt",
                "selected_ref_video",
                "node_count",
                "attachments",
            )
            if canvas_context.get(k) is not None
        }
        user = f"{user}\n\n[画布上下文]\n{json.dumps(slim, ensure_ascii=False)[:2500]}"

    messages: List[Dict[str, str]] = [{"role": "system", "content": system}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user})
    return messages


def _resolve_chat_provider(provider: str, model: str, editor: Any) -> Tuple[str, str]:
    if not provider and editor is not None:
        try:
            provider, model = editor._get_selected_edit_agent_model()  # noqa: SLF001
        except Exception:
            logger.debug("忽略异常（原为 pass）: project_agent_host.py", exc_info=True)
    if not provider:
        try:
            from app.modules.lego.model_config import load_active_provider

            provider = load_active_provider() or ""
        except Exception:
            provider = ""
    return provider or "", model or ""


def project_agent_chat(
    *,
    message: str,
    provider: str = "",
    model: str = "",
    apply: bool = True,
    canvas_context: Optional[Dict[str, Any]] = None,
    mode: str = "",
    stream_id: str = "",
    agent_mode: str = "",
    session_id: str = "",
) -> Dict[str, Any]:
    """项目/画布 Agent 对话。

    - mode=canvas_fast 或带 canvas_context：轻量提示，不依赖剪辑模块已打开
    - 可选 stream_id：经 SSE 推送 chat.delta / chat.done，前端可边收边显
    - agent_mode: plan / collaborative / autonomous（对照会话策略）
    """
    message = (message or "").strip()
    if not message:
        return {"ok": False, "message": "消息为空"}

    from app.core.agent_context import compress_messages
    from app.core.agent_policy import MODE_PLAN, normalize_mode
    from app.core.agent_session import agent_sessions
    from app.core.agent_task_store import agent_tasks

    amode = normalize_mode(agent_mode or (canvas_context or {}).get("agent_mode"))
    sid_sess = (session_id or (canvas_context or {}).get("session_id") or "canvas").strip()
    agent_sessions.set_mode(sid_sess, amode)
    ok_round, err_round = agent_sessions.begin_model_round(sid_sess)
    if not ok_round:
        return {"ok": False, "message": err_round, "agent_mode": amode}

    history_msgs = agent_sessions.get_history_messages(sid_sess)

    task = agent_tasks.create(session_id=sid_sess, goal=message, mode=amode, source="canvas")
    agent_tasks.bump_round(task["id"])
    try:
        agent_tasks.transition(task["id"], "running")
    except Exception:
        logger.debug("忽略异常（原为 pass）: project_agent_host.py", exc_info=True)

    if amode == MODE_PLAN:
        apply = False

    editor = get_editor_module()
    use_fast = (mode or "").strip().lower() in ("canvas_fast", "fast", "canvas") or bool(
        canvas_context
    )
    # 画布场景默认快路径；剪辑侧栏无 canvas_context 仍走完整提示
    if not use_fast and editor is None:
        use_fast = True

    provider, model = _resolve_chat_provider(provider, model, editor)

    if use_fast:
        messages = _build_canvas_fast_messages(
            message, canvas_context, agent_mode=amode, history=history_msgs
        )
        path = "canvas_fast"
    else:
        def _build():
            msgs = editor._build_edit_agent_messages(message)  # noqa: SLF001
            if canvas_context:
                extra = (
                    "\n\n[画布上下文]\n"
                    + json.dumps(canvas_context, ensure_ascii=False)[:4000]
                )
                if msgs and msgs[-1].get("role") == "user":
                    msgs[-1]["content"] = str(msgs[-1].get("content") or "") + extra
            if history_msgs and msgs:
                system = [m for m in msgs if m.get("role") == "system"]
                rest = [m for m in msgs if m.get("role") != "system"]
                msgs = system + history_msgs + rest
            return msgs

        ok, messages, err = _run_on_ui(_build)
        if not ok:
            # 主线程失败时降级快路径，避免整段不可用
            logger.warning("editor prompt build failed, fallback canvas_fast: %s", err)
            messages = _build_canvas_fast_messages(
                message, canvas_context, agent_mode=amode, history=history_msgs
            )
            path = "canvas_fast_fallback"
        else:
            path = "editor"

    # 预算按模型窗口自适应（V4.33.4）：128K 窗口 ≈ 15 万字符，未命中模型时退回 12000
    messages = compress_messages(messages, model=model, provider=provider)
    sid = (stream_id or "").strip() or f"s_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
    if sid:
        push_to_canvas(
            "chat.delta",
            {"stream_id": sid, "delta": "", "status": "start", "path": path},
        )

    try:
        from app.core.ai_engine import ai_engine

        chunks: List[str] = []
        last_push = 0.0
        buf = ""

        def _emit_delta(force: bool = False) -> None:
            nonlocal last_push, buf
            if not sid or not buf:
                return
            now = time.time()
            if not force and (now - last_push) < _DELTA_INTERVAL and len(buf) < _DELTA_MIN_CHARS:
                return
            push_to_canvas(
                "chat.delta",
                {"stream_id": sid, "delta": buf, "status": "delta"},
            )
            buf = ""
            last_push = now

        if provider:
            stream = ai_engine.chat(
                provider,
                messages,
                model=model or None,
                stream=True,
                use_cache=False,
            )
        else:
            stream = ai_engine.chat_with_fallback(
                messages=messages,
                model=model or None,
                use_cache=False,
                template=lambda: "模型暂不可用，请在「模型管理」配置 Key 或启动 Ollama。",
            )
        for chunk in stream:
            if chunk:
                piece = str(chunk)
                chunks.append(piece)
                buf += piece
                _emit_delta(False)
        _emit_delta(True)
        raw = "".join(chunks).strip()
    except Exception as e:
        try:
            agent_tasks.transition(task["id"], "failed", errorCode="model_error")
        except Exception:
            logger.debug("忽略异常（原为 pass）: project_agent_host.py", exc_info=True)
        push_to_canvas(
            "chat.done",
            {"stream_id": sid, "ok": False, "error": str(e), "path": path},
        )
        return {"ok": False, "message": f"模型调用失败: {e}", "stream_id": sid, "path": path}

    if raw.startswith("错误:") or raw.startswith("API 错误"):
        push_to_canvas(
            "chat.done",
            {"stream_id": sid, "ok": False, "error": raw, "path": path},
        )
        return {"ok": False, "message": raw, "reply": raw, "stream_id": sid, "path": path}

    commands: List[Any] = []
    results: List[Any] = []
    canvas_tool_results: List[Any] = []
    canvas_tools: List[Any] = []
    reply = raw
    try:
        from app.core.agent_runtime import parse_canvas_tools

        clean, canvas_tools = parse_canvas_tools(raw)
        if canvas_tools:
            reply = clean or raw
    except Exception as e:
        logger.warning("parse canvas tools: %s", e)

    # 仅完整剪辑路径 + 已绑定 editor 时尝试解析落轨指令
    if path == "editor" and editor is not None and apply:

        def _parse_apply():
            nonlocal commands, results, reply
            cmds = editor._parse_agent_commands(message, raw)  # noqa: SLF001
            commands = cmds or []
            if commands and apply:
                results = editor._apply_agent_commands_to_editor(commands)  # noqa: SLF001
            reply = raw
            return True

        ok2, _, err2 = _run_on_ui(_parse_apply)
        if not ok2:
            push_to_canvas(
                "chat.done",
                {
                    "stream_id": sid,
                    "ok": True,
                    "text": raw,
                    "path": path,
                    "warning": err2,
                },
            )
            return {
                "ok": True,
                "reply": raw,
                "message": f"已得到回复，但解析/应用失败: {err2}",
                "commands": [],
                "results": [],
                "provider": provider,
                "model": model,
                "stream_id": sid,
                "path": path,
            }

    push_to_canvas(
        "chat.done",
        {
            "stream_id": sid,
            "ok": True,
            "text": reply,
            "path": path,
            "applied": bool(apply and commands),
            "task_id": task.get("id"),
        },
    )

    # 落盘本轮对话到 session history（供下一轮作为上下文）
    try:
        agent_sessions.push_history(sid_sess, message, reply)
    except Exception:
        logger.warning("push_history 失败", exc_info=True)

    if canvas_tools:
        try:
            from app.core.agent_runtime import dispatch_canvas_tools

            canvas_tool_results = dispatch_canvas_tools(
                canvas_tools,
                mode=amode,
                session_id=sid_sess,
                task_id=str(task.get("id") or ""),
            )
            all_ok = all(r.get("ok") for r in canvas_tool_results) if canvas_tool_results else True
            push_to_canvas(
                "task.done" if all_ok else "task.fail",
                {
                    "task_id": task.get("id"),
                    "results": canvas_tool_results,
                    "error": "" if all_ok else "部分工具失败",
                },
            )
        except Exception as e:
            logger.warning("canvas tool dispatch: %s", e)

    try:
        agent_tasks.transition(
            task["id"],
            "completed" if not canvas_tool_results or all(r.get("ok") for r in canvas_tool_results) else "failed",
        )
    except Exception:
        logger.debug("忽略异常（原为 pass）: project_agent_host.py", exc_info=True)

    return {
        "ok": True,
        "reply": reply,
        "raw": raw,
        "commands": commands,
        "results": results,
        "canvas_tools": canvas_tool_results,
        "task_id": task.get("id"),
        "applied": bool(apply and commands),
        "message": "画布 Agent 已回复" if use_fast else "项目 Agent 已回复",
        "provider": provider,
        "model": model,
        "stream_id": sid,
        "path": path,
        "agent_mode": amode,
    }


def list_project_tools(agent_mode: str = "") -> Dict[str, Any]:
    """拓展中心工具 + Skill + capability 枚举（与侧栏 Agent 同源）。"""
    from app.core.agent_policy import EFFECT_READ, list_canvas_tools_for_mode, lookup_tool, normalize_mode

    amode = normalize_mode(agent_mode) if agent_mode else ""
    tools: List[Dict[str, Any]] = []
    tools.extend(list_canvas_tools_for_mode(amode or None))
    try:
        from app.skills.external_loader import ensure_external_skills_registered

        ensure_external_skills_registered()
    except Exception:
        logger.debug("忽略异常（原为 pass）: project_agent_host.py", exc_info=True)

    editor = get_editor_module()
    if editor is not None and hasattr(editor, "_get_agent_extensions_context"):
        ok, v, err = _run_on_ui(lambda: editor._get_agent_extensions_context())  # noqa: SLF001
        if ok and isinstance(v, list):
            tools.extend(v)
        elif err:
            logger.debug("list tools via editor failed: %s", err)

    if not tools:
        # 无编辑器时直接扫 registry / skill_engine
        try:
            from app.core.extension_base import get_extensions_registry

            for ext in get_extensions_registry().list_all():
                if not ext.is_enabled and not ext.is_available:
                    continue
                for t in ext.get_tools() or []:
                    tools.append(
                        {
                            "extension_id": ext.info.id,
                            "extension_name": ext.info.name,
                            "extension_type": ext.extension_type.value,
                            "tool_id": t.id,
                            "tool_name": t.name,
                            "description": t.description,
                        }
                    )
        except Exception as e:
            logger.debug("registry tools: %s", e)
        try:
            from app.modules.lego.skill_engine import skill_engine

            for skill in skill_engine.list_all():
                tools.append(
                    {
                        "extension_id": skill.skill_id,
                        "extension_name": skill.skill_name,
                        "extension_type": "skill",
                        "tool_id": skill.skill_id,
                        "tool_name": skill.skill_name,
                        "description": getattr(skill, "skill_description", ""),
                    }
                )
        except Exception as e:
            logger.debug("skill tools: %s", e)

    caps: List[Dict[str, Any]] = []
    try:
        from app.core.capability_dispatcher import get_capability_dispatcher

        caps = get_capability_dispatcher().list_capabilities()
        if amode == "plan":
            caps = [c for c in caps if lookup_tool(str(c.get("capability_id") or ""))[0] == EFFECT_READ]
    except Exception as e:
        logger.debug("list caps: %s", e)

    if amode == "plan":
        tools = [t for t in tools if t.get("effect") == EFFECT_READ]

    return {
        "ok": True,
        "tools": tools[:200],
        "capabilities": caps[:200],
        "agent_mode": amode or "collaborative",
        "message": f"工具 {len(tools)} · capability {len(caps)}",
    }


def run_project_tool(
    *,
    extension_id: str = "",
    tool_id: str = "",
    skill_id: str = "",
    params: Optional[Dict[str, Any]] = None,
    agent_mode: str = "",
    approved: bool = False,
    session_id: str = "",
) -> Dict[str, Any]:
    """经 CapabilityDispatcher 执行拓展/Skill（与侧栏 call_extension 同源）。"""
    params = dict(params or {})
    try:
        from app.core.capability_dispatcher import CapabilityRequest, get_capability_dispatcher

        disp = get_capability_dispatcher()
        if skill_id or (extension_id and not tool_id):
            sid = skill_id or extension_id
            req = CapabilityRequest(
                capability_id="ext.run_skill",
                params={"skill_id": sid, **params},
                caller="canvas",
                agent_mode=agent_mode,
                approved=approved,
                session_id=session_id,
            )
        else:
            req = CapabilityRequest(
                capability_id="ext.run_extension",
                params={
                    "extension_id": extension_id,
                    "tool_id": tool_id or extension_id,
                    "params": params,
                },
                caller="canvas",
                agent_mode=agent_mode,
                approved=approved,
                session_id=session_id,
            )
        # dispatcher 内部可能碰 UI，尽量丢主线程
        ok, result, err = _run_on_ui(lambda: disp.invoke(req))
        if not ok:
            return {"ok": False, "message": err}
        success = bool(getattr(result, "success", False))
        return {
            "ok": success,
            "message": getattr(result, "error", None)
            or (getattr(result, "data", None) and str(result.data)[:300])
            or ("完成" if success else "失败"),
            "data": getattr(result, "data", None),
            "error": getattr(result, "error", None),
        }
    except Exception as e:
        return {"ok": False, "message": f"执行失败: {e}"}


# ════════════════════════════════════════════════════════════════════════
# 剧本合规守护 —— AI 检查剧本 / 分镜 / 角色 的一致性
#   复用 ai_engine + push_to_canvas SSE 推送
# ════════════════════════════════════════════════════════════════════════

def script_compliance_check(
    script: str,
    shots: Optional[List[Dict[str, Any]]] = None,
    characters: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """剧本合规守护：检查剧本内容与分镜/角色配置的一致性。

    检查维度：
    1. **场景遗漏** — 剧本中提到的场景是否都有对应分镜
    2. **角色冲突** — 剧本中出现的角色是否在角色库中存在
    3. **节奏断裂** — 分镜时长与剧本段落是否对齐
    4. **Prompt 偏离** — 分镜 Prompt 是否准确反映剧本意图

    Args:
        script: 剧本文本
        shots: 分镜节点列表（[{title, prompt, shotSize, duration, characterName}, ...]）
        characters: 角色列表（[{name, appearance, ...}, ...]）

    Returns:
        {"ok": True, "suggestions": [...], "summary": "..."}
        同时通过 SSE 推送 ``compliance.report`` 事件到前端
    """
    script = (script or "").strip()
    if not script:
        return {"ok": False, "message": "剧本为空"}

    shots = shots or []
    characters = characters or []

    # ── 启发式快速检查（不依赖 AI，秒级返回） ──
    suggestions: List[Dict[str, Any]] = []

    script_chars: List[str] = []
    for line in script.splitlines():
        line = line.strip()
        if not line:
            continue
        # 简易角色识别：以「」『』包裹或冒号前缀
        if line.startswith(("「", "『")) and "」" in line:
            name = line[1 : line.index("」")].strip()
            if name:
                script_chars.append(name)
        if "：" in line and len(line.split("：")[0]) <= 6:
            name = line.split("：")[0].strip()
            if name and name not in script_chars:
                script_chars.append(name)

    known_names = {c.get("name", "") for c in characters if c.get("name")}
    shot_char_names = {s.get("characterName", "") for s in shots if s.get("characterName")}

    # 角色在剧本中出现但不在角色库
    unknown_chars = [n for n in script_chars if n and n not in known_names]
    if unknown_chars:
        suggestions.append(
            {
                "level": "warning",
                "category": "角色冲突",
                "message": f"剧本中出现 {len(unknown_chars)} 个角色未在角色库中定义：{', '.join(unknown_chars[:5])}",
                "action": "add_character",
                "subject": unknown_chars[:3],
            }
        )

    # 分镜中绑定的角色不在剧本里
    orphan_shots = [s for s in shots if s.get("characterName") and s["characterName"] not in script_chars]
    if orphan_shots:
        suggestions.append(
            {
                "level": "info",
                "category": "Prompt 偏离",
                "message": f"{len(orphan_shots)} 个分镜绑定的角色在剧本中未出现，可能是遗留绑定",
                "action": "unbind_character",
                "subject": [s.get("title", "") for s in orphan_shots[:3]],
            }
        )

    # 剧本段落 vs 分镜数量
    script_blocks = [b for b in script.split("\n\n") if b.strip()]
    if len(script_blocks) > len(shots) + 2:
        suggestions.append(
            {
                "level": "warning",
                "category": "场景遗漏",
                "message": f"剧本有 {len(script_blocks)} 个段落但只有 {len(shots)} 个分镜，可能遗漏了关键场景",
                "action": "add_missing_shots",
                "subject": [],
            }
        )
    elif len(shots) > len(script_blocks) * 3:
        suggestions.append(
            {
                "level": "info",
                "category": "节奏断裂",
                "message": f"分镜数量（{len(shots)}）远多于剧本段落（{len(script_blocks)}），可能存在过度拆分",
                "action": "consolidate_shots",
                "subject": [],
            }
        )

    # 分镜总时长合理性
    total_duration = sum(float(s.get("duration") or 0) for s in shots)
    if shots and total_duration < len(script_chars) * 0.5:
        suggestions.append(
            {
                "level": "warning",
                "category": "节奏断裂",
                "message": f"分镜总时长 {total_duration:.1f}s 可能不足以承载剧本对话量",
                "action": "adjust_duration",
                "subject": [],
            }
        )

    # ── AI 增强检查（走 ai_engine，慢但准） ──
    ai_summary = ""
    try:
        from app.core.ai_engine import AIEngine

        engine = AIEngine()
        shots_text = "\n".join(
            f"  - {s.get('title', '未命名')}: [{s.get('shotSize', '')}] {s.get('prompt', '')[:60]}"
            for s in shots[:10]
        ) or "（无分镜）"
        msgs = [
            {
                "role": "system",
                "content": (
                    "你是资深剧本审查员。检查剧本与分镜表的一致性，输出 JSON 数组，每项格式："
                    '{"level":"warning|info|ok","category":"场景遗漏|角色冲突|节奏断裂|Prompt偏离",'
                    '"message":"具体描述","action":"建议操作"}。只输出 JSON，不要其他文字。'
                ),
            },
            {
                "role": "user",
                "content": (
                    f"【剧本】\n{script[:800]}\n\n【分镜表】\n{shots_text}\n\n"
                    "请检查一致性问题，只返回确实存在的问题，不要编造。"
                ),
            },
        ]
        full = ""
        for chunk in engine.chat_with_fallback(
            msgs,
            template=lambda: json.dumps([], ensure_ascii=False),
        ):
            full += chunk
        try:
            ai_items = json.loads(full.strip())
            if isinstance(ai_items, list):
                for item in ai_items:
                    if isinstance(item, dict) and item.get("message"):
                        suggestions.append(
                            {
                                "level": item.get("level", "info"),
                                "category": item.get("category", "AI 建议"),
                                "message": str(item["message"]),
                                "action": item.get("action", ""),
                                "subject": [],
                            }
                        )
                ai_summary = f"AI 审查发现 {len(ai_items)} 条建议"
        except json.JSONDecodeError:
            ai_summary = "AI 审查完成但未能解析结果"
    except Exception as e:
        logger.warning("[script_compliance_check] AI 增强跳过: %s", e)

    # ── SSE 推送到前端 AgentPanel ──
    summary = (
        f"合规守护：共 {len(suggestions)} 条建议"
        + (f"（{ai_summary}）" if ai_summary else "")
    )
    try:
        push_to_canvas(
            "compliance.report",
            {
                "suggestions": suggestions,
                "summary": summary,
                "ai_summary": ai_summary,
                "total_shots": len(shots),
                "total_characters": len(script_chars),
            },
        )
    except Exception as e:
        logger.warning("[script_compliance_check] SSE 推送失败: %s", e)

    return {
        "ok": True,
        "suggestions": suggestions,
        "summary": summary,
        "total_suggestions": len(suggestions),
    }


# ════════════════════════════════════════════════════════════════════
# 多轮 Agent 循环 + 控制台（Track B / D）
#   run_project_agent_loop  = 观察→规划→行动→观察 的 while 循环（复用 agent_loop）
#   get_agent_console       = 任务/大脑/会话/循环/记忆 聚合快照（供面板/前端）
# ════════════════════════════════════════════════════════════════════

def run_project_agent_loop(
    *,
    message: str,
    mode: str = "",
    session_id: str = "",
    provider: str = "",
    model: str = "",
    use_native_tools: bool = False,
) -> Dict[str, Any]:
    """多轮 Agent 循环入口（项目/画布侧）。

    与单轮 ``project_agent_chat`` 的区别：模型每轮选工具 → 执行 → 观察结果回流 →
    再决策，直到给出最终答复、预算耗尽、或协作模式下遇写工具待确认而暂停。

    执行器策略：画布前端 action（addNode/queryNodes…）走 SSE 派发，
    其余（editor.*/pipeline.* 等 capability）走 CapabilityDispatcher（含 policy）。
    """
    message = (message or "").strip()
    if not message:
        return {"ok": False, "message": "消息为空"}

    from app.core.agent_loop import agent_loop
    from app.core.agent_policy import normalize_mode
    from app.core.agent_action_registry import build_canvas_actions_list, build_clipskills_layers_block

    amode = normalize_mode(mode or "")
    sid = (session_id or "canvas_loop").strip() or "canvas_loop"

    # 工具清单（画布 action + 能力分层约束）进 system
    try:
        canvas_actions = build_canvas_actions_list()
    except Exception:
        canvas_actions = []
    tool_prompt = build_clipskills_layers_block()
    tool_prompt += (
        "\n[画布工具]\n"
        + json.dumps(
            [{"action": a["action"], "effect": a["effect"],
              "danger_level": a["danger_level"], "desc": a["description"]}
             for a in canvas_actions],
            ensure_ascii=False,
        )[:3000]
    )

    # canvas_tools 后端化（2026-09-15）：画布节点级 action（含别名）已注册为
    # canvas.* capability，统一走 dispatcher（经 ACTION_TO_CAPABILITY 映射）；
    # 仅 media_write 生成类（runGenerate/batchGenerate）仍走 SSE 桥（前端 onRequestGenerate）。
    from app.core.agent_action_registry import (
        ACTION_TO_CAPABILITY, canvas_generation_actions,
    )
    generation_actions = canvas_generation_actions()

    def executor(action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if action in generation_actions:
            from app.core.agent_runtime import dispatch_canvas_tools
            results = dispatch_canvas_tools(
                [{"action": action, "params": params}], mode=amode, session_id=sid,
            )
            if results:
                r = results[0]
                return {
                    "ok": bool(r.get("ok")),
                    "error": r.get("error") or "",
                    "payload": r.get("payload"),
                    "capability_id": action,
                }
            return {"ok": False, "error": "画布未回执", "capability_id": action}
        # 归一别名 → canonical capability_id，再统一走 dispatcher（节点级走 handler 桥接）
        cap = ACTION_TO_CAPABILITY.get(action, action)
        return agent_loop._make_dispatcher_executor(amode, sid)(cap, params)

    result = agent_loop.run(
        goal=message, mode=amode, session_id=sid,
        provider=provider, model=model,
        system_prompt="你是拾光剪影「导演台画布」助手（Agent-IM）。用简短中文；"
                      "需要改画布/时间线时输出工具调用，执行结果会喂回给你，多轮推进直到完成。",
        tool_prompt=tool_prompt,
        tool_executor=executor,
        use_native_tools=use_native_tools,
    )
    return {
        "ok": True,
        "result": result.to_dict(),
        "agent_mode": amode,
        "message": "多轮循环已结束" if result.reason == "done" else f"循环结束（{result.reason}）",
    }


def get_agent_console(
    *,
    session_id: str = "",
    task_id: str = "",
) -> Dict[str, Any]:
    """Agent 控制台状态快照（Track D 数据层，只读聚合）。"""
    from app.core.agent_console import collect_agent_status

    try:
        status = collect_agent_status(session_id=session_id, task_id=task_id)
        return {"ok": True, **status}
    except Exception as e:
        return {"ok": False, "message": f"控制台聚合失败: {e}"}

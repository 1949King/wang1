# -*- coding: utf-8 -*-
"""AgentLoop —— 多轮「观察 → 规划 → 行动 → 观察」执行循环（Track B / C）。

定位
----
把剪辑 Agent 从「单轮遥控器」升级成「多轮 Agent 应用」：此前一次模型回复 →
正则抽 JSON → 执行就结束，观察结果不回流、模型不会基于执行结果再决策。
本模块提供真正的 while 循环：模型选下一步 → 派发 → 拿回执 → 喂回模型 → 再决策，
直到模型给出最终答复、或预算耗尽、或用户停止/暂停。

设计原则（贴合项目特性）
------------------------
- **纯 core、UI 无关**：不 import PyQt；模型调用与工具执行都通过注入回调，
  便于无 LLM 的自包含回归测试（注入假的 model_fn / tool_executor）。
- **复用既有地基，不另起炉灶**：预算走 `agent_session`（12 轮 / 24 工具）、
  任务步骤走 `agent_task_store`、策略走 `agent_policy.decide`、大脑学习走
  `agent_brain.reinforce_path`。不做 ε 随机探索（拒绝随机效果）。
- **确认后执行**：协作模式下写工具不自动落地 —— 由 tool_executor 返回
  ``require_approval`` 时循环**立即停止**并回传已收集的规划 + 待确认清单，
  交由调用方（UI）确认后带 ``approved=True`` 再继续；Plan 模式只允许只读。
- **诚实失败**：工具失败如实记录进 step 与最终 result，不把「报错」包装成「成功」；
  模型无回复 / 预算耗尽 / 被停止，都给出可读 reason。
- **最小侵入**：本文件是新增模块，不修改既有单轮路径（`project_agent_chat` 等）。

工具协议
--------
tool_executor(action: str, params: dict) -> dict，返回：
    {"ok": bool, "message": str, "require_approval": bool, "skipped": bool,
     "capability_id": str, "payload": any}
``capability_id`` 用于把本次执行记入 executed_path（供 Hebbian 精确强化）。
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.core.agent_constants import ERR_WAITING_APPROVAL

logger = logging.getLogger(__name__)

# 预算默认值：与 agent_policy 对齐（不硬编码，运行期从 policy 取，这里仅兜底）
_DEFAULT_MAX_ROUNDS = 12
_DEFAULT_MAX_TOOLS = 24

_JSON_OBJ = re.compile(r"\{[\s\S]*\}")
_JSON_ARR = re.compile(r"\[[\s\S]*\]")


# ═══════════════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════════════

@dataclass
class LoopStep:
    """循环中的一次工具执行记录。"""
    round_no: int
    action: str
    params: Dict[str, Any] = field(default_factory=dict)
    ok: bool = False
    error: str = ""
    require_approval: bool = False
    skipped: bool = False
    capability_id: str = ""


@dataclass
class LoopResult:
    """一次 AgentLoop.run 的结果。"""
    session_id: str
    success: bool
    final_reply: str = ""          # 模型的最终答复（无工具时）
    steps: List[LoopStep] = field(default_factory=list)
    rounds: int = 0                # 实际消耗的模型轮次
    tool_calls: int = 0            # 实际消耗的工具调用次数
    pending_commands: List[Dict[str, Any]] = field(default_factory=list)  # 待确认的写指令
    reason: str = ""               # 结束原因（done / budget / stopped / approval / no_tools / error）
    executed_path: List[str] = field(default_factory=list)  # 实际执行经过的 capability 序列

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "success": self.success,
            "final_reply": self.final_reply,
            "rounds": self.rounds,
            "tool_calls": self.tool_calls,
            "steps": [
                {
                    "round": s.round_no,
                    "action": s.action,
                    "ok": s.ok,
                    "error": s.error,
                    "require_approval": s.require_approval,
                    "skipped": s.skipped,
                }
                for s in self.steps
            ],
            "pending_commands": self.pending_commands,
            "reason": self.reason,
            "executed_path": self.executed_path,
        }


# ═══════════════════════════════════════════════════════════════════
# 工具调用解析（兼容 JSON 指令数组 / commands / tools / canvas_tools）
# ═══════════════════════════════════════════════════════════════════

def _norm_tool(item: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(item, dict):
        return None
    action = str(item.get("action") or item.get("tool") or item.get("name") or "").strip()
    if not action:
        return None
    params = item.get("params") if isinstance(item.get("params"), dict) else {}
    # 把散在顶层、非结构键的字段并入 params（兼容 {action, clip_index:...} 写法）
    extra = {k: v for k, v in item.items() if k not in ("action", "tool", "name", "params", "reply", "reasoning")}
    merged = {**extra, **params}
    return {"action": action, "params": merged}


def parse_tool_calls(text: str) -> Tuple[str, List[Dict[str, Any]]]:
    """从模型回复里拆出 (中文回复, 工具调用列表)。

    兼容多种写法，解析失败则整体按最终答复返回（不误伤纯文本回答）：
      - {"commands":[{"action":...,"params":{...}}], "reply":"..."}
      - {"tools":[...]} / {"canvas_tools":[...]} / {"actions":[...]}
      - [{"action":...}, ...]   （裸数组）
      - {"action":..., "params":{...}}  （单对象工具调用）
      - {"tool_calls":[{"function":{"name":...,"arguments":"..."}}]}（原生 function calling）
      - 纯文本（无 JSON）→ 视为最终答复
    """
    raw = (text or "").strip()
    if not raw:
        return "", []

    # 定位最早出现的 JSON 片段（对象或数组），解析它
    candidates = []
    for pattern in (_JSON_OBJ, _JSON_ARR):
        m = pattern.search(raw)
        if m:
            candidates.append((m.start(), m.end(), m.group(0)))
    if not candidates:
        return raw, []
    candidates.sort(key=lambda x: x[0])
    start, end, snippet = candidates[0]

    try:
        blob = json.loads(snippet)
    except json.JSONDecodeError:
        return raw, []

    calls: List[Dict[str, Any]] = []
    if isinstance(blob, list):
        for item in blob:
            norm = _norm_tool(item)
            if norm:
                calls.append(norm)
    elif isinstance(blob, dict):
        # 原生 function calling 的 tool_calls 字段（Track C）
        native = blob.get("tool_calls")
        if isinstance(native, list):
            for tc in native:
                if not isinstance(tc, dict):
                    continue
                fn = tc.get("function") or tc
                action = str(fn.get("name") or fn.get("action") or "").strip()
                args = fn.get("arguments")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                if not isinstance(args, dict):
                    args = {}
                if action:
                    calls.append({"action": action, "params": args})
        if not calls:
            for key in ("commands", "tools", "canvas_tools", "actions"):
                arr = blob.get(key)
                if isinstance(arr, list):
                    for item in arr:
                        norm = _norm_tool(item)
                        if norm:
                            calls.append(norm)
        if not calls:
            # 对象本身就是一个工具调用（有 action/tool/name 键）
            norm = _norm_tool(blob)
            if norm:
                calls.append(norm)

    clean = (raw[:start] + raw[end:]).strip()
    reply = clean
    if isinstance(blob, dict) and blob.get("reply"):
        reply = str(blob.get("reply")).strip() or clean
    return (reply or raw), calls


# ═══════════════════════════════════════════════════════════════════
# 工具 schema（Track C：原生 function calling 用，可选）
# ═══════════════════════════════════════════════════════════════════

def build_tool_schemas(limit: int = 60) -> List[Dict[str, Any]]:
    """由能力目录派生 OpenAI 风格 function schema（供原生工具调用）。

    参数用宽松 schema（additionalProperties 允许任意键），因为能力目录只登记
    语义描述、未登记逐参数 JSON Schema —— 宁可让模型自由传参，也别写死错误签名。
    供 AgentLoop 在 ``use_native_tools=True`` 时注入，provider 不支持则回退 JSON。
    """
    try:
        from app.core.agent_capability_catalog import CAPABILITY_ROWS
    except Exception:
        return []
    schemas = []
    for cid, _cat, _eff, _paid, desc, _hemi, _label, _kw in CAPABILITY_ROWS:
        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": cid,
                    "description": desc,
                    "parameters": {"type": "object", "additionalProperties": True},
                },
            }
        )
    return schemas[:limit]


# ═══════════════════════════════════════════════════════════════════
# AgentLoop
# ═══════════════════════════════════════════════════════════════════

class AgentLoop:
    """多轮 Agent 执行循环（单例可选，但保持无状态可独立实例化）。"""

    def __init__(self) -> None:
        self._active: Dict[str, LoopResult] = {}

    def run(
        self,
        *,
        goal: str,
        mode: str = "collaborative",
        session_id: str = "",
        provider: str = "",
        model: str = "",
        system_prompt: str = "",
        tool_prompt: str = "",
        memory_context: str = "",
        tool_executor: Optional[Callable[[str, Dict[str, Any]], Dict[str, Any]]] = None,
        model_fn: Optional[Callable[[List[Dict[str, str]]], str]] = None,
        approve_fn: Optional[Callable[[List[Dict[str, Any]]], bool]] = None,
        history: Optional[List[Dict[str, str]]] = None,
        max_rounds: Optional[int] = None,
        max_tools: Optional[int] = None,
        use_native_tools: bool = False,
        on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> LoopResult:
        """执行多轮循环。

        Args:
            goal: 用户目标。
            mode: plan / collaborative / autonomous（normalize 后）。
            session_id: 会话 id（预算/停止/暂停挂靠 agent_session）。
            provider / model: 模型（model_fn 未注入时用 ai_engine）。
            system_prompt: 基础 system（不含模式块，模式块由本方法注入）。
            tool_prompt: 工具清单说明（追加进 system）。
            memory_context: 长期记忆注入文本。
            tool_executor: (action, params) -> result dict，见模块 docstring 协议。
            model_fn: (messages) -> 完整回复文本；不传则走 ai_engine。
            approve_fn: 写工具确认回调；协作模式写工具且未提供时，循环停止等待确认。
            history: 既有对话历史（user/assistant）。
            max_rounds / max_tools: 覆盖默认预算。
            use_native_tools: 尝试用原生 function calling（Track C），失败回退 JSON。
            on_progress: 进度回调（每轮/每工具），供 UI/SSE。

        Returns:
            LoopResult
        """
        from app.core.agent_context import compress_messages
        from app.core.agent_policy import (
            EFFECT_READ, MODE_PLAN, normalize_mode, mode_prompt_block, decide,
        )
        from app.core.agent_session import agent_sessions

        amode = normalize_mode(mode)
        session_id = (session_id or "agent_loop").strip() or "agent_loop"
        agent_sessions.set_mode(session_id, amode)
        max_rounds = max_rounds or _DEFAULT_MAX_ROUNDS
        max_tools = max_tools or _DEFAULT_MAX_TOOLS

        result = LoopResult(session_id=session_id, success=False)
        self._active[session_id] = result

        # 组装 system
        system = (system_prompt or "你是拾光剪影的 AI 剪辑助手，多轮观察时间线与画布、逐步完成任务。")
        system += mode_prompt_block(amode)
        if tool_prompt:
            system += "\n" + tool_prompt
        if memory_context:
            system += "\n" + memory_context
        system += (
            "\n[多轮执行] 每轮可输出要执行的工具调用（JSON），执行结果会喂回给你；"
            "任务完成或只需回答时，直接输出纯文本答复（不要 JSON）。"
        )

        messages: List[Dict[str, str]] = [{"role": "system", "content": system}]
        for m in (history or []):
            if isinstance(m, dict) and m.get("role") in ("user", "assistant"):
                messages.append({"role": m["role"], "content": str(m.get("content") or "")})
        messages.append({"role": "user", "content": (goal or "").strip()})

        model_call = model_fn or self._default_model_fn(provider, model, use_native_tools)
        executor = tool_executor or self._make_dispatcher_executor(amode, session_id)

        rounds = 0
        tools = 0
        while rounds < max_rounds:
            # ── 上下文压缩（V4.33.3）──
            # 轮内工具观测持续追加（每轮 2 条、每条约 400~600 字符），12 轮可累积到数十 KB，
            # 对窄窗口模型有撑爆风险。每轮开始前压一次：**只改「发给模型的窗口」**，
            # 不动 result.steps 里的原始记录（与 project_agent_host / editor_agent_panel 两条
            # 路径保持一致）；未超限时 compress_messages 直接返回原列表（开销仅一次字符统计），
            # 故逐轮调用无性能顾虑。
            # 预算按模型窗口自适应（V4.33.4）：大窗口模型自动放大，未命中模型时退回 12000。
            messages = compress_messages(messages, model=model, provider=provider)

            # 预算 / 停止 / 暂停
            ok_round, err_round = agent_sessions.begin_model_round(session_id)
            if not ok_round:
                result.reason = "stopped" if "停止" in err_round else (
                    "paused" if "暂停" in err_round else "budget")
                break
            rounds += 1

            if on_progress:
                on_progress({"round": rounds, "stage": "thinking", "session_id": session_id})

            try:
                reply = model_call(messages)
            except Exception as e:
                result.reason = "error"
                result.final_reply = f"模型调用失败: {e}"
                break

            text, calls = parse_tool_calls(reply)
            if not calls:
                # 无工具 → 最终答复
                result.success = True
                result.final_reply = text or reply
                result.reason = "done"
                break

            # 本轮有工具调用：逐条执行，观察结果回流
            for call in calls:
                if tools >= max_tools:
                    result.reason = "budget"
                    break
                action = str(call.get("action") or "")
                params = call.get("params") or {}
                ok_t, err_t = agent_sessions.begin_tool_call(session_id)
                if not ok_t:
                    result.reason = "stopped" if "停止" in err_t else "budget"
                    break
                tools += 1

                # Plan 模式：只允许只读
                decision = decide(tool_id=action, mode=amode)
                if amode == MODE_PLAN and decision.effect != EFFECT_READ:
                    step = LoopStep(round_no=rounds, action=action, params=params,
                                    ok=False, skipped=True, error="Plan 模式禁止非只读工具")
                    result.steps.append(step)
                    continue

                try:
                    r = executor(action, params) if executor else {"ok": False, "error": "无执行器"}
                except Exception as e:
                    r = {"ok": False, "error": str(e)}
                r = r if isinstance(r, dict) else {"ok": bool(r)}

                if r.get("require_approval"):
                    # 协作模式写工具待确认：收集并停止，回传给调用方
                    result.pending_commands.append(call)
                    step = LoopStep(round_no=rounds, action=action, params=params,
                                    ok=False, require_approval=True, error="等待用户确认")
                    result.steps.append(step)
                    result.reason = "approval"
                    result.rounds = rounds
                    result.tool_calls = tools
                    self._finalize(result, session_id,
                                   budget_used_ratio=tools / max(1, max_tools))
                    return result

                step = LoopStep(
                    round_no=rounds, action=action, params=params,
                    ok=bool(r.get("ok")), error=str(r.get("error") or r.get("message") or ""),
                    skipped=bool(r.get("skipped")),
                    capability_id=str(r.get("capability_id") or ""),
                )
                result.steps.append(step)
                if step.capability_id and step.capability_id not in result.executed_path:
                    result.executed_path.append(step.capability_id)

                # 观察结果回流成 assistant 消息，供下一轮决策
                obs = f"工具 {action} 执行{'成功' if step.ok else '失败'}。"
                if step.error:
                    obs += f" 结果: {step.error[:400]}"
                elif isinstance(r.get("payload"), dict):
                    obs += " 结果: " + json.dumps(r.get("payload"), ensure_ascii=False)[:600]
                messages.append({"role": "assistant", "content": json.dumps(
                    {"tool_call": action, "params": params}, ensure_ascii=False)})
                messages.append({"role": "user", "content": obs})

                if on_progress:
                    on_progress({"round": rounds, "stage": "act", "action": action,
                                 "ok": step.ok, "session_id": session_id})

            if result.reason == "budget":
                break

        # 收尾
        if result.reason in ("", "budget") and result.steps and not result.final_reply:
            # 预算耗尽但还有步骤：诚实标失败（没拿到最终答复）
            result.reason = "budget"
            result.final_reply = "已执行部分工具，但预算耗尽、未获最终答复。"
        if result.reason == "":
            result.reason = "no_tools"
        result.rounds = rounds
        result.tool_calls = tools
        self._finalize(result, session_id,
                       budget_used_ratio=tools / max(1, max_tools))
        return result

    # ─────────────── 内部 ───────────────

    def _default_model_fn(self, provider: str, model: str, use_native_tools: bool):
        """返回默认模型调用闭包：走 ai_engine，可选原生 tools。"""

        def _call(messages: List[Dict[str, str]]) -> str:
            from app.core.ai_engine import ai_engine

            kwargs: Dict[str, Any] = {"stream": False, "use_cache": False}
            if use_native_tools:
                # Track C：尝试注入原生 function schema；provider 不支持会抛错，
                # 下面捕获后回退到不带 tools 的 JSON 路径（最大兼容）。
                try:
                    schemas = build_tool_schemas()
                    if schemas:
                        kwargs["tools"] = schemas
                        kwargs["tool_choice"] = "auto"
                except Exception:
                    pass
            try:
                if provider:
                    chunks = list(ai_engine.chat(provider, messages, model=model or None, **kwargs))
                else:
                    chunks = list(ai_engine.chat_with_fallback(messages=messages, model=model or None, **kwargs))
            except Exception:
                # 原生 tools 不被支持 → 去掉 tools 重试（JSON 路径）
                kwargs.pop("tools", None)
                kwargs.pop("tool_choice", None)
                try:
                    if provider:
                        chunks = list(ai_engine.chat(provider, messages, model=model or None, **kwargs))
                    else:
                        chunks = list(ai_engine.chat_with_fallback(messages=messages, model=model or None, **kwargs))
                except Exception as e:
                    return f"错误: {e}"
            text = "".join(str(c) for c in chunks)
            if text.startswith("错误") or text.startswith("API 错误"):
                return ""  # 视为无有效输出，触发最终答复/重试
            return text

        return _call

    @staticmethod
    def _make_dispatcher_executor(mode: str, session_id: str):
        """构造默认执行器：走 capability_dispatcher，带策略上下文。

        - ``agent_mode`` + ``approved=False``：让 dispatcher 内的 policy 生效 ——
          协作模式下写工具返回 ``waiting_approval``（循环据此停止等待确认），
          自主模式下写工具自动执行；只读永远自动放行。
        """

        def _executor(action: str, params: Dict[str, Any]) -> Dict[str, Any]:
            from app.core.capability_dispatcher import capability_dispatcher, CapabilityRequest

            cap_id = action
            if not action.startswith((
                "editor.", "model.", "ext.", "workflow.", "account.",
                "pipeline.", "canvas.", "memory.",
            )):
                try:
                    from app.core.agent_action_registry import ACTION_TO_CAPABILITY
                    cap_id = ACTION_TO_CAPABILITY.get(action, action)
                except Exception:
                    cap_id = action
            res = capability_dispatcher.invoke(CapabilityRequest(
                capability_id=cap_id, params=params, caller="agent_loop",
                agent_mode=mode, session_id=session_id, approved=False,
            ))
            err = getattr(res, "error", None) or ""
            return {
                "ok": bool(getattr(res, "success", False)),
                "error": err,
                "capability_id": cap_id,
                "payload": getattr(res, "output", None),
                "require_approval": err == ERR_WAITING_APPROVAL,
            }

        return _executor

    def _finalize(self, result: LoopResult, session_id: str,
                  budget_used_ratio: float = 0.0) -> None:
        """收尾：写任务步骤 + 大脑强化（真实执行路径）+ 内心状态观察。"""
        try:
            from app.core.agent_brain import agent_brain
            path = [c for c in result.executed_path if c]
            if len(path) >= 2:
                agent_brain.reinforce_path(path, success=bool(result.success))
        except Exception as e:
            logger.debug(f"[AgentLoop] 大脑强化失败: {e}")
        # 内心状态（affect_model）：观察本次 run 的成败/调用密度/审批事件/重试压力。
        # 失败静默降级；冷启动（无历史）时所有门控 = 不干预，行为不变。
        try:
            from app.core.ai.affect_model import agent_affect
            failed_calls = sum(
                1 for s in result.steps
                if not s.ok and not s.skipped and not s.require_approval
            )
            actions = [s.action for s in result.steps if s.action]
            retry_like = len(actions) - len(set(actions))
            agent_affect.observe_run(
                success=bool(result.success),
                tool_calls=int(result.tool_calls),
                failed_calls=failed_calls,
                approval_events=len(result.pending_commands),
                retry_like=max(0, retry_like),
                budget_used_ratio=budget_used_ratio,
                max_budget=max(_DEFAULT_MAX_TOOLS, int(result.tool_calls) or 1),
            )
        except Exception as e:
            logger.debug(f"[AgentLoop] 内心状态观察失败: {e}")
        try:
            from app.modules.lego.core import EventBus, EventType
            EventBus.get_instance().emit(
                EventType.CUSTOM,
                {"subtype": "agent_loop_done", "session_id": session_id,
                 "result": result.to_dict()},
                source="AgentLoop",
            )
        except Exception as e:
            logger.debug(f"[AgentLoop] 广播完成事件失败: {e}")


agent_loop = AgentLoop()

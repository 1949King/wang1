"""
统一能力调用层 (CapabilityDispatcher)
==================================
Agent / UI / 外部入口访问三大模块的唯一通道。

设计原则：
  - 不替代三大模块，只做统一调度与 trace
  - 延迟导入 handlers，避免循环依赖
  - 每次 invoke 都写入 MemoryStore 并广播 EventBus
  - 同步 invoke 与异步 invoke_async 并存

架构位置：
  Agent → CapabilityDispatcher → 三大核心模块（剪辑/模型/拓展）+ 多任务调度
"""
from __future__ import annotations
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from app.core.agent_constants import ERR_WAITING_APPROVAL

# P1-3 取消异常：管线任务化后取消是控制流，dispatcher 的 catch-all 必须放行，
# 否则任务层看到的永远是「执行失败」而不是 cancelled。独立加载场景不可能出现取消，
# 空元组 except 子句永不匹配。
try:
    from app.core.canvas_gen_jobs import GenCancelled as _GenCancelled
except Exception:  # noqa: BLE001
    _GenCancelled = ()  # type: ignore[assignment]

logger = logging.getLogger(__name__)


class CapabilityCategory(str, Enum):
    """能力分类 —— 对应三大模块 + 多任务 + 全链路"""
    EDITOR = "editor"        # 剪辑模块
    MODEL = "model"          # 模型模块
    EXTENSION = "extension"  # 拓展模块
    WORKFLOW = "workflow"    # 多任务调度
    PIPELINE = "pipeline"    # Agent 全链路闭环
    CANVAS = "canvas"        # AI 画布


@dataclass
class CapabilityRequest:
    """能力调用请求"""
    capability_id: str                                # 形如 "editor.split_clip" / "ext.run_skill"
    params: Dict[str, Any] = field(default_factory=dict)
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    caller: str = "agent"                             # 调用源标记，便于 trace
    timeout: Optional[float] = None
    async_mode: bool = False
    agent_mode: str = ""                              # plan / collaborative / autonomous
    approved: bool = False                            # 协作模式用户已确认
    session_id: str = ""


@dataclass
class CapabilityResult:
    """能力调用结果"""
    request_id: str
    success: bool
    output: Any = None
    error: Optional[str] = None
    trace: List[str] = field(default_factory=list)
    duration_ms: float = 0.0
    capability_id: str = ""


@dataclass
class _HandlerEntry:
    """内部：handler 注册条目"""
    capability_id: str
    category: CapabilityCategory
    handler: Callable[[CapabilityRequest], CapabilityResult]
    description: str = ""
    schema: Dict[str, Any] = field(default_factory=dict)


class CapabilityDispatcher:
    """
    统一能力调度器 —— 单例

    使用方式：
        from app.core.capability_dispatcher import capability_dispatcher, CapabilityRequest
        result = capability_dispatcher.invoke(CapabilityRequest(
            capability_id="ext.run_skill",
            params={"skill_id": "account_data_collect", "inputs": {...}},
            caller="agent",
        ))
    """
    _instance: Optional['CapabilityDispatcher'] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._handlers: Dict[str, _HandlerEntry] = {}
        self._lock = threading.RLock()
        # 延迟引用，避免在 import 时拉起 lego 链
        self._event_bus = None
        self._memory = None
        self._builtin_registered = False

    @classmethod
    def get_instance(cls) -> 'CapabilityDispatcher':
        return cls()

    @property
    def event_bus(self):
        """延迟获取 EventBus 单例，避免循环导入"""
        if self._event_bus is None:
            from app.modules.lego.core import EventBus
            self._event_bus = EventBus.get_instance()
        return self._event_bus

    @property
    def memory(self):
        """延迟获取 MemoryStore 单例"""
        if self._memory is None:
            from app.core.memory_store import MemoryStore
            self._memory = MemoryStore.get_instance()
        return self._memory

    def register(self, capability_id: str, category: CapabilityCategory,
                 handler: Callable[[CapabilityRequest], CapabilityResult],
                 description: str = "", schema: Optional[Dict] = None) -> bool:
        """注册一个能力"""
        with self._lock:
            if capability_id in self._handlers:
                logger.warning(f"[CapabilityDispatcher] 重复注册: {capability_id}")
                return False
            self._handlers[capability_id] = _HandlerEntry(
                capability_id=capability_id, category=category,
                handler=handler, description=description, schema=schema or {},
            )
            return True

    def unregister(self, capability_id: str) -> bool:
        """注销一个能力"""
        with self._lock:
            return self._handlers.pop(capability_id, None) is not None

    def list_capabilities(self, category: Optional[CapabilityCategory] = None) -> List[Dict[str, Any]]:
        """列出所有已注册能力 —— 供 Agent 动态构建 system prompt"""
        with self._lock:
            entries = list(self._handlers.values())
        if category is not None:
            entries = [e for e in entries if e.category == category]
        return [{
            "capability_id": e.capability_id,
            "category": e.category.value,
            "description": e.description,
            "schema": e.schema,
        } for e in entries]

    def invoke(self, request: CapabilityRequest) -> CapabilityResult:
        """
        同步调用一个能力

        流程：
        1. 确保内置 handler 已注册
        2. emit CAPABILITY_INVOKED
        3. 执行 handler（捕获异常）
        4. 写 MemoryStore trace
        5. emit CAPABILITY_COMPLETED
        """
        self._ensure_builtin()
        start = time.time()
        entry = self._handlers.get(request.capability_id)

        if (request.agent_mode or "").strip() or request.caller in ("canvas", "project_agent"):
            try:
                from app.core.agent_policy import (
                    DECISION_DENY,
                    DECISION_REQUIRE_APPROVAL,
                    decide,
                    sanitize_for_log,
                )
                from app.core.agent_session import agent_sessions

                if request.session_id:
                    ok_b, err_b = agent_sessions.begin_tool_call(request.session_id)
                    if not ok_b:
                        return CapabilityResult(
                            request_id=request.request_id,
                            success=False,
                            error=err_b,
                            capability_id=request.capability_id,
                        )
                decision = decide(
                    tool_id=request.capability_id,
                    mode=request.agent_mode,
                    approved=request.approved,
                )
                if decision.action == DECISION_DENY:
                    return CapabilityResult(
                        request_id=request.request_id,
                        success=False,
                        error=decision.reason,
                        capability_id=request.capability_id,
                    )
                if decision.action == DECISION_REQUIRE_APPROVAL and not request.approved:
                    return CapabilityResult(
                        request_id=request.request_id,
                        success=False,
                        error=ERR_WAITING_APPROVAL,
                        output=sanitize_for_log(
                            {
                                "require_approval": True,
                                "tool_id": request.capability_id,
                                "reason": decision.reason,
                            }
                        ),
                        capability_id=request.capability_id,
                    )
            except Exception as e:
                # 策略链异常必须失败关闭：继续执行会让写能力绕过预算与审批。
                logger.exception("[CapabilityDispatcher] policy failed closed: %s", e)
                return CapabilityResult(
                    request_id=request.request_id,
                    success=False,
                    error=f"Agent 策略校验失败，已阻止执行: {e}",
                    capability_id=request.capability_id,
                )

        # 广播调用开始
        self._safe_emit(
            "CAPABILITY_INVOKED",
            {"request_id": request.request_id, "capability_id": request.capability_id,
             "caller": request.caller, "params_keys": list(request.params.keys())},
            source="CapabilityDispatcher",
        )

        if entry is None:
            result = CapabilityResult(
                request_id=request.request_id, success=False,
                error=f"未知能力: {request.capability_id}",
                capability_id=request.capability_id,
            )
        else:
            try:
                # B1 撤销反馈回路：能力链执行期间标记「Agent 来源」——
                # handler 内部落到编辑器撤销栈的动作会盖上 origin=agent 章，
                # 用户事后 Ctrl+Z 即触发 AgentBrain 负反馈。线程局部，零签名改动。
                from app.core.agent_origin import agent_origin_scope
                with agent_origin_scope():
                    result = entry.handler(request)
                result.capability_id = request.capability_id
                result.request_id = request.request_id
            except _GenCancelled:
                # P1-3：取消是控制流不是执行失败——放行给任务层标记 cancelled，
                # 不写 trace/不广播 CAPABILITY_COMPLETED（被中止的调用没有结果语义）。
                raise
            except Exception as e:
                logger.exception(f"[CapabilityDispatcher] {request.capability_id} 执行异常")
                result = CapabilityResult(
                    request_id=request.request_id, success=False, error=str(e),
                    capability_id=request.capability_id,
                )

        result.duration_ms = (time.time() - start) * 1000

        # 左右脑神经链接：每次调用都激活对应神经元（此前 activate() 定义了但从无调用方，
        # 导致 AgentBrain 的"活跃神经元"永远是 0，联想扩散也从未真正发生过）
        try:
            from app.core.agent_brain import agent_brain
            agent_brain.activate(
                request.capability_id,
                {"caller": request.caller, "success": result.success},
                strength=1.0 if result.success else 0.6,
            )
        except Exception as e:
            logger.debug(f"[CapabilityDispatcher] AgentBrain 激活失败: {e}")

        # 写记忆 trace（失败更值得回忆，score 更高）
        try:
            self.memory.record(
                category="execution_trace",
                content={
                    "capability_id": request.capability_id,
                    "caller": request.caller,
                    "success": result.success,
                    "duration_ms": round(result.duration_ms, 2),
                    "error": result.error,
                    "params_summary": self._summarize_params(request.params),
                },
                tags=[request.capability_id.split(".")[0], "trace"],
                score=0.5 if result.success else 0.8,
            )
        except Exception as e:
            logger.debug(f"[CapabilityDispatcher] 写记忆失败: {e}")

        # 广播调用完成
        self._safe_emit(
            "CAPABILITY_COMPLETED",
            {"request_id": request.request_id, "capability_id": request.capability_id,
             "success": result.success, "duration_ms": round(result.duration_ms, 2),
             "error": result.error},
            source="CapabilityDispatcher",
        )
        return result

    def invoke_async(self, request: CapabilityRequest,
                     callback: Optional[Callable[[CapabilityResult], None]] = None) -> str:
        """
        异步调用 —— 后台线程执行，完成后回调

        返回 request_id，调用方可通过 EventBus 监听 CAPABILITY_COMPLETED
        """
        def _runner():
            result = self.invoke(request)
            if callback:
                try:
                    callback(result)
                except Exception:
                    logger.exception("[CapabilityDispatcher] async callback 异常")

        t = threading.Thread(target=_runner, daemon=True,
                             name=f"cap_{request.capability_id}")
        t.start()
        return request.request_id

    def _ensure_builtin(self):
        """首次调用时注册内置能力（延迟到 EventBus/MemoryStore 就绪后）"""
        if self._builtin_registered:
            return
        with self._lock:
            if self._builtin_registered:
                return
            try:
                from app.core.capability_handlers import register_builtin_handlers
                register_builtin_handlers(self)
                self._builtin_registered = True
                logger.info("[CapabilityDispatcher] 内置 handler 已注册")
            except Exception as e:
                logger.warning(f"[CapabilityDispatcher] 注册内置 handler 失败: {e}")
                self._builtin_registered = True  # 避免重复尝试

    def _safe_emit(self, event_name: str, data: Dict[str, Any], source: str = ""):
        """安全广播事件，EventBus 不可用时静默跳过"""
        try:
            from app.modules.lego.core import EventType
            evt = getattr(EventType, event_name, None)
            if evt is not None:
                self.event_bus.emit(evt, data, source=source)
        except Exception as e:
            logger.debug(f"[CapabilityDispatcher] emit {event_name} 失败: {e}")

    @staticmethod
    def _summarize_params(params: Dict[str, Any], max_len: int = 200) -> str:
        """参数摘要，避免记忆过大"""
        try:
            from app.core.agent_policy import sanitize_for_log

            s = str(sanitize_for_log(params))
        except Exception:
            s = str(params)
        return s if len(s) <= max_len else s[:max_len] + "..."


# 全局单例便捷引用
capability_dispatcher = CapabilityDispatcher.get_instance()


def get_capability_dispatcher() -> CapabilityDispatcher:
    return capability_dispatcher

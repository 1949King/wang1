"""Agent 来源标记：区分「Agent/自动化能力链干的」与「用户手动干的」编辑操作。

B1 撤销反馈回路的基础设施：
- capability_dispatcher.invoke 执行 handler 前进入 agent_origin_scope()
- EditorModule._record_action 依据 is_agent_origin() 给撤销栈动作盖 origin 章
- 用户 Ctrl+Z 撤销 origin=agent 的动作 → 触发 AgentBrain Hebbian 负反馈

线程局部（threading.local）而非实例标志：
Agent 能力即使跑在工作线程、与主线程用户操作并发，来源判定也互不污染。

本模块不 import 任何 app 包成员，可独立加载/单测。
"""

import threading
from contextlib import contextmanager

_TLS = threading.local()


def is_agent_origin() -> bool:
    """当前线程是否正处于 Agent 能力执行链内。"""
    return bool(getattr(_TLS, "active", False))


@contextmanager
def agent_origin_scope():
    """进入 Agent 来源作用域（可嵌套，退出时恢复外层状态）。"""
    prev = bool(getattr(_TLS, "active", False))
    _TLS.active = True
    try:
        yield
    finally:
        _TLS.active = prev

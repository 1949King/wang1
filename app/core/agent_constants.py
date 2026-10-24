# -*- coding: utf-8 -*-
"""Agent 跨模块共享常量 —— 消除「字符串协议」静默失效风险。

为什么需要这个文件
--------------------
此前 ``waiting_approval`` 这个字符串被硬编码在 **4 个文件、8 处**，由不同模块
各自「约定」其含义：

  1. ``capability_dispatcher.py`` —— **产出方**：策略判定需确认时写入 ``error``
  2. ``agent_loop._make_dispatcher_executor`` —— **消费方**：比对 ``err == "waiting_approval"``
     决定 ``require_approval`` 是否置位
  3. ``agent_runtime.py`` —— 任务步进状态
  4. ``agent_task_store.py`` —— 状态机合法迁移表

危险在于 1 与 2 之间只靠字面量握手：**dispatcher 端改一次文案（如改为
"awaiting_approval"），消费方的比对永远为 False**，表现为——协作模式下写操作
被当成「普通失败」而非「待确认」，审批流静默失效，且没有任何报错。

收敛后：产出方与消费方共用 ``STATUS_WAITING_APPROVAL``，改一处即全局生效；
若有人再写裸字符串，``_verify`` 下的回归脚本可检出。

命名说明
--------
- ``STATUS_*``：**任务/步进状态**（进入 ``agent_task_store._LEGAL`` 状态机）
- ``ERR_*``    ：**错误标识**（走 ``CapabilityResult.error`` 通道）
两者当前取值相同，但语义域不同，故分别定义，避免将来一处变更误伤另一处。
"""
from __future__ import annotations

# ═══════════════════════════════════════════════════════════════════
# 待确认状态 / 错误标识
# ═══════════════════════════════════════════════════════════════════

#: 任务/步进状态：等待用户确认（进入状态机）
STATUS_WAITING_APPROVAL = "waiting_approval"

#: 错误标识：策略要求确认，本次调用未执行
#: 产出方 capability_dispatcher，消费方 agent_loop
ERR_WAITING_APPROVAL = "waiting_approval"

# ═══════════════════════════════════════════════════════════════════
# 其余任务状态（供状态机与展示层引用，避免再散落字面量）
# ═══════════════════════════════════════════════════════════════════

STATUS_QUEUED = "queued"
STATUS_PLANNING = "planning"
STATUS_RUNNING = "running"
STATUS_PAUSED = "paused"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_STOPPED = "stopped"

#: 所有合法状态（状态机校验用）
ALL_TASK_STATUSES = frozenset({
    STATUS_QUEUED,
    STATUS_PLANNING,
    STATUS_RUNNING,
    STATUS_WAITING_APPROVAL,
    STATUS_PAUSED,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_STOPPED,
})

__all__ = [
    "STATUS_WAITING_APPROVAL",
    "ERR_WAITING_APPROVAL",
    "STATUS_QUEUED",
    "STATUS_PLANNING",
    "STATUS_RUNNING",
    "STATUS_PAUSED",
    "STATUS_COMPLETED",
    "STATUS_FAILED",
    "STATUS_STOPPED",
    "ALL_TASK_STATUSES",
]

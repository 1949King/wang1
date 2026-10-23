# -*- coding: utf-8 -*-
"""执行层专项决策器的 Agent 能力处理器（画布 / 剪辑 / 流水线智能体共用）。

用户指令（2026-10-23）：「前面加一个专项执行层模型，让它决定怎么调度本地与 API 之间的
运算逻辑和方式；也要能加进画布模块和剪辑模块的智能体。」

设计边界：
  · 本文件**只做能力壳**（薄委托），决策逻辑全在 `app/core/ai/execution_planner.py`。
  · 这样做是因为 `capability_handlers.py` 已 1,997 行（规模硬线 2,000）——
    新能力在此注册，那里只留 2 行委托，不破守卫。
  · 能力**只读**（effect=read）：`execution.plan` 给计划、`execution.status` 给快照；
    真正执行仍由既有生成能力（canvas.generate_image / pipeline.generate …）负责。
    ⇒ 不会让 Agent 通过本层「顺手」触发付费生成，也不改变任何既有计费语义。
"""
from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class ExecutionPlannerHandlers:
    """执行层决策能力（薄壳）。"""

    def plan(self, req) -> Any:
        """`execution.plan`：本次该走本地 / 云端 / 混合，返回可解释计划（只读，不执行）。"""
        from app.core.capability_handlers import CapabilityResult
        from app.core.ai.execution_planner import plan

        p: Dict[str, Any] = dict(getattr(req, "params", None) or {})
        try:
            res = plan(
                capability=str(p.get("capability") or "image"),
                has_reference=bool(p.get("has_reference") or p.get("reference_image")
                                   or p.get("first_frame")),
                explicit_channel=str(p.get("channel_id") or p.get("channel") or ""),
                urgency=str(p.get("urgency") or ""),
            )
        except Exception as e:  # 决策层不外抛（R3）：如实返回失败
            logger.debug("[execution_planner_handlers] plan 失败", exc_info=True)
            return CapabilityResult(req.request_id, False, error=f"执行层裁定失败: {e}")
        # 只读能力恒成功：ok=False 表示「本层不裁定该能力」，仍是合法查询结果
        return CapabilityResult(req.request_id, True, output=res)

    def status(self, req) -> Any:
        """`execution.status`：本地引擎 / 硬件档 / 预算 λ / 云端可用性快照（只读）。"""
        from app.core.capability_handlers import CapabilityResult
        from app.core.ai.execution_planner import status

        try:
            res = status()
        except Exception as e:
            logger.debug("[execution_planner_handlers] status 失败", exc_info=True)
            return CapabilityResult(req.request_id, False, error=f"执行层快照失败: {e}")
        return CapabilityResult(req.request_id, True, output=res)


def register_execution_capabilities(dispatcher) -> None:
    """把执行层决策能力注册进 dispatcher（由 register_builtin_handlers 末尾委托调用）。"""
    from app.core.capability_dispatcher import CapabilityCategory

    h = ExecutionPlannerHandlers()
    dispatcher.register(
        "execution.plan", CapabilityCategory.PIPELINE, h.plan,
        "执行层裁定：本次走本地引擎还是云端 API、混合顺序与理由（只读，不执行生成）")
    dispatcher.register(
        "execution.status", CapabilityCategory.PIPELINE, h.status,
        "执行层快照：本地引擎/硬件档/预算 λ/云端渠道可用性（只读）")

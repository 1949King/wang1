# -*- coding: utf-8 -*-
"""审美治理闸门能力（2026-10-20 · 治理线）

只读薄壳：`pipeline.aesthetic_gate` = 五维评分结果 → pass/review/block。
不写时间线、不改生成参数；接入 S3→S4 写闸门是下一刀（任务清单 E2）。
"""
from __future__ import annotations

from typing import Any, Dict

try:
    from app.core.aesthetic_gate import evaluate_batch, evaluate_gate
    from app.core.capability_dispatcher import (
        CapabilityCategory,
        CapabilityRequest,
        CapabilityResult,
    )
except ImportError:  # 兼容 `core.*` 旧导入路径
    from core.aesthetic_gate import evaluate_batch, evaluate_gate  # type: ignore
    from core.capability_dispatcher import (  # type: ignore
        CapabilityCategory,
        CapabilityRequest,
        CapabilityResult,
    )


class GateCapabilityHandlers:
    """治理闸门：评分 → 判定（纯函数委托）。"""

    def aesthetic_gate(self, req: CapabilityRequest) -> CapabilityResult:
        params: Dict[str, Any] = req.params or {}
        policy = params.get("policy") if isinstance(params.get("policy"), dict) else None
        items = params.get("items")
        item = params.get("item")
        if items is None and item is None:
            return CapabilityResult(
                req.request_id, False,
                error="需要 item（单条评分）或 items（评分数组）",
            )
        if items is not None:
            if not isinstance(items, list) or not items:
                return CapabilityResult(
                    req.request_id, False, error="items 必须是非空数组"
                )
            return CapabilityResult(
                req.request_id, True, output=evaluate_batch(items, policy), error=None
            )
        if not isinstance(item, dict):
            return CapabilityResult(
                req.request_id, False, error=f"item 必须是对象，收到 {type(item).__name__}"
            )
        return CapabilityResult(
            req.request_id, True, output=evaluate_gate(item, policy), error=None
        )


def register_gate_handlers(dispatcher) -> None:
    handlers = GateCapabilityHandlers()
    dispatcher.register(
        "pipeline.aesthetic_gate", CapabilityCategory.PIPELINE,
        handlers.aesthetic_gate,
        "审美治理闸门：五维评分 → pass/review/block（估算维度默认复核，不假通过）",
    )

# -*- coding: utf-8 -*-
"""画布桥 · 执行层端点（V4.46.5 · 2026-10-23）

`GET  /host/execution-status` —— 执行层快照：算力档位、本地引擎、硬件档、λ、云端可用性。
`POST /host/execution-bias`   —— 设置混合算力偏好（0=纯本地 … 50=动态混合 … 100=纯云端）。
`GET  /host/execution-plan`   —— 只读试算：给某个能力出一份调度计划（不执行生成）。

为什么单开 mixin：`canvas_routes_post.py` 已 1,982/2,000 行，按 dub/roughcut/digital_human
先例外开，避免撞规模守卫。

身份：档位是**用户偏好**（存 data/compute_bias.json），不是密钥，不需要 host token 之外的
额外校验；但读接口仍过 `_check_host_token`，与既有 /host/* 一致。
"""
from __future__ import annotations

import json
import logging

from app.core.canvas_route_registry import _route_get, _route_post

logger = logging.getLogger(__name__)


def _cs():
    """延迟取 canvas_server 模块（顶层导入会循环：canvas_server 要继承本 mixin）。"""
    from app.core import canvas_server

    return canvas_server


class CanvasExecutionRoutesMixin:
    """执行层（混合算力）端点集合（由 `_BridgeHandler` 继承）。"""

    @_route_get("/host/execution-status")
    def _g_host_execution_status(self, parsed) -> None:
        cs = _cs()
        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            from app.core.ai.execution_planner import status

            self._json(200, {"ok": True, **status()})
        except Exception as e:
            logger.debug("[/host/execution-status] 失败", exc_info=True)
            self._json(500, {"ok": False, "message": f"执行层状态读取失败: {e}"})

    @_route_post("/host/execution-bias")
    def _p_host_execution_bias(self, parsed, raw: bytes, ctype: str) -> None:
        cs = _cs()
        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"ok": False, "message": "invalid json"})
            return
        try:
            from app.core.ai.compute_bias import get_bias
            from app.core.ai.quality_gate import get_gate

            b = get_bias()
            g = get_gate()
            if "quality" in body:
                # 质量总闸（draft/standard/fine/cinema）与算力偏好并列
                if not g.set(body.get("quality")):
                    self._json(400, {"ok": False,
                                     "message": "quality 必须是 draft/standard/fine/cinema"})
                    return
            if "bias" not in body:
                # 只读回显：便于前端打开面板时同步当前值
                self._json(200, {"ok": True, **b.status(), **g.status()})
                return
            ok = b.set(int(body.get("bias")))
            if not ok:
                self._json(400, {"ok": False, "message": "bias 必须是 0-100 的整数"})
                return
            self._json(200, {"ok": True, **b.status(), **g.status()})
        except Exception as e:
            logger.debug("[/host/execution-bias] 失败", exc_info=True)
            self._json(500, {"ok": False, "message": f"算力偏好设置失败: {e}"})

    @_route_get("/host/engines")
    def _g_host_engines(self, parsed) -> None:
        """引擎注册表快照（W1）：族/角色/健康/用量，供画布与排障面板消费。"""
        cs = _cs()
        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            from app.core.engine_registry import status

            self._json(200, {"ok": True, **status()})
        except Exception as e:
            logger.debug("[/host/engines] 失败", exc_info=True)
            self._json(500, {"ok": False, "message": f"引擎注册表读取失败: {e}"})

    @_route_get("/host/execution-plan")
    def _g_host_execution_plan(self, parsed) -> None:
        cs = _cs()
        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            from urllib.parse import parse_qs

            from app.core.ai.execution_planner import plan

            qs = parse_qs(parsed.query)
            cap = (qs.get("capability") or ["image"])[0]
            has_ref = (qs.get("has_reference") or [""])[0] in ("1", "true", "True")
            self._json(200, {"ok": True, "plan": plan(
                capability=cap, has_reference=has_ref,
                quality=(qs.get("quality") or [""])[0],
                explicit_channel=(qs.get("channel_id") or [""])[0])})
        except Exception as e:
            logger.debug("[/host/execution-plan] 失败", exc_info=True)
            self._json(500, {"ok": False, "message": f"执行层试算失败: {e}"})

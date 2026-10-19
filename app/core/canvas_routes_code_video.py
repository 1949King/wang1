# -*- coding: utf-8 -*-
"""画布桥 · codeVideo 渲染路由（V4.46 · 2026-10-20）

两条端点：
- `POST /host/code-video/render`：body = {spec?|storyboard?, output_name?, qc?}；
  立即返回 job_id（渲染在后台线程，进度走 SSE `code_video.*`）。
- `GET  /host/code-video/status?job_id=`：任务状态/结果查询。

与 `canvas_routes_roughcut.py` 同构：单独 mixin，由 `_BridgeHandler` 继承；
鉴权沿用 `_check_host_token`（与 /host/* 一致）。
"""
from __future__ import annotations

import json
import logging

from app.core.canvas_route_registry import _route_get, _route_post

logger = logging.getLogger(__name__)


def _cs():
    from app.core import canvas_server

    return canvas_server


class CanvasCodeVideoRoutesMixin:
    """codeVideo 渲染任务端点。"""

    @_route_post("/host/code-video/render")
    def _p_host_code_video_render(self, parsed, raw: bytes, ctype: str) -> None:
        cs = _cs()
        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"ok": False, "message": "invalid json"})
            return
        if not isinstance(body, dict):
            self._json(400, {"ok": False, "message": "body 必须是对象"})
            return
        from app.core.canvas_code_video_jobs import start_job

        job = start_job(body)
        self._json(200, {"ok": True, "job": job})
        return

    @_route_get("/host/code-video/status")
    def _route_host_code_video_status(self, parsed=None) -> None:
        cs = _cs()
        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        from urllib.parse import parse_qs

        qs = parse_qs(parsed.query) if parsed is not None else {}
        job_id = (qs.get("job_id") or [""])[0].strip()
        if not job_id:
            self._json(400, {"ok": False, "message": "缺少 job_id"})
            return
        from app.core.canvas_code_video_jobs import get_job

        job = get_job(job_id)
        if job is None:
            self._json(404, {"ok": False, "message": "任务不存在或已过期"})
            return
        self._json(200, {"ok": True, "job": job})
        return

# -*- coding: utf-8 -*-
"""画布桥 · 图片转3D / 全景生成路由（2026-11-20，四项优化 T5）

为什么单开一个 mixin
====================
`canvas_routes_post.py` 已逼近 `_verify/check_file_size.py` 的 2000 行阈值，
照「桥函数另开文件」的既有纪律（dub / roughcut / digital_human / execution 先例），
把 T5 场景3D 端点独立成 `CanvasScene3dRoutesMixin`
（与 canvas_routes_get / canvas_routes_post 同构，由 canvas_server._BridgeHandler 继承）。
handler 函数体与迁出前**逐行等价**（含注释、响应码、错误分支），本次不顺手改逻辑。

两条端点与分工
==============
- `POST /host/generate-panorama`：可选网关 H3 全景生成（**默认关**）。薄路由，
  token + json 校验后调 `gateway_scene3d.generate_panorama`；渠道未启用 ⇒
  ok:false + guidance（绝不触网）；成功返回等距柱状全景 data URL，前端喂现有
  PanoramaViewer3D 真 3D 环视。署名 MiniMax H3（社区许可，见 license/third_party）。
- `POST /host/image-to-3d`：单图深度重建 2.5D GLB 网格（**异步任务**）。
  深度估计/网格重建/导出在 canvas_gen_jobs worker 线程执行，HTTP 立即返回 job_id，
  前端经 /host/generation/status 轮询。深度模型缺失诚实 ok:false + guidance
  （绝不触网、绝不自动下载权重）；产物诚实标 2.5D 网格（非真体积/高斯泼溅）。
"""
from __future__ import annotations

import json
import logging

from app.core.canvas_route_registry import _route_post

logger = logging.getLogger(__name__)


def _cs():
    """延迟取 canvas_server 模块（顶层导入会循环：canvas_server 要继承本 mixin）。"""
    from app.core import canvas_server

    return canvas_server


class CanvasScene3dRoutesMixin:
    """T5 场景3D 端点 handler 集合（由 `_BridgeHandler` 继承）。"""

    @_route_post("/host/generate-panorama")
    def _p_host_generate_panorama(self, parsed, raw: bytes, ctype: str) -> None:
        """T5 全景生成（可选网关 H3，默认关）：薄路由，token+json+调 gateway_scene3d。

        渠道未启用 ⇒ ok:false+guidance；成功返回等距柱状全景 data URL，
        前端喂现有 PanoramaViewer3D 真 3D 环视。署名 MiniMax H3（社区许可）。
        """
        cs = _cs()

        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"ok": False, "message": "invalid json"})
            return
        try:
            from app.core.ai.gateway_scene3d import generate_panorama

            res = generate_panorama(
                prompt=str(data.get("prompt") or ""),
                image=str(data.get("image") or ""),
                model=str(data.get("model") or ""),
                channel_id=str(data.get("channel_id") or ""),
            )
        except Exception as e:
            logger.exception("[/host/generate-panorama] 失败")
            self._json(500, {"ok": False, "message": str(e)})
            return
        code = 200 if res.get("ok") else 400
        self._json(code, res)
        return

    # ── POST /host/image-to-3d：单图深度重建 2.5D GLB 网格（异步任务，T5）──
    # 2026-11-20 T5 项四：深度估计/网格重建/导出在 canvas_gen_jobs worker 线程执行，
    # HTTP 立即返回 job_id；前端经 /host/generation/status 轮询。
    # 深度模型缺失诚实 ok:false+guidance（绝不触网）；产物诚实标 2.5D 网格。
    @_route_post("/host/image-to-3d")
    def _p_host_image_to_3d(self, parsed, raw: bytes, ctype: str) -> None:
        cs = _cs()

        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"ok": False, "message": "invalid json"})
            return
        from app.core import canvas_gen_jobs
        from app.core.image_to_3d import parse_image_to_3d_request, run_image_to_3d

        req = parse_image_to_3d_request(body)
        if not req.get("ok"):
            self._json(400, {"ok": False, "message": req.get("error", "请求无效")})
            return
        job = canvas_gen_jobs.submit(
            "image",
            lambda report: run_image_to_3d(req, report),
            label="图片转3D（深度重建）",
            meta={"kind_detail": "image-to-3d", "fov": req["fov"]},
        )
        self._json(200, {"ok": True, "job_id": job["job_id"], "status": job["status"]})
        return

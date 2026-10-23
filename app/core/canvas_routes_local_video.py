# -*- coding: utf-8 -*-
"""画布桥 · 本地视频端点（V4.46.6 · 2026-10-24）

`POST /host/local-video-generate` —— **本机** diffusers 视频生成（SVD 图生视频）。

为什么外开 mixin：`canvas_routes_post.py` 已顶 2,000 行规模守卫（按 dub/roughcut/
digital_human 先例外开）。路由注册方式与既有 mixin 完全一致（`@_route_post`）。

首帧输入链路（2026-10-24 修）：画布节点的首帧常是 `/inbox_file/<name>`（图片节点产物
落画布 inbox 后就是这个 URL），此前只认 data URL ⇒ 本地 SVD 永远拿不到图。
现统一走 `local_video_infer.resolve_image_path`：data URL / inbox URL / 本地路径三态通吃。
"""
from __future__ import annotations

import json
import logging
import os

from app.core.canvas_route_registry import _route_post

logger = logging.getLogger(__name__)


def _cs():
    from app.core import canvas_server

    return canvas_server


class CanvasLocalVideoRoutesMixin:
    """本地视频生成端点（由 `_BridgeHandler` 继承）。"""

    @_route_post("/host/local-video-generate")
    def _p_host_local_video_generate(self, parsed, raw: bytes, ctype: str) -> None:
        cs = _cs()
        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"ok": False, "message": "invalid json"})
            return

        action = str(body.get("action") or "generate").strip().lower()
        try:
            from app.core.neural import video_gen as vg
        except Exception as e:
            self._json(500, {"ok": False, "message": f"视频模块加载失败: {e}"})
            return

        model_id = str(body.get("model_id") or "svd-xt-i2v").strip()

        # ── models：只读列出可选模型（含实测体积/显存/内存需求）──
        if action == "models":
            self._json(200, {
                "ok": True,
                "models": vg.available_models(),
                "available": vg.VideoGenEngine.is_available(),
                "unavailable_reason": vg.VideoGenEngine.unavailable_reason(),
                "downloaded": [m["id"] for m in vg.available_models()
                               if vg.VideoGenEngine.is_downloaded(m["id"])],
            })
            return

        # ── pull：下载模型（长耗时；前端应轮询或接受长请求）──
        if action == "pull":
            res = vg.get_video_engine().pull(model_id)
            logger.info("[/host/local-video-generate] pull %s ok=%s", model_id, res.get("ok"))
            self._json(200 if res.get("ok") else 400, res)
            return

        # ── generate：生成视频 ──
        image_path = str(body.get("image_path") or "").strip()
        image_data = str(
            body.get("image")
            or body.get("image_url")
            or body.get("first_frame")
            or body.get("reference_image")
            or ""
        ).strip()
        if not image_path and image_data:
            try:
                from app.core.local_video_infer import resolve_image_path

                image_path = resolve_image_path(
                    image_data,
                    dest_dir=os.path.join("短剧AI剪辑输出", "_video_input"),
                    name_hint="canvas",
                ) or ""
            except Exception:
                logger.debug("[/host/local-video-generate] 首帧解析失败", exc_info=True)
                image_path = ""
            if not image_path:
                self._json(400, {
                    "ok": False,
                    "message": "首帧图无法解析：支持 data URL / 本地路径 / /inbox_file/ URL（SVD 是图生视频）",
                })
                return
        if not image_path:
            self._json(400, {"ok": False,
                             "message": "需要首帧图（image / image_url / first_frame / image_path 任一，SVD 是图生视频）"})
            return
        try:
            res = vg.get_video_engine().generate(
                model_id,
                prompt=str(body.get("prompt") or ""),
                image_path=image_path,
                seconds=float(body.get("seconds") or 1.5),
                fps=int(body.get("fps") or 7),
                seed=int(body.get("seed") or 0),
                out_path=str(body.get("out_path") or ""),
            )
        except Exception as e:
            logger.exception("[/host/local-video-generate] 失败")
            self._json(500, {"ok": False, "message": str(e)})
            return
        logger.info("[/host/local-video-generate] generate %s ok=%s", model_id, res.get("ok"))
        self._json(200 if res.get("ok") else 400, res)
        return

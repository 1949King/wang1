# -*- coding: utf-8 -*-
"""画布桥 · 数字人「口型成片」端点（V4.46.4 · 2026-10-22）

`POST /host/digital-human/talking-video`
  body = {image: <dataURL | /inbox_file/… | inbox 裸文件名>,
          audio: <同上>, name?: str}
  → 静态形象 + 配音 合成 mp4 落 inbox，返回可播放 URL。

诚实契约（红线）：
  * 产物**必须**带 `mouth_moved: False` —— 这是"能出片"与"口型同步"的边界，
    绝不用静帧视频冒充对口型成片；
  * 输入不齐 / ffmpeg 缺失 → ok=False + 缺什么（missing）+ 引擎说明（lipsync_note），
    不产出半成品；
  * 媒体引用只接受 inbox 文件 / data URL（**拒绝任意绝对路径**，防本机任意文件读取）。

与 canvas_routes_roughcut.py 同构：单独 mixin（canvas_routes_post.py 已 1,967/2,000 行）。
"""
from __future__ import annotations

import json
import logging
import os
import time

from app.core.canvas_route_registry import _route_post

logger = logging.getLogger(__name__)


def _cs():
    """延迟取 canvas_server 模块（顶层导入会循环：canvas_server 要继承本 mixin）。"""
    from app.core import canvas_server

    return canvas_server


class CanvasDigitalHumanRoutesMixin:
    """数字人成片端点集合（由 `_BridgeHandler` 继承）。"""

    @_route_post("/host/digital-human/talking-video")
    def _p_host_digital_human_talking(self, parsed, raw: bytes, ctype: str) -> None:
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

        from app.core.digital_human_talking import (
            make_talking_video, resolve_media_ref,
        )

        inbox = cs.canvas_inbox_dir()
        image_local, err_i = resolve_media_ref(
            str(body.get("image") or ""), inbox, prefix="dh_img_")
        audio_local, err_a = resolve_media_ref(
            str(body.get("audio") or ""), inbox, prefix="dh_aud_")
        if err_i or err_a:
            # 输入解析失败：诚实报哪个引用不合法（不合成、不假成功）
            self._json(400, {
                "ok": False, "mouth_moved": False,
                "message": err_i or err_a,
                "which": "image" if err_i else "audio",
            })
            return

        raw_name = str(body.get("name") or "") or time.strftime("talking_%H%M%S")
        out_name = f"{cs._safe_filename(raw_name)}.mp4".replace(".mp4.mp4", ".mp4")
        # 长耗时合成：留在本 HTTP 线程（ThreadingHTTPServer 一请求一线程，与精剪/导出同纪律）
        res = make_talking_video(image_local, audio_local, out_name, inbox)
        if res.get("ok"):
            res["url"] = f"/inbox_file/{os.path.basename(str(res.get('file')))}"
            res.pop("file", None)
            self._json(200, res)
        else:
            self._json(400, res)
        return

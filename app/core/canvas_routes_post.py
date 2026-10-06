# -*- coding: utf-8 -*-
"""画布桥 POST 路由（从 canvas_server.py 的 do_POST if 链迁出，2026-09-27 整改 A4 批次 2/3）

`do_POST` 曾是约 1,049 行的 if 链（评价报告 §2/§4.2 架构债 #2）。本模块把其中
29 个端点迁成独立 handler，经 `@_route_post` 注册。

保持行为等价（本次不顺手改逻辑）
--------------------------------
- 每个 handler 的函数体与迁出前**逐行等价**（含注释、响应码、错误分支）。
- 401 响应体原样保留（各端点 `message` 文案与附加字段不同，前端依赖）。
- 依赖的模块级符号经 `_cs()` 取 canvas_server 模块访问
  （`cs._check_host_token` / `cs._BATCH_JOBS` … 同一对象，行为不变）。
- handler 签名 `(self, parsed, raw, ctype)` 与既有路由表 handler 约定一致
  （`_dispatch_table(..., parsed=, raw=, ctype=)`）。

**未迁出**（仍留在 canvas_server.do_POST）：请求体解析（Content-Length/ctype）、
路由表分发、404 兜底。
"""
from __future__ import annotations

import json
import logging
import os
import queue
import time
import uuid
from typing import Any, Dict, List
from urllib.parse import parse_qs

from app.core.canvas_route_registry import _route_post

logger = logging.getLogger(__name__)


def _cs():
    """延迟取 canvas_server 模块（顶层导入会循环：canvas_server 要继承本 mixin）。"""
    from app.core import canvas_server

    return canvas_server


class CanvasPostRoutesMixin:
    """POST 端点 handler 集合（由 `_BridgeHandler` 继承）。"""

    # ── POST: Tauri 桌面画布主窗口关闭时通知后端清理 ──────────────
    # Tauri 端在 on_window_event CloseRequested 中 POST 此端点，
    # 后端通过 EventBus.CANVAS_TAURI_CLOSED 通知 Qt 主程序清理 canvas_runtime 引用。
    @_route_post("/host/tauri-closing")
    def _p_host_tauri_closing(self, parsed, raw: bytes, ctype: str) -> None:
        cs = _cs()

        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            from app.modules.lego.core import EventBus, EventType
        except ImportError:
            from modules.lego.core import EventBus, EventType  # type: ignore
        try:
            bus = EventBus.get_instance()
            if hasattr(EventType, "CANVAS_TAURI_CLOSED"):
                bus.emit(
                    EventType.CANVAS_TAURI_CLOSED,
                    {"source": "tauri", "ts": time.time()},
                    source="canvas_bridge",
                )
            # 同步清理 canvas_runtime 进程引用，避免下次启动判定仍在运行
            try:
                from app.core.canvas_runtime import get_canvas_runtime
                rt = get_canvas_runtime()
                rt.mark_tauri_closed()
            except Exception as exc:
                logger.debug("mark_tauri_closed failed: %s", exc)
        except Exception as exc:
            logger.warning("[/host/tauri-closing] 事件分发失败: %s", exc)
        self._json(200, {"ok": True})
        return

    # ── POST: 画布 Agent 主动回执（对 task.create 的响应 / 主动 canvas.query）──
    @_route_post("/host/agent/session")
    def _p_host_agent_session(self, parsed, raw: bytes, ctype: str) -> None:
        cs = _cs()

        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            self._json(400, {"ok": False, "message": "invalid json"})
            return
        from app.core.agent_session import agent_sessions

        sid = str(body.get("session_id") or "canvas")
        action = str(body.get("action") or "").lower()
        if action == "stop":
            agent_sessions.stop(sid)
        elif action == "pause":
            agent_sessions.pause(sid)
        elif action in ("resume", "continue"):
            agent_sessions.resume(sid)
        elif action == "mode":
            agent_sessions.set_mode(sid, str(body.get("mode") or ""))
        self._json(200, {"ok": True, **agent_sessions.snapshot(sid)})
        return

    @_route_post("/host/agent/reply")
    def _p_host_agent_reply(self, parsed, raw: bytes, ctype: str) -> None:
        cs = _cs()

        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            self._json(400, {"ok": False, "message": "invalid json"})
            return
        correlation_id = str(body.get("correlation_id") or "").strip()
        reply_type = str(body.get("type") or "canvas.reply").strip()
        payload = body.get("payload") if "payload" in body else body
        evt = cs.make_agent_event(
            reply_type,
            payload,
            from_agent="canvas",
            to_agent="editor",
            correlation_id=correlation_id or None,
        )
        cs.broadcast_agent_event(evt)
        # 如果剪辑侧有在等这条回执（阻塞式），把内容塞给它
        if correlation_id:
            with cs._EVT_REPLY_LOCK:
                q = cs._EVT_REPLY_QUEUES.pop(correlation_id, None)
            if q is not None:
                try:
                    q.put_nowait(evt)
                except queue.Full:
                    logger.debug("event reply queue full", exc_info=True)
        self._json(200, {"ok": True, "id": evt["id"]})
        return

    @_route_post("/host/agent/start")
    def _p_host_agent_start(self, parsed, raw: bytes, ctype: str) -> None:
        cs = _cs()

        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            from app.core.canvas_agent_runtime import get_canvas_agent_runtime
        except ImportError:
            from core.canvas_agent_runtime import get_canvas_agent_runtime  # type: ignore
        rt = get_canvas_agent_runtime()
        ok, msg = rt.ensure_started(wait_seconds=90.0)
        self._json(
            200 if ok else 500,
            {
                "ok": bool(ok),
                "message": msg,
                "url": rt.url if ok else "",
                "token": rt.token if ok else "",
                "listening": rt.is_listening(),
            },
        )
        return

    # ── 剧本合规守护：POST /host/compliance-check ────────────────
    @_route_post("/host/compliance-check")
    def _p_host_compliance_check(self, parsed, raw: bytes, ctype: str) -> None:
        cs = _cs()

        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            self._json(400, {"ok": False, "message": "invalid json"})
            return
        script = str(body.get("script") or "")
        shots = body.get("shots") or []
        characters = body.get("characters") or []
        try:
            from app.core.project_agent_host import script_compliance_check

            result = script_compliance_check(script, shots, characters)
            self._json(200, result)
        except Exception as e:
            logger.exception("[/host/compliance-check] 失败")
            self._json(500, {"ok": False, "message": str(e)})
        return

    # ── 首尾帧视频生成：POST /host/video-generate（首尾帧 → CogVideoX / Wan 管线入口） ──
    @_route_post("/host/video-generate")
    def _p_host_video_generate(self, parsed, raw: bytes, ctype: str) -> None:
        cs = _cs()

        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            self._json(400, {"ok": False, "message": "invalid json"})
            return
        first_frame = str(body.get("firstFrame") or body.get("first_frame") or "")
        last_frame = str(body.get("lastFrame") or body.get("last_frame") or "")
        prompt = str(body.get("prompt") or "")
        duration = float(body.get("duration") or 5.0)
        size = str(body.get("size") or "1280x720")
        model = str(body.get("model") or "")
        channel_id = str(body.get("channel_id") or "")
        if not first_frame or not last_frame:
            self._json(400, {"ok": False, "message": "缺少 firstFrame / lastFrame"})
            return
        port = getattr(self.server, "bridge_port", cs.DEFAULT_PORT)
        try:
            res = cs.generate_video_via_host(
                prompt=prompt,
                model=model,
                channel_id=channel_id,
                duration=duration,
                size=size,
                first_frame=first_frame,
                last_frame=last_frame,
                bridge_port=int(port),
            )
            code = 200 if res.get("ok") else 400
            if not res.get("ok"):
                try:
                    from app.core.ai_engine import AIEngine
                    AIEngine().increment_ng_count(1)
                except Exception:
                    logger.debug("increment_ng_count failed", exc_info=True)
            self._json(code, res)
        except Exception as e:
            logger.exception("[/host/local-video-generate] 调用异常")
            self._json(500, {"ok": False, "message": str(e)})
        return

    # ── 动态预算阈值：POST /host/budget/set ──
    @_route_post("/host/budget/set")
    def _p_host_budget_set(self, parsed, raw: bytes, ctype: str) -> None:
        cs = _cs()

        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            self._json(400, {"ok": False, "message": "invalid json"})
            return
        try:
            from app.core.ai_engine import AIEngine

            limit = float(body.get("budget_limit") or 0)
            project_limit = float(body.get("project_budget") or 0)
            AIEngine().set_budget_limit(limit, project_limit)
            self._json(
                200,
                {"ok": True, "budget_limit": limit, "project_budget": project_limit},
            )
        except Exception as e:
            logger.exception("[/host/budget/set] 失败")
            self._json(500, {"ok": False, "message": str(e)})
        return

    @_route_post("/ingest")
    def _p_ingest(self, parsed, raw: bytes, ctype: str) -> None:
        self._handle_ingest(raw, ctype, parse_qs(parsed.query))
        return

    @_route_post("/ingest_path")
    def _p_ingest_path(self, parsed, raw: bytes, ctype: str) -> None:
        cs = _cs()

        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"success": False, "message": "invalid json"})
            return
        # merge toolbar prefs if not provided
        char_id = str(data.get("character_id") or cs._BRIDGE_PREFS.get("character_id") or "")
        char_name = str(data.get("character_name") or cs._BRIDGE_PREFS.get("character_name") or "")
        if "enable_interpolation" in data:
            interp = bool(data.get("enable_interpolation"))
        else:
            interp = bool(cs._BRIDGE_PREFS.get("enable_interpolation"))
        path = str(data.get("path") or "")
        res = cs.ingest_local_file(
            path,
            title=str(data.get("title") or ""),
            character_id=char_id,
            character_name=char_name,
            send_to_editor=bool(data.get("send_to_editor", True)),
            enable_interpolation=interp,
            source=str(data.get("source") or "infinite_canvas"),
            duration_sec=float(data.get("duration_sec") or 0),
            canvas_node_id=str(data.get("canvas_node_id") or data.get("node_id") or ""),
            canvas_kind=str(data.get("canvas_kind") or data.get("kind") or ""),
        )
        self._json(200 if res.get("success") else 400, res)
        return

    @_route_post("/push_from_editor")
    def _p_push_from_editor(self, parsed, raw: bytes, ctype: str) -> None:
        cs = _cs()

        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"success": False, "message": "invalid json"})
            return
        res = cs.push_editor_to_canvas(
            str(data.get("path") or ""),
            title=str(data.get("title") or ""),
            source=str(data.get("source") or "editor"),
            extra={
                k: data.get(k)
                for k in (
                    "clip_id",
                    "canvas_node_id",
                    "kind",
                    "in_point",
                    "out_point",
                    "start_time",
                    "duration",
                )
                if data.get(k) not in (None, "")
            },
        )
        self._json(200 if res.get("success") else 400, res)
        return

    @_route_post("/host/generate-image")
    def _p_host_generate_image(self, parsed, raw: bytes, ctype: str) -> None:
        cs = _cs()

        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"ok": False, "message": "invalid json"})
            return
        quality = str(data.get("quality") or "standard")
        aspect = str(data.get("aspect") or "") or cs.DEFAULT_ASPECT
        size = str(data.get("size") or "") or cs.translate_quality(quality, cs.CAPABILITY_IMAGE, aspect)["size"]
        res = cs.generate_image_openai_compatible(
            prompt=str(data.get("prompt") or ""),
            model=str(data.get("model") or ""),
            size=size,
            channel_id=str(data.get("channel_id") or ""),
            reference_image=str(data.get("reference_image") or ""),
            strength=float(data.get("strength") or 0.65),
            quality=quality,
            seed=data.get("seed"),
            aspect=aspect,
        )
        code = 200 if res.get("ok") else 400
        if not res.get("ok"):
            try:
                from app.core.ai_engine import AIEngine; AIEngine().increment_ng_count(1)
            except Exception:
                logger.debug("increment_ng_count failed", exc_info=True)
        # 画质档位含人脸修复时，后台预载 GFPGAN（不阻塞本次生成，前端按 job_id 轮询进度）
        try:
            if isinstance(res, dict) and cs.translate_quality(quality, cs.CAPABILITY_IMAGE, aspect).get("face_restore"):
                preload_job_id = cs.start_gfpgan_preload()
                res["preload_job_id"] = preload_job_id
                with cs._MODEL_PRELOAD_LOCK:
                    _pjob = cs._MODEL_PRELOAD_JOBS.get(preload_job_id)
                res["face_restore_ready"] = bool(_pjob and _pjob.get("ready"))
        except Exception as exc:
            logger.debug(f"GFPGAN 预载触发失败: {exc}")
        self._json(code, res)
        return

    # ── ComfyUI 工作流执行：POST /host/comfyui/run（粘贴即用 / dry-run 演练） ──
    @_route_post("/host/comfyui/run")
    def _p_host_comfyui_run(self, parsed, raw: bytes, ctype: str) -> None:
        cs = _cs()

        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"ok": False, "message": "invalid json"})
            return
        workflow_json = data.get("workflow_json")
        # 兼容前端直接传 JSON 字符串（粘贴原始文本）与已解析对象两种情况
        if isinstance(workflow_json, str):
            try:
                workflow_json = json.loads(workflow_json)
            except Exception:
                self._json(400, {"ok": False, "message": "workflow_json 不是合法 JSON"})
                return
        dry_run = bool(data.get("dry_run", False))
        try:
            from app.core.ai.comfy_provider import comfy_provider

            result = comfy_provider.run_workflow_from_json(workflow_json, dry_run=dry_run)
        except Exception as e:
            logger.exception("[/host/comfyui/run] 失败")
            self._json(500, {"ok": False, "message": str(e)})
            return
        code = 200 if result.get("ok") else 400
        self._json(code, result)
        return

    @_route_post("/host/generate-video")
    def _p_host_generate_video(self, parsed, raw: bytes, ctype: str) -> None:
        cs = _cs()

        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"ok": False, "message": "invalid json"})
            return
        port = getattr(self.server, "bridge_port", cs.DEFAULT_PORT)
        quality = str(data.get("quality") or "standard")
        aspect = str(data.get("aspect") or "") or cs.DEFAULT_ASPECT
        size = str(data.get("size") or "") or cs.translate_quality(quality, cs.CAPABILITY_VIDEO, aspect)["size"]

        # 需要后处理（超分/补帧）时创建后台任务，前端按 postprocess_job_id 轮询进度
        quality_params = cs.translate_quality(quality, cs.CAPABILITY_VIDEO, aspect)
        postprocess_job_id = ""
        progress_cb = None
        done_cb = None
        if quality_params.get("frame_interpolate") or quality_params.get("upscale"):
            postprocess_job_id = uuid.uuid4().hex[:12]
            with cs._POSTPROCESS_LOCK:
                cs._POSTPROCESS_JOBS[postprocess_job_id] = {
                    "job_id": postprocess_job_id,
                    "status": "processing",
                    "progress": 0,
                    "message": "等待后处理...",
                    "video_path": "",
                    "video_url": "",
                    "postprocessed": False,
                    "created_at": time.time(),
                    "updated_at": time.time(),
                }

            def progress_cb(pct: int, message: str) -> None:
                with cs._POSTPROCESS_LOCK:
                    job = cs._POSTPROCESS_JOBS.get(postprocess_job_id)
                    if job:
                        job["progress"] = int(pct)
                        job["message"] = message or ""
                        job["updated_at"] = time.time()

            def done_cb(src_path: str, final_path: str) -> None:
                with cs._POSTPROCESS_LOCK:
                    job = cs._POSTPROCESS_JOBS.get(postprocess_job_id)
                    if not job:
                        return
                    if final_path and final_path != src_path and os.path.isfile(final_path):
                        job["video_path"] = final_path
                        job["video_url"] = (
                            f"http://127.0.0.1:{int(port)}/inbox_file/"
                            f"{os.path.basename(final_path)}"
                        )
                        job["postprocessed"] = True
                    job["status"] = "done"
                    job["progress"] = 100
                    job["message"] = "后处理完成"
                    job["updated_at"] = time.time()

        res = cs.generate_video_via_host(
            prompt=str(data.get("prompt") or ""),
            model=str(data.get("model") or ""),
            channel_id=str(data.get("channel_id") or ""),
            duration=float(data.get("duration") or 5.0),
            size=size,
            reference_image=str(data.get("reference_image") or ""),
            reference_video=str(data.get("reference_video") or data.get("referenceVideo") or ""),
            first_frame=str(data.get("first_frame") or data.get("firstFrame") or ""),
            last_frame=str(data.get("last_frame") or data.get("lastFrame") or ""),
            bridge_port=int(port),
            quality=quality,
            aspect=aspect,
            postprocess_progress_callback=progress_cb,
            postprocess_done_callback=done_cb,
        )
        if postprocess_job_id and res.get("ok") and res.get("postprocessing"):
            res["postprocess_job_id"] = postprocess_job_id
        elif postprocess_job_id:
            # 未派生出后处理工作（生成失败/无需处理），清理掉避免残留
            with cs._POSTPROCESS_LOCK:
                cs._POSTPROCESS_JOBS.pop(postprocess_job_id, None)
        code = 200 if res.get("ok") else 400
        if not res.get("ok"):
            try:
                from app.core.ai_engine import AIEngine; AIEngine().increment_ng_count(1)
            except Exception:
                logger.debug("increment_ng_count failed", exc_info=True)
        self._json(code, res)
        return

    # ── 模式 B 姿态解析：POST /host/pose-extract（视频 → BlazePose 关键点 JSON 子进程） ──
    @_route_post("/host/pose-extract")
    def _p_host_pose_extract(self, parsed, raw: bytes, ctype: str) -> None:
        cs = _cs()

        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"ok": False, "message": "invalid json"})
            return
        port = getattr(self.server, "bridge_port", cs.DEFAULT_PORT)
        # 参考视频统一走 inbox 规范化（data URL / inbox URL / 本地路径 → 本地路径）
        from app.core.canvas_aigc import _normalize_reference_video

        video_ref = str(data.get("video") or data.get("reference_video") or "")
        if not video_ref:
            self._json(400, {"ok": False, "message": "缺少参考视频（video 字段）"})
            return
        normalized = _normalize_reference_video(video_ref, bridge_port=int(port))
        if not normalized.get("ok"):
            self._json(400, {"ok": False, "message": str(normalized.get("message") or "参考视频无效")})
            return
        video_path = str(normalized.get("path") or "")
        if not video_path:
            self._json(400, {"ok": False, "message": "仅支持本地/画布参考视频（外链 URL 无法解析姿态）"})
            return
        try:
            from app.core.ai.pose_extract_service import pose_extract_service

            res = pose_extract_service.extract(
                video_path,
                sample_step=int(data.get("sample_step") or 1),
                max_frames=int(data.get("max_frames") or 300),
                model_complexity=int(data.get("model_complexity") or 1),
                timeout=float(data.get("timeout") or 180.0),
            )
        except Exception as e:
            logger.exception("[/host/pose-extract] 失败")
            self._json(500, {"ok": False, "message": str(e)})
            return
        code = 200 if res.get("ok") else 400
        self._json(code, res)
        return

    # ── 模式 B 第四刀：POST /host/pose-video-encode（逐帧 PNG 序列 → mp4，落 inbox） ──
    # 前端逐帧渲染白模姿态并采集 PNG data URL（复用离屏 RenderTarget 读像素），
    # 本端点负责合成。产出的 mp4 即作为 reference_video 走第一刀通道。
    @_route_post("/host/pose-video-encode")
    def _p_host_pose_video_encode(self, parsed, raw: bytes, ctype: str) -> None:
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
            from app.core.ai.pose_video_service import encode_pose_video

            res = encode_pose_video(
                data.get("frames") or [],
                fps=int(data.get("fps") or 25),
                name=str(data.get("name") or "pose_motion"),
            )
        except Exception as e:
            logger.exception("[/host/pose-video-encode] 失败")
            self._json(500, {"ok": False, "message": str(e)})
            return
        code = 200 if res.get("ok") else 400
        self._json(code, res)
        return

    @_route_post("/host/inpaint")
    def _p_host_inpaint(self, parsed, raw: bytes, ctype: str) -> None:
        cs = _cs()

        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"ok": False, "message": "invalid json"})
            return
        res = cs.inpaint_via_host(
            prompt=str(data.get("prompt") or ""),
            image=str(data.get("image") or ""),
            mask=str(data.get("mask") or ""),
            model=str(data.get("model") or ""),
            channel_id=str(data.get("channel_id") or ""),
            size=str(data.get("size") or "1024x576"),
        )
        code = 200 if res.get("ok") else 400
        if not res.get("ok"):
            try:
                from app.core.ai_engine import AIEngine; AIEngine().increment_ng_count(1)
            except Exception:
                logger.debug("increment_ng_count failed", exc_info=True)
        self._json(code, res)
        return

    @_route_post("/host/repair-image")
    def _p_host_repair_image(self, parsed, raw: bytes, ctype: str) -> None:
        """P4 局部重绘（抽卡闭环）：自动定位坏区 → 蒙版 → inpaint → 合成。

        与 /host/inpaint 的分工：后者要求调用方自带蒙版（"我知道哪坏了"）；
        本端点自己找坏区（"帮我看看哪坏了并修掉"），且**坏区外像素逐字节保持原图**。
        坏区检测免费；本端点会真花一次云端额度 ⇒ 前端/Agent 需显式调用。
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
        image = str(data.get("image") or data.get("image_data_url") or "")
        if not image:
            self._json(400, {"ok": False, "message": "缺少 image（原图 data URL）"})
            return
        try:
            from app.core.ai.inpaint_retry import repair_image

            res = repair_image(
                image,
                prompt=str(data.get("prompt") or ""),
                model=str(data.get("model") or ""),
                channel_id=str(data.get("channel_id") or ""),
                size=str(data.get("size") or "768x1344"),
                grid=int(data.get("grid") or 4),
                threshold=float(data.get("threshold") or 0.35),
            )
        except Exception as exc:
            logger.debug("repair_image 端点异常: %s", exc)
            res = {"ok": False, "message": f"局部重绘异常: {exc}"}
        self._json(200 if res.get("ok") else 400, res)
        return

    @_route_post("/host/generate-audio")
    def _p_host_generate_audio(self, parsed, raw: bytes, ctype: str) -> None:
        cs = _cs()

        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"ok": False, "message": "invalid json"})
            return
        res = cs.generate_audio_via_host(
            prompt=str(data.get("prompt") or ""),
            model=str(data.get("model") or ""),
            channel_id=str(data.get("channel_id") or ""),
            voice=str(data.get("voice") or ""),
            bridge_port=int(getattr(self.server, "bridge_port", cs.DEFAULT_PORT)),
        )
        code = 200 if res.get("ok") else 400
        if not res.get("ok"):
            try:
                from app.core.ai_engine import AIEngine; AIEngine().increment_ng_count(1)
            except Exception:
                logger.debug("increment_ng_count failed", exc_info=True)
        self._json(code, res)
        return

    @_route_post("/host/generate-music")
    def _p_host_generate_music(self, parsed, raw: bytes, ctype: str) -> None:
        cs = _cs()

        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"ok": False, "message": "invalid json"})
            return
        port = getattr(self.server, "bridge_port", cs.DEFAULT_PORT)
        res = cs.generate_music_via_host(
            prompt=str(data.get("prompt") or ""),
            model=str(data.get("model") or ""),
            channel_id=str(data.get("channel_id") or ""),
            style=str(data.get("style") or ""),
            lyrics=str(data.get("lyrics") or ""),
            title=str(data.get("title") or ""),
            instrumental=bool(data.get("instrumental")),
            bridge_port=int(port),
        )
        code = 200 if res.get("ok") else 400
        if not res.get("ok"):
            try:
                from app.core.ai_engine import AIEngine; AIEngine().increment_ng_count(1)
            except Exception:
                logger.debug("increment_ng_count failed", exc_info=True)
        self._json(code, res)
        return

    # ── POST /host/yue/plan：YuE 符号规划（歌词+风格 → 可编辑旋律/和弦 ABC 谱） ──
    # 与 /host/generate-music（Suno 黑盒）的分工：本端点**只出可编辑的谱**，
    # 是「意图卡片」要展示的东西 —— 用户改完谱再走 /host/yue/generate 渲染。
    # 执行端未配置时返回 unavailable + 安装指引（不造假谱）。
    @_route_post("/host/yue/plan")
    def _p_host_yue_plan(self, parsed, raw: bytes, ctype: str) -> None:
        cs = _cs()

        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"ok": False, "message": "invalid json"})
            return
        res = cs.yue_plan_song(
            lyrics=str(data.get("lyrics") or ""),
            style=str(data.get("style") or ""),
            cot=str(data.get("cot") or "full"),
            seed=data.get("seed"),
        )
        self._json(200 if res.get("ok") else 400, res)
        return

    # ── POST /host/yue/generate：YuE 渲染整曲（可带用户编辑过的 ABC 谱） ──
    # abc 非空 = YuE2 的「编辑模式」（按 --abc-file 语义渲染，产出全新录音）。
    @_route_post("/host/yue/generate")
    def _p_host_yue_generate(self, parsed, raw: bytes, ctype: str) -> None:
        cs = _cs()

        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"ok": False, "message": "invalid json"})
            return
        port = getattr(self.server, "bridge_port", cs.DEFAULT_PORT)
        res = cs.yue_render_song(
            lyrics=str(data.get("lyrics") or ""),
            style=str(data.get("style") or ""),
            abc=str(data.get("abc") or ""),
            cot=str(data.get("cot") or "full"),
            seed=data.get("seed"),
            title=str(data.get("title") or ""),
            bridge_port=int(port),
        )
        code = 200 if res.get("ok") else 400
        if not res.get("ok") and not res.get("unavailable"):
            try:
                from app.core.ai_engine import AIEngine; AIEngine().increment_ng_count(1)
            except Exception:
                logger.debug("increment_ng_count failed", exc_info=True)
        self._json(code, res)
        return

    # ── POST /host/yue/transcribe：翻唱前置（参考曲 → 旋律 ABC 谱） ──
    # 官方用 SheetSage2 在独立环境转录，输出只留旋律、去和弦（便于伴奏适配新风格）。
    # 转录质量决定翻唱质量 ⇒ 返回的谱应先给用户审阅，再走 /host/yue/generate。
    @_route_post("/host/yue/transcribe")
    def _p_host_yue_transcribe(self, parsed, raw: bytes, ctype: str) -> None:
        cs = _cs()

        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"ok": False, "message": "invalid json"})
            return
        res = cs.yue_transcribe_reference(
            audio=str(data.get("audio") or data.get("audio_url") or data.get("reference") or ""),
            melody_only=bool(data.get("melody_only", True)),
        )
        self._json(200 if res.get("ok") else 400, res)
        return

    # ── POST /host/yue/probe：探测 YuE 执行端可用性（UI 据此决定是否显示入口） ──
    @_route_post("/host/yue/probe")
    def _p_host_yue_probe(self, parsed, raw: bytes, ctype: str) -> None:
        cs = _cs()

        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        self._json(200, {"ok": True, "engine": "yue", **cs.yue_probe_engine()})
        return

    # ── POST /host/video-batch：分镜批量生成（V2 多机位编排 + V3 完整时长入口） ──
    @_route_post("/host/video-batch")
    def _p_host_video_batch(self, parsed, raw: bytes, ctype: str) -> None:
        cs = _cs()

        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"ok": False, "message": "invalid json"})
            return
        segments_in = body.get("segments") or []
        if not isinstance(segments_in, list) or not segments_in:
            self._json(400, {"ok": False, "message": "segments 不能为空"})
            return
        channel_id = str(body.get("channel_id") or "")
        model = str(body.get("model") or "")
        duration = int(body.get("duration") or 5)
        # 构建 job
        job_id = uuid.uuid4().hex[:12]
        job_segments: List[Dict[str, Any]] = []
        for idx, seg in enumerate(segments_in):
            job_segments.append({
                "index": idx,
                "camera_name": str(seg.get("cameraName") or seg.get("camera_name") or f"机位{idx + 1}"),
                "prompt": str(seg.get("prompt") or ""),
                "duration": int(seg.get("duration") or duration),
                "first_frame": str(seg.get("firstFrame") or seg.get("first_frame") or ""),
                "last_frame": str(seg.get("lastFrame") or seg.get("last_frame") or ""),
                "reference_image": str(seg.get("referenceImage") or seg.get("reference_image") or ""),
                "video_url": "",
                "local_path": "",
                "status": "pending",
                "error": "",
            })
        total = len(job_segments)
        job: Dict[str, Any] = {
            "job_id": job_id,
            "status": "running",
            "total": total,
            "done": 0,
            "failed": 0,
            "segments": job_segments,
            "channel_id": channel_id,
            "model": model,
            "created_at": time.time(),
            "updated_at": time.time(),
            "output_path": "",
            "concat_status": "pending",
            "transition_sec": float(body.get("transition_sec") or 0),
            "auto_concat": bool(body.get("auto_concat")),
        }
        with cs._BATCH_LOCK:
            cs._BATCH_JOBS[job_id] = job

        # 后台线程：串行调用 generate_video_via_host
        def _run_batch():
            try:
                for seg in job["segments"]:
                    if job["status"] in ("cancelled",):
                        break
                    seg["status"] = "generating"
                    job["updated_at"] = time.time()
                    try:
                        res = cs.generate_video_via_host(
                            prompt=seg["prompt"],
                            model=model,
                            channel_id=channel_id,
                            duration=seg["duration"],
                            first_frame=seg["first_frame"],
                            last_frame=seg["last_frame"],
                            reference_image=seg["reference_image"],
                            bridge_port=int(getattr(self.server, "bridge_port", cs.DEFAULT_PORT)),
                        )
                        if res.get("ok"):
                            # generate_video_via_host 通过 _save_video_bytes 返回 video_path + video_url
                            local_path = str(res.get("video_path") or res.get("local_path") or "")
                            seg["local_path"] = local_path
                            seg["video_url"] = str(res.get("video_url") or "")
                            seg["status"] = "done"
                            job["done"] += 1
                        else:
                            seg["status"] = "failed"
                            seg["error"] = str(res.get("message") or res.get("note") or "未知错误")
                            job["failed"] += 1
                            try:
                                from app.core.ai_engine import AIEngine
                                AIEngine().increment_ng_count(1)
                            except Exception:
                                logger.debug("increment_ng_count failed", exc_info=True)
                    except Exception as e:
                        seg["status"] = "failed"
                        seg["error"] = str(e)
                        job["failed"] += 1
                    job["updated_at"] = time.time()
                job["status"] = "done" if job["failed"] < job["total"] else "failed"
                # 自动拼接
                if job.get("auto_concat"):
                    valid_paths = [s["local_path"] for s in job["segments"] if s["status"] == "done" and s["local_path"]]
                    if len(valid_paths) >= 2:
                        out = os.path.join(
                            cs.canvas_inbox_dir(),
                            f"batch_{job_id}_{int(time.time())}.mp4",
                        )
                        if job.get("transition_sec", 0) > 0:
                            result = cs._run_concat_xfade(valid_paths, out, float(job["transition_sec"]))
                        else:
                            result = cs._run_concat_demuxer(valid_paths, out)
                        if result:
                            job["output_path"] = result
                            job["concat_status"] = "done"
                        else:
                            job["concat_status"] = "failed"
                    else:
                        job["concat_status"] = "skipped"
            except Exception:
                job["status"] = "failed"
                logger.exception("batch %s 执行异常", job_id)
            finally:
                job["updated_at"] = time.time()

        cs._threading.Thread(target=_run_batch, daemon=True, name=f"batch-{job_id}").start()
        # 给前端返回精简版
        summary_segs = [
            {
                "index": s["index"],
                "camera_name": s["camera_name"],
                "status": s["status"],
                "error": s["error"][:120] if s["error"] else "",
            }
            for s in job_segments
        ]
        self._json(200, {
            "ok": True,
            "job_id": job_id,
            "total": total,
            "status": job["status"],
            "model": model,
            "segments": summary_segs,
        })
        return

    # ── POST /host/interpolate：帧间插值（VFI）占位，记录参数后返回 ok ──
    @_route_post("/host/interpolate")
    def _p_host_interpolate(self, parsed, raw: bytes, ctype: str) -> None:
        cs = _cs()

        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"ok": False, "message": "invalid json"})
            return
        mode = str(body.get("mode") or "smart")
        target_fps = int(body.get("target_fps") or 24)
        logger.info("[/host/interpolate] stub: mode=%s fps=%d title=%s", mode, target_fps, body.get("title"))
        self._json(200, {
            "ok": True,
            "message": "帧间插值占位：后端暂未实现实际 VFI（可后续接 RIFE/EMA-VFI）",
            "mode": mode,
            "target_fps": target_fps,
            "todo": "backend-vfi-integration",
        })
        return

    # ── POST /host/video-concat：批量任务结果拼接成片 ──
    @_route_post("/host/video-concat")
    def _p_host_video_concat(self, parsed, raw: bytes, ctype: str) -> None:
        cs = _cs()

        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"ok": False, "message": "invalid json"})
            return
        job_id = str(body.get("job_id") or "")
        transition_sec = float(body.get("transition_sec") or 0)
        video_paths: List[str] = []
        if job_id:
            with cs._BATCH_LOCK:
                job = cs._BATCH_JOBS.get(job_id)
            if not job:
                self._json(404, {"ok": False, "message": f"job {job_id} not found"})
                return
            video_paths = [s["local_path"] for s in job["segments"] if s["status"] == "done" and s["local_path"]]
        else:
            raw_paths = body.get("paths") or body.get("video_paths") or []
            video_paths = [str(p) for p in raw_paths if str(p)]
        # 路径校验：全部存在
        missing = [p for p in video_paths if not os.path.isfile(p)]
        if missing:
            self._json(400, {"ok": False, "message": f"路径不存在: {missing[:3]}"})
            return
        if len(video_paths) < 2:
            self._json(400, {"ok": False, "message": "至少需要 2 个视频才能拼接"})
            return
        out = os.path.join(
            cs.canvas_inbox_dir(),
            f"concat_{int(time.time())}_{len(video_paths)}segs.mp4",
        )
        try:
            if transition_sec > 0:
                result = cs._run_concat_xfade(video_paths, out, transition_sec)
            else:
                result = cs._run_concat_demuxer(video_paths, out)
            if result:
                total_dur = sum(cs._probe_duration(p) for p in video_paths)
                self._json(200, {
                    "ok": True,
                    "output_path": result,
                    "video_url": f"/inbox_file/{os.path.basename(result)}",
                    "segment_count": len(video_paths),
                    "total_duration": round(total_dur, 2),
                    "transition_sec": transition_sec,
                })
            else:
                self._json(500, {"ok": False, "message": "FFmpeg 拼接失败，请检查 ffmpeg 安装与输入文件"})
        except Exception as e:
            logger.exception("[/host/video-concat] 异常")
            self._json(500, {"ok": False, "message": str(e)})
        return

    # ── POST /host/batch-to-timeline：分镜批量生成结果回填时间轴（入轨） ──
    @_route_post("/host/batch-to-timeline")
    def _p_host_batch_to_timeline(self, parsed, raw: bytes, ctype: str) -> None:
        cs = _cs()

        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"ok": False, "message": "invalid json"})
            return
        job_id = str(body.get("job_id") or "")
        if not job_id:
            self._json(400, {"ok": False, "message": "job_id 不能为空"})
            return
        with cs._BATCH_LOCK:
            job = cs._BATCH_JOBS.get(job_id)
        if not job:
            self._json(404, {"ok": False, "message": f"job {job_id} not found"})
            return
        # 可选：仅入轨指定分镜序号（indices 为 list[int]，缺省全部已完成片段）
        indices = body.get("indices")
        done_segs = [
            s for s in job.get("segments", [])
            if s.get("status") == "done" and s.get("local_path")
            and (indices is None or (isinstance(indices, list) and s.get("index") in indices))
        ]
        if not done_segs:
            self._json(400, {"ok": False, "message": "无已完成片段可入轨"})
            return
        pushed: List[Dict[str, Any]] = []
        failed: List[Dict[str, Any]] = []
        for seg in done_segs:
            res = cs.emit_canvas_to_editor(
                seg["local_path"],
                title=str(seg.get("camera_name") or f"分镜{int(seg.get('index', 0)) + 1}"),
                source="storyboard_batch",
                duration_sec=float(seg.get("duration") or 0),
            )
            entry = {"index": seg.get("index"), "path": seg.get("local_path")}
            if res.get("success"):
                pushed.append({**entry, "title": str(seg.get("camera_name") or "")})
            else:
                failed.append({**entry, "message": res.get("message", "入轨失败")})
        logger.info("[/host/batch-to-timeline] 入轨 job=%s pushed=%d failed=%d",
                    job_id, len(pushed), len(failed))
        self._json(200, {
            "ok": True,
            "job_id": job_id,
            "pushed": len(pushed),
            "failed": len(failed),
            "items": pushed,
            "errors": failed,
        })
        return

    # DEPRECATED: 旧 Node MCP 路径（→ agent_chat_proxy → :17371）。
    # 自研画布请看 /host/project-agent/chat（→ project_agent_host.project_agent_chat → ai_engine）。
    @_route_post("/host/agent/chat")
    def _p_host_agent_chat(self, parsed, raw: bytes, ctype: str) -> None:
        cs = _cs()

        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"ok": False, "message": "invalid json"})
            return
        res = cs.agent_chat_proxy(str(data.get("message") or data.get("content") or ""))
        code = 200 if res.get("ok") else 400
        self._json(code, res)
        return

    # 主路径：自研画布 Agent 对话（走 project_agent_host → ai_engine）。
    # 支持 SSE chat.delta 流式推送、canvas_context 上下文、provider/model 选择。
    @_route_post("/host/project-agent/chat")
    def _p_host_project_agent_chat(self, parsed, raw: bytes, ctype: str) -> None:
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
            from app.core.project_agent_host import project_agent_chat
        except ImportError:
            from core.project_agent_host import project_agent_chat  # type: ignore
        ctx = data.get("canvas_context")
        if ctx is not None and not isinstance(ctx, dict):
            ctx = None
        res = project_agent_chat(
            message=str(data.get("message") or data.get("content") or ""),
            provider=str(data.get("provider") or ""),
            model=str(data.get("model") or ""),
            apply=bool(data.get("apply", True)),
            canvas_context=ctx,
            mode=str(data.get("mode") or "canvas_fast"),
            stream_id=str(data.get("stream_id") or ""),
            agent_mode=str(data.get("agent_mode") or ""),
            session_id=str(data.get("session_id") or ""),
        )
        code = 200 if res.get("ok") else 400
        self._json(code, res)
        return

    @_route_post("/host/upload-asset")
    def _p_host_upload_asset(self, parsed, raw: bytes, ctype: str) -> None:
        cs = _cs()

        # 画布参考视频/图：落盘 inbox，返回可播放 /inbox_file/ URL（避免巨型 dataURL）
        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        qs = parse_qs(parsed.query)
        filename = (qs.get("filename") or ["asset.bin"])[0]
        port = getattr(self.server, "bridge_port", cs.DEFAULT_PORT)
        try:
            if "application/json" in ctype:
                data = json.loads(raw.decode("utf-8") or "{}")
                b64 = str(data.get("data_base64") or data.get("base64") or "")
                if "," in b64:
                    b64 = b64.split(",", 1)[-1]
                if not b64:
                    self._json(400, {"ok": False, "message": "缺少 data_base64"})
                    return
                import base64

                file_bytes = base64.b64decode(b64)
                filename = str(data.get("filename") or filename)
            else:
                file_bytes = raw
            if not file_bytes:
                self._json(400, {"ok": False, "message": "空文件"})
                return
            name = f"{int(time.time())}_{cs._safe_filename(filename)}"
            dest = os.path.join(cs.canvas_inbox_dir(), name)
            with open(dest, "wb") as f:
                f.write(file_bytes)
            url = f"http://127.0.0.1:{int(port)}/inbox_file/{name}"
            ext = os.path.splitext(name)[1].lower()
            kind = (
                "video"
                if ext in (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v")
                else "image"
                if ext in (".png", ".jpg", ".jpeg", ".webp", ".gif")
                else "file"
            )
            self._json(
                200,
                {
                    "ok": True,
                    "url": url,
                    "path": dest,
                    "filename": name,
                    "kind": kind,
                    "bytes": len(file_bytes),
                    "message": f"已上传参考{kind}",
                },
            )
        except Exception as e:
            self._json(500, {"ok": False, "message": f"上传失败: {e}"})
        return

    @_route_post("/host/tools/run")
    def _p_host_tools_run(self, parsed, raw: bytes, ctype: str) -> None:
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
            from app.core.project_agent_host import run_project_tool
        except ImportError:
            from core.project_agent_host import run_project_tool  # type: ignore
        params = data.get("params") if isinstance(data.get("params"), dict) else {}
        res = run_project_tool(
            extension_id=str(data.get("extension_id") or ""),
            tool_id=str(data.get("tool_id") or ""),
            skill_id=str(data.get("skill_id") or ""),
            params=params,
            agent_mode=str(data.get("agent_mode") or ""),
            approved=bool(data.get("approved", False)),
            session_id=str(data.get("session_id") or ""),
        )
        code = 200 if res.get("ok") else 400
        self._json(code, res)
        return

    @_route_post("/host/storyboard-breakdown")
    def _p_host_storyboard_breakdown(self, parsed, raw: bytes, ctype: str) -> None:
        cs = _cs()

        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized", "shots": []})
            return
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"ok": False, "message": "invalid json", "shots": []})
            return
        use_llm = bool(data.get("use_llm"))
        res = cs.storyboard_breakdown(str(data.get("script") or ""), use_llm=use_llm)
        code = 200 if res.get("ok") else 400
        self._json(code, res)
        return

    @_route_post("/host/storyboard-camera-plan")
    def _p_host_storyboard_camera_plan(self, parsed, raw: bytes, ctype: str) -> None:
        cs = _cs()

        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized", "cameras": []})
            return
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"ok": False, "message": "invalid json", "cameras": []})
            return
        # 优先直接用前端回传的分镜表；否则按剧本走「拉片 → 相机规划」一步到位
        shots = data.get("shots")
        if isinstance(shots, list):
            res = cs.storyboard_to_camera_plan(shots)
        else:
            breakdown = cs.storyboard_breakdown(str(data.get("script") or ""), use_llm=bool(data.get("use_llm")))
            res = cs.storyboard_to_camera_plan(breakdown.get("shots") or [])
        code = 200 if res.get("ok") else 400
        self._json(code, res)
        return

    # ── AI 审阅：POST /host/canvas-ai-review（磁吸卡片质检 → 五维评分回传） ──
    # 前端层叠卡片（CardStack）生成后调用，后端统一走五维评分器算总分/分级/建议，
    # 结果回传用于卡片 qualityScore 展示与 passed / issues-found 状态切换。
    @_route_post("/host/canvas-ai-review")
    def _p_host_canvas_ai_review(self, parsed, raw: bytes, ctype: str) -> None:
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
            from app.core.five_dimension_scorer import five_dimension_scorer
        except ImportError:
            from core.five_dimension_scorer import five_dimension_scorer  # type: ignore
        # 前端可回传已 AI 质检的五维原始分 quality_scores（缺省维度用 70 基线并标注为估算）
        clip_meta = {
            "id": body.get("clip_id") or body.get("node_id") or "",
            "path": body.get("path") or "",
            "duration": body.get("duration") or 0,
            "quality_scores": body.get("quality_scores") if isinstance(body.get("quality_scores"), dict) else {},
        }
        try:
            features = five_dimension_scorer.extract_features_from_clip(clip_meta)
            result = five_dimension_scorer.score(features)
            review = result.to_dict()
        except Exception as e:
            logger.exception("[/host/canvas-ai-review] 失败")
            self._json(500, {"ok": False, "message": str(e)})
            return
        # 卡片状态映射：D 级（<60 分，should_drop）视为发现问题，其余视为通过
        card_status = "issues-found" if result.should_drop else "passed"
        self._json(200, {
            "ok": True,
            "review": review,
            "status": card_status,
            "quality_score": review.get("weighted_score"),
        })
        return

    # ── POST /host/canvas-run：图执行（默认只出计划；dry_run=false 才真跑） ──
    # 守北极星「确认后执行」：缺省 dry_run=True ⇒ 只返回执行计划，不消耗额度。
    # 单节点失败不炸整图（跳过其下游）；诚实失败（绝不伪造产物）。
    @_route_post("/host/canvas-run")
    def _p_host_canvas_run(self, parsed, raw: bytes, ctype: str) -> None:
        cs = _cs()

        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"ok": False, "message": "invalid json"})
            return
        graph = body.get("graph")
        if not isinstance(graph, dict):
            self._json(400, {"ok": False,
                             "message": "graph 必须是 {nodes, edges} 对象"})
            return
        # dry_run 缺省 True（只出计划）；显式传 false 才真正生成。
        # bool("false") == True 是坑，故按「显式 false」判定。
        raw_dry = body.get("dry_run", True)
        dry_run = False if raw_dry is False or str(raw_dry).strip().lower() in ("false", "0", "no") else True
        try:
            from app.core import canvas_workflow_runner as runner
            res = runner.run_graph(
                graph,
                dry_run=dry_run,
                use_cache=bool(body.get("use_cache", True)),
                quality=str(body.get("quality") or "standard"),
                aspect=str(body.get("aspect") or cs.DEFAULT_ASPECT),
            )
        except Exception as e:
            logger.exception("[/host/canvas-run] 失败")
            self._json(500, {"ok": False, "message": str(e)})
            return
        logger.info("[/host/canvas-run] dry_run=%s counters=%s",
                    dry_run, res.get("counters"))
        self._json(200 if res.get("ok") else 400, res)
        return

    # ── POST /host/canvas-cache：增量缓存管理（stats / clear） ──
    @_route_post("/host/canvas-cache")
    def _p_host_canvas_cache(self, parsed, raw: bytes, ctype: str) -> None:
        cs = _cs()

        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            body = {}
        action = str(body.get("action") or "stats").strip().lower()
        try:
            from app.core import canvas_node_cache as cache
            store = cache.get_store()
            if action == "clear":
                cleared = store.clear()
                self._json(200, {"ok": True, "action": "clear",
                                 "cleared": cleared, "stats": store.stats()})
                return
            self._json(200, {"ok": True, "action": "stats", "stats": store.stats()})
        except Exception as e:
            logger.exception("[/host/canvas-cache] 失败")
            self._json(500, {"ok": False, "message": str(e)})
        return

    # ── POST /host/canvas-enhance：意图级增强（修复人脸/超分/抠像/风格/局部修图） ──
    # 设计：**能力升格成「意图」，不是「节点」** —— 用户传一个有序列表，
    # 系统选实现并**如实回报实际用了哪个引擎**（绝不把双三次插值说成 AI 超分）。
    # ⚠️ 状态：**experimental**（刀 A4 第 4 项，2026-10-05 标注）。
    #   现状 = 后端可用但**未接任何 UI**、也无前端调用方；保留它是因为意图分级
    #   （repair/upscale/matting/style/inpaint）的设计有价值，将来做"一键增强"时是现成地基。
    #   **明确不承诺**：不保证参数/返回结构稳定，不保证引擎可用性；**调用方需自行兜底**。
    #   不要把它当稳定端点接进新功能，除非先把它从 experimental 毕业（补 UI + 前端调用 + 测试）。
    @_route_post("/host/canvas-enhance")
    def _p_host_canvas_enhance(self, parsed, raw: bytes, ctype: str) -> None:
        cs = _cs()

        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"ok": False, "message": "invalid json"})
            return
        image = str(body.get("image") or body.get("image_data_url") or "")
        if not image:
            self._json(400, {"ok": False, "message": "缺少 image（需 data URL）"})
            return
        intents = body.get("intents")
        if isinstance(intents, str):
            intents = [intents]
        if not isinstance(intents, list) or not intents:
            self._json(400, {"ok": False, "message": "intents 必须是非空列表"})
            return
        try:
            from app.core import canvas_enhance as enhance
            res = enhance.apply_intents(
                image,
                [str(i) for i in intents],
                quality=str(body.get("quality") or "standard"),
                params=body.get("params") if isinstance(body.get("params"), dict) else {},
            )
        except Exception as e:
            logger.exception("[/host/canvas-enhance] 失败")
            self._json(500, {"ok": False, "message": str(e)})
            return
        logger.info("[/host/canvas-enhance] applied=%s skipped=%s",
                    [a.get("intent") for a in res.get("applied", [])],
                    [s.get("intent") for s in res.get("skipped", [])])
        self._json(200 if res.get("ok") else 400, res)
        return

    # ── POST /host/local-video-generate：**本地**视频生成（SVD 图生视频）────
    # ⚠️ 路径刻意带 local：既有 `/host/video-generate` 是**云端**渠道那条，
    #    两者语义不同（云 AIGC 渠道 vs 本机 diffusers 模型），不可混用同一路径。
    # 设计：**走项目原生链路**（neural_engine + models/cache），不经 ComfyUI。
    # 三个 action：models（列注册表，只读）· pull（下载模型）· generate（生成）。
    # 纪律：**不自动下载** —— generate 面对未下载的模型必须如实报错，绝不悄悄开拉几 GB。
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
        image_data = str(body.get("image") or "").strip()
        if not image_path and image_data:
            # 画布传的是 data URL → 落成临时输入图（保持 generate() 单入口）
            image_path = vg.write_data_url(
                image_data, os.path.join("短剧AI剪辑输出", "_video_input"),
                name_hint="canvas") or ""
            if not image_path:
                self._json(400, {"ok": False, "message": "image（data URL）解析失败"})
                return
        if not image_path:
            self._json(400, {"ok": False,
                             "message": "需要 image_path 或 image(data URL)（SVD 是图生视频）"})
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

    # ── POST /host/local-image-generate：**本地**图像生成（SD1.5/SDXL 双栈）────
    # 刀 A1（2026-10-04）：给 V4.40.26/27/28 落地的两个图像引擎**通生产电** ——
    # 此前它们只有 bench 与测试在调（生产调用方为 0）。
    # 与 /host/generate-image 的语义分界（刻意不同路径，同 local-video 的约定）：
    #   generate-image       = **云端**模型广场渠道（付费，seed 贯通）
    #   local-image-generate = **本机**扩散引擎（零调用费，主备双栈，不自动下载）
    # 引擎分派：execution_decider.resolve_local_image_engine()（主备裁定的**真执行**，
    # R9 降级可见）；body 可显式 engine="diffsynth"/"builtin" 覆盖。
    # 三个 action：models（列注册表，只读）· pull（下载模型）· generate（生成）。
    @_route_post("/host/local-image-generate")
    def _p_host_local_image_generate(self, parsed, raw: bytes, ctype: str) -> None:
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
            from app.core.ai.execution_decider import resolve_local_image_engine
            from app.core.neural import diffusers_image as dfe
            from app.core.neural import diffsynth_image as dse
        except Exception as e:
            self._json(500, {"ok": False, "message": f"图像模块加载失败: {e}"})
            return

        model_id = str(body.get("model_id") or "sd15-t2i").strip()

        # ── models：只读列出双栈可选模型（含体积/显存/内存需求与已下载状态）──
        if action == "models":
            self._json(200, {
                "ok": True,
                "engines": [
                    {"id": "diffsynth", "role": "主选",
                     "available": dse.DiffsynthImageEngine.is_available(),
                     "unavailable_reason": dse.DiffsynthImageEngine.unavailable_reason(),
                     "models": dse.available_models()},
                    {"id": "builtin", "role": "备选/自研",
                     "available": dfe.DiffusersImageEngine.is_available(),
                     "unavailable_reason": dfe.DiffusersImageEngine.unavailable_reason(),
                     "models": dfe.available_models()},
                ],
                # 权重双栈共享 ⇒ 任一侧已下载即两侧可用（以自研侧严格校验为准，
                # 它连 original_config/组件 config 一起验）
                "downloaded": [m["id"] for m in dfe.available_models()
                               if dfe.DiffusersImageEngine.is_downloaded(m["id"])],
            })
            return

        # ── 引擎分派（pull/generate 共用）：主备裁定的**真执行**入口 ──
        sel = resolve_local_image_engine(prefer=str(body.get("engine") or ""))
        if not sel.get("ok"):
            self._json(400, {"ok": False, "engine": sel.get("engine"),
                             "reasons": sel.get("reasons"),
                             "message": sel.get("message") or "本地图像引擎不可用"})
            return
        eng = sel["backend"]

        # ── pull：下载模型（长耗时；权重双栈共享 ⇒ 拉一次两侧皆可用）──
        if action == "pull":
            res = eng.pull(model_id)
            res["engine"] = sel["engine"]
            logger.info("[/host/local-image-generate] pull %s engine=%s ok=%s",
                        model_id, sel["engine"], res.get("ok"))
            self._json(200 if res.get("ok") else 400, res)
            return

        # ── generate：生成图像（t2i；给 image_path 则 i2i）──
        image_path = str(body.get("image_path") or "").strip()
        image_data = str(body.get("image") or "").strip()
        if not image_path and image_data:
            # 画布传的是 data URL → 落成临时输入图（与 local-video 同一约定）
            from app.core.neural.video_gen import write_data_url
            image_path = write_data_url(
                image_data, os.path.join("短剧AI剪辑输出", "_image_input"),
                name_hint="canvas") or ""
            if not image_path:
                self._json(400, {"ok": False, "message": "image（data URL）解析失败"})
                return
        try:
            res = eng.generate(
                model_id,
                prompt=str(body.get("prompt") or ""),
                negative_prompt=str(body.get("negative_prompt") or ""),
                image_path=image_path,
                width=int(body.get("width") or 0),
                height=int(body.get("height") or 0),
                seed=int(body.get("seed") or 0),
                steps=int(body.get("steps") or 0),
                cfg=float(body.get("cfg") or 0.0),
                out_path=str(body.get("out_path") or ""),
            )
        except Exception as e:
            logger.exception("[/host/local-image-generate] 失败")
            self._json(500, {"ok": False, "message": str(e)})
            return
        # R9：主备降级必须可见 —— 引擎选择与理由随响应下发
        res["engine"] = sel["engine"]
        res["engine_is_fallback"] = sel.get("is_fallback", False)
        res["engine_reasons"] = sel.get("reasons", [])
        logger.info("[/host/local-image-generate] generate %s engine=%s ok=%s",
                    model_id, sel["engine"], res.get("ok"))
        self._json(200 if res.get("ok") else 400, res)
        return

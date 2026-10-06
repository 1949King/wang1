# -*- coding: utf-8 -*-
"""画布桥 GET 路由（从 canvas_server.py 的 do_GET if 链迁出，2026-09-27 整改 A4 批次 1）

背景
----
`canvas_server.py` 的 `do_GET` 曾是约 680 行的 if 链（评价报告 §2/§4.2 列为
「路由巨石」架构债 #2）：加端点要改同一个方法、鉴权重复内联、无法单测路由。
本模块把其中 25 个**精确路径**端点迁成独立 handler，经 `@_route_get` 注册，
`do_GET` 只保留薄分发 + 少数兜底路由。

保持行为等价（本次不顺手改逻辑）
--------------------------------
- 每个 handler 的函数体与迁出前**逐行等价**（含注释、响应码、错误分支）。
- 401 响应体原样保留（`/host/chat-models` 带 `providers: []`、
  `/host/tools` 带 `tools: []` 等差异是前端依赖的，不可统一）。
- 依赖的模块级符号（`_check_host_token`、`_BATCH_JOBS`、helper 函数…）
  通过函数内 `_cs()` 取 canvas_server 模块访问 —— 模块属性查找，
  与迁出前访问同一对象，行为不变。

**未迁出**（仍留在 canvas_server.do_GET）：`/` 与 `/health`、`/inject.js`、
`/host/agent/events`（SSE 长连接，结构特殊）、`/editor_file/*` 与
`/inbox_file/*`（前缀路由，路由表是精确匹配）、404 兜底。
"""
from __future__ import annotations

import logging
from urllib.parse import parse_qs

from app.core.canvas_route_registry import _route_get, _route_post

logger = logging.getLogger(__name__)


def _cs():
    """延迟取 canvas_server 模块（顶层导入会循环：canvas_server 要继承本 mixin）。"""
    from app.core import canvas_server

    return canvas_server


class CanvasGetRoutesMixin:
    """GET 端点 handler 集合（由 `_BridgeHandler` 继承）。"""

    # ── AI NG 预算追踪：返回聚合成本仪表盘数据 ────────────────
    @_route_get("/host/budget")
    def _route_host_budget(self, parsed=None):
        cs = _cs()
        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            from app.core.ai_engine import AIEngine

            report = AIEngine().check_budget()
            self._json(200, {"ok": True, "data": report})
        except Exception as e:
            self._json(500, {"ok": False, "message": str(e)})
        return

    # ── AI NG 预算追踪：最近 N 次调用明细 ──────────────────────
    @_route_get("/host/calls")
    def _route_host_calls(self, parsed=None):
        cs = _cs()
        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            qd = parse_qs(parsed.query or "")
            limit = min(100, max(1, int((qd.get("limit") or ["20"])[0])))
            from app.core.ai_engine import AIEngine

            calls = AIEngine().get_recent_calls(limit)
            self._json(200, {"ok": True, "data": calls})
        except Exception as e:
            logger.exception("[/host/calls] 失败")
            self._json(500, {"ok": False, "message": str(e)})
        return

    # ── 剧本合规守护：POST /host/compliance-check ──────────────
    @_route_get("/host/compliance-check")
    def _route_host_compliance_check(self, parsed=None):
        cs = _cs()
        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        # 这个端点实际是 POST，但 do_GET 里先拦一下返回友好错误
        self._json(405, {"ok": False, "message": "use POST"})
        return

    # ── Character Library（对接 CharacterStore）─────────────
    @_route_get("/host/characters")
    def _route_host_characters(self, parsed=None):
        from app.modules.lego.character_management_module import (
            CHARACTER_FIELD_SCHEMA,
            CharacterStore,
        )

        try:
            store = CharacterStore()
            raw = store.all()
            # 裁剪为 CharacterEntry 结构（与前端对齐）。
            # 字段白名单由 CHARACTER_FIELD_SCHEMA 派生 —— 新增角色字段时此处无需手工同步，
            # 否则会出现「库里存了、前端看不到」的静默漏传。
            # 一致性校验：_verify/check_character_schema.py
            characters = []
            for c in raw:
                entry = {"id": c.get("id", "")}
                for key in [f[0] for f in CHARACTER_FIELD_SCHEMA]:
                    entry[key] = c.get(key) or ""
                entry["tags"] = c.get("tags") or []      # 列表字段不能退化成空串
                # 由 Python 侧唯一真相源拼好的生图提示片段（含 visual 组全部 4 个字段）。
                # 前端直接用它，不要自己再拼一遍 —— 两份拼装逻辑必然漂移。
                # 一致性校验：_verify/check_character_schema.py
                cs = _cs()
                entry["prompt"] = cs.build_character_prompt(c)
                entry["media_dir"] = c.get("media_dir", "")
                entry["avatar_url"] = c.get("avatar_url", "")
                entry["created_at"] = c.get("created_at", "")
                entry["updated_at"] = c.get("updated_at", "")
                characters.append(entry)
            self._json(200, characters)
        except Exception as exc:
            logger.warning(f"/host/characters 读取失败: {exc}")
            self._json(200, [])
        return

    @_route_get("/host/prefs")
    def _route_host_prefs(self, parsed=None):
        cs = _cs()
        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        self._json(200, {"ok": True, **cs._BRIDGE_PREFS})
        return

    @_route_get("/host/prompt-fetch")
    def _route_host_prompt_fetch(self, parsed=None):
        cs = _cs()
        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        qs = parse_qs(parsed.query)
        url = (qs.get("url") or [""])[0].strip()
        if not url:
            self._json(400, {"ok": False, "message": "缺少 url 参数"})
            return
        if not cs._is_allowed_prompt_fetch_url(url):
            self._json(400, {"ok": False, "message": "不允许的提示词源域名"})
            return
        try:
            data = cs._fetch_remote_json(url)
            self._json(200, {"ok": True, "data": data})
        except Exception as e:
            logger.warning("prompt-fetch failed: %s — %s", url[:120], e)
            self._json(502, {"ok": False, "message": str(e)})
        return

    @_route_get("/host/prompt-bundled")
    def _route_host_prompt_bundled(self, parsed=None):
        cs = _cs()
        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        qs = parse_qs(parsed.query)
        source_id = (qs.get("source_id") or qs.get("id") or [""])[0].strip()
        if not source_id:
            self._json(400, {"ok": False, "message": "缺少 source_id 参数"})
            return
        try:
            data = cs._read_local_prompt_json(source_id)
            self._json(200, {"ok": True, "data": data})
        except FileNotFoundError as e:
            self._json(404, {"ok": False, "message": str(e)})
        except Exception as e:
            logger.warning("prompt-bundled failed: %s — %s", source_id, e)
            self._json(502, {"ok": False, "message": str(e)})
        return

    @_route_get("/host/prompt-image")
    def _route_host_prompt_image(self, parsed=None):
        cs = _cs()
        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        qs = parse_qs(parsed.query)
        url = (qs.get("url") or [""])[0].strip()
        if not url:
            self._json(400, {"ok": False, "message": "缺少 url 参数"})
            return
        if not cs._is_allowed_prompt_image_url(url):
            self._json(400, {"ok": False, "message": "不允许的图片域名"})
            return
        try:
            cached = cs._read_prompt_image_cache(url)
            if cached:
                raw, content_type = cached
            else:
                if cs._prompt_image_failed_recently(url):
                    self._json(502, {"ok": False, "message": "图片此前拉取失败，负缓存 TTL 内不再重试"})
                    return
                try:
                    raw, content_type = cs._fetch_remote_bytes(url)
                except Exception:
                    cs._mark_prompt_image_failed(url)
                    raise
                cs._clear_prompt_image_failed(url)
                if len(raw) <= 12 * 1024 * 1024:
                    cs._write_prompt_image_cache(url, raw, content_type)
            if len(raw) > 12 * 1024 * 1024:
                self._json(413, {"ok": False, "message": "图片过大"})
                return
            self._bytes(200, raw, content_type, cache=True)
        except Exception as e:
            logger.warning("prompt-image failed: %s — %s", url[:120], e)
            self._json(502, {"ok": False, "message": str(e)})
        return

    @_route_get("/host/ai-config-patch")
    @_route_get("/host/providers")
    def _route_host_ai_config_patch(self, parsed=None):
        cs = _cs()
        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        patch = cs.build_host_ai_config_patch()
        self._json(200, {"ok": True, **patch})
        return

    @_route_get("/host/comfyui/status")
    def _route_host_comfyui_status(self, parsed=None):
        cs = _cs()
        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            from app.core.ai.comfy_provider import comfy_provider

            status = comfy_provider.engine_status()
        except Exception as e:
            logger.exception("[/host/comfyui/status] 失败")
            self._json(500, {"ok": False, "message": str(e)})
            return
        self._json(200, {"ok": True, "status": status})
        return

    @_route_get("/host/image-models")
    def _route_host_image_models(self, parsed=None):
        cs = _cs()
        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        patch = cs.build_host_ai_config_patch()
        models = []
        for ch in patch.get("channels") or []:
            if not (ch.get("apiKey") or "").strip():
                continue
            for m in ch.get("models") or []:
                if m.get("capability") != "image":
                    continue
                models.append(
                    {
                        "channel_id": ch.get("id"),
                        "channel_name": ch.get("name"),
                        "model": m.get("name"),
                        "label": f"{ch.get('name')} / {m.get('name')}",
                    }
                )
        self._json(
            200,
            {
                "ok": True,
                "models": models,
                "default": (patch.get("defaults") or {}).get("imageModel") or "",
                "warnings": patch.get("warnings") or [],
                "configured_providers": patch.get("configured_providers") or [],
                "active_provider": patch.get("active_provider") or "",
                "active_provider_label": patch.get("active_provider_label") or "",
                "has_image_models": bool(models),
            },
        )
        return

    @_route_get("/host/video-models")
    def _route_host_video_models(self, parsed=None):
        cs = _cs()
        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        patch = cs.build_host_ai_config_patch()
        models = []
        for ch in patch.get("channels") or []:
            if not (ch.get("apiKey") or "").strip():
                continue
            for m in ch.get("models") or []:
                if m.get("capability") != "video":
                    continue
                models.append(
                    {
                        "channel_id": ch.get("id"),
                        "channel_name": ch.get("name"),
                        "model": m.get("name"),
                        "label": f"{ch.get('name')} / {m.get('name')}",
                    }
                )
        self._json(
            200,
            {
                "ok": True,
                "models": models,
                "default": (patch.get("defaults") or {}).get("videoModel") or "",
                "warnings": patch.get("warnings") or [],
                "configured_providers": patch.get("configured_providers") or [],
                "active_provider": patch.get("active_provider") or "",
                "active_provider_label": patch.get("active_provider_label") or "",
                "has_video_models": bool(models),
            },
        )
        return

    @_route_get("/host/audio-models")
    def _route_host_audio_models(self, parsed=None):
        cs = _cs()
        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        patch = cs.build_host_ai_config_patch()
        models = []
        for ch in patch.get("channels") or []:
            if not (ch.get("apiKey") or "").strip():
                continue
            for m in ch.get("models") or []:
                if m.get("capability") != "audio":
                    continue
                models.append(
                    {
                        "channel_id": ch.get("id"),
                        "channel_name": ch.get("name"),
                        "model": m.get("name"),
                        "label": f"{ch.get('name')} / {m.get('name')}",
                    }
                )
        self._json(
            200,
            {
                "ok": True,
                "models": models,
                "default": (patch.get("defaults") or {}).get("audioModel") or "",
                "warnings": patch.get("warnings") or [],
                "configured_providers": patch.get("configured_providers") or [],
                "active_provider": patch.get("active_provider") or "",
                "active_provider_label": patch.get("active_provider_label") or "",
                "has_audio_models": bool(models),
            },
        )
        return

    @_route_get("/host/music-models")
    def _route_host_music_models(self, parsed=None):
        cs = _cs()
        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        patch = cs.build_host_ai_config_patch()
        models = []
        for ch in patch.get("channels") or []:
            if not (ch.get("apiKey") or "").strip():
                continue
            for m in ch.get("models") or []:
                if m.get("capability") != "music":
                    continue
                models.append(
                    {
                        "channel_id": ch.get("id"),
                        "channel_name": ch.get("name"),
                        "model": m.get("name"),
                        "label": f"{ch.get('name')} / {m.get('name')}",
                    }
                )
        self._json(
            200,
            {
                "ok": True,
                "models": models,
                "default": (patch.get("defaults") or {}).get("musicModel") or "",
                "warnings": patch.get("warnings") or [],
                "configured_providers": patch.get("configured_providers") or [],
                "active_provider": patch.get("active_provider") or "",
                "active_provider_label": patch.get("active_provider_label") or "",
                "has_music_models": bool(models),
            },
        )
        return

    @_route_get("/host/chat-models")
    def _route_host_chat_models(self, parsed=None):
        cs = _cs()
        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized", "providers": []})
            return
        try:
            from app.core.project_agent_host import list_chat_models
        except ImportError:
            from core.project_agent_host import list_chat_models  # type: ignore
        self._json(200, list_chat_models())
        return

    @_route_get("/host/tools")
    def _route_host_tools(self, parsed=None):
        cs = _cs()
        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized", "tools": []})
            return
        try:
            from app.core.project_agent_host import list_project_tools
        except ImportError:
            from core.project_agent_host import list_project_tools  # type: ignore
        qs = parse_qs(parsed.query)
        agent_mode = (qs.get("agent_mode") or [""])[0]
        self._json(200, list_project_tools(agent_mode=agent_mode))
        return

    @_route_get("/host/agent/session")
    def _route_host_agent_session(self, parsed=None):
        cs = _cs()
        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        from app.core.agent_session import agent_sessions

        qs = parse_qs(parsed.query)
        sid = (qs.get("session_id") or ["canvas"])[0]
        self._json(200, {"ok": True, **agent_sessions.snapshot(sid)})
        return

    @_route_get("/host/agent/tasks")
    def _route_host_agent_tasks(self, parsed=None):
        cs = _cs()
        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized", "tasks": []})
            return
        from app.core.agent_task_store import agent_tasks

        qs = parse_qs(parsed.query)
        sid = (qs.get("session_id") or ["canvas"])[0]
        self._json(200, {"ok": True, "tasks": agent_tasks.list_for_session(sid)})
        return

    @_route_get("/host/agent")
    def _route_host_agent(self, parsed=None):
        cs = _cs()
        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            from app.core.canvas_agent_runtime import get_canvas_agent_runtime
        except ImportError:
            from core.canvas_agent_runtime import get_canvas_agent_runtime  # type: ignore
        rt = get_canvas_agent_runtime()
        self._json(
            200,
            {
                "ok": True,
                "url": rt.url,
                "token": rt.token,
                "listening": rt.is_listening(),
                "message": "已连接" if (rt.is_listening() and rt.token) else "画布 MCP（:17371）未启动，请点「连接画布MCP」",
                "kind": "canvas_mcp",
            },
        )
        return

    @_route_get("/editor_outbox")
    def _route_editor_outbox(self, parsed=None):
        cs = _cs()
        items = []
        for it in cs.list_editor_outbox():
            items.append(
                {
                    "id": it["id"],
                    "title": it["title"],
                    "filename": it["filename"],
                    "ext": it["ext"],
                    "url": f"{getattr(self.server, 'base_url', f'http://127.0.0.1:{cs.DEFAULT_PORT}')}{it['url']}",
                    "created_at": it.get("created_at"),
                }
            )
        # fix urls relative
        for it, raw in zip(items, cs.list_editor_outbox(), strict=False):
            it["url"] = f"http://127.0.0.1:{getattr(self.server, 'bridge_port', cs.DEFAULT_PORT)}{raw['url']}"
            for key in (
                "clip_id",
                "canvas_node_id",
                "kind",
                "in_point",
                "out_point",
                "start_time",
                "duration",
                "source",
            ):
                if raw.get(key) is not None:
                    it[key] = raw.get(key)
        self._json(200, {"ok": True, "items": items})
        return

    @_route_get("/host/timeline-snapshot")
    def _route_host_timeline_snapshot(self, parsed=None):
        cs = _cs()
        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized", "clips": [], "clip_count": 0})
            return
        snap = cs.get_timeline_snapshot()
        try:
            from app.core.editor_canvas_link import suggest_canvas_roundtrip
        except ImportError:
            from core.editor_canvas_link import suggest_canvas_roundtrip  # type: ignore
        snap = dict(snap)
        snap["suggestions"] = suggest_canvas_roundtrip(snap)
        self._json(200, snap)
        return

    @_route_get("/host/plugins")
    def _route_host_plugins(self, parsed=None):
        """画布节点插件列表（从 Qt 端 plugin-store 读取）"""
        cs = _cs()
        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        plugins = cs._load_canvas_plugins_manifest()
        self._json(200, {"ok": True, "plugins": plugins, "builtin": cs._BUILTIN_PLUGIN_REGISTRY})
        return

    # ── GET /host/video-batch?job_id=xxx：查询批量视频任务状态 ──
    @_route_get("/host/video-batch")
    def _route_host_video_batch(self, parsed=None):
        cs = _cs()
        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        qs = parse_qs(parsed.query)
        job_id = (qs.get("job_id") or [""])[0] if hasattr(parsed, "query") else ""
        if not job_id:
            with cs._BATCH_LOCK:
                summary = [
                    {
                        "job_id": jid,
                        "status": j["status"],
                        "total": j["total"],
                        "done": j["done"],
                        "failed": j["failed"],
                        "model": j["model"],
                        "created_at": j["created_at"],
                        "concat_status": j["concat_status"],
                        "output_path": j["output_path"],
                    }
                    for jid, j in list(cs._BATCH_JOBS.items())[-20:]
                ]
            self._json(200, {"ok": True, "jobs": summary})
            return
        with cs._BATCH_LOCK:
            job = cs._BATCH_JOBS.get(job_id)
        if not job:
            self._json(404, {"ok": False, "message": f"job {job_id} not found"})
            return
        segs = [
            {
                "index": s["index"],
                "camera_name": s["camera_name"],
                "status": s["status"],
                "local_path": s["local_path"],
                "video_url": s["video_url"],
                "error": s["error"][:200] if s["error"] else "",
            }
            for s in job["segments"]
        ]
        self._json(200, {
            "ok": True,
            "job_id": job_id,
            "status": job["status"],
            "total": job["total"],
            "done": job["done"],
            "failed": job["failed"],
            "concat_status": job["concat_status"],
            "output_path": job["output_path"],
            "segments": segs,
            "updated_at": job["updated_at"],
        })
        return

    # ── GET /host/video-postprocess?job_id=xxx：查询单视频后处理任务进度 ──
    @_route_get("/host/video-postprocess")
    def _route_host_video_postprocess(self, parsed=None):
        cs = _cs()
        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        qs = parse_qs(parsed.query)
        job_id = (qs.get("job_id") or [""])[0] if hasattr(parsed, "query") else ""
        if not job_id:
            self._json(400, {"ok": False, "message": "job_id 不能为空"})
            return
        with cs._POSTPROCESS_LOCK:
            job = cs._POSTPROCESS_JOBS.get(job_id)
        if not job:
            self._json(404, {"ok": False, "message": f"job {job_id} not found"})
            return
        self._json(200, {
            "ok": True,
            "job_id": job_id,
            "status": job["status"],
            "progress": job["progress"],
            "message": job["message"],
            "video_path": job["video_path"],
            "video_url": job["video_url"],
            "postprocessed": job["postprocessed"],
            "updated_at": job["updated_at"],
        })
        return

    # ── GET /host/agent-policy：把 Agent 工具策略**派生化下发**（★ 刀 A4 第 2 项）──
    #
    # 为什么必须有这个端点：前端 `agentPolicy.ts` 曾**硬编码一份 CANVAS 映射**
    # （20+ 条 effect/paid），与后端 `agent_action_registry._CANVAS_ACTION_ROWS`
    # 构成**两个真源** —— 后端加一个工具，前端不知道 ⇒ 落到默认分支，策略静默错判
    # （轻则多问一次，重则少问一次）。项目纪律是「派生值一律后端下发，前端不要自己算」。
    #
    # 数据全部来自**单一事实来源** `agent_action_registry`，本端点**不重复定义任何映射**；
    # 另附 `table_hash` 供前端/测试比对，便于发现两边版本不一致。
    @_route_get("/host/agent-policy")
    def _route_host_agent_policy(self, parsed=None):
        cs = _cs()
        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            from app.core import agent_action_registry as reg

            tools = {}
            for action, danger, effect, desc in reg._CANVAS_ACTION_ROWS:
                tools[action] = {
                    "effect": effect,
                    "paid": effect == "media_write",
                    "danger": danger,
                    "desc": desc,
                }
            import hashlib
            import json as _json

            blob = _json.dumps(tools, ensure_ascii=False, sort_keys=True)
            self._json(200, {
                "ok": True,
                "modes": ["plan", "collaborative", "autonomous"],
                "tools": tools,
                "write_effects": ["canvas_write", "file_write", "media_write",
                                  "memory_write"],
                "dangerous": sorted(reg._CANVAS_DANGEROUS_ACTIONS),
                "table_hash": hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16],
                # 模式语义（后端为准，前端只做展示与兜底）：
                "mode_rules": {
                    "plan": "只读；任何写/生成一律 deny",
                    "collaborative": "写/生成需用户确认（paid 的必须确认）",
                    "autonomous": "自动放行（dangerous 仍受 tool 白名单约束）",
                },
            })
        except Exception as e:
            logger.exception("[agent-policy] 下发失败")
            self._json(500, {"ok": False, "message": f"策略下发失败: {e}"})
        return


    # ── GET/POST /host/model-preload：本地模型（GFPGAN）后台预载进度轮询 / 触发 ──
    # ★ A4（2026-10-05）修方法错配：前端 `bridge.ts::startModelPreload()` 用的是 **POST**，
    #   而这里**只注册了 GET** ⇒ 请求根本到不了本 handler（handler 里 `self.command == "POST"`
    #   那段分支成了**不可达代码**，前端拿到 404）。两个装饰器是两个独立注册表（可叠加），
    #   故直接把同一 handler 同时登记到 GET（轮询）/POST（触发）⇒ 与 handler 内的分支一致。
    #   守卫已同步升级为按 **(method, path) 二元组** 比对，同类错配以后会被拦下。
    @_route_post("/host/model-preload")
    @_route_get("/host/model-preload")
    def _route_host_model_preload(self, parsed=None):
        cs = _cs()
        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        if self.command == "POST":
            job_id = cs.start_gfpgan_preload()
            self._json(200, {"ok": True, "job_id": job_id})
            return
        qs = parse_qs(parsed.query)
        job_id = (qs.get("job_id") or [""])[0] if hasattr(parsed, "query") else ""
        if not job_id:
            self._json(400, {"ok": False, "message": "job_id 不能为空"})
            return
        with cs._MODEL_PRELOAD_LOCK:
            job = cs._MODEL_PRELOAD_JOBS.get(job_id)
        if not job:
            self._json(404, {"ok": False, "message": f"job {job_id} not found"})
            return
        self._json(200, {
            "ok": True,
            "job_id": job_id,
            "kind": job.get("kind"),
            "status": job.get("status"),
            "progress": job.get("progress"),
            "message": job.get("message"),
            "ready": job.get("ready"),
            "updated_at": job.get("updated_at"),
        })
        return

    # ── GET /host/enhance-intents：意图目录（供 UI 渲染选择器，不加载模型） ──
    # 只暴露「意图」（修复人脸/超分/抠像…），**不暴露模型名** —— 这是与 ComfyUI 的分歧点。
    @_route_get("/host/enhance-intents")
    def _route_host_enhance_intents(self, parsed=None):
        cs = _cs()
        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            from app.core import canvas_enhance as enhance
            self._json(200, {
                "ok": True,
                "intents": enhance.available_intents(),
                "quality_tiers": list(enhance.QUALITY_TIERS),
            })
        except Exception as e:
            logger.exception("[/host/enhance-intents] 失败")
            self._json(500, {"ok": False, "message": str(e)})
        return

# -*- coding: utf-8 -*-
"""画布桥 HTTP 服务层：本地小 HTTP 桥（_BridgeHandler / CanvasBridgeServer）。

从 canvas_bridge.py 拆分而来（大文件治理）。自研导演台 /host/*、/ingest、/ingest_path、
/push_from_editor、/inbox_file、/editor_outbox、/inject.js 等 HTTP 端点与 SSE 事件流全部弘中于此。

IO / 状态 / 媒体层（canvas_inbox_dir、ingest_local_file、emit_canvas_to_editor、agent 事件
总线、插件 manifest、FFmpeg 拼接等）仍留在 canvas_bridge.py；AIGC 生成能力在 canvas_aigc.py。
本模块顶部 import 引用它们，canvas_bridge.py 末尾 re-export 本模块以保持向后兼容。

端口冻结约束（stage3d-core）：DEFAULT_PORT 以 canvas_bridge.py 为准（18765 不得更改），
本模块仅引用该常量，不单独定义端口。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import queue
import threading
import threading as _threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from app.core.canvas_aigc import (
    agent_chat_proxy,
    build_host_ai_config_patch,
    generate_audio_via_host,
    generate_image_openai_compatible,
    generate_music_via_host,
    generate_video_via_host,
    inpaint_via_host,
    storyboard_breakdown,
    storyboard_to_camera_plan,
)
from app.core.canvas_bridge import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    _BUILTIN_PLUGIN_REGISTRY,
    _BATCH_JOBS,
    _BATCH_LOCK,
    _BRIDGE_PREFS,
    _EVT_REPLY_LOCK,
    _EVT_REPLY_QUEUES,
    _EVT_SUBS,
    _EVT_SUBS_LOCK,
    _SESSION_TOKEN,
    _load_canvas_plugins_manifest,
    _probe_duration,
    _remove_canvas_plugin,
    _run_concat_demuxer,
    _run_concat_xfade,
    _safe_filename,
    _toggle_canvas_plugin_enabled,
    _upsert_canvas_plugin,
    broadcast_agent_event,
    canvas_inbox_dir,
    canvas_outbox_dir,
    emit_canvas_to_editor,
    get_timeline_snapshot,
    ingest_local_file,
    list_editor_outbox,
    make_agent_event,
    push_editor_to_canvas,
    replay_agent_events,
)

logger = logging.getLogger("AI短剧编辑器.canvas_bridge")


def _check_host_token(handler: BaseHTTPRequestHandler) -> bool:
    tok = (handler.headers.get("X-Shiguang-Token") or "").strip()
    if tok and tok == _SESSION_TOKEN:
        return True
    # 同机无 Origin 时允许 query token（inject 内嵌）
    parsed = urlparse(handler.path)
    qs = parse_qs(parsed.query)
    qtok = (qs.get("token") or [""])[0]
    return bool(qtok) and qtok == _SESSION_TOKEN


# 提示词库远程 JSON / 封面图代理（Qt WebView 直连外网 CDN 常失败）
_PROMPT_FETCH_HOSTS = (
    "raw.githubusercontent.com",
    "cdn.jsdelivr.net",
)
_PROMPT_IMAGE_HOSTS = _PROMPT_FETCH_HOSTS + (
    "githubusercontent.com",
    "camo.githubusercontent.com",
    "r2.apimodels.app",
    "apimodels.app",
    "glidea.github.io",
    "images.unsplash.com",
    "i.imgur.com",
    "pbs.twimg.com",
)


def _is_allowed_prompt_fetch_url(url: str) -> bool:
    try:
        host = urlparse(url.strip()).netloc.lower().split(":")[0]
    except Exception:
        return False
    return any(host == h or host.endswith("." + h) for h in _PROMPT_FETCH_HOSTS)


def _is_allowed_prompt_image_url(url: str) -> bool:
    try:
        parsed = urlparse(url.strip())
        if parsed.scheme.lower() not in ("http", "https"):
            return False
        host = parsed.netloc.lower().split(":")[0]
    except Exception:
        return False
    return any(host == h or host.endswith("." + h) for h in _PROMPT_IMAGE_HOSTS)


def _guess_image_content_type(url: str) -> str:
    low = url.lower().split("?", 1)[0]
    if low.endswith(".png"):
        return "image/png"
    if low.endswith(".webp"):
        return "image/webp"
    if low.endswith(".gif"):
        return "image/gif"
    if low.endswith(".svg"):
        return "image/svg+xml"
    return "image/jpeg"


def _fetch_remote_json(url: str, timeout: float = 90.0) -> Any:
    from urllib.request import Request, urlopen

    req = Request(url, headers={"User-Agent": "ShiguangCanvas/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return json.loads(raw.decode("utf-8"))


def _fetch_remote_bytes(url: str, timeout: float = 45.0) -> Tuple[bytes, str]:
    from urllib.request import Request, urlopen

    req = Request(url, headers={"User-Agent": "ShiguangCanvas/1.0", "Accept": "image/*,*/*"})
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        ct = (resp.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
    if not ct.startswith("image/"):
        ct = _guess_image_content_type(url)
    return raw, ct


_PROMPT_IMAGE_CACHE_DIR = Path(os.path.expanduser("~")) / ".video_editor_cache" / "prompt_images"
_PROMPT_IMAGE_CACHE_MAX_BYTES = 80 * 1024 * 1024


def _prompt_image_cache_key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8", errors="replace")).hexdigest()


def _read_prompt_image_cache(url: str) -> Optional[Tuple[bytes, str]]:
    try:
        key = _prompt_image_cache_key(url)
        blob = _PROMPT_IMAGE_CACHE_DIR / key
        meta = _PROMPT_IMAGE_CACHE_DIR / f"{key}.ct"
        if not blob.is_file() or not meta.is_file():
            return None
        if blob.stat().st_size > 12 * 1024 * 1024:
            return None
        ct = meta.read_text(encoding="utf-8").strip() or "image/jpeg"
        return blob.read_bytes(), ct
    except Exception:
        return None


def _trim_prompt_image_cache() -> None:
    try:
        files = [p for p in _PROMPT_IMAGE_CACHE_DIR.iterdir() if p.is_file() and not p.name.endswith(".ct")]
        total = sum(p.stat().st_size for p in files)
        if total <= _PROMPT_IMAGE_CACHE_MAX_BYTES:
            return
        files.sort(key=lambda p: p.stat().st_mtime)
        for p in files:
            if total <= _PROMPT_IMAGE_CACHE_MAX_BYTES:
                break
            sz = p.stat().st_size
            try:
                p.unlink(missing_ok=True)
                meta = _PROMPT_IMAGE_CACHE_DIR / f"{p.name}.ct"
                meta.unlink(missing_ok=True)
                total -= sz
            except Exception:
                continue
    except Exception:
        logger.debug("prompt-image cache trim skipped", exc_info=True)


def _write_prompt_image_cache(url: str, raw: bytes, content_type: str) -> None:
    try:
        _PROMPT_IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        key = _prompt_image_cache_key(url)
        tmp = _PROMPT_IMAGE_CACHE_DIR / f"{key}.tmp"
        tmp.write_bytes(raw)
        tmp.replace(_PROMPT_IMAGE_CACHE_DIR / key)
        (_PROMPT_IMAGE_CACHE_DIR / f"{key}.ct").write_text(
            (content_type or "image/jpeg").split(";", 1)[0].strip() or "image/jpeg",
            encoding="utf-8",
        )
        _trim_prompt_image_cache()
    except Exception:
        logger.debug("prompt-image cache write skipped", exc_info=True)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_PROMPTS_PUBLIC = _REPO_ROOT / "vendor" / "shiguang-canvas" / "public" / "prompts"
_LOCAL_PROMPT_BY_ID: Dict[str, Path] = {
    "shiguang-curated": _PROMPTS_PUBLIC / "shiguang-curated.json",
    "shiguang-drama-pack": _PROMPTS_PUBLIC / "shiguang-drama.json",
    "shiguang-adult-18plus": _PROMPTS_PUBLIC / "shiguang-adult-18plus.json",
}


def _resolve_local_prompt_path(source_id: str) -> Optional[Path]:
    sid = (source_id or "").strip()
    if not sid or ".." in sid or "/" in sid or "\\" in sid:
        return None
    if sid in _LOCAL_PROMPT_BY_ID:
        return _LOCAL_PROMPT_BY_ID[sid]
    bundled = _PROMPTS_PUBLIC / "bundled" / f"{sid}.json"
    if bundled.is_file():
        return bundled
    flat = _PROMPTS_PUBLIC / f"{sid}.json"
    if flat.is_file():
        return flat
    return None


def _read_local_prompt_json(source_id: str) -> Any:
    path = _resolve_local_prompt_path(source_id)
    if path is None or not path.is_file():
        raise FileNotFoundError(f"本地提示词包不存在: {source_id}")
    return json.loads(path.read_text(encoding="utf-8"))


class _BridgeHandler(BaseHTTPRequestHandler):
    server_version = "ShiguangCanvasBridge/1.0"

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        logger.debug("bridge %s - %s", self.address_string(), fmt % args)

    def handle(self) -> None:  # noqa: D401
        try:
            super().handle()
        except (OSError, ConnectionResetError):
            logger.debug("bridge client closed connection: %s", self.address_string())
        except BrokenPipeError:
            logger.debug("bridge broken pipe: %s", self.address_string())

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, X-Shiguang-Token",
        )

    def _json(self, code: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _bytes(self, code: int, body: bytes, content_type: str, *, cache: bool = False) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if cache:
            self.send_header("Cache-Control", "public, max-age=86400")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ("/", "/health"):
            self._json(
                200,
                {
                    "ok": True,
                    "service": "shiguang-canvas-bridge",
                    "inbox": canvas_inbox_dir(),
                    "port": getattr(self.server, "bridge_port", DEFAULT_PORT),
                    "session": _SESSION_TOKEN[:8] + "…",
                },
            )
            return
        if path == "/inject.js":
            js = _build_inject_js().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(js)))
            self.send_header("Cache-Control", "no-cache")
            self._cors()
            self.end_headers()
            self.wfile.write(js)
            return
        # ── AI NG 预算追踪：返回聚合成本仪表盘数据 ────────────────
        if path == "/host/budget":
            if not _check_host_token(self):
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
        if path == "/host/calls":
            if not _check_host_token(self):
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
        if path == "/host/compliance-check":
            if not _check_host_token(self):
                self._json(401, {"ok": False, "message": "unauthorized"})
                return
            # 这个端点实际是 POST，但 do_GET 里先拦一下返回友好错误
            self._json(405, {"ok": False, "message": "use POST"})
            return
        # ── SSE: Agent ↔ Canvas 双向事件流 ──────────────────────
        if path == "/host/agent/events":
            if not _check_host_token(self):
                self.send_response(401)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self._cors()
                self.end_headers()
                self.wfile.write(b"event: error\ndata: {\"ok\":false,\"message\":\"unauthorized\"}\n\n")
                return
            qs = parse_qs(urlparse(self.path).query)
            since_id = (qs.get("since_id") or [""])[0] or ""
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-transform")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")     # 反代（如果有）不要缓冲 SSE
            self._cors()
            self.end_headers()

            # 1) 先回放历史事件（断线重连）
            try:
                for evt in replay_agent_events(since_id):
                    line = f"event: agent\ndata: {json.dumps(evt, ensure_ascii=False)}\n\n"
                    self.wfile.write(line.encode("utf-8"))
                self.wfile.flush()
            except Exception:
                # 写不出去 = 客户端已关，直接退出
                return

            # 2) 注册实时订阅队列
            sub_q: queue.Queue = queue.Queue(maxsize=500)
            with _EVT_SUBS_LOCK:
                _EVT_SUBS.append(sub_q)

            last_ping = time.time()
            try:
                while True:
                    try:
                        evt = sub_q.get(timeout=15.0)
                    except queue.Empty:
                        # 超时：发 ping 注释保活
                        try:
                            self.wfile.write(b": ping\n\n")
                            self.wfile.flush()
                        except Exception:
                            break
                        continue
                    try:
                        line = f"event: agent\ndata: {json.dumps(evt, ensure_ascii=False)}\n\n"
                        self.wfile.write(line.encode("utf-8"))
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        break
                    except Exception:
                        break
                    last_ping = time.time()
            finally:
                with _EVT_SUBS_LOCK:
                    try:
                        _EVT_SUBS.remove(sub_q)
                    except ValueError:
                        logger.debug("event subscriber removal failed", exc_info=True)
            return
        # ── Character Library（对接 CharacterStore）─────────────
        if path == "/host/characters":
            from app.modules.lego.character_management_module import CharacterStore
            try:
                store = CharacterStore()
                raw = store.all()
                # 裁剪为 CharacterEntry 结构（与前端对齐）
                characters = []
                for c in raw:
                    characters.append({
                        "id": c.get("id", ""),
                        "name": c.get("name", ""),
                        "gender": c.get("gender", ""),
                        "age_range": c.get("age_range", ""),
                        "role_type": c.get("role_type", ""),
                        "tags": c.get("tags", []) or [],
                        "appearance": c.get("appearance", ""),
                        "personality": c.get("personality", ""),
                        "representative_line": c.get("representative_line", ""),
                        "background": c.get("background", ""),
                        "notes": c.get("notes", ""),
                        "media_dir": c.get("media_dir", ""),
                        "avatar_url": c.get("avatar_url", ""),
                        "created_at": c.get("created_at", ""),
                        "updated_at": c.get("updated_at", ""),
                    })
                self._json(200, characters)
            except Exception as exc:
                logger.warning(f"/host/characters 读取失败: {exc}")
                self._json(200, [])
            return
        if path == "/host/prefs":
            if not _check_host_token(self):
                self._json(401, {"ok": False, "message": "unauthorized"})
                return
            self._json(200, {"ok": True, **_BRIDGE_PREFS})
            return
        if path == "/host/prompt-fetch":
            if not _check_host_token(self):
                self._json(401, {"ok": False, "message": "unauthorized"})
                return
            qs = parse_qs(parsed.query)
            url = (qs.get("url") or [""])[0].strip()
            if not url:
                self._json(400, {"ok": False, "message": "缺少 url 参数"})
                return
            if not _is_allowed_prompt_fetch_url(url):
                self._json(400, {"ok": False, "message": "不允许的提示词源域名"})
                return
            try:
                data = _fetch_remote_json(url)
                self._json(200, {"ok": True, "data": data})
            except Exception as e:
                logger.warning("prompt-fetch failed: %s — %s", url[:120], e)
                self._json(502, {"ok": False, "message": str(e)})
            return
        if path == "/host/prompt-bundled":
            if not _check_host_token(self):
                self._json(401, {"ok": False, "message": "unauthorized"})
                return
            qs = parse_qs(parsed.query)
            source_id = (qs.get("source_id") or qs.get("id") or [""])[0].strip()
            if not source_id:
                self._json(400, {"ok": False, "message": "缺少 source_id 参数"})
                return
            try:
                data = _read_local_prompt_json(source_id)
                self._json(200, {"ok": True, "data": data})
            except FileNotFoundError as e:
                self._json(404, {"ok": False, "message": str(e)})
            except Exception as e:
                logger.warning("prompt-bundled failed: %s — %s", source_id, e)
                self._json(502, {"ok": False, "message": str(e)})
            return
        if path == "/host/prompt-image":
            if not _check_host_token(self):
                self._json(401, {"ok": False, "message": "unauthorized"})
                return
            qs = parse_qs(parsed.query)
            url = (qs.get("url") or [""])[0].strip()
            if not url:
                self._json(400, {"ok": False, "message": "缺少 url 参数"})
                return
            if not _is_allowed_prompt_image_url(url):
                self._json(400, {"ok": False, "message": "不允许的图片域名"})
                return
            try:
                cached = _read_prompt_image_cache(url)
                if cached:
                    raw, content_type = cached
                else:
                    raw, content_type = _fetch_remote_bytes(url)
                    if len(raw) <= 12 * 1024 * 1024:
                        _write_prompt_image_cache(url, raw, content_type)
                if len(raw) > 12 * 1024 * 1024:
                    self._json(413, {"ok": False, "message": "图片过大"})
                    return
                self._bytes(200, raw, content_type, cache=True)
            except Exception as e:
                logger.warning("prompt-image failed: %s — %s", url[:120], e)
                self._json(502, {"ok": False, "message": str(e)})
            return
        if path in ("/host/providers", "/host/ai-config-patch"):
            if not _check_host_token(self):
                self._json(401, {"ok": False, "message": "unauthorized"})
                return
            patch = build_host_ai_config_patch()
            self._json(200, {"ok": True, **patch})
            return
        if path == "/host/comfyui/status":
            if not _check_host_token(self):
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
        if path == "/host/image-models":
            if not _check_host_token(self):
                self._json(401, {"ok": False, "message": "unauthorized"})
                return
            patch = build_host_ai_config_patch()
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
        if path == "/host/video-models":
            if not _check_host_token(self):
                self._json(401, {"ok": False, "message": "unauthorized"})
                return
            patch = build_host_ai_config_patch()
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
        if path == "/host/audio-models":
            if not _check_host_token(self):
                self._json(401, {"ok": False, "message": "unauthorized"})
                return
            patch = build_host_ai_config_patch()
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
        if path == "/host/music-models":
            if not _check_host_token(self):
                self._json(401, {"ok": False, "message": "unauthorized"})
                return
            patch = build_host_ai_config_patch()
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
        if path == "/host/chat-models":
            if not _check_host_token(self):
                self._json(401, {"ok": False, "message": "unauthorized", "providers": []})
                return
            try:
                from app.core.project_agent_host import list_chat_models
            except ImportError:
                from core.project_agent_host import list_chat_models  # type: ignore
            self._json(200, list_chat_models())
            return
        if path == "/host/tools":
            if not _check_host_token(self):
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
        if path == "/host/agent/session":
            if not _check_host_token(self):
                self._json(401, {"ok": False, "message": "unauthorized"})
                return
            from app.core.agent_session import agent_sessions

            qs = parse_qs(parsed.query)
            sid = (qs.get("session_id") or ["canvas"])[0]
            self._json(200, {"ok": True, **agent_sessions.snapshot(sid)})
            return
        if path == "/host/agent/tasks":
            if not _check_host_token(self):
                self._json(401, {"ok": False, "message": "unauthorized", "tasks": []})
                return
            from app.core.agent_task_store import agent_tasks

            qs = parse_qs(parsed.query)
            sid = (qs.get("session_id") or ["canvas"])[0]
            self._json(200, {"ok": True, "tasks": agent_tasks.list_for_session(sid)})
            return
        if path == "/host/agent":
            if not _check_host_token(self):
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
        if path == "/editor_outbox":
            items = []
            for it in list_editor_outbox():
                items.append(
                    {
                        "id": it["id"],
                        "title": it["title"],
                        "filename": it["filename"],
                        "ext": it["ext"],
                        "url": f"{getattr(self.server, 'base_url', f'http://127.0.0.1:{DEFAULT_PORT}')}{it['url']}",
                        "created_at": it.get("created_at"),
                    }
                )
            # fix urls relative
            for it, raw in zip(items, list_editor_outbox()):
                it["url"] = f"http://127.0.0.1:{getattr(self.server, 'bridge_port', DEFAULT_PORT)}{raw['url']}"
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
        if path == "/host/timeline-snapshot":
            if not _check_host_token(self):
                self._json(401, {"ok": False, "message": "unauthorized", "clips": [], "clip_count": 0})
                return
            snap = get_timeline_snapshot()
            try:
                from app.core.editor_canvas_link import suggest_canvas_roundtrip
            except ImportError:
                from core.editor_canvas_link import suggest_canvas_roundtrip  # type: ignore
            snap = dict(snap)
            snap["suggestions"] = suggest_canvas_roundtrip(snap)
            self._json(200, snap)
            return
        if path == "/host/plugins":
            """画布节点插件列表（从 Qt 端 plugin-store 读取）"""
            if not _check_host_token(self):
                self._json(401, {"ok": False, "message": "unauthorized"})
                return
            plugins = _load_canvas_plugins_manifest()
            self._json(200, {"ok": True, "plugins": plugins, "builtin": _BUILTIN_PLUGIN_REGISTRY})
            return
        if path.startswith("/editor_file/"):
            name = _safe_filename(path.split("/editor_file/", 1)[-1])
            fpath = os.path.join(canvas_outbox_dir(), name)
            if not os.path.isfile(fpath):
                self._json(404, {"ok": False, "message": "file not found"})
                return
            try:
                with open(fpath, "rb") as f:
                    data = f.read()
            except Exception as e:
                self._json(500, {"ok": False, "message": str(e)})
                return
            ctype = "application/octet-stream"
            ext = os.path.splitext(name)[1].lower()
            if ext in (".png",):
                ctype = "image/png"
            elif ext in (".jpg", ".jpeg"):
                ctype = "image/jpeg"
            elif ext in (".webp",):
                ctype = "image/webp"
            elif ext in (".mp4",):
                ctype = "video/mp4"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Disposition", f'inline; filename="{name}"')
            self._cors()
            self.end_headers()
            self.wfile.write(data)
            return
        # ── GET /host/video-batch?job_id=xxx：查询批量视频任务状态 ──
        if path == "/host/video-batch":
            if not _check_host_token(self):
                self._json(401, {"ok": False, "message": "unauthorized"})
                return
            qs = parse_qs(parsed.query)
            job_id = (qs.get("job_id") or [""])[0] if hasattr(parsed, "query") else ""
            if not job_id:
                with _BATCH_LOCK:
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
                        for jid, j in list(_BATCH_JOBS.items())[-20:]
                    ]
                self._json(200, {"ok": True, "jobs": summary})
                return
            with _BATCH_LOCK:
                job = _BATCH_JOBS.get(job_id)
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

        if path.startswith("/inbox_file/"):
            name = _safe_filename(path.split("/inbox_file/", 1)[-1])
            fpath = os.path.join(canvas_inbox_dir(), name)
            if not os.path.isfile(fpath):
                self._json(404, {"ok": False, "message": "file not found"})
                return
            try:
                with open(fpath, "rb") as f:
                    data = f.read()
            except Exception as e:
                self._json(500, {"ok": False, "message": str(e)})
                return
            ctype = "application/octet-stream"
            ext = os.path.splitext(name)[1].lower()
            if ext in (".mp4", ".webm", ".mov"):
                ctype = "video/mp4" if ext == ".mp4" else f"video/{ext[1:]}"
            elif ext in (".png", ".jpg", ".jpeg", ".webp"):
                ctype = f"image/{'jpeg' if ext in ('.jpg', '.jpeg') else ext[1:]}"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Disposition", f'inline; filename="{name}"')
            self._cors()
            self.end_headers()
            self.wfile.write(data)
            return
        self._json(404, {"ok": False, "message": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length > 0 else b""
        ctype = (self.headers.get("Content-Type") or "").lower()

        # ── POST: Tauri 桌面画布主窗口关闭时通知后端清理 ──────────────
        # Tauri 端在 on_window_event CloseRequested 中 POST 此端点，
        # 后端通过 EventBus.CANVAS_TAURI_CLOSED 通知 Qt 主程序清理 canvas_runtime 引用。
        if parsed.path == "/host/tauri-closing":
            if not _check_host_token(self):
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
        if parsed.path == "/host/agent/session":
            if not _check_host_token(self):
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
        if parsed.path == "/host/agent/reply":
            if not _check_host_token(self):
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
            evt = make_agent_event(
                reply_type,
                payload,
                from_agent="canvas",
                to_agent="editor",
                correlation_id=correlation_id or None,
            )
            broadcast_agent_event(evt)
            # 如果剪辑侧有在等这条回执（阻塞式），把内容塞给它
            if correlation_id:
                with _EVT_REPLY_LOCK:
                    q = _EVT_REPLY_QUEUES.pop(correlation_id, None)
                if q is not None:
                    try:
                        q.put_nowait(evt)
                    except queue.Full:
                        logger.debug("event reply queue full", exc_info=True)
            self._json(200, {"ok": True, "id": evt["id"]})
            return

        if parsed.path == "/host/agent/start":
            if not _check_host_token(self):
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
        if parsed.path == "/host/compliance-check":
            if not _check_host_token(self):
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
        if parsed.path == "/host/video-generate":
            if not _check_host_token(self):
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
            port = getattr(self.server, "bridge_port", DEFAULT_PORT)
            try:
                res = generate_video_via_host(
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
                logger.exception("[/host/video-generate] 调用异常")
                self._json(500, {"ok": False, "message": str(e)})
            return

        # ── 动态预算阈值：POST /host/budget/set ──
        if parsed.path == "/host/budget/set":
            if not _check_host_token(self):
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

        if parsed.path == "/ingest":
            self._handle_ingest(raw, ctype, parse_qs(parsed.query))
            return
        if parsed.path == "/ingest_path":
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                self._json(400, {"success": False, "message": "invalid json"})
                return
            # merge toolbar prefs if not provided
            char_id = str(data.get("character_id") or _BRIDGE_PREFS.get("character_id") or "")
            char_name = str(data.get("character_name") or _BRIDGE_PREFS.get("character_name") or "")
            if "enable_interpolation" in data:
                interp = bool(data.get("enable_interpolation"))
            else:
                interp = bool(_BRIDGE_PREFS.get("enable_interpolation"))
            path = str(data.get("path") or "")
            res = ingest_local_file(
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
        if parsed.path == "/push_from_editor":
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                self._json(400, {"success": False, "message": "invalid json"})
                return
            res = push_editor_to_canvas(
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
        if parsed.path == "/host/generate-image":
            if not _check_host_token(self):
                self._json(401, {"ok": False, "message": "unauthorized"})
                return
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                self._json(400, {"ok": False, "message": "invalid json"})
                return
            res = generate_image_openai_compatible(
                prompt=str(data.get("prompt") or ""),
                model=str(data.get("model") or ""),
                size=str(data.get("size") or "1024x576"),
                channel_id=str(data.get("channel_id") or ""),
                reference_image=str(data.get("reference_image") or ""),
                strength=float(data.get("strength") or 0.65),
            )
            code = 200 if res.get("ok") else 400
            if not res.get("ok"):
                try:
                    from app.core.ai_engine import AIEngine; AIEngine().increment_ng_count(1)
                except Exception:
                    logger.debug("increment_ng_count failed", exc_info=True)
            self._json(code, res)
            return
        # ── ComfyUI 工作流执行：POST /host/comfyui/run（粘贴即用 / dry-run 演练） ──
        if parsed.path == "/host/comfyui/run":
            if not _check_host_token(self):
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
        if parsed.path == "/host/generate-video":
            if not _check_host_token(self):
                self._json(401, {"ok": False, "message": "unauthorized"})
                return
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                self._json(400, {"ok": False, "message": "invalid json"})
                return
            port = getattr(self.server, "bridge_port", DEFAULT_PORT)
            res = generate_video_via_host(
                prompt=str(data.get("prompt") or ""),
                model=str(data.get("model") or ""),
                channel_id=str(data.get("channel_id") or ""),
                duration=float(data.get("duration") or 5.0),
                size=str(data.get("size") or "1280x720"),
                reference_image=str(data.get("reference_image") or ""),
                reference_video=str(data.get("reference_video") or data.get("referenceVideo") or ""),
                first_frame=str(data.get("first_frame") or data.get("firstFrame") or ""),
                last_frame=str(data.get("last_frame") or data.get("lastFrame") or ""),
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
        # ── 模式 B 姿态解析：POST /host/pose-extract（视频 → BlazePose 关键点 JSON 子进程） ──
        if parsed.path == "/host/pose-extract":
            if not _check_host_token(self):
                self._json(401, {"ok": False, "message": "unauthorized"})
                return
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                self._json(400, {"ok": False, "message": "invalid json"})
                return
            port = getattr(self.server, "bridge_port", DEFAULT_PORT)
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
        if parsed.path == "/host/inpaint":
            if not _check_host_token(self):
                self._json(401, {"ok": False, "message": "unauthorized"})
                return
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                self._json(400, {"ok": False, "message": "invalid json"})
                return
            res = inpaint_via_host(
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
        if parsed.path == "/host/generate-audio":
            if not _check_host_token(self):
                self._json(401, {"ok": False, "message": "unauthorized"})
                return
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                self._json(400, {"ok": False, "message": "invalid json"})
                return
            res = generate_audio_via_host(
                prompt=str(data.get("prompt") or ""),
                model=str(data.get("model") or ""),
                channel_id=str(data.get("channel_id") or ""),
                voice=str(data.get("voice") or ""),
                bridge_port=int(getattr(self.server, "bridge_port", DEFAULT_PORT)),
            )
            code = 200 if res.get("ok") else 400
            if not res.get("ok"):
                try:
                    from app.core.ai_engine import AIEngine; AIEngine().increment_ng_count(1)
                except Exception:
                    logger.debug("increment_ng_count failed", exc_info=True)
            self._json(code, res)
            return
        if parsed.path == "/host/generate-music":
            if not _check_host_token(self):
                self._json(401, {"ok": False, "message": "unauthorized"})
                return
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                self._json(400, {"ok": False, "message": "invalid json"})
                return
            port = getattr(self.server, "bridge_port", DEFAULT_PORT)
            res = generate_music_via_host(
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

        # ── POST /host/video-batch：分镜批量生成（V2 多机位编排 + V3 完整时长入口） ──
        if parsed.path == "/host/video-batch":
            if not _check_host_token(self):
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
            with _BATCH_LOCK:
                _BATCH_JOBS[job_id] = job

            # 后台线程：串行调用 generate_video_via_host
            def _run_batch():
                try:
                    for seg in job["segments"]:
                        if job["status"] in ("cancelled",):
                            break
                        seg["status"] = "generating"
                        job["updated_at"] = time.time()
                        try:
                            res = generate_video_via_host(
                                prompt=seg["prompt"],
                                model=model,
                                channel_id=channel_id,
                                duration=seg["duration"],
                                first_frame=seg["first_frame"],
                                last_frame=seg["last_frame"],
                                reference_image=seg["reference_image"],
                                bridge_port=int(getattr(self.server, "bridge_port", DEFAULT_PORT)),
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
                                canvas_inbox_dir(),
                                f"batch_{job_id}_{int(time.time())}.mp4",
                            )
                            if job.get("transition_sec", 0) > 0:
                                result = _run_concat_xfade(valid_paths, out, float(job["transition_sec"]))
                            else:
                                result = _run_concat_demuxer(valid_paths, out)
                            if result:
                                job["output_path"] = result
                                job["concat_status"] = "done"
                            else:
                                job["concat_status"] = "failed"
                        else:
                            job["concat_status"] = "skipped"
                except Exception as e:
                    job["status"] = "failed"
                    logger.exception("batch %s 执行异常", job_id)
                finally:
                    job["updated_at"] = time.time()

            _threading.Thread(target=_run_batch, daemon=True, name=f"batch-{job_id}").start()
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
        if parsed.path == "/host/interpolate":
            if not _check_host_token(self):
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
        if parsed.path == "/host/video-concat":
            if not _check_host_token(self):
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
                with _BATCH_LOCK:
                    job = _BATCH_JOBS.get(job_id)
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
                canvas_inbox_dir(),
                f"concat_{int(time.time())}_{len(video_paths)}segs.mp4",
            )
            try:
                if transition_sec > 0:
                    result = _run_concat_xfade(video_paths, out, transition_sec)
                else:
                    result = _run_concat_demuxer(video_paths, out)
                if result:
                    total_dur = sum(_probe_duration(p) for p in video_paths)
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
        if parsed.path == "/host/batch-to-timeline":
            if not _check_host_token(self):
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
            with _BATCH_LOCK:
                job = _BATCH_JOBS.get(job_id)
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
                res = emit_canvas_to_editor(
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
        if parsed.path == "/host/agent/chat":
            if not _check_host_token(self):
                self._json(401, {"ok": False, "message": "unauthorized"})
                return
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                self._json(400, {"ok": False, "message": "invalid json"})
                return
            res = agent_chat_proxy(str(data.get("message") or data.get("content") or ""))
            code = 200 if res.get("ok") else 400
            self._json(code, res)
            return
        # 主路径：自研画布 Agent 对话（走 project_agent_host → ai_engine）。
        # 支持 SSE chat.delta 流式推送、canvas_context 上下文、provider/model 选择。
        if parsed.path == "/host/project-agent/chat":
            if not _check_host_token(self):
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
        if parsed.path == "/host/upload-asset":
            # 画布参考视频/图：落盘 inbox，返回可播放 /inbox_file/ URL（避免巨型 dataURL）
            if not _check_host_token(self):
                self._json(401, {"ok": False, "message": "unauthorized"})
                return
            qs = parse_qs(parsed.query)
            filename = (qs.get("filename") or ["asset.bin"])[0]
            port = getattr(self.server, "bridge_port", DEFAULT_PORT)
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
                name = f"{int(time.time())}_{_safe_filename(filename)}"
                dest = os.path.join(canvas_inbox_dir(), name)
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
        if parsed.path == "/host/tools/run":
            if not _check_host_token(self):
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
        if parsed.path == "/host/storyboard-breakdown":
            if not _check_host_token(self):
                self._json(401, {"ok": False, "message": "unauthorized", "shots": []})
                return
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                self._json(400, {"ok": False, "message": "invalid json", "shots": []})
                return
            use_llm = bool(data.get("use_llm"))
            res = storyboard_breakdown(str(data.get("script") or ""), use_llm=use_llm)
            code = 200 if res.get("ok") else 400
            self._json(code, res)
            return
        if parsed.path == "/host/storyboard-camera-plan":
            if not _check_host_token(self):
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
                res = storyboard_to_camera_plan(shots)
            else:
                breakdown = storyboard_breakdown(str(data.get("script") or ""), use_llm=bool(data.get("use_llm")))
                res = storyboard_to_camera_plan(breakdown.get("shots") or [])
            code = 200 if res.get("ok") else 400
            self._json(code, res)
            return
        # ── AI 审阅：POST /host/canvas-ai-review（磁吸卡片质检 → 五维评分回传） ──
        # 前端层叠卡片（CardStack）生成后调用，后端统一走五维评分器算总分/分级/建议，
        # 结果回传用于卡片 qualityScore 展示与 passed / issues-found 状态切换。
        if parsed.path == "/host/canvas-ai-review":
            if not _check_host_token(self):
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
        self._json(404, {"ok": False, "message": "not found"})

    def _handle_ingest(self, raw: bytes, ctype: str, qs: Dict[str, List[str]]) -> None:
        title = (qs.get("title") or [""])[0]
        character_id = (qs.get("character_id") or [""])[0] or str(
            _BRIDGE_PREFS.get("character_id") or ""
        )
        character_name = (qs.get("character_name") or [""])[0] or str(
            _BRIDGE_PREFS.get("character_name") or ""
        )
        send_to_editor = (qs.get("send_to_editor") or ["1"])[0] not in ("0", "false", "False")
        if (qs.get("enable_interpolation") or [""])[0] in ("1", "true", "True"):
            enable_interpolation = True
        elif (qs.get("enable_interpolation") or [""])[0] in ("0", "false", "False"):
            enable_interpolation = False
        else:
            enable_interpolation = bool(_BRIDGE_PREFS.get("enable_interpolation"))
        filename = (qs.get("filename") or ["upload.bin"])[0]
        try:
            duration_sec = float((qs.get("duration_sec") or ["0"])[0] or 0)
        except (TypeError, ValueError):
            duration_sec = 0.0
        node_id = (qs.get("node_id") or qs.get("canvas_node_id") or [""])[0]
        canvas_kind = (qs.get("kind") or qs.get("canvas_kind") or [""])[0]

        if "multipart/form-data" in ctype:
            # 极简 multipart：找 filename= 与空行后的二进制（够用；复杂表单走 /ingest_path）
            try:
                boundary = None
                for part in ctype.split(";"):
                    part = part.strip()
                    if part.startswith("boundary="):
                        boundary = part.split("=", 1)[1].strip().strip('"')
                if not boundary:
                    self._json(400, {"success": False, "message": "no boundary"})
                    return
                marker = ("--" + boundary).encode("utf-8")
                chunks = raw.split(marker)
                file_bytes = None
                for ch in chunks:
                    if b"filename=" not in ch:
                        continue
                    # header / body
                    sep = ch.find(b"\r\n\r\n")
                    if sep < 0:
                        continue
                    header = ch[:sep].decode("utf-8", errors="ignore")
                    body = ch[sep + 4 :]
                    if body.endswith(b"\r\n"):
                        body = body[:-2]
                    if body.endswith(b"--"):
                        body = body[:-2]
                    if body.endswith(b"\r\n"):
                        body = body[:-2]
                    for line in header.split("\r\n"):
                        if "filename=" in line:
                            import re

                            m = re.search(r'filename="([^"]+)"', line)
                            if m:
                                filename = m.group(1)
                    file_bytes = body
                    break
                if file_bytes is None:
                    self._json(400, {"success": False, "message": "no file part"})
                    return
                dest = os.path.join(canvas_inbox_dir(), f"{int(time.time())}_{_safe_filename(filename)}")
                with open(dest, "wb") as f:
                    f.write(file_bytes)
                res = ingest_local_file(
                    dest,
                    title=title or filename,
                    character_id=character_id,
                    character_name=character_name,
                    send_to_editor=send_to_editor,
                    enable_interpolation=enable_interpolation,
                    duration_sec=duration_sec,
                    canvas_node_id=node_id,
                    canvas_kind=canvas_kind,
                )
                self._json(200 if res.get("success") else 400, res)
                return
            except Exception as e:
                self._json(500, {"success": False, "message": str(e)})
                return

        # raw body + filename query
        if not raw:
            self._json(400, {"success": False, "message": "empty body"})
            return
        dest = os.path.join(canvas_inbox_dir(), f"{int(time.time())}_{_safe_filename(filename)}")
        try:
            with open(dest, "wb") as f:
                f.write(raw)
        except Exception as e:
            self._json(500, {"success": False, "message": str(e)})
            return
        res = ingest_local_file(
            dest,
            title=title or filename,
            character_id=character_id,
            character_name=character_name,
            send_to_editor=send_to_editor,
            enable_interpolation=enable_interpolation,
            duration_sec=duration_sec,
            canvas_node_id=node_id,
            canvas_kind=canvas_kind,
        )
        self._json(200 if res.get("success") else 400, res)
        return

        # ── 画布节点插件操作（install / toggle / uninstall）──
        if parsed.path == "/host/plugins/install":
            if not _check_host_token(self):
                self._json(401, {"ok": False, "message": "unauthorized"})
                return
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                self._json(400, {"ok": False, "message": "invalid json"})
                return
            plugin_id = str(data.get("id") or "").strip()
            if not plugin_id:
                self._json(400, {"ok": False, "message": "plugin id required"})
                return
            preset = next((p for p in _BUILTIN_PLUGIN_REGISTRY if p.get("id") == plugin_id), None)
            entry: Dict[str, Any] = {
                "name": str(data.get("name") or (preset.get("name") if preset else "") or plugin_id),
                "version": str(data.get("version") or (preset.get("version") if preset else "") or "0.0.0"),
                "description": str(data.get("description") or (preset.get("description") if preset else "") or ""),
                "url": str(data.get("url") or (preset.get("url") if preset else "") or ""),
                "nodes": data.get("nodes") or (preset.get("nodes") if preset else []) or [],
                "official": bool(data.get("official", (preset.get("official") if preset else False))),
                "enabled": True,
            }
            saved = _upsert_canvas_plugin(plugin_id, **entry)
            self._json(200, {"ok": True, "plugin": saved})
            return

        if parsed.path == "/host/plugins/toggle":
            if not _check_host_token(self):
                self._json(401, {"ok": False, "message": "unauthorized"})
                return
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                self._json(400, {"ok": False, "message": "invalid json"})
                return
            plugin_id = str(data.get("id") or "").strip()
            enabled = bool(data.get("enabled", True))
            ok = _toggle_canvas_plugin_enabled(plugin_id, enabled)
            if not ok:
                self._json(404, {"ok": False, "message": "plugin not found"})
                return
            self._json(200, {"ok": True, "id": plugin_id, "enabled": enabled})
            return

        if parsed.path == "/host/plugins/uninstall":
            if not _check_host_token(self):
                self._json(401, {"ok": False, "message": "unauthorized"})
                return
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                self._json(400, {"ok": False, "message": "invalid json"})
                return
            plugin_id = str(data.get("id") or "").strip()
            ok = _remove_canvas_plugin(plugin_id)
            if not ok:
                self._json(404, {"ok": False, "message": "plugin not found"})
                return
            self._json(200, {"ok": True, "id": plugin_id})
            return


def _build_inject_js() -> str:
    tok = _SESSION_TOKEN
    return _INJECT_JS_TEMPLATE.replace("__TOKEN__", tok)


_INJECT_JS_TEMPLATE = r"""
(function () {
  if (window.__SHIGUANG_BRIDGE_INJECTED__) return;
  window.__SHIGUANG_BRIDGE_INJECTED__ = true;
  var BRIDGE = "http://127.0.0.1:18765";
  var TOKEN = "__TOKEN__";
  var CONFIG_KEY = "infinite-canvas:ai_config_store";
  try {
    window.__SHIGUANG_BRIDGE_TOKEN = TOKEN;
    localStorage.setItem("__shiguang_bridge_token", TOKEN);
  } catch (e) {}
  var hdr = function () { return { "X-Shiguang-Token": TOKEN }; };

  function setStatus(t) {
    var el = document.getElementById("sg-status");
    if (el) el.textContent = t || "";
  }
  window.__shiguangSetStatus = setStatus;

  function ensurePanel() {
    if (document.getElementById("shiguang-bridge-panel")) return;
    var panel = document.createElement("div");
    panel.id = "shiguang-bridge-panel";
    panel.style.cssText = [
      "position:fixed", "right:16px", "top:16px", "z-index:2147483647",
      "background:#111827", "color:#e5e7eb", "border:1px solid #374151",
      "border-radius:12px", "padding:12px", "width:280px",
      "font:13px/1.4 system-ui,sans-serif", "box-shadow:0 8px 24px rgba(0,0,0,.4)"
    ].join(";");
    panel.innerHTML = [
      "<div style='display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;gap:8px'>",
      "<div style='font-weight:700'>拾光剪影</div>",
      "<div style='display:flex;gap:4px'>",
      "<button id='sg-min' title='收起' style='width:28px;height:28px;border:0;border-radius:6px;",
      "background:#1f2937;color:#e5e7eb;cursor:pointer;font-size:14px;line-height:1'>–</button>",
      "<button id='sg-close' title='关闭' style='width:28px;height:28px;border:0;border-radius:6px;",
      "background:#1f2937;color:#f87171;cursor:pointer;font-size:16px;line-height:1'>×</button>",
      "</div></div>",
      "<div id='sg-sub' style='opacity:.8;margin-bottom:8px;font-size:12px'>画布 ↔ 剪辑 · 模型同步 · Agent</div>",
      "<label style='display:flex;gap:6px;align-items:center;margin-bottom:8px;font-size:12px'>",
      "<input id='sg-interp' type='checkbox'/> 入轨后开线性补帧</label>",
      "<input id='sg-file' type='file' accept='image/*,video/*' style='width:100%;margin-bottom:8px'/>",
      "<button id='sg-send' style='width:100%;padding:8px;border:0;border-radius:8px;margin-bottom:6px;",
      "background:#2563eb;color:#fff;font-weight:600;cursor:pointer'>发送到剪辑</button>",
      "<button id='sg-sync-models' style='width:100%;padding:6px;border:0;border-radius:8px;margin-bottom:6px;",
      "background:#0d9488;color:#fff;font-weight:600;cursor:pointer'>同步模型池</button>",
      "<button id='sg-connect-agent' style='width:100%;padding:6px;border:0;border-radius:8px;margin-bottom:6px;",
      "background:#7c3aed;color:#fff;font-weight:600;cursor:pointer'>连接本地 Agent</button>",
      "<div id='sg-outbox' style='margin-top:6px;font-size:11px;max-height:90px;overflow:auto'></div>",
      "<div id='sg-status' style='margin-top:8px;font-size:11px;opacity:.85'></div>"
    ].join("");
    document.documentElement.appendChild(panel);

    function hidePanel(persist) {
      panel.style.display = "none";
      if (persist) localStorage.setItem("__shiguang_panel_hidden", "1");
    }
    function showPanel() {
      panel.style.display = "block";
      localStorage.removeItem("__shiguang_panel_hidden");
    }
    document.getElementById("sg-close").onclick = function () { hidePanel(true); };
    document.getElementById("sg-min").onclick = function () { hidePanel(true); };
    window.__shiguangShowBridgePanel = showPanel;
    window.__shiguangHideBridgePanel = function () { hidePanel(true); };

    if (localStorage.getItem("__shiguang_panel_hidden") !== "0") {
      hidePanel(false);
    }

    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape" && panel.style.display !== "none") {
        hidePanel(true);
      }
    });

    document.getElementById("sg-send").onclick = async function () {
      var input = document.getElementById("sg-file");
      var file = input && input.files && input.files[0];
      if (!file) { setStatus("请先选择图片或视频文件"); return; }
      var interp = !!(document.getElementById("sg-interp") || {}).checked;
      setStatus("上传中…");
      try {
        var prefs = {};
        try {
          var pr = await fetch(BRIDGE + "/host/prefs?token=" + encodeURIComponent(TOKEN), { headers: hdr() });
          prefs = await pr.json();
        } catch (e) {}
        if (prefs.enable_interpolation) {
          var box = document.getElementById("sg-interp");
          if (box) box.checked = true;
          interp = true;
        }
        var q = new URLSearchParams({
          filename: file.name,
          title: file.name,
          send_to_editor: "1",
          enable_interpolation: interp ? "1" : "0",
          character_id: prefs.character_id || "",
          character_name: prefs.character_name || ""
        });
        var res = await fetch(BRIDGE + "/ingest?" + q.toString(), {
          method: "POST",
          body: file,
          headers: { "Content-Type": file.type || "application/octet-stream" }
        });
        var data = await res.json();
        setStatus(data.message || (data.success ? "已发送" : "失败"));
      } catch (e) {
        setStatus("桥接失败: " + e);
      }
    };

    document.getElementById("sg-sync-models").onclick = function () {
      window.__shiguangSyncModels && window.__shiguangSyncModels(true);
    };
    document.getElementById("sg-connect-agent").onclick = function () {
      window.__shiguangConnectAgent && window.__shiguangConnectAgent();
    };
    window.__shiguangRefreshPrefsSubtitle && window.__shiguangRefreshPrefsSubtitle();
  }

  window.__shiguangRefreshPrefsSubtitle = async function () {
    try {
      var pr = await fetch(BRIDGE + "/host/prefs?token=" + encodeURIComponent(TOKEN), { headers: hdr() });
      var prefs = await pr.json();
      var el = document.getElementById("sg-sub");
      if (!el) return;
      var label = prefs.active_provider_label || prefs.active_provider || "";
      if (label) {
        el.textContent = "激活模型: " + label + " · 画布↔剪辑";
      } else {
        el.textContent = "画布 ↔ 剪辑 · 模型同步 · Agent（请先在模型管理激活）";
      }
    } catch (e) {}
  };

  window.__shiguangSyncModels = async function (forceReload) {
    try {
      setStatus("同步模型池（含 AIGC）…");
      var res = await fetch(BRIDGE + "/host/ai-config-patch?token=" + encodeURIComponent(TOKEN), { headers: hdr() });
      var data = await res.json();
      if (!data.ok || !data.channels) { setStatus("同步失败"); return; }
      var raw = localStorage.getItem(CONFIG_KEY);
      var store = raw ? JSON.parse(raw) : { state: { config: { channels: [] } }, version: 0 };
      if (!store.state) store.state = {};
      if (!store.state.config) store.state.config = {};
      var channels = Array.isArray(store.state.config.channels) ? store.state.config.channels.slice() : [];
      data.channels.forEach(function (ch) {
        var idx = channels.findIndex(function (c) { return c && c.id === ch.id; });
        if (idx >= 0) channels[idx] = Object.assign({}, channels[idx], ch);
        else channels.push(ch);
      });
      store.state.config.channels = channels;
      store.state.config.channelMode = "local";
      if (data.defaults) {
        Object.keys(data.defaults).forEach(function (k) {
          if (data.defaults[k]) store.state.config[k] = data.defaults[k];
        });
      }
      localStorage.setItem(CONFIG_KEY, JSON.stringify(store));
      localStorage.setItem("__shiguang_models_synced_v1", "1");
      localStorage.setItem("__shiguang_aigc_synced_v1", "1");
      var nImg = 0, nVid = 0, nAud = 0;
      data.channels.forEach(function (ch) {
        (ch.models || []).forEach(function (m) {
          if (m.capability === "image") nImg++;
          if (m.capability === "video") nVid++;
          if (m.capability === "audio") nAud++;
        });
      });
      setStatus("已同步 " + data.channels.length + " 渠道（图" + nImg + "/视频" + nVid + "/音频" + nAud + ")" + (forceReload ? "，刷新中…" : ""));
      if (forceReload) setTimeout(function () { location.reload(); }, 400);
    } catch (e) {
      setStatus("同步异常: " + e);
    }
  };

  window.__shiguangApplyAgent = function (url, token, doReload) {
    if (!url || !token) return;
    localStorage.setItem("canvas-agent-url", url);
    localStorage.setItem("canvas-agent-token", token);
    try {
      window.__SHIGUANG_AGENT_URL = url;
      window.__SHIGUANG_AGENT_TOKEN = token;
    } catch (e0) {}
    try {
      var inputs = document.querySelectorAll("input");
      inputs.forEach(function (inp) {
        var ph = ((inp.getAttribute("placeholder") || "") + " " + (inp.getAttribute("aria-label") || "")).toLowerCase();
        var name = ((inp.name || "") + " " + (inp.id || "")).toLowerCase();
        var blob = ph + " " + name;
        if (blob.indexOf("token") >= 0) {
          inp.value = token;
          inp.dispatchEvent(new Event("input", { bubbles: true }));
          inp.dispatchEvent(new Event("change", { bubbles: true }));
        }
        if (blob.indexOf("local") >= 0 || blob.indexOf("url") >= 0 || blob.indexOf("地址") >= 0) {
          if (inp.type === "text" || inp.type === "url" || !inp.type) {
            inp.value = url;
            inp.dispatchEvent(new Event("input", { bubbles: true }));
            inp.dispatchEvent(new Event("change", { bubbles: true }));
          }
        }
      });
      // 自研导演台顶栏有「连接 Agent / Agent面板」——禁止自动 click，否则会循环拉起 :17371 拖垮画布。
      // 仅在 infinite-canvas 旧壳（存在其 Agent 设置输入）时尝试点「连接」。
      var isShiguang =
        !!document.querySelector(".ic-nav-brand, .topbar .brand, .sg-node") ||
        (document.title || "").indexOf("拾光") >= 0;
      if (!isShiguang) {
        var openers = Array.prototype.slice.call(document.querySelectorAll("button, [role=button], a"));
        var agentBtn = openers.find(function (b) {
          if (b.getAttribute && b.getAttribute("data-sg-no-autoclick") === "1") return false;
          var t = (b.textContent || "").replace(/\s+/g, " ").trim();
          return t === "Agent" || t === "本地 Agent";
        });
        if (agentBtn) agentBtn.click();
        setTimeout(function () {
          var buttons = Array.prototype.slice.call(document.querySelectorAll("button"));
          var connectBtn = buttons.find(function (b) {
            if (b.getAttribute && b.getAttribute("data-sg-no-autoclick") === "1") return false;
            var t = (b.textContent || "").replace(/\s+/g, " ").trim();
            return t === "连接" || t.toLowerCase() === "connect";
          });
          if (connectBtn) connectBtn.click();
        }, 400);
      }
    } catch (e) {}
    if (doReload) setTimeout(function () { location.reload(); }, 350);
  };

  window.__shiguangConnectAgent = async function () {
    try {
      setStatus("正在启动 / 连接 Agent（可能需要 1 分钟）…");
      var res = await fetch(BRIDGE + "/host/agent/start?token=" + encodeURIComponent(TOKEN), {
        method: "POST",
        headers: Object.assign({}, hdr(), { "Content-Type": "application/json" }),
        body: "{}",
      });
      var data = await res.json();
      if (!data.ok || !data.token) {
        setStatus(data.message || "Agent 启动失败（也可在宿主顶栏点「连接 Agent」）");
        return;
      }
      window.__shiguangApplyAgent(data.url, data.token, false);
      setStatus(data.message || ("Agent 已连接 " + (data.url || "")));
    } catch (e) {
      setStatus("Agent 连接失败: " + e);
    }
  };

  async function refreshOutbox() {
    try {
      var res = await fetch(BRIDGE + "/editor_outbox");
      var data = await res.json();
      var box = document.getElementById("sg-outbox");
      if (!box || !data.items || !data.items.length) {
        if (box) box.innerHTML = "";
        return;
      }
      box.innerHTML = "<div style='font-weight:600;margin-bottom:4px'>来自剪辑</div>" +
        data.items.slice(-5).reverse().map(function (it) {
          return "<div style='margin:2px 0'><a href='" + it.url + "' download='" +
            (it.filename || "file") + "' style='color:#93c5fd'>" +
            (it.title || it.filename) + "</a></div>";
        }).join("");
    } catch (e) {}
  }

  function boot() {
    ensurePanel();
    if (!localStorage.getItem("__shiguang_aigc_synced_v1")) {
      window.__shiguangSyncModels(true);
    } else if (!localStorage.getItem("__shiguang_models_synced_v1")) {
      window.__shiguangSyncModels(true);
    }
    refreshOutbox();
    setInterval(refreshOutbox, 4000);
    // 若本机已写入 Agent 凭证，延迟自动点连接（Zustand 已 hydrate）
    setTimeout(function () {
      var au = localStorage.getItem("canvas-agent-url");
      var at = localStorage.getItem("canvas-agent-token");
      if (au && at) window.__shiguangApplyAgent(au, at, false);
    }, 1800);
    // ── 画布节点插件：Qt → React 状态同步轮询 ──
    var _lastPluginSnapshot = null;
    function pollCanvasPlugins() {
      fetch(BRIDGE + "/host/plugins?token=" + encodeURIComponent(TOKEN), { headers: hdr() })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (!data || !data.plugins) return;
          var snap = JSON.stringify(data.plugins.map(function (p) {
            return { id: p.id, enabled: !!p.enabled };
          }));
          if (snap === _lastPluginSnapshot) return;
          _lastPluginSnapshot = snap;
          if (typeof window.__shiguangPluginSync === "function") {
            window.__shiguangPluginSync(data.plugins, data.builtin || []);
          }
        })
        .catch(function () { /* bridge 未启动时静默 */ });
    }
    setTimeout(pollCanvasPlugins, 2500);
    setInterval(pollCanvasPlugins, 5000);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
"""


class CanvasBridgeServer:
    """后台线程 HTTP 桥。"""

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
        self.host = host
        self.port = port
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> bool:
        if self._thread and self._thread.is_alive():
            return True
        try:
            self._httpd = ThreadingHTTPServer((self.host, self.port), _BridgeHandler)
            self._httpd.bridge_port = self.port  # type: ignore[attr-defined]
            self._httpd.base_url = self.base_url  # type: ignore[attr-defined]
            self._thread = threading.Thread(
                target=self._httpd.serve_forever, name="CanvasBridge", daemon=True
            )
            self._thread.start()
            logger.info("canvas bridge listening on %s", self.base_url)
            try:
                from app.core.agent_session import agent_sessions

                agent_sessions.mark_restart_paused()
            except Exception:
                logger.debug("mark_restart_paused failed", exc_info=True)
            return True
        except OSError as e:
            # 端口占用：假定已有桥在跑
            logger.warning("canvas bridge bind failed (%s), assume already running", e)
            return True
        except Exception as e:
            logger.error("canvas bridge start failed: %s", e)
            return False

    def stop(self) -> None:
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
            except Exception:
                logger.debug("httpd shutdown failed", exc_info=True)
            self._httpd = None
        self._thread = None


_bridge_singleton: Optional[CanvasBridgeServer] = None


def get_canvas_bridge() -> CanvasBridgeServer:
    global _bridge_singleton
    if _bridge_singleton is None:
        _bridge_singleton = CanvasBridgeServer()
    return _bridge_singleton

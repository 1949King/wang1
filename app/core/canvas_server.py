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
import threading as _threading  # noqa: F401 - 供 canvas_routes_post 经 cs._threading 访问（回归 check_canvas_route_attrs.py）
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from collections.abc import Mapping
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

# ⚠️ 本 import 块整体标 noqa: F401 —— A4 把端点迁到 canvas_routes_get/post 后，
# 其中多个名字本文件不再直接使用，但**被 mixin 经 `cs.xxx` 延迟引用**。
# 不标 noqa 的话 `ruff --fix` 会把它们当死 import 删掉 ⇒ mixin 的 cs.xxx 变
# AttributeError、端点静默失效（2026-09-27 实测踩过：/host/plugins、
# /host/characters、/editor_outbox 及 5 个 *-models 端点）。
# 回归守卫：`_verify/check_canvas_route_attrs.py`（已验证 15 个名字全是 mixin 依赖）。
from app.core.canvas_aigc import (  # noqa: F401
    CAPABILITY_IMAGE,
    CAPABILITY_VIDEO,
    agent_chat_proxy,
    build_host_ai_config_patch,
    generate_audio_via_host,
    generate_image_openai_compatible,
    generate_music_via_host,
    generate_video_via_host,
    inpaint_via_host,
    storyboard_breakdown,
    storyboard_to_camera_plan,
    translate_quality,
    video_storyboard_breakdown,
    DEFAULT_ASPECT,
)
# YuE（乐）全曲生成适配：供 POST /host/yue/plan + /host/yue/generate 经 cs. 访问
# （2026-09-28 接入画布音乐节点与意图卡片；未配置执行端时诚实失败，不造假音频）
from app.core.ai.yue_music import (  # noqa: F401
    probe_engine as yue_probe_engine,
    plan_song as yue_plan_song,
    render_song as yue_render_song,
    transcribe_reference as yue_transcribe_reference,
)
from app.core import canvas_gen_jobs as _gen_jobs
from app.core import gen_task_registry as _gen_task_reg  # 生成任务账本：submit 查重/收尾 + 只读端点
from app.core import project_snapshot as _proj_snap
from app.core.ai import storyboard_memory as _storyboard_memory
from app.core.canvas_bridge import (  # noqa: F401 - 同上方说明：多名字供路由 mixin 经 cs. 访问，勿删
    DEFAULT_HOST,
    DEFAULT_PORT,
    _BUILTIN_PLUGIN_REGISTRY,
    _BATCH_JOBS,
    _BATCH_LOCK,
    _POSTPROCESS_JOBS,
    _POSTPROCESS_LOCK,
    _MODEL_PRELOAD_JOBS,
    _MODEL_PRELOAD_LOCK,
    start_gfpgan_preload,
    _BRIDGE_PREFS,
    _EVT_REPLY_LOCK,
    _EVT_REPLY_QUEUES,
    _EVT_SUBS,
    _EVT_SUBS_LOCK,
    _SESSION_TOKEN,
    _load_canvas_plugins_manifest,
    build_character_prompt,
    list_editor_outbox,
    _probe_duration,
    _remove_canvas_plugin,
    _run_concat_demuxer,
    _run_concat_xfade,
    _safe_filename,
    _toggle_canvas_plugin_enabled,
    _upsert_canvas_plugin,
    _image_to_still_video,
    broadcast_agent_event,
    canvas_inbox_dir,
    canvas_outbox_dir,
    emit_canvas_to_editor,
    get_timeline_snapshot,
    ingest_local_file,
    make_agent_event,
    push_editor_to_canvas,
    replay_agent_events,
)

# 路由表下沉到 canvas_route_registry（整改 A4 批次 0）：端点 mixin 也需要
# @_route_get/@_route_post，从本文件导入会形成循环 → 双方都从 registry 取。
# 本文件内仍用 _route_get / _route_post 注册既有 handler，故一并 re-export。
from app.core.canvas_route_registry import (
    _ROUTES_GET,
    _ROUTES_POST,
    _route_get,
    _route_post,
    dispatch_table as _dispatch_table_impl,
)
from app.core.canvas_routes_dub import CanvasDubRoutesMixin
from app.core.canvas_routes_get import CanvasGetRoutesMixin
from app.core.canvas_routes_post import CanvasPostRoutesMixin
# 2026-10-17 画布审核卡：粗剪 apply/export 端点（canvas_routes_post.py 已逼近
# 2000 行规模阈值，照 dub 先例单开 mixin）。
from app.core.canvas_routes_roughcut import CanvasRoughCutRoutesMixin
from app.core.canvas_routes_code_video import CanvasCodeVideoRoutesMixin
# 2026-10-22 数字人「口型成片」端点（canvas_routes_post.py 已 1967/2000 行，同 dub 先例）。
from app.core.canvas_routes_digital_human import CanvasDigitalHumanRoutesMixin
# 2026-10-23 执行层（混合算力）端点：status / bias / plan（canvas_routes_post.py 已 1,982 行）。
from app.core.canvas_routes_execution import CanvasExecutionRoutesMixin
from app.core.canvas_routes_local_video import CanvasLocalVideoRoutesMixin
from app.core.canvas_routes_team import CanvasTeamRoutesMixin
from app.core.canvas_routes_draw_plan import CanvasDrawPlanRoutesMixin
# 2026-11-20 四项优化 T5：图片转3D / 全景生成端点（canvas_routes_post.py 已逼近
# 2000 行规模阈值，照 dub / roughcut / digital_human 先例单开 mixin）。
from app.core.canvas_routes_scene3d import CanvasScene3dRoutesMixin
from app.core.canvas_http_file import serve_file as _serve_file

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


# V4.46.1 安全刀：CORS 只放行本机 Origin（详见 _BridgeHandler._cors 注释）。
# 注意：urlparse().hostname 会剥掉 IPv6 的方括号（"[::1]" → "::1"），故集合存裸形。
_LOCAL_ORIGIN_HOSTS = {"127.0.0.1", "localhost", "::1", "::ffff:127.0.0.1", "tauri.localhost"}


def _is_local_bridge_origin(origin: str) -> bool:
    """Origin 是否属于本机（Qt WebEngine 3010/3011、Tauri、直连 18765）。"""
    try:
        parsed = urlparse(origin.strip())
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https", "tauri"):
        return False
    host = (parsed.hostname or "").lower()
    if host in _LOCAL_ORIGIN_HOSTS:
        return True
    # 127.0.0.x 全段视为本机（极少数 WebView 用 127.0.0.2 等）
    if host.startswith("127."):
        try:
            return all(0 <= int(p) <= 255 for p in host.split("."))
        except ValueError:
            return False
    return False


def cors_allow_origin(origin: str) -> Optional[str]:
    """返回应写入 Access-Control-Allow-Origin 的值；None = 不写该头（纯函数便于单测）。

    - 无 Origin（curl / 原生请求 / WebView 主文档导航）→ "*"（保持既有行为）
    - 本机 Origin → 回显自身
    - 陌生 Origin → None（浏览器据此拦截跨站脚本读取）
    """
    origin = (origin or "").strip()
    if not origin:
        return "*"
    if _is_local_bridge_origin(origin):
        return origin
    return None


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


# 失败负缓存（现行技术文档 §2d.3）：同一 URL 拉取失败后在 TTL 内不再重试。
# 此前失败无记录 ⇒ 每次启动对同一批死链（pbs.twimg.com 等）重复多轮
# 45s 超时轰炸、刷 warning 日志、拖慢启动。TTL 取 6h：覆盖一次工作会话，
# 隔天重启允许重试一次，远端恢复后可自愈（成功后主动清除标记）。
_PROMPT_IMAGE_FAIL_TTL_SEC = 6 * 3600


def _prompt_image_fail_path(url: str) -> Path:
    return _PROMPT_IMAGE_CACHE_DIR / f"{_prompt_image_cache_key(url)}.fail"


def _prompt_image_failed_recently(url: str) -> bool:
    """TTL 内曾拉取失败 → True（端点不再重试）。判定本身出错时不拦（宁可重试）。"""
    try:
        fp = _prompt_image_fail_path(url)
        return fp.is_file() and (time.time() - fp.stat().st_mtime) < _PROMPT_IMAGE_FAIL_TTL_SEC
    except Exception:
        return False


def _mark_prompt_image_failed(url: str) -> None:
    try:
        _PROMPT_IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _prompt_image_fail_path(url).write_text(f"{time.time():.0f}\n", encoding="utf-8")
    except Exception:
        logger.debug("prompt-image fail-cache write skipped", exc_info=True)


def _clear_prompt_image_failed(url: str) -> None:
    try:
        _prompt_image_fail_path(url).unlink(missing_ok=True)
    except Exception:
        logger.debug("prompt-image fail-cache clear skipped", exc_info=True)


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


# ── 路由表（P1-1 · 绞杀者模式；2026-09-27 整改 A4 下沉到 canvas_route_registry）
# 历史包袱：`do_GET` / `do_POST` 曾各是一条 600~1050 行的 `if path == ...` 链。
# 绞杀者做法：新端点一律用 @_route_get / @_route_post 注册进路由表，请求进来
# 先查表，未命中才回落 if 链；老链端点在 A4 整改中**逐条迁出**到
# `canvas_routes_get.py`（GET 25 个）/ `canvas_routes_post.py`（POST）。
#
# ⚠️ 曾经的教训：端点被追加到文件末尾 → 落进上一个函数体内、且在 `return` 之后
#    → 语法合法、静态检查全绿、但永远走不到（`/host/plugins/install` 就是这样死的）。
#    `_verify/check_canvas_routes.py` 现在会用 AST 检测这类不可达路由。
# 路由表本体与装饰器已下沉到 `app/core/canvas_route_registry.py`（顶部 import）。


class _BridgeHandler(CanvasGetRoutesMixin, CanvasPostRoutesMixin, CanvasDubRoutesMixin, CanvasRoughCutRoutesMixin, CanvasCodeVideoRoutesMixin, CanvasDigitalHumanRoutesMixin, CanvasExecutionRoutesMixin, CanvasLocalVideoRoutesMixin, CanvasTeamRoutesMixin, CanvasDrawPlanRoutesMixin, CanvasScene3dRoutesMixin, BaseHTTPRequestHandler):
    server_version = "ShiguangCanvasBridge/1.0"

    def log_message(self, fmt: str, *args) -> None:
        logger.debug("bridge %s - %s", self.address_string(), fmt % args)

    def handle(self) -> None:
        try:
            super().handle()
        except (OSError, ConnectionResetError):
            logger.debug("bridge client closed connection: %s", self.address_string())
        except BrokenPipeError:
            logger.debug("bridge broken pipe: %s", self.address_string())

    def _cors(self) -> None:
        # V4.46.1 安全刀：不再 `Access-Control-Allow-Origin: *`。
        # 本机桥暴露角色库/时间线/收件箱文件，`*` 意味着用户浏览器里任意网页（含恶意页）
        # 都能带 fetch 读走这些数据。收紧为**只放行本机 Origin**（纯函数 cors_allow_origin）：
        #   - http(s)://127.0.0.1|localhost|[::1](:任意端口)（Qt WebEngine 从 3010/3011 拉起）
        #   - tauri.localhost / tauri://localhost（Tauri 宿主生产形态）
        # 无 Origin（curl/原生请求）回 "*"；陌生 Origin **不写 ACAO** ⇒ 浏览器拦截跨站读取。
        allow = cors_allow_origin(self.headers.get("Origin") or "")
        if allow is not None:
            self.send_header("Access-Control-Allow-Origin", allow)
            if allow != "*":
                self.send_header("Vary", "Origin")
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
        self._write_body(body)

    def _write_body(self, body: bytes) -> None:
        """写响应体；客户端已断开时静默丢弃。

        浏览器取消在途请求（组件卸载 / 切页 / StrictMode 双调用）会让这里抛
        ``ConnectionAbortedError``，冒泡上去会被记成「路由处理失败」+ 再写一次
        500（必然再失败），把真故障淹在噪音里（2026-10-25 排查实证）。
        """
        try:
            self.wfile.write(body)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError) as exc:
            logger.debug("响应写失败，客户端已断开: %s", exc)

    def _bytes(self, code: int, body: bytes, content_type: str, *, cache: bool = False) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if cache:
            self.send_header("Cache-Control", "public, max-age=86400")
        self._cors()
        self.end_headers()
        self._write_body(body)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.end_headers()

    def _dispatch_table(self, table: Dict[str, str], path: str, **kw) -> bool:
        """路由表分发（实现已下沉 canvas_route_registry.dispatch_table）。

        命中则执行并返回 True，未命中返回 False（交给 if 链兜底）。
        """
        return _dispatch_table_impl(self, table, path, **kw)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        # ── 路由表优先（新增端点走这里）；未命中才回落下面的老 if 链 ──
        if self._dispatch_table(_ROUTES_GET, path, parsed=parsed):
            return
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

        # ── A4 批次 1（2026-09-27）：以下 25 个 GET 端点已迁出到
        #    canvas_routes_get.py（经 @_route_get 注册，上面路由表分发即可命中）──
        # /host/budget · calls · compliance-check · characters · prefs · prompt-fetch ·
        # prompt-bundled · prompt-image · providers · ai-config-patch · comfyui/status ·
        # image|video|audio|music|chat-models · tools · agent/session · agent/tasks ·
        # agent · editor_outbox · timeline-snapshot · plugins · video-batch ·
        # video-postprocess · model-preload
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
            finally:
                with _EVT_SUBS_LOCK:
                    try:
                        _EVT_SUBS.remove(sub_q)
                    except ValueError:
                        logger.debug("event subscriber removal failed", exc_info=True)
            return
        if path.startswith("/editor_file/"):
            name = _safe_filename(path.split("/editor_file/", 1)[-1])
            fpath = os.path.join(canvas_outbox_dir(), name)
            if not os.path.isfile(fpath):
                self._json(404, {"ok": False, "message": "file not found"})
                return
            # V4.46.1：流式 + Range（原整读内存 → 大视频 seek 卡顿/内存尖峰）
            _serve_file(self, fpath)
            return
        if path.startswith("/inbox_file/"):
            name = _safe_filename(path.split("/inbox_file/", 1)[-1])
            fpath = os.path.join(canvas_inbox_dir(), name)
            if not os.path.isfile(fpath):
                self._json(404, {"ok": False, "message": "file not found"})
                return
            _serve_file(self, fpath)
            return
        self._json(404, {"ok": False, "message": "not found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length > 0 else b""
        ctype = (self.headers.get("Content-Type") or "").lower()

        # ── 路由表优先（新增端点走这里）；未命中才回落下面的老 if 链 ──
        if self._dispatch_table(_ROUTES_POST, parsed.path, parsed=parsed, raw=raw, ctype=ctype):
            return


        # ── A4 批次 2/3（2026-09-27）：以下 29 个 POST 端点已迁出到
        #    canvas_routes_post.py（经 @_route_post 注册，上面路由表分发即可命中）──
        # /host/tauri-closing · agent/{session,reply,start,chat} · compliance-check ·
        # video-generate · budget/set · ingest · ingest_path · push_from_editor ·
        # generate-image|video|audio|music · comfyui/run · pose-extract ·
        # pose-video-encode · inpaint · video-batch · interpolate · video-concat ·
        # batch-to-timeline · project-agent/chat · upload-asset · tools/run ·
        # storyboard-breakdown · storyboard-camera-plan · canvas-ai-review
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
        # 生成参数血缘块（可选）：前端 JSON 串经 query 透传，非法/缺省 ⇒ None（零行为变化）
        generation: Optional[Dict[str, Any]] = None
        gen_raw = (qs.get("generation_json") or [""])[0]
        if gen_raw:
            try:
                _gen = json.loads(gen_raw)
                if isinstance(_gen, dict) and _gen:
                    generation = _gen
            except (ValueError, TypeError):
                generation = None

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
                    generation=generation,
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
            generation=generation,
        )
        self._json(200 if res.get("success") else 400, res)
        return


    # ── 画布节点插件操作（install / toggle / uninstall）─────────────────
    # 2026-09-13 修复：这三个端点原先被追加在 `_handle_ingest()` 的 `return` 之后，
    # 语法合法但永不执行 —— 前端点「安装/启用/卸载插件」只会拿到 do_POST 末尾的 404。
    # 现改为 @_route_post 注册进路由表。新增端点请照此办理，不要往老 if 链里塞。

    @_route_post("/host/plugins/install")
    def _h_plugins_install(self, parsed, raw: bytes, ctype: str) -> None:
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

    @_route_post("/host/plugins/toggle")
    def _h_plugins_toggle(self, parsed, raw: bytes, ctype: str) -> None:
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

    @_route_post("/host/plugins/uninstall")
    def _h_plugins_uninstall(self, parsed, raw: bytes, ctype: str) -> None:
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

    # ── 分镜记忆规划：把记忆衰减模型换算成「每镜该给多少秒」─────────────
    # 类型由人在画布上选（细节/意义/情绪），后端只算保留率与建议时长。
    # 数学在 app/core/ai/storyboard_memory.py，校验 _verify/check_storyboard_memory.py。
    @_route_post("/host/storyboard-memory-plan")
    def _h_storyboard_memory_plan(self, parsed, raw: bytes, ctype: str) -> None:
        if not _check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"ok": False, "message": "invalid json"})
            return
        if not isinstance(body, dict):
            self._json(400, {"ok": False, "message": "body must be an object"})
            return
        rows = body.get("rows")
        if rows is None:
            rows = []
        if not isinstance(rows, list):
            self._json(400, {"ok": False, "message": "rows must be an array"})
            return
        try:
            result = _storyboard_memory.plan(
                rows,
                t_hours=float(body.get("t_hours", _storyboard_memory.DEFAULT_T_HOURS)),
                min_duration=float(body.get("minDuration", _storyboard_memory.MIN_DURATION)),
                max_duration=float(body.get("maxDuration", _storyboard_memory.MAX_DURATION)),
            )
        except (TypeError, ValueError) as exc:
            self._json(400, {"ok": False, "message": f"参数非法: {exc}"})
            return
        except Exception as exc:
            logger.exception("[/host/storyboard-memory-plan] 失败")
            self._json(500, {"ok": False, "message": str(exc)})
            return
        # V4.15.2 P0-1 补强：apply=true 时把 plan 真的落回 _clips（不再只回字符串）
        applied_info: Optional[Dict[str, Any]] = None
        if body.get("apply") is True:
            plan_rows = result.get("rows") or []
            # 把 plan 行投影成 {clip_id, duration} 列表
            durations: List[Dict[str, Any]] = []
            for pr in plan_rows:
                if not isinstance(pr, dict):
                    continue
                cid = pr.get("id")
                dur = pr.get("suggestedDuration")
                if isinstance(cid, str) and cid and isinstance(dur, (int, float)):
                    durations.append({"clip_id": cid, "duration": float(dur)})
            # 调 EditorModule 的公开 agent 方法（无 provider 时诚实失败）
            from app.core.project_snapshot import get_full_clips  # 触发 editor 加载
            # 关键路径：写回 _clips 必须有 provider（set_clips_writer 在 editor 启动时注册）
            try:
                from app.core.project_snapshot import write_clips
            except Exception:
                write_clips = None  # type: ignore
            # 走 agent 公开方法（agent_apply_storyboard_durations）需要 EditorModule 实例
            # 桥上不直接 import EditorModule（避免循环 + 桥层不应依赖上帝类）。
            # 方案：通过 /host/project-snapshot 的 writer 通道（已注册）+ 临时合约：
            # 把 {clip_id, duration} 转成 [{id, duration, ...} + 原 _clips 的其它字段] → 写回。
            # 这一步由本端点直接做（因为它能读 get_full_clips 拿到完整 _clips）。
            existing = get_full_clips() or []
            existing_by_id = {c.get("id"): c for c in existing if isinstance(c, Mapping) and c.get("id")}
            if not existing_by_id:
                # 没有可写回的 _clips（剪辑未就绪或未注册）
                applied_info = {"ok": False, "message": "剪辑模块未就绪或未注册时间线 writer"}
            else:
                new_clips: List[Dict[str, Any]] = []
                applied = 0
                unmatched: List[str] = []
                for d in durations:
                    cid = d["clip_id"]
                    base = existing_by_id.get(cid)
                    if not base:
                        unmatched.append(cid)
                        continue
                    new_c = dict(base)
                    new_c["duration"] = d["duration"]
                    # out_point 跟着改（in_point 起点不动）
                    try:
                        in_pt = float(base.get("in_point", 0) or 0)
                        new_c["out_point"] = in_pt + d["duration"]
                    except Exception:
                        logger.debug("解析 in_point 失败，跳过 out_point 计算", exc_info=True)
                    new_clips.append(new_c)
                    applied += 1
                # 没改的也带上（保证不丢片段）
                applied_ids = {c.get("id") for c in new_clips}
                for c in existing:
                    if c.get("id") not in applied_ids:
                        new_clips.append(dict(c))
                if write_clips is None:
                    applied_info = {"ok": False, "message": "project_snapshot 模块缺失"}
                else:
                    wres = write_clips(new_clips)
                    applied_info = {
                        "ok": wres.get("ok") is True,
                        "applied": applied,
                        "unmatched": unmatched,
                        "message": wres.get("message") or f"已应用 {applied} 个片段",
                    }
        out: Dict[str, Any] = {"ok": True, "plan": result}
        if applied_info is not None:
            out["applied"] = applied_info
        # V4.15.2: result 本身是 plan 字典（rows / totalSuggested / ok）
        # 为向后兼容既有调用（直接读 result.rows）直接平铺 result 字段
        if isinstance(result, dict):
            for k, v in result.items():
                out.setdefault(k, v)
        self._json(200, out)

    # ── 生成任务：异步 · 真实进度 · 可取消 ──────────────────────────────
    # 背景：生图/生视频原先是一次阻塞 POST（超时档 120~300s），前端全程转圈、
    # 无法取消；批量还是串行 for。这里改造成任务制：
    #     submit 立即返回 job_id → status/list 轮询 → cancel 中断在途请求。
    #
    # 进度诚实性（与「诚实失败」同源）：上游 provider 只给一次阻塞响应、没有进度
    # 信号时，`progress` 必须保持 null，前端只显示「阶段 + 已用时」；
    # 只有生视频的后处理（超分/补帧）有真回调，才写真实百分比。
    #
    # 任务表与线程池在 app/core/canvas_gen_jobs.py（新模块，冻结区零改动）。

    _GEN_KINDS = ("image", "video", "audio", "music")

    _GEN_PAYLOAD_KEYS: Dict[str, Tuple[str, ...]] = {
        "image": ("prompt", "model", "channel_id", "size", "reference_image", "strength", "quality", "seed", "aspect"),
        "video": (
            "prompt", "model", "channel_id", "duration", "size",
            "reference_image", "reference_video", "first_frame", "last_frame", "quality", "aspect",
            "referenceVideo", "firstFrame", "lastFrame",
        ),
        "audio": ("prompt", "model", "channel_id", "voice"),
        "music": ("prompt", "model", "channel_id", "style", "lyrics", "title", "instrumental"),
    }

    def _ng_count(self) -> None:
        """生成失败时累计 NG 计数（与老端点行为一致，失败也要记账）。"""
        try:
            from app.core.ai_engine import AIEngine

            AIEngine().increment_ng_count(1)
        except Exception:
            logger.debug("increment_ng_count failed", exc_info=True)

    def _build_gen_callable(self, kind: str, kwargs: Dict[str, Any]):
        """把「kind + 白名单参数」编译成一个 ``fn(report)`` 交给任务表执行。

        ⚠️ 这里是老端点 ``/host/generate-image`` ``/host/generate-video`` 的**保真搬运**：
        画质档 → size 换算、NG 计数、GFPGAN 后台预载、后处理任务注册，
        一个都不能少，否则异步化会静默丢功能。
        """
        port = int(getattr(self.server, "bridge_port", DEFAULT_PORT))

        def _run_image(report) -> Dict[str, Any]:
            quality = str(kwargs.get("quality") or "standard")
            aspect = str(kwargs.get("aspect") or "") or DEFAULT_ASPECT
            size = str(kwargs.get("size") or "") or translate_quality(quality, CAPABILITY_IMAGE, aspect)["size"]
            report.stage("await_provider", "等待模型返回图像")
            # 🔴 2026-11-01 修：此前这里直接调 `generate_image_openai_compatible`（**纯云端**），
            #   而同步端点 `POST /host/generate-image` 早在 2026-10-23 就接了混合调度
            #   （`generate_image_hybrid`）。前端默认走**异步任务化**（submit + 轮询），
            #   于是「算力滑块拉到本地 / 本地 SD 已下载」时照样只走云端
            #   ⇒ 报「没有可用的 AIGC 生图渠道」，本地模型形同不存在。
            #   异步端点必须与同步端点**同一实现**，否则「保真搬运」会静默丢掉功能。
            from app.core.ai.hybrid_dispatch import generate_image_hybrid

            res = generate_image_hybrid(
                prompt=str(kwargs.get("prompt") or ""),
                model=str(kwargs.get("model") or ""),
                size=size,
                channel_id=str(kwargs.get("channel_id") or ""),
                reference_image=str(kwargs.get("reference_image") or ""),
                strength=float(kwargs.get("strength") or 0.65),
                quality=quality,
                seed=kwargs.get("seed"),
                aspect=aspect,
            )
            if not res.get("ok"):
                self._ng_count()
            # 画质档含人脸修复时后台预载 GFPGAN（真进度，前端按 job_id 轮询）
            try:
                if isinstance(res, dict) and translate_quality(quality, CAPABILITY_IMAGE, aspect).get("face_restore"):
                    preload_job_id = start_gfpgan_preload()
                    res["preload_job_id"] = preload_job_id
                    with _MODEL_PRELOAD_LOCK:
                        _pjob = _MODEL_PRELOAD_JOBS.get(preload_job_id)
                    res["face_restore_ready"] = bool(_pjob and _pjob.get("ready"))
            except Exception as exc:
                logger.debug("GFPGAN 预载触发失败: %s", exc)
            return res

        def _run_video(report) -> Dict[str, Any]:
            quality = str(kwargs.get("quality") or "standard")
            aspect = str(kwargs.get("aspect") or "") or DEFAULT_ASPECT
            size = str(kwargs.get("size") or "") or translate_quality(quality, CAPABILITY_VIDEO, aspect)["size"]
            quality_params = translate_quality(quality, CAPABILITY_VIDEO, aspect)

            postprocess_job_id = ""
            progress_cb = None
            done_cb = None
            if quality_params.get("frame_interpolate") or quality_params.get("upscale"):
                postprocess_job_id = uuid.uuid4().hex[:12]
                with _POSTPROCESS_LOCK:
                    _POSTPROCESS_JOBS[postprocess_job_id] = {
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
                    with _POSTPROCESS_LOCK:
                        _pjob = _POSTPROCESS_JOBS.get(postprocess_job_id)
                        if _pjob:
                            _pjob["progress"] = int(pct)
                            _pjob["message"] = message or ""
                            _pjob["updated_at"] = time.time()
                    # 后处理是整条链路里唯一有真实百分比的阶段，如实上报给任务表
                    report.stage("postprocess", "后处理（超分/补帧）")
                    report.progress(pct)
                    if message:
                        report.note(message)

                def done_cb(src_path: str, final_path: str) -> None:
                    with _POSTPROCESS_LOCK:
                        _pjob = _POSTPROCESS_JOBS.get(postprocess_job_id)
                        if not _pjob:
                            return
                        if final_path and final_path != src_path and os.path.isfile(final_path):
                            _pjob["video_path"] = final_path
                            _pjob["video_url"] = (
                                f"http://127.0.0.1:{int(port)}/inbox_file/"
                                f"{os.path.basename(final_path)}"
                            )
                            _pjob["postprocessed"] = True
                        _pjob["status"] = "done"
                        _pjob["progress"] = 100
                        _pjob["message"] = "后处理完成"
                        _pjob["updated_at"] = time.time()

            report.stage("await_provider", "等待模型返回视频")
            res = generate_video_via_host(
                prompt=str(kwargs.get("prompt") or ""),
                model=str(kwargs.get("model") or ""),
                channel_id=str(kwargs.get("channel_id") or ""),
                duration=float(kwargs.get("duration") or 5.0),
                size=size,
                reference_image=str(kwargs.get("reference_image") or ""),
                reference_video=str(kwargs.get("reference_video") or kwargs.get("referenceVideo") or ""),
                first_frame=str(kwargs.get("first_frame") or kwargs.get("firstFrame") or ""),
                last_frame=str(kwargs.get("last_frame") or kwargs.get("lastFrame") or ""),
                bridge_port=int(port),
                quality=quality,
                aspect=aspect,
                postprocess_progress_callback=progress_cb,
                postprocess_done_callback=done_cb,
            )
            if postprocess_job_id and res.get("ok") and res.get("postprocessing"):
                res["postprocess_job_id"] = postprocess_job_id
            elif postprocess_job_id:
                with _POSTPROCESS_LOCK:
                    _POSTPROCESS_JOBS.pop(postprocess_job_id, None)
            if not res.get("ok"):
                self._ng_count()
            return res

        def _run_audio(report) -> Dict[str, Any]:
            report.stage("await_provider", "等待模型返回音频")
            res = generate_audio_via_host(
                prompt=str(kwargs.get("prompt") or ""),
                model=str(kwargs.get("model") or ""),
                channel_id=str(kwargs.get("channel_id") or ""),
                voice=str(kwargs.get("voice") or ""),
                bridge_port=int(port),
            )
            if not res.get("ok"):
                self._ng_count()
            return res

        def _run_music(report) -> Dict[str, Any]:
            report.stage("await_provider", "等待模型返回音乐")
            res = generate_music_via_host(
                prompt=str(kwargs.get("prompt") or ""),
                model=str(kwargs.get("model") or ""),
                channel_id=str(kwargs.get("channel_id") or ""),
                style=str(kwargs.get("style") or ""),
                lyrics=str(kwargs.get("lyrics") or ""),
                title=str(kwargs.get("title") or ""),
                instrumental=bool(kwargs.get("instrumental")),
                bridge_port=int(port),
            )
            if not res.get("ok"):
                self._ng_count()
            return res

        return {
            "image": _run_image,
            "video": _run_video,
            "audio": _run_audio,
            "music": _run_music,
        }.get(kind, lambda report: {"ok": False, "message": f"未知生成类型: {kind}"})

    @_route_post("/host/video-storyboard")
    def _h_video_storyboard(self, parsed, raw: bytes, ctype: str) -> None:
        """一键拉片：参考视频 → 可编辑分镜表。

        接受 { path }（本地绝对路径）或 { url }（/inbox_file/ 或 http inbox URL）。
        后端检测镜头边界 + 抽代表帧 + 算色调/亮度 + 推断景别，返回 shots 数组。
        若 body.use_llm 为真，再走本机视觉模型逐镜解析景别/运镜/画面描述
        （canvas_shot_vision.enrich_shot_table，素材不出机；失败诚实降级）。
        """
        if not _check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized", "shots": []})
            return
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"ok": False, "message": "invalid json", "shots": []})
            return
        if not isinstance(body, dict):
            self._json(400, {"ok": False, "message": "body must be an object", "shots": []})
            return

        local_path = str(body.get("path") or "")
        if not local_path:
            src = str(body.get("url") or "")
            if "/inbox_file/" in src:
                name = _safe_filename(src.split("/inbox_file/", 1)[-1])
                local_path = os.path.join(canvas_inbox_dir(), name)
        if not local_path or not os.path.isfile(local_path):
            self._json(400, {"ok": False, "message": "视频文件不存在，请先上传参考片", "shots": []})
            return

        port = getattr(self.server, "bridge_port", DEFAULT_PORT)
        try:
            res = video_storyboard_breakdown(
                local_path,
                use_llm=False,
                max_shots=int(body.get("max_shots") or 30),
                frames_dir=canvas_inbox_dir(),
                frame_url_prefix=f"http://127.0.0.1:{int(port)}/inbox_file",
            )
            # I1 本地拉片：① 补齐画面列（base 抽帧走 %TEMP%，本机 AV 锁 %TEMP% 时会全空）
            # ② 若请求 use_llm，再走本机视觉模型逐镜解析景别/运镜/描述（素材不出机）。
            if res.get("ok"):
                try:
                    from app.core.canvas_shot_vision import (
                        enrich_shot_table,
                        ensure_shot_frames,
                    )
                except ImportError:
                    from core.canvas_shot_vision import (  # type: ignore
                        enrich_shot_table,
                        ensure_shot_frames,
                    )
                ensure_shot_frames(
                    res,
                    local_path,
                    frames_dir=canvas_inbox_dir(),
                    frame_url_prefix=f"http://127.0.0.1:{int(port)}/inbox_file",
                )
                if body.get("use_llm"):
                    enrich_shot_table(res, local_path, model=str(body.get("vision_model") or ""))
        except Exception as e:
            logger.exception("[/host/video-storyboard] 失败")
            self._json(500, {"ok": False, "message": str(e), "shots": []})
            return
        code = 200 if res.get("ok") else 400
        self._json(code, res)

    @_route_post("/host/still-video")
    def _h_still_video(self, parsed, raw: bytes, ctype: str) -> None:
        """图 → 静帧视频（成片闭环 · 伪真图卡）。

        接受三类输入，统一转成本地 .mp4 路径数组：
          - /inbox_file/xxx.png 或 http://127.0.0.1:port/inbox_file/xxx.png（inbox URL）
          - data:image/...;base64,xxx（data URL）
          - 本地绝对路径（已是 .mp4 的视频原样返回）
        图片复用 canvas_bridge._image_to_still_video 转静帧视频（失败跳过并记 warning）。
        """
        if not _check_host_token(self):
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
        raw_items = body.get("items")
        if raw_items is None:
            raw_items = body.get("paths")
        if raw_items is None:
            raw_items = body.get("urls")
        if raw_items is None:
            raw_items = []
        if not isinstance(raw_items, list):
            self._json(400, {"ok": False, "message": "items 必须是数组"})
            return
        try:
            duration = float(body.get("duration") or 3.0)
        except (TypeError, ValueError):
            duration = 3.0

        import base64 as _b64

        results: List[Dict[str, Any]] = []
        for item in raw_items:
            if not isinstance(item, str) or not item.strip():
                continue
            src = item.strip()
            local_path = ""
            # 1) inbox URL → 本地路径
            if "/inbox_file/" in src:
                name = _safe_filename(src.split("/inbox_file/", 1)[-1])
                local_path = os.path.join(canvas_inbox_dir(), name)
            # 2) data URL → 落盘 inbox
            elif src.startswith("data:image/") and ";base64," in src:
                try:
                    head, b64 = src.split(";base64,", 1)
                    ext = "png"
                    if "jpeg" in head or "jpg" in head:
                        ext = "jpg"
                    elif "webp" in head:
                        ext = "webp"
                    payload = _b64.b64decode(b64)
                    name = f"{int(time.time())}_{uuid.uuid4().hex[:8]}.{ext}"
                    dest = os.path.join(canvas_inbox_dir(), name)
                    with open(dest, "wb") as f:
                        f.write(payload)
                    local_path = dest
                except Exception as exc:
                    logger.warning("[still-video] data URL 落盘失败: %s", exc)
                    continue
            # 3) 本地绝对路径
            else:
                local_path = src

            if not os.path.isfile(local_path):
                logger.warning("[still-video] 文件不存在，跳过: %s", local_path)
                continue
            ext = os.path.splitext(local_path)[1].lower()
            if ext in (".mp4", ".mov", ".webm", ".m4v", ".mkv"):
                # 已是视频，原样返回
                results.append({"ok": True, "path": os.path.abspath(local_path), "kind": "video"})
                continue
            if ext not in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
                logger.warning("[still-video] 不支持的图片格式，跳过: %s", local_path)
                continue
            out = _image_to_still_video(local_path, duration_sec=duration)
            if out:
                results.append({"ok": True, "path": os.path.abspath(out), "kind": "still"})
            else:
                results.append({"ok": False, "path": local_path, "kind": "still", "error": "转视频失败"})

        self._json(200, {
            "ok": True,
            "count": len(results),
            "results": results,
            "paths": [r["path"] for r in results if r.get("ok")],
        })

    @_route_post("/host/generation/submit")
    def _h_generation_submit(self, parsed, raw: bytes, ctype: str) -> None:
        if not _check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"ok": False, "message": "invalid json"})
            return
        if not isinstance(body, dict):
            self._json(400, {"ok": False, "message": "body must be an object"})
            return
        kind = str(body.get("kind") or "").strip().lower()
        if kind not in self._GEN_KINDS:
            self._json(400, {"ok": False, "message": f"kind 必须是 {list(self._GEN_KINDS)} 之一"})
            return
        raw_payload = body.get("payload")
        if raw_payload is None:
            raw_payload = {}
        if not isinstance(raw_payload, dict):
            self._json(400, {"ok": False, "message": "payload must be an object"})
            return
        allowed = self._GEN_PAYLOAD_KEYS.get(kind, ())
        kwargs = {k: raw_payload[k] for k in allowed if k in raw_payload and raw_payload[k] is not None}
        if not str(kwargs.get("prompt") or kwargs.get("lyrics") or "").strip():
            self._json(400, {"ok": False, "message": "提示词为空"})
            return
        try:
            max_attempts = int(body.get("max_attempts") or 1)
        except (TypeError, ValueError):
            max_attempts = 1
        label = str(body.get("label") or "").strip()
        if not label:
            label = (str(kwargs.get("prompt") or "") or "生成任务")[:24]
        # ── 生成任务账本（§6.9-P1 正式化，2026-10-18）──────────────────
        # 幂等查重：同「介质+prompt+model+尺寸+种子+时长+渠道」已有活跃任务
        # ⇒ 直接回既有 job，防重复计费；前端刻意重抽传 body.force=true 绕过。
        # 账本是优化项：registry 内部吞一切记录异常，绝不拖垮生成主链路。
        _store = _gen_task_reg.get_store()
        _rec, _deduped = _store.begin(kind, {
            "prompt": str(kwargs.get("prompt") or ""),
            "model": str(kwargs.get("model") or ""),
            "size": str(kwargs.get("size") or ""),
            "seed": kwargs.get("seed"),
            "duration": kwargs.get("duration"),
            "channel_id": str(kwargs.get("channel_id") or ""),
        }, force=bool(body.get("force")))
        _task_id = str(_rec.get("task_id") or "")
        if _deduped:
            _existing = _gen_jobs.get_job(str(_rec.get("job_id") or ""))
            if _existing and _existing.get("status") not in _gen_task_reg.TERMINAL_STATUSES:
                self._json(200, {"ok": True, "job": _existing,
                                 "deduped": True, "task_id": _task_id})
                return
        _base_fn = self._build_gen_callable(kind, kwargs)

        def _fn_with_ledger(report):
            """任务体包装：收尾把终态写回账本（重试时后写覆盖前写，finish 幂等）。"""
            try:
                res = _base_fn(report)
            except _gen_jobs.GenCancelled as exc:
                _store.finish(_task_id, "cancelled", error=str(exc)[:300])
                raise
            except Exception as exc:
                _store.finish(_task_id, "failed", error=str(exc)[:300])
                raise
            if isinstance(res, dict) and res.get("ok"):
                _store.finish(_task_id, "done",
                              result_paths=_gen_task_reg.extract_result_paths(res))
            else:
                _msg = str((res or {}).get("message") if isinstance(res, dict) else res)[:300]
                _store.finish(_task_id, "failed", error=_msg or "生成失败")
            return res

        job = _gen_jobs.submit(
            kind,
            _fn_with_ledger,
            label=label,
            meta={
                "model": str(kwargs.get("model") or ""),
                "channel_id": str(kwargs.get("channel_id") or ""),
                "size": str(kwargs.get("size") or ""),
                "duration": kwargs.get("duration"),
                "task_id": _task_id,
            },
            max_attempts=max_attempts,
        )
        _store.set_job_id(_task_id, str(job.get("job_id") or ""))
        self._json(200, {"ok": True, "job": job, "task_id": _task_id})

    @_route_get("/host/generation/status")
    def _h_generation_status(self, parsed) -> None:
        if not _check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        qs = parse_qs(parsed.query)
        job_id = str((qs.get("job_id") or [""])[0]).strip()
        if not job_id:
            self._json(400, {"ok": False, "message": "job_id required"})
            return
        job = _gen_jobs.get_job(job_id)
        if job is None:
            self._json(404, {"ok": False, "message": "任务不存在或已过期"})
            return
        self._json(200, {"ok": True, "job": job})

    @_route_get("/host/generation/list")
    def _h_generation_list(self, parsed) -> None:
        if not _check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        qs = parse_qs(parsed.query)
        try:
            limit = int((qs.get("limit") or ["30"])[0])
        except (TypeError, ValueError):
            limit = 30
        self._json(200, {
            "ok": True,
            "jobs": _gen_jobs.list_jobs(limit),
            "stats": _gen_jobs.queue_stats(),
        })

    @_route_post("/host/generation/cancel")
    def _h_generation_cancel(self, parsed, raw: bytes, ctype: str) -> None:
        if not _check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"ok": False, "message": "invalid json"})
            return
        job_id = str((body or {}).get("job_id") or "").strip()
        if not job_id:
            self._json(400, {"ok": False, "message": "job_id required"})
            return
        res = _gen_jobs.cancel(job_id, str((body or {}).get("reason") or "用户取消"))
        self._json(200 if res.get("ok") else 404, res)

    # ── 生成任务账本只读端点（§6.9-P1 正式化，照 /host/clip-lineage 先例）──
    # 供前端/Agent 跨进程查任务血缘：canvas_gen_jobs 是内存态，进程退了
    # 账本（data/gen_tasks.json）仍记得 prompt/seed/产物/节点。

    @_route_get("/host/gen-task")
    def _h_gen_task(self, parsed) -> None:
        if not _check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        qs = parse_qs(parsed.query)
        task_id = str((qs.get("task_id") or [""])[0]).strip()
        key = str((qs.get("key") or [""])[0]).strip()
        store = _gen_task_reg.get_store()
        rec = store.get_task(task_id) if task_id else None
        if rec is None and key:
            rec = store.latest_by_key(key)
        if rec is None:
            self._json(404, {"ok": False, "message": "任务记录不存在"})
            return
        self._json(200, {"ok": True, "task": rec})

    @_route_get("/host/asset-node")
    def _h_asset_node(self, parsed) -> None:
        if not _check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        qs = parse_qs(parsed.query)
        asset_id = str((qs.get("asset_id") or [""])[0]).strip()
        if not asset_id:
            self._json(400, {"ok": False, "message": "asset_id required"})
            return
        rec = _gen_task_reg.get_store().get_asset(asset_id)
        if rec is None:
            self._json(404, {"ok": False, "message": "资产记录不存在"})
            return
        self._json(200, {"ok": True, "asset": rec})

    # ── 工程级快照（P1-4）────────────────────────────────────────────
    # 把剪辑器时间线（完整 _clips，非摘要）与画布 bundle 一起打包成工程快照，
    # 支持「可回滚 / 可 diff / 可直导剪辑器」。时间线读写经 project_snapshot 的
    # provider 回调落到 EditorModule，桥不直接 import 上帝类。
    # 前端（generationQueue 同款）通过 /host/project-snapshot/* 合入 exportProjectZip。

    @_route_get("/host/project-snapshot/export")
    def _h_project_snapshot_export(self, parsed) -> None:
        if not _check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        clips = _proj_snap.get_full_clips()
        if clips is None:
            # 未注册完整 provider：回退到摘要快照，至少让「直导」不炸
            snap = get_timeline_snapshot()
            clips = list(snap.get("clips") or [])
        timeline = _proj_snap.snapshot_timeline(clips)
        self._json(200, {
            "ok": True,
            "timeline": timeline,
            "meta": {
                "schema": "project-snapshot/v1",
                "taken_at": timeline["taken_at"],
                "clip_count": timeline["clip_count"],
            },
        })

    @_route_post("/host/project-snapshot/import")
    def _h_project_snapshot_import(self, parsed, raw: bytes, ctype: str) -> None:
        if not _check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"ok": False, "message": "invalid json"})
            return
        if not isinstance(body, dict):
            self._json(400, {"ok": False, "message": "body must be an object"})
            return
        clips = body.get("clips")
        if clips is None and isinstance(body.get("timeline"), dict):
            clips = body["timeline"].get("clips")
        if not isinstance(clips, list):
            self._json(400, {"ok": False, "message": "clips 必须是数组"})
            return
        # 导入前自动压一条回滚快照（可撤销）
        store = _proj_snap.get_snapshot_store()
        before = _proj_snap.get_full_clips() or []
        store.push(before, label="导入前自动快照", meta={"source": "project-snapshot/import"})
        res = _proj_snap.write_clips(clips)
        if res.get("ok") is False:
            self._json(500, {"ok": False, "message": res.get("message") or "写回失败"})
            return
        self._json(200, {
            "ok": True,
            "message": res.get("message") or f"已导入 {len(clips)} 个片段",
            "imported": len(clips),
        })

    @_route_get("/host/project-snapshot/history")
    def _h_project_snapshot_history(self, parsed) -> None:
        if not _check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        self._json(200, {"ok": True, "snapshots": _proj_snap.get_snapshot_store().list()})

    @_route_post("/host/project-snapshot/restore")
    def _h_project_snapshot_restore(self, parsed, raw: bytes, ctype: str) -> None:
        if not _check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"ok": False, "message": "invalid json"})
            return
        snapshot_id = str((body or {}).get("snapshot_id") or "").strip()
        if not snapshot_id:
            self._json(400, {"ok": False, "message": "snapshot_id required"})
            return
        entry = _proj_snap.get_snapshot_store().get(snapshot_id)
        if entry is None:
            self._json(404, {"ok": False, "message": "快照不存在"})
            return
        res = _proj_snap.write_clips(entry.get("clips") or [])
        if res.get("ok") is False:
            self._json(500, {"ok": False, "message": res.get("message") or "回滚失败"})
            return
        self._json(200, {
            "ok": True,
            "message": f"已回滚到快照「{entry.get('label')}」（{entry.get('clip_count')} 片段）",
            "restored": entry.get("clip_count"),
        })


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
        # §12-P2 启动打点：bridge 就绪三段计时（already running → bind → total），
        # 对齐 canvas_runtime 的三段先例；零行为变化，仅补短路段日志。
        _t0 = time.monotonic()
        if self._thread and self._thread.is_alive():
            logger.info("canvas bridge boot timing: already running (%.3fs)",
                        time.monotonic() - _t0)
            return True
        try:
            self._httpd = ThreadingHTTPServer((self.host, self.port), _BridgeHandler)
            self._httpd.bridge_port = self.port  # type: ignore[attr-defined]
            self._httpd.base_url = self.base_url  # type: ignore[attr-defined]
            self._thread = threading.Thread(
                target=self._httpd.serve_forever, name="CanvasBridge", daemon=True
            )
            self._thread.start()
            # 2026-10-20：后台预热渠道配置 / ComfyUI 状态 / Agent 端口探活，
            # 避免用户第一次点开面板时这些端点冷启动卡 0.7~4s。
            try:
                def _warm_canvas_caches() -> None:
                    try:
                        build_host_ai_config_patch()
                    except Exception:
                        logger.debug("ai config warmup failed", exc_info=True)
                    try:
                        from app.core.canvas_routes_get import warm_comfy_status_cache

                        warm_comfy_status_cache()
                    except Exception:
                        logger.debug("comfy status warmup failed", exc_info=True)
                    try:
                        from app.core.canvas_agent_runtime import get_canvas_agent_runtime

                        get_canvas_agent_runtime().is_listening()
                    except Exception:
                        logger.debug("agent listen warmup failed", exc_info=True)

                threading.Thread(
                    target=_warm_canvas_caches,
                    name="CanvasAiConfigWarmup",
                    daemon=True,
                ).start()
            except Exception:
                logger.debug("canvas cache warmup failed", exc_info=True)
            logger.info("canvas bridge listening on %s (bind %.3fs)",
                        self.base_url, time.monotonic() - _t0)
            try:
                from app.core.agent_session import agent_sessions

                # 先恢复上次的会话检查点（恢复后一律为暂停态），再统一置暂停
                _ckpt = agent_sessions.load_checkpoint()
                if _ckpt.get("restored"):
                    logger.info(
                        "Agent 会话检查点已恢复：%d 个（%d 个暂停待续跑）",
                        _ckpt.get("restored"), _ckpt.get("paused"),
                    )
                agent_sessions.mark_restart_paused()
            except Exception:
                logger.debug("agent checkpoint / mark_restart_paused failed", exc_info=True)
            logger.info("canvas bridge boot done (total %.3fs)", time.monotonic() - _t0)
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

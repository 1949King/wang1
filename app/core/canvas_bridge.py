# -*- coding: utf-8 -*-
"""自研拾光导演台画布 ↔ 拾光剪影 本地桥。

职责：
- 接收画布导出的图片/视频（HTTP multipart 或本地路径）
- 落盘到 ~/.video_editor_cache/canvas_inbox/
- 可选写入角色库资产（CharacterStore）
- EventBus 推送到剪辑时间线（MATERIAL_TO_TIMELINE）
- 可选开启线性补帧标记（非神经网络）

不嵌入 React 内核；画布仍跑在 localhost WebView。
"""
from __future__ import annotations

import json
import logging
import os
import queue
import re
import hashlib
import shutil
import sys
import threading
import time
import uuid
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse
# AIGC / 模型配置 / 分镜层已拆到 canvas_aigc.py，此处 re-export 保持向后兼容
from app.core.canvas_aigc import (
    VIDEO_KEYWORDS,
    AUDIO_KEYWORDS,
    IMAGE_KEYWORDS,
    guess_capability,
    build_host_ai_config_patch,
    _data_url_to_b64,
    generate_image_openai_compatible,
    inpaint_via_host,
    _resolve_aigc_channel,
    generate_audio_via_host,
    agent_chat_proxy,
    generate_video_via_host,
    generate_music_via_host,
    _parse_storyboard_json,
    _heuristic_storyboard,
    storyboard_breakdown,
)


logger = logging.getLogger("AI短剧编辑器.canvas_bridge")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18765
CONFIG_STORE_KEY = "infinite-canvas:ai_config_store"

# 本机会话令牌（写入 inject.js；/host/* 校验）
_SESSION_TOKEN = uuid.uuid4().hex
_BRIDGE_PREFS: Dict[str, Any] = {
    "character_id": "",
    "character_name": "",
    "character_prompt": "",
    "enable_interpolation": False,
    "active_provider": "",
    "active_provider_label": "",
}
_EDITOR_OUTBOX: List[Dict[str, Any]] = []
_OUTBOX_LOCK = threading.Lock()
_TIMELINE_SNAPSHOT_PROVIDER: Optional[Callable[[], Dict[str, Any]]] = None


def set_timeline_snapshot_provider(fn: Optional[Callable[[], Dict[str, Any]]]) -> None:
    """EditorModule 注册只读时间线快照（避免桥直接 import 上帝类）。"""
    global _TIMELINE_SNAPSHOT_PROVIDER
    _TIMELINE_SNAPSHOT_PROVIDER = fn


def get_timeline_snapshot() -> Dict[str, Any]:
    fn = _TIMELINE_SNAPSHOT_PROVIDER
    if not callable(fn):
        return {
            "ok": True,
            "clip_count": 0,
            "clips": [],
            "gaps": [],
            "message": "剪辑模块未就绪",
        }
    try:
        ctx = fn() or {}
        if not isinstance(ctx, dict):
            ctx = {}
        ctx.setdefault("ok", True)
        return ctx
    except Exception as e:
        logger.warning("timeline snapshot 失败: %s", e)
        return {"ok": False, "clip_count": 0, "clips": [], "gaps": [], "message": str(e)}

# ── Agent ↔ Canvas 双向通信事件总线 ──────────────────────────────
_EVT_BUFFER: Deque[Dict[str, Any]] = deque(maxlen=200)    # 内存环形缓冲（断线补发）
_EVT_SUBS: List[queue.Queue] = []                         # 活跃 SSE 订阅者队列
_EVT_SUBS_LOCK = threading.Lock()
_EVT_REPLY_QUEUES: Dict[str, queue.Queue] = {}            # correlation_id → reply queue（画布回执）
_EVT_REPLY_LOCK = threading.Lock()

EVENT_BUFFER_MAX = 200

def make_agent_event(
    event_type: str,
    payload: Any,
    *,
    from_agent: str = "editor",
    to_agent: str = "canvas",
    correlation_id: Optional[str] = None,
    ack_required: bool = False,
) -> Dict[str, Any]:
    """构造一条标准化事件信封。"""
    return {
        "id": f"evt_{uuid.uuid4().hex[:8]}",
        "ts": time.time() * 1000,
        "from": from_agent,
        "to": to_agent,
        "type": event_type,
        "correlation_id": correlation_id or "",
        "payload": payload,
        "ack_required": ack_required,
    }

def broadcast_agent_event(evt: Dict[str, Any]) -> None:
    """把一条事件广播给所有活跃的 SSE 订阅者，并写入环形缓冲。"""
    _EVT_BUFFER.append(evt)
    with _EVT_SUBS_LOCK:
        dead: List[queue.Queue] = []
        for q in _EVT_SUBS:
            try:
                q.put_nowait(evt)
            except queue.Full:
                dead.append(q)
            except Exception:
                dead.append(q)
        for q in dead:
            try:
                _EVT_SUBS.remove(q)
            except ValueError:
                pass

def replay_agent_events(since_id: str) -> List[Dict[str, Any]]:
    """断线重连时回放 evt_id > since_id 的未投递事件。"""
    if not since_id:
        return list(_EVT_BUFFER)
    ids_in_buf = [e.get("id") for e in _EVT_BUFFER]
    if since_id not in ids_in_buf:
        # 缓冲区里都没有（太老了），全量回
        return list(_EVT_BUFFER)
    out: List[Dict[str, Any]] = []
    seen = False
    for e in _EVT_BUFFER:
        if seen:
            out.append(e)
        if e.get("id") == since_id:
            seen = True
    return out

def register_reply_queue(correlation_id: str) -> queue.Queue:
    """为某个 correlation_id 注册一个回执队列，供剪辑侧阻塞等待画布回复。"""
    q: queue.Queue = queue.Queue(maxsize=1)
    with _EVT_REPLY_LOCK:
        _EVT_REPLY_QUEUES[correlation_id] = q
    return q

def unregister_reply_queue(correlation_id: str) -> None:
    with _EVT_REPLY_LOCK:
        _EVT_REPLY_QUEUES.pop(correlation_id, None)



def session_token() -> str:
    return _SESSION_TOKEN


# ── 画布节点插件官方注册表（Qt 端维护，GET /host/plugins 返回给前端）──
# 真实生态下应从 GitHub 插件仓库拉取，这里内置 6 个示例便于启动。
_BUILTIN_PLUGIN_REGISTRY: List[Dict[str, Any]] = [
    {
        "id": "builtin:sticky-note",
        "name": "便利贴",
        "version": "0.1.0",
        "description": "彩色便利贴节点，双击编辑内容",
        "nodes": [{"type": "builtin:sticky-note", "title": "便利贴", "icon": "📌"}],
        "url": "/plugins/sticky-note.js",
        "official": True,
    },
    {
        "id": "builtin:markdown",
        "name": "Markdown 文档",
        "version": "0.1.0",
        "description": "渲染 Markdown 文档节点，支持代码高亮和表格",
        "nodes": [{"type": "builtin:markdown", "title": "Markdown", "icon": "📄"}],
        "url": "/plugins/markdown.js",
        "official": True,
    },
    {
        "id": "builtin:svg-viewer",
        "name": "SVG 查看器",
        "version": "0.1.0",
        "description": "嵌入 SVG 图形，支持缩放和导出",
        "nodes": [{"type": "builtin:svg-viewer", "title": "SVG", "icon": "🎨"}],
        "url": "/plugins/svg-viewer.js",
        "official": True,
    },
    {
        "id": "builtin:timeline-embed",
        "name": "时间线嵌入",
        "version": "0.1.0",
        "description": "嵌入剪辑时间线预览，画布节点可双向跳转",
        "nodes": [{"type": "builtin:timeline-embed", "title": "时间线", "icon": "🎬"}],
        "url": "/plugins/timeline-embed.js",
        "official": True,
    },
    {
        "id": "community:comfyui-controlnet",
        "name": "ControlNet 姿态控制",
        "version": "0.2.1",
        "description": "通过骨骼节点精准控制视频生成的人物姿态（社区插件）",
        "nodes": [{"type": "community:comfyui-controlnet", "title": "姿态控制", "icon": "🧍"}],
        "url": "https://cdn.shiguang.io/plugins/comfyui-controlnet-0.2.1.js",
        "official": False,
    },
    {
        "id": "community:prompt-expander",
        "name": "提示词展开器",
        "version": "0.1.3",
        "description": "自动把简短提示词展开成详细描述词（社区插件）",
        "nodes": [{"type": "community:prompt-expander", "title": "提示词展开", "icon": "✨"}],
        "url": "https://cdn.shiguang.io/plugins/prompt-expander-0.1.3.js",
        "official": False,
    },
]

# Qt 端已安装插件 manifest 存储路径
_CANVAS_PLUGINS_JSON = os.path.join(
    os.path.expanduser("~"), ".video_editor_cache", "canvas_plugins.json"
)


def _load_canvas_plugins_manifest() -> List[Dict[str, Any]]:
    """读取 Qt 端已安装画布节点插件列表"""
    try:
        if os.path.isfile(_CANVAS_PLUGINS_JSON):
            with open(_CANVAS_PLUGINS_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception as e:
        logger.warning("读取 canvas_plugins.json 失败: %s", e)
    return []


def _save_canvas_plugins_manifest(plugins: List[Dict[str, Any]]) -> None:
    """持久化已安装插件列表"""
    try:
        os.makedirs(os.path.dirname(_CANVAS_PLUGINS_JSON), exist_ok=True)
        with open(_CANVAS_PLUGINS_JSON, "w", encoding="utf-8") as f:
            json.dump(plugins, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("写入 canvas_plugins.json 失败: %s", e)


def _upsert_canvas_plugin(plugin_id: str, **fields: Any) -> Dict[str, Any]:
    """增/改一个插件条目（返回合并后的完整条目）"""
    plugins = _load_canvas_plugins_manifest()
    existing = next((p for p in plugins if p.get("id") == plugin_id), None)
    entry: Dict[str, Any] = {"id": plugin_id, **fields}
    if existing:
        # 保留旧字段，新字段覆盖
        entry = {**existing, **{k: v for k, v in entry.items() if v is not None}}
        idx = plugins.index(existing)
        plugins[idx] = entry
    else:
        plugins.append(entry)
    _save_canvas_plugins_manifest(plugins)
    return entry


def _toggle_canvas_plugin_enabled(plugin_id: str, enabled: bool) -> bool:
    """切换插件启用/禁用"""
    plugins = _load_canvas_plugins_manifest()
    for p in plugins:
        if p.get("id") == plugin_id:
            p["enabled"] = bool(enabled)
            _save_canvas_plugins_manifest(plugins)
            return True
    return False


def _remove_canvas_plugin(plugin_id: str) -> bool:
    """卸载插件"""
    plugins = _load_canvas_plugins_manifest()
    new_list = [p for p in plugins if p.get("id") != plugin_id]
    if len(new_list) == len(plugins):
        return False
    _save_canvas_plugins_manifest(new_list)
    return True


def build_character_prompt(char: Optional[Dict[str, Any]]) -> str:
    """把角色库字段压成生图一致性提示片段。"""
    if not char:
        return ""
    name = str(char.get("name") or "").strip()
    parts: List[str] = []
    if name:
        parts.append(f"角色「{name}」")
    gender = str(char.get("gender") or "").strip()
    if gender:
        parts.append(gender)
    age = str(char.get("age_range") or "").strip()
    if age:
        parts.append(f"年龄感{age}")
    tags = char.get("tags")
    if isinstance(tags, list) and tags:
        parts.append("标签:" + ",".join(str(t) for t in tags if t))
    elif isinstance(tags, str) and tags.strip():
        parts.append("标签:" + tags.strip())
    appearance = str(char.get("appearance") or "").strip()
    if appearance:
        parts.append("外貌:" + appearance[:240])
    personality = str(char.get("personality") or "").strip()
    if personality:
        parts.append("气质:" + personality[:120])
    return "，".join(parts)


def set_bridge_prefs(
    *,
    character_id: str = "",
    character_name: str = "",
    character_prompt: Optional[str] = None,
    enable_interpolation: Optional[bool] = None,
    active_provider: Optional[str] = None,
    active_provider_label: Optional[str] = None,
) -> None:
    if character_id is not None:
        _BRIDGE_PREFS["character_id"] = str(character_id or "")
    if character_name is not None:
        _BRIDGE_PREFS["character_name"] = str(character_name or "")
    if character_prompt is not None:
        _BRIDGE_PREFS["character_prompt"] = str(character_prompt or "")
    if enable_interpolation is not None:
        _BRIDGE_PREFS["enable_interpolation"] = bool(enable_interpolation)
    if active_provider is not None:
        _BRIDGE_PREFS["active_provider"] = str(active_provider or "")
    if active_provider_label is not None:
        _BRIDGE_PREFS["active_provider_label"] = str(active_provider_label or "")


def canvas_inbox_dir() -> str:
    root = os.path.join(os.path.expanduser("~"), ".video_editor_cache", "canvas_inbox")
    os.makedirs(root, exist_ok=True)
    return root


def canvas_outbox_dir() -> str:
    root = os.path.join(canvas_inbox_dir(), "from_editor")
    os.makedirs(root, exist_ok=True)
    return root


# ── 批量任务注册表：V2/V3 分镜→批量生成→拼接 编排层 ──
_BATCH_JOBS: Dict[str, Any] = {}
import threading as _threading
_BATCH_LOCK = _threading.Lock()


def _ffmpeg_bin() -> str:
    import shutil as _shutil
    found = _shutil.which("ffmpeg")
    return found if found else "ffmpeg"


def _ffprobe_bin() -> str:
    import shutil as _shutil
    found = _shutil.which("ffprobe")
    return found if found else "ffprobe"


def _probe_duration(path: str) -> float:
    """用 ffprobe 获取媒体时长（秒），失败返回 0。"""
    if not path or not os.path.isfile(path):
        return 0.0
    try:
        import subprocess as _subprocess
        cmd = [
            _ffprobe_bin(),
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            path,
        ]
        flags = _subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        r = _subprocess.run(cmd, capture_output=True, text=True, timeout=15, creationflags=flags)
        if r.returncode == 0 and r.stdout.strip():
            return float(r.stdout.strip())
    except Exception as e:
        logger.debug("_probe_duration 失败 %s: %s", os.path.basename(path), e)
    return 0.0


def _run_concat_demuxer(video_paths: List[str], output_path: str) -> Optional[str]:
    """FFmpeg concat demuxer（-c copy，不重编码，极快）。
    要求所有输入编码/分辨率/帧率一致，否则自动降级到 concat filter。"""
    if not video_paths:
        return None
    import subprocess as _subprocess
    # 写 concat list file
    list_path = output_path + ".concat.txt"
    try:
        with open(list_path, "w", encoding="utf-8") as f:
            for p in video_paths:
                # ffmpeg concat demuxer 对单引号敏感，用转义
                safe = p.replace("'", "'\\''")
                f.write(f"file '{safe}'\n")
        cmd = [
            _ffmpeg_bin(), "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", list_path,
            "-c", "copy",
            "-movflags", "+faststart",
            output_path,
        ]
        flags = _subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        r = _subprocess.run(cmd, capture_output=True, timeout=3600, creationflags=flags)
        if r.returncode == 0 and os.path.isfile(output_path) and os.path.getsize(output_path) > 1024:
            return output_path
        logger.warning("concat demuxer 失败，降级 concat filter: %s", (r.stderr or b"")[:300])
    except Exception as e:
        logger.warning("concat demuxer 异常，降级 concat filter: %s", e)
    finally:
        try:
            os.remove(list_path)
        except Exception as err:
            logger.debug("清理 concat 临时列表文件失败: %s", err, exc_info=True)
    # 降级：concat filter（重编码，兼容性强）
    try:
        n = len(video_paths)
        if n == 0:
            return None
        inputs_args: List[str] = []
        for p in video_paths:
            inputs_args += ["-i", p]
        filter_parts = []
        for i in range(n):
            filter_parts.append(f"[{i}:v]scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1,fps=30[v{i}];")
        concat_inputs = "".join(f"[v{i}]" for i in range(n))
        filter_parts.append(f"{concat_inputs}concat=n={n}:v=1:a=0[vout]")
        cmd = (
            [_ffmpeg_bin(), "-y"]
            + inputs_args
            + [
                "-filter_complex", "".join(filter_parts),
                "-map", "[vout]",
                "-r", "30",
                "-pix_fmt", "yuv420p",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                "-movflags", "+faststart",
                output_path,
            ]
        )
        flags = _subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        r = _subprocess.run(cmd, capture_output=True, timeout=3600, creationflags=flags)
        if r.returncode == 0 and os.path.isfile(output_path) and os.path.getsize(output_path) > 1024:
            return output_path
        logger.warning("concat filter 也失败了: %s", (r.stderr or b"")[:300])
    except Exception as e:
        logger.warning("concat filter 异常: %s", e)
    return None


def _run_concat_xfade(video_paths: List[str], output_path: str, transition_sec: float = 0.5) -> Optional[str]:
    """带 xfade 转场的拼接。比 concat filter 更慢但画面过渡平滑。"""
    if len(video_paths) < 2:
        return _run_concat_demuxer(video_paths, output_path)
    import subprocess as _subprocess
    durations = [_probe_duration(p) for p in video_paths]
    # xfade 需要精确 offset = cumulative duration - transition_sec
    try:
        n = len(video_paths)
        inputs_args: List[str] = []
        for p in video_paths:
            inputs_args += ["-i", p]
        # filter_complex: 两两 xfade
        fc_parts: List[str] = []
        # scale + fps + sar normalize for all
        norm = []
        for i in range(n):
            norm.append(f"[{i}:v]scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1,fps=30[v{i}n];")
        fc_parts.extend(norm)
        cur_label = "v0n"
        offset = durations[0] - transition_sec
        if offset < 0:
            offset = 0
        for i in range(1, n):
            next_label = f"v{i}n"
            out_label = f"v{i}xf" if i < n - 1 else "vout"
            fc_parts.append(f"[{cur_label}][{next_label}]xfade=transition=fade:duration={transition_sec}:offset={offset}[{out_label}];")
            cur_label = out_label
            offset += durations[i] - transition_sec
        cmd = (
            [_ffmpeg_bin(), "-y"]
            + inputs_args
            + [
                "-filter_complex", "".join(fc_parts),
                "-map", "[vout]",
                "-r", "30",
                "-pix_fmt", "yuv420p",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                "-movflags", "+faststart",
                output_path,
            ]
        )
        flags = _subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        r = _subprocess.run(cmd, capture_output=True, timeout=3600, creationflags=flags)
        if r.returncode == 0 and os.path.isfile(output_path) and os.path.getsize(output_path) > 1024:
            return output_path
        logger.warning("xfade 失败，降级 concat filter: %s", (r.stderr or b"")[:300])
    except Exception as e:
        logger.warning("xfade 异常，降级 concat filter: %s", e)
    return _run_concat_demuxer(video_paths, output_path)


def canvas_characters_media_dir(char_id: str = "default") -> str:
    root = os.path.join(
        os.path.expanduser("~"), ".video_editor_cache", "characters", "media", char_id
    )
    os.makedirs(root, exist_ok=True)
    return root


def _safe_filename(name: str) -> str:
    base = os.path.basename(name or "asset.bin").replace("..", "_")
    keep = "".join(c for c in base if c.isalnum() or c in "._- ()[]")
    return keep or f"asset_{uuid.uuid4().hex[:8]}.bin"


def ingest_local_file(
    src_path: str,
    *,
    title: str = "",
    character_id: str = "",
    character_name: str = "",
    send_to_editor: bool = True,
    enable_interpolation: bool = False,
    source: str = "infinite_canvas",
    duration_sec: float = 0.0,
    canvas_node_id: str = "",
    canvas_kind: str = "",
) -> Dict[str, Any]:
    """复制本地文件到 inbox，可选入轨 / 挂角色资产。"""
    inbox = os.path.abspath(canvas_inbox_dir())
    path = os.path.abspath(src_path)
    if not os.path.isfile(path):
        return {"success": False, "message": f"文件不存在: {path}"}

    ext = os.path.splitext(path)[1].lower()
    dest_name = os.path.basename(path)
    if os.path.dirname(path) == inbox:
        dest = path
    else:
        dest_name = f"{int(time.time())}_{_safe_filename(os.path.basename(path))}"
        dest = os.path.join(inbox, dest_name)
        try:
            shutil.copy2(path, dest)
        except Exception as e:
            return {"success": False, "message": f"复制失败: {e}"}

    asset = {
        "id": f"canvas_{uuid.uuid4().hex[:12]}",
        "path": dest,
        "title": title or os.path.basename(path),
        "ext": ext,
        "kind": "video" if ext in (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v") else "image",
        "character_id": character_id or "",
        "character_name": character_name or "",
        "source": source,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "enable_interpolation": bool(enable_interpolation),
        "duration_sec": float(duration_sec) if duration_sec else None,
    }

    if character_id:
        try:
            media_dir = canvas_characters_media_dir(character_id)
            linked = os.path.join(media_dir, dest_name)
            if not os.path.isfile(linked):
                shutil.copy2(dest, linked)
            asset["character_media_path"] = linked
            _append_character_asset(character_id, asset)
        except Exception as e:
            logger.warning("挂角色资产失败: %s", e)

    result: Dict[str, Any] = {
        "success": True,
        "message": f"已入库: {os.path.basename(dest)}",
        "asset": asset,
        "file_path": dest,
    }

    if send_to_editor:
        send_res = emit_canvas_to_editor(
            dest,
            title=asset["title"],
            source=source,
            enable_interpolation=enable_interpolation,
            kind=asset["kind"],
            duration_sec=float(duration_sec) if duration_sec else 0.0,
            canvas_node_id=canvas_node_id,
            canvas_kind=canvas_kind or asset["kind"],
        )
        result["editor"] = send_res
        if not send_res.get("success"):
            result["message"] = send_res.get("message") or result["message"]
            result["success"] = bool(send_res.get("success"))

    return result


def _append_character_asset(character_id: str, asset: Dict[str, Any]) -> None:
    try:
        from app.modules.lego.character_management_module import CharacterStore
    except ImportError:
        from modules.lego.character_management_module import CharacterStore  # type: ignore

    store = CharacterStore()
    char = store.get(character_id)
    if not char:
        return
    assets = list(char.get("generated_assets") or [])
    assets.append(
        {
            "id": asset.get("id"),
            "path": asset.get("character_media_path") or asset.get("path"),
            "kind": asset.get("kind"),
            "title": asset.get("title"),
            "created_at": asset.get("created_at"),
            "source": asset.get("source"),
        }
    )
    # 保留最近 50 条
    store.update(character_id, {"generated_assets": assets[-50:]})


def _image_to_still_video(image_path: str, duration_sec: float = 3.0) -> Optional[str]:
    """把静图转成短视频，便于入时间线。失败返回 None。"""
    ext = os.path.splitext(image_path)[1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
        return None
    out = os.path.join(
        canvas_inbox_dir(),
        f"{int(time.time())}_{_safe_filename(os.path.splitext(os.path.basename(image_path))[0])}.still.mp4",
    )
    ffmpeg = "ffmpeg"
    try:
        import shutil

        found = shutil.which("ffmpeg")
        if found:
            ffmpeg = found
    except Exception as exc:
        logger.debug("探测 ffmpeg 路径失败，回退到默认 'ffmpeg': %s", exc, exc_info=True)
    cmd = [
        ffmpeg,
        "-y",
        "-loop",
        "1",
        "-i",
        image_path,
        "-t",
        str(max(0.5, float(duration_sec))),
        "-vf",
        "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-pix_fmt",
        "yuv420p",
        "-r",
        "30",
        out,
    ]
    try:
        import subprocess
        import sys

        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        r = subprocess.run(cmd, capture_output=True, timeout=60, creationflags=flags)
        if r.returncode == 0 and os.path.isfile(out):
            return out
        logger.warning("静图转视频失败: %s", (r.stderr or b"")[:200])
    except Exception as e:
        logger.warning("静图转视频异常: %s", e)
    return None


def emit_canvas_to_editor(
    file_path: str,
    *,
    title: str = "",
    source: str = "infinite_canvas",
    enable_interpolation: bool = False,
    kind: str = "",
    duration_sec: float = 0.0,
    canvas_node_id: str = "",
    canvas_kind: str = "",
) -> Dict[str, Any]:
    """推送到剪辑模块（与 drama_send_to_editor 同通道）。"""
    path = os.path.abspath(file_path)
    if not os.path.isfile(path):
        return {"success": False, "message": f"文件不存在: {path}"}

    resolved_kind = kind
    if not resolved_kind:
        ext = os.path.splitext(path)[1].lower()
        resolved_kind = (
            "video"
            if ext in (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v")
            else "image"
        )

    timeline_path = path
    if resolved_kind == "image":
        dur = float(duration_sec) if duration_sec and float(duration_sec) > 0 else 3.0
        still = _image_to_still_video(path, duration_sec=dur)
        if still:
            timeline_path = still
            resolved_kind = "video"
        else:
            return {
                "success": False,
                "message": "图片入轨需要 ffmpeg 转成短视频，未找到可用 ffmpeg",
                "file_path": path,
            }

    try:
        from app.modules.lego.core import EventBus, EventType
    except ImportError:
        from modules.lego.core import EventBus, EventType  # type: ignore

    bus = EventBus.get_instance()
    bus.emit(
        EventType.MODULE_ACTIVATED,
        {
            "target": "editor",
            "hint": f"画布素材已发送到剪辑：{title or os.path.basename(path)}",
            "source": source,
        },
        source=source,
    )
    payload = {
        "file_path": timeline_path,
        "title": title,
        "source": source,
        "kind": resolved_kind,
        "enable_interpolation": bool(enable_interpolation),
        "original_path": path,
    }
    if duration_sec and float(duration_sec) > 0:
        payload["duration_hint"] = float(duration_sec)
    if canvas_node_id:
        payload["canvas_node_id"] = str(canvas_node_id)
        payload["node_id"] = str(canvas_node_id)
    if canvas_kind:
        payload["canvas_kind"] = str(canvas_kind)
    bus.emit(
        EventType.MATERIAL_TO_TIMELINE,
        payload,
        source=source,
    )
    return {
        "success": True,
        "message": f"已发送到剪辑：{os.path.basename(timeline_path)}",
        "file_path": timeline_path,
        "enable_interpolation": bool(enable_interpolation),
        "duration_sec": float(duration_sec) if duration_sec else None,
    }




def push_editor_to_canvas(
    src_path: str,
    *,
    title: str = "",
    source: str = "editor",
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """剪辑 → 画布 outbox（供 inject / React 拉取并自动落源节点）。"""
    path = os.path.abspath(src_path)
    if not os.path.isfile(path):
        return {"success": False, "message": f"文件不存在: {path}"}

    dest_name = f"{int(time.time())}_{_safe_filename(os.path.basename(path))}"
    dest = os.path.join(canvas_outbox_dir(), dest_name)
    try:
        shutil.copy2(path, dest)
    except Exception as e:
        return {"success": False, "message": f"复制失败: {e}"}

    item = {
        "id": f"ed_{uuid.uuid4().hex[:10]}",
        "path": dest,
        "title": title or os.path.basename(path),
        "filename": dest_name,
        "ext": os.path.splitext(path)[1].lower(),
        "source": source,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "url": f"/editor_file/{dest_name}",
    }
    if extra:
        for k, v in extra.items():
            if v is None or v == "":
                continue
            item[k] = v
    with _OUTBOX_LOCK:
        _EDITOR_OUTBOX.append(item)
        # 保留最近 30
        while len(_EDITOR_OUTBOX) > 30:
            _EDITOR_OUTBOX.pop(0)

    try:
        from app.modules.lego.core import EventBus, EventType
    except ImportError:
        from modules.lego.core import EventBus, EventType  # type: ignore

    bus = EventBus.get_instance()
    bus.emit(
        EventType.MODULE_ACTIVATED,
        {
            "target": "characters",
            "hint": f"剪辑素材已推送到画布：{item['title']}",
            "source": source,
        },
        source=source,
    )
    if hasattr(EventType, "TIMELINE_TO_CANVAS"):
        bus.emit(
            EventType.TIMELINE_TO_CANVAS,
            item,
            source=source,
        )

    return {
        "success": True,
        "message": f"已推送到画布：{item['title']}",
        "item": item,
    }




def list_editor_outbox() -> List[Dict[str, Any]]:
    with _OUTBOX_LOCK:
        return list(_EDITOR_OUTBOX)

# HTTP 服务层（_BridgeHandler / CanvasBridgeServer / inject.js）已拆到 canvas_server.py，此处 re-export 保持向后兼容
from app.core.canvas_server import (
    _check_host_token,
    _BridgeHandler,
    _build_inject_js,
    CanvasBridgeServer,
    get_canvas_bridge,
)


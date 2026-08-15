# -*- coding: utf-8 -*-
"""infinite-canvas ↔ 拾光剪影 本地桥。

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
import shutil
import threading
import time
import uuid
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

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

VIDEO_KEYWORDS = (
    # ── 2024-2025 元老 ──
    "seedance", "video", "sora", "veo", "kling", "wan", "hailuo",
    # ── 2026 头部新模型 ──
    "flux-3", "flux3", "black-forest-labs", "bfl",
    "runway", "gen-4", "gen4", "gen-4.5", "gen4.5", "runwayml",
    "minimax", "h3", "vidu", "shengshu", "mini-max",
    "happyhorse", "happy-horse", "happy_horse", "alibaba", "aliyun-wan",
    "grok-imagine", "aurora-video", "xai-video",
    "ltx", "ltx-video", "lightricks",
    "pika", "pika-labs",
    "luma", "dream-machine", "labs-ray", "ray-3", "ray3",
    # ── 开源本地部署 ──
    "cogvideox", "cogvideo", "hunyuan-video", "hunyuanvideo",
    "mochi", "drmochi", "ltx-2", "ltx2", "wan2", "wan3",
)
AUDIO_KEYWORDS = (
    "audio", "tts", "speech", "voice", "music", "sound",
    # ── 2026 新增 ──
    "suno", "udio", "chirp", "elevenlabs", "fish-audio",
    "fishaudio", "gpt-s4o", "s4o-audio", "flux-audio",
)
IMAGE_KEYWORDS = (
    "seedream",
    "gpt-image",
    "codex-gpt-image",
    "image",
    "dall-e",
    "dalle",
    "imagen",
    "flux",
    "flux-1", "flux1",
    "sdxl",
    "stable-diffusion",
    "sd3", "sd3.5",
    "midjourney",
    "kolors",
    "cogview",
    "hunyuan-image",
    "seedream-4", "seedream4",
    "grok-image",
    "aurora-image",
)


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
        except Exception:
            pass
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
    except Exception:
        pass
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


def guess_capability(name: str) -> str:
    value = (name or "").lower()
    if any(k in value for k in VIDEO_KEYWORDS):
        return "video"
    if any(k in value for k in AUDIO_KEYWORDS):
        return "audio"
    if any(k in value for k in IMAGE_KEYWORDS):
        return "image"
    return "text"


def build_host_ai_config_patch() -> Dict[str, Any]:
    """从模型广场组装画布 channels（id 前缀 shiguang-），含 AIGC 生图/生视频。"""
    channels: List[Dict[str, Any]] = []
    try:
        from app.modules.lego.model_config import (
            PROVIDERS,
            AIGC_MODELS,
            AIGC_CATALOG_PLACEHOLDER,
            AIGC_KEY_PRIORITY,
        )
    except ImportError:
        try:
            from modules.lego.model_config import (  # type: ignore
                PROVIDERS,
                AIGC_MODELS,
                AIGC_CATALOG_PLACEHOLDER,
                AIGC_KEY_PRIORITY,
            )
        except ImportError:
            PROVIDERS = {}
            AIGC_MODELS = {}
            AIGC_CATALOG_PLACEHOLDER = {}
            AIGC_KEY_PRIORITY = ()

    def _merge_models(
        text_names: List[str], aigc_entries: List[Dict[str, str]]
    ) -> List[Dict[str, str]]:
        by_name: Dict[str, Dict[str, str]] = {}
        for n in text_names:
            if not n:
                continue
            by_name[n] = {"name": n, "capability": guess_capability(n)}
        for ent in aigc_entries or []:
            name = str(ent.get("name") or "")
            if not name:
                continue
            by_name[name] = {
                "name": name,
                "capability": str(ent.get("capability") or guess_capability(name)),
            }
        return list(by_name.values())

    # Ollama（默认渠道；模型列表尽力探测，失败不阻塞）
    ollama_models: List[Dict[str, str]] = [{"name": "llama3.2", "capability": "text"}]
    try:
        import socket

        with socket.create_connection(("127.0.0.1", 11434), timeout=0.4):
            pass
        try:
            from app.modules.lego.ollama_client import ollama_client
        except ImportError:
            try:
                from modules.lego.ollama_client import ollama_client  # type: ignore
            except ImportError:
                ollama_client = None  # type: ignore
        if ollama_client is not None:
            try:
                listed = ollama_client.list_models() or []
                names = []
                for m in listed:
                    name = getattr(m, "name", None) or str(m)
                    if name:
                        names.append({"name": name, "capability": guess_capability(name)})
                if names:
                    ollama_models = names
            except Exception as e:
                logger.debug("ollama list failed: %s", e)
    except OSError:
        pass
    channels.append(
        {
            "id": "shiguang-ollama",
            "name": "拾光·Ollama",
            "baseUrl": "http://127.0.0.1:11434/v1",
            "apiKey": "ollama",
            "apiFormat": "openai",
            "models": ollama_models,
        }
    )

    # Cloud providers with keys (+ AIGC extras)
    try:
        from app.modules.lego.cloud_api import cloud_api_service
    except ImportError:
        try:
            from modules.lego.cloud_api import cloud_api_service  # type: ignore
        except ImportError:
            cloud_api_service = None  # type: ignore

    configured: Dict[str, Dict[str, Any]] = {}
    if cloud_api_service is not None:
        for pid, meta in (PROVIDERS or {}).items():
            if pid == "ollama" or not isinstance(meta, dict):
                continue
            try:
                if not cloud_api_service.is_configured(pid):
                    continue
            except Exception:
                continue
            cfg = cloud_api_service.get_config(pid)
            api_key = (cfg.api_key if cfg else "") or ""
            if not api_key:
                continue
            base = (cfg.base_url if cfg and cfg.base_url else "") or str(meta.get("url") or "")
            if not base:
                continue
            model_names = list(meta.get("models") or [])
            if cfg and cfg.model and cfg.model not in model_names:
                model_names.insert(0, cfg.model)
            aigc = list((AIGC_MODELS or {}).get(pid) or [])
            models = _merge_models(model_names, aigc)
            if not models:
                models = [{"name": "default", "capability": "text"}]
            ch = {
                "id": f"shiguang-{pid}",
                "name": f"拾光·{meta.get('name') or pid}",
                "baseUrl": base.rstrip("/"),
                "apiKey": api_key,
                "apiFormat": "ark" if "ark.cn-beijing" in base else "openai",
                "models": models,
            }
            channels.append(ch)
            configured[pid] = ch

    # 专用 AIGC 渠道：优先复用已配置 Key；否则挂目录占位（画布内提示补 Key，不作为默认可生成渠道）
    aigc_channel = None
    for pid in AIGC_KEY_PRIORITY or ():
        if pid in configured:
            src = configured[pid]
            aigc_channel = {
                "id": "shiguang-aigc",
                "name": f"拾光·AIGC（{PROVIDERS.get(pid, {}).get('name') or pid}）",
                "baseUrl": src["baseUrl"],
                "apiKey": src["apiKey"],
                "apiFormat": src.get("apiFormat") or "openai",
                "models": list((AIGC_MODELS or {}).get(pid) or src.get("models") or []),
            }
            break
    # 回退：任意已配置渠道若挂有 image/video 目录，也可作 AIGC
    if aigc_channel is None:
        for pid, src in configured.items():
            aigc_ents = list((AIGC_MODELS or {}).get(pid) or [])
            if any(str(e.get("capability")) in ("image", "video", "audio") for e in aigc_ents):
                aigc_channel = {
                    "id": "shiguang-aigc",
                    "name": f"拾光·AIGC（{PROVIDERS.get(pid, {}).get('name') or pid}）",
                    "baseUrl": src["baseUrl"],
                    "apiKey": src["apiKey"],
                    "apiFormat": src.get("apiFormat") or "openai",
                    "models": aigc_ents or list(src.get("models") or []),
                }
                break
    placeholder_only = False
    if aigc_channel is None and AIGC_CATALOG_PLACEHOLDER:
        aigc_channel = dict(AIGC_CATALOG_PLACEHOLDER)
        aigc_channel["id"] = "shiguang-aigc"
        aigc_channel["name"] = "拾光·AIGC（请在模型管理填硅基流动/OpenAI 等 Key）"
        aigc_channel["needsKey"] = True
        placeholder_only = True
    if aigc_channel:
        channels.append(aigc_channel)

    # 画布默认选中模型（channelId::model）——仅对有 Key 的渠道设默认，避免空 Key 假默认
    defaults: Dict[str, str] = {}
    prefer_ch = None
    if aigc_channel and (aigc_channel.get("apiKey") or "").strip() and not placeholder_only:
        prefer_ch = aigc_channel
    else:
        for c in channels:
            if c.get("id") == "shiguang-ollama":
                continue
            if not (c.get("apiKey") or "").strip():
                continue
            if any((m.get("capability") == "image") for m in (c.get("models") or [])):
                prefer_ch = c
                break
        if prefer_ch is None:
            for c in channels:
                if (c.get("apiKey") or "").strip() and c.get("id") != "shiguang-ollama":
                    prefer_ch = c
                    break
    if prefer_ch:
        cid = prefer_ch["id"]
        for m in prefer_ch.get("models") or []:
            cap = m.get("capability") or "text"
            key = {"image": "imageModel", "video": "videoModel", "text": "textModel", "audio": "audioModel"}.get(
                cap
            )
            if key and key not in defaults:
                defaults[key] = f"{cid}::{m['name']}"
        if "imageModel" in defaults:
            defaults["model"] = defaults["imageModel"]
        elif "textModel" in defaults:
            defaults["model"] = defaults["textModel"]

    warnings: List[str] = []
    keyed = [c for c in channels if (c.get("apiKey") or "").strip() and c.get("id") != "shiguang-ollama"]
    has_img = any(
        (c.get("apiKey") or "").strip()
        and any(m.get("capability") == "image" for m in (c.get("models") or []))
        for c in channels
    )
    has_vid = any(
        (c.get("apiKey") or "").strip()
        and any(m.get("capability") == "video" for m in (c.get("models") or []))
        for c in channels
    )
    has_aud = any(
        (c.get("apiKey") or "").strip()
        and any(m.get("capability") == "audio" for m in (c.get("models") or []))
        for c in channels
    )
    if not keyed:
        warnings.append("模型管理尚未配置任何云端 Key，请到「模型管理」填写后点同步模型池。")
    elif not has_img:
        names = "、".join(
            str((PROVIDERS or {}).get(pid, {}).get("name") or pid) for pid in configured
        ) or "已配置渠道"
        warnings.append(
            f"当前仅有对话渠道（{names}），无生图 Key。"
            "请在模型管理为「硅基流动 / OpenAI / 通义」等填写 Key，再同步模型池。"
        )
    if keyed and not has_vid:
        warnings.append("暂无生视频 Key；视频节点会诚实失败，不影响生图/拉片。")

    active_provider = ""
    active_label = ""
    try:
        from app.modules.lego.model_config import load_active_provider, PROVIDERS as _P

        active_provider = load_active_provider() or ""
        active_label = str((_P.get(active_provider) or {}).get("name") or active_provider)
    except Exception:
        try:
            from modules.lego.model_config import load_active_provider, PROVIDERS as _P  # type: ignore

            active_provider = load_active_provider() or ""
            active_label = str((_P.get(active_provider) or {}).get("name") or active_provider)
        except Exception:
            pass

    return {
        "channels": channels,
        "defaults": defaults,
        "source": "shiguang_model_square",
        "aigc": True,
        "warnings": warnings,
        "configured_providers": list(configured.keys()),
        "active_provider": active_provider,
        "active_provider_label": active_label,
        "has_image_models": has_img,
        "has_video_models": has_vid,
        "has_audio_models": has_aud,
    }


def push_editor_to_canvas(
    src_path: str,
    *,
    title: str = "",
    source: str = "editor",
) -> Dict[str, Any]:
    """剪辑 → 画布 outbox（供 inject 拉取）。"""
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


def _data_url_to_b64(data_url: str) -> tuple:
    """返回 (mime, raw_b64) ；失败 ("", "")。"""
    import base64 as _b64
    import re

    s = (data_url or "").strip()
    if not s:
        return "", ""
    if s.startswith("data:") and "," in s:
        header, payload = s.split(",", 1)
        m = re.match(r"data:([^;]+)", header)
        mime = m.group(1) if m else "image/png"
        # 去掉空白
        payload = "".join(payload.split())
        try:
            _b64.b64decode(payload, validate=False)
        except Exception:
            return "", ""
        return mime, payload
    # 已是裸 b64
    try:
        _b64.b64decode(s, validate=False)
        return "image/png", "".join(s.split())
    except Exception:
        return "", ""


def generate_image_openai_compatible(
    *,
    prompt: str,
    model: str = "",
    size: str = "1024x576",
    channel_id: str = "",
    reference_image: str = "",
    strength: float = 0.65,
) -> Dict[str, Any]:
    """用模型广场同步的 AIGC 渠道调用 OpenAI-compatible ``/images/generations``。

    供自研导演台「生成选中节点」走宿主代理（避免浏览器 CORS）。
    若提供 ``reference_image``（data URL / b64），优先尝试图生图；失败则降级文生图。
    """
    import base64
    import urllib.error
    import urllib.request

    prompt = (prompt or "").strip()
    if not prompt:
        return {"ok": False, "message": "提示词为空"}

    patch = build_host_ai_config_patch()
    channels = list(patch.get("channels") or [])
    defaults = dict(patch.get("defaults") or {})

    ch = None
    if channel_id:
        ch = next((c for c in channels if c.get("id") == channel_id), None)
    if ch is None:
        ch = next((c for c in channels if c.get("id") == "shiguang-aigc"), None)
    if ch is None:
        # 任一带 image 模型且有 Key 的渠道
        for c in channels:
            if not (c.get("apiKey") or "").strip():
                continue
            if any((m.get("capability") == "image") for m in (c.get("models") or [])):
                ch = c
                break
    if ch is None or not (ch.get("apiKey") or "").strip():
        return {
            "ok": False,
            "message": "没有可用的 AIGC 生图渠道。请到「模型管理」填写硅基流动/OpenAI 等 Key，并在画布点「同步模型池」。",
            "fallback_placeholder": True,
        }

    if not model:
        # defaults: "shiguang-aigc::FLUX..."
        raw = str(defaults.get("imageModel") or defaults.get("model") or "")
        if "::" in raw:
            model = raw.split("::", 1)[-1]
        if not model:
            for m in ch.get("models") or []:
                if m.get("capability") == "image":
                    model = str(m.get("name") or "")
                    break
    if not model:
        return {"ok": False, "message": "渠道内没有生图模型", "fallback_placeholder": True}

    base = str(ch.get("baseUrl") or "").rstrip("/")
    if not base:
        return {"ok": False, "message": "渠道缺少 baseUrl"}

    def _post(body: Dict[str, Any], endpoint: str = "/images/generations") -> Dict[str, Any]:
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            base + endpoint,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {ch['apiKey']}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return {
                    "ok": True,
                    "payload": json.loads(resp.read().decode("utf-8", errors="replace")),
                }
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")[:400]
            except Exception:
                pass
            return {
                "ok": False,
                "message": f"生图 API HTTP {e.code}: {err_body or e.reason}",
            }
        except Exception as e:
            return {"ok": False, "message": f"生图请求失败: {e}"}

    def _parse_payload(payload: Any, mode: str) -> Dict[str, Any]:
        items = payload.get("data") if isinstance(payload, dict) else None
        if not items and isinstance(payload, dict):
            items = payload.get("images")
        if not isinstance(items, list) or not items:
            return {
                "ok": False,
                "message": f"生图返回无法解析: {str(payload)[:200]}",
                "model": model,
                "fallback_placeholder": True,
            }
        first = items[0] if isinstance(items[0], dict) else {}
        b64 = first.get("b64_json") or first.get("base64")
        img_url = first.get("url")
        if b64:
            return {
                "ok": True,
                "image_data_url": f"data:image/png;base64,{b64}",
                "model": model,
                "channel_id": ch.get("id"),
                "channel_name": ch.get("name"),
                "mode": mode,
                "message": f"已生成（{mode} · {ch.get('name')} / {model}）",
            }
        if img_url:
            try:
                with urllib.request.urlopen(img_url, timeout=60) as r:
                    raw_img = r.read()
                mime = "image/png"
                ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip()
                if ctype.startswith("image/"):
                    mime = ctype
                data_url = f"data:{mime};base64,{base64.b64encode(raw_img).decode('ascii')}"
                return {
                    "ok": True,
                    "image_data_url": data_url,
                    "image_url": img_url,
                    "model": model,
                    "channel_id": ch.get("id"),
                    "channel_name": ch.get("name"),
                    "mode": mode,
                    "message": f"已生成（{mode} · {ch.get('name')} / {model}）",
                }
            except Exception as e:
                return {
                    "ok": True,
                    "image_url": img_url,
                    "model": model,
                    "channel_id": ch.get("id"),
                    "mode": mode,
                    "message": f"已生成 URL（本地下载失败可仍用外链）: {e}",
                }
        return {"ok": False, "message": "返回中无图像数据", "fallback_placeholder": True}

    mime, ref_b64 = _data_url_to_b64(reference_image)
    used_img2img = False
    img2img_err = ""
    if ref_b64:
        # 硅基 / 兼容渠道常见字段：image + image_size；部分用 images 数组
        strength_clamped = max(0.1, min(0.95, float(strength or 0.65)))
        img2_body: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "n": 1,
            "response_format": "b64_json",
            "image": f"data:{mime};base64,{ref_b64}",
            "strength": strength_clamped,
        }
        if "siliconflow" in base.lower():
            img2_body["image_size"] = size or "1024x576"
        else:
            img2_body["size"] = size or "1024x576"
        r2 = _post(img2_body)
        if r2.get("ok"):
            parsed = _parse_payload(r2.get("payload"), "img2img")
            if parsed.get("ok"):
                used_img2img = True
                return parsed
            img2img_err = str(parsed.get("message") or "img2img 解析失败")
        else:
            img2img_err = str(r2.get("message") or "img2img 失败")

    body: Dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "n": 1,
        "size": size or "1024x576",
        "response_format": "b64_json",
    }
    if "siliconflow" in base.lower():
        body["image_size"] = size or "1024x576"
        body.pop("size", None)

    r = _post(body)
    if not r.get("ok"):
        return {
            "ok": False,
            "message": (
                f"{r.get('message')}"
                + (f"（img2img 已降级：{img2img_err}）" if img2img_err else "")
            ),
            "model": model,
            "channel_id": ch.get("id"),
            "fallback_placeholder": True,
        }
    parsed = _parse_payload(r.get("payload"), "txt2img")
    if img2img_err and parsed.get("ok"):
        parsed["message"] = (
            f"{parsed.get('message')}；首帧 img2img 不可用已降级文生图（{img2img_err[:120]}）"
        )
        parsed["img2img_fallback"] = True
    elif used_img2img:
        parsed["mode"] = "img2img"
    return parsed


def inpaint_via_host(
    *,
    prompt: str,
    image: str,
    mask: str,
    model: str = "",
    channel_id: str = "",
    size: str = "1024x576",
) -> Dict[str, Any]:
    """局部重绘：优先 OpenAI-compatible ``/images/edits``；否则用 mask 提示 + img2img。

    不支持时诚实失败（不返回假图）。
    """
    import base64
    import urllib.error
    import urllib.request

    prompt = (prompt or "").strip() or "inpaint the masked region"
    if not image or not mask:
        return {"ok": False, "message": "inpaint 需要原图与蒙版"}

    # 先尝试 edits 端点
    patch = build_host_ai_config_patch()
    channels = list(patch.get("channels") or [])
    ch = None
    if channel_id:
        ch = next((c for c in channels if c.get("id") == channel_id), None)
    if ch is None:
        ch = next((c for c in channels if c.get("id") == "shiguang-aigc"), None)
    if ch is None:
        for c in channels:
            if (c.get("apiKey") or "").strip() and any(
                (m.get("capability") == "image") for m in (c.get("models") or [])
            ):
                ch = c
                break
    if ch is None or not (ch.get("apiKey") or "").strip():
        return {
            "ok": False,
            "message": "没有可用生图渠道，无法 inpaint。请到模型管理填写 AIGC Key 后同步。",
        }

    if not model:
        for m in ch.get("models") or []:
            if m.get("capability") == "image":
                model = str(m.get("name") or "")
                break
    base = str(ch.get("baseUrl") or "").rstrip("/")
    mime_i, b64_i = _data_url_to_b64(image)
    mime_m, b64_m = _data_url_to_b64(mask)
    if not b64_i or not b64_m:
        return {"ok": False, "message": "原图或蒙版不是有效 data URL"}

    # 1) /images/edits（部分兼容站支持）
    try:
        boundary = "----ShiguangInpaintBoundary"
        parts = []

        def _add(name: str, value: bytes, filename: str | None = None, ctype: str | None = None):
            parts.append(f"--{boundary}\r\n".encode())
            if filename:
                parts.append(
                    f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode()
                )
                parts.append(f"Content-Type: {ctype or 'application/octet-stream'}\r\n\r\n".encode())
                parts.append(value)
                parts.append(b"\r\n")
            else:
                parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
                parts.append(value)
                parts.append(b"\r\n")

        _add("model", model.encode("utf-8"))
        _add("prompt", prompt.encode("utf-8"))
        _add("n", b"1")
        _add("size", (size or "1024x576").encode("utf-8"))
        _add("response_format", b"b64_json")
        _add("image", base64.b64decode(b64_i), "image.png", mime_i or "image/png")
        _add("mask", base64.b64decode(b64_m), "mask.png", mime_m or "image/png")
        parts.append(f"--{boundary}--\r\n".encode())
        body = b"".join(parts)
        req = urllib.request.Request(
            base + "/images/edits",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {ch['apiKey']}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
        items = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(items, list) and items:
            first = items[0] if isinstance(items[0], dict) else {}
            b64 = first.get("b64_json") or first.get("base64")
            if b64:
                return {
                    "ok": True,
                    "image_data_url": f"data:image/png;base64,{b64}",
                    "model": model,
                    "mode": "inpaint-edits",
                    "message": f"局部重绘成功（edits · {ch.get('name')} / {model}）",
                }
    except Exception as e:
        edits_err = str(e)
    else:
        edits_err = "edits 返回无图像"

    # 2) 降级：把蒙版意图写入提示 + img2img
    strengthened = (
        f"{prompt}\n\n"
        "Inpaint only the white-masked regions; keep unmasked areas unchanged. "
        "High fidelity to the original composition."
    )
    fallback = generate_image_openai_compatible(
        prompt=strengthened,
        model=model,
        size=size,
        channel_id=str(ch.get("id") or ""),
        reference_image=image,
        strength=0.55,
    )
    if fallback.get("ok"):
        fallback["mode"] = "inpaint-img2img-fallback"
        fallback["message"] = (
            f"{fallback.get('message')}（/images/edits 不可用：{edits_err[:120]}，已用 img2img 降级）"
        )
        return fallback
    return {
        "ok": False,
        "message": (
            f"局部重绘失败。edits: {edits_err[:160]}；"
            f"img2img: {fallback.get('message')}"
        ),
    }


def _resolve_aigc_channel(
    *,
    channel_id: str = "",
    capability: str = "image",
    default_model_key: str = "imageModel",
) -> tuple[Optional[Dict[str, Any]], str, Dict[str, Any]]:
    """解析带 Key 的 AIGC 渠道与默认模型名。"""
    patch = build_host_ai_config_patch()
    channels = list(patch.get("channels") or [])
    defaults = dict(patch.get("defaults") or {})

    ch: Optional[Dict[str, Any]] = None
    if channel_id:
        ch = next((c for c in channels if c.get("id") == channel_id), None)
    if ch is None:
        ch = next((c for c in channels if c.get("id") == "shiguang-aigc"), None)
    if ch is None:
        for c in channels:
            if not (c.get("apiKey") or "").strip():
                continue
            if any((m.get("capability") == capability) for m in (c.get("models") or [])):
                ch = c
                break
    if ch is None or not (ch.get("apiKey") or "").strip():
        return None, "", patch

    model = ""
    raw = str(defaults.get(default_model_key) or "")
    if "::" in raw:
        model = raw.split("::", 1)[-1]
    return ch, model, patch


def generate_audio_via_host(
    *,
    prompt: str,
    model: str = "",
    channel_id: str = "",
    voice: str = "",
    bridge_port: int = DEFAULT_PORT,
) -> Dict[str, Any]:
    """生音频：优先模型广场云端 TTS（OpenAI-compatible /audio/speech）；失败降级本地 VoiceGenerator。"""
    import time
    import urllib.error
    import urllib.request

    prompt = (prompt or "").strip()
    if not prompt:
        return {"ok": False, "message": "音频提示词为空"}

    ch, default_model, _patch = _resolve_aigc_channel(
        channel_id=channel_id,
        capability="audio",
        default_model_key="audioModel",
    )
    if not model and default_model:
        model = default_model
    if ch and not model:
        for m in ch.get("models") or []:
            if m.get("capability") == "audio":
                model = str(m.get("name") or "")
                break

    cloud_err = ""
    if ch and model and (ch.get("apiKey") or "").strip():
        base = str(ch.get("baseUrl") or "").rstrip("/")
        api_key = str(ch.get("apiKey") or "")
        tts_voice = (voice or "alloy").strip() or "alloy"
        body = {
            "model": model,
            "input": prompt,
            "voice": tts_voice,
            "response_format": "mp3",
        }
        speech_url = f"{base}/audio/speech" if base.endswith("/v1") else f"{base}/v1/audio/speech"
        if base:
            try:
                req = urllib.request.Request(
                    speech_url,
                    data=json.dumps(body).encode("utf-8"),
                    method="POST",
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {api_key}",
                    },
                )
                with urllib.request.urlopen(req, timeout=120) as resp:
                    raw = resp.read()
                    ctype = resp.headers.get("Content-Type") or ""
                if raw:
                    ext = ".wav" if "wav" in ctype else ".mp3"
                    name = f"tts_{int(time.time())}_{abs(hash(prompt)) % 100000}{ext}"
                    dest = os.path.join(canvas_inbox_dir(), name)
                    with open(dest, "wb") as f:
                        f.write(raw)
                    audio_url = f"http://127.0.0.1:{int(bridge_port)}/inbox_file/{name}"
                    return {
                        "ok": True,
                        "audio_url": audio_url,
                        "audio_path": dest,
                        "model": model,
                        "message": f"TTS 已生成（{ch.get('name') or '云端'} · {model}）",
                    }
            except urllib.error.HTTPError as e:
                detail = ""
                try:
                    detail = e.read().decode("utf-8", errors="replace")[:200]
                except Exception:
                    pass
                cloud_err = f"HTTP {e.code} {detail}".strip()
            except Exception as e:
                cloud_err = str(e)[:200]

    try:
        try:
            from app.core.voice_generator import VoiceGenerator
        except ImportError:
            from core.voice_generator import VoiceGenerator  # type: ignore

        vg = VoiceGenerator()
        name = f"tts_{int(time.time())}_{abs(hash(prompt)) % 100000}.wav"
        dest = os.path.join(canvas_inbox_dir(), name)
        result = vg.generate_audio(prompt, output_path=dest)
        if result.get("success") and os.path.isfile(dest):
            url = f"http://127.0.0.1:{int(bridge_port)}/inbox_file/{name}"
            msg = "TTS 已生成（本地 VoiceGenerator · edge-tts/gTTS 可用时更佳）"
            if cloud_err:
                msg += f"；云端不可用：{cloud_err[:120]}"
            return {
                "ok": True,
                "audio_url": url,
                "audio_path": dest,
                "message": msg,
                "fallback_local": True,
            }
        err = str(result.get("error") or "TTS 生成失败")
    except Exception as e:
        err = str(e)

    hint = ""
    if cloud_err:
        hint = f"云端：{cloud_err[:120]}；"
    elif not ch or not model:
        hint = "请在模型管理配置 OpenAI 等 TTS Key 并同步模型池；"
    return {
        "ok": False,
        "message": (
            f"宿主 TTS 失败：{hint}本地：{err[:160]}。"
            "可上传音频到音频节点，或检查模型管理中的 gpt-4o-mini-tts / speech-01。"
        ),
    }


def agent_chat_proxy(message: str) -> Dict[str, Any]:
    """把自然语言转发到外部 Node canvas-agent（:17371，@basketikun/canvas-agent）。

    ⚠️ DEPRECATED：这是旧 MCP 路径。自研画布请看
    ``project_agent_host.project_agent_chat()`` 和端点 ``/host/project-agent/chat``。
    本函数保留仅为兼容 character_management_module 的「连接 Agent」按钮。
    """
    import urllib.error
    import urllib.request

    message = (message or "").strip()
    if not message:
        return {"ok": False, "message": "消息为空"}
    try:
        from app.core.canvas_agent_runtime import get_canvas_agent_runtime
    except ImportError:
        from core.canvas_agent_runtime import get_canvas_agent_runtime  # type: ignore

    rt = get_canvas_agent_runtime()
    if not rt.is_listening():
        return {"ok": False, "message": "Agent 未启动，请先点「连接 Agent」"}
    base = (rt.url or "http://127.0.0.1:17371").rstrip("/")
    headers = {"Content-Type": "application/json"}
    if rt.token:
        headers["Authorization"] = f"Bearer {rt.token}"
        headers["X-Canvas-Agent-Token"] = rt.token
    bodies = [
        ("/v1/chat/completions", {"model": "canvas-agent", "messages": [{"role": "user", "content": message}]}),
        ("/chat", {"message": message}),
        ("/api/chat", {"message": message, "content": message}),
    ]
    errors = []
    for path, body in bodies:
        try:
            req = urllib.request.Request(
                base + path,
                data=json.dumps(body).encode("utf-8"),
                method="POST",
                headers=headers,
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(raw)
            except Exception:
                return {"ok": True, "reply": raw[:2000], "message": f"已代理 {path}"}
            # OpenAI style
            choices = data.get("choices") if isinstance(data, dict) else None
            if isinstance(choices, list) and choices:
                msg = (choices[0].get("message") or {}).get("content") or choices[0].get("text")
                if msg:
                    return {"ok": True, "reply": str(msg), "message": "Agent 已回复"}
            reply = None
            if isinstance(data, dict):
                reply = data.get("reply") or data.get("message") or data.get("content")
            if reply:
                return {"ok": True, "reply": str(reply), "message": "Agent 已回复"}
            return {"ok": True, "reply": raw[:2000], "message": f"已代理 {path}（原始响应）"}
        except Exception as e:
            errors.append(f"{path}: {e}")
    return {
        "ok": False,
        "message": (
            "canvas-agent 未提供可用聊天 HTTP（多为 MCP 工具通道）。"
            f"请用面板 / 指令操作画布，或接 Codex MCP。详情：{'; '.join(errors)[:240]}"
        ),
    }


def generate_video_via_host(
    *,
    prompt: str,
    model: str = "",
    channel_id: str = "",
    duration: float = 5.0,
    size: str = "1280x720",
    reference_image: str = "",
    first_frame: str = "",
    last_frame: str = "",
    bridge_port: int = DEFAULT_PORT,
) -> Dict[str, Any]:
    """用模型广场 AIGC 渠道尝试生视频；失败返回明确错误（不假成功占位）。

    分支优先级：
    1) Zhipu CogVideoX 首尾帧：base 含 bigmodel.cn，first_frame + last_frame 同时存在
       → POST /videos/generations → 轮询 GET /async-result/{id}（支持 image_url 数组）
    2) 硅基流动 Wan：submit + poll 异步
    3) 通用 OpenAI-compatible：/videos、/video/generations、/videos/generations
    成功后文件写入 canvas inbox，返回可播放 URL。
    """
    import urllib.error
    import urllib.request

    prompt = (prompt or "").strip()
    if not prompt:
        return {"ok": False, "message": "提示词为空"}

    # ── 本地 GPU 推理 fallback：channel_id 以 "local/" 开头强制本地 ──
    if channel_id and channel_id.startswith("local/"):
        try:
            from app.core.local_video_infer import generate_video_local
        except ImportError:
            try:
                from core.local_video_infer import generate_video_local  # type: ignore
            except ImportError:
                generate_video_local = None
        if generate_video_local is None:
            return {
                "ok": False,
                "message": "本地推理模块 local_video_infer.py 不可用，请检查文件是否存在",
            }
        return generate_video_local(
            prompt=prompt,
            model=model,
            duration=duration,
            size=size,
            reference_image=reference_image,
            first_frame=first_frame,
            last_frame=last_frame,
            bridge_port=bridge_port,
        )

    patch = build_host_ai_config_patch()
    channels = list(patch.get("channels") or [])
    defaults = dict(patch.get("defaults") or {})

    ch = None
    if channel_id:
        ch = next((c for c in channels if c.get("id") == channel_id), None)
    if ch is None:
        ch = next((c for c in channels if c.get("id") == "shiguang-aigc"), None)
    if ch is None:
        for c in channels:
            if not (c.get("apiKey") or "").strip():
                continue
            if any((m.get("capability") == "video") for m in (c.get("models") or [])):
                ch = c
                break
    if ch is None or not (ch.get("apiKey") or "").strip():
        return {
            "ok": False,
            "message": (
                "没有可用的 AIGC 生视频渠道。请到「模型管理」填写硅基流动等 Key，"
                "并确认 AIGC 目录含视频模型后点「同步模型池」。"
            ),
        }

    if not model:
        raw = str(defaults.get("videoModel") or "")
        if "::" in raw:
            model = raw.split("::", 1)[-1]
        if not model:
            for m in ch.get("models") or []:
                if m.get("capability") == "video":
                    model = str(m.get("name") or "")
                    break
    if not model:
        return {"ok": False, "message": "渠道内没有生视频模型"}

    base = str(ch.get("baseUrl") or "").rstrip("/")
    if not base:
        return {"ok": False, "message": "渠道缺少 baseUrl"}

    api_key = str(ch.get("apiKey") or "")
    errors: List[str] = []

    def _json_req(method: str, url: str, body: Optional[Dict[str, Any]] = None, timeout: float = 60):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))

    def _save_video_bytes(raw: bytes, ext: str = ".mp4") -> Dict[str, Any]:
        name = f"{int(time.time())}_gen{ext}"
        path = os.path.join(canvas_inbox_dir(), name)
        with open(path, "wb") as f:
            f.write(raw)
        url = f"http://127.0.0.1:{int(bridge_port)}/inbox_file/{name}"
        return {
            "ok": True,
            "video_path": path,
            "video_url": url,
            "model": model,
            "channel_id": ch.get("id"),
            "channel_name": ch.get("name"),
            "message": f"已生成视频（{ch.get('name')} / {model}）",
        }

    def _download_url(file_url: str) -> Dict[str, Any]:
        req = urllib.request.Request(file_url, headers={"Authorization": f"Bearer {api_key}"})
        with urllib.request.urlopen(req, timeout=180) as resp:
            raw = resp.read()
        return _save_video_bytes(raw, ".mp4")

    # ── Zhipu CogVideoX 首尾帧 → POST /videos/generations + 轮询 /async-result/{id} ──
    if "bigmodel.cn" in base.lower() and first_frame and last_frame:
        try:
            mf, bf64 = _data_url_to_b64(first_frame)
            ml, bl64 = _data_url_to_b64(last_frame)
            if not bf64 or not bl64:
                errors.append("首尾帧不是有效 data URL（需要 data:image/png;base64,... 格式）")
            else:
                body: Dict[str, Any] = {
                    "model": model or "cogvideox-3",
                    "prompt": prompt,
                    "image_url": [
                        f"data:{mf or 'image/png'};base64,{bf64}",
                        f"data:{ml or 'image/png'};base64,{bl64}",
                    ],
                    "duration": int(max(5, min(15, duration))),
                    "size": size or "1920x1080",
                    "fps": 30,
                    "quality": "speed",
                    "with_audio": False,
                }
                # 参考图（角色正脸）用于身份锚定，CogVideoX 兼容该字段
                if reference_image:
                    mr, br64 = _data_url_to_b64(reference_image)
                    if br64:
                        body["reference_image"] = f"data:{mr or 'image/png'};base64,{br64}"
                submit = _json_req("POST", base + "/videos/generations", body, timeout=60)
                task_id = str(submit.get("id") or submit.get("request_id") or "")
                if not task_id:
                    errors.append(f"CogVideoX submit 无任务 ID: {str(submit)[:200]}")
                else:
                    # 快速路径：部分渠道 submit 直接返回结果（task_status=SUCCESS 且含 video_url）
                    submit_data = submit.get("data") if isinstance(submit, dict) else None
                    submit_status = str(
                        (submit.get("task_status") if isinstance(submit, dict) else "")
                        or (submit_data.get("task_status") if isinstance(submit_data, dict) else "")
                        or ""
                    ).upper()
                    submit_video_url = ""
                    if isinstance(submit_data, dict):
                        submit_video_url = str(submit_data.get("video_url") or submit_data.get("url") or "")
                    if not submit_video_url and isinstance(submit, dict):
                        submit_video_url = str(submit.get("video_url") or "")
                    if submit_status in ("SUCCESS", "SUCCEEDED") and submit_video_url:
                        return _download_url(submit_video_url)
                    if submit_status in ("FAIL", "FAILED", "ERROR", "CANCELLED"):
                        errors.append(f"CogVideoX submit 即失败: {str(submit)[:200]}")
                    else:
                        deadline = time.time() + 600
                        while time.time() < deadline:
                            status_resp = _json_req(
                                "GET",
                                base + f"/async-result/{task_id}",
                                None,
                                timeout=30,
                            )
                            data = status_resp.get("data") if isinstance(status_resp, dict) else None
                            task_status = str(
                                (status_resp.get("task_status") if isinstance(status_resp, dict) else "")
                                or (data.get("task_status") if isinstance(data, dict) else "")
                                or ""
                            ).upper()
                            if task_status in ("SUCCESS", "SUCCEEDED"):
                                video_url = ""
                                if isinstance(data, dict):
                                    video_url = str(data.get("video_url") or data.get("url") or "")
                                if not video_url and isinstance(status_resp, dict):
                                    video_url = str(status_resp.get("video_url") or "")
                                if video_url:
                                    return _download_url(video_url)
                                errors.append(f"CogVideoX 成功但无 video_url: {str(status_resp)[:200]}")
                                break
                            if task_status in ("FAIL", "FAILED", "ERROR", "CANCELLED"):
                                errors.append(f"CogVideoX 生成失败: {str(status_resp)[:200]}")
                                break
                            time.sleep(3.0)
                        else:
                            errors.append("CogVideoX 轮询超时（300s）")
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                pass
            errors.append(f"CogVideoX HTTP {e.code}: {err_body or e.reason}")
        except Exception as e:
            errors.append(f"CogVideoX 异常: {e}")

    # ── 硅基流动 Wan：submit + poll ──
    if "siliconflow" in base.lower() or "Wan" in model or "Wan-AI" in model:
        try:
            body: Dict[str, Any] = {
                "model": model,
                "prompt": prompt,
            }
            # 部分渠道用 image 做 I2V
            mime, ref_b64 = _data_url_to_b64(reference_image)
            if ref_b64:
                body["image"] = f"data:{mime};base64,{ref_b64}"
            if duration:
                body["duration"] = max(1, min(10, int(duration)))
            submit = _json_req("POST", base + "/video/submit", body, timeout=90)
            request_id = (
                (submit.get("requestId") if isinstance(submit, dict) else None)
                or (submit.get("id") if isinstance(submit, dict) else None)
                or ((submit.get("data") or {}).get("requestId") if isinstance(submit, dict) else None)
            )
            if not request_id:
                errors.append(f"硅基 submit 无 requestId: {str(submit)[:200]}")
            else:
                deadline = time.time() + 180
                while time.time() < deadline:
                    st = _json_req(
                        "POST",
                        base + "/video/status",
                        {"requestId": request_id},
                        timeout=60,
                    )
                    status = str(
                        (st.get("status") if isinstance(st, dict) else "")
                        or ((st.get("data") or {}).get("status") if isinstance(st, dict) else "")
                        or ""
                    ).lower()
                    results = []
                    if isinstance(st, dict):
                        results = st.get("results") or (st.get("data") or {}).get("results") or []
                        if not results and st.get("videos"):
                            results = st.get("videos")
                    if status in ("succeed", "succeeded", "success", "completed", "done"):
                        file_url = ""
                        if isinstance(results, list) and results:
                            first = results[0]
                            if isinstance(first, dict):
                                file_url = str(first.get("url") or first.get("video") or "")
                            elif isinstance(first, str):
                                file_url = first
                        if not file_url and isinstance(st, dict):
                            file_url = str(st.get("video_url") or st.get("url") or "")
                        if file_url:
                            return _download_url(file_url)
                        errors.append(f"状态成功但无视频 URL: {str(st)[:200]}")
                        break
                    if status in ("failed", "error", "canceled", "cancelled"):
                        errors.append(f"硅基视频失败: {str(st)[:200]}")
                        break
                    time.sleep(2.5)
                else:
                    errors.append("硅基视频轮询超时（180s）")
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                pass
            errors.append(f"硅基视频 HTTP {e.code}: {err_body or e.reason}")
        except Exception as e:
            errors.append(f"硅基视频异常: {e}")

    # ── FLUX 3 Video（BFL API，2026.8 GA，原生音画，20s） ──
    if "bfl" in base.lower() or "black-forest" in base.lower() or "flux" in model.lower():
        try:
            body: Dict[str, Any] = {
                "model": model or "flux-3-video",
                "prompt": prompt,
            }
            mime, ref_b64 = _data_url_to_b64(reference_image)
            if ref_b64:
                body["first_frame"] = f"data:{mime};base64,{ref_b64}"
            if duration:
                body["duration"] = max(1, min(20, int(duration)))
            submit = _json_req("POST", base + "/v1/video", body, timeout=90)
            task_id = str(
                (submit.get("id") or "")
                or (submit.get("task_id") or "")
                or ((submit.get("data") or {}).get("id") or "")
                or ((submit.get("data") or {}).get("task_id") or "")
            )
            if not task_id:
                # BFL submit 有时直接返回 video_url
                if isinstance(submit, dict):
                    d = submit.get("data") if isinstance(submit.get("data"), dict) else submit
                    direct_url = str(d.get("video_url") or d.get("url") or "")
                    if direct_url:
                        return _download_url(direct_url)
                errors.append(f"FLUX 3 submit 无任务 ID: {str(submit)[:200]}")
            else:
                deadline = time.time() + 240
                while time.time() < deadline:
                    st = _json_req("GET", base + f"/v1/video/{task_id}", None, timeout=30)
                    status = str(
                        (st.get("status") if isinstance(st, dict) else "")
                        or ((st.get("data") or {}).get("status") if isinstance(st, dict) else "")
                        or ""
                    ).lower()
                    if status in ("succeeded", "success", "completed", "done"):
                        d = st.get("data") if isinstance(st.get("data"), dict) else st
                        video_url = str(
                            (d.get("video_url") or "")
                            or (d.get("url") or "")
                            or ((d.get("videos") or [{}])[0].get("url") if isinstance(d.get("videos"), list) else "")
                        )
                        if video_url:
                            return _download_url(video_url)
                        errors.append(f"FLUX 3 成功但无 video_url: {str(st)[:200]}")
                        break
                    if status in ("failed", "error", "canceled", "cancelled"):
                        errors.append(f"FLUX 3 失败: {str(st)[:200]}")
                        break
                    time.sleep(3.0)
                else:
                    errors.append("FLUX 3 轮询超时（240s）")
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                pass
            errors.append(f"FLUX 3 HTTP {e.code}: {err_body or e.reason}")
        except Exception as e:
            errors.append(f"FLUX 3 异常: {e}")

    # ── Runway Gen-4.5（submit /v1/generate → poll /v1/tasks/{id}） ──
    if "runway" in base.lower() or "runwayml" in base.lower() or "gen-4" in model.lower() or "gen4" in model.lower():
        try:
            body: Dict[str, Any] = {
                "model": model or "gen4.5_turbo",
                "prompt": prompt,
            }
            mime, ref_b64 = _data_url_to_b64(reference_image)
            if ref_b64:
                body["image"] = f"data:{mime};base64,{ref_b64}"
            if duration:
                body["duration"] = max(1, min(10, int(duration)))
            submit = _json_req("POST", base + "/v1/generate", body, timeout=90)
            task_id = str(
                (submit.get("id") or "")
                or (submit.get("task_id") or "")
                or ((submit.get("data") or {}).get("id") or "")
            )
            if not task_id:
                errors.append(f"Runway submit 无任务 ID: {str(submit)[:200]}")
            else:
                deadline = time.time() + 240
                while time.time() < deadline:
                    st = _json_req("GET", base + f"/v1/tasks/{task_id}", None, timeout=30)
                    status = str(
                        (st.get("status") if isinstance(st, dict) else "")
                        or ((st.get("task") or {}).get("status") if isinstance(st, dict) else "")
                        or ""
                    ).lower()
                    if status in ("succeeded", "success", "completed", "done"):
                        data = st.get("data") if isinstance(st.get("data"), dict) else st
                        outputs = data.get("outputs") if isinstance(data.get("outputs"), list) else []
                        video_url = ""
                        for out in outputs:
                            if isinstance(out, dict) and out.get("type") == "video":
                                video_url = str(out.get("url") or "")
                                break
                        if not video_url and isinstance(data.get("video_url"), str):
                            video_url = str(data["video_url"])
                        if video_url:
                            return _download_url(video_url)
                        errors.append(f"Runway 成功但无 video_url: {str(st)[:200]}")
                        break
                    if status in ("failed", "error", "canceled", "cancelled"):
                        errors.append(f"Runway 失败: {str(st)[:200]}")
                        break
                    time.sleep(2.5)
                else:
                    errors.append("Runway 轮询超时（240s）")
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                pass
            errors.append(f"Runway HTTP {e.code}: {err_body or e.reason}")
        except Exception as e:
            errors.append(f"Runway 异常: {e}")

    # ── Kling 3.0（快手开放平台 submit + poll） ──
    if "kling" in base.lower() or "klingai" in base.lower() or "kling" in model.lower():
        try:
            endpoint = "/kling/v1/videos/text2video" if not reference_image else "/kling/v1/videos/image2video"
            body: Dict[str, Any] = {
                "model_name": model or "kling-v2.6",
                "prompt": prompt,
                "mode": "std",
            }
            if reference_image:
                mime, ref_b64 = _data_url_to_b64(reference_image)
                if ref_b64:
                    body["image"] = f"data:{mime};base64,{ref_b64}"
            submit = _json_req("POST", base + endpoint, body, timeout=90)
            task_id = str(
                (submit.get("task_id") or "")
                or ((submit.get("data") or {}).get("task_id") or "")
                or (submit.get("id") or "")
            )
            if not task_id:
                errors.append(f"Kling submit 无任务 ID: {str(submit)[:200]}")
            else:
                deadline = time.time() + 600
                while time.time() < deadline:
                    st = _json_req("GET", base + f"/kling/v1/videos/{task_id}", None, timeout=30)
                    data = st.get("data") if isinstance(st.get("data"), dict) else st
                    status = str(
                        (data.get("task_status") if isinstance(data, dict) else "")
                        or ((st.get("task_status") if isinstance(st, dict) else ""))
                        or ""
                    ).lower()
                    if status in ("succeed", "succeeded", "success", "completed", "done"):
                        videos = data.get("task_result", {}).get("videos", []) if isinstance(data, dict) else []
                        video_url = ""
                        if isinstance(videos, list) and videos:
                            video_url = str((videos[0] or {}).get("url") or "")
                        if not video_url and isinstance(data, dict):
                            video_url = str(data.get("video_url") or data.get("url") or "")
                        if video_url:
                            return _download_url(video_url)
                        errors.append(f"Kling 成功但无 video_url: {str(st)[:200]}")
                        break
                    if status in ("fail", "failed", "error", "canceled", "cancelled"):
                        errors.append(f"Kling 失败: {str(st)[:200]}")
                        break
                    time.sleep(3.0)
                else:
                    errors.append("Kling 轮询超时（300s）")
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                pass
            errors.append(f"Kling HTTP {e.code}: {err_body or e.reason}")
        except Exception as e:
            errors.append(f"Kling 异常: {e}")

    # ── MiniMax Hailuo / Vidu（submit + poll） ──
    if "minimax" in base.lower() or "hailuo" in model.lower() or "vidu" in model.lower():
        try:
            body: Dict[str, Any] = {
                "model": model or "hailuo-02",
                "prompt": prompt,
            }
            mime, ref_b64 = _data_url_to_b64(reference_image)
            if ref_b64:
                body["image_first_frame"] = f"data:{mime};base64,{ref_b64}"
            if duration:
                body["duration"] = max(5, min(15, int(duration)))
            submit = _json_req("POST", base + "/v1/video/generations", body, timeout=90)
            task_id = str(
                (submit.get("task_id") or "")
                or ((submit.get("data") or {}).get("task_id") or "")
                or (submit.get("id") or "")
            )
            if not task_id:
                errors.append(f"MiniMax submit 无任务 ID: {str(submit)[:200]}")
            else:
                deadline = time.time() + 240
                while time.time() < deadline:
                    st = _json_req("GET", base + f"/v1/query/video/{task_id}", None, timeout=30)
                    data = st.get("data") if isinstance(st.get("data"), dict) else st
                    status = str(
                        (data.get("status") if isinstance(data, dict) else "")
                        or (st.get("status") if isinstance(st, dict) else "")
                        or ""
                    ).lower()
                    if status in ("succeeded", "success", "completed", "done", "finished"):
                        video_url = ""
                        if isinstance(data, dict):
                            video_url = str(
                                (data.get("video_url") or "")
                                or (data.get("url") or "")
                                or (data.get("file_url") or "")
                            )
                        if not video_url and isinstance(st, dict):
                            video_url = str(st.get("video_url") or "")
                        if video_url:
                            return _download_url(video_url)
                        errors.append(f"MiniMax 成功但无 video_url: {str(st)[:200]}")
                        break
                    if status in ("failed", "error", "canceled", "cancelled"):
                        errors.append(f"MiniMax 失败: {str(st)[:200]}")
                        break
                    time.sleep(2.5)
                else:
                    errors.append("MiniMax 轮询超时（240s）")
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                pass
            errors.append(f"MiniMax HTTP {e.code}: {err_body or e.reason}")
        except Exception as e:
            errors.append(f"MiniMax 异常: {e}")

    # ── 通用兜底：先同步 → 再通用异步 submit+poll ──
    # 第一阶段：尝试同步返回
    def _extract_video_url(payload: Any) -> str:
        """从任意 JSON 响应结构里尽力挖出 video_url。"""
        if isinstance(payload, dict):
            direct = str(payload.get("url") or payload.get("video_url") or payload.get("file_url") or "")
            if direct:
                return direct
            for key in ("data", "result", "video"):
                child = payload.get(key)
                if isinstance(child, dict):
                    direct = str(child.get("url") or child.get("video_url") or child.get("file_url") or "")
                    if direct:
                        return direct
                elif isinstance(child, list) and child:
                    first = child[0]
                    if isinstance(first, dict):
                        direct = str(first.get("url") or first.get("video_url") or first.get("file_url") or "")
                        if direct:
                            return direct
        return ""

    def _extract_task_id(payload: Any) -> str:
        """从任意 JSON 响应结构里尽力挖出 task_id / id / request_id。"""
        if not isinstance(payload, dict):
            return ""
        candidates = [
            "id", "task_id", "taskId", "request_id", "requestId", "job_id", "jobId",
        ]
        for key in candidates:
            v = payload.get(key)
            if isinstance(v, str) and v:
                return v
        data = payload.get("data")
        if isinstance(data, dict):
            for key in candidates:
                v = data.get(key)
                if isinstance(v, str) and v:
                    return v
        return ""

    def _poll_generic(task_id: str, submit_endpoint: str) -> Optional[Dict[str, Any]]:
        """通用轮询：猜测 status endpoint 格式并轮询直到有 video_url。"""
        # 猜测轮询 endpoint：/tasks/{id}, /task/{id}, /status/{id}, /async-result/{id}, /video/{id}
        poll_endpoints = [
            lambda tid: f"/tasks/{tid}",
            lambda tid: f"/task/{tid}",
            lambda tid: f"/status/{tid}",
            lambda tid: f"/async-result/{tid}",
            lambda tid: f"/video/{tid}",
            lambda tid: f"/videos/{tid}",
        ]
        deadline = time.time() + 240
        while time.time() < deadline:
            last_err = ""
            for pf in poll_endpoints:
                try:
                    st = _json_req("GET", base + pf(task_id), None, timeout=30)
                    # 直接挖到 video_url → 成功
                    v = _extract_video_url(st)
                    if v:
                        return {"ok": True, "video_url": v}
                    # 检测状态 → 完成/失败
                    data = st.get("data") if isinstance(st.get("data"), dict) else st
                    status = str(
                        (data.get("status") if isinstance(data, dict) else "")
                        or (st.get("status") if isinstance(st, dict) else "")
                        or (data.get("task_status") if isinstance(data, dict) else "")
                        or ""
                    ).lower()
                    if status in ("succeeded", "success", "completed", "done", "finished"):
                        break  # 挖到 video_url 才真的成功，不然继续换下一个 poll endpoint
                    if status in ("failed", "error", "canceled", "cancelled"):
                        return {"ok": False, "message": f"通用轮询检测到失败: {status}"}
                except Exception as e:
                    last_err = str(e)
                    continue
            time.sleep(2.5)
        return None

    for endpoint in ("/videos", "/video/generations", "/videos/generations"):
        try:
            body2: Dict[str, Any] = {
                "model": model,
                "prompt": prompt,
            }
            mime, ref_b64 = _data_url_to_b64(reference_image)
            if ref_b64:
                body2["image"] = f"data:{mime};base64,{ref_b64}"
            if duration:
                body2["seconds"] = str(int(max(1, min(10, float(duration) or 5))))
                body2["duration"] = int(max(1, min(10, float(duration) or 5)))
            if size:
                body2["size"] = size
            payload = _json_req("POST", base + endpoint, body2, timeout=120)

            # 路径 A：同步直接返回 video_url
            direct_url = _extract_video_url(payload)
            if direct_url:
                return _download_url(direct_url)

            # 路径 B：拿到 task_id → 通用异步轮询
            tid = _extract_task_id(payload)
            if tid:
                poll_result = _poll_generic(tid, endpoint)
                if poll_result and poll_result.get("ok"):
                    return _download_url(str(poll_result["video_url"]))
                elif poll_result and not poll_result.get("ok"):
                    errors.append(f"{endpoint} 轮询失败: {poll_result.get('message','')}")
                else:
                    errors.append(f"{endpoint} 轮询超时（240s）")
            else:
                errors.append(f"{endpoint} 返回无法解析（无 url 也无 task_id）: {str(payload)[:200]}")
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                pass
            errors.append(f"{endpoint} HTTP {e.code}: {err_body or e.reason}")
        except Exception as e:
            errors.append(f"{endpoint}: {e}")

    return {
        "ok": False,
        "message": "生视频失败：" + ("；".join(errors[:4]) if errors else "未知错误"),
        "model": model,
        "channel_id": ch.get("id"),
        "channel_name": ch.get("name"),
    }


def generate_music_via_host(
    *,
    prompt: str,
    model: str = "",
    channel_id: str = "",
    style: str = "",
    lyrics: str = "",
    title: str = "",
    instrumental: bool = False,
    bridge_port: int = DEFAULT_PORT,
) -> Dict[str, Any]:
    """Suno / Suno 中转站 文生音乐。异步提交 → 轮询 → 下载 mp3 到 inbox。

    支持三种主流 Suno API 格式：
    1) 官方 platform.suno.com   → POST /v0/audio → GET /v0/audio/{id}
    2) sunoapi.org / record-info → POST /api/v1/generate → GET /api/v1/generate/record-info?taskId=
    3) 神马 / openai-hk 中转   → POST /suno/submit/music → GET /suno/fetch?task_id=

    落盘前校验文件有效性（>1KB），避免返回 0 字节假成功。
    """
    import urllib.error
    import urllib.request

    prompt = (prompt or "").strip()
    if not prompt and not lyrics.strip():
        return {"ok": False, "message": "音乐提示词或歌词不能为空"}

    ch, model, patch = _resolve_aigc_channel(
        channel_id=channel_id,
        capability="music",
        default_model_key="musicModel",
    )

    # 若渠道没有 capability=music，尝试用 "audio" capability 兜底（TTS 渠道不算）
    if ch is None or not (ch.get("apiKey") or "").strip():
        for c in list((patch.get("channels") or [])):
            if not (c.get("apiKey") or "").strip():
                continue
            if any((m.get("capability") in ("music",) for m in (c.get("models") or []))):
                ch = c
                break

    if ch is None or not (ch.get("apiKey") or "").strip():
        return {
            "ok": False,
            "message": (
                "没有可用的 Suno 音乐生成渠道。请到「模型管理」添加 Suno 渠道 "
                "（capability 设为 music，key 填 suno.com 或 sunoapi.org 的 API Key）。"
            ),
        }

    if not model:
        defaults = dict(patch.get("defaults") or {})
        raw = str(defaults.get("musicModel") or "")
        if "::" in raw:
            model = raw.split("::", 1)[-1]
        if not model:
            for m in ch.get("models") or []:
                if m.get("capability") == "music":
                    model = str(m.get("name") or "")
                    break

    base = str(ch.get("baseUrl") or "").rstrip("/")
    if not base:
        return {"ok": False, "message": "渠道缺少 baseUrl（Suno 官方用 https://api.suno.com，中转站各有不同）"}

    api_key = str(ch.get("apiKey") or "")
    errors: List[str] = []

    def _json_req(method: str, url: str, body: Optional[Dict[str, Any]] = None, timeout: float = 120):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))

    def _download_to_inbox(file_url: str, ext: str = ".mp3") -> Dict[str, Any]:
        """下载音频到 canvas inbox 并返回可播放 URL。下载后校验文件有效性（>1KB）。"""
        try:
            req = urllib.request.Request(
                file_url,
                headers={"Authorization": f"Bearer {api_key}"} if file_url.startswith(base) else {},
            )
            with urllib.request.urlopen(req, timeout=300) as resp:
                raw = resp.read()
        except Exception as e:
            return {"ok": False, "message": f"下载音乐失败: {e}"}

        # 有效性防线：0 字节或极小文件视为无效
        if not raw or len(raw) < 1024:
            return {"ok": False, "message": f"下载到的音乐文件无效（{len(raw)} 字节，可能是 CDN 404 页）"}

        name = f"music_{int(time.time())}_{abs(hash(prompt or lyrics)) % 100000}{ext}"
        dest = os.path.join(canvas_inbox_dir(), name)
        with open(dest, "wb") as f:
            f.write(raw)
        url = f"http://127.0.0.1:{int(bridge_port)}/inbox_file/{name}"
        return {
            "ok": True,
            "audio_path": dest,
            "audio_url": url,
            "title": title or "AI 生成音乐",
            "duration_hint": None,
            "model": model,
            "channel_id": ch.get("id"),
            "channel_name": ch.get("name"),
            "message": f"音乐已生成（{ch.get('name') or 'Suno'} · {model}）",
        }

    # ── 分支 1：Suno 官方 API（api.suno.com / v0/audio） ──
    if "suno.com" in base.lower():
        try:
            body: Dict[str, Any] = {}
            if lyrics.strip():
                body["lyrics"] = lyrics.strip()
                if style.strip():
                    body["style"] = style.strip()
            else:
                body["description"] = prompt
            if title.strip():
                body["title"] = title.strip()
            if instrumental:
                body["instrumental"] = True

            submit = _json_req("POST", base + "/v0/audio", body, timeout=120)
            task_id = str((submit.get("id") or "")) if isinstance(submit, dict) else ""
            if not task_id:
                errors.append(f"Suno 官方 submit 无 id: {str(submit)[:200]}")
            else:
                deadline = time.time() + 600
                while time.time() < deadline:
                    st = _json_req("GET", f"{base}/v0/audio/{task_id}", timeout=60)
                    status = str((st.get("status") if isinstance(st, dict) else "") or "").lower()
                    if status in ("complete", "completed"):
                        audio_url = str((st.get("audio_url") if isinstance(st, dict) else "") or "")
                        if audio_url:
                            return _download_to_inbox(audio_url)
                        errors.append(f"Suno 完成但无 audio_url: {str(st)[:200]}")
                        break
                    if status in ("error", "failed"):
                        errors.append(f"Suno 失败: {str(st.get('error') or st)[:200] if isinstance(st, dict) else str(st)[:200]}")
                        break
                    time.sleep(4)
                else:
                    errors.append("Suno 官方轮询超时（300s）")
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                pass
            errors.append(f"Suno 官方 HTTP {e.code}: {err_body or e.reason}")
        except Exception as e:
            errors.append(f"Suno 官方异常: {e}")

    # ── 分支 2：sunoapi.org / record-info 格式 ──
    elif "sunoapi" in base.lower() or base.endswith("/api/v1/generate".rsplit("/", 1)[0]):
        try:
            body2: Dict[str, Any] = {
                "prompt": lyrics.strip() or prompt,
                "customMode": bool(lyrics.strip()),
                "instrumental": instrumental,
                "model": model or "V4_5ALL",
            }
            if lyrics.strip():
                body2["title"] = title.strip() if title else "AI Song"

            submit2 = _json_req("POST", base + "/api/v1/generate", body2, timeout=120)
            task_id2 = ""
            if isinstance(submit2, dict):
                d = submit2.get("data")
                if isinstance(d, dict):
                    task_id2 = str(d.get("taskId") or "")
                elif isinstance(d, str):
                    task_id2 = d
                task_id2 = task_id2 or str(submit2.get("taskId") or "")

            if not task_id2:
                errors.append(f"sunoapi submit 无 taskId: {str(submit2)[:200]}")
            else:
                deadline = time.time() + 600
                while time.time() < deadline:
                    st2 = _json_req(
                        "GET",
                        f"{base}/api/v1/generate/record-info?taskId={task_id2}",
                        timeout=60,
                    )
                    d2 = (st2.get("data") if isinstance(st2, dict) else None) or {}
                    status2 = str((d2.get("status") if isinstance(d2, dict) else "") or "").lower()
                    resp = (d2.get("response") if isinstance(d2, dict) else None) or {}
                    suno_list = (resp.get("sunoData") if isinstance(resp, dict) else None) or []
                    if status2 == "success" and suno_list:
                        first = suno_list[0] if isinstance(suno_list[0], dict) else {}
                        audio_url2 = str(first.get("audioUrl") or "")
                        if audio_url2:
                            result = _download_to_inbox(audio_url2)
                            if result.get("ok") and isinstance(first.get("duration"), (int, float)):
                                result["duration_hint"] = float(first["duration"])
                                if first.get("title"):
                                    result["title"] = str(first["title"])
                            return result
                        errors.append(f"sunoapi 成功但无 audioUrl: {str(st2)[:200]}")
                        break
                    if status2 in ("failed", "error", "canceled", "cancelled"):
                        errors.append(f"sunoapi 失败: {str(d2.get('errorMessage') or st2)[:200]}")
                        break
                    time.sleep(4)
                else:
                    errors.append("sunoapi 轮询超时（300s）")
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                pass
            errors.append(f"sunoapi HTTP {e.code}: {err_body or e.reason}")
        except Exception as e:
            errors.append(f"sunoapi 异常: {e}")

    # ── 分支 3：神马 / openai-hk 等中转（/suno/submit/music + /suno/fetch） ──
    else:
        try:
            body3: Dict[str, Any]
            if lyrics.strip():
                body3 = {
                    "prompt": lyrics.strip(),
                    "tags": style.strip() or "pop",
                    "mv": model or "chirp-v3-5",
                    "title": title.strip() or "AI Song",
                }
            else:
                body3 = {
                    "gpt_description_prompt": prompt,
                    "model": model or "chirp-v3-5",
                }
            if instrumental:
                body3["make_instrumental"] = True

            submit3 = _json_req("POST", base + "/suno/submit/music", body3, timeout=120)
            task_id3 = ""
            if isinstance(submit3, dict):
                d3 = submit3.get("data")
                if isinstance(d3, str):
                    task_id3 = d3
                elif isinstance(d3, dict):
                    task_id3 = str(d3.get("task_id") or d3.get("taskId") or "")
                elif isinstance(d3, list) and d3:
                    first = d3[0] if isinstance(d3[0], dict) else {}
                    task_id3 = str(first.get("task_id") or first.get("taskId") or "")
                task_id3 = task_id3 or str(submit3.get("task_id") or submit3.get("taskId") or "")

            if not task_id3:
                errors.append(f"中转站 submit 无 taskId: {str(submit3)[:200]}")
            else:
                deadline = time.time() + 600
                while time.time() < deadline:
                    try:
                        st3 = _json_req(
                            "GET",
                            f"{base}/suno/fetch?task_id={task_id3}",
                            timeout=60,
                        )
                    except Exception:
                        st3 = _json_req(
                            "GET",
                            f"{base}/suno/fetch?taskId={task_id3}",
                            timeout=60,
                        )
                    data3 = (st3.get("data") if isinstance(st3, dict) else None) or {}
                    if isinstance(data3, list) and data3:
                        data3 = data3[0] if isinstance(data3[0], dict) else {}
                    status3 = str((data3.get("status") if isinstance(data3, dict) else "") or "").lower()
                    clips = (data3.get("clips") if isinstance(data3, dict) else None) or []
                    if isinstance(data3, dict) and data3.get("audio_url"):
                        return _download_to_inbox(str(data3["audio_url"]))
                    if clips and isinstance(clips[0], dict):
                        audio_url3 = str(clips[0].get("audio_url") or clips[0].get("audioUrl") or "")
                        if audio_url3:
                            return _download_to_inbox(audio_url3)
                    if status3 in ("failed", "error"):
                        errors.append(f"中转站失败: {str(st3)[:200]}")
                        break
                    time.sleep(4)
                else:
                    errors.append("中转站轮询超时（300s）")
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                pass
            errors.append(f"中转站 HTTP {e.code}: {err_body or e.reason}")
        except Exception as e:
            errors.append(f"中转站异常: {e}")

    return {
        "ok": False,
        "message": "音乐生成失败：" + ("；".join(errors[:4]) if errors else "未知错误"),
        "model": model,
        "channel_id": ch.get("id") if ch else "",
        "channel_name": ch.get("name") if ch else "",
    }


def _parse_storyboard_json(text: str) -> List[Dict[str, Any]]:
    """从 LLM 输出中提取 JSON 数组（兼容代码块包裹）。"""
    try:
        cleaned = (text or "").strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
            if cleaned.endswith("```"):
                cleaned = cleaned.rsplit("```", 1)[0]
            cleaned = cleaned.strip()
        start = cleaned.find("[")
        end = cleaned.rfind("]")
        if start >= 0 and end > start:
            data = json.loads(cleaned[start : end + 1])
            return data if isinstance(data, list) else []
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    return []


def _heuristic_storyboard(script: str) -> List[Dict[str, Any]]:
    """LLM 不可用时：按段落/句号切分启发式分镜。"""
    text = (script or "").strip()
    if not text:
        return [
            {
                "id": 1,
                "duration": 5,
                "shot": "远景",
                "description": "开场镜头",
                "dialogue": "",
            },
            {
                "id": 2,
                "duration": 5,
                "shot": "中景",
                "description": "主体展示",
                "dialogue": "",
            },
            {
                "id": 3,
                "duration": 5,
                "shot": "特写",
                "description": "收尾定格",
                "dialogue": "",
            },
        ]
    parts: List[str] = []
    for block in text.replace("\r\n", "\n").split("\n"):
        block = block.strip()
        if not block:
            continue
        for piece in block.replace("。", "。\n").split("\n"):
            piece = piece.strip()
            if piece:
                parts.append(piece)
    if not parts:
        parts = [text[:200]]
    parts = parts[:25]
    shotsizes = ["远景", "全景", "中景", "近景", "特写"]
    out: List[Dict[str, Any]] = []
    for i, p in enumerate(parts):
        dialogue = ""
        desc = p
        if "「" in p and "」" in p:
            try:
                dialogue = p[p.index("「") + 1 : p.index("」")]
                desc = (p[: p.index("「")] + p[p.index("」") + 1 :]).strip() or p
            except ValueError:
                pass
        out.append(
            {
                "id": i + 1,
                "duration": max(3, min(12, 2 + len(p) // 20)),
                "shot": shotsizes[i % len(shotsizes)],
                "description": desc[:200],
                "dialogue": dialogue[:120],
            }
        )
    return out


def storyboard_breakdown(script: str) -> Dict[str, Any]:
    """一键拉片：剧本 → 分镜表。优先 AIEngine，失败启发式。"""
    script = (script or "").strip()
    if not script:
        return {"ok": False, "shots": [], "message": "剧本为空"}

    try:
        from app.core.ai_engine import AIEngine

        engine = AIEngine()
        messages = [
            {
                "role": "system",
                "content": (
                    "你是分镜师。把剧本拆成结构化分镜表，每镜一行 JSON："
                    '{"id":1,"duration":5,"shot":"特写/中景/远景",'
                    '"description":"画面描述","dialogue":"对白"}。'
                    "输出 JSON 数组，不要其他文字。"
                ),
            },
            {"role": "user", "content": f"剧本：\n{script}\n\n请输出分镜表 JSON。"},
        ]
        full = ""
        for chunk in engine.chat_with_fallback(
            messages, template=lambda: json.dumps(_heuristic_storyboard(script), ensure_ascii=False)
        ):
            full += chunk
        shots = _parse_storyboard_json(full.strip())
        if shots:
            # 规范化字段
            norm: List[Dict[str, Any]] = []
            for i, s in enumerate(shots):
                if not isinstance(s, dict):
                    continue
                norm.append(
                    {
                        "id": int(s.get("id") or i + 1),
                        "duration": float(s.get("duration") or 5),
                        "shot": str(s.get("shot") or "中景"),
                        "description": str(s.get("description") or ""),
                        "dialogue": str(s.get("dialogue") or ""),
                    }
                )
            if norm:
                return {
                    "ok": True,
                    "shots": norm,
                    "fallback": False,
                    "message": f"拉片完成（LLM）{len(norm)} 镜",
                }
    except Exception as e:
        shots = _heuristic_storyboard(script)
        return {
            "ok": True,
            "shots": shots,
            "fallback": True,
            "message": f"LLM 失败，已用启发式：{e}",
        }

    shots = _heuristic_storyboard(script)
    return {
        "ok": True,
        "shots": shots,
        "fallback": True,
        "message": f"拉片完成（启发式）{len(shots)} 镜",
    }


def list_editor_outbox() -> List[Dict[str, Any]]:
    with _OUTBOX_LOCK:
        return list(_EDITOR_OUTBOX)


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
                        pass
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
                raw, content_type = _fetch_remote_bytes(url)
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
            self._json(200, {"ok": True, "items": items})
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
                        pass
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
                        pass
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
                    pass
            self._json(code, res)
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
                first_frame=str(data.get("first_frame") or data.get("firstFrame") or ""),
                last_frame=str(data.get("last_frame") or data.get("lastFrame") or ""),
                bridge_port=int(port),
            )
            code = 200 if res.get("ok") else 400
            if not res.get("ok"):
                try:
                    from app.core.ai_engine import AIEngine; AIEngine().increment_ng_count(1)
                except Exception:
                    pass
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
                    pass
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
                    pass
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
                    pass
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
                                    pass
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

        # ── GET /host/video-batch?job_id=xxx：查询批量任务状态 ──
        if parsed.path == "/host/video-batch":
            qs = parse_qs(parsed.query)
            job_id = (qs.get("job_id") or [""])[0] if hasattr(parsed, "query") else ""
            if not job_id:
                # 列出所有任务
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
            res = storyboard_breakdown(str(data.get("script") or ""))
            code = 200 if res.get("ok") else 400
            self._json(code, res)
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
        )
        self._json(200 if res.get("success") else 400, res)

        # ── 画布节点插件操作（install / toggle / uninstall）──
        if parsed.path == "/host/plugins/install":
            if not _check_host_token(self):
                self._json(401, {"ok": False, "message": "unauthorized"})
                return
            plugin_id = str(data.get("id") or "").strip()
            if not plugin_id:
                self._json(400, {"ok": False, "message": "plugin id required"})
                return
            # 先在官方注册表找预设
            preset = next((p for p in _BUILTIN_PLUGIN_REGISTRY if p.get("id") == plugin_id), None)
            entry: Dict[str, Any] = {
                "name": str(data.get("name") or preset.get("name") or plugin_id),
                "version": str(data.get("version") or preset.get("version") or "0.0.0"),
                "description": str(data.get("description") or preset.get("description") or ""),
                "url": str(data.get("url") or preset.get("url") or ""),
                "nodes": data.get("nodes") or preset.get("nodes") or [],
                "official": bool(data.get("official", preset.get("official", False))),
                "enabled": True,
            }
            saved = _upsert_canvas_plugin(plugin_id, **entry)
            self._json(200, {"ok": True, "plugin": saved})
            return

        if parsed.path == "/host/plugins/toggle":
            if not _check_host_token(self):
                self._json(401, {"ok": False, "message": "unauthorized"})
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
      "position:fixed", "right:16px", "bottom:16px", "z-index:2147483647",
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

    var fab = document.createElement("button");
    fab.id = "shiguang-bridge-fab";
    fab.type = "button";
    fab.textContent = "拾光";
    fab.title = "打开拾光剪影面板";
    fab.style.cssText = [
      "position:fixed", "right:16px", "bottom:16px", "z-index:2147483647",
      "display:none", "padding:10px 14px", "border:0", "border-radius:999px",
      "background:#2563eb", "color:#fff", "font:12px/1 system-ui,sans-serif",
      "font-weight:700", "cursor:pointer", "box-shadow:0 6px 18px rgba(0,0,0,.35)"
    ].join(";");
    document.documentElement.appendChild(fab);

    function hidePanel(persist) {
      panel.style.display = "none";
      fab.style.display = "block";
      if (persist) localStorage.setItem("__shiguang_panel_hidden", "1");
    }
    function showPanel() {
      panel.style.display = "block";
      fab.style.display = "none";
      localStorage.removeItem("__shiguang_panel_hidden");
    }
    document.getElementById("sg-close").onclick = function () { hidePanel(true); };
    document.getElementById("sg-min").onclick = function () { hidePanel(true); };
    fab.onclick = showPanel;
    window.__shiguangShowBridgePanel = showPanel;
    window.__shiguangHideBridgePanel = function () { hidePanel(true); };

    if (localStorage.getItem("__shiguang_panel_hidden") === "1") {
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
                pass
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
                pass
            self._httpd = None
        self._thread = None


_bridge_singleton: Optional[CanvasBridgeServer] = None


def get_canvas_bridge() -> CanvasBridgeServer:
    global _bridge_singleton
    if _bridge_singleton is None:
        _bridge_singleton = CanvasBridgeServer()
    return _bridge_singleton

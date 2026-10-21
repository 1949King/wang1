# -*- coding: utf-8 -*-
"""数字人「口型成片」诚实合成管线（V4.46.4 · 2026-10-22）

背景（实测）：画布 DigitalHumanNode 的「口型成片」按钮此前是**写死的拒绝文案**
（mediaExtraNodes.tsx:303，冻结区），后端没有任何对应端点；而
`ai/video_lipsync.py` 的真人视频对口型引擎（MuseTalk/LatentSync）未安装、
未接线。用户诉求「完善数字人节点」= 把这条断头路接成**能交付且诚实**的管线。

三级诚实降级（与 video_lipsync 的降级链同构，逐级不撒谎）::

    ① still_video     静态形象 + 配音 → 可入轨 mp4（**口型不动**，产物必须标
                       mouth_moved=False；这是"能出片"与"口型同步"的边界）
    ② unavailable     缺图/缺音/缺 ffmpeg → ok=False + 具体缺什么

真·口型同步（video_sync）需要：真人**视频**素材 + MuseTalk/LatentSync 引擎，
本模块只探测并如实转告（`lipsync_engine_note()`），不假装能做。

纪律：
* 顶层零 Qt、不 import 冻结区之外的私有件（canvas_bridge 公共函数可 import）；
* 产物只落画布 inbox（单一出口），返回 /inbox_file/ URL（WebView 只认这个）；
* ffmpeg 失败/超时 → 诚实报错带 stderr 摘要，不产出半成品冒充成功。
"""
from __future__ import annotations

import base64
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("AI短剧编辑器.canvas_bridge")

PATH_STILL_VIDEO = "still_video"
PATH_UNAVAILABLE = "unavailable"

_IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
_AUDIO_EXT = (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg")


def lipsync_engine_note() -> str:
    """真·口型同步的可用性说明（诚实转告，不代做判断）。"""
    try:
        from app.core.ai.video_lipsync import unavailable_reason
    except ImportError:
        try:
            from core.ai.video_lipsync import unavailable_reason  # type: ignore
        except ImportError:
            return "口型同步引擎模块缺失。"
    return unavailable_reason()


def plan_talking(*, has_image: bool, has_audio: bool) -> str:
    """纯函数：输入齐备度 → 走哪条路径（可单测，降级不撒谎的机器化表达）。"""
    if has_image and has_audio:
        return PATH_STILL_VIDEO
    return PATH_UNAVAILABLE


def missing_inputs(*, has_image: bool, has_audio: bool) -> list:
    missing = []
    if not has_image:
        missing.append("形象图（上传或绑定镜头/图片节点）")
    if not has_audio:
        missing.append("配音（先点「生成配音」）")
    return missing


def _ffmpeg_bin() -> Optional[str]:
    return shutil.which("ffmpeg")


def synthesize_still_video(
    image_path: str,
    audio_path: str,
    out_path: str,
    *,
    timeout_s: float = 120.0,
) -> Dict[str, Any]:
    """静图 + 配音 → mp4（-shortest 截到音频长度；口型不动，产物如实标注）。

    返回 {ok, error?}；失败时删除半成品，绝不留假产物。
    """
    ffmpeg = _ffmpeg_bin()
    if not ffmpeg:
        return {"ok": False, "error": "本机未找到 ffmpeg，无法合成视频"}
    if not os.path.isfile(image_path):
        return {"ok": False, "error": f"形象图不存在: {os.path.basename(image_path)}"}
    if not os.path.isfile(audio_path):
        return {"ok": False, "error": f"配音文件不存在: {os.path.basename(audio_path)}"}
    cmd = [
        ffmpeg, "-y",
        "-loop", "1", "-i", image_path,
        "-i", audio_path,
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-tune", "stillimage",
        "-pix_fmt", "yuv420p", "-r", "30",
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-c:a", "aac", "-b:a", "160k",
        "-shortest", "-movflags", "+faststart",
        out_path,
    ]
    try:
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        r = subprocess.run(
            cmd, capture_output=True, timeout=timeout_s, creationflags=flags,
        )
    except subprocess.TimeoutExpired:
        _unlink_quiet(out_path)
        return {"ok": False, "error": f"合成超时（>{int(timeout_s)}s）"}
    except OSError as e:
        _unlink_quiet(out_path)
        return {"ok": False, "error": f"ffmpeg 启动失败: {e}"}
    if r.returncode != 0 or not os.path.isfile(out_path) or os.path.getsize(out_path) < 1024:
        err = (r.stderr or b"").decode("utf-8", errors="replace")[-400:]
        _unlink_quiet(out_path)
        return {"ok": False, "error": f"ffmpeg 合成失败: {err or r.returncode}"}
    return {"ok": True, "path": out_path, "bytes": os.path.getsize(out_path)}


def _unlink_quiet(path: str) -> None:
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        logger.debug("清理合成半成品失败: %s", path, exc_info=True)


def make_talking_video(
    image_local: str,
    audio_local: str,
    out_name: str,
    inbox_dir: str,
) -> Dict[str, Any]:
    """完整编排：校验输入 → 合成 → 返回诚实结果（URL 由路由层拼）。

    out_name 已由调用方 _safe_filename 清洗并保证 .mp4 后缀；产物直接落 inbox。
    """
    has_image = bool(image_local) and os.path.isfile(image_local) \
        and os.path.splitext(image_local)[1].lower() in _IMAGE_EXT
    has_audio = bool(audio_local) and os.path.isfile(audio_local) \
        and os.path.splitext(audio_local)[1].lower() in _AUDIO_EXT
    path = plan_talking(has_image=has_image, has_audio=has_audio)
    if path == PATH_UNAVAILABLE:
        return {
            "ok": False,
            "path": PATH_UNAVAILABLE,
            "mouth_moved": False,
            "missing": missing_inputs(has_image=has_image, has_audio=has_audio),
            "error": "输入不齐备，未合成（非假成功）",
            "lipsync_note": lipsync_engine_note(),
        }
    out_path = os.path.join(inbox_dir, out_name)
    res = synthesize_still_video(image_local, audio_local, out_path)
    if not res.get("ok"):
        return {
            "ok": False,
            "path": PATH_STILL_VIDEO,
            "mouth_moved": False,
            "error": res.get("error", "合成失败"),
            "lipsync_note": lipsync_engine_note(),
        }
    return {
        "ok": True,
        "path": PATH_STILL_VIDEO,
        "mouth_moved": False,
        "file": out_path,
        "bytes": res["bytes"],
        "note": "静态形象 + 配音已合成 mp4（口型未动）；真·口型同步见 lipsync_note",
        "lipsync_note": lipsync_engine_note(),
    }


def temp_media_dir() -> str:
    return tempfile.mkdtemp(prefix="sg_dh_")


# ── 媒体引用解析（安全边界）─────────────────────────────────────
# HTTP 调用方只许给三种引用：data URL / inbox_file URL / inbox 内裸文件名。
# **绝不接受任意绝对路径** —— 否则本机任何进程能借 ffmpeg 读磁盘任意文件。

_MIME_EXT = {
    "image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp",
    "image/gif": ".gif", "image/bmp": ".bmp",
    "audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/wav": ".wav",
    "audio/x-wav": ".wav", "audio/mp4": ".m4a", "audio/aac": ".aac",
    "audio/flac": ".flac", "audio/ogg": ".ogg",
}
_SAFE_RE = re.compile(r"^[A-Za-z0-9._\-\u4e00-\u9fff]{1,120}$")


def _safe_name(name: str) -> str:
    """文件名清洗：去路径分隔符/控制字符；不合法返回空串。"""
    n = os.path.basename((name or "").strip())
    if not n or ".." in n or not _SAFE_RE.match(n):
        return ""
    return n


def resolve_media_ref(
    ref: str,
    inbox_dir: str,
    *,
    prefix: str = "dh_",
) -> Tuple[str, str]:
    """把媒体引用解析为本地文件路径。返回 (path, error)，二者仅一个非空。

    - ``data:<mime>;base64,...`` → 解码落 inbox（与 /host/upload-asset 同归宿）
    - ``/inbox_file/<name>`` 或 ``http://…/inbox_file/<name>`` → inbox 内文件
    - 裸文件名（存在于 inbox）→ inbox 内文件
    - 其他（含绝对路径）→ 拒绝
    """
    s = (ref or "").strip()
    if not s:
        return "", "引用为空"
    if s.startswith("data:"):
        m = re.match(r"data:([^;,]+)[^,]*,", s)
        mime = (m.group(1) if m else "application/octet-stream").lower()
        ext = _MIME_EXT.get(mime, "")
        if not ext:
            return "", f"不支持的 data URL 类型: {mime}"
        try:
            payload = s.split(",", 1)[1]
            raw = base64.b64decode(payload)
        except (ValueError, IndexError):
            return "", "data URL base64 解码失败"
        if not raw or len(raw) > 80 * 1024 * 1024:
            return "", "data URL 内容为空或超 80MB"
        name = f"{prefix}{int(time.time() * 1000)}_{os.urandom(4).hex()}{ext}"
        dest = os.path.join(inbox_dir, name)
        try:
            with open(dest, "wb") as f:
                f.write(raw)
        except OSError as e:
            return "", f"data URL 落盘失败: {e}"
        return dest, ""
    m = re.search(r"/inbox_file/([^/?#]+)", s)
    cand = m.group(1) if m else s
    name = _safe_name(cand)
    if not name:
        return "", "引用不合法（只接受 inbox 文件 / data URL）"
    path = os.path.join(inbox_dir, name)
    if not os.path.isfile(path):
        return "", f"inbox 中不存在文件: {name}"
    return path, ""

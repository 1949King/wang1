# -*- coding: utf-8 -*-
"""白模姿态视频合成服务（模式 B · 第四刀）
===================================================

把 3D 导演台逐帧渲染出的 PNG 帧序列合成为 mp4，作为 `reference_video`
走**已有的**第一刀通道（`reference_video` 已贯通 bridge → server → generate_video_via_host）。

为什么要「逐帧导出帧序列 → 后端合成」而不是前端实时录制：
  - 前端 `MediaRecorder` 录到的是「实时发生」的过程，会掉帧；
  - 且 WebGL canvas 用 `preserveDrawingBuffer:false`（见 Stage3D.tsx 注释），
    实时录制拿不到稳定像素，开 `preserveDrawingBuffer` 又要每帧复制定全屏缓冲。
  - 逐帧导出则是「要哪帧渲染哪帧」，帧率精确、不掉帧，且复用既有的离屏 RenderTarget 读像素机制。

架构位置：Stage3D.tsx（逐帧渲染 + 采集） → bridge.ts（上传） → canvas_server(/host/pose-video-encode)
          → **本模块（解码 + FFmpeg 合成 + 落 inbox）**

设计约束（沿用本功能全链的既有铁律）：
  - **诚实失败**：帧数 0 / 超上限 / 解码失败 / FFmpeg 缺失 / 编码失败 → 明确 message，绝不产假视频；
  - **不假成功**：只有 mp4 真的落盘且体积 > 0 才返回 ok:True；
  - 临时目录在所有退出路径上都被清理（try/finally）。
"""
from __future__ import annotations

import base64
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("AI短剧编辑器.core.ai.pose_video_service")

#: 帧数硬上限 —— 与 `pose_worker.py` 的 `--max-frames 900` 对齐，
#: 避免两侧上限不一致导致「解析得出、录不下来」。
MAX_FRAMES = 900

#: 单帧 PNG 上限（base64 解码后）。1080p PNG 通常 <3MB；超过视为异常数据。
MAX_FRAME_BYTES = 8 * 1024 * 1024

DEFAULT_FPS = 25

#: data URL 前缀：`data:image/png;base64,`
_DATA_URL_RE = re.compile(r"^data:image/(png|jpeg|jpg);base64,(.+)$", re.DOTALL)


class PoseVideoError(Exception):
    """可对外解释的失败（会原样进 message，中文可读）。"""


def _decode_frame(data_url: str, index: int) -> bytes:
    """把单帧 data URL 解码为字节；失败抛 PoseVideoError（带帧号，便于定位）。"""
    if not isinstance(data_url, str) or not data_url:
        raise PoseVideoError(f"第 {index + 1} 帧为空")
    m = _DATA_URL_RE.match(data_url.strip())
    if not m:
        raise PoseVideoError(
            f"第 {index + 1} 帧不是合法的 PNG/JPEG data URL"
            f"（应以 data:image/png;base64, 开头）"
        )
    try:
        raw = base64.b64decode(m.group(2), validate=False)
    except Exception as e:
        raise PoseVideoError(f"第 {index + 1} 帧 base64 解码失败：{e}") from e
    if not raw:
        raise PoseVideoError(f"第 {index + 1} 帧解码后为空")
    if len(raw) > MAX_FRAME_BYTES:
        raise PoseVideoError(
            f"第 {index + 1} 帧过大（{len(raw) // 1024 // 1024}MB > "
            f"{MAX_FRAME_BYTES // 1024 // 1024}MB）"
        )
    return raw


def _inbox_dir() -> str:
    """画布 inbox 目录（复用 canvas_aigc 的既有定义，避免两处各写一份）。"""
    from app.core.canvas_aigc import _canvas_inbox_dir
    return _canvas_inbox_dir()


def encode_pose_video(
    frames: List[str],
    fps: int = DEFAULT_FPS,
    name: str = "pose_motion",
) -> Dict[str, Any]:
    """把 PNG data URL 序列合成为 mp4 并落进画布 inbox。

    返回（成功）::

        {"ok": True, "url": "/inbox_file/xxx.mp4", "path": "...", "frames": 90,
         "fps": 25, "duration": 3.6, "bytes": 123456}

    返回（失败）::

        {"ok": False, "message": "<中文可读原因>"}
    """
    # ── 前置校验：全部走「诚实失败」 ──
    if not frames:
        return {"ok": False, "message": "没有可合成的帧（请先解析姿态并加载关键点轨迹）"}
    if not isinstance(frames, list):
        return {"ok": False, "message": "frames 必须是数组"}

    total = len(frames)
    if total > MAX_FRAMES:
        return {
            "ok": False,
            "message": f"帧数 {total} 超过上限 {MAX_FRAMES}（请缩短参考视频或增大采样间隔）",
        }
    try:
        fps_i = int(fps)
    except (TypeError, ValueError):
        return {"ok": False, "message": f"fps 必须是整数，收到 {fps!r}"}
    if fps_i <= 0 or fps_i > 120:
        return {"ok": False, "message": f"fps 需在 1~120，收到 {fps_i}"}

    # ── 解码全部帧（先全解，任一失败就整体失败，不留半成品） ──
    blobs: List[bytes] = []
    for i, f in enumerate(frames):
        try:
            blobs.append(_decode_frame(f, i))
        except PoseVideoError as e:
            return {"ok": False, "message": str(e)}

    from app.core.ffmpeg_utils import get_ffmpeg

    ffmpeg = get_ffmpeg()

    tmpdir = tempfile.mkdtemp(prefix="pose_video_")
    try:
        for i, blob in enumerate(blobs):
            with open(os.path.join(tmpdir, f"frame_{i:05d}.png"), "wb") as fh:
                fh.write(blob)
        # 释放内存：写盘后不再需要 base64 原串
        blobs = []

        out_path = os.path.join(tmpdir, "out.mp4")
        cmd = [
            ffmpeg, "-y",
            "-framerate", str(fps_i),
            "-i", os.path.join(tmpdir, "frame_%05d.png"),
            # 帧序列可能不是偶数边长，libx264 + yuv420p 要求偶数，统一裁到偶数
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            out_path,
        ]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=600,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except FileNotFoundError:
            return {
                "ok": False,
                "message": "未找到 FFmpeg（无法合成白模视频）。请安装 FFmpeg 或检查路径配置。",
            }
        except subprocess.TimeoutExpired:
            return {"ok": False, "message": "FFmpeg 合成超时（600s），请减少帧数后重试"}

        if proc.returncode != 0:
            tail = (proc.stderr or "").strip().splitlines()[-3:]
            return {
                "ok": False,
                "message": "FFmpeg 合成失败：" + (" | ".join(tail) or f"rc={proc.returncode}"),
            }
        if not os.path.isfile(out_path) or os.path.getsize(out_path) <= 0:
            return {"ok": False, "message": "FFmpeg 报告成功但没有产出文件（诚实失败，不返回假结果）"}

        # ── 落 canvas inbox ──
        safe_name = re.sub(r"[^0-9A-Za-z_\u4e00-\u9fff-]", "_", str(name or "pose_motion"))[:48]
        dst_name = f"{safe_name}_{int(time.time())}.mp4"
        try:
            inbox = _inbox_dir()
            os.makedirs(inbox, exist_ok=True)
            dst_path = os.path.join(inbox, dst_name)
            shutil.move(out_path, dst_path)
        except Exception as e:
            logger.exception("[pose-video] 落 inbox 失败")
            return {"ok": False, "message": f"视频已合成但落入画布 inbox 失败：{e}"}

        return {
            "ok": True,
            "url": f"/inbox_file/{dst_name}",
            "path": dst_path,
            "frames": total,
            "fps": fps_i,
            "duration": round(total / fps_i, 3),
            "bytes": os.path.getsize(dst_path),
        }
    finally:
        # 无论成败都清临时目录：mp4 已 move 进 inbox，剩下的只有 PNG 中间产物
        shutil.rmtree(tmpdir, ignore_errors=True)


__all__ = ["MAX_FRAMES", "DEFAULT_FPS", "PoseVideoError", "encode_pose_video"]

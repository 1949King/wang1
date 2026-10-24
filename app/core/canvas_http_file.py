# -*- coding: utf-8 -*-
"""画布桥文件服务：流式 + Range（V4.46.1 安全/性能刀，2026-10-20）

问题：`/inbox_file/*` 与 `/editor_file/*` 原先把**整个文件读进内存**再一次性写回
（`data = f.read()`）。画布 inbox 里是生成的 mp4（常 50~500MB），后果：
1. 一次预览/切节点就吃掉整段内存；多个请求叠加 → 卡顿甚至 OOM；
2. `<video>` 拖动进度条无法 seek（不支持 Range，浏览器只能整段重下）。

修法：分块拷贝（1MB）+ 单段 Range（`bytes=a-b` / `a-` / `-suffix`）→ 206 部分内容。
与 Python `http.server.SimpleHTTPRequestHandler` 的 Range 语义对齐，但**不做多段
multipart/byteranges**（视频 seek 用不到；诚实声明在 416/降级分支里）。

纪律：纯标准库；只读服务，不写任何状态；调用方负责鉴权（本模块不判 token，
与 canvas_server 的既有分工一致——这两个前缀路由本来也不走 `_check_host_token`，
见下方注释）。
"""
from __future__ import annotations

import logging
import mimetypes
import os
import re
from http.server import BaseHTTPRequestHandler
from typing import Optional, Tuple

logger = logging.getLogger("AI短剧编辑器.canvas_bridge")

# 分块大小：1MB（够吞吐，又不会一次占住内存）
_CHUNK = 1024 * 1024
# 仅接受单段 Range（`bytes=...`）；多段 range: bytes=0-1,5-6 直接忽略并整发
_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


def content_type_for(name: str) -> str:
    """按扩展名给 Content-Type；未知回落 octet-stream（不猜、不误标）。"""
    guess, _ = mimetypes.guess_type(name)
    return guess or "application/octet-stream"


def parse_range(header: str, size: int) -> Optional[Tuple[int, int]]:
    """解析单段 Range → (start, end)（闭区间）；无效/多段/超界返回 None（整发）。

    注意：**返回 None 表示「按完整 200 发送」**，不是错误。浏览器对无法理解的
    Range 的正常行为就是收 200 + 整包，所以这里不轻易 416。
    只有「起点明显超出文件长度」才判 416（由调用方看 `start > size` 决定）。
    """
    if not header:
        return None
    m = _RANGE_RE.match(header.strip())
    if not m:
        return None  # 多段/语法不熟 ⇒ 忽略 Range，发整包
    start_s, end_s = m.group(1), m.group(2)
    if not start_s and not end_s:
        return None
    if not start_s:
        # bytes=-N ：末尾 N 字节
        try:
            n = int(end_s)
        except ValueError:
            return None
        if n <= 0:
            return None
        start = max(0, size - n)
        return (start, size - 1)
    start = int(start_s)
    end = int(end_s) if end_s else size - 1
    if end < start:
        return None
    return (start, min(end, size - 1))


def serve_file(handler: BaseHTTPRequestHandler, fpath: str, *, inline: bool = True) -> None:
    """把 fpath 流式写给 handler（支持单段 Range / 206 / HEAD 语义）。

    fpath 必须已确认存在（调用方判 404）。失败一律诚实：写不出去（客户端断开）
    直接返回，不重试不掩盖。
    """
    try:
        size = os.path.getsize(fpath)
    except OSError as e:
        handler._json(500, {"ok": False, "message": f"stat 失败: {e}"})  # type: ignore[attr-defined]
        return

    name = os.path.basename(fpath)
    ctype = content_type_for(name)
    start, end = 0, size - 1
    partial = False
    if getattr(handler, "command", "GET") != "HEAD":
        rng = handler.headers.get("Range", "")
        if rng:
            parsed = parse_range(rng, size)
            if parsed is not None:
                start, end = parsed
                partial = True
                if start >= size:
                    # 起点越界：416 + 实际长度（浏览器会按空内容处理）
                    handler.send_response(416)
                    handler.send_header("Content-Range", f"bytes */{size}")
                    handler.send_header("Content-Length", "0")
                    handler._cors()  # type: ignore[attr-defined]
                    handler.end_headers()
                    return

    length = end - start + 1 if size else 0
    handler.send_response(206 if partial else 200)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Content-Length", str(length))
    handler.send_header("Accept-Ranges", "bytes")
    if partial:
        handler.send_header("Content-Range", f"bytes {start}-{end}/{size}")
    handler.send_header(
        "Content-Disposition",
        ('inline' if inline else 'attachment') + f'; filename="{name}"',
    )
    # 媒体文件常被反复播放：给短缓存，键变了（同名覆盖）靠浏览器重新验证
    handler.send_header("Cache-Control", "no-cache")
    handler._cors()  # type: ignore[attr-defined]
    handler.end_headers()

    if getattr(handler, "command", "GET") == "HEAD" or length <= 0:
        return
    try:
        with open(fpath, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(_CHUNK, remaining))
                if not chunk:
                    break  # 文件被截断：已发多少算多少（诚实，不补零）
                handler.wfile.write(chunk)
                remaining -= len(chunk)
    except (BrokenPipeError, ConnectionResetError, OSError):
        # 客户端断开/进度条快拖：静默结束（handle() 外层同样兜这几种）
        logger.debug("file stream aborted: %s (%d/%d bytes)", name, length - remaining, length)
    except Exception:
        logger.debug("file stream failed: %s", name, exc_info=True)

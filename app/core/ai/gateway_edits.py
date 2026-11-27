# -*- coding: utf-8 -*-
"""可选网关局部编辑客户端（Gateway Edits，T3 2026-11-20）。

对标上游无界工作台 ``server.js`` 的 ``/images/edits`` 契约（默认关）：
  · mode ∈ {inpaint, remove, outpaint}；
  · inpaint/remove 必须 image + mask **双文件**；outpaint **单图** + megapixels；
  · singleShot 强制 n=1；响应取 ``data[0].b64_json``。

设计纪律（同 video_edit_client.py 的纯模块风格）
==========================================
- 纯逻辑 + 标准库 HTTP，模块级不 import app 包（伪包可单测）；
- 渠道经 ``build_host_ai_config_patch()`` 懒加载（id ``shiguang-wujie-gateway``），
  状态统一归集 cloud_api_service，不在本模块散落全局状态；
- **默认关三重保证**：无配置 ⇒ 渠道不注入 ⇒ 本客户端诚实返 ok:false + guidance；
- **绝不自动下载、不随包权重**：网关由用户自备，本模块只发 HTTP；
- 超时/网络异常诚实失败，不返回假图。
"""
from __future__ import annotations

import base64
import json
import logging
import urllib.request
from typing import Any, Dict, List, Tuple

logger = logging.getLogger("AI短剧编辑器.core.ai.gateway_edits")

#: 模型广场渠道 id（model_config.PROVIDERS["wujie-gateway"] ⇒ 注入 id 前缀 shiguang-）。
GATEWAY_CHANNEL_ID = "shiguang-wujie-gateway"

#: 渠道未启用时给用户的指引（默认关；本地替代走 LaMa / SD1.5-inpainting 自取）。
GATEWAY_GUIDANCE = (
    "无界网关渠道未启用（默认关）。本软件绝不自动下载模型、不随包权重；如需云端语义重绘/移除/扩图：\n"
    "【启用步骤】\n"
    "  1. 自行部署无界工作台网关（默认本机 http://127.0.0.1:8190/v1），或填写已有网关 Base URL。\n"
    "  2. 打开「模型广场 → 无界网关」卡片，填 Base URL + Auth Key（网关无鉴权可填 local），点「测试连接」后保存。\n"
    "  3. 保存后渠道自动注入画布，重试本功能。\n"
    "【本地替代】未启用网关时，局部修补优先走本地 LaMa / SD1.5-inpainting（权重自取，见下载中心）。"
)

_VALID_MODES = ("inpaint", "remove", "outpaint")


def _load_channels() -> List[Dict[str, Any]]:
    """懒加载画布渠道（避免模块级 import canvas_aigc 造成循环/重依赖）。"""
    try:
        from app.core.canvas_aigc import build_host_ai_config_patch
    except ImportError:
        from core.canvas_aigc import build_host_ai_config_patch  # type: ignore
    try:
        return list(build_host_ai_config_patch().get("channels") or [])
    except Exception:
        logger.warning("[gateway_edits] 组装渠道失败", exc_info=True)
        return []


def _data_url_to_bytes(data_url: str) -> Tuple[str, bytes]:
    """data URL → (mime, 原始字节)；非法返 ("", b"")。"""
    s = str(data_url or "")
    if not s.startswith("data:"):
        return "", b""
    try:
        header, b64 = s.split(",", 1)
        mime = header[5:].split(";", 1)[0]
        return mime, base64.b64decode(b64)
    except Exception:
        logger.debug("[gateway_edits] data URL 解析失败", exc_info=True)
        return "", b""


def _build_multipart(
    fields: List[Tuple[str, str]],
    files: List[Tuple[str, bytes, str, str]],
) -> Tuple[bytes, str]:
    """组装 multipart/form-data（与 canvas_aigc.inpaint_via_host 同套路）。"""
    boundary = "----ShiguangGatewayEditBoundary"
    parts: List[bytes] = []
    for name, value in fields:
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        parts.append(str(value).encode("utf-8"))
        parts.append(b"\r\n")
    for name, value, filename, ctype in files:
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode()
        )
        parts.append(f"Content-Type: {ctype}\r\n\r\n".encode())
        parts.append(value)
        parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def gateway_edit(
    *,
    mode: str,
    image: str,
    mask: str = "",
    prompt: str = "",
    model: str = "",
    channel_id: str = "",
    megapixels: float = 1.0,
    size: str = "1024x1024",
    timeout: float = 120.0,
) -> Dict[str, Any]:
    """经可选网关执行局部编辑（inpaint/remove/outpaint）。

    渠道未启用 ⇒ ok:false + guidance；成功 ⇒ image_data_url（data[0].b64_json）。
    调用方应在 worker 线程调用（本模块不碰 UI）。
    """
    mode = (mode or "").strip().lower()
    if mode not in _VALID_MODES:
        return {"ok": False, "message": f"不支持的 mode: {mode!r}（仅 inpaint/remove/outpaint）"}
    if not image:
        return {"ok": False, "message": "缺少原图 image（data URL）"}
    if mode in ("inpaint", "remove") and not mask:
        return {"ok": False, "message": f"{mode} 需要原图与蒙版双文件（image + mask）"}

    channels = _load_channels()
    cid = (channel_id or "").strip() or GATEWAY_CHANNEL_ID
    ch = next((c for c in channels if c.get("id") == cid), None)
    if ch is None or not str(ch.get("apiKey") or "").strip():
        return {"ok": False, "message": "无界网关未启用。" + GATEWAY_GUIDANCE,
                "guidance": GATEWAY_GUIDANCE}
    base = str(ch.get("baseUrl") or "").rstrip("/")
    if not base:
        return {"ok": False, "message": "无界网关 Base URL 为空", "guidance": GATEWAY_GUIDANCE}

    mime_i, b_i = _data_url_to_bytes(image)
    if not b_i:
        return {"ok": False, "message": "原图不是有效 data URL"}
    files: List[Tuple[str, bytes, str, str]] = [("image", b_i, "image.png", mime_i or "image/png")]
    if mode in ("inpaint", "remove"):
        mime_m, b_m = _data_url_to_bytes(mask)
        if not b_m:
            return {"ok": False, "message": "蒙版不是有效 data URL"}
        files.append(("mask", b_m, "mask.png", mime_m or "image/png"))

    if not model:
        for m in ch.get("models") or []:
            if isinstance(m, dict) and m.get("capability") == "image":
                model = str(m.get("name") or "")
                break
        model = model or "gpt-image-2"

    fields: List[Tuple[str, str]] = [
        ("model", model),
        ("prompt", (prompt or "").strip() or "inpaint the masked region"),
        ("n", "1"),                       # singleShot 强制 n=1
        ("size", size or "1024x1024"),
        ("response_format", "b64_json"),
        ("mode", mode),
    ]
    if mode == "outpaint":
        fields.append(("megapixels", str(megapixels)))

    body, ctype = _build_multipart(fields, files)
    req = urllib.request.Request(
        base + "/images/edits",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {ch['apiKey']}",
            "Content-Type": ctype,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        logger.warning("[gateway_edits] 请求失败: %s", exc)
        return {"ok": False, "message": f"无界网关请求异常: {exc}"}

    items = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(items, list) and items:
        first = items[0] if isinstance(items[0], dict) else {}
        b64 = first.get("b64_json") or first.get("base64")
        if b64:
            return {
                "ok": True,
                "image_data_url": f"data:image/png;base64,{b64}",
                "model": model,
                "mode": mode,
                "channel": ch.get("name"),
                "message": f"局部编辑成功（{mode} · {ch.get('name')} / {model}）",
            }
    return {"ok": False, "message": "无界网关未返回有效图像（data[0].b64_json 缺失）"}

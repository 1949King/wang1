# -*- coding: utf-8 -*-
"""可选网关全景生成客户端（Gateway Scene3D，T5 2026-11-20）。

对标上游无界工作台 ``/v1/scene3d/*`` 全景路（H3 生全景 → 接缝修复 → 环视取景）。
上游具体字段报告未给 ⇒ **薄客户端 OpenAI 兼容 multipart**（image + prompt），
响应取 ``data[0].b64_json`` [INFERRED]，异常形状诚实失败，不返回假全景。

设计纪律（同 gateway_edits.py 的纯模块风格）
==========================================
- 纯逻辑 + 标准库 HTTP，模块级不 import app 包（伪包可单测）；
- 渠道经 ``build_host_ai_config_patch()`` 懒加载（id ``shiguang-wujie-gateway``），
  状态统一归集 cloud_api_service，不在本模块散落全局状态；
- **默认关三重保证**：无配置 ⇒ 渠道不注入 ⇒ 本客户端诚实返 ok:false + guidance；
- **绝不自动下载、不随包权重**：网关由用户自备（含 H3 全景工作流），本模块只发 HTTP；
- 超时/网络异常诚实失败；
- **合规（H3 Community License，用户已确认条件放行）**：返回值带 attribution
  "MiniMax H3"，前端 UI 显著署名；地域（中国大陆）/营收（≤2000万美元）条件用户自担。
"""
from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any, Dict, List

try:
    from app.core.ai.gateway_edits import _build_multipart, _data_url_to_bytes
except ImportError:
    from core.ai.gateway_edits import _build_multipart, _data_url_to_bytes  # type: ignore

logger = logging.getLogger("AI短剧编辑器.core.ai.gateway_scene3d")

#: 模型广场渠道 id（与 gateway_edits 同一渠道，model_config.PROVIDERS["wujie-gateway"]）。
GATEWAY_CHANNEL_ID = "shiguang-wujie-gateway"

#: H3 社区许可要求的显著署名（前端 UI 必须展示）。
H3_ATTRIBUTION = "MiniMax H3"

#: 渠道未启用时给用户的指引（默认关；本地替代走深度重建 2.5D 网格）。
SCENE3D_GUIDANCE = (
    "无界网关渠道未启用（默认关）。本软件绝不自动下载模型、不随包权重；如需 H3 全景生成：\n"
    "【启用步骤】\n"
    "  1. 自行部署无界工作台网关（默认本机 http://127.0.0.1:8190/v1，需含 MiniMax H3 全景工作流），或填写已有网关 Base URL。\n"
    "  2. 打开「模型广场 → 无界网关」卡片，填 Base URL + Auth Key（网关无鉴权可填 local），点「测试连接」后保存。\n"
    "  3. 保存后渠道自动注入画布，重试本功能。\n"
    "【合规】全景生成由 MiniMax H3 提供（H3 Community License）：使用地域限中国大陆、年营收≤2000万美元（超出须书面授权），输出不得用于训练其他模型。\n"
    "【本地替代】未启用网关时，可用「图片节点 → 转3D」走本地深度重建 2.5D 网格（权重自取，见下载中心）。"
)


def _load_channels() -> List[Dict[str, Any]]:
    """懒加载画布渠道（避免模块级 import canvas_aigc 造成循环/重依赖）。"""
    try:
        from app.core.canvas_aigc import build_host_ai_config_patch
    except ImportError:
        from core.canvas_aigc import build_host_ai_config_patch  # type: ignore
    try:
        return list(build_host_ai_config_patch().get("channels") or [])
    except Exception:
        logger.warning("[gateway_scene3d] 组装渠道失败", exc_info=True)
        return []


def generate_panorama(
    *,
    prompt: str,
    image: str = "",
    model: str = "",
    channel_id: str = "",
    size: str = "2048x1024",
    timeout: float = 300.0,
) -> Dict[str, Any]:
    """经可选网关生成等距柱状全景（H3）。prompt / image 至少一项。

    渠道未启用 ⇒ ok:false + guidance；成功 ⇒ image_data_url（data[0].b64_json）
    + attribution "MiniMax H3"。调用方应在 worker 线程调用（本模块不碰 UI）。
    产物喂现有 PanoramaViewer3D 真 3D 环视（2:1 等距柱状）。
    """
    prompt = (prompt or "").strip()
    if not prompt and not image:
        return {"ok": False, "message": "缺少全景描述 prompt（或源图 image）"}

    channels = _load_channels()
    cid = (channel_id or "").strip() or GATEWAY_CHANNEL_ID
    ch = next((c for c in channels if c.get("id") == cid), None)
    if ch is None or not str(ch.get("apiKey") or "").strip():
        return {"ok": False, "message": "无界网关未启用。" + SCENE3D_GUIDANCE,
                "guidance": SCENE3D_GUIDANCE}
    base = str(ch.get("baseUrl") or "").rstrip("/")
    if not base:
        return {"ok": False, "message": "无界网关 Base URL 为空", "guidance": SCENE3D_GUIDANCE}

    files = []
    if image:
        mime_i, b_i = _data_url_to_bytes(image)
        if not b_i:
            return {"ok": False, "message": "源图不是有效 data URL"}
        files.append(("image", b_i, "image.png", mime_i or "image/png"))

    model = (model or "").strip() or "MiniMax-H3"
    fields = [
        ("model", model),
        ("prompt", prompt or "equirectangular 360 panorama, seamless"),
        ("n", "1"),                       # 单张全景
        ("size", size or "2048x1024"),    # 2:1 等距柱状
        ("response_format", "b64_json"),
    ]
    body, ctype = _build_multipart(fields, files)
    req = urllib.request.Request(
        base + "/scene3d/panorama",
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
        logger.warning("[gateway_scene3d] 请求失败: %s", exc)
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
                "attribution": H3_ATTRIBUTION,
                "channel": ch.get("name"),
                "message": f"全景生成成功（{H3_ATTRIBUTION} · {ch.get('name')} / {model}）",
            }
    return {"ok": False, "message": "无界网关未返回有效全景图（data[0].b64_json 缺失）"}

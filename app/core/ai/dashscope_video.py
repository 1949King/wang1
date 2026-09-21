"""阿里云百炼（DashScope）万相文生视频客户端。

为什么是它：项目已持有 DASHSCOPE_API_KEY（`API Keys.env`），百炼自带
万相（Wan）系列文生视频模型，国内直连、新账号有免费额度（视频 50 秒/90 天），
不需要再引入第三方集成站。

API 协议（legacy video-synthesis，wan2.5/2.2/2.1 系列）：
  1. POST /api/v1/services/aigc/video-generation/video-synthesis
     头：Authorization: Bearer <key> / X-DashScope-Async: enable
     体：{"model": ..., "input": {"prompt": ...}, "parameters": {"size": "1280*720"}}
  2. GET /api/v1/tasks/{task_id} 轮询（PENDING/RUNNING → SUCCEEDED/FAILED）
  3. SUCCEEDED → output.video_url（24h 有效）→ 下载到本地

设计纪律：
- 纯模块（不 import app 包），可独立加载/单测。
- 诚实降级：认证失败/额度耗尽/模型不存在 → 抛 RuntimeError（带平台原始 message），
  由 video_generation_client 记为 provider 失败进额度池，不静默。
- 模型回退链：wan2.2-t2v-flash → wan2.1-t2v-turbo（模型下架/不存在时自动降档）。
- video_url 24 小时有效——**当场下载**，不缓存 URL。
"""

from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

_BASE_URL = "https://dashscope.aliyuncs.com"
_ENDPOINT = f"{_BASE_URL}/api/v1/services/aigc/video-generation/video-synthesis"
_TASK_URL = f"{_BASE_URL}/api/v1/tasks"

# 模型回退链（前优先；触发「模型不存在/无权限/未开通」时降档重试）
# 命名坑（实测+官方模型广场核对）：wan2.2 系不带 x，wan2.1 系带 x（wanx2.1-*）
_MODEL_CHAIN: List[str] = [
    "wan2.2-t2v-flash",
    "wanx2.1-t2v-turbo",
    "wanx2.1-t2v-plus",
]

# 轮询参数：视频生成典型 1~5 分钟
_POLL_INTERVAL = 5.0
_POLL_TIMEOUT = 360.0

# 输出目录（与 video_generation_client 的占位产物同区）
_OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))), "app", "temp", "dashscope_video")


def get_api_key() -> str:
    """取 DashScope key：环境变量优先，回落项目根 `API Keys.env` 解析。"""
    key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if key:
        return key
    try:
        env_path = Path(__file__).resolve().parents[3] / "API Keys.env"
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8-sig").splitlines():
                line = line.strip()
                if line.startswith("DASHSCOPE_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        logger.debug("解析 API Keys.env 失败", exc_info=True)
    return ""


def _headers(key: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
    }


def _http_json(method: str, url: str, headers: Dict[str, str],
               body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    import json
    import urllib.request

    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:  # noqa: F821 - 3.x 均有
        detail = ""
        try:
            detail = e.read().decode("utf-8", errors="replace")[:400]
        except Exception:
            pass
        raise RuntimeError(f"DashScope HTTP {e.code}: {detail}") from e


def _is_model_error(msg: str) -> bool:
    """判定是否「模型不存在/无权限」类错误（可降档重试）。"""
    patterns = ("model not found", "不存在", "无权限", "not exist",
                "invalid model", "unsupported model", "无可用渠道")
    low = (msg or "").lower()
    return any(p in low for p in patterns)


def _create_task(key: str, prompt: str, size: str, model: str) -> str:
    body = {
        "model": model,
        "input": {"prompt": prompt},
        "parameters": {"size": size},
    }
    resp = _http_json("POST", _ENDPOINT, _headers(key), body)
    task_id = (resp.get("output") or {}).get("task_id", "")
    if not task_id:
        raise RuntimeError(f"DashScope 未返回 task_id: {resp}")
    return task_id


def _poll_task(key: str, task_id: str,
               on_check: Optional[Callable[[], None]] = None) -> Dict[str, Any]:
    deadline = time.time() + _POLL_TIMEOUT
    while time.time() < deadline:
        if on_check is not None:
            on_check()  # 段间取消检查（协作式，由调用方注入）
        resp = _http_json("GET", f"{_TASK_URL}/{task_id}",
                          {"Authorization": f"Bearer {key}"})
        output = resp.get("output") or {}
        status = (output.get("task_status") or "").upper()
        if status == "SUCCEEDED":
            return output
        if status in ("FAILED", "CANCELED", "UNKNOWN"):
            raise RuntimeError(
                f"DashScope 任务 {status}: {output.get('message') or output.get('code') or ''}")
        time.sleep(_POLL_INTERVAL)
    raise RuntimeError(f"DashScope 任务超时（>{_POLL_TIMEOUT:.0f}s）: {task_id}")


def _download(url: str, dest: Path) -> str:
    import urllib.request

    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=120) as resp, open(dest, "wb") as f:
        while True:
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
    return str(dest)


def generate_videos(prompt: str, duration: float = 5.0, count: int = 1,
                    width: int = 1280, height: int = 720,
                    model: Optional[str] = None,
                    on_check: Optional[Callable[[], None]] = None) -> List[str]:
    """生成文生视频片段（每段一个异步任务，逐段下载到本地）。

    Args:
        prompt: 提示词（中英文均可）
        duration: 单段时长（万相 t2v 系列当前固定 5 秒/段；非 5 值只记录日志）
        count: 段数
        width/height: 分辨率（归一到 Wan 支持的档位）
        model: 指定模型；None 走回退链
        on_check: 轮询间隙的取消检查钩子（协作式取消，抛出即中止）

    Returns:
        本地 mp4 路径列表（部分失败时返回已成功部分；全失败抛 RuntimeError）
    """
    key = get_api_key()
    if not key:
        raise RuntimeError("DASHSCOPE_API_KEY 未配置（环境变量或 API Keys.env）")
    if abs(float(duration) - 5.0) > 1e-6:
        logger.warning("万相 t2v 当前按 5 秒/段生成，请求的 %.1fs 按最接近档位处理", duration)
    size = f"{int(width)}*{int(height)}"
    models = [model] if model else list(_MODEL_CHAIN)
    paths: List[str] = []
    ts = time.strftime("%Y%m%d_%H%M%S")
    for i in range(max(1, int(count))):
        last_err: Optional[Exception] = None
        for m in models:
            try:
                task_id = _create_task(key, prompt, size, m)
                logger.info("[dashscope] 模型 %s 任务 %s 已提交（%d/%d）", m, task_id, i + 1, count)
                output = _poll_task(key, task_id, on_check=on_check)
                url = output.get("video_url") or ""
                if not url:
                    raise RuntimeError(f"任务成功但无 video_url: {output}")
                dest = Path(_OUTPUT_DIR) / f"wan_{ts}_{i + 1:02d}.mp4"
                paths.append(_download(url, dest))
                logger.info("[dashscope] 第 %d/%d 段完成 → %s", i + 1, count, dest)
                break  # 该段成功，下一段
            except RuntimeError as e:
                last_err = e
                if _is_model_error(str(e)) and m != models[-1]:
                    logger.warning("[dashscope] 模型 %s 不可用，降档重试: %s", m, e)
                    continue
                raise
        if last_err is not None and len(paths) < i + 1:
            raise last_err
    return paths


def probe() -> Dict[str, Any]:
    """渠道探测（只读）：key 是否存在 / 端点是否可达（不生成、不花钱）。

    用一次**非法空模型**请求触发 400——能拿到结构化错误说明认证与端点通，
    拿到 401 说明 key 失效。这是最便宜的真实连通性测试。
    """
    key = get_api_key()
    if not key:
        return {"ok": False, "reason": "no_key"}
    try:
        _http_json("POST", _ENDPOINT, _headers(key),
                   {"model": "__probe__", "input": {}})
        return {"ok": True, "reason": "unexpected_success"}
    except RuntimeError as e:
        msg = str(e)
        if "HTTP 401" in msg or "InvalidApiKey" in msg or "invalid api key" in msg.lower():
            return {"ok": False, "reason": "invalid_key", "detail": msg}
        # 400 + 模型参数错误 = 认证与端点都通
        if "HTTP 400" in msg or re.search(r"model", msg, re.I):
            return {"ok": True, "reason": "auth_ok_endpoint_reachable", "detail": msg[:200]}
        return {"ok": False, "reason": "error", "detail": msg[:200]}

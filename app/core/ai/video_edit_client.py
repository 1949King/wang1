# -*- coding: utf-8 -*-
"""指令式视频编辑客户端（Video Edit Client，2026-10-15）。

对标调研结论（2026-10-14 交付，用户裁决：Seedance + Kling Omni 两家都接）
================================================================
· 火山 Seedance：官方「编辑视频」任务，`video_url` **支持 Base64**
  ——本地素材直传，是桌面软件的主编辑渠道。
· 可灵 3.0 Omni：`contents[].type=base_video`，官方示例即"改颜色其余不变"；
  ⚠️ 视频**必须公网 URL**（素材出域），调用方不显式给 URL 时本模块**诚实拒绝**。
· MiniMax H3（reference_video）：语义待实测、双向计费贵——**未接线就不声明能力**
  （provider_caps 表暂不加 minimax 行，接了再改，诚实边界）。

设计纪律（同 dashscope_video.py 的纯模块风格）
==========================================
- 纯逻辑 + 标准库 HTTP，模块级不 import app 包（伪包可单测）；
- **失败保原镜**：任何渠道失败都返回 `original_kept=True` + 原路径，绝不产半成品冒充；
- **不出域硬约束**：`SHIGUANG_NO_EGRESS=1` 时整个编辑请求诚实拒绝（编辑无本地占位路径，
  不拿色块冒充"已编辑"）；
- 端点/请求体按调研样例编写，**首次真机联调需复核**（代码注释里逐处标注）；
- 调用方应在 worker 线程调用（轮询分钟级），本模块不碰 UI。

⚠️ 真机复核清单（拿到 Key 后逐项验证，验证前该渠道按失败顺延处理）：
  1. Seedance 编辑任务的 model 名（Ark 模型广场）与 content 结构；
  2. Kling omni-video 端点路径与 contents 类型枚举；
  3. 两家的任务状态字段名与结果 URL 字段名。
"""
from __future__ import annotations

import base64
import json
import logging
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("AI短剧编辑器.core.ai.video_edit_client")

# ── 渠道常量（调研 2026-10-14；真机复核清单第 1/2 条）──────────────
_ARK_BASE = "https://ark.cn-beijing.volces.com/api/v3"
_SEEDANCE_TASKS = f"{_ARK_BASE}/contents/generations/tasks"
_KLING_BASE_DEFAULT = "https://api.klingai.com"
_KLING_EDIT_PATH = "/kling/v1/videos/omni-video"
_KLING_POLL_PATH = "/kling/v1/videos/{task_id}"

# 轮询：编辑任务典型 1~10 分钟
_POLL_INTERVAL = 5.0
_POLL_TIMEOUT = 600.0

# Base64 直传上限（火山网关对请求体有大小限制，保守 50MB；超限诚实拒绝）
_MAX_BASE64_MB = 50

# 编辑渠道的固定优先级（**不走 resolve_order 的 tier 排序**）：
# seedance 在前——本地素材 Base64 直传可用；kling 在后——要公网 URL，多数场景给不出。
_EDIT_CHANNELS: Tuple[str, ...] = ("seedance", "kling")

# 输出目录（与 dashscope_video 同区）
_OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))), "app", "temp", "video_edit")


# ─────────────────────── Key 解析（env 优先，回落 API Keys.env）───────────────────────

def _from_keys_env(var: str) -> str:
    """从项目根 `API Keys.env` 读一个变量（与 dashscope_video 同套路）。"""
    try:
        env_path = Path(__file__).resolve().parents[3] / "API Keys.env"
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8-sig").splitlines():
                line = line.strip()
                if line.startswith(f"{var}="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        logger.debug("解析 API Keys.env 失败", exc_info=True)
    return ""


def get_ark_key() -> str:
    """火山方舟 Key：env（ARK_API_KEY / VOLC_ARK_API_KEY）→ API Keys.env → 豆包 provider 配置。"""
    for var in ("ARK_API_KEY", "VOLC_ARK_API_KEY", "DOUBAO_API_KEY"):
        key = os.getenv(var, "").strip()
        if key:
            return key
    key = _from_keys_env("ARK_API_KEY") or _from_keys_env("VOLC_ARK_API_KEY")
    if key:
        return key
    try:  # 回落：应用内配置好的豆包（Ark）provider Key
        from app.modules.lego.cloud_providers import get_provider  # type: ignore
        p = get_provider("doubao")
        return str(getattr(p, "api_key", "") or "")
    except Exception:
        logger.debug("豆包 provider 配置不可用", exc_info=True)
        return ""


def get_kling_key() -> str:
    """可灵 Key：env（KLING_API_KEY）→ API Keys.env → 画布 AIGC 渠道配置。"""
    key = os.getenv("KLING_API_KEY", "").strip() or _from_keys_env("KLING_API_KEY")
    if key:
        return key
    try:  # 回落：画布渠道表里 baseUrl 含 kling 的渠道 apiKey
        from app.core.canvas_aigc import build_host_ai_config_patch  # type: ignore
        patch = build_host_ai_config_patch() or {}
        for ch in patch.get("channels") or []:
            base = str(ch.get("baseUrl") or "").lower()
            if ("kling" in base or "kling" in str(ch.get("id") or "").lower()):
                k = str(ch.get("apiKey") or "")
                if k:
                    return k
    except Exception:
        logger.debug("画布 kling 渠道配置不可用", exc_info=True)
    return ""


def no_egress() -> bool:
    """素材不出域硬开关（与 provider_caps 同一 env，独立实现避免包级依赖）。"""
    return os.environ.get("SHIGUANG_NO_EGRESS", "").strip().lower() in {"1", "true", "yes", "on"}


# ─────────────────────── 纯函数：计划（可离线单测）───────────────────────

def plan_edit(clip_path: str, instruction: str, *,
              channel: str = "auto", video_url: str = "") -> Dict[str, Any]:
    """把一次编辑请求变成**渠道执行计划**（纯函数，不联网、不读 Key）。

    渠道筛选走 provider_caps 的 `edit_video` 能力位（表加一行，路由零改动）；
    排序走本模块固定优先级 `_EDIT_CHANNELS`（seedance 先、kling 后，理由见常量注释）。

    Returns::
        {"ok": bool, "channels": [pid...], "dropped": [(pid, 理由)...],
         "message": str}   # ok=False 时 channels 为空、message 给人话原因
    """
    try:
        from .provider_caps import supports as _supports
    except Exception:  # 伪包/独立加载兜底：能力表不可用时按内置常量表判
        _supports = None
    out: Dict[str, Any] = {"ok": False, "channels": [], "dropped": [], "message": ""}
    if not str(instruction or "").strip():
        out["message"] = "缺少编辑指令（instruction）"
        return out
    if not str(clip_path or "").strip() and not str(video_url or "").strip():
        out["message"] = "需要本地片段 clip_path 或公网 video_url 至少其一"
        return out
    if clip_path and not os.path.isfile(str(clip_path)):
        out["message"] = f"片段文件不存在: {clip_path}"
        return out
    if no_egress():
        out["message"] = ("素材不出域（SHIGUANG_NO_EGRESS=1）：指令式编辑必须走云端，"
                          "本请求已拒绝——编辑没有本地占位路径，不拿色块冒充")
        return out
    want = str(channel or "auto").strip().lower()
    chain = list(_EDIT_CHANNELS) if want in ("", "auto") else [want]
    for pid in chain:
        if _supports is not None:
            ok, reason = _supports(pid, {"edit_video": True})
        else:  # 表不可用：只认内置两渠道（它们就是表里声明 True 的两行）
            ok, reason = (pid in _EDIT_CHANNELS), "不在编辑渠道表"
        if not ok:
            out["dropped"].append((pid, reason))
            continue
        # kling 的出域前提：必须显式给公网 URL（拿不到就跳过该渠道，不偷传本地文件）
        if pid == "kling" and not str(video_url or "").strip():
            out["dropped"].append((pid, "可灵编辑需公网 URL（素材出域），未显式提供 video_url"))
            continue
        out["channels"].append(pid)
    if not out["channels"]:
        parts = [f"{p}: {r}" for p, r in out["dropped"]]
        out["message"] = "没有可用编辑渠道" + (f"（{'；'.join(parts)}）" if parts else "")
        return out
    out["ok"] = True
    return out


# ─────────────────────── HTTP 小工具（标准库，同 dashscope_video 风格）───────────────────────

def _http_json(method: str, url: str, headers: Dict[str, str],
               body: Optional[Dict[str, Any]] = None,
               timeout: float = 90.0) -> Dict[str, Any]:
    """发一个 JSON 请求并解析响应（HTTPError 带响应体片段抛出，不静默）。"""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace") or "{}")
    except urllib.error.HTTPError as e:
        snippet = ""
        try:
            snippet = e.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            logger.debug("读 HTTP 错误体失败", exc_info=True)
        raise RuntimeError(f"HTTP {e.code}: {snippet or e.reason}") from e


def _download(url: str, out_dir: str, prefix: str) -> str:
    """把结果视频**当场下载到本地**（渠道 URL 有效期短，不缓存外链）。"""
    os.makedirs(out_dir, exist_ok=True)
    dst = os.path.join(out_dir, f"{prefix}_{int(time.time())}.mp4")
    req = urllib.request.Request(url, headers={"User-Agent": "shiguang-editor/1.0"})
    with urllib.request.urlopen(req, timeout=180) as resp, open(dst, "wb") as fh:
        fh.write(resp.read())
    return dst


def _result_video_url(payload: Dict[str, Any]) -> str:
    """从任务响应里挖结果视频 URL（Seedance content 数组 / 通用字段都试）。"""
    if not isinstance(payload, dict):
        return ""
    content = payload.get("content")
    if isinstance(content, dict):
        u = str(content.get("video_url") or content.get("url") or "")
        if u:
            return u
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                u = str(item.get("video_url") or item.get("url") or "")
                if u:
                    return u
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    return str(data.get("video_url") or data.get("url") or "")


# ─────────────────────── 渠道实现 ───────────────────────

def _edit_seedance(clip_path: str, instruction: str, *, model: str = "",
                   key: str = "", out_dir: str = "") -> Dict[str, Any]:
    """Seedance 编辑任务：本地片段 Base64 直传 → 轮询 → 下载（真机复核清单第 1/3 条）。"""
    key = key or get_ark_key()
    if not key:
        return {"ok": False, "message": "未配置火山方舟 Key（ARK_API_KEY），Seedance 编辑不可用"}
    model = str(model or os.getenv("SHIGUANG_SEEDANCE_EDIT_MODEL") or "").strip()
    if not model:
        # 诚实边界：编辑模型 id 以 Ark 模型广场为准，不猜一个下架/无权限的 id 去烧钱
        return {"ok": False, "message": "未配置 Seedance 编辑模型名"
                                        "（model 参数或 SHIGUANG_SEEDANCE_EDIT_MODEL）"}
    size_mb = os.path.getsize(clip_path) / (1024 * 1024) if clip_path else 0.0
    if size_mb > _MAX_BASE64_MB:
        return {"ok": False, "message": f"片段 {size_mb:.0f}MB 超 Base64 直传上限"
                                        f"（{_MAX_BASE64_MB}MB），请先压缩或裁短"}
    b64 = base64.b64encode(Path(clip_path).read_bytes()).decode("ascii")
    body = {
        "model": model,
        "content": [
            {"type": "text", "text": instruction},
            {"type": "video_url", "video_url": {"url": f"data:video/mp4;base64,{b64}"}},
        ],
    }
    submit = _http_json("POST", _SEEDANCE_TASKS,
                        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                        body, timeout=120)
    task_id = str(submit.get("id") or submit.get("task_id") or "")
    if not task_id:
        return {"ok": False, "message": f"Seedance 提交无任务 ID: {str(submit)[:200]}"}
    deadline = time.time() + _POLL_TIMEOUT
    while time.time() < deadline:
        st = _http_json("GET", f"{_SEEDANCE_TASKS}/{task_id}",
                        {"Authorization": f"Bearer {key}"}, timeout=30)
        status = str(st.get("status") or "").lower()
        if status in ("succeeded", "success", "completed"):
            v = _result_video_url(st)
            if not v:
                return {"ok": False, "message": f"Seedance 成功但无结果 URL: {str(st)[:200]}"}
            path = _download(v, out_dir or _OUTPUT_DIR, "edit_seedance")
            return {"ok": True, "clip_path": path, "channel": "seedance",
                    "cost_note": "按 token 计费（估算以账单为准）"}
        if status in ("failed", "error", "cancelled"):
            err = st.get("error") if isinstance(st.get("error"), dict) else {}
            return {"ok": False, "message": f"Seedance 任务失败: {str(err or st)[:200]}"}
        time.sleep(_POLL_INTERVAL)
    return {"ok": False, "message": f"Seedance 轮询超时（{_POLL_TIMEOUT:g}s）"}


def _edit_kling(video_url: str, instruction: str, *, model: str = "",
                key: str = "", base: str = "", out_dir: str = "") -> Dict[str, Any]:
    """可灵 Omni 编辑（base_video 模式）：**只接受公网 URL**（真机复核清单第 2/3 条）。"""
    key = key or get_kling_key()
    if not key:
        return {"ok": False, "message": "未配置可灵 Key（KLING_API_KEY），Kling 编辑不可用"}
    if not str(video_url or "").strip():
        # 双保险：plan_edit 已拦一次；直调也拦——绝不把本地素材偷偷转存出域
        return {"ok": False, "message": "可灵编辑需公网 video_url（素材出域，需显式提供）"}
    base = str(base or os.getenv("SHIGUANG_KLING_BASE") or _KLING_BASE_DEFAULT).rstrip("/")
    body = {
        "model_name": model or "kling-3.0-omni",
        "contents": [
            {"type": "base_video", "video_url": video_url},
            {"type": "prompt", "text": instruction},
        ],
    }
    submit = _http_json("POST", base + _KLING_EDIT_PATH,
                        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                        body, timeout=90)
    task_id = str(submit.get("task_id") or (submit.get("data") or {}).get("task_id") or "")
    if not task_id:
        return {"ok": False, "message": f"Kling 提交无任务 ID: {str(submit)[:200]}"}
    deadline = time.time() + _POLL_TIMEOUT
    while time.time() < deadline:
        st = _http_json("GET", base + _KLING_POLL_PATH.format(task_id=task_id),
                        {"Authorization": f"Bearer {key}"}, timeout=30)
        data = st.get("data") if isinstance(st.get("data"), dict) else st
        status = str((data or {}).get("task_status") or "").lower()
        if status in ("succeed", "succeeded", "completed"):
            videos = ((data or {}).get("task_result") or {}).get("videos") or []
            v = str((videos[0] or {}).get("url") or "") if videos else ""
            if not v:
                return {"ok": False, "message": f"Kling 成功但无 video_url: {str(st)[:200]}"}
            path = _download(v, out_dir or _OUTPUT_DIR, "edit_kling")
            return {"ok": True, "clip_path": path, "channel": "kling",
                    "cost_note": "720p 约 0.63 元/5s（估算以账单为准）"}
        if status in ("fail", "failed", "error", "canceled", "cancelled"):
            return {"ok": False, "message": f"Kling 任务失败: {str(st)[:200]}"}
        time.sleep(_POLL_INTERVAL)
    return {"ok": False, "message": f"Kling 轮询超时（{_POLL_TIMEOUT:g}s）"}


# ─────────────────────── 主入口 ───────────────────────

def edit_video(clip_path: str, instruction: str, *, channel: str = "auto",
               video_url: str = "", model: str = "", key: str = "",
               kling_base: str = "", out_dir: str = "") -> Dict[str, Any]:
    """指令式编辑主入口：**失败保原镜**，成功出本地新片段。

    Args:
        clip_path:   本地片段路径（Seedance 走 Base64 直传；Kling 仅作记录）
        instruction: 编辑指令（如"把外套改成红色，其余保持不变"）
        channel:     auto / seedance / kling
        video_url:   公网 URL（走 Kling 时**必须**显式提供——出域要知情）
        model/key/kling_base/out_dir: 渠道覆盖参数（默认走 env/配置解析）

    Returns::
        {"ok", "clip_path"(新片段或原片), "original_kept", "channel_used",
         "cost_note", "errors": [...], "message"}
        ok=False 时 clip_path 一定是原片、original_kept=True —— 半成品绝不冒充成品。
    """
    plan = plan_edit(clip_path, instruction, channel=channel, video_url=video_url)
    if not plan["ok"]:
        return {"ok": False, "clip_path": str(clip_path or ""), "original_kept": True,
                "channel_used": "", "cost_note": "", "errors": [],
                "message": plan["message"]}
    errors: List[str] = []
    for pid in plan["channels"]:
        try:
            if pid == "seedance":
                r = _edit_seedance(clip_path, instruction, model=model,
                                   key=key, out_dir=out_dir)
            else:
                r = _edit_kling(video_url, instruction, model=model,
                                key=key, base=kling_base, out_dir=out_dir)
        except RuntimeError as e:  # _http_json 抛出：带平台原始 message，不静默
            r = {"ok": False, "message": str(e)}
        except Exception as e:
            logger.debug("[video_edit] %s 渠道异常", pid, exc_info=True)
            r = {"ok": False, "message": f"{pid} 异常: {e}"}
        if r.get("ok"):
            return {"ok": True, "clip_path": r["clip_path"], "original_kept": False,
                    "channel_used": r["channel"], "cost_note": r.get("cost_note", ""),
                    "errors": errors, "message": ""}
        errors.append(f"{pid}: {r.get('message', '')}")
        logger.warning("[video_edit] 渠道 %s 失败，顺延下一渠道: %s", pid, r.get("message"))
    return {"ok": False, "clip_path": str(clip_path or ""), "original_kept": True,
            "channel_used": "", "cost_note": "", "errors": errors,
            "message": "所有编辑渠道失败，原片段已保留（未产生任何改动）"}

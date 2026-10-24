"""Provider 能力声明 + 自动路由（P0-3）
==========================================
问题（对照鲸影学到的）：`video_generation_client._resolve_provider_order()` 只是
**写死的名字顺序**（`["seedance", "cogvideo", "local"]`）—— 没有「这个 provider
支持不支持图生视频 / 首尾帧 / 12 秒 / 1080p」的声明。要生成「首尾帧」时可能选中
一个不支持的 provider，白试一轮、白烧一次钱。

本模块把选路从「名字回退」升级为「**按能力筛选**」：

    候选 = [声明表里 capabilities 满足本次请求的 provider（按 quality_tier 降序）] + ["local"]

设计纪律：
  - **纯逻辑、不 import app 包**（同 guard_base.py，便于单测）；
  - **新增 provider 只加声明**（表里加一行或 `register_caps()`），路由代码零改动；
  - `local` 是**终端兜底**，永远排在最后、不受能力筛选拦截（保住「无网络也能演示」
    的既有承诺——占位生成本来就不区分输入形态）；
  - 筛选掉的 provider 会给出**人话理由**（供审计日志 / UI 提示），不是静默消失；
  - **`SHIGUANG_NO_EGRESS=1` ⇒ 强制 local-only（素材不出域）**，见 `no_egress()`。

⚠️ 关于「素材不能出域」（2026-10-09 补）：
    本模块默认排序是 `[真实 provider 按 quality_tier 降序] + ["local"]` —— 即
    **优先走云端**，`local` 只是兜底。这对「客户素材不得离开本机/内网」的硬约束
    是反向的：默认行为就会把素材发给 dashscope/seedance/cogvideo。此前没有任何
    开关能表达「这一单不许出域」，只能靠调用方手工传 `provider="local"`（而那条
    分支还会返回 `["local", "local"]` 的重复项）。现已补 `SHIGUANG_NO_EGRESS`。
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("AI短剧编辑器.core.ai.provider_caps")

# 终端兜底 provider 的 id（唯一一个保证「不出域」的实现）
LOCAL_PROVIDER_ID = "local"

# 环境开关名（显式常量，禁裸字符串 —— 见项目不变量 #5 的精神）
ENV_NO_EGRESS = "SHIGUANG_NO_EGRESS"

_TRUTHY = {"1", "true", "yes", "on"} 

# ═══════════════════════════════════════════════════════════
# 能力声明表（新增 provider = 这里加一行，路由零改动）
# ═══════════════════════════════════════════════════════════
#
# 字段说明：
#   text_to_video / image_to_video / first_last_frame / lip_sync / edit_video : 布尔能力位
#   （edit_video=指令式视频编辑，2026-10-15 新增；未接线渠道一律 False，不声明没接的东西）
#   max_duration  : 单段最大时长（秒），超过则不接单
#   resolutions   : 支持的分辨率档位；["*"] 表示任意
#   quality_tier  : 0=免费/占位 1=低价 2=高价（越大越贵越稳；auto 排序用）
#   price_per_clip: **估算单价（元/段）**，供 quote() 报价；非精确计费，
#                   实际以渠道账单为准；新渠道可用 register_caps 覆盖

PROVIDER_CAPS: Dict[str, Dict[str, Any]] = {
    "dashscope": {
        "name": "阿里云百炼 万相（Wan）",
        "edit_video": False,
        "text_to_video": True,
        "image_to_video": False,   # wan2.2-i2v-flash 系列存在，后续接线后改 True
        "first_last_frame": False,  # wan2.2-kf2v-flash 系列存在，后续接线后改 True
        "lip_sync": False,
        "max_duration": 5.0,        # 万相 t2v 系当前固定 5 秒/段
        "resolutions": ["480p", "720p", "1080p"],
        "quality_tier": 1,
        "price_per_clip": 1.5,      # 估算（5s 段）；实际以百炼账单为准
    },
    "seedance": {
        "name": "火山引擎 Seedance",
        # 指令式编辑：官方「编辑视频」任务；video_url 支持 Base64（本地素材直传）
        "edit_video": True,
        "text_to_video": True,
        "image_to_video": True,
        "first_last_frame": True,   # Seedance 支持首帧/尾帧图输入
        "lip_sync": False,
        "max_duration": 10.0,
        "resolutions": ["480p", "720p", "1080p"],
        "quality_tier": 1,
        "price_per_clip": 1.0,
    },
    "cogvideo": {
        "name": "智谱 CogVideo",
        "edit_video": False,
        "text_to_video": True,
        "image_to_video": True,
        "first_last_frame": False,  # 只支持首帧驱动，不支持首尾帧对插
        "lip_sync": False,
        "max_duration": 10.0,
        "resolutions": ["720p", "1080p"],
        "quality_tier": 1,
        "price_per_clip": 0.8,
    },
    "kling": {
        # 可灵（快手开放平台，submit + poll 链路，见 canvas_aigc.py L1857）
        # 2026-10-14 起设为 auto 默认首选：短剧预演画质/运镜稳定性第一梯队。
        # 注意：当前链路只提交 prompt + 可选首帧图（std 模式），
        # duration 未随请求下发（服务端按 model_name 定长），故 max_duration
        # 记 10.0 保守值，避免被 spec 的 duration 误筛。
        "name": "可灵 Kling（快手开放平台）",
        # 指令式编辑：3.0 Omni base_video 模式；⚠️ 素材必须公网 URL（出域），
        # 调用方未显式给 video_url 时客户端会诚实拒绝该渠道
        "edit_video": True,
        "text_to_video": True,
        "image_to_video": True,
        "first_last_frame": False,   # 当前接线只下发首帧图，尾帧未接
        "lip_sync": False,
        "max_duration": 10.0,
        "resolutions": ["480p", "720p", "1080p"],  # 当前接线不按 size 裁剪，服务端按 mode 定档
        "quality_tier": 2,
        "price_per_clip": 3.5,       # 估算（std 模式 5s 段），实际以可灵账单为准
    },
    "local": {
        "name": "本地占位生成（FFmpeg 色块）",
        "edit_video": False,   # 编辑无本地占位路径：不出域就诚实拒绝，不拿色块冒充
        "text_to_video": True,
        "image_to_video": True,     # 占位生成不区分输入形态
        "first_last_frame": True,
        "lip_sync": False,
        "max_duration": 60.0,
        "resolutions": ["*"],
        "quality_tier": 0,
        "price_per_clip": 0.0,
    },
}

# auto 模式下真实 provider 的基础顺序（local 由 resolve_order 统一追加，不写在这）
# 2026-10-14：kling 置首 —— 用户明确要求「切换默认后端为 Kling」。
# kling 画质/运镜属第一梯队（quality_tier=2），承接短剧预演主生成位；
# dashscope 次之（唯一长期有可用客户端的低价渠道），seedance/cogvideo 兜底。
# ⚠️ 无 kling Key 时按既有纪律诚实失败并顺延下一渠道，不会假成功。
DEFAULT_REAL_ORDER: List[str] = ["kling", "dashscope", "seedance", "cogvideo"]

# 收益函数 λ_c：每元单价愿意牺牲多少期望质量（规格书 §11 V = q̂ − λ_c·ĉ）
# 语义：两个渠道期望质量差 > λ_c×价差 时，贵的才排前面
_LAMBDA_PRICE = 0.2

# 能力位 → 人话（筛选理由用）
_CAP_LABELS = {
    "text_to_video": "文生视频",
    "image_to_video": "图生视频",
    "first_last_frame": "首尾帧",
    "lip_sync": "口型同步",
    "edit_video": "指令式编辑",
}


# ═══════════════════════════════════════════════════════════
# 声明表操作
# ═══════════════════════════════════════════════════════════


def register_caps(provider_id: str, caps: Dict[str, Any], *,
                  base_order: bool = True) -> None:
    """注册/覆盖一个 provider 的能力声明（供未来插件式 provider 用）。

    ``base_order=True`` 时同时把该 provider 加进 auto 默认顺序（已存在则忽略）。
    """
    if not provider_id or not isinstance(caps, dict):
        return
    PROVIDER_CAPS[provider_id] = caps
    if base_order and provider_id != "local" and provider_id not in DEFAULT_REAL_ORDER:
        DEFAULT_REAL_ORDER.append(provider_id)


def get_caps(provider_id: str) -> Optional[Dict[str, Any]]:
    """取一个 provider 的能力声明（未声明返回 None）。"""
    return PROVIDER_CAPS.get(provider_id)


def list_capabilities() -> List[Dict[str, Any]]:
    """全量声明（供 UI 展示 / 诊断）。"""
    return [
        {"id": pid, **caps}
        for pid, caps in PROVIDER_CAPS.items()
    ]


# ═══════════════════════════════════════════════════════════
# 需求 spec 规范化
# ═══════════════════════════════════════════════════════════


def resolution_label(width: int, height: int) -> str:
    """把像素分辨率归一成档位标签（横竖屏同档）：1920x1080 / 1080x1920 → "1080p"。"""
    try:
        short = min(int(width), int(height))
    except (TypeError, ValueError):
        return ""
    return {480: "480p", 720: "720p", 1080: "1080p", 1440: "1440p", 2160: "2160p"}.get(short, "")


def normalize_spec(spec: Optional[Dict[str, Any]] = None, *,
                   duration: float = 0.0,
                   width: int = 0, height: int = 0) -> Dict[str, Any]:
    """把调用方给的零散参数规范化成统一 spec（未提的字段不参与筛选）。

    spec 可含：``text_to_video / image_to_video / first_last_frame / lip_sync``
    （布尔）与 ``duration / resolution``（"1080p" 或 "auto"）。
    """
    s = dict(spec) if isinstance(spec, dict) else {}
    out: Dict[str, Any] = {}
    for k in ("text_to_video", "image_to_video", "first_last_frame", "lip_sync",
              "edit_video"):
        if k in s and s[k] is not None:
            out[k] = bool(s[k])
    if duration or (s.get("duration") not in (None, 0, 0.0)):
        try:
            out["duration"] = float(s.get("duration") or duration or 0.0) or None
        except (TypeError, ValueError):
            out["duration"] = None
    if out.get("duration") is None:
        out.pop("duration", None)
    res = str(s.get("resolution") or "").strip()
    if not res:
        try:
            w = int(s.get("width") or width or 0)
            h = int(s.get("height") or height or 0)
        except (TypeError, ValueError):
            w = h = 0
        res = resolution_label(w, h) if w and h else ""
    if res and res.lower() not in ("auto", "*"):
        out["resolution"] = res
    return out


# ═══════════════════════════════════════════════════════════
# 筛选 + 路由
# ═══════════════════════════════════════════════════════════


def supports(provider_id: str, spec: Optional[Dict[str, Any]] = None) -> Tuple[bool, str]:
    """检查 provider 能力是否满足本次请求 spec。

    Returns:
        (ok, reason) —— ok=False 时 reason 是人话理由；ok=True 时 reason 为空。
    """
    caps = PROVIDER_CAPS.get(provider_id)
    if caps is None:
        return False, "未声明能力（不在声明表里）"
    s = normalize_spec(spec)
    for cap_key, label in _CAP_LABELS.items():
        if s.get(cap_key) and not caps.get(cap_key):
            return False, f"不支持{label}"
    max_d = caps.get("max_duration")
    if s.get("duration") and max_d and float(s["duration"]) > float(max_d):
        return False, f"超时长（>{max_d:g}s）"
    resolutions = caps.get("resolutions") or ["*"]
    if s.get("resolution") and "*" not in resolutions and s["resolution"] not in resolutions:
        return False, f"不支持分辨率 {s['resolution']}"
    return True, ""


def filter_by_caps(order: List[str], spec: Optional[Dict[str, Any]] = None
                   ) -> Dict[str, List[Any]]:
    """按能力筛选候选 provider（**不动 local**——它是终端兜底）。

    Returns::
        {"kept": [provider_id...], "dropped": [(provider_id, 理由), ...]}
    """
    s = normalize_spec(spec)
    kept: List[str] = []
    dropped: List[Tuple[str, str]] = []
    for pid in order:
        if pid == "local":
            continue
        ok, reason = supports(pid, s)
        if ok:
            kept.append(pid)
        else:
            dropped.append((pid, reason))
            logger.info("[provider_caps] %s 被筛掉：%s", pid, reason)
    return {"kept": kept, "dropped": dropped}


def no_egress() -> bool:
    """是否开启了「素材不出域」硬约束（``SHIGUANG_NO_EGRESS=1``）。

    为什么每次调用都重读环境变量、不在 import 时算一次（2026-10-09）：
    进程级缓存会让测试无法用 monkeypatch 验证、也让长驻进程无法中途切换
    （用户在处理客户素材那一单临时打开开关）。读 env 是纳秒级操作，
    相对一次视频生成调用（秒~分钟级）完全可忽略。
    """
    return os.environ.get(ENV_NO_EGRESS, "").strip().lower() in _TRUTHY


def resolve_order(provider: str = "auto",
                  spec: Optional[Dict[str, Any]] = None,
                  priors: Optional[Dict[str, float]] = None,
                  lambda_price: Optional[float] = None) -> List[str]:
    """**主入口**：解析 provider 调用顺序（能力筛选 + 排序 + local 兜底）。

    * ``provider="auto"``：声明表满足 spec 的真实 provider；
    * 排序规则：给了 ``priors``（{provider: 期望质量 q̂}）→ **收益函数排序**
      V = q̂ − λ_c·price（规格书 §11 切片，V4.37.4）；否则退回 quality_tier
      降序（旧行为，向后兼容）；
    * ``lambda_price``：动态影子价格（V4.37.6 切片④，由 budget_pacer 按预算
      消耗连续调节）；不传用静态 ``_LAMBDA_PRICE`` 兜底；
    * 显式 provider：能力满足才进候选（不满足 → 只剩 local，理由进日志）；
    * ``local`` 永远在最后（保证无网络/无 Key 仍可演示）；
    * **``SHIGUANG_NO_EGRESS=1`` ⇒ 无条件返回 ``["local"]``**（素材不出域，
      见 `no_egress()`）。此开关**优先于一切其它参数**，包括显式 provider ——
      硬约束不该被一个函数参数绕过。
    """
    # ── 硬约束优先：出域开关在能力筛选之前拦截 ──
    if no_egress():
        logger.warning(
            "[provider_caps] %s=1 ⇒ 强制 local-only，本次请求不做任何出域调用"
            "（请求的 provider=%r 被忽略）", ENV_NO_EGRESS, provider)
        return [LOCAL_PROVIDER_ID]

    s = normalize_spec(spec)
    if provider and provider != "auto":
        # 显式指定 local：直接出域检查已过，返回单元素即可
        # （原实现走下面的 [provider, "local"] 分支会返回 ["local","local"] 重复项）
        if provider == LOCAL_PROVIDER_ID:
            return [LOCAL_PROVIDER_ID]
        ok, reason = supports(provider, s)
        if not ok:
            logger.warning("[provider_caps] 指定 provider %s 不满足本次请求：%s", provider, reason)
            return [LOCAL_PROVIDER_ID]
        return [provider, LOCAL_PROVIDER_ID]

    order = [p for p in DEFAULT_REAL_ORDER if p != "local"]
    filtered = filter_by_caps(order, s)
    kept = filtered["kept"]
    if priors:
        lam = float(lambda_price) if lambda_price is not None else _LAMBDA_PRICE

        # 收益函数排序：q̂ 缺失用中性 0.5（冷启动探索位）；tier 做平局 tiebreak
        def _utility(p: str) -> float:
            q = float(priors.get(p, 0.5))
            price = float((PROVIDER_CAPS.get(p) or {}).get("price_per_clip") or 0.0)
            return q - lam * price
        kept.sort(key=lambda p: (
            -_utility(p),
            -int((PROVIDER_CAPS.get(p) or {}).get("quality_tier") or 0)))
    else:
        # quality_tier 降序（同档保持声明表顺序，结果稳定可复现）
        kept.sort(key=lambda p: -int((PROVIDER_CAPS.get(p) or {}).get("quality_tier") or 0))
    return kept + [LOCAL_PROVIDER_ID]


# ═══════════════════════════════════════════════════════════
# 报价（P1-1 · 生成前知道花多少钱）
# ═══════════════════════════════════════════════════════════


def quote(provider: str = "auto", *, count: int = 1,
          spec: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """按能力声明**估算**一次生成的花费（纯声明推导，不查额度池）。

    ``provider="auto"`` 时取路由链的第一个候选（tier 降序后的最优）。
    额度池视角（谁接单 / 配额够不够）在 ``provider_pool.quote()`` 里叠加。

    Returns::
        {"provider", "tier", "price_per_clip", "count",
         "cost_estimate", "currency": "CNY", "fallback_chain": [...],
         "note": "估算值，实际以渠道账单为准"}
    """
    s = normalize_spec(spec)
    chain = resolve_order(provider, spec=s)
    best = chain[0] if chain else LOCAL_PROVIDER_ID
    caps = PROVIDER_CAPS.get(best) or {}
    n = max(1, int(count or 1))
    price = float(caps.get("price_per_clip") or 0.0)
    return {
        "provider": best,
        "tier": int(caps.get("quality_tier") or 0),
        "price_per_clip": price,
        "count": n,
        "cost_estimate": round(price * n, 2),
        "currency": "CNY",
        "fallback_chain": chain,
        "note": "估算值（声明单价×段数）；实际以渠道账单为准",
    }

"""L1 执行决策出口 —— 「选路」的**唯一**入口。

## 为什么单独成模块

1. **架构上就该独立**：`canvas_aigc.py` 近 3000 行，而「决定用谁执行」是**决策层（L1）**
   的职责，与「怎么执行」（L2）不属于同一层。埋在巨石文件里既找不着也改不动。
2. **规模守卫**：单文件规模守卫阈值 2000 行、**存量冻结只许减不许增**；
   把这块从 `canvas_aigc` 移出，两者都回落（沿用本项目 `editor_agent_*_mixin` 的拆分先例）。

## 背景：为什么需要这个出口（2026-10-02 核查结论）

**画布侧生成链此前完全不消费「异构动态协作引擎」的任何切片** ——
对 `budget_pacer` / `global_price` / `provider_caps` / `quality_prior` / `degradation`
等 12 个切片的引用数为 **0**；而 Agent 侧经 `ai_video_generation_pipeline`
→ `video_generation_client` 已接 11 个切片。

⇒ 两条链平行：**Agent 侧是「动态选路」，画布侧是「静态查表」**，
  画布生成因此**绕过了预算控制、价格层、渠道能力探测与质量先验**。

## 本模块的定位（**第 1 步，刻意保守**）

先把「选路」**收敛成一个可解释的单一出口**（当前行为与收敛前**逐键一致**），
后续治理切片逐个挂进来；**不一步到位改主链路**。

## 铁律

- **R2**：选路**只在这里**；调用方不得再自行查表，否则预算/价格/降级全部失效。
- **R3**：**诚实失败** —— 无可用渠道时如实返回 `ok=False` + 指引，绝不静默换路或伪造产物。
- **R4**：统一语义 → 各家参数的翻译**只在 `translate_*`**，禁止在此处散写 per-渠道分支。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# ⚠️ 模块级导入 `canvas_aigc` 是安全的：`canvas_aigc` **只在函数内惰性**引用本模块，
#    因此不构成循环导入。若将来有人把此处改成 canvas_aigc 的模块级 import，会成环。
from app.core.canvas_aigc import (
    CAPABILITY_VIDEO,
    _resolve_aigc_channel,
    local_generation_registry,
    translate_motion,
    translate_quality,
)


def decide_execution(
    *,
    capability: str = "image",
    quality: str = "standard",
    motion: str = "normal",
    channel_id: str = "",
    model: str = "",
    allow_local: bool = True,
    allow_cloud: bool = True,
    frames: int = 0,
    has_image: bool = False,
    duration: float = 0.0,
    resolution: str = "",
    default_model_key: str = "imageModel",
) -> Dict[str, Any]:
    """**L1 决策出口**。返回 ``{ok, channel_id, model, params, reasons, degrade_level, message}``。

    当前行为与收敛前一致：
      · `channel_id` 以 `local/` 开头 ⇒ 强制本地（查 `local_generation_registry`）
      · 否则 ⇒ 走 `_resolve_aigc_channel` 解析云端渠道，并在渠道内挑首个该能力的模型

    差别在于：**多了必定非空的 `reasons`**（选路可解释，线上可排障），
    且「选路」从此只有一个出口 —— 后续挂治理切片只需改这一处。
    """
    reasons: List[str] = []
    cid = (channel_id or "").strip()

    # ── 0) 主选 / 备选引擎选择（用户裁定，见文件末「主选/备选」段）──
    # ★ 铁律 R9：降级必须可见 —— 退备选时一定写进 reasons。
    eng = resolve_execution_engine()
    reasons.append(f"执行引擎：{eng['engine']}" + ("（**备选/自研**）" if eng["is_fallback"] else "（主选）")
                   + f" —— {eng['reason']}")

    # ── 1) 本地优先（显式前缀，语义与既有 `local/` 约定一致）──
    if cid.startswith("local/"):
        if not allow_local:
            return {"ok": False, "channel_id": "", "model": model, "params": {},
                    "reasons": reasons + ["调用方显式禁止本地执行，但 channel_id 指向本地"],
                    "engine": eng["engine"], "degrade_level": 0,
                    "message": "本地执行被禁用（allow_local=False）"}
        backends = local_generation_registry.resolve(capability)
        if not backends:
            return {"ok": False, "channel_id": cid, "model": model, "params": {},
                    "reasons": reasons + [f"本地无可用后端（capability={capability}）"],
                    "engine": eng["engine"], "degrade_level": 0,
                    "message": "本地推理模块不可用（请检查 local_video_infer.py / voice_generator.py）"}
        reasons.append(f"channel_id 以 local/ 开头 ⇒ 强制本地（后端 {backends[0].backend_id}）")
        if frames:
            reasons.append(f"帧数 {frames}（供本地显存分级使用）")
        return {"ok": True, "channel_id": cid, "model": model, "params": {},
                "reasons": reasons, "engine": eng["engine"], "degrade_level": 0, "message": ""}

    # ── 2) 云端渠道 ──
    if not allow_cloud:
        return {"ok": False, "channel_id": cid, "model": model, "params": {},
                "reasons": reasons + ["调用方禁止云端，且未指定本地渠道"],
                "engine": eng["engine"], "degrade_level": 0, "message": "云端执行被禁用（allow_cloud=False）"}

    ch, chan_model, _patch = _resolve_aigc_channel(
        channel_id=cid, capability=capability, default_model_key=default_model_key)
    if ch is None:
        return {"ok": False, "channel_id": cid, "model": model, "params": {},
                "reasons": reasons + [
                    f"未解析到可用云端渠道（capability={capability}，"
                    f"请求的 channel_id={cid or '（空）'}）"],
                "engine": eng["engine"], "degrade_level": 0,
                "message": "未找到可用 AIGC 渠道，请在「模型管理」配置渠道 Key"}

    resolved_model = model or chan_model
    reasons.append(f"云端渠道解析：{ch.get('id')}"
                   + ("（按请求指定）" if cid else "（回退默认渠道）"))

    # ⚠️ 「渠道内挑首个可用模型」**必须放在治理筛选之后**（见下方步骤 3），
    #    因为治理筛选可能换渠道 ⇒ 换渠道就要重挑模型。此处不再提前挑。

    # ── 3) 治理切片接入（P3，2026-10-02）────────────────────────────
    # 把选路从「名字回退」升级为「**按能力筛选 + 收益函数排序**」——
    # 这正是 LiteLLM 那套思路，而项目**早已备好零件**（此前画布侧引用数为 0）：
    #   · `provider_caps.resolve_order` —— 能力筛选 + 排序（V = q̂ − λ·price）
    #   · `budget_pacer.get_pacer().get_lambda()` —— 动态影子价格 λ
    #   · `quality_prior.get_store().predict(pid)` —— 逐 provider 的期望质量 q̂
    # 三者都是**只读**；任一失败即**诚实降级**到静态解析，**不阻断生成**。
    order: List[str] = []
    try:
        from app.core.ai import provider_caps

        # ⚠️ spec 要的是**语义标志**（text_to_video / image_to_video / first_last_frame），
        #    不是 capability/quality —— 传错键会得到空 spec、筛选**静默空转**（本次踩过）。
        spec = provider_caps.normalize_spec({
            "text_to_video": bool(capability == "video" and not has_image),
            "image_to_video": bool(capability == "video" and has_image),
            "duration": duration or 0.0,
            "resolution": resolution or "",
        })

        # ① 先拿基础候选（无先验时按 quality_tier 排序）——
        #    用它才能逐 provider 预测质量，解开「先有候选才能算先验」的依赖。
        base_order = provider_caps.resolve_order("auto", spec=spec)
        candidates = [p for p in base_order if p != "local"]

        # ② 期望质量 q̂
        priors = None
        try:
            from app.core.ai.quality_prior import get_store
            store = get_store()
            pred: Dict[str, float] = {}
            for pid in candidates:
                p = store.predict(pid)
                if isinstance(p, dict):
                    v = p.get("mean", p.get("q", p.get("quality")))
                    if isinstance(v, (int, float)):
                        pred[pid] = float(v)
            priors = pred or None
        except Exception:
            logger.debug("quality_prior 不可用，跳过收益排序先验", exc_info=True)

        # ③ 动态影子价格 λ
        lam = None
        try:
            from app.core.ai.budget_pacer import get_pacer
            lam = float(get_pacer().get_lambda())
        except Exception:
            logger.debug("budget_pacer 不可用，跳过动态影子价格", exc_info=True)

        order = provider_caps.resolve_order("auto", spec=spec, priors=priors, lambda_price=lam)
        if order:
            reasons.append(
                f"能力筛选候选：{order}"
                + ("（含质量先验收益排序）" if priors else "（按 quality_tier 排序）")
                + (f"（λ={lam:.3f}）" if isinstance(lam, (int, float)) else "")
            )
    except Exception:
        logger.debug("治理切片不可用，降级为静态解析", exc_info=True)
        reasons.append("治理切片不可用 ⇒ 降级为静态渠道解析（不影响生成）")

    # 若能力筛选给出的首选与当前解析不一致，则以筛选结果为准（**保守**：
    # 仅当候选非空、不含当前渠道、且首选渠道确实配了 Key 时才切）。
    if order and str(ch.get("id") or "") not in order and order[0] != "local":
        preferred = order[0]
        cand = next((c for c in (_patch.get("channels") or [])
                     if c.get("id") == preferred), None)
        if cand is not None and (cand.get("apiKey") or "").strip():
            reasons.append(f"能力筛选优先 {preferred}（原解析 {ch.get('id')}）⇒ 切换")
            ch = cand

    # 选定渠道后，若仍无模型则在该渠道内挑首个具备该能力的
    if not resolved_model:
        for m in ch.get("models") or []:
            if m.get("capability") == capability:
                resolved_model = str(m.get("name") or "")
                break
    if not resolved_model:
        return {"ok": False, "channel_id": str(ch.get("id") or ""), "model": "", "params": {},
                "reasons": reasons + [f"渠道 {ch.get('id')} 内没有 {capability} 能力的模型"],
                "engine": eng["engine"], "degrade_level": 0,
                "message": f"渠道内没有 {capability} 模型，请点「同步模型池」"}

    if frames:
        reasons.append(f"帧数 {frames}（本地显存分级输入，云端当前不消费）")

    # 统一语义 → 各家参数的翻译**只在 translate_***（铁律 R4）
    params: Dict[str, Any] = {}
    try:
        params["quality"] = translate_quality(quality, capability)
    except Exception:
        logger.debug("translate_quality 失败，按原值透传", exc_info=True)
        params["quality"] = quality
    if capability in (CAPABILITY_VIDEO,):
        try:
            # ⚠️ 词汇不一致的坑（2026-10-02 发现）：`neural/video_gen` 用 calm/normal/lively，
            #   而 `translate_motion` 认 low/medium/high，传错会**静默退回 medium**
            #   （不报错、结果错）—— 正是「同一信息多处演化」的典型。
            #   这里做单向归一，两套词汇都能用；**新代码请统一用 low/medium/high**。
            _alias = {"calm": "low", "normal": "medium", "lively": "high"}
            params["motion"] = translate_motion(_alias.get(motion, motion))
        except Exception:
            logger.debug("translate_motion 失败，按原值透传", exc_info=True)

    return {"ok": True, "channel_id": str(ch.get("id") or ""), "model": resolved_model,
            "params": params, "reasons": reasons, "engine": eng["engine"], "degrade_level": 0, "message": ""}


__all__ = ["decide_execution", "resolve_execution_engine", "resolve_local_image_engine",
           "PRIMARY_ENGINE", "FALLBACK_ENGINE"]


# ══════════════════════════════════════════════════════════════════════════
#  执行引擎的「主选 / 备选」选择（2026-10-02 用户裁定）
# ══════════════════════════════════════════════════════════════════════════
#
# 用户裁定：**把目前自研的执行引擎降为「备选」，另选一个成熟引擎做「主用」**；
#          等自研在能力与架构上都起来后，**再切回来**。
#
# ── 主选：DiffSynth（Apache-2.0）────────────────────────────────────────
# 为何是它（2026-10 核实，非凭印象）：
#   ① **PyPI 可装**：`pip install diffsynth`（2.1.5）；另有专门的
#      `DiffSynth-Engine`（包名 `diffsynth_engine`）**定位就是「扩散模型推理管道引擎」**，
#      而 Studio 偏学术探索 —— 取 Engine 形态，Studio 作兜底。
#   ② **被竞品生态采用**：ComfyUI 的 WanVideoWrapper 直接把 `diffsynth/vram_management`
#      封装成节点（`WanVideoVRAMManagement`）⇒ 它的显存管理被同赛道抄，含金量高。
#   ③ **被模型方官方推荐**：阿里云 Wan2.1 最佳实践文档原文推荐 DiffSynth-Studio。
#   ④ **对症本机**：**逐层（Layer 级）磁盘卸载 + FP8/INT8/NF4 量化**，
#      官方称 Wan2.1-T2V-1.3B 最低 **8G 显存**可跑 —— 正对本机 8GB 的痛点。
#      （对比：本项目自研路径目前只能靠「调小 decode_chunk_size」抠显存。）
#   ⑤ **国内直连**：模型走 **ModelScope** 下载，**不需要 HF 镜像**
#      —— 本项目此前在 HF 上必须走 hf-mirror 绕代理，这是实打实的运维收益。
#   ⑥ 许可 **Apache-2.0**，可商用（对比 ComfyUI 的 GPL-3.0 闸门）。
#
# ⚠️ 导入前置条件（2026-10-02 实装后排障，V4.40.25）：
#   `diffsynth_engine` 的真实 import 要求 moviepy **2.x 形态**（`from moviepy import
#   ImageSequenceClip`），而本项目固定在 moviepy **1.0.3**（`moviepy.editor`，剪辑主路径依赖）。
#   ⇒ 真实导入**必须**走 `app/core/neural/diffsynth_compat.py::import_diffsynth_engine()`
#   （先垫 1.x→2.x 兼容 shim 再 import）。**裸 `import diffsynth_engine` 在本环境必炸**。
#   本模块的探测只做 find_spec（存在性），不触发真实 import —— 这是刻意的：
#   find_spec 说「装了」，compat 入口保证「能 import」，两层职责分开。
#
# ── 备选：自研（builtin）────────────────────────────────────────────────
# 即「L1 决策出口 + `diffusers` 直连 + 既有 `local_video_infer`」，
# **现在就能用**（SVD 已端到端跑通），保证主选不可用时不至于断供。
#
# ── 切换方式 ───────────────────────────────────────────────────────────
# `SHIGUANG_EXEC_ENGINE`：
#   · `primary`（默认）—— 优先主选；**主选不可用则自动退备选**（并在 reasons 里说明）
#   · `fallback`      —— 强制用自研备选（**将来自研成熟后，一行配置切回来**）
#
# 纪律（铁律 R9）：**降级必须可见**。退备选时要在 `reasons` 里写明原因，
# 绝不能静默切换 —— 否则「以为在用主选、其实一直在跑备选」这种事永远查不出来。
PRIMARY_ENGINE = "diffsynth"
FALLBACK_ENGINE = "builtin"

# ── 主选的落地进度（2026-10-02 更新）────────────────────────────────────
#   · **图像生成**：已接线 ⇒ `app/core/neural/diffsynth_image.py`（SD1.5 首发，
#     补 M3「图像 ≥2 族」缺口的第 1 族）。**选图像而非视频落地的原因**：Wan 系视频绑
#     umt5-xxl T5 = 10.58GB，cpu_offload 需 ≈13.7GB 权重驻留 RAM > 本机 15.3GB 扣 OS
#     —— 视频侧主选**本机不可行**（实测，详见
#     `docs/_reports/2026-10-02-自主迭代规划与开源参照.md` §C1/C2）。
#   · **视频生成**：仍走自研备选 `video_gen`（SVD，本机唯一可行且已调优）——
#     这不是「主备制失效」，而是**按机型实测的诚实分工**；
#     Wan 视频的启用条件（量化 T5 出现 / 硬件升级）列入看板 P2。

_ENGINE_ALIASES = {
    "diffsynth": ("diffsynth_engine", "diffsynth"),
    "comfyui": ("comfy",),
    "invokeai": ("invokeai",),
}


def _probe_importable(mod_names: tuple) -> str:
    """返回**首个可导入**的模块名（用 find_spec，**不触发重量级 import**）。"""
    import importlib.util as _u
    for m in mod_names:
        try:
            if _u.find_spec(m) is not None:
                return m
        except (ImportError, ValueError, ModuleNotFoundError):
            continue
    return ""


def resolve_execution_engine(*, prefer: str = "") -> Dict[str, Any]:
    """解析「主选 / 备选」该用哪个执行引擎。

    Returns:
        ``{engine, available, is_fallback, reason, switch}``

    · `engine`：最终选定的引擎 id（`diffsynth` / `builtin`）
    · `is_fallback`：**是否退到了备选**（调用方应据此在日志/UI 上明示）
    · `switch`：当前开关值（`primary` / `fallback`）
    """
    import os

    switch = (prefer or os.environ.get("SHIGUANG_EXEC_ENGINE") or "primary").strip().lower()
    if switch in ("fallback", "builtin", "self", "自研"):
        return {"engine": FALLBACK_ENGINE, "available": True, "is_fallback": True,
                "reason": "开关显式指定走自研备选（SHIGUANG_EXEC_ENGINE=fallback）",
                "switch": "fallback"}

    mod = _probe_importable(_ENGINE_ALIASES.get(PRIMARY_ENGINE, ()))
    if mod:
        return {"engine": PRIMARY_ENGINE, "available": True, "is_fallback": False,
                "reason": f"主选引擎 {PRIMARY_ENGINE} 可用（模块 {mod}）",
                "switch": "primary"}

    # 主选不可用 ⇒ **诚实降级**到备选，并把原因交代清楚
    return {"engine": FALLBACK_ENGINE, "available": True, "is_fallback": True,
            "reason": (f"主选引擎 {PRIMARY_ENGINE} 未安装（`pip install diffsynth`）"
                       f"⇒ 退回自研备选；装好后自动启用，无需改代码"),
            "switch": "primary"}


# ── 本地图像引擎的「真分派」（刀 A1，2026-10-04）──────────────────────────
# 此前 resolve_execution_engine() 的结论只写进 reasons 文本，不改变任何执行路径
# （决策空转）。本函数是主备裁定的**第一个真执行消费者**：
# /host/local-image-generate 路由与 canvas.local_generate_image 能力共用。
# 职责边界：这里只做「选谁 + 拿单例 + 可用性核验」，生成参数翻译在引擎内部（R4）。
def resolve_local_image_engine(*, prefer: str = "") -> Dict[str, Any]:
    """按主备裁定选**本地图像引擎**并返回其单例。

    Returns:
        ``{ok, engine, is_fallback, reasons, backend, message}``
        · `backend`：引擎单例（DiffsynthImageEngine / DiffusersImageEngine），失败为 None
        · `is_fallback`：是否退到备选（R9 —— 调用方必须把此标志透出给日志/UI）

    `prefer` 可显式指定 "diffsynth" / "builtin"（大小写不敏感），
    空串则走 SHIGUANG_EXEC_ENGINE 开关（默认 primary）。
    选定的引擎不可用（缺依赖/CUDA）时**再降级一次**到另一栈，理由全部留痕。
    """
    reasons: List[str] = []
    req = (prefer or "").strip().lower()
    if req in ("diffsynth", "builtin"):
        eng = {"engine": req, "is_fallback": req != PRIMARY_ENGINE,
               "reason": f"调用方显式指定引擎 {req}", "switch": "explicit"}
    else:
        if req:
            reasons.append(f"未知 engine 指定 {req!r} ⇒ 忽略，按开关解析")
        eng = resolve_execution_engine()
    reasons.append(eng["reason"])

    def _backend(engine_id: str):
        if engine_id == "diffsynth":
            from app.core.neural import diffsynth_image as m
            return m.get_image_engine(), m.DiffsynthImageEngine.is_available, \
                m.DiffsynthImageEngine.unavailable_reason
        from app.core.neural import diffusers_image as m
        return m.get_diffusers_image_engine(), m.DiffusersImageEngine.is_available, \
            m.DiffusersImageEngine.unavailable_reason

    candidates = [eng["engine"]]
    other = FALLBACK_ENGINE if eng["engine"] == PRIMARY_ENGINE else PRIMARY_ENGINE
    candidates.append(other)

    for i, eid in enumerate(candidates):
        try:
            backend, is_avail, unavail = _backend(eid)
            if is_avail():
                if i > 0:
                    reasons.append(f"首选引擎不可用 ⇒ 降级到 {eid}（R9 可见）")
                return {"ok": True, "engine": eid,
                        "is_fallback": bool(eng.get("is_fallback")) or eid != PRIMARY_ENGINE,
                        "reasons": reasons, "backend": backend, "message": ""}
            reasons.append(f"引擎 {eid} 不可用：{unavail() or '未知原因'}")
        except Exception as e:
            logger.debug("[execution_decider] 引擎 %s 探测异常", eid, exc_info=True)
            reasons.append(f"引擎 {eid} 探测异常：{type(e).__name__}: {e}")

    return {"ok": False, "engine": "", "is_fallback": True, "reasons": reasons,
            "backend": None,
            "message": "本地图像引擎双栈均不可用（详见 reasons）"}

# -*- coding: utf-8 -*-
"""执行层专项决策器（ExecutionPlanner）—— 「这次走本地 / 走 API / 混合」的唯一裁定层。

用户指令（2026-10-23）：「在生成前面加一个专项执行层模型，让它决定怎么调度本地与 API
之间的运算逻辑和方式；这层也要能挂进画布模块和剪辑模块的智能体。」

为什么要有这一层（诊断结论，写进行免得后人重查）：
  · 项目原有 `execution_decider.decide_execution()` 只解决「云端渠道怎么挑」，
    且生产里**只有视频 local/ 分支调用它一次**；图像路径根本不经过。
  · `compute_bias`（用户滑块 0=纯本地 … 100=纯云端）也只是个数字，没有消费者。
  · 结果：本地 SD 引擎（实测健康、SD1.5/SDXL/SVD 权重齐全）与云端 API
    从来没有一个统一的地方决定「这一次谁上」。
  本模块就是那个地方：**纯决策、不执行**（执行在调用方），输出一份可解释的计划。

计划形状（`plan()` 返回）：
  {
    "ok": bool,
    "route": "local" | "cloud" | "hybrid",      # hybrid=本地先跑、云端兜底/补强
    "engine": "diffsynth" | "diffusers" | "",    # 本地引擎（route 含本地时）
    "chain": ["local", "cloud"],                 # 实际尝试顺序（可解释）
    "model_hint": str,                           # 建议模型 id（本地）
    "reasons": [str, ...],                       # 为什么这么定（R9 可见）
    "bias": int, "mode": str,                    # 用户偏好快照
    "hw_tier": str, "budget_lambda": float,      # 环境快照
    "degrade_level": int,                        # 与既有六级降级同义
  }

纪律：
  · **纯 stdlib + 惰性 import**：不 import torch/diffusers/canvas_aigc（避免环与重依赖），
    可在画布 HTTP 线程、剪辑 QThread、Agent 能力里安全调用。
  · 一切异常不外抛：探测失败按「云端优先」兜底并如实写 reason（R3/R9 诚实）。
  · **不改既有行为**：本层只产出计划；调用方没接它时，旧路径逐键不变。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger("AI短剧编辑器.core.ai.execution_planner")

# 支持本层裁定的能力（其余能力直接回落既有路径，不假装能管）
_SUPPORTED = {"image", "video", "audio", "music"}

# 本地引擎当前能纯 prompt 出图/出片的能力（诚实边界）：
#   · image ：SD1.5/SDXL 文生图 ✅（本机实测可用）
#   · video ：SVD 是**图生视频**，没有首帧/参考图就产不出真内容 ⇒ 不算可直接本地
_LOCAL_PROMPT_ONLY = {"image"}


def _engine_probe() -> Dict[str, Any]:
    """本地引擎健康度（惰性、包异常）。返回 {engine, available, is_fallback, reason}。"""
    try:
        from app.core.ai.execution_decider import resolve_execution_engine

        return resolve_execution_engine()
    except Exception as e:
        logger.debug("[execution_planner] 引擎探测失败", exc_info=True)
        return {"engine": "", "available": False, "is_fallback": True,
                "reason": f"引擎探测异常 {type(e).__name__}: {e}"}


def _hw_probe() -> Dict[str, Any]:
    try:
        from app.core.ai.execution_decider import detect_hardware_tier

        return detect_hardware_tier()
    except Exception as e:
        logger.debug("[execution_planner] 硬件探测失败", exc_info=True)
        return {"tier": "cloud", "memory_mb": 0, "gpu_name": "",
                "reason": f"硬件探测异常 {type(e).__name__}（按全云档）"}


def _budget_lambda() -> float:
    """L1 动态影子价格 λ（预算紧则大 ⇒ 倾向便宜的本地）。失败给 0.2 静态兜底。"""
    try:
        from app.core.ai.budget_pacer import get_pacer

        return float(get_pacer().get_lambda())
    except Exception:
        logger.debug("[execution_planner] 预算 λ 不可用，用静态 0.2", exc_info=True)
        return 0.2


def _cloud_available() -> bool:
    """有没有可用的云端渠道（有 Key）。失败按「不可用」处理（保守）。"""
    try:
        from app.core.canvas_aigc import build_host_ai_config_patch

        channels = list((build_host_ai_config_patch() or {}).get("channels") or [])
        return any((c.get("apiKey") or "").strip() for c in channels)
    except Exception:
        logger.debug("[execution_planner] 云端渠道探测失败", exc_info=True)
        return False


def _local_model_hint() -> str:
    """本地优先模型：优先 SDXL（质量），不可用退 SD1.5。"""
    try:
        from app.core.neural import diffsynth_image as ds

        for mid in ("sdxl-t2i", "sd15-t2i"):
            try:
                if mid in ds.IMAGE_MODELS and ds.DiffsynthImageEngine.is_downloaded(mid):
                    return mid
            except Exception:
                continue
    except Exception:
        logger.debug("[execution_planner] 本地模型探测失败", exc_info=True)
    return "sd15-t2i"


def plan(*, capability: str = "image", has_reference: bool = False,
         explicit_channel: str = "", urgency: str = "") -> Dict[str, Any]:
    """产出本次执行的调度计划（纯决策）。调用方按 `chain` 依次尝试即可。

    Args:
        capability: image / video / audio / music
        has_reference: 是否给了参考图/首帧（视频本地推理的必要条件）
        explicit_channel: 调用方显式指定的渠道（非空 ⇒ 手选优先，本层不改道）
        urgency: "fast" 表示要快（倾向本地占位/直接云端），空=常规
    """
    reasons: List[str] = []
    cap = (capability or "image").strip().lower()

    # ── 快照 ──
    bias, mode = 50, "engine"
    try:
        from app.core.ai.compute_bias import bias_mode, get_bias

        bias = get_bias().get()
        mode = bias_mode(bias)
    except Exception:
        logger.debug("[execution_planner] 偏好读取失败，按默认 engine", exc_info=True)
    eng = _engine_probe()
    hw = _hw_probe()
    lam = _budget_lambda()
    cloud_ok = _cloud_available()
    local_ok = bool(eng.get("available")) and hw.get("tier") != "cloud"
    reasons.append(f"偏好 bias={bias}（{mode}）· 硬件 {hw.get('tier')} · "
                   f"本地引擎 {eng.get('engine') or '无'}（可用={local_ok}）· "
                   f"云端渠道={'有' if cloud_ok else '无'} · λ={lam:.2f}")

    # ── 0) 显式手选：最高意图，不改道 ──
    cid = (explicit_channel or "").strip()
    if cid:
        is_local = cid.startswith("local/")
        reasons.append(f"调用方显式指定 {cid!r} ⇒ 按选择执行（本层不改道）")
        return {"ok": True, "route": "local" if is_local else "cloud",
                "engine": eng.get("engine", "") if is_local else "",
                "chain": ["local"] if is_local else ["cloud"],
                "model_hint": _local_model_hint() if is_local else "",
                "reasons": reasons, "bias": bias, "mode": mode,
                "hw_tier": hw.get("tier", ""), "budget_lambda": lam,
                "degrade_level": 0}

    # ── 1) 能力是否本地可做（诚实边界）──
    if cap not in _SUPPORTED:
        reasons.append(f"能力 {cap} 不在本层裁定范围 ⇒ 走既有路径")
        return {"ok": False, "route": "cloud", "engine": "", "chain": ["cloud"],
                "model_hint": "", "reasons": reasons, "bias": bias, "mode": mode,
                "hw_tier": hw.get("tier", ""), "budget_lambda": lam, "degrade_level": 0}

    local_doable = local_ok
    if local_doable and cap not in _LOCAL_PROMPT_ONLY and not has_reference:
        local_doable = False
        reasons.append(f"本地 {cap} 推理需要参考图/首帧（本机模型是 i2v），本次没有 ⇒ 本地不可做")

    # ── 2) 按偏好 + 环境定链 ──
    chain: List[str] = []
    route = "cloud"
    if mode == "local" and local_doable:
        route = "local"
        chain = ["local"] + (["cloud"] if cloud_ok else [])
        reasons.append("档位 local ⇒ 本地优先" + ("，云端兜底" if cloud_ok else "（无云端可用）"))
    elif mode == "cloud" and cloud_ok:
        route = "cloud"
        chain = ["cloud"] + (["local"] if local_doable else [])
        reasons.append("档位 cloud ⇒ 云端优先" + ("，本地兜底" if local_doable else ""))
    elif mode == "cloud" and not cloud_ok:
        route = "local" if local_doable else "cloud"
        chain = [route]
        reasons.append("档位 cloud 但无云端渠道 ⇒ " + ("回退本地" if local_doable else "无路可走"))
    else:
        # engine 档：动态混合 —— 本地可做且预算偏紧 ⇒ 本地先跑；否则云端先跑。
        if local_doable and cloud_ok:
            if lam >= 0.35 or urgency == "fast":
                route, chain = "hybrid", ["local", "cloud"]
                reasons.append(f"engine 档 ⇒ 混合：本地先跑（λ={lam:.2f} 偏紧/要求快）"
                               "，云端补强或兜底")
            else:
                route, chain = "hybrid", ["cloud", "local"]
                reasons.append(f"engine 档 ⇒ 混合：云端先跑（λ={lam:.2f} 宽松），本地兜底")
        elif local_doable:
            route, chain = "local", ["local"]
            reasons.append("engine 档 ⇒ 仅本地可用")
        elif cloud_ok:
            route, chain = "cloud", ["cloud"]
            reasons.append("engine 档 ⇒ 仅云端可用")
        else:
            route, chain = "cloud", ["cloud"]
            reasons.append("engine 档 ⇒ 本地与云端都不可用，仍尝试云端（由调用方如实报错）")

    # 与既有六级降级对齐：只有真混合才算 L1；单路（本地或云端）不抬降级级数。
    degrade = 1 if route == "hybrid" else 0
    return {"ok": True, "route": route, "engine": eng.get("engine", ""),
            "chain": chain, "model_hint": _local_model_hint() if "local" in chain else "",
            "reasons": reasons, "bias": bias, "mode": mode,
            "hw_tier": hw.get("tier", ""), "budget_lambda": lam,
            "degrade_level": degrade}


def status() -> Dict[str, Any]:
    """供 UI/Agent 回显当前执行层快照（只读）。"""
    eng = _engine_probe()
    hw = _hw_probe()
    bias, mode = 50, "engine"
    try:
        from app.core.ai.compute_bias import bias_mode, get_bias

        bias = get_bias().get()
        mode = bias_mode(bias)
    except Exception:
        logger.debug("[execution_planner] status 偏好读取失败", exc_info=True)
    return {"bias": bias, "mode": mode, "engine": eng,
            "hw_tier": hw.get("tier", ""), "gpu": hw.get("gpu_name", ""),
            "budget_lambda": _budget_lambda(), "cloud_available": _cloud_available(),
            "local_prompt_only": sorted(_LOCAL_PROMPT_ONLY)}

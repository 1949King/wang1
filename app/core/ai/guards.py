"""生成质量守护 · 统一门面
============================

四个守护模块的统一调度 —— 让「生成前后加守护」变成一次调用，而不是四次。

| 守护 | 模块 | 入参 | 治什么 |
|---|---|---|---|
| ``tts`` | `tts_guard` | text / max_chars / asr_texts | 配音长文本漂移 |
| ``character`` | `character_anchor` | character / shot_prompts | 人物跨镜头漂移 |
| ``expression`` | `expression_guard` | frames / emotion / profile | 表情夸张 |
| ``prop`` | `prop_guard` | prop / prop_type / grip / hand_points | 武器结构畸形 |

三个便利点：

  * ``plan_guards(kinds, params)`` —— 一次跑多个守护，合并结果与提示；
  * ``guard_negative_all()`` —— 合并四者的**全部负面词并去重**：生成时一次拼齐约束；
  * ``list_guards()`` —— 守护清单（含对应 capability id），供 UI / Agent 提示自描述。

设计纪律：只读只出计划、不 import app 包（相对导入同目录守护即可）。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional

from .guard_base import merge_unique

logger = logging.getLogger("AI短剧编辑器.core.ai.guards")

GUARD_KINDS: tuple = ("tts", "character", "expression", "prop")

_GUARD_META: List[Dict[str, Any]] = [
    {"kind": "tts", "capability": "pipeline.tts_polish", "title": "TTS 正音",
     "desc": "长台词语义切段 + 多音字注音", "has_negative": False},
    {"kind": "character", "capability": "pipeline.character_anchor", "title": "角色一致性锚定",
     "desc": "跨镜头特征卡 + 漂移检测", "has_negative": True},
    {"kind": "expression", "capability": "pipeline.expression_clamp", "title": "表情幅度守护",
     "desc": "权重钳制 + 帧间限幅 + 幅度质检", "has_negative": True},
    {"kind": "prop", "capability": "pipeline.prop_consistency", "title": "手持道具守护",
     "desc": "结构约束 + 握持描述 + 道具漂移检测", "has_negative": True},
]


def list_guards() -> List[Dict[str, Any]]:
    """守护清单（含对应 capability id），供 UI / Agent 自描述。"""
    return [dict(m) for m in _GUARD_META]


def guard_negative_all() -> List[str]:
    """合并四个守护的全部负面词（去重保序）。

    **一次拼齐**全部约束 —— 生成时不必逐个能力取负面词。
    （``tts`` 无负面词：它是「切段 + 注音」，不涉及负面提示词。）
    """
    from .character_anchor import anchor_negative
    from .expression_guard import expression_negative
    from .prop_guard import prop_negative

    return merge_unique([
        *anchor_negative(),
        *expression_negative(),
        *prop_negative(),
    ])


def _run_one(kind: str, p: Dict[str, Any]) -> Dict[str, Any]:
    """跑单个守护；内部异常一律降级为「该守护失败」，不影响其余守护。"""
    try:
        if kind == "tts":
            from .tts_guard import plan_tts

            return plan_tts(
                p.get("text", "") or "",
                max_chars=int(p.get("max_chars", 40) or 40),
                llm=p.get("llm"),
            )
        if kind == "character":
            from .character_anchor import plan_anchor, plan_multi_anchor

            chars = p.get("characters")
            if isinstance(chars, list) and chars:
                pm = p.get("prompts")
                return plan_multi_anchor(chars, prompts=pm if isinstance(pm, dict) else None)
            shots = p.get("shot_prompts")
            return plan_anchor(
                p.get("character") if isinstance(p.get("character"), dict) else None,
                prompt=str(p.get("prompt") or ""),
                reference_image=str(p.get("reference_image") or ""),
                shot_prompts=list(shots) if isinstance(shots, list) else None,
                anchor=p.get("anchor") if isinstance(p.get("anchor"), dict) else None,
            )
        if kind == "expression":
            from .expression_guard import plan_expression

            frames = p.get("frames")
            ov = p.get("overrides")
            return plan_expression(
                list(frames) if isinstance(frames, list) else None,
                emotion=str(p.get("emotion") or ""),
                profile=str(p.get("profile") or "natural"),
                overrides=ov if isinstance(ov, dict) else None,
                max_delta=float(p.get("max_delta", 0.25) or 0.25),
                sparse=bool(p.get("sparse", False)),
                sparse_min_delta=float(p.get("sparse_min_delta", 0.03) or 0.03),
            )
        if kind == "prop":
            from .prop_guard import plan_prop

            hp = p.get("hand_points")
            return plan_prop(
                p.get("prop") if isinstance(p.get("prop"), dict) else None,
                prop_type=str(p.get("prop_type") or ""),
                grip=str(p.get("grip") or "single_hand"),
                hand=str(p.get("hand") or "right"),
                custom_structure=str(p.get("custom_structure") or ""),
                off_prop_type=str(p.get("off_prop_type") or ""),
                anchor=p.get("anchor") if isinstance(p.get("anchor"), dict) else None,
                hand_points=list(hp) if isinstance(hp, list) else None,
            )
    except Exception:
        logger.debug("[guards] 守护 %s 执行异常，降级为该守护失败", kind, exc_info=True)
    return {"ok": False, "message": f"{kind} 守护执行失败（参数或内部异常）"}


def plan_guards(
    kinds: Optional[Iterable[str]] = None,
    *,
    params: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """一次跑多个守护，合并结果。

    Args:
        kinds: 要跑的守护；None = 全部（``GUARD_KINDS``）。非法项自动忽略。
        params: ``{kind: {该守护的入参}}``，如
            ``{"tts": {"text": "…"}, "prop": {"prop_type": "spear"}}``

    Returns::

        {"ok", "kinds", "results": {kind: 该守护的 plan}, "messages": [str],
         "negative": [str]}

    单个守护失败**不影响其余**（异常降级为该守护 ok=False）。
    """
    params = params or {}
    requested = list(kinds) if kinds is not None else list(GUARD_KINDS)
    sel = [k for k in requested if k in GUARD_KINDS]

    results: Dict[str, Any] = {}
    messages: List[str] = []
    for kind in sel:
        p = params.get(kind)
        r = _run_one(kind, p if isinstance(p, dict) else {})
        results[kind] = r
        msg = str(r.get("message") or "").strip()
        if msg:
            messages.append(f"[{kind}] {msg}")

    return {
        "ok": all(bool(r.get("ok")) for r in results.values()) if results else False,
        "kinds": sel,
        "results": results,
        "messages": messages,
        "negative": guard_negative_all(),
        "count": len(sel),
    }

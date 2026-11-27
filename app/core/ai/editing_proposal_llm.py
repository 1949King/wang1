# -*- coding: utf-8 -*-
"""LLM 精剪提案器 —— 把"看懂"接到 ``rough_cut_chain`` 现成的执行链上。

接线关系（本文件是整条链里唯一真正新写的"决策"件）
--------------------------------------------------
    SemanticTable + EditIntent + 记忆召回
        → TextDecisionBackend（本地 Ollama / 云端 OpenAI 兼容）
        → 模型只输出 ops（shot_id / portion / sec / reason / evidence）
        → compile_interval 用语义表把 ops 编译成帧对齐坐标
        → 组装成 rough_cut_chain.plan() **同形** proposal
        → chain.register_proposal() → 既有审核卡 → 既有 apply() → 既有 compound undo

为什么不造轮子
--------------
``rough_cut_chain.py`` 已实现：needs_confirmation 审核卡、confirmed=True 纪律、
时间线陈旧守卫、波纹删除+合缝、一条 compound 撤销、导出委托。本文件**只替换第一环
的决策者**，其余全部原样复用；降级时直接调 ``chain.plan()`` 走规则提案。

安全红线
--------
· 模型**永不输出帧号/时间坐标**：只允许引用 shot_id，坐标由 ``compile_interval``
  从语义表算。幻觉 shot_id、命中保护区/必留台词的 op 一律丢弃并记 warning。
· 一次决策 = 一个提案 = 一条 compound 撤销；不新增第二套事务层。
· 云端出域沿用 ``OpenAIVisionBackend`` 的显式授权，默认全本地。
· 所有失败诚实回传 ``degraded=True``，不生成"看起来合理"的假决策。
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

try:
    from app.core.editing.intent import EditIntent
    from app.core.editing.semantic_table import (
        SemanticTable, compile_interval, merge_intervals,
    )
    from app.core.ai.vision_backends import (
        OpenAIVisionBackend, VisionBackend, default_backend, parse_json_object,
    )
except ImportError:  # 打包/副库路径兜底
    from core.editing.intent import EditIntent  # type: ignore
    from core.editing.semantic_table import (  # type: ignore
        SemanticTable, compile_interval, merge_intervals,
    )
    from core.ai.vision_backends import (  # type: ignore
        OpenAIVisionBackend, VisionBackend, default_backend, parse_json_object,
    )

logger = logging.getLogger(__name__)

__all__ = [
    "TextDecisionBackend",
    "LocalOllamaDecision",
    "OpenAITextDecision",
    "ProposalOutcome",
    "build_fine_cut_proposal",
    "run_fine_cut",
    "recall_from_memory",
]

_DECISION_PROMPT = """你是影视精剪决策器。给你一份【帧级语义镜头表】和【剪辑意图】。
只依据表中出现过的信息决策，不要臆测画面内容，不要输出任何表外的 shot_id。

只允许输出一个 JSON 对象，格式：
{"ops":[{"op":"ripple_delete","shot_id":"s003","portion":"all","sec":0,"reason":"≤30字，说明依据哪条语义/意图","evidence":{"basis":"表中字段名"}}],
 "summary":"≤60字，说明整体节奏策略"}

字段含义：
· portion = all（整镜删） / head（从镜首删 sec 秒） / tail（从镜尾删 sec 秒）；
· sec 只在 head/tail 时有效，必须是正数；
· evidence.basis 必须指向语义表里真实存在的字段（如 asr_text / quality_score / highlight / description）。

硬约束（违反的 op 会被丢弃）：
· 不得删除含「必须保留台词」的镜头；
· 不得删除「禁改区间 / 禁改片段」内的镜头；
· 不得输出时间坐标或帧号，坐标由程序编译；
· 宁可少删，不要错删；不确定就不放进 ops。

【语义镜头表】
{semantic_table}

{intent_block}

{memory_block}
"""


class TextDecisionBackend(ABC):
    """纯文本决策后端。返回 (正文, 错误)；错误非空即视为不可用。"""

    name: str = "base"

    @abstractmethod
    def complete(self, prompt: str) -> Tuple[Optional[str], str]:
        """不得抛异常到调用链。"""


class LocalOllamaDecision(TextDecisionBackend):
    """本地 Ollama 文本模型，零费用、不出域。"""

    name = "ollama-text"

    def __init__(self, model: str = "", *, timeout_hint: str = "") -> None:
        self.model = str(model or "")
        self.timeout_hint = timeout_hint

    def complete(self, prompt: str) -> Tuple[Optional[str], str]:
        try:
            from app.core.canvas_shot_vision import _ollama_client
        except ImportError:
            try:
                from core.canvas_shot_vision import _ollama_client  # type: ignore
            except ImportError as e:
                return None, f"本地 Ollama 客户端不可用：{e}"
        try:
            client = _ollama_client()
            parts = list(client.chat(
                self.model,
                [{"role": "user", "content": prompt}],
                stream=False, think=False, format="json",
            ))
            text = "".join(str(p) for p in parts).strip()
        except Exception as e:
            logger.debug("[fine-cut] 本地决策模型调用失败：%s", e, exc_info=True)
            return None, f"{type(e).__name__}: {e}"
        return (text, "") if text else (None, "本地决策模型返回空正文")


class OpenAITextDecision(TextDecisionBackend):
    """复用 ``OpenAIVisionBackend`` 的配置与出域授权，但只发纯文本。

    这样做不引入第二套 key/开关/超时配置；云端默认仍是关的。
    """

    name = "openai-text"

    def __init__(self, backend: OpenAIVisionBackend) -> None:
        self.backend = backend

    def complete(self, prompt: str) -> Tuple[Optional[str], str]:
        err = self.backend._availability_error()
        if err:
            return None, err
        payload = {
            "model": self.backend.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "max_tokens": self.backend.max_tokens,
            "temperature": self.backend.temperature,
        }
        try:
            body = self.backend._post(payload)
        except Exception as e:
            logger.debug("[fine-cut] 云端决策调用失败：%s", e, exc_info=True)
            return None, f"{type(e).__name__}: {e}"
        content, reasoning, usage = OpenAIVisionBackend._extract_message(body)
        self.backend.last_usage = usage
        if not content.strip():
            if reasoning.strip():
                return None, (
                    "思考耗尽 max_tokens：正文为空但仍计费，"
                    f"请提高 SHIGUANG_VISION_MAX_TOKENS（当前 {self.backend.max_tokens}）"
                )
            return None, "云端决策返回空正文"
        return content, ""


def recall_from_memory(intent: EditIntent, *, limit: int = 5) -> str:
    """从 ``memory_store`` 召回与本次意图相关的历史经验。

    失败静默降级为空串（记忆是增强项，不是链路前置条件）。
    """
    try:
        from app.core.memory_store import MemoryStore
    except ImportError:
        try:
            from core.memory_store import MemoryStore  # type: ignore
        except ImportError:
            return ""
    try:
        store = MemoryStore.get_instance()
        entries = store.query(tags=list(intent.tags) or None, limit=max(1, int(limit)))
        lines = []
        for e in entries or ():
            content = getattr(e, "content", None)
            if isinstance(content, Mapping):
                text = str(content.get("note") or content.get("reason") or content.get("summary") or "")
                if text:
                    lines.append(f"- {text}")
        return "\n".join(lines[:limit])
    except Exception as e:
        logger.debug("[fine-cut] 记忆召回失败（不阻断）：%s", e, exc_info=True)
        return ""


@dataclass
class ProposalOutcome:
    ok: bool
    proposal: Optional[Dict[str, Any]] = None
    warnings: List[str] = field(default_factory=list)
    degraded: bool = False
    error: str = ""
    source: str = ""        # llm-local / llm-cloud / rule-fallback
    usage: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok, "proposal": self.proposal, "warnings": list(self.warnings),
            "degraded": self.degraded, "error": self.error, "source": self.source,
            "usage": dict(self.usage),
        }


def _layout_from_clips(clips: Sequence[Mapping[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str], float]:
    """复用 rough_cut_chain 的 _clip_start/_clip_dur，保证与 apply() 判定口径一致。"""
    try:
        from app.core.rough_cut_chain import _clip_dur, _clip_start
    except ImportError:
        from core.rough_cut_chain import _clip_dur, _clip_start  # type: ignore
    layout = [
        {
            "id": str(c.get("id")),
            "track": int(c.get("track", 0) or 0),
            "start_time": round(_clip_start(c), 4),
            "duration": round(_clip_dur(c), 4),
        }
        for c in clips
    ]
    return layout, [row["id"] for row in layout], sum(row["duration"] for row in layout)


def _parse_ops(text: str) -> Tuple[List[Dict[str, Any]], str]:
    obj = parse_json_object(text)
    if obj is None:
        return [], "决策输出不是可解析的 JSON 对象"
    raw_ops = obj.get("ops")
    if raw_ops is None:
        return [], "决策输出缺少 ops 字段"
    if not isinstance(raw_ops, list):
        return [], "ops 必须是数组"
    return [dict(o) for o in raw_ops if isinstance(o, dict)], ""


def build_fine_cut_proposal(
    clips: Sequence[Mapping[str, Any]],
    table: SemanticTable,
    intent: EditIntent,
    backend: TextDecisionBackend,
    *,
    recall: str = "",
    request_id: str = "",
    label: str = "AI 精剪提案",
) -> ProposalOutcome:
    """产出 ``rough_cut_chain.plan()`` 同形 proposal（**不注册、不写时间线**）。

    调用方用 ``chain.register_proposal(proposal)`` 接进既有审核卡与 apply 链。
    """
    warnings: List[str] = list(table.warnings)
    problems = intent.validate()
    if problems:
        return ProposalOutcome(ok=False, warnings=problems, degraded=True, error="意图规格非法")
    if not clips:
        return ProposalOutcome(ok=False, degraded=True, error="时间线为空，无法生成提案")
    if not table.shots:
        return ProposalOutcome(ok=False, degraded=True, error="语义镜头表为空（感知未产出）")

    # 用 replace 而非 str.format：模板里含 JSON 示例的 {}，format 会把
    # {"ops":...} 当成占位符并抛 KeyError（实测踩过，别改回 format）。
    prompt = (
        _DECISION_PROMPT
        .replace("{semantic_table}", json.dumps(table.to_llm_payload(intent), ensure_ascii=False))
        .replace("{intent_block}", intent.to_prompt_block())
        .replace(
            "{memory_block}",
            ("【历史经验（仅供参考，不覆盖本次意图）】\n" + recall) if recall else "【历史经验】无",
        )
    )
    text, err = backend.complete(prompt)
    if not text:
        return ProposalOutcome(
            ok=False, warnings=warnings, degraded=True,
            error=f"决策后端不可用：{err}", source=backend.name,
        )
    ops, parse_err = _parse_ops(text)
    if parse_err:
        return ProposalOutcome(
            ok=False, warnings=warnings, degraded=True,
            error=parse_err, source=backend.name,
        )

    intervals: List[Dict[str, Any]] = []
    valid_ops = 0
    for idx, op in enumerate(ops):
        sid = str(op.get("shot_id") or "").strip()
        shot = table.shot_by_id(sid)
        if shot is None:
            warnings.append(f"op[{idx}] 引用了表中不存在的 shot_id={sid!r}，已丢弃")
            continue
        iv, why = compile_interval(shot, op, intent)
        if iv is None:
            warnings.append(f"op[{idx}] 未通过约束：{why}")
            continue
        intervals.append(iv)
        valid_ops += 1

    intervals = merge_intervals(intervals)
    layout, clip_ids, original_duration = _layout_from_clips(clips)
    deleted = sum(max(0.0, float(iv["timeline_out"]) - float(iv["timeline_in"])) for iv in intervals)
    predicted = max(0.0, original_duration - deleted)

    if intent.target_duration_sec > 0:
        delta = abs(predicted - intent.target_duration_sec)
        if delta > intent.duration_tolerance_sec:
            warnings.append(
                f"预测时长 {predicted:.2f}s 与目标 {intent.target_duration_sec:.2f}s "
                f"偏差 {delta:.2f}s（容差 {intent.duration_tolerance_sec:.2f}s），"
                "已如实保留，交由复核层判定，未自动补刀"
            )
    if valid_ops == 0:
        warnings.append("模型未给出任何通过约束的剪辑操作，提案为空（不擅自代决策）")

    proposal: Dict[str, Any] = {
        "plan_id": uuid.uuid4().hex[:12],
        "created_at": time.time(),
        "label": str(label or "AI 精剪提案"),
        "mode": "timeline",
        "request_id": str(request_id or ""),
        "needs_confirmation": True,
        "status": "pending_confirmation",
        "applied": False,
        "clip_ids": clip_ids,
        "layout": layout,
        "intervals": intervals,
        "original_duration": round(original_duration, 3),
        "predicted_duration": round(predicted, 3),
        "deleted_duration": round(deleted, 3),
        "warnings": warnings,
        # 附加溯源字段：apply() 不消费，供复核/记忆回流使用
        "intent": intent.to_dict(),
        "intent_fingerprint": intent.fingerprint(),
        "semantic_source": table.source,
        "decision_source": backend.name,
        "evidence_index": {s.shot_id: s.evidence() for s in table.shots},
    }
    usage = {}
    inner = getattr(backend, "backend", None)
    if inner is not None and isinstance(getattr(inner, "last_usage", None), dict):
        usage = dict(inner.last_usage)
    return ProposalOutcome(
        ok=True, proposal=proposal, warnings=warnings, source=backend.name, usage=usage,
    )


def run_fine_cut(
    clips: Sequence[Mapping[str, Any]],
    table: SemanticTable,
    intent: EditIntent,
    *,
    decision_backend: Optional[TextDecisionBackend] = None,
    chain: Any = None,
    asr_by_clip: Optional[Dict[str, Sequence[Dict[str, Any]]]] = None,
    subtitles: Optional[Sequence[Dict[str, Any]]] = None,
    request_id: str = "",
    recall: Optional[str] = None,
) -> ProposalOutcome:
    """端到端编排：LLM 提案 → 注册进既有链；失败则诚实降级到既有规则粗剪链。

    返回的 ``proposal`` 已注册（含审核卡广播），调用方只需拿 ``plan_id`` 等用户确认后
    调 ``chain.apply(editor, plan_id, confirmed=True)``。
    """
    if chain is None:
        try:
            from app.core.rough_cut_chain import rough_cut_chain as chain
        except ImportError:
            from core.rough_cut_chain import rough_cut_chain as chain  # type: ignore

    if decision_backend is None:
        vb: VisionBackend = default_backend()
        if isinstance(vb, OpenAIVisionBackend):
            decision_backend = OpenAITextDecision(vb)
        else:
            decision_backend = LocalOllamaDecision(model=getattr(vb, "model", ""))

    # 显式传 "" 可完全跳过记忆 IO（离线单测用）；None 才自动召回。
    memory_text = recall_from_memory(intent) if recall is None else recall
    outcome = build_fine_cut_proposal(
        clips, table, intent, decision_backend,
        recall=memory_text, request_id=request_id,
    )
    if outcome.ok and outcome.proposal is not None:
        reg = chain.register_proposal(outcome.proposal)
        if not reg.get("ok"):
            outcome.ok = False
            outcome.error = f"提案注册失败：{reg.get('error')}"
            outcome.degraded = True
            return outcome
        # 与 chain 内部生成的 plan_id 对齐（register_proposal 只补缺，不覆盖已有 id）
        outcome.proposal["plan_id"] = reg.get("plan_id", outcome.proposal["plan_id"])
        return outcome

    # ── 诚实降级：直接复用既有规则粗剪链（它自己会注册 + 广播审核卡）──
    logger.debug("[fine-cut] LLM 提案不可用，降级规则链：%s", outcome.error)
    try:
        res = chain.plan(
            clips, mode="timeline", asr_by_clip=asr_by_clip,
            subtitles=subtitles, label="规则粗剪（AI 精剪降级）", request_id=request_id,
        )
    except Exception as e:
        logger.debug("[fine-cut] 规则降级也失败：%s", e, exc_info=True)
        outcome.error = f"{outcome.error}；规则降级亦失败：{type(e).__name__}: {e}"
        return outcome
    if not res.get("ok"):
        outcome.error = f"{outcome.error}；规则降级失败：{res.get('error')}"
        return outcome
    fallback = res.get("proposal") or {}
    return ProposalOutcome(
        ok=True, proposal=fallback,
        warnings=[*outcome.warnings, f"AI 精剪不可用，已降级为规则粗剪：{outcome.error}"],
        degraded=True, error=outcome.error, source="rule-fallback",
    )

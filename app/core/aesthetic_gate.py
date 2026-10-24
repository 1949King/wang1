# -*- coding: utf-8 -*-
"""审美治理闸门（2026-10-20 · 治理线第一刀）

回答一个问题：**什么分数不许进下游？**（设计文档 §7.4：现在能打分、不能「管」）

输入 = `FiveDimensionScorer.to_dict()` 的形状：
    {clip_id, dimensions{visual_quality,narrative_highlight,copy_match,bgm_match,shot_duration},
     weighted_score, grade, should_drop, estimated_dims, is_fully_estimated}

输出 = `pass / review / block` + 原因码。纯函数、零依赖、可单测；
**只做判定，不做 UI、不写时间线**——接入 S3→S4 的写闸门是下一刀（见任务清单 E2）。

诚实纪律：
* 估算维度（`estimated_dims`）不能当真实评分 ⇒ 默认进 review 而不是 pass；
* 缺字段不猜：缺 weighted_score 时按五维权重算；缺维度则跳过该维度硬底线并记录；
* 所有拦截都带原因，不静默丢弃。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

GATE_VERSION = "1.0"

WEIGHTS: Dict[str, float] = {
    "visual_quality": 0.25,
    "narrative_highlight": 0.25,
    "copy_match": 0.20,
    "bgm_match": 0.15,
    "shot_duration": 0.15,
}

GRADE_THRESHOLDS: Dict[str, float] = {"S": 90.0, "A": 80.0, "B": 70.0, "C": 60.0}

DEFAULT_POLICY: Dict[str, Any] = {
    "min_weighted_score": 60.0,       # 低于 60 = D 级，默认 block
    "block_grades": ["D"],
    "review_grades": ["C"],           # C 级可进人工复核，不直接 pass
    "hard_floors": {                  # 单维硬底线（0-100 原始分）
        "visual_quality": 10.0,
        "narrative_highlight": 10.0,
    },
    "estimated_requires_review": True,
}


def _num(value: Any, default: Optional[float] = None) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return float(value)


def policy_errors(policy: Dict[str, Any]) -> List[str]:
    """策略自检：阈值单调、分数范围、等级集合合法。缺省项按 DEFAULT_POLICY 补齐。"""
    policy = dict(DEFAULT_POLICY, **(policy or {}))
    errors: List[str] = []
    min_score = _num(policy.get("min_weighted_score"))
    if min_score is None or not (0.0 <= min_score <= 100.0):
        errors.append("min_weighted_score 必须在 0~100")
    thresholds = policy.get("grade_thresholds") or GRADE_THRESHOLDS
    for grade, value in thresholds.items():
        v = _num(value)
        if v is None or not (0.0 <= v <= 100.0):
            errors.append(f"grade_thresholds.{grade} 必须在 0~100")
    if len(set(thresholds.values())) != len(thresholds):
        errors.append("grade_thresholds 存在重复阈值")
    for key in ("block_grades", "review_grades"):
        vals = policy.get(key)
        if not isinstance(vals, list) or any(not isinstance(x, str) for x in vals):
            errors.append(f"{key} 必须是字符串数组")
    overlap = set(policy.get("block_grades") or []) & set(policy.get("review_grades") or [])
    if overlap:
        errors.append(f"block_grades 与 review_grades 重叠：{sorted(overlap)}")
    floors = policy.get("hard_floors")
    if floors is not None and not isinstance(floors, dict):
        errors.append("hard_floors 必须是对象")
    return errors


def weighted_score(dimensions: Dict[str, Any]) -> Optional[float]:
    if not isinstance(dimensions, dict) or not dimensions:
        return None
    total = 0.0
    weight_sum = 0.0
    for key, weight in WEIGHTS.items():
        value = _num(dimensions.get(key))
        if value is None:
            continue
        total += max(0.0, min(100.0, value)) * weight
        weight_sum += weight
    if weight_sum <= 0:
        return None
    return round(total / weight_sum, 1)


def grade_of(score: float, thresholds: Optional[Dict[str, float]] = None) -> str:
    th = thresholds or GRADE_THRESHOLDS
    for grade in ("S", "A", "B", "C"):
        if score >= float(th[grade]):
            return grade
    return "D"


def evaluate_gate(
    item: Dict[str, Any],
    policy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """对单条评分结果做闸门判定。返回 decision + reasons（原因码）。"""
    policy = dict(DEFAULT_POLICY, **(policy or {}))
    errors = policy_errors(policy)
    if errors:
        return {
            "clip_id": str((item or {}).get("clip_id") or ""),
            "decision": "block",
            "reasons": [f"policy_invalid:{e}" for e in errors],
            "gate": GATE_VERSION,
        }
    item = item or {}
    dimensions = item.get("dimensions") if isinstance(item.get("dimensions"), dict) else {}
    score = _num(item.get("weighted_score"))
    if score is None:
        score = weighted_score(dimensions)
    if score is None:
        return {
            "clip_id": str(item.get("clip_id") or ""),
            "decision": "block",
            "reasons": ["missing_scores"],
            "gate": GATE_VERSION,
        }
    thresholds = policy.get("grade_thresholds") or GRADE_THRESHOLDS
    grade = str(item.get("grade") or grade_of(score, thresholds))
    estimated = list(item.get("estimated_dims") or [])
    reasons: List[str] = []
    decision = "pass"

    if grade in set(policy.get("block_grades") or []) or score < float(policy["min_weighted_score"]):
        decision = "block"
        reasons.append(f"score_below_min:{score:.1f}<{float(policy['min_weighted_score']):.1f}"
                       if score < float(policy["min_weighted_score"]) else f"grade_blocked:{grade}")
    floors = policy.get("hard_floors") or {}
    for dim, floor in floors.items():
        value = _num(dimensions.get(dim))
        if value is None:
            reasons.append(f"dimension_missing:{dim}")
            continue
        if value < float(floor):
            decision = "block"
            reasons.append(f"dimension_floor:{dim}:{value:.1f}<{float(floor):.1f}")
    if decision != "block":
        if grade in set(policy.get("review_grades") or []):
            decision = "review"
            reasons.append(f"grade_review:{grade}")
        if policy.get("estimated_requires_review") and estimated:
            decision = "review" if decision == "pass" else decision
            reasons.append("estimated_review:" + ",".join(estimated))
    if not reasons:
        reasons.append("passed")
    return {
        "clip_id": str(item.get("clip_id") or ""),
        "decision": decision,
        "grade": grade,
        "weighted_score": round(score, 1),
        "reasons": reasons,
        "estimated_dims": estimated,
        "gate": GATE_VERSION,
    }


def evaluate_batch(
    items: List[Dict[str, Any]],
    policy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    decisions = [evaluate_gate(item, policy) for item in (items or [])]
    counts = {"pass": 0, "review": 0, "block": 0}
    for d in decisions:
        counts[d["decision"]] = counts.get(d["decision"], 0) + 1
    return {"counts": counts, "decisions": decisions, "gate": GATE_VERSION}

# -*- coding: utf-8 -*-
"""问题路由规则表（Problem Router，智能时间线 P1 / §6.9，2026-10-17）。

§6.8.5 第 3 步「问题分类路由」的判据落地 —— **不是所有问题都回画布**：
  · 剪辑问题（节奏/顺序/时长/音频适配）→ 时间线内修复（edit_commands）
  · 生成问题（画面崩坏/不一致）→ 退回画布局部重拍（segment_retake）
  · 文案与画面不符 → 指令式编辑（video_edit_client，失败保原镜纪律不变）
  · 混合问题 → 组合序列（先时间线内低成本修，再动生成层）+ 人工确认

【边界（§6.9-P1 原文）】本模块是**纯函数**：只输出路由建议，不调用任何通道、
不碰 UI、不读文件；UI/Agent 拿到结果后**仍需用户确认才执行**（「确认后执行」
纪律不变）。输入口径与 five_dimension_scorer.ScoreResult.to_dict() 对齐：

    review   = {"dimensions": {维度: 0-100}, "estimated_dims": [维度...],
                "grade": "S/A/B/C/D"}        # grade 目前不参与判据（保留字段）
    features = {"has_canvas_lineage": bool,  # clip 是否带画布血缘（canvas_node_id/generation）
                "marks": [str]}              # 审核卡显式标记，识别词表见 MARK_*

marks 识别词表（其余标记一律忽略，不猜）：
  · MARK_SUBTITLE_ERROR "subtitle_error" → 文案问题判为字幕错（时间线内可修）
  · MARK_FRAME_MISMATCH "frame_mismatch" → 文案问题判为画面不符（指令式编辑）
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── 判据常量 ──────────────────────────────────────────────────────────
#: 单维低分线：与五维评分 D 级口径一致（<60 即该维有问题）
LOW_THRESHOLD = 60.0

# 路由动作（与三通道一一对应，字符串即通道名）
ACTION_SEGMENT_RETAKE = "segment_retake"   # 画布局部重拍
ACTION_VIDEO_EDIT = "video_edit"           # 云端指令式编辑
ACTION_TIMELINE_EDIT = "timeline_edit"     # 时间线内操作
ACTION_MIXED = "mixed"                     # 混合问题：组合序列
ACTION_MANUAL = "manual"                   # 信号不足：诚实交人工
ACTION_KEEP = "keep"                       # 无低分维度：保留不动

# marks 识别词表（只认这两个，其余忽略 —— 绝不拿未知标记猜路由）
MARK_SUBTITLE_ERROR = "subtitle_error"
MARK_FRAME_MISMATCH = "frame_mismatch"

# 维度 → 问题类别（规则表核心：类别决定通道）
DIM_CATEGORY: Dict[str, str] = {
    "visual_quality": "generation",     # 画面崩坏/不一致
    "narrative_highlight": "editing",   # 节奏/顺序
    "shot_duration": "editing",         # 时长
    "bgm_match": "editing",             # 音频适配
    "copy_match": "copy",               # 文案匹配：需按 marks 细分
}

# 类别 → 通道
CATEGORY_ACTION: Dict[str, str] = {
    "generation": ACTION_SEGMENT_RETAKE,
    "editing": ACTION_TIMELINE_EDIT,
    "copy": ACTION_VIDEO_EDIT,
}

# 混合问题的执行顺序：先时间线内（零成本、不动素材），再指令编辑，最后重拍
# （重拍代价最高 —— 生成一次要烧额度，放最后）
MIXED_ORDER: Tuple[str, ...] = (ACTION_TIMELINE_EDIT, ACTION_VIDEO_EDIT,
                                ACTION_SEGMENT_RETAKE)


def _to_float(v: Any) -> Optional[float]:
    """维度值安全转 float：非数值/None 返回 None（该维不参与判据，不抛）。"""
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def low_dimensions(review: Any, *, threshold: float = LOW_THRESHOLD) -> List[str]:
    """**纯函数**：挑出低于低分线的已知维度（保持 DIM_CATEGORY 声明序）。

    脏输入全兜住：review 非 dict / dimensions 缺失或非 dict / 值非数值 →
    一律忽略该维，绝不抛异常（调用方可能直接透传前端 JSON）。
    """
    if not isinstance(review, dict):
        return []
    dims = review.get("dimensions")
    if not isinstance(dims, dict):
        return []
    out: List[str] = []
    for key in DIM_CATEGORY:
        v = _to_float(dims.get(key))
        if v is not None and v < threshold:
            out.append(key)
    return out


def _copy_action(marks: List[str]) -> Tuple[str, str]:
    """copy_match 细分：字幕错→时间线内；画面不符/无细标→指令编辑（附说明）。"""
    if MARK_SUBTITLE_ERROR in marks:
        return ACTION_TIMELINE_EDIT, "文案问题带字幕错标记：时间线内改字幕即可"
    if MARK_FRAME_MISMATCH in marks:
        return ACTION_VIDEO_EDIT, "文案问题带画面不符标记：走指令式编辑改画面"
    return ACTION_VIDEO_EDIT, ("文案问题未细分标记：默认走指令式编辑；"
                               "若实为字幕错请打 subtitle_error 标记后重路由")


def route_problem(review: Any, features: Any = None) -> Dict[str, Any]:
    """**纯函数**：问题标记/片段特征 → 路由建议（规则表主入口）。

    Returns::
        {"ok": True, "action": 通道名, "steps": [按序通道...],
         "low_dims": [低分维度...], "categories": [问题类别...],
         "confidence": 0.0~1.0, "needs_confirmation": bool,
         "reason": 给人话的判定说明, "notes": [降级/默认值说明...]}

    只输出建议，**不执行**；needs_confirmation=False 仅出现在 keep。
    """
    feats: Dict[str, Any] = features if isinstance(features, dict) else {}
    marks = [str(m) for m in (feats.get("marks") or []) if isinstance(m, (str, int))]
    notes: List[str] = []

    lows = low_dimensions(review)
    dims = (review.get("dimensions") if isinstance(review, dict) else None) or {}
    known = [k for k in DIM_CATEGORY if _to_float(dims.get(k)) is not None]

    # ── 兜底：没有任何可用维度 ⇒ 诚实 manual，绝不猜 ──
    if not known:
        return {"ok": True, "action": ACTION_MANUAL, "steps": [ACTION_MANUAL],
                "low_dims": [], "categories": [], "confidence": 0.0,
                "needs_confirmation": True,
                "reason": "无可用五维评分，信号不足——请人工判断走哪条通道",
                "notes": notes}

    # ── 无低分维度：保留不动 ──
    if not lows:
        return {"ok": True, "action": ACTION_KEEP, "steps": [],
                "low_dims": [], "categories": [], "confidence": 1.0,
                "needs_confirmation": False,
                "reason": "五维均不低于低分线（%g）——保留，无需返工" % LOW_THRESHOLD,
                "notes": notes}

    # ── 维度 → 类别 → 通道 ──
    cat_of: Dict[str, str] = {}
    action_of: Dict[str, str] = {}
    for d in lows:
        cat = DIM_CATEGORY[d]
        if cat == "copy":
            act, why = _copy_action(marks)
            notes.append(why)
            # 细分后字幕错并入 editing 类（避免与剪辑问题混成 mixed 单列）
            cat = "editing" if act == ACTION_TIMELINE_EDIT else "content_edit"
        else:
            act = CATEGORY_ACTION[cat]
        cat_of[d] = cat
        action_of[d] = act

    # 生成类但无画布血缘：没有源节点可「退回重拍」→ 降级指令编辑（如实标注）
    has_lineage = bool(feats.get("has_canvas_lineage"))
    if not has_lineage and ACTION_SEGMENT_RETAKE in action_of.values():
        notes.append("画面问题但片段无画布血缘（canvas_node_id/generation）："
                     "无源节点可退回重拍，降级为指令式编辑通道")
        action_of = {d: (ACTION_VIDEO_EDIT if a == ACTION_SEGMENT_RETAKE else a)
                     for d, a in action_of.items()}

    actions = list(dict.fromkeys(action_of.values()))  # 去重保序
    categories = sorted(set(cat_of.values()))

    if len(actions) == 1:
        action = actions[0]
        steps = [action]
    else:
        # 混合问题：按 MIXED_ORDER 排组合序列（先便宜后贵）
        steps = [a for a in MIXED_ORDER if a in actions]
        action = ACTION_MIXED

    # ── 置信度：低分维度里实测分占比 + 低分严重度（估算分/降级都拉低）──
    estimated = {str(e) for e in ((review.get("estimated_dims")
                                   if isinstance(review, dict) else None) or [])}
    measured_ratio = (len([d for d in lows if d not in estimated]) / len(lows)) if lows else 0.0
    severity = sum(max(0.0, (LOW_THRESHOLD - _to_float(dims.get(d))) / LOW_THRESHOLD)
                   for d in lows) / len(lows)
    confidence = round(0.45 + 0.35 * measured_ratio + 0.20 * min(1.0, severity), 2)
    if notes:
        confidence = round(max(0.0, confidence - 0.10), 2)  # 走了默认/降级即降置信
    if measured_ratio == 0.0:
        confidence = min(confidence, 0.5)  # 全估算：封顶 0.5，不许冒充高置信

    reason = "低分维度 %s → 问题类别 %s → %s" % (
        "、".join(lows), "、".join(categories),
        "组合序列 " + " → ".join(steps) if action == ACTION_MIXED else steps[0])

    return {"ok": True, "action": action, "steps": steps,
            "low_dims": lows, "categories": categories,
            "confidence": confidence, "needs_confirmation": True,
            "reason": reason, "notes": notes}

# -*- coding: utf-8 -*-
"""§6.9-P3 语义轨道原型：高光/质量分落 clip 元数据（B4「AI 结果挂 clip」，2026-10-17）

形态（与 §1.4「不重写时间线架构」红线兼容的唯一形态，见文档 §6.9-P3）：
  - **不新增轨道类型、不动时间线架构**；语义信号全部挂在 clip dict 的
    ``clip["semantic"]`` 元数据块上（工程保存全量 JSON dump 自动落盘，
    与 6.9-P1 ``clip["generation"]`` 血缘块同先例）。
  - 质量分：五维打分（five_dimension_scorer）盖章写入，估算维度如实标注
    （estimated_dims / is_fully_estimated 不隐瞒，对齐 §8 诚实红线）。
  - 高光：narrative_highlight ≥ 80（A 级线，对齐 GRADE_THRESHOLDS["A"]）
    自动判定；人工/Agent 显式标记（marked_by）优先，自动判定不覆盖人工标记。
  - 入库后编辑器可能重生成 id，按 ``source_clip_id`` 别名回退解析
    （与 rough_cut_chain 同一断链修复口径）。

本模块全部是 clip dict 的纯数据操作：不碰 UI、不发事件、不建撤销条目
（写回入口在能力层，撤销语义由调用方决定）。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Sequence

#: clip dict 上语义块的键名（唯一真相源键，勿散写字符串）
SEMANTIC_KEY = "semantic"
#: 高光判定取的维度（高光叙事）
HIGHLIGHT_DIM = "narrative_highlight"
#: 自动高光阈值 = A 级线（five_dimension_scorer.GRADE_THRESHOLDS["A"]）
HIGHLIGHT_THRESHOLD = 80.0


def _now() -> float:
    return time.time()


def get_semantic(clip: Dict[str, Any]) -> Dict[str, Any]:
    """读片段语义块（不存在返回空 dict，不造默认值——诚实）。"""
    if not isinstance(clip, dict):
        return {}
    sem = clip.get(SEMANTIC_KEY)
    return sem if isinstance(sem, dict) else {}


def _index_by_alias(clips: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """id + source_clip_id 双键索引（别名不覆盖真实 id）。"""
    by_alias: Dict[str, Dict[str, Any]] = {}
    for c in clips:
        if not isinstance(c, dict):
            continue
        cid = c.get("id")
        if cid:
            by_alias.setdefault(str(cid), c)
            alias = c.get("source_clip_id")
            if alias:
                by_alias.setdefault(str(alias), c)
    return by_alias


def _is_manual_highlight(sem: Dict[str, Any]) -> bool:
    hl = sem.get("highlight")
    return isinstance(hl, dict) and hl.get("marked_by") in ("manual", "agent")


def stamp_scored_results(
    clips: Sequence[Dict[str, Any]],
    results: Sequence[Dict[str, Any]],
) -> int:
    """五维打分结果（ScoreResult.to_dict 形状）→ 盖章到对应 clip 的语义块。

    按 clip_id / source_clip_id 别名匹配；无匹配的条目如实跳过（不造片段）。
    返回成功盖章的片段数。
    """
    by_alias = _index_by_alias(clips)
    stamped = 0
    for r in results or []:
        if not isinstance(r, dict):
            continue
        cid = str(r.get("clip_id") or "")
        clip = by_alias.get(cid)
        if clip is None:
            continue
        dims = r.get("dimensions") or {}
        try:
            nh = float(dims.get(HIGHLIGHT_DIM, 0) or 0)
        except (TypeError, ValueError):
            nh = 0.0
        sem = clip.setdefault(SEMANTIC_KEY, {})
        sem["quality"] = {
            "weighted_score": r.get("weighted_score"),
            "grade": r.get("grade"),
            "dimensions": dict(dims),
            "estimated_dims": list(r.get("estimated_dims") or []),
            "is_fully_estimated": bool(r.get("is_fully_estimated", False)),
            "should_drop": bool(r.get("should_drop", False)),
            "scored_at": _now(),
            "source": "five_dimension_scorer",
        }
        # 高光自动判定：人工/Agent 显式标记优先，自动值不覆盖人工标记
        if not _is_manual_highlight(sem):
            sem["highlight"] = {
                "value": nh >= HIGHLIGHT_THRESHOLD,
                "auto": True,
                "dim_score": nh,
                "threshold": HIGHLIGHT_THRESHOLD,
                "updated_at": _now(),
            }
        stamped += 1
    return stamped


def mark_highlight(
    clips: Sequence[Dict[str, Any]],
    clip_id: str,
    value: bool,
    *,
    marked_by: str = "agent",
    note: str = "",
) -> bool:
    """人工/Agent 显式标记高光（覆盖自动判定；后续打分盖章不再回改）。"""
    clip = _index_by_alias(clips).get(str(clip_id or ""))
    if clip is None:
        return False
    sem = clip.setdefault(SEMANTIC_KEY, {})
    sem["highlight"] = {
        "value": bool(value),
        "auto": False,
        "marked_by": str(marked_by or "agent"),
        "note": str(note or ""),
        "updated_at": _now(),
    }
    return True


def read_semantic(
    clips: Sequence[Dict[str, Any]],
    clip_id: str = "",
) -> List[Dict[str, Any]]:
    """查询语义元数据（给 clip_id 查单个，不给列全部）；无语义块如实返回空。"""
    out: List[Dict[str, Any]] = []
    for c in clips:
        if not isinstance(c, dict):
            continue
        cid = str(c.get("id") or "")
        if clip_id and cid != str(clip_id) and str(c.get("source_clip_id") or "") != str(clip_id):
            continue
        sem = get_semantic(c)
        if not sem and clip_id:
            # 指定片段但无语义块：如实返回空语义（不省略条目，调用方要能区分「没标」与「没找到」）
            out.append({"clip_id": cid, "found": False, "semantic": {}})
            continue
        if not sem:
            continue
        hl = sem.get("highlight") or {}
        q = sem.get("quality") or {}
        out.append({
            "clip_id": cid,
            "found": True,
            "semantic": sem,
            "highlight": bool(hl.get("value", False)),
            "highlight_auto": bool(hl.get("auto", False)),
            "grade": q.get("grade"),
            "weighted_score": q.get("weighted_score"),
        })
    return out

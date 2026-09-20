# -*- coding: utf-8 -*-
"""词锚定 · 重锚引擎（阶段 3）
==============================

把「剪辑片段锚在台词的第 a~b 个词」这件事，在**台词改动后**重新对齐。

为什么需要「重锚」而不是「稳定 id」
----------------------------------
改文案 = 重跑 ASR = **时间也变了**。所以**不存在内容派生出来的稳定 id** ——
任何 `hash(text)` 方案在文本变化时必然失效，而「文本变化」恰恰是要支撑的场景。
（这一段是方案里最容易想错的地方，见 `docs/_reports/2026-09-20-词锚定技术方案.md` §三 P0-2）

于是锚点存三样东西，各司其职：

| 字段 | 作用 | 什么时候失效 |
|---|---|---|
| `dialogue_id` | **快路径**：同一次分析内定位 | 重新分析后可能失效（id 是按顺序重排的） |
| `text_fingerprint` | **慢路径**：跨版本匹配（去标点的原句） | 这一句被改写才失效 |
| `word_span` | 词区间 `[from_word, to_word)` | 随 fingerprint 一起迁移 |

架构位置：`EditorModule._clips`（真相源） → **本模块（纯函数，只读快照、只出计划）** → 调用方落地

⚠️ **本模块绝不写 `_clips`**。它只产出 `ReAnchorPlan`（一份"哪些片段该移到哪"的差异清单），
由调用方在拿到用户确认后、于 `_clips_lock` 内落地。
这与磁吸让位 `reflow.ts` 的纪律一致：**计算与落地严格分离**。

设计约束
--------
* **纯函数、无 Qt、无 I/O** —— 可脱离界面与 GPU 单测
* **孤儿优先于错配** —— 匹配不确定时倾向标 `orphan`（让用户看见）而不是硬挂一个错句子
* **无台词片段绝不动** —— 没有 anchor 的片段 `range` 保持不变（空镜/BGM 段不该被挪走）
* **`fallback_range` 是保底** —— 锚点彻底失效时回落到原时间点，宁可不动也不丢片段
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

#: 相似度阈值：低于此值不认（宁可标孤儿）
DEFAULT_SIMILARITY_THRESHOLD = 0.75

#: 歧义裕度：最佳与次佳的比值差小于此值 ⇒ 判为歧义，标孤儿而非猜
AMBIGUITY_MARGIN = 0.05

#: 指纹：只保留「词字符」（字母 / 数字 / 下划线 / CJK），其余（空白与中英标点）全部丢弃。
#:
#: 为什么用「反向提取」而不是「列一堆标点去 sub」：后者要把全角/半角/引号/破折号
#: 逐个写进字符类，极易漏（而且 Python 里相邻字符串字面量会**静默拼接**，
#: 引号混用会让正则悄悄变成另一个东西）。提取 \w+ 则天然覆盖所有标点，无需枚举。
_WORD_RE = re.compile(r"\w+", re.UNICODE)


#: 时间输出精度：毫秒。与 `timeline_source.TIMECODE_PRECISION` 一致。
#:
#: 为什么要在这里规整：ASR 的词级时间是长浮点，直接透传会得到
#: `0.8999999999999999` 这种值 —— 它对时间轴无害，但会污染差异计划的可读性
#: （用户看到一串无意义的尾数），也让往返比对变难。
TIME_PRECISION = 3


def _round_ms(v: Any) -> float:
    try:
        return round(float(v), TIME_PRECISION)
    except (TypeError, ValueError):
        return 0.0


def fingerprint(text: Any) -> str:
    """把台词规整成用于**跨版本匹配**的指纹（只留词字符，统一小写）。

    注意：指纹只用于**比较**，不用于当 id —— 它随文本变化而变，
    而我们要支撑的正是文本变化。

    >>> fingerprint("你别走！")
    '你别走'
    >>> fingerprint("你、别 走？")
    '你别走'
    """
    return "".join(_WORD_RE.findall(str(text or ""))).lower()


# ── 输入适配：同时接受 DialogueSegment 对象与纯 dict（便于脱离引擎单测） ──

def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _dialogue_ref(d: Any) -> "_Dialogue":
    words_raw = _get(d, "words") or []
    words: List[Tuple[float, float]] = []
    for w in words_raw:
        try:
            words.append((float(_get(w, "start", 0.0) or 0.0),
                          float(_get(w, "end", 0.0) or 0.0)))
        except (TypeError, ValueError):
            continue
    return _Dialogue(
        id=str(_get(d, "id", "") or ""),
        text=str(_get(d, "text", "") or ""),
        start=float(_get(d, "start_time", 0.0) or 0.0),
        end=float(_get(d, "end_time", 0.0) or 0.0),
        words=words,
    )


@dataclass
class _Dialogue:
    id: str
    text: str
    start: float
    end: float
    words: List[Tuple[float, float]] = field(default_factory=list)

    @property
    def fp(self) -> str:
        return fingerprint(self.text)

    def span_range(self, from_word: int, to_word: int) -> Optional[Tuple[float, float]]:
        """词区间 → 时间区间。无词级数据时回落到整句。

        ⚠️ **区间必须完整可用，否则返回 None（判孤儿）**。

        为什么不"能取多少取多少"：若锚点说「第 0~9 个词」而新句子只剩 1 个词，
        截断后片段会盖住一个**语义完全不同**的范围，而且**看不出有问题** ——
        这是最难发现的一类错配。按本模块「孤儿优先于错配」的原则，宁可标孤儿
        让用户看见，也不静默缩水。
        """
        if not self.words:
            return (self.start, self.end)
        f = max(0, int(from_word))
        t = int(to_word)
        if t <= f:
            return None
        if t > len(self.words):
            # 请求的词区间超出新句子的词数 ⇒ 这句的词结构已实质变化
            return None
        seg = self.words[f:t]
        if not seg:
            return None
        return (_round_ms(seg[0][0]), _round_ms(seg[-1][1]))


# ── 输出结构 ──

@dataclass
class ClipShift:
    """单个片段的迁移计划。"""
    clip_id: str
    old_range: Tuple[float, float]
    new_range: Optional[Tuple[float, float]]
    reason: str          # id_hit | fingerprint_match | orphan | unchanged
    dialogue_id: str = ""
    note: str = ""


@dataclass
class ReAnchorPlan:
    shifts: List[ClipShift] = field(default_factory=list)
    matched: int = 0
    orphaned: int = 0
    unchanged: int = 0
    unmatched_new: int = 0     # 新增台词数（可提示用户「有新台词可自动入轨」）
    overlaps: List[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.shifts)

    def moved(self) -> List[ClipShift]:
        return [s for s in self.shifts if s.reason in ("id_hit", "fingerprint_match")]


def plan_reanchor(
    clips: Sequence[Dict[str, Any]],
    dialogues: Sequence[Any],
    *,
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> ReAnchorPlan:
    """计算重锚差异计划（**只读、不写 `_clips`**）。

    Args:
        clips: 片段列表（调用方应传 `EditorModule._clips_snapshot()` 的产物）
        dialogues: 新的台词序列（`DialogueSegment` 或同形 dict 均可）
        threshold: 相似度阈值，低于此值判孤儿

    Returns:
        `ReAnchorPlan` —— 差异清单与统计。**调用方需在用户确认后才落地。**
    """
    new_items = [_dialogue_ref(d) for d in (dialogues or [])]
    by_id: Dict[str, _Dialogue] = {d.id: d for d in new_items if d.id}

    plan = ReAnchorPlan()
    used_fp: Dict[str, int] = {}          # 匹配成功后占用次数（用于判别重复台词）
    matched_new: set = set()              # 用对象身份记录已命中的新台词

    for clip in (clips or []):
        meta = _get(clip, "metadata") or {}
        anchor = (meta.get("anchor") if isinstance(meta, dict) else None) or {}
        # `metadata.anchor` 是外部写入的扩展字段，可能被写坏（字符串/列表/None）。
        # 这里必须显式挡住：一个坏锚点不该让整条时间线的重锚全崩。
        if not isinstance(anchor, dict):
            anchor = {}
        clip_id = str(_get(clip, "id", "") or "")
        start = float(_get(clip, "start_time", 0.0) or 0.0)
        dur = float(_get(clip, "duration", 0.0) or 0.0)
        old_range = (_round_ms(start), _round_ms(start + dur))

        # 无锚点 ⇒ 绝不移动（空镜/BGM 段不该被挪走）
        if not anchor or str(anchor.get("kind") or "") != "dialogue":
            plan.shifts.append(ClipShift(clip_id, old_range, old_range, "unchanged",
                                         note="无锚点，保持原时间"))
            plan.unchanged += 1
            continue

        fb = anchor.get("fallback_range")
        fallback = (_round_ms(fb[0]), _round_ms(fb[1])) \
            if isinstance(fb, (list, tuple)) and len(fb) >= 2 else old_range

        from_word = int(anchor.get("from_word") or 0)
        to_word = int(anchor.get("to_word") or 0)
        old_fp = str(anchor.get("text_fingerprint") or "")
        dlg_id = str(anchor.get("dialogue_id") or "")

        target: Optional[_Dialogue] = None
        reason = ""

        # ── 快路径：id 命中且指纹一致 ──
        cand = by_id.get(dlg_id)
        if cand is not None and (not old_fp or cand.fp == old_fp):
            target, reason = cand, "id_hit"

        # ── 慢路径：按指纹跨版本匹配 ──
        if target is None and old_fp:
            target, reason = _match_by_fingerprint(
                old_fp, new_items, used_fp, threshold, fallback,
            )

        if target is None:
            plan.shifts.append(ClipShift(
                clip_id, old_range, fallback, "orphan", dialogue_id=dlg_id,
                note="未找到对应台词，已回落到原时间（原锚点保留，不丢片段）",
            ))
            plan.orphaned += 1
            continue

        rng = target.span_range(from_word, to_word)
        if rng is None:
            plan.shifts.append(ClipShift(
                clip_id, old_range, fallback, "orphan", dialogue_id=target.id,
                note=f"词区间 [{from_word},{to_word}) 在新台词中已不存在，回落原时间",
            ))
            plan.orphaned += 1
            continue

        used_fp[target.fp] = used_fp.get(target.fp, 0) + 1
        # 用对象身份而非 id 字段记录命中：dict 形态的台词可能根本没有 id
        matched_new.add(id(target))
        plan.shifts.append(ClipShift(clip_id, old_range, rng, reason,
                                     dialogue_id=target.id))
        plan.matched += 1

    plan.unmatched_new = max(0, len(new_items) - len(matched_new))
    plan.overlaps = _detect_overlaps(plan.shifts)
    return plan


def _match_by_fingerprint(
    old_fp: str,
    new_items: List[_Dialogue],
    used_fp: Dict[str, int],
    threshold: float,
    fallback: Tuple[float, float],
) -> Tuple[Optional[_Dialogue], str]:
    """指纹匹配：先精确、再模糊；**歧义时返回 None（宁可孤儿，不要错配）**。"""
    # ① 精确指纹。重复台词按「已占用次数」顺次取下一句，保持与时间轴同序。
    exact = [d for d in new_items if d.fp == old_fp]
    if exact:
        idx = min(used_fp.get(old_fp, 0), len(exact) - 1)
        return exact[idx], "fingerprint_match"

    # ② 模糊匹配：取相似度最高者，但次高若咬得太近 ⇒ 判歧义
    scored: List[Tuple[float, _Dialogue]] = []
    for d in new_items:
        if not d.fp:
            continue
        r = difflib.SequenceMatcher(None, old_fp, d.fp).ratio()
        if r >= threshold:
            scored.append((r, d))
    if not scored:
        return None, ""
    scored.sort(key=lambda x: (-x[0], x[1].start))
    best = scored[0][0]
    if len(scored) > 1 and (best - scored[1][0]) < AMBIGUITY_MARGIN:
        # 两句都像 ⇒ 不猜。错配会把片段挂到错误的台词上，比孤儿更难发现。
        return None, ""
    return scored[0][1], "fingerprint_match"


def _detect_overlaps(shifts: Sequence[ClipShift]) -> List[str]:
    """检测迁移后新增的时间重叠（只报告，不自动解决）。"""
    items = [s for s in shifts if s.new_range and s.reason in ("id_hit", "fingerprint_match")]
    items = sorted(items, key=lambda s: s.new_range[0])  # type: ignore[index]
    out: List[str] = []
    for a, b in zip(items, items[1:]):
        if b.new_range[0] < a.new_range[1] - 1e-6:  # type: ignore[index]
            out.append(
                f"{a.clip_id} 与 {b.clip_id} 迁移后重叠 "
                f"({b.new_range[0]:.3f} < {a.new_range[1]:.3f})"  # type: ignore[index]
            )
    return out


def summarize(plan: ReAnchorPlan) -> str:
    """给用户看的一句话摘要（诚实呈现孤儿数，不粉饰）。"""
    parts = [f"可重排 {plan.matched} 个片段"]
    if plan.orphaned:
        parts.append(f"{plan.orphaned} 个失去锚点（保持原时间）")
    if plan.unchanged:
        parts.append(f"{plan.unchanged} 个无锚点不动")
    if plan.unmatched_new:
        parts.append(f"{plan.unmatched_new} 句新台词未使用")
    if plan.overlaps:
        parts.append(f"{len(plan.overlaps)} 处重叠需人工确认")
    return "；".join(parts)


__all__ = [
    "DEFAULT_SIMILARITY_THRESHOLD",
    "AMBIGUITY_MARGIN",
    "TIME_PRECISION",
    "fingerprint",
    "ClipShift",
    "ReAnchorPlan",
    "plan_reanchor",
    "summarize",
]

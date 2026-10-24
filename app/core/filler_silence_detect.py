"""
B2：口播填充词 / 长静音检测 → 复用 B0 帧绑定 + B1 波纹删除

职责：
  - 从 ASR/字幕条目或句间空隙检测待删区间
  - 映射为时间线半开区间 [t_in, t_out)
  - 批量调用 edit_commands.ripple_delete_timeline_range（从右向左）

提供 `realign_subtitles_after_cleanup` 纯数据重对齐；UI 确认与列表刷新由编辑器接线层负责。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from app.core.edit_commands import RippleDeleteResult, ripple_delete_timeline_range
from app.core.text_frame_map import (
    ClipContext,
    TextFrameBinding,
    TextTimedEntry,
    Timebase,
    bind_entries_to_clip,
    bind_whisper_segments_to_clip,
    clip_context_from_dict,
    from_whisper_segments,
    normalize_timed_entry,
)

_EPS = 1e-4

# 常见中文口播填充词（纯词或整句仅含这些时删除）
DEFAULT_FILLER_WORDS: Tuple[str, ...] = (
    "呃",
    "啊",
    "嗯",
    "哦",
    "额",
    "诶",
    "唉",
    "哎",
    "哈",
    "嘛",
    "呢",
    "噢",
    "喔",
    "欸",
    "那个",
    "这个",
)

# 去掉标点后仍视为填充词的短句
_FILLER_STRIP_RE = re.compile(r"[\s，。！？、；：「」『』（）()\[\]\"'…—\-·]+")

# 句首/句尾单字填充（aggressive 模式）
_EDGE_FILLER_RE = re.compile(
    r"^(?:"
    + "|".join(re.escape(w) for w in ("呃", "啊", "嗯", "哦", "额", "诶", "唉", "哎", "噢", "喔", "欸"))
    + r")+"
)


@dataclass
class CleanupConfig:
    """检测参数。"""

    silence_min_sec: float = 0.4
    detect_fillers: bool = True
    detect_silence: bool = True
    filler_words: Tuple[str, ...] = DEFAULT_FILLER_WORDS
    aggressive_fillers: bool = False  # 句首单字填充（短剧默认关）
    fps: float = 30.0
    # 短剧/密集对白：仅删纯填充词，不删句间静音（由 UI 默认勾选控制）
    skip_inter_segment_silence: bool = False


@dataclass
class CleanupInterval:
    """一条待删时间线区间（半开）。"""

    timeline_in: float
    timeline_out: float
    kind: str  # "filler" | "silence"
    text: str = ""
    source_index: int = -1

    @property
    def duration(self) -> float:
        return max(0.0, self.timeline_out - self.timeline_in)


@dataclass
class CleanupPlan:
    """检测结果汇总。"""

    intervals: List[CleanupInterval] = field(default_factory=list)
    clip_id: str = ""
    is_dense_dialogue: bool = False  # 启发式：短句密集 → UI 需确认

    @property
    def total_duration(self) -> float:
        return sum(i.duration for i in self.intervals)

    def timeline_ranges(self) -> List[Tuple[float, float]]:
        return [(i.timeline_in, i.timeline_out) for i in self.intervals]

    def with_intervals(self, intervals: Sequence["CleanupInterval"]) -> "CleanupPlan":
        """M5：勾选子集后构造新计划（保留 clip_id / 密集对白标记）。"""
        return CleanupPlan(
            intervals=list(intervals),
            clip_id=self.clip_id,
            is_dense_dialogue=self.is_dense_dialogue,
        )


def realign_subtitles_after_cleanup(
    subtitles: Sequence[Dict[str, Any]],
    intervals: Sequence[CleanupInterval],
    *,
    eps: float = _EPS,
) -> List[Dict[str, Any]]:
    """
    去水词/波纹删之后：同步字幕时间轴（M3）。

    规则（自右向左应用每个删除区间 [t_in, t_out)）：
      - 完全在切口左侧：不动
      - 完全在切口右侧：整体左移 (t_out - t_in)
      - 与切口相交：丢弃（通常为被删的填充词字幕本身）
    """
    if not subtitles:
        return []
    remaining: List[Dict[str, Any]] = [dict(s) for s in subtitles]
    if not intervals:
        return remaining

    for iv in sorted(intervals, key=lambda x: float(x.timeline_in), reverse=True):
        t_in = float(iv.timeline_in)
        t_out = float(iv.timeline_out)
        if t_out <= t_in + eps:
            continue
        dur = t_out - t_in
        next_list: List[Dict[str, Any]] = []
        for sub in remaining:
            try:
                ss = float(sub.get("start_time", 0) or 0)
                se = float(sub.get("end_time", 0) or 0)
            except (TypeError, ValueError):
                next_list.append(sub)
                continue
            if se <= ss:
                continue
            if se <= t_in + eps:
                next_list.append(sub)
            elif ss >= t_out - eps:
                shifted = dict(sub)
                shifted["start_time"] = max(0.0, ss - dur)
                shifted["end_time"] = max(shifted["start_time"] + eps, se - dur)
                next_list.append(shifted)
            # else: overlap → drop
        remaining = next_list

    # 重排 id，避免列表显示空洞
    for i, sub in enumerate(remaining, 1):
        sub["id"] = f"subtitle_{i}"
    return remaining


def replace_subtitle_manager_entries(manager: Any, entries: Sequence[Dict[str, Any]]) -> int:
    """用重对齐结果覆盖 SubtitleManager.subtitles（保留可见字段）。"""
    if manager is None:
        return 0
    cleaned = [dict(e) for e in entries]
    manager.subtitles = cleaned
    return len(cleaned)


def _normalize_filler_text(text: str) -> str:
    return _FILLER_STRIP_RE.sub("", (text or "").strip())


def is_pure_filler_text(text: str, filler_words: Sequence[str]) -> bool:
    """整段文本是否仅为填充词。"""
    norm = _normalize_filler_text(text)
    if not norm:
        return False
    if norm in filler_words:
        return True
    # 连续重复单字填充，如「啊啊啊」
    if len(norm) <= 6 and all(ch in filler_words or ch in "啊啊嗯嗯哦哦额额" for ch in norm):
        return True
    return False


def extract_filler_spans_from_text(
    text: str,
    filler_words: Sequence[str],
    *,
    aggressive: bool = False,
) -> List[Tuple[int, int, str]]:
    """
    从混合句中提取填充词字符跨度（相对原文字符索引，不含标点调整）。

    返回 [(char_start, char_end, matched_text), ...]；仅 aggressive 时尝试句首单字。
    """
    spans: List[Tuple[int, int, str]] = []
    if not text or not aggressive:
        return spans
    m = _EDGE_FILLER_RE.match(text)
    if m and len(text) - len(m.group()) >= 2:
        spans.append((0, m.end(), m.group()))
    return spans


def detect_filler_entries(
    entries: Sequence[TextTimedEntry],
    ctx: ClipContext,
    config: CleanupConfig,
    *,
    timebase: Timebase = Timebase.SOURCE_RELATIVE,
) -> List[CleanupInterval]:
    """从 ASR/字幕条目检测纯填充词区间（经 B0 映射到 timeline）。"""
    if not config.detect_fillers or not entries:
        return []

    fillers = config.filler_words
    hits: List[CleanupInterval] = []
    bindings = bind_entries_to_clip(
        list(entries),
        ctx,
        timebase=timebase,
        clamp_to_clip=True,
    )

    for i, (entry, binding) in enumerate(zip(entries, bindings)):
        if is_pure_filler_text(entry.text, fillers):
            hits.append(
                CleanupInterval(
                    timeline_in=binding.timeline_in_sec,
                    timeline_out=binding.timeline_out_sec,
                    kind="filler",
                    text=entry.text.strip(),
                    source_index=i,
                )
            )
            continue
        if config.aggressive_fillers:
            spans = extract_filler_spans_from_text(entry.text, fillers, aggressive=True)
            if spans and entry.duration_sec > _EPS:
                # 句首填充：按字符比例估算时间（句级 ASR 无字级时间戳时的近似）
                cs, ce, matched = spans[0]
                ratio = max(0.05, min(0.5, (ce - cs) / max(1, len(entry.text))))
                rel_end = entry.start_sec + entry.duration_sec * ratio
                sub = TextTimedEntry(
                    text=matched,
                    start_sec=entry.start_sec,
                    end_sec=rel_end,
                    entry_id=f"{entry.entry_id}_filler",
                )
                sub_bindings = bind_entries_to_clip([sub], ctx, timebase=timebase, clamp_to_clip=True)
                if sub_bindings:
                    b = sub_bindings[0]
                    hits.append(
                        CleanupInterval(
                            timeline_in=b.timeline_in_sec,
                            timeline_out=b.timeline_out_sec,
                            kind="filler",
                            text=matched,
                            source_index=i,
                        )
                    )
    return hits


def detect_silence_gaps(
    entries: Sequence[TextTimedEntry],
    ctx: ClipContext,
    config: CleanupConfig,
    *,
    timebase: Timebase = Timebase.SOURCE_RELATIVE,
    clip_end_rel: Optional[float] = None,
) -> List[CleanupInterval]:
    """
    检测句间（及片头片尾）长静音。

    entries 时间与 timebase 一致；clip_end_rel 为相对 in_point 的媒体结束秒（可选）。
    """
    if not config.detect_silence or config.skip_inter_segment_silence:
        return []
    if not entries and clip_end_rel is None:
        return []

    min_gap = max(0.05, float(config.silence_min_sec))
    sorted_entries = sorted(entries, key=lambda e: e.start_sec)

    def _to_timeline(start: float, end: float) -> Tuple[float, float]:
        sub = TextTimedEntry(text="", start_sec=start, end_sec=end)
        b = bind_entries_to_clip([sub], ctx, timebase=timebase, clamp_to_clip=True)[0]
        return b.timeline_in_sec, b.timeline_out_sec

    gaps: List[CleanupInterval] = []

    # 片头静音：第一条之前
    if sorted_entries:
        head_end = sorted_entries[0].start_sec
        if head_end >= min_gap:
            t_in, t_out = _to_timeline(0.0, head_end)
            if t_out > t_in + _EPS:
                gaps.append(CleanupInterval(t_in, t_out, kind="silence", text="[片头静音]"))

    for prev, nxt in zip(sorted_entries, sorted_entries[1:]):
        gap_start = prev.end_sec
        gap_end = nxt.start_sec
        if gap_end - gap_start >= min_gap - _EPS:
            t_in, t_out = _to_timeline(gap_start, gap_end)
            if t_out > t_in + _EPS:
                gaps.append(
                    CleanupInterval(
                        t_in,
                        t_out,
                        kind="silence",
                        text=f"[静音 {gap_end - gap_start:.2f}s]",
                    )
                )

    # 片尾静音
    if clip_end_rel is not None and sorted_entries:
        tail_start = sorted_entries[-1].end_sec
        if clip_end_rel - tail_start >= min_gap - _EPS:
            t_in, t_out = _to_timeline(tail_start, clip_end_rel)
            if t_out > t_in + _EPS:
                gaps.append(CleanupInterval(t_in, t_out, kind="silence", text="[片尾静音]"))

    return gaps


def _is_dense_dialogue(entries: Sequence[TextTimedEntry]) -> bool:
    """短剧/密集对白启发式：多短句且平均时长 < 2s。"""
    if len(entries) < 8:
        return False
    durs = [e.duration_sec for e in entries if e.duration_sec > 0]
    if not durs:
        return False
    avg = sum(durs) / len(durs)
    return avg < 2.0 and len(entries) >= 12


def merge_intervals(
    intervals: Sequence[CleanupInterval],
    *,
    merge_gap_sec: float = 0.05,
) -> List[CleanupInterval]:
    """合并重叠或相邻（间隔 <= merge_gap）的区间，保留 kind 与 text。"""
    if not intervals:
        return []
    sorted_iv = sorted(intervals, key=lambda x: x.timeline_in)
    merged: List[CleanupInterval] = [sorted_iv[0]]
    for cur in sorted_iv[1:]:
        last = merged[-1]
        same_kind = last.kind == cur.kind
        if same_kind and cur.timeline_in <= last.timeline_out + merge_gap_sec:
            last = CleanupInterval(
                timeline_in=last.timeline_in,
                timeline_out=max(last.timeline_out, cur.timeline_out),
                kind=last.kind,
                text="; ".join(filter(None, [last.text, cur.text])),
                source_index=last.source_index,
            )
            merged[-1] = last
        else:
            merged.append(cur)
    return merged


def build_cleanup_plan_from_entries(
    entries: Sequence[Union[TextTimedEntry, Dict[str, Any]]],
    clip: Dict[str, Any],
    config: Optional[CleanupConfig] = None,
    *,
    timebase: Timebase = Timebase.SOURCE_RELATIVE,
    clip_end_rel: Optional[float] = None,
) -> CleanupPlan:
    """
    标准入口：条目 + clip → CleanupPlan。

    entries 可为 TextTimedEntry 或 whisper/字幕 dict。
    """
    cfg = config or CleanupConfig()
    normalized: List[TextTimedEntry] = []
    for i, raw in enumerate(entries):
        if isinstance(raw, TextTimedEntry):
            normalized.append(raw)
        else:
            e = normalize_timed_entry(raw, index=i)
            if e:
                normalized.append(e)

    ctx = clip_context_from_dict(clip, fps=cfg.fps)
    filler_hits = detect_filler_entries(normalized, ctx, cfg, timebase=timebase)
    silence_hits = detect_silence_gaps(
        normalized,
        ctx,
        cfg,
        timebase=timebase,
        clip_end_rel=clip_end_rel,
    )
    merged = merge_intervals(filler_hits + silence_hits)
    return CleanupPlan(
        intervals=merged,
        clip_id=ctx.clip_id,
        is_dense_dialogue=_is_dense_dialogue(normalized),
    )


def build_cleanup_plan_from_whisper(
    segments: Sequence[Dict[str, Any]],
    clip: Dict[str, Any],
    config: Optional[CleanupConfig] = None,
) -> CleanupPlan:
    """Whisper segments（source_relative）→ CleanupPlan。"""
    entries = from_whisper_segments(segments)
    in_p = float(clip.get("in_point", 0) or 0)
    out_p = float(clip.get("out_point", 0) or 0)
    dur = float(clip.get("duration", 0) or 0)
    if out_p > in_p + 0.05:
        clip_end_rel = out_p - in_p
    elif dur > 0:
        clip_end_rel = dur
    elif entries:
        clip_end_rel = max(e.end_sec for e in entries)
    else:
        clip_end_rel = None
    return build_cleanup_plan_from_entries(
        entries,
        clip,
        config,
        timebase=Timebase.SOURCE_RELATIVE,
        clip_end_rel=clip_end_rel,
    )


def build_cleanup_plan_from_subtitles(
    subtitle_items: Sequence[Dict[str, Any]],
    clip: Dict[str, Any],
    config: Optional[CleanupConfig] = None,
) -> CleanupPlan:
    """SubtitleManager 条目（timeline 绝对时间）→ CleanupPlan。"""
    entries: List[TextTimedEntry] = []
    for i, item in enumerate(subtitle_items):
        e = normalize_timed_entry(item, index=i)
        if e:
            entries.append(e)
    return build_cleanup_plan_from_entries(
        entries,
        clip,
        config,
        timebase=Timebase.TIMELINE,
        clip_end_rel=None,
    )


def ripple_delete_intervals(
    clips: Sequence[Dict[str, Any]],
    ranges: Sequence[Tuple[float, float]],
    *,
    track: Optional[int] = None,
) -> RippleDeleteResult:
    """
    批量波纹删除；从右向左删，避免已算好的 timeline 坐标失效。

    返回聚合 RippleDeleteResult（steps 合并为一条 compound）。
    """
    if not ranges:
        return RippleDeleteResult(False, "无可删除区间", clips=list(clips))

    working = list(clips)
    all_steps: List[Dict[str, Any]] = []
    total_deleted = 0.0
    ok_count = 0

    for t_in, t_out in sorted(ranges, key=lambda r: r[0], reverse=True):
        t_in, t_out = float(t_in), float(t_out)
        if t_out <= t_in + _EPS:
            continue
        result = ripple_delete_timeline_range(working, t_in, t_out, track=track)
        working = result.clips
        if result.steps:
            all_steps.extend(result.steps)
        if result.ok:
            ok_count += 1
            total_deleted += result.deleted_duration

    if not all_steps:
        return RippleDeleteResult(False, "未执行任何删除", clips=working)

    msg = f"已删除 {ok_count} 段，共 {total_deleted:.2f}s"
    return RippleDeleteResult(
        ok=ok_count > 0,
        message=msg,
        clips=working,
        steps=all_steps,
        deleted_duration=total_deleted,
    )


def execute_cleanup_plan(
    clips: Sequence[Dict[str, Any]],
    plan: CleanupPlan,
    *,
    track: Optional[int] = None,
) -> RippleDeleteResult:
    """CleanupPlan → B1 批量 ripple delete。"""
    return ripple_delete_intervals(clips, plan.timeline_ranges(), track=track)


def binding_to_cleanup_interval(binding: TextFrameBinding, *, kind: str = "filler") -> CleanupInterval:
    """B0 binding → CleanupInterval（供测试或单条删除）。"""
    return CleanupInterval(
        timeline_in=float(binding.timeline_in_sec),
        timeline_out=float(binding.timeline_out_sec),
        kind=kind,
        text=binding.text,
        source_index=binding.index,
    )

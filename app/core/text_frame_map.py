"""
字词/句级 ASR 与字幕 ↔ 时间线/源媒体帧级绑定（B0）

职责：纯映射层，不写 _clips，不执行 Ripple Delete（留给 B1）。

输入：带 start/end 的字词或句级条目 + fps（及可选 clip 上下文）
输出：timeline / source 的 in_sec、out_sec 与 frame_in、frame_out（半开区间）

边界策略（默认 SAFE_WORD，见 FrameBoundaryPolicy）：
  - 起点 frame_in = floor(t * fps)   → 不截断字首
  - 终点 frame_out = ceil(t * fps)   → 半开区间 [frame_in, frame_out)，末帧完整包含结束时刻
  - 极短段（frame_out <= frame_in）强制至少 1 帧，避免「零宽删除」

坐标系：
  - source_relative：相对 clip.in_point（Whisper 截取 in_point 后音频的 0 基时间）
  - timeline：时间线绝对秒
  - source_absolute：源文件绝对秒

用法:
    from app.core.text_frame_map import (
        from_whisper_segments,
        clip_context_from_dict,
        bind_entries_to_clip,
        Timebase,
    )

    entries = from_whisper_segments(raw_segments)
    ctx = clip_context_from_dict(clip_dict, fps=30.0)
    bindings = bind_entries_to_clip(entries, ctx, timebase=Timebase.SOURCE_RELATIVE)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Union


# ── 边界策略 ──────────────────────────────────────────────────


class FrameBoundaryPolicy(str, Enum):
    """
    帧边界取整策略。

    SAFE_WORD（默认，B0/B1 推荐）：
      - 起点向下取整，终点向上取整（半开区间）
      - 删除/切分时覆盖整词，避免切半字

    FLOOR_BOTH（调试/严格对齐帧头）：
      - 起终点均 floor；out 为 inclusive 语义时需自行 +1

    NEAREST（预览高亮，不推荐用于删除）：
      - 起终点 round 到最近帧
    """

    SAFE_WORD = "safe_word"
    FLOOR_BOTH = "floor_both"
    NEAREST = "nearest"


class Timebase(str, Enum):
    """输入条目 start/end 的时间基准。"""

    SOURCE_RELATIVE = "source_relative"  # 相对 clip.in_point（AI 字幕默认）
    TIMELINE = "timeline"  # 时间线绝对秒（SubtitleManager 写入后）
    SOURCE_ABSOLUTE = "source_absolute"  # 源文件绝对秒


# ── 数据结构 ──────────────────────────────────────────────────


@dataclass(frozen=True)
class TextTimedEntry:
    """归一化后的带时间戳文本条目。"""

    text: str
    start_sec: float
    end_sec: float
    entry_id: str = ""
    confidence: float = 0.0
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def duration_sec(self) -> float:
        return max(0.0, self.end_sec - self.start_sec)


@dataclass(frozen=True)
class FrameRange:
    """某一时间轴上的半开帧区间 [frame_in, frame_out)。"""

    in_sec: float
    out_sec: float
    frame_in: int
    frame_out: int  # exclusive
    fps: float
    policy: FrameBoundaryPolicy = FrameBoundaryPolicy.SAFE_WORD

    @property
    def frame_count(self) -> int:
        return max(0, self.frame_out - self.frame_in)

    @property
    def frame_out_inclusive(self) -> int:
        """含末帧的闭区间上界（便于 UI 展示）。"""
        return max(self.frame_in, self.frame_out - 1)


@dataclass(frozen=True)
class ClipContext:
    """绑定目标 clip 的最小上下文（与 EditorModule._clips 字段对齐）。"""

    clip_id: str
    start_time: float
    in_point: float
    out_point: float = 0.0
    speed: float = 1.0
    fps: float = 30.0
    path: str = ""


@dataclass(frozen=True)
class TextFrameBinding:
    """
    单条文本的 timeline + source 双坐标帧绑定。

    B1 Ripple Delete 可直接读 timeline_* 写回 _clips；
    预览/导出对齐源媒体时用 source_*。
    """

    index: int
    text: str
    entry_id: str
    confidence: float
    raw_start_sec: float
    raw_end_sec: float
    input_timebase: Timebase

    timeline_in_sec: float
    timeline_out_sec: float
    timeline_frame_in: int
    timeline_frame_out: int

    source_in_sec: float
    source_out_sec: float
    source_frame_in: int
    source_frame_out: int

    clip_id: str
    fps: float
    policy: FrameBoundaryPolicy = FrameBoundaryPolicy.SAFE_WORD

    def to_dict(self) -> Dict[str, Any]:
        """便于挂到字幕条目 meta 或 JSON 序列化。"""
        return {
            "index": self.index,
            "text": self.text,
            "entry_id": self.entry_id,
            "confidence": self.confidence,
            "input_timebase": self.input_timebase.value,
            "timeline_in_sec": self.timeline_in_sec,
            "timeline_out_sec": self.timeline_out_sec,
            "timeline_frame_in": self.timeline_frame_in,
            "timeline_frame_out": self.timeline_frame_out,
            "source_in_sec": self.source_in_sec,
            "source_out_sec": self.source_out_sec,
            "source_frame_in": self.source_frame_in,
            "source_frame_out": self.source_frame_out,
            "clip_id": self.clip_id,
            "fps": self.fps,
            "policy": self.policy.value,
        }


# ── 帧 ↔ 秒 纯函数 ───────────────────────────────────────────


def _clamp_fps(fps: float) -> float:
    return max(1.0, float(fps or 30.0))


def frame_in_from_sec(
    sec: float,
    fps: float,
    policy: FrameBoundaryPolicy = FrameBoundaryPolicy.SAFE_WORD,
) -> int:
    """秒 → 起始帧号（含该秒所在帧）。"""
    fps = _clamp_fps(fps)
    t = max(0.0, float(sec))
    if policy == FrameBoundaryPolicy.NEAREST:
        return int(round(t * fps))
    # SAFE_WORD / FLOOR_BOTH：起点均 floor，避免切半字
    return int(math.floor(t * fps + 1e-9))


def frame_out_exclusive_from_sec(
    sec: float,
    fps: float,
    policy: FrameBoundaryPolicy = FrameBoundaryPolicy.SAFE_WORD,
) -> int:
    """秒 → 半开区间上界帧号（不含）。"""
    fps = _clamp_fps(fps)
    t = max(0.0, float(sec))
    if policy == FrameBoundaryPolicy.FLOOR_BOTH:
        fi = int(math.floor(t * fps + 1e-9))
        return fi + 1
    if policy == FrameBoundaryPolicy.NEAREST:
        return int(round(t * fps)) + 1
    # SAFE_WORD：终点 ceil，完整包含结束时刻所在帧
    return int(math.ceil(t * fps - 1e-9))


def frame_to_sec(frame: int, fps: float) -> float:
    """帧号 → 该帧起始时刻（秒）。"""
    fps = _clamp_fps(fps)
    return max(0, int(frame)) / fps


def sec_range_from_frames(
    frame_in: int,
    frame_out: int,
    fps: float,
) -> tuple[float, float]:
    """半开帧区间 → (in_sec, out_sec)。"""
    fps = _clamp_fps(fps)
    fi = max(0, int(frame_in))
    fo = max(fi + 1, int(frame_out))
    return frame_to_sec(fi, fps), frame_to_sec(fo, fps)


def map_sec_range_to_frames(
    start_sec: float,
    end_sec: float,
    fps: float,
    policy: FrameBoundaryPolicy = FrameBoundaryPolicy.SAFE_WORD,
) -> FrameRange:
    """
    将 [start_sec, end_sec] 映射为半开帧区间。

    保证至少 1 帧宽，避免 ASR 零时长或倒序时间戳。
    """
    fps = _clamp_fps(fps)
    s = float(start_sec)
    e = float(end_sec)
    if e < s:
        s, e = e, s
    fi = frame_in_from_sec(s, fps, policy)
    fo = frame_out_exclusive_from_sec(e, fps, policy)
    if fo <= fi:
        fo = fi + 1
    in_sec, out_sec = sec_range_from_frames(fi, fo, fps)
    return FrameRange(
        in_sec=in_sec,
        out_sec=out_sec,
        frame_in=fi,
        frame_out=fo,
        fps=fps,
        policy=policy,
    )


# ── clip 时间换算 ─────────────────────────────────────────────


def clip_context_from_dict(clip: Mapping[str, Any], fps: float = 30.0) -> ClipContext:
    """从 EditorModule._clips 条目构造 ClipContext。"""
    in_p = float(clip.get("in_point", 0) or 0)
    out_p = float(clip.get("out_point", 0) or 0)
    return ClipContext(
        clip_id=str(clip.get("id") or clip.get("clip_id") or ""),
        start_time=float(clip.get("start_time", 0) or 0),
        in_point=in_p,
        out_point=out_p if out_p > in_p else 0.0,
        speed=max(0.05, float(clip.get("speed", 1.0) or 1.0)),
        fps=_clamp_fps(fps),
        path=str(clip.get("path") or ""),
    )


def source_relative_to_source_abs(rel_sec: float, ctx: ClipContext) -> float:
    return ctx.in_point + float(rel_sec)


def source_abs_to_timeline(source_sec: float, ctx: ClipContext) -> float:
    return ctx.start_time + (float(source_sec) - ctx.in_point) / ctx.speed


def timeline_to_source_abs(timeline_sec: float, ctx: ClipContext) -> float:
    return ctx.in_point + (float(timeline_sec) - ctx.start_time) * ctx.speed


def normalize_to_timeline_source(
    start_sec: float,
    end_sec: float,
    ctx: ClipContext,
    timebase: Timebase,
) -> tuple[float, float, float, float]:
    """
    将输入时间归一化为 (timeline_in, timeline_out, source_in, source_out)。
    """
    s, e = float(start_sec), float(end_sec)
    if e < s:
        s, e = e, s

    if timebase == Timebase.SOURCE_RELATIVE:
        src_in = source_relative_to_source_abs(s, ctx)
        src_out = source_relative_to_source_abs(e, ctx)
        tl_in = source_abs_to_timeline(src_in, ctx)
        tl_out = source_abs_to_timeline(src_out, ctx)
    elif timebase == Timebase.TIMELINE:
        tl_in, tl_out = s, e
        src_in = timeline_to_source_abs(tl_in, ctx)
        src_out = timeline_to_source_abs(tl_out, ctx)
    elif timebase == Timebase.SOURCE_ABSOLUTE:
        src_in, src_out = s, e
        tl_in = source_abs_to_timeline(src_in, ctx)
        tl_out = source_abs_to_timeline(src_out, ctx)
    else:
        raise ValueError(f"未知 timebase: {timebase}")

    return tl_in, tl_out, src_in, src_out


def _clamp_to_clip_source(src_in: float, src_out: float, ctx: ClipContext) -> tuple[float, float]:
    """可选：将源时间钳在 clip 有效 in/out 内。"""
    lo = ctx.in_point
    hi = ctx.out_point if ctx.out_point > ctx.in_point + 1e-6 else float("inf")
    return max(lo, src_in), min(hi, src_out)


# ── 输入适配 ──────────────────────────────────────────────────


def _pick_time(d: Mapping[str, Any], start_keys: Sequence[str], end_keys: Sequence[str]) -> tuple[float, float]:
    start = 0.0
    end = 0.0
    for k in start_keys:
        if k in d and d[k] is not None:
            start = float(d[k])
            break
    for k in end_keys:
        if k in d and d[k] is not None:
            end = float(d[k])
            break
    return start, end


def normalize_timed_entry(
    data: Union[TextTimedEntry, Mapping[str, Any], Any],
    *,
    index: int = 0,
) -> Optional[TextTimedEntry]:
    """Whisper segment / SubtitleManager 条目 / SubtitleSegment 对象 → TextTimedEntry。"""
    if isinstance(data, TextTimedEntry):
        return data

    if isinstance(data, Mapping):
        text = str(data.get("text") or "").strip()
        if not text:
            return None
        s, e = _pick_time(data, ("start", "start_time", "start_sec"), ("end", "end_time", "end_sec"))
        return TextTimedEntry(
            text=text,
            start_sec=s,
            end_sec=e,
            entry_id=str(data.get("id") or data.get("entry_id") or f"entry_{index}"),
            confidence=float(data.get("confidence") or data.get("avg_logprob") or 0.0),
            meta=dict(data.get("meta") or {}),
        )

    text = str(getattr(data, "text", "") or "").strip()
    if not text:
        return None
    s, e = _pick_time(
        {"start": getattr(data, "start_time", None), "end": getattr(data, "end_time", None)},
        ("start",),
        ("end",),
    )
    return TextTimedEntry(
        text=text,
        start_sec=s,
        end_sec=e,
        entry_id=str(getattr(data, "id", None) or f"entry_{index}"),
        confidence=float(getattr(data, "confidence", 0) or 0),
    )


def from_whisper_segments(segments: Iterable[Mapping[str, Any]]) -> List[TextTimedEntry]:
    """whisper_asr.transcribe 返回值 → TextTimedEntry 列表。"""
    out: List[TextTimedEntry] = []
    for i, seg in enumerate(segments):
        entry = normalize_timed_entry(seg, index=i)
        if entry:
            out.append(entry)
    return out


def from_subtitle_items(items: Iterable[Union[Mapping[str, Any], Any]]) -> List[TextTimedEntry]:
    """SubtitleManager 条目（timeline 绝对时间）→ TextTimedEntry。"""
    out: List[TextTimedEntry] = []
    for i, item in enumerate(items):
        entry = normalize_timed_entry(item, index=i)
        if entry:
            out.append(entry)
    return out


# ── 核心 API ──────────────────────────────────────────────────


def map_entry_to_frames(
    entry: TextTimedEntry,
    fps: float,
    policy: FrameBoundaryPolicy = FrameBoundaryPolicy.SAFE_WORD,
) -> FrameRange:
    """单条目 → 帧区间（输入时间原样映射，不含 clip 偏移）。"""
    return map_sec_range_to_frames(entry.start_sec, entry.end_sec, fps, policy)


def map_entries_to_frames(
    entries: Sequence[TextTimedEntry],
    fps: float,
    policy: FrameBoundaryPolicy = FrameBoundaryPolicy.SAFE_WORD,
) -> List[FrameRange]:
    return [map_entry_to_frames(e, fps, policy) for e in entries]


def bind_entry_to_clip(
    entry: TextTimedEntry,
    ctx: ClipContext,
    *,
    index: int = 0,
    timebase: Timebase = Timebase.SOURCE_RELATIVE,
    policy: FrameBoundaryPolicy = FrameBoundaryPolicy.SAFE_WORD,
    clamp_to_clip: bool = True,
) -> TextFrameBinding:
    """单条目绑定到 clip，输出 timeline + source 双坐标帧区间。"""
    fps = _clamp_fps(ctx.fps)
    tl_in, tl_out, src_in, src_out = normalize_to_timeline_source(
        entry.start_sec, entry.end_sec, ctx, timebase
    )
    if clamp_to_clip and ctx.out_point > ctx.in_point:
        src_in, src_out = _clamp_to_clip_source(src_in, src_out, ctx)
        tl_in = source_abs_to_timeline(src_in, ctx)
        tl_out = source_abs_to_timeline(src_out, ctx)

    tl_range = map_sec_range_to_frames(tl_in, tl_out, fps, policy)
    src_range = map_sec_range_to_frames(src_in, src_out, fps, policy)

    return TextFrameBinding(
        index=index,
        text=entry.text,
        entry_id=entry.entry_id,
        confidence=entry.confidence,
        raw_start_sec=entry.start_sec,
        raw_end_sec=entry.end_sec,
        input_timebase=timebase,
        timeline_in_sec=tl_range.in_sec,
        timeline_out_sec=tl_range.out_sec,
        timeline_frame_in=tl_range.frame_in,
        timeline_frame_out=tl_range.frame_out,
        source_in_sec=src_range.in_sec,
        source_out_sec=src_range.out_sec,
        source_frame_in=src_range.frame_in,
        source_frame_out=src_range.frame_out,
        clip_id=ctx.clip_id,
        fps=fps,
        policy=policy,
    )


def bind_entries_to_clip(
    entries: Sequence[TextTimedEntry],
    ctx: ClipContext,
    *,
    timebase: Timebase = Timebase.SOURCE_RELATIVE,
    policy: FrameBoundaryPolicy = FrameBoundaryPolicy.SAFE_WORD,
    clamp_to_clip: bool = True,
) -> List[TextFrameBinding]:
    """批量绑定；AI 字幕 / Whisper 结果接 B1 前的标准入口。"""
    return [
        bind_entry_to_clip(
            e,
            ctx,
            index=i,
            timebase=timebase,
            policy=policy,
            clamp_to_clip=clamp_to_clip,
        )
        for i, e in enumerate(entries)
    ]


def bind_whisper_segments_to_clip(
    segments: Iterable[Mapping[str, Any]],
    clip: Mapping[str, Any],
    fps: float = 30.0,
    **kwargs: Any,
) -> List[TextFrameBinding]:
    """
    便捷入口：whisper_asr segments + clip dict → bindings。

    kwargs 转发至 bind_entries_to_clip（timebase 默认 SOURCE_RELATIVE）。
    """
    ctx = clip_context_from_dict(clip, fps=fps)
    entries = from_whisper_segments(segments)
    return bind_entries_to_clip(entries, ctx, **kwargs)


def bind_subtitle_items_to_clip(
    subtitle_items: Iterable[Union[Mapping[str, Any], Any]],
    clip: Mapping[str, Any],
    fps: float = 30.0,
    **kwargs: Any,
) -> List[TextFrameBinding]:
    """
    SubtitleManager 已写入时间线绝对时间后的绑定入口。

    timebase 默认 TIMELINE。
    """
    ctx = clip_context_from_dict(clip, fps=fps)
    entries = from_subtitle_items(subtitle_items)
    if "timebase" not in kwargs:
        kwargs = {**kwargs, "timebase": Timebase.TIMELINE}
    return bind_entries_to_clip(entries, ctx, **kwargs)


def enrich_subtitle_dicts_with_bindings(
    subtitle_items: Sequence[Mapping[str, Any]],
    bindings: Sequence[TextFrameBinding],
) -> List[Dict[str, Any]]:
    """
    将帧绑定挂到字幕 dict 的 frame_binding 字段（浅拷贝，不改 SubtitleManager 内部列表时可先用此函数）。

    B1 执行器可读取 item["frame_binding"]["timeline_frame_in/out"]。
    """
    enriched: List[Dict[str, Any]] = []
    bind_by_id = {b.entry_id: b for b in bindings if b.entry_id}
    for i, item in enumerate(subtitle_items):
        row = dict(item)
        b = bind_by_id.get(str(item.get("id") or "")) or (bindings[i] if i < len(bindings) else None)
        if b is not None:
            row["frame_binding"] = b.to_dict()
        enriched.append(row)
    return enriched

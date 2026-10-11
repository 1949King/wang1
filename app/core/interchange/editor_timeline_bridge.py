"""编辑器 ``_clips`` ↔ ``timeline_dsl.Timeline`` 桥接
====================================================
编辑器真相源是 ``EditorModule._clips``（dict 列表），而互操作导出（OTIO/EDL/FCPXML）
需要 ``timeline_dsl.Timeline``。本模块只做**纯数据映射**：

* 不 import Qt、不依赖编辑器实例 —— 便于单测，也可在子进程里复用；
* 字段映射逐项显式，未识别的附加字段原样收进 ``metadata``，往返不丢。

字段对照（编辑器 clip dict → DSL Clip）
--------------------------------------
``path``        → ``source``
``start_time``  → ``range.start``（时间线位置）
``in_point`` / ``out_point`` → ``source_range``（素材裁剪区间）
``track``       → 分组为 ``Track``（同 track 序号归一轨）
``volume``      → ``volume``
``transform``   → ``ClipTransform``（x/y/scale/opacity/rotation/anchor）
``transition``  → ``Timeline.transitions``（与前一片段成对）
其他            → ``metadata`` 原样保留
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from app.core.timeline_dsl import (
    BlendMode,
    Clip,
    ClipTransform,
    ClipType,
    Resolution,
    TimeRange,
    Timeline,
    TimelineSettings,
    Track,
    TrackType,
    Transition,
)

logger = logging.getLogger("AI短剧编辑器.interchange.bridge")

_AUDIO_EXTS = (".mp3", ".wav", ".aac", ".m4a", ".flac", ".ogg", ".aiff", ".wma", ".opus")
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".tif", ".tiff")


# ============================================================
# 小工具
# ============================================================

def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def is_audio_clip(clip: Any) -> bool:
    """判断编辑器片段 dict 是否为音频（类型标记优先，其次扩展名）。"""
    if not isinstance(clip, dict):
        return False
    if str(clip.get("type", "")).lower() == "audio":
        return True
    return str(clip.get("path") or "").lower().endswith(_AUDIO_EXTS)


def is_image_clip(clip: Any) -> bool:
    if not isinstance(clip, dict):
        return False
    if str(clip.get("type", "")).lower() in ("image", "picture", "still"):
        return True
    return str(clip.get("path") or "").lower().endswith(_IMAGE_EXTS)


def _clip_duration(clip: Dict[str, Any]) -> float:
    """片段在时间线上的时长（优先 out-in，其次 duration 字段）。"""
    in_p = _f(clip.get("in_point", 0.0))
    out_p = _f(clip.get("out_point", 0.0))
    dur = out_p - in_p
    if dur <= 1e-9:
        dur = _f(clip.get("duration", 0.0))
    return max(0.0, dur)


def _clip_range(clip: Dict[str, Any]) -> TimeRange:
    start = _f(clip.get("start_time", 0.0))
    return TimeRange(start=start, end=start + _clip_duration(clip))


def _clip_source_range(clip: Dict[str, Any]) -> TimeRange:
    in_p = _f(clip.get("in_point", 0.0))
    out_p = _f(clip.get("out_point", 0.0))
    if out_p <= in_p:
        out_p = in_p + _f(clip.get("duration", 0.0))
    return TimeRange(start=in_p, end=max(in_p, out_p))


def _clip_transform(clip: Dict[str, Any]) -> ClipTransform:
    tf = clip.get("transform") if isinstance(clip.get("transform"), dict) else {}
    scale = _f(tf.get("scale", clip.get("pip_scale", 1.0)), 1.0)
    return ClipTransform(
        x=_f(tf.get("x", clip.get("pip_x", 0.0))),
        y=_f(tf.get("y", clip.get("pip_y", 0.0))),
        scale_x=scale,
        scale_y=scale,
        rotation=_f(tf.get("rotation", clip.get("rotation", 0.0))),
        opacity=_f(tf.get("opacity", clip.get("opacity", 1.0)), 1.0),
        anchor_x=_f(tf.get("anchor_x", 0.5), 0.5),
        anchor_y=_f(tf.get("anchor_y", 0.5), 0.5),
    )


def _clip_blend(clip: Dict[str, Any]) -> BlendMode:
    tf = clip.get("transform") if isinstance(clip.get("transform"), dict) else {}
    raw = clip.get("blend_mode") or clip.get("blend") or tf.get("blend")
    try:
        return BlendMode(str(raw))
    except Exception:
        return BlendMode.NORMAL


#: 已显式映射的键；其余原样收进 metadata。
#: 注意 ``transition`` / ``transitions`` **刻意不列入** —— 它们不落进 Clip 字段，
#: 而是留给 ``_collect_transitions`` 从 ``metadata["editor"]`` 里读取并配对成 DSL 转场。
_MAPPED_KEYS = frozenset({
    "id", "name", "type", "path", "start_time", "in_point", "out_point", "duration",
    "track", "volume", "transform", "opacity", "rotation", "pip_x", "pip_y", "pip_scale",
    "blend_mode", "blend", "muted", "locked", "visible",
})


def _clip_of(c: Dict[str, Any]) -> Clip:
    """编辑器 clip dict → DSL Clip。"""
    clip_id = str(c.get("id") or f"clip_{abs(hash(str(c.get('path', '')))) % 10**8}")
    audio = is_audio_clip(c)
    ctype = ClipType.AUDIO if audio else (ClipType.IMAGE if is_image_clip(c) else ClipType.VIDEO)
    extra = {k: v for k, v in c.items() if k not in _MAPPED_KEYS}
    return Clip(
        id=clip_id,
        name=str(c.get("name") or os.path.basename(str(c.get("path") or "")) or clip_id),
        type=ctype,
        source=str(c.get("path") or ""),
        range=_clip_range(c),
        source_range=_clip_source_range(c),
        transform=_clip_transform(c),
        blend_mode=_clip_blend(c),
        volume=_f(c.get("volume", 1.0), 1.0),
        effects=[str(e) for e in (c.get("effects") or []) if e],
        locked=bool(c.get("locked", False)),
        visible=bool(c.get("visible", True)),
        muted=bool(c.get("muted", False)),
        color=str(c.get("color") or ""),
        notes=str(c.get("notes") or ""),
        metadata={"editor": dict(extra)} if extra else {},
    )


# ============================================================
# clips → Timeline
# ============================================================

def clips_to_timeline(
    clips: List[Dict[str, Any]],
    *,
    name: str = "",
    fps: float = 30.0,
    width: int = 1920,
    height: int = 1080,
    sample_rate: int = 44100,
    track_types: Optional[Dict[int, str]] = None,
    duration: float = 0.0,
) -> Timeline:
    """编辑器 ``_clips`` → DSL Timeline（按 ``track`` 序号归一轨）。"""
    items = [c for c in (clips or []) if isinstance(c, dict)]
    groups: Dict[int, List[Dict[str, Any]]] = {}
    for c in items:
        groups.setdefault(int(_f(c.get("track", 0.0))), []).append(c)

    tracks: List[Track] = []
    for idx in sorted(groups):
        members = groups[idx]
        declared = (track_types or {}).get(idx)
        if declared:
            try:
                ttype = TrackType(str(declared))
            except ValueError:
                ttype = TrackType.VIDEO
        else:
            ttype = TrackType.AUDIO if all(is_audio_clip(c) for c in members) else TrackType.VIDEO
        label = "音频" if ttype == TrackType.AUDIO else "视频"
        track = Track(
            id=f"track_{ttype.value}_{idx}",
            name=f"{label}轨道 {idx + 1}",
            type=ttype,
            height=50 if ttype == TrackType.AUDIO else 80,
        )
        for c in sorted(members, key=lambda x: _f(x.get("start_time", 0.0))):
            track.add_clip(_clip_of(c))
        tracks.append(track)

    transitions = _collect_transitions(tracks)
    total = duration or max((t.total_duration for t in tracks), default=0.0)
    tl = Timeline(
        id=f"tl_{abs(hash(tuple(str(c.get('id')) for c in items))) % 10**10}",
        name=name or "拾光剪影时间线",
        settings=TimelineSettings(
            resolution=Resolution(width=int(width or 1920), height=int(height or 1080)),
            fps=float(fps or 30.0),
            sample_rate=int(sample_rate or 44100),
            duration=float(total),
        ),
        tracks=tracks,
        transitions=transitions,
    )
    return tl


def _collect_transitions(tracks: List[Track]) -> List[Transition]:
    """按各视频轨时间顺序，把片段上的 transition 与前一片段配对。"""
    out: List[Transition] = []
    for track in tracks:
        clips = sorted(track.clips, key=lambda c: c.range.start)
        for i, clip in enumerate(clips):
            if i == 0:
                continue  # 首片无「前段」可配
            editor_meta = clip.metadata.get("editor") or {}
            if not isinstance(editor_meta, dict):
                editor_meta = {}
            one = editor_meta.get("transition")  # 当前转场（权威）
            trans_list = editor_meta.get("transitions")  # 历史列表（回退）
            candidates = [one] if isinstance(one, dict) else (
                trans_list if isinstance(trans_list, list) else []
            )
            for t in candidates:
                if not isinstance(t, dict):
                    continue
                try:
                    out.append(Transition(
                        id=f"trans_{clips[i - 1].id}_{clip.id}",
                        from_clip_id=clips[i - 1].id,
                        to_clip_id=clip.id,
                        type=str(t.get("type") or "dissolve"),
                        duration=max(0.0, _f(t.get("duration", 0.5), 0.5)),
                        params={
                            "plugin_id": t.get("plugin_id"),
                            "position": t.get("position"),
                            "curve": t.get("curve"),
                        },
                    ))
                except Exception as exc:  # pragma: no cover - 防御
                    logger.debug("转场映射失败: %s", exc)
    return out


# ============================================================
# Timeline → clips（回灌编辑器）
# ============================================================

def timeline_to_clips(timeline: Timeline) -> List[Dict[str, Any]]:
    """DSL Timeline → 编辑器 ``_clips`` dict 列表。"""
    out: List[Dict[str, Any]] = []
    for ti, track in enumerate(timeline.tracks):
        for clip in sorted(track.clips, key=lambda c: c.range.start):
            tf = clip.transform
            item: Dict[str, Any] = {
                "id": clip.id,
                "name": clip.name,
                "type": "audio" if clip.type == ClipType.AUDIO else "video",
                "path": clip.source,
                "track": ti,
                "start_time": float(clip.range.start),
                "in_point": float(clip.source_range.start),
                "out_point": float(clip.source_range.end),
                "duration": float(clip.range.duration),
                "volume": float(clip.volume),
                "opacity": float(tf.opacity),
                "rotation": float(tf.rotation),
                "pip_x": float(tf.x),
                "pip_y": float(tf.y),
                "pip_scale": float(tf.scale_x),
                "transform": {
                    "x": float(tf.x), "y": float(tf.y),
                    "scale": float(tf.scale_x), "opacity": float(tf.opacity),
                    "rotation": float(tf.rotation),
                    "anchor_x": float(tf.anchor_x), "anchor_y": float(tf.anchor_y),
                },
                "blend_mode": clip.blend_mode.value,
                "muted": bool(clip.muted),
                "visible": bool(clip.visible),
                "locked": bool(clip.locked),
                "effects": list(clip.effects or []),
            }
            for k, v in (clip.metadata.get("editor") or {}).items():
                if k in ("transition", "transitions"):
                    continue  # 转场统一由 timeline.transitions 重建，避免与 extra 重复
                item.setdefault(k, v)
            out.append(item)

    # 转场回灌到 to_clip
    by_id = {c["id"]: c for c in out}
    for t in timeline.transitions:
        target = by_id.get(t.to_clip_id)
        if target is None:
            continue
        rec = {
            "type": t.type,
            "plugin_id": (t.params or {}).get("plugin_id") or t.type,
            "duration": float(t.duration),
            "position": (t.params or {}).get("position") or "end",
            "curve": (t.params or {}).get("curve") or "线性",
        }
        history = target.setdefault("transitions", [])
        if rec not in history:
            history.append(rec)
        target.setdefault("transition", rec)
    return out


# ============================================================
# 面向编辑器的便捷入口（惰性 import，避免 Qt 进程 import otio）
# ============================================================

def export_editor_timeline(
    clips: List[Dict[str, Any]],
    path: str,
    adapter: Optional[str] = None,
    **kwargs: Any,
) -> str:
    """把编辑器 ``_clips`` 直接导出为 OTIO / EDL / FCPXML。

    真正的 opentimelineio 读写发生在独立子进程（见 ``otio_adapter``），
    本进程（Qt GUI）绝不 import opentimelineio。
    """
    from app.core.interchange import otio_adapter

    timeline = clips_to_timeline(clips, **kwargs)
    return otio_adapter.export_otio(timeline, path, adapter=adapter)


def import_timeline_to_clips(path: str) -> List[Dict[str, Any]]:
    """从 OTIO / EDL / FCPXML 读入并转换为可回灌编辑器的 clip dict 列表。

    显式按扩展名指定适配器（``.fcpxml`` 不是 OTIO 注册扩展名，自动识别会失败）。
    """
    from app.core.interchange import otio_adapter

    return timeline_to_clips(otio_adapter.import_otio(path, adapter=adapter_for_path(path)))


#: 扩展名 → OTIO 适配器名
EXT_TO_ADAPTER: Dict[str, str] = {
    ".otio": "otio_json",
    ".edl": "cmx_3600",
    ".fcpxml": "fcp_xml",
    ".xml": "fcp_xml",
    ".otioz": "otioz",
    ".otiod": "otiod",
}


def _ext_of(path: str) -> str:
    """取小写扩展名；对「裸扩展名」输入（如 ``".fcpxml"``）也能正确返回。

    ``os.path.splitext(".fcpxml")`` 会把整个串当成无扩展名的隐藏文件名返回 ``''``，
    故先做一次裸扩展名特判。
    """
    s = str(path or "").lower()
    if s.startswith(".") and s.count(".") == 1:
        return s
    return os.path.splitext(s)[1]


def adapter_for_path(path: str) -> Optional[str]:
    """按扩展名推断适配器；未知返回 None（交给 OTIO 自动判断）。"""
    return EXT_TO_ADAPTER.get(_ext_of(path))


def is_timeline_extension(path: str) -> bool:
    return _ext_of(path) in EXT_TO_ADAPTER


def timeline_export_filters() -> str:
    """QFileDialog 用过滤器字符串（含全部时间线互操作格式）。"""
    return (
        "时间线互操作 (*.otio *.edl *.fcpxml *.otiod *.otioz);;"
        "OpenTimelineIO (*.otio);;"
        "EDL/CMX3600 (*.edl);;"
        "FCPXML (*.fcpxml *.xml);;"
        "所有文件 (*.*)"
    )


def roundtrip_editor_clips(clips: List[Dict[str, Any]]) -> Tuple[bool, str]:
    """自检：编辑器 clips → Timeline → OTIO 往返 → clips，关键字段守恒。"""
    from app.core.interchange import otio_adapter

    tl = clips_to_timeline(clips)
    a = timeline_to_clips(tl)
    if not otio_adapter.roundtrip_ok(tl):
        return False, "OTIO 轨道/片段数不守恒"
    b = timeline_to_clips(clips_to_timeline(a))
    keys = ("id", "start_time", "in_point", "out_point")
    ka = {tuple(round(c[k], 3) if isinstance(c[k], float) else c[k] for k in keys) for c in a}
    kb = {tuple(round(c[k], 3) if isinstance(c[k], float) else c[k] for k in keys) for c in b}
    if ka != kb:
        return False, f"二次往返不一致：{ka ^ kb}"
    return True, f"OK（{len(a)} 片段）"

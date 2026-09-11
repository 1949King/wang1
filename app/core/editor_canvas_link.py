# -*- coding: utf-8 -*-
"""剪辑 ↔ 画布 round-trip 字段（不换 ``EditorModule._clips`` 真相源）。

画布入轨时带 ``canvas_node_id``；剪辑回推 outbox 时带 ``clip_id`` / 入出点。
AI 只出建议，确认后才 ``push_editor_to_canvas``。
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, MutableMapping, Sequence

LINK_KEYS = ("canvas_node_id", "canvas_kind", "canvas_title")


def extra_from_material_payload(data: Any) -> Dict[str, str]:
    """从 MATERIAL_TO_TIMELINE / ingest 载荷抽出可盖到 clip 上的字段。"""
    if not isinstance(data, Mapping):
        return {}
    extra: Dict[str, str] = {}
    nid = data.get("canvas_node_id") or data.get("node_id")
    if nid:
        extra["canvas_node_id"] = str(nid)
    kind = data.get("canvas_kind") or data.get("kind")
    if kind:
        extra["canvas_kind"] = str(kind)
    title = data.get("title")
    if title:
        extra["canvas_title"] = str(title)
    return extra


def stamp_clip(clip: MutableMapping[str, Any], extra: Mapping[str, Any]) -> None:
    """就地盖 round-trip 字段；空值不覆盖已有。"""
    if not extra:
        return
    for key in LINK_KEYS:
        val = extra.get(key)
        if val:
            clip[key] = val
    title = extra.get("canvas_title")
    if title and not clip.get("name"):
        clip["name"] = title


def outbox_fields_from_clip(clip: Mapping[str, Any]) -> Dict[str, Any]:
    """剪辑 → 画布 outbox 附加身份（可供画布自动落源节点）。"""
    if not isinstance(clip, Mapping):
        return {}
    fields: Dict[str, Any] = {}
    cid = clip.get("id")
    if cid:
        fields["clip_id"] = str(cid)
    nid = clip.get("canvas_node_id")
    if nid:
        fields["canvas_node_id"] = str(nid)
    kind = clip.get("canvas_kind") or clip.get("type")
    if kind:
        fields["kind"] = str(kind)
    for key in ("in_point", "out_point", "start_time", "duration"):
        if clip.get(key) is None:
            continue
        try:
            fields[key] = float(clip.get(key))
        except (TypeError, ValueError):
            continue
    return fields


def public_clip_row(clip: Mapping[str, Any], index: int) -> Dict[str, Any]:
    """时间线快照里给画布 / Agent 看的一行（不含大文件）。"""
    path = str(clip.get("path") or clip.get("file_path") or "")
    name = str(clip.get("name") or "")
    if not name and path:
        name = path.replace("\\", "/").rsplit("/", 1)[-1]
    start = float(clip.get("start_time") or 0)
    duration = float(clip.get("duration") or 0)
    return {
        "clip_index": index,
        "id": clip.get("id"),
        "name": name,
        "path": path,
        "type": clip.get("type") or "video",
        "track": clip.get("track", 0),
        "start_time": start,
        "duration": duration,
        "end_time": start + duration,
        "in_point": clip.get("in_point", 0),
        "out_point": clip.get("out_point"),
        "canvas_node_id": clip.get("canvas_node_id") or "",
        "canvas_kind": clip.get("canvas_kind") or "",
    }


def suggest_canvas_roundtrip(ctx: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """只读建议：无关联的视频片可送到画布；已关联的可回写入出点；空隙提示补镜。

    不写 ``_clips``。音频轨默认跳过（避免联动音轨双发）。
    """
    suggestions: List[Dict[str, Any]] = []
    clips = ctx.get("clips") or []
    if not isinstance(clips, Sequence):
        return suggestions
    for c in clips:
        if not isinstance(c, Mapping):
            continue
        if str(c.get("type") or "video") == "audio":
            continue
        path = str(c.get("path") or "")
        name = str(c.get("name") or "未命名")
        cid = c.get("id") or c.get("clip_id")
        nid = str(c.get("canvas_node_id") or "")
        if nid:
            suggestions.append(
                {
                    "action": "refresh_canvas",
                    "clip_id": cid,
                    "canvas_node_id": nid,
                    "path": path,
                    "title": name,
                    "in_point": c.get("in_point"),
                    "out_point": c.get("out_point"),
                    "duration": c.get("duration"),
                    "label": f"回写画布：{name}",
                    "description": "同步入出点到已关联节点（不重新复制文件）",
                }
            )
            continue
        if not path:
            continue
        suggestions.append(
            {
                "action": "send_to_canvas",
                "clip_id": cid,
                "path": path,
                "title": name,
                "in_point": c.get("in_point"),
                "out_point": c.get("out_point"),
                "duration": c.get("duration"),
                "label": f"送到画布做变体：{name}",
                "description": "落成源文件节点，可再生成 / 数字人 / 入轨",
            }
        )
    for gap in list(ctx.get("gaps") or [])[:5]:
        if not isinstance(gap, Mapping):
            continue
        t_in = gap.get("t_in")
        t_out = gap.get("t_out")
        if t_in is None or t_out is None:
            continue
        suggestions.append(
            {
                "action": "info",
                "label": f"时间线空隙 {float(t_in):.1f}–{float(t_out):.1f}s",
                "description": "可在画布补镜后入轨填空",
                "t_in": t_in,
                "t_out": t_out,
            }
        )
    return suggestions


def guess_outbox_media_type(ext: str, kind: str = "") -> str:
    e = (ext or "").lower()
    k = (kind or "").lower()
    if k in ("audio", "music") or e in (".mp3", ".wav", ".m4a", ".aac", ".flac"):
        return "audio"
    if k in ("image", "shot", "director", "panorama") or e in (
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".bmp",
        ".gif",
    ):
        return "image"
    return "video"

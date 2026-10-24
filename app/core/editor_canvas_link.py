# -*- coding: utf-8 -*-
"""剪辑 ↔ 画布 round-trip 字段（不换 ``EditorModule._clips`` 真相源）。

画布入轨时带 ``canvas_node_id``；剪辑回推 outbox 时带 ``clip_id`` / 入出点。
AI 只出建议，确认后才 ``push_editor_to_canvas``。
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence

try:  # 运行时走包内相对导入；守卫脚本以顶层模块导入（无包上下文）时回退
    from .glue.schema import normalize_generation
except ImportError:  # pragma: no cover
    from glue.schema import normalize_generation  # type: ignore

# "generation" 为嵌套 dict（生成参数血缘块）：载荷携带且非空 ⇒ 整块替换；
# 缺省 / 空块 ⇒ 不覆盖已有（与字符串键同一条 `if val` 纪律，语义见 schema.py）。
LINK_KEYS = ("canvas_node_id", "canvas_kind", "canvas_title", "generation")


def extra_from_material_payload(data: Any) -> Dict[str, Any]:
    """从 MATERIAL_TO_TIMELINE / ingest 载荷抽出可盖到 clip 上的字段。

    含 ``generation`` 血缘块（经 ``normalize_generation`` 白名单清洗，
    空块不输出 —— 缺什么不发什么，绝不猜默认值）。
    """
    if not isinstance(data, Mapping):
        return {}
    extra: Dict[str, Any] = {}
    nid = data.get("canvas_node_id") or data.get("node_id")
    if nid:
        extra["canvas_node_id"] = str(nid)
    kind = data.get("canvas_kind") or data.get("kind")
    if kind:
        extra["canvas_kind"] = str(kind)
    title = data.get("title")
    if title:
        extra["canvas_title"] = str(title)
    gen = normalize_generation(data.get("generation"))
    if gen:
        extra["generation"] = gen
    return extra


def stamp_clip(clip: MutableMapping[str, Any], extra: Mapping[str, Any]) -> None:
    """就地盖 round-trip 字段；空值不覆盖已有。

    ``generation`` 例外语义：载荷携带且非空 ⇒ **整块替换**旧血缘
    （重拍 / 改参数后旧 prompt/seed 不得残留）；空块 ⇒ 不动已有。
    """
    if not extra:
        return
    for key in LINK_KEYS:
        val = extra.get(key)
        if val:
            clip[key] = dict(val) if key == "generation" else val
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


def lineage_from_clip(clip: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """clip → 画布节点的正式血缘记录；无关联 ⇒ None（诚实：不造空记录）。

    「有关联」判据：有 ``canvas_node_id`` 或有非空 ``generation`` 血缘块。
    数值字段宽松清洗（不可转换即丢弃），绝不抛异常。
    """
    if not isinstance(clip, Mapping):
        return None
    nid = str(clip.get("canvas_node_id") or "")
    gen = clip.get("generation")
    has_gen = isinstance(gen, Mapping) and bool(gen)
    if not nid and not has_gen:
        return None
    rec: Dict[str, Any] = {
        "clip_id": str(clip.get("id") or ""),
        "canvas_node_id": nid,
        "canvas_kind": str(clip.get("canvas_kind") or ""),
        "path": str(clip.get("path") or clip.get("file_path") or ""),
        "generation": dict(gen) if has_gen else {},
    }
    for key in ("duration", "in_point", "out_point"):
        val = clip.get(key)
        if val is None:
            continue
        try:
            rec[key] = float(val)
        except (TypeError, ValueError):
            continue
    return rec


def lineage_index(clips: Sequence[Any]) -> Dict[str, Any]:
    """按需从 ``_clips`` 快照构建双向血缘索引（不落第二份真相源）。

    返回 ``{"by_clip_id": {clip_id: rec}, "by_node_id": {node_id: [rec, …]}}``；
    同一节点可多次入轨 ⇒ node 方向为列表。
    """
    by_clip_id: Dict[str, Dict[str, Any]] = {}
    by_node_id: Dict[str, List[Dict[str, Any]]] = {}
    for c in clips or []:
        rec = lineage_from_clip(c)
        if not rec:
            continue
        cid = rec["clip_id"]
        if cid:
            by_clip_id[cid] = rec
        nid = rec["canvas_node_id"]
        if nid:
            by_node_id.setdefault(nid, []).append(rec)
    return {"by_clip_id": by_clip_id, "by_node_id": by_node_id}


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

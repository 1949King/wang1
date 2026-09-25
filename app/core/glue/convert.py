# -*- coding: utf-8 -*-
"""粘合层三向转换 —— 剪辑线 / 生成线 / 画布线之间的标准换算。

【三条转换路径】
    clip_to_glue            剪辑线内部表示 → 契约层规范表示
    glue_to_outbox          契约层 → 画布 outbox 载荷（剪辑→画布）
    canvas_payload_to_glue  画布/生成载荷 → 契约层（画布→剪辑）
    glue_to_clip_patch      契约层 → 可盖章到 clip 的字段子集
    glue_to_clip_row        契约层 → 给画布/Agent 看的一行

【兼容性铁律】
本模块的输出**必须与既有实现逐字段等价**（``app/core/editor_canvas_link.py``）。
由 ``_verify/check_glue_contract.py`` 用同一组样例做等价性断言，
一旦不等等价即报错 —— 这是「只新增不改行为」的可执行保证。

【纯标准库】
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from .schema import (
    CLIP_ROW_KEYS,
    ENVELOPE_FIELD,
    GLUE_SCHEMA_VERSION,
    LINK_KEYS,
    ORIGIN_CANVAS,
    ORIGIN_EDITOR,
    LANE_CANVAS,
    LANE_CLIP,
    canonical_key,
    make_provenance,
)


def _as_float(v: Any, default: Optional[float] = None) -> Optional[float]:
    """宽松浮点转换：失败回默认值（不抛），与既有实现同语义。"""
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _first(m: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    """按序取第一个「真值」字段（兼容历史别名路径）。"""
    for k in keys:
        if k in m and m[k] not in (None, ""):
            return m[k]
    return default


# ---------------------------------------------------------------------------
# ① 剪辑线 → 契约层
# ---------------------------------------------------------------------------
def clip_to_glue(clip: Mapping[str, Any], index: Optional[int] = None) -> Dict[str, Any]:
    """把时间线 clip 归一成契约层表示。

    Args:
        clip: ``EditorModule._clips`` 里的一项（只读，不修改）。
        index: 可选的片序号（快照行需要）。

    Returns:
        dict，含规范字段 + ``glue`` 信封（orgin=editor, lane=N）。
    """
    if not isinstance(clip, Mapping):
        return {}
    path = str(clip.get("path") or clip.get("file_path") or "")
    # title 的取值规则**必须与 editor_canvas_link.public_clip_row 的 name 完全一致**
    # （只认 name，回退文件名）—— 否则接入契约层就等于改了行为。
    # canvas_title 单独出一个字段承载，不参与 title 回退。
    title = str(clip.get("name") or "")
    if not title and path:
        title = path.replace("\\", "/").rsplit("/", 1)[-1]
    start = _as_float(clip.get("start_time"), 0.0) or 0.0
    duration = _as_float(clip.get("duration"), 0.0) or 0.0

    out: Dict[str, Any] = {
        "id": clip.get("id"),
        "title": title,
        "canvas_title": str(clip.get("canvas_title") or ""),
        "path": path,
        "type": str(clip.get("type") or "video"),
        "track": clip.get("track", 0),
        "start_time": start,
        "duration": duration,
        "end_time": start + duration,
        "in_point": clip.get("in_point", 0),
        "out_point": clip.get("out_point"),
        "canvas_node_id": str(clip.get("canvas_node_id") or ""),
        "canvas_kind": str(clip.get("canvas_kind") or ""),
    }
    if index is not None:
        out["clip_index"] = index
    out[ENVELOPE_FIELD] = make_provenance(
        origin=ORIGIN_EDITOR, lane=LANE_CLIP, degraded=0
    ).as_dict()
    return out


# ---------------------------------------------------------------------------
# ② 契约层 → 画布 outbox（剪辑 → 画布）
# ---------------------------------------------------------------------------
def glue_to_outbox(glue: Mapping[str, Any]) -> Dict[str, Any]:
    """生成 outbox 附加身份：``{clip_id, canvas_node_id, kind, in/out, start, duration}``。

    与 ``editor_canvas_link.outbox_fields_from_clip`` 等价：**空值不输出**，
    数值字段只在可转换时输出。
    """
    if not isinstance(glue, Mapping):
        return {}
    fields: Dict[str, Any] = {}
    cid = glue.get("id") or glue.get("clip_id")
    if cid:
        fields["clip_id"] = str(cid)
    nid = glue.get("canvas_node_id")
    if nid:
        fields["canvas_node_id"] = str(nid)
    kind = glue.get("canvas_kind") or glue.get("type")
    if kind:
        fields["kind"] = str(kind)
    for key in ("in_point", "out_point", "start_time", "duration"):
        if glue.get(key) is None:
            continue
        v = _as_float(glue.get(key))
        if v is None:
            continue
        fields[key] = v
    return fields


# ---------------------------------------------------------------------------
# ③ 画布/生成载荷 → 契约层（画布 → 剪辑）
# ---------------------------------------------------------------------------
def canvas_payload_to_glue(
    payload: Mapping[str, Any],
    origin: str = ORIGIN_CANVAS,
    degraded: int = 0,
    lane: str = LANE_CANVAS,
    note: str = "",
) -> Dict[str, Any]:
    """把画布 or 生成线的载荷归一成契约层表示。

    与 ``editor_canvas_link.extra_from_material_payload`` 的字段抽取规则一致
    （``canvas_node_id``/``node_id``、``canvas_kind``/``kind``、``title``），
    额外补上溯源信封 —— 这正是本契约层要解决的「看不见出处」问题。

    Args:
        payload: 画布 ``/ingest`` 或 ``MATERIAL_TO_TIMELINE`` 载荷。
        origin:  产物来源（canvas / generator）。
        degraded: 降级级别 0..6（生成线降级后必须如实填写）。
        lane:    归属轨。
        note:    降级原因等备注。
    """
    if not isinstance(payload, Mapping):
        return {}
    out: Dict[str, Any] = {}
    nid = _first(payload, "canvas_node_id", "node_id")
    if nid:
        out["canvas_node_id"] = str(nid)
    kind = _first(payload, "canvas_kind", "kind")
    if kind:
        out["canvas_kind"] = str(kind)
    title = payload.get("title")
    if title:
        # ⚠️ 关键语义：载荷的 ``title`` 落到 clip 上的规范名是 ``canvas_title``
        # （既有实现 editor_canvas_link.extra_from_material_payload 就是这么映射的）。
        # 两个键都写：canvas_title 供盖章用，title 供展示用。
        out["canvas_title"] = str(title)
        out["title"] = str(title)
    path = _first(payload, "path", "file_path", "url")
    if path:
        out["path"] = str(path)
    typ = payload.get("type")
    if typ:
        out["type"] = str(typ)
    for key in ("in_point", "out_point", "duration"):
        if payload.get(key) is None:
            continue
        v = _as_float(payload.get(key))
        if v is not None:
            out[key] = v
    out[ENVELOPE_FIELD] = make_provenance(
        origin=origin, lane=lane, degraded=degraded, note=note
    ).as_dict()
    return out


# ---------------------------------------------------------------------------
# ④ 契约层 → 可盖章字段（画布/生成 → 剪辑）
# ---------------------------------------------------------------------------
def glue_to_clip_patch(glue: Mapping[str, Any]) -> Dict[str, str]:
    """抽出可盖到 clip 上的关联字段（只含 ``LINK_KEYS``）。空值不输出。"""
    if not isinstance(glue, Mapping):
        return {}
    patch: Dict[str, str] = {}
    for key in LINK_KEYS:
        val = glue.get(key)
        if val:
            patch[key] = str(val)
    return patch


# ---------------------------------------------------------------------------
# ⑤ 契约层 → 快照行（给画布 / Agent 看）
# ---------------------------------------------------------------------------
def glue_to_clip_row(glue: Mapping[str, Any], index: int = 0) -> Dict[str, Any]:
    """生成时间线快照的一行，键集合与 ``CLIP_ROW_KEYS`` 一致。"""
    if not isinstance(glue, Mapping):
        return {}
    row = {k: glue.get(k) for k in CLIP_ROW_KEYS}
    row["clip_index"] = index
    row["id"] = glue.get("id")
    row["name"] = glue.get("title") or ""
    row["path"] = glue.get("path") or ""
    row["type"] = glue.get("type") or "video"
    row["track"] = glue.get("track", 0)
    start = _as_float(glue.get("start_time"), 0.0) or 0.0
    duration = _as_float(glue.get("duration"), 0.0) or 0.0
    row["start_time"] = start
    row["duration"] = duration
    row["end_time"] = start + duration
    row["in_point"] = glue.get("in_point", 0)
    row["canvas_node_id"] = glue.get("canvas_node_id") or ""
    row["canvas_kind"] = glue.get("canvas_kind") or ""
    return {k: row.get(k) for k in CLIP_ROW_KEYS if k in row}


def clip_rows(glues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """批量转快照行（供 ``/host/timeline-snapshot`` 使用）。"""
    return [glue_to_clip_row(g, i) for i, g in enumerate(glues or [])]


def normalize_payload_keys(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """把历史别名收敛到规范键（不丢未知键，避免破坏扩展字段）。"""
    if not isinstance(payload, Mapping):
        return {}
    out: Dict[str, Any] = {}
    for k, v in payload.items():
        ck = canonical_key(k)
        if ck not in out:
            out[ck] = v
    return out

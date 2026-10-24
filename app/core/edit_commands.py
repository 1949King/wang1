"""
B1：薄指令执行器 — 纯数据层 Split / Ripple Delete（写 _clips 语义）

职责：
  - 给定 clips 列表与时间线半开区间 [t_in, t_out)，执行切分 + 波纹删除
  - 返回与 EditorModule._apply_action 兼容的 undo steps（compound）
  - 不写 UI、不碰 SubtitleManager

用法:
    from app.core.edit_commands import ripple_delete_timeline_range

    result = ripple_delete_timeline_range(clips, t_in, t_out, track=0)
    if result.ok:
        clips[:] = result.clips
        editor._record_action(result.undo_action)
"""

from __future__ import annotations

import copy
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple


_EPS = 1e-4
_LINKED_AV_START_TOL = 0.08


def _clip_end(clip: Dict[str, Any]) -> float:
    return float(clip.get("start_time", 0) or 0) + float(clip.get("duration", 0) or 0)


def _clip_overlaps_range(clip: Dict[str, Any], t_in: float, t_out: float) -> bool:
    st = float(clip.get("start_time", 0) or 0)
    en = _clip_end(clip)
    return st < t_out - _EPS and en > t_in + _EPS


def _track_match(clip: Dict[str, Any], track: Optional[int]) -> bool:
    if track is None:
        return True
    return int(clip.get("track", 0) or 0) == int(track)


def _default_id_factory(prefix: str = "clip") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _find_linked_av_partners(
    clips: Sequence[Dict[str, Any]],
    clip: Dict[str, Any],
    *,
    ref_start: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """同 path、与 ref_start 对齐的联动片（视频↔内嵌音频），与 EditorModule 一致。"""
    if not clip:
        return []
    path = clip.get("path")
    cid = clip.get("id")
    if not path:
        return []
    st0 = float(ref_start if ref_start is not None else clip.get("start_time", 0) or 0)
    out: List[Dict[str, Any]] = []
    for c in clips:
        if c.get("id") == cid:
            continue
        if c.get("path") != path:
            continue
        if abs(float(c.get("start_time", 0) or 0) - st0) < _LINKED_AV_START_TOL:
            out.append(c)
    return out


def _clips_covering_timeline_time(
    clips: Sequence[Dict[str, Any]],
    t: float,
    *,
    track: Optional[int] = None,
) -> List[Dict[str, Any]]:
    t = float(t)
    hits: List[Dict[str, Any]] = []
    for c in clips:
        if not _track_match(c, track):
            continue
        st = float(c.get("start_time", 0) or 0)
        en = _clip_end(c)
        if st + _EPS < t < en - _EPS:
            hits.append(c)
    return hits


def _expand_split_targets_with_linked_av(
    clips: Sequence[Dict[str, Any]],
    seeds: Sequence[Dict[str, Any]],
    split_t: float,
) -> List[Dict[str, Any]]:
    """种子片段 + 同 path/同 start 联动片（仍覆盖 split_t）去重。"""
    by_id: Dict[str, Dict[str, Any]] = {}
    split_t = float(split_t)
    for c in seeds or []:
        if not isinstance(c, dict) or not c.get("id"):
            continue
        st = float(c.get("start_time", 0) or 0)
        en = _clip_end(c)
        if not (st + _EPS < split_t < en - _EPS):
            continue
        by_id[str(c["id"])] = c
        for p in _find_linked_av_partners(clips, c):
            pst = float(p.get("start_time", 0) or 0)
            pen = _clip_end(p)
            if pst + _EPS < split_t < pen - _EPS and p.get("id"):
                by_id[str(p["id"])] = p
    return list(by_id.values())


def _split_rank(clip: Dict[str, Any]) -> Tuple[int, int]:
    is_audio = str(clip.get("type", "")).lower() == "audio"
    return (1 if is_audio else 0, int(clip.get("track", 0) or 0))


def _split_all_at_timeline_with_linked_av(
    clips: Sequence[Dict[str, Any]],
    split_t: float,
    *,
    track: Optional[int] = None,
    id_factory: Optional[Callable[[], str]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """在 split_t 切开目标轨片段及其联动音/视频（刀片 + B1 共用语义）。"""
    factory = id_factory or (lambda: _default_id_factory("split"))
    working = [copy.deepcopy(c) for c in clips]
    steps: List[Dict[str, Any]] = []
    done: set[str] = set()

    seeds = _clips_covering_timeline_time(working, split_t, track=track)
    targets = _expand_split_targets_with_linked_av(working, seeds, split_t)
    for clip in sorted(targets, key=_split_rank):
        cid = str(clip.get("id") or "")
        if not cid or cid in done:
            continue
        live = next((c for c in working if c.get("id") == cid), None)
        if live is None:
            continue
        working, action = split_clip_at_timeline(working, cid, split_t, id_factory=factory)
        if not action:
            continue
        steps.append(action)
        done.add(cid)
        left = next((c for c in working if c.get("id") == cid), None)
        if left is None:
            continue
        for p in _find_linked_av_partners(working, left):
            pid = str(p.get("id") or "")
            if not pid or pid in done:
                continue
            plive = next((c for c in working if c.get("id") == pid), None)
            if plive is None:
                continue
            pst = float(plive.get("start_time", 0) or 0)
            pen = _clip_end(plive)
            if not (pst + _EPS < split_t < pen - _EPS):
                continue
            working, pact = split_clip_at_timeline(working, pid, split_t, id_factory=factory)
            if pact:
                steps.append(pact)
                done.add(pid)
    return working, steps


@dataclass
class RippleDeleteResult:
    """ripple_delete_timeline_range 返回值。"""

    ok: bool
    message: str
    clips: List[Dict[str, Any]] = field(default_factory=list)
    steps: List[Dict[str, Any]] = field(default_factory=list)
    deleted_duration: float = 0.0

    @property
    def undo_action(self) -> Dict[str, Any]:
        """供 EditorModule._record_action 使用的复合撤销条目。"""
        return {
            "type": "compound",
            "steps": list(self.steps),
            "label": "ripple_delete_range",
        }


def split_clip_at_timeline(
    clips: Sequence[Dict[str, Any]],
    clip_id: str,
    split_timeline: float,
    *,
    id_factory: Optional[Callable[[], str]] = None,
) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    在绝对时间线 split_timeline 处切分 clip_id。

    返回 (新 clips 列表, split undo action)；失败时 action 为 None。
    """
    factory = id_factory or (lambda: _default_id_factory("split"))
    working = [copy.deepcopy(c) for c in clips]
    clip = next((c for c in working if c.get("id") == clip_id), None)
    if clip is None:
        return list(working), None

    start = float(clip.get("start_time", 0) or 0)
    duration = float(clip.get("duration", 0) or 0)
    local = float(split_timeline) - start
    if local <= _EPS or local >= duration - _EPS:
        return list(working), None

    original_duration = duration
    original_out = float(clip.get("out_point", 0) or 0)
    if original_out <= float(clip.get("in_point", 0) or 0):
        original_out = float(clip.get("in_point", 0) or 0) + original_duration

    new_clip = copy.deepcopy(clip)
    new_clip["id"] = factory()
    new_clip["start_time"] = start + local
    new_clip["duration"] = duration - local
    new_clip["in_point"] = float(clip.get("in_point", 0) or 0) + local
    new_clip["out_point"] = new_clip["in_point"] + new_clip["duration"]

    clip["duration"] = local
    clip["out_point"] = float(clip.get("in_point", 0) or 0) + local

    working.append(new_clip)
    action = {
        "type": "split",
        "original_clip": clip,
        "new_clip": new_clip,
        "original_duration": original_duration,
        "original_out_point": original_out,
    }
    return working, action


def ripple_delete_clip_data(
    clips: Sequence[Dict[str, Any]],
    clip_id: str,
    *,
    ripple: bool = True,
) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    从 clips 删除 clip_id；默认同轨后续片 start_time 前移（波纹）。

    返回 (新 clips, delete undo action)。
    """
    working = [copy.deepcopy(c) for c in clips]
    deleted = next((c for c in working if c.get("id") == clip_id), None)
    if deleted is None:
        return list(working), None

    track_i = int(deleted.get("track", 0) or 0)
    st = float(deleted.get("start_time", 0) or 0)
    dur = float(deleted.get("duration", 0) or 0)
    end = st + dur
    ripple_shifts: List[Dict[str, Any]] = []

    working = [c for c in working if c.get("id") != clip_id]

    if ripple and dur > _EPS:
        for c in working:
            if int(c.get("track", 0) or 0) != track_i:
                continue
            cst = float(c.get("start_time", 0) or 0)
            if cst >= end - _EPS:
                old = cst
                c["start_time"] = max(0.0, cst - dur)
                ripple_shifts.append({"id": c.get("id"), "old": old, "new": c["start_time"]})

    action = {"type": "delete", "clip": deleted, "ripple_shifts": ripple_shifts}
    return working, action


def ripple_delete_timeline_range(
    clips: Sequence[Dict[str, Any]],
    t_in: float,
    t_out: float,
    *,
    track: Optional[int] = None,
    id_factory: Optional[Callable[[], str]] = None,
) -> RippleDeleteResult:
    """
    在时间线半开区间 [t_in, t_out) 上执行：边界切分 + 波纹删除中间段。

    track: 仅处理该轨；None 表示所有轨（多轨工程慎用）。
    """
    t_in = float(t_in)
    t_out = float(t_out)
    if t_out <= t_in + _EPS:
        return RippleDeleteResult(False, "无效区间：t_out 须大于 t_in", clips=list(clips))

    factory = id_factory or (lambda: _default_id_factory(f"split_{int(time.time() * 1000)}"))
    working = [copy.deepcopy(c) for c in clips]
    steps: List[Dict[str, Any]] = []

    # Phase 1: split at t_in（含联动音/视频）
    working, split_steps = _split_all_at_timeline_with_linked_av(
        working, t_in, track=track, id_factory=factory
    )
    steps.extend(split_steps)

    # Phase 2: split at t_out（含联动音/视频）
    working, split_steps = _split_all_at_timeline_with_linked_av(
        working, t_out, track=track, id_factory=factory
    )
    steps.extend(split_steps)

    # Phase 3: delete segments fully inside [t_in, t_out)
    to_delete: List[str] = []
    seen_delete: set[str] = set()
    for c in working:
        if not _track_match(c, track):
            continue
        st = float(c.get("start_time", 0) or 0)
        en = _clip_end(c)
        if st >= t_in - _EPS and en <= t_out + _EPS:
            cid = str(c.get("id"))
            if cid not in seen_delete:
                seen_delete.add(cid)
                to_delete.append(cid)
            for p in _find_linked_av_partners(working, c):
                pst = float(p.get("start_time", 0) or 0)
                pen = _clip_end(p)
                if pst >= t_in - _EPS and pen <= t_out + _EPS:
                    pcid = str(p.get("id"))
                    if pcid not in seen_delete:
                        seen_delete.add(pcid)
                        to_delete.append(pcid)

    if not to_delete:
        return RippleDeleteResult(
            False,
            f"[{t_in:.3f}, {t_out:.3f}) 内无可删除片段",
            clips=working,
            steps=steps,
        )

    deleted_dur = 0.0
    # 从左到右删，每次 ripple（与 EditorModule 行为一致）
    for cid in sorted(
        to_delete,
        key=lambda i: float(
            next(c.get("start_time", 0) for c in working if c.get("id") == i)
        ),
    ):
        clip = next((c for c in working if c.get("id") == cid), None)
        if clip is None:
            continue
        if track is None or _track_match(clip, track):
            deleted_dur += float(clip.get("duration", 0) or 0)
        working, action = ripple_delete_clip_data(working, cid, ripple=True)
        if action:
            steps.append(action)

    return RippleDeleteResult(
        True,
        f"已波纹删除 [{t_in:.3f}, {t_out:.3f})，共 {len(to_delete)} 段",
        clips=working,
        steps=steps,
        deleted_duration=deleted_dur,
    )


@dataclass
class CloseGapsResult:
    ok: bool
    message: str
    clips: List[Dict[str, Any]] = field(default_factory=list)
    steps: List[Dict[str, Any]] = field(default_factory=list)
    closed_duration: float = 0.0

    @property
    def undo_action(self) -> Dict[str, Any]:
        return {
            "type": "compound",
            "steps": list(self.steps),
            "label": "close_gaps",
        }


def close_track_gaps(
    clips: Sequence[Dict[str, Any]],
    track: Optional[int] = None,
    *,
    gap_threshold: float = 0.05,
) -> CloseGapsResult:
    """
    磁吸合缝：同轨按 start_time 排序，把后续片前移贴齐前片尾（不删内容）。

    track=None 时处理所有轨。返回 edit_clip steps（仅 start_time）。
    """
    working = [copy.deepcopy(c) for c in clips]
    steps: List[Dict[str, Any]] = []
    closed = 0.0
    thr = max(0.0, float(gap_threshold))

    track_ids = set()
    for c in working:
        if track is None or int(c.get("track", 0) or 0) == int(track):
            track_ids.add(int(c.get("track", 0) or 0))

    for ti in sorted(track_ids):
        row = [c for c in working if int(c.get("track", 0) or 0) == ti]
        row.sort(key=lambda c: float(c.get("start_time", 0) or 0))
        cursor = 0.0
        for c in row:
            st = float(c.get("start_time", 0) or 0)
            dur = max(0.0, float(c.get("duration", 0) or 0))
            if st > cursor + thr:
                gap = st - cursor
                before = {
                    "start_time": st,
                    "track": ti,
                    "duration": dur,
                    "in_point": float(c.get("in_point", 0) or 0),
                    "out_point": float(c.get("out_point", 0) or 0),
                }
                c["start_time"] = cursor
                after = dict(before)
                after["start_time"] = cursor
                steps.append({
                    "type": "edit_clip",
                    "clip_id": c.get("id"),
                    "before": before,
                    "after": after,
                })
                closed += gap
            elif st < cursor - _EPS:
                # 重叠：不强制推开，只推进 cursor
                pass
            cursor = max(cursor, float(c.get("start_time", 0) or 0) + dur)

    # 单轨合缝时联动音画跟着 Δstart 走（同 path + 合缝前 start 对齐）
    moved_ids = {s.get("clip_id") for s in steps}
    extra: List[Dict[str, Any]] = []
    for step in list(steps):
        cid = step.get("clip_id")
        clip = next((c for c in working if c.get("id") == cid), None)
        if not clip:
            continue
        before_st = float((step.get("before") or {}).get("start_time", 0) or 0)
        after_st = float((step.get("after") or {}).get("start_time", 0) or 0)
        delta = after_st - before_st
        if abs(delta) < _EPS:
            continue
        for p in _find_linked_av_partners(working, clip, ref_start=before_st):
            pid = p.get("id")
            if pid in moved_ids:
                continue
            pst = float(p.get("start_time", 0) or 0)
            before_p = {
                "start_time": pst,
                "track": int(p.get("track", 0) or 0),
                "duration": float(p.get("duration", 0) or 0),
                "in_point": float(p.get("in_point", 0) or 0),
                "out_point": float(p.get("out_point", 0) or 0),
            }
            p["start_time"] = max(0.0, pst + delta)
            after_p = dict(before_p)
            after_p["start_time"] = float(p["start_time"])
            extra.append({
                "type": "edit_clip",
                "clip_id": pid,
                "before": before_p,
                "after": after_p,
            })
            moved_ids.add(pid)
    steps.extend(extra)

    if not steps:
        return CloseGapsResult(False, "没有可合缝的间隙", clips=list(clips))
    return CloseGapsResult(
        True,
        f"已合缝 {closed:.2f}s（{len(steps)} 处）",
        clips=working,
        steps=steps,
        closed_duration=closed,
    )


def ripple_delete_from_binding(
    clips: Sequence[Dict[str, Any]],
    binding: Any,
    *,
    track: Optional[int] = None,
) -> RippleDeleteResult:
    """
    B0 TextFrameBinding → ripple delete。

    binding 须有 timeline_in_sec / timeline_out_sec（TextFrameBinding 或 dict）。
    """
    if hasattr(binding, "timeline_in_sec"):
        t_in = float(binding.timeline_in_sec)
        t_out = float(binding.timeline_out_sec)
    elif isinstance(binding, dict):
        t_in = float(binding.get("timeline_in_sec", binding.get("start_time", 0)))
        t_out = float(binding.get("timeline_out_sec", binding.get("end_time", 0)))
    else:
        return RippleDeleteResult(False, "无效 binding", clips=list(clips))
    return ripple_delete_timeline_range(clips, t_in, t_out, track=track)

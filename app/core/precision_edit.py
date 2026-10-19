# -*- coding: utf-8 -*-
"""帧级精剪审计 / 对齐计划（2026-10-20 · 精剪线第一刀）

剪辑真相源是 `TimelineStore`（`EditorModule._clips` 行缓存），时间以**秒（float）**存储。
浮点秒在 24/25/30fps 下很容易落在帧边界之外，表现为：
  · 片段起止不在帧网格（导出后首尾各多/少 1 帧）
  · 同轨相邻片段出现**次帧缝隙/重叠**（0.3 帧之类，肉眼看不见但会累积）
  · 视频与联动音频起点不完全一致（音画错位 < 1 帧，长片累积）

本模块只做**纯计算**：审计 + 对齐计划，不读 UI、不写时间线。
写回由能力层委托既有 store API（可撤销）——本模块不制造第二套写入口。

设计纪律：
* 不猜：缺字段按 0 处理并如实标注；非法值进 issues，不静默修正。
* 不动用户意图：对齐计划只吸附到**最近帧**，不改 in_point、不裁剪内容超过 1 帧。
* 只报测到的：音画偏移是 **info**（J/L cut 是有意为之），不是错误。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

DEFAULT_FPS = 30.0


def _num(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return float(value)


def _fps_of(clips: List[Dict[str, Any]], fps: Optional[float]) -> float:
    if fps and fps > 0:
        return float(fps)
    for clip in clips or []:
        candidate = clip.get("fps") if isinstance(clip, dict) else None
        if isinstance(candidate, (int, float)) and candidate > 0:
            return float(candidate)
    return DEFAULT_FPS


def snap_seconds(seconds: float, fps: float, mode: str = "nearest") -> float:
    """把秒吸附到帧网格（nearest / floor / ceil）。"""
    if fps <= 0:
        return float(seconds)
    frames = float(seconds) * float(fps)
    if mode == "floor":
        n = int(frames // 1)
    elif mode == "ceil":
        n = int(-((-frames) // 1))
    else:
        n = int(round(frames))
    return n / float(fps)


def frames_of(seconds: float, fps: float) -> float:
    return float(seconds) * float(fps)


def _end(clip: Dict[str, Any]) -> float:
    return _num(clip.get("start_time")) + _num(clip.get("duration"))


def _severity(code: str) -> str:
    if code in ("negative_start", "non_positive_duration", "invalid_speed", "bad_source_window"):
        return "error"
    if code in ("off_grid_start", "off_grid_duration", "subframe_gap", "overlap"):
        return "warning"
    return "info"


def _issue(code: str, clip: Dict[str, Any], detail: str,
           suggested: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "code": code,
        "severity": _severity(code),
        "clip_id": str(clip.get("id") or ""),
        "track": int(_num(clip.get("track"), 0)),
        "detail": detail,
        "suggested": suggested or None,
    }


def audit_timeline(
    clips: List[Dict[str, Any]],
    fps: Optional[float] = None,
    *,
    tolerance_frames: float = 0.1,
    include_av: bool = True,
) -> Dict[str, Any]:
    """审计时间线帧精度；返回 {ok, fps, stats, issues}。

    `ok=False` 仅当出现结构性 error（负起点/非正时长/非法速度/源窗非法）；
    帧网格与次帧缝隙是 warning，音画偏移是 info。
    """
    clips = [c for c in (clips or []) if isinstance(c, dict)]
    rate = _fps_of(clips, fps)
    frame = 1.0 / rate
    tol = max(0.0, float(tolerance_frames)) / rate
    issues: List[Dict[str, Any]] = []

    for clip in clips:
        start = _num(clip.get("start_time"))
        duration = _num(clip.get("duration"))
        speed = _num(clip.get("speed"), 1.0)
        if start < -1e-9:
            issues.append(_issue("negative_start", clip, f"start_time={start:.6f}s < 0",
                                 {"start_time": 0.0}))
        if duration <= 0:
            issues.append(_issue("non_positive_duration", clip,
                                 f"duration={duration:.6f}s 必须 > 0"))
        else:
            snapped_start = snap_seconds(start, rate)
            if abs(start - snapped_start) > tol:
                issues.append(_issue(
                    "off_grid_start", clip,
                    f"起点 {start:.6f}s 不在帧网格（最近 {snapped_start:.6f}s）",
                    {"start_time": snapped_start},
                ))
            snapped_duration = snap_seconds(duration, rate)
            if snapped_duration < frame:
                snapped_duration = frame
            if abs(duration - snapped_duration) > tol:
                issues.append(_issue(
                    "off_grid_duration", clip,
                    f"时长 {duration:.6f}s 不在帧网格（最近 {snapped_duration:.6f}s）",
                    {"duration": snapped_duration},
                ))
        if speed <= 0:
            issues.append(_issue("invalid_speed", clip, f"speed={speed} 必须 > 0"))
        in_point = _num(clip.get("in_point"))
        out_point = _num(clip.get("out_point"))
        if out_point > 0 and out_point <= in_point:
            issues.append(_issue(
                "bad_source_window", clip,
                f"out_point={out_point:.3f}s <= in_point={in_point:.3f}s",
            ))

    # 同轨相邻：次帧缝隙 / 重叠
    tracks: Dict[int, List[Dict[str, Any]]] = {}
    for clip in clips:
        tracks.setdefault(int(_num(clip.get("track"), 0)), []).append(clip)
    for track, items in sorted(tracks.items()):
        ordered = sorted(items, key=lambda c: _num(c.get("start_time")))
        for prev, nxt in zip(ordered, ordered[1:], strict=False):
            gap = _num(nxt.get("start_time")) - _end(prev)
            if gap > 1e-9 and gap < frame - 1e-9:
                issues.append(_issue(
                    "subframe_gap", nxt,
                    f"轨道 {track} 两片段间 {gap:.6f}s 次帧缝隙（< 1 帧）",
                    {"start_time": snap_seconds(_num(nxt.get("start_time")), rate)},
                ))
            elif gap < -1e-9 and abs(gap) < frame:
                issues.append(_issue(
                    "overlap", nxt,
                    f"轨道 {track} 两片段重叠 {-gap:.6f}s（< 1 帧）",
                ))

    # 音画偏移（同路径视频/音频；J/L cut 合法 ⇒ info）
    if include_av:
        by_path: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
        for clip in clips:
            path = str(clip.get("path") or "")
            if not path:
                continue
            kind = str(clip.get("type") or "").lower()
            bucket = by_path.setdefault(path, {"video": [], "audio": []})
            if kind == "audio":
                bucket["audio"].append(clip)
            else:
                bucket["video"].append(clip)
        for _path, bucket in sorted(by_path.items()):
            for video in bucket["video"]:
                vstart = _num(video.get("start_time"))
                nearest = min(
                    bucket["audio"],
                    key=lambda a: abs(_num(a.get("start_time")) - vstart),
                    default=None,
                )
                if nearest is None:
                    continue
                offset = _num(nearest.get("start_time")) - vstart
                if abs(offset) > tol:
                    issues.append(_issue(
                        "av_offset", video,
                        f"音画起点偏移 {offset:+.6f}s（J/L cut 属正常；否则建议对齐）",
                    ))

    errors = sum(1 for i in issues if i["severity"] == "error")
    warnings = sum(1 for i in issues if i["severity"] == "warning")
    total = max((_end(c) for c in clips), default=0.0)
    return {
        "ok": errors == 0,
        "fps": rate,
        "clip_count": len(clips),
        "stats": {
            "track_count": len(tracks),
            "total_duration": round(total, 6),
            "total_frames": round(total * rate, 3),
            "errors": errors,
            "warnings": warnings,
            "infos": len(issues) - errors - warnings,
        },
        "issues": issues,
    }


def plan_frame_align(
    clips: List[Dict[str, Any]],
    fps: Optional[float] = None,
    *,
    max_changes: int = 200,
) -> Dict[str, Any]:
    """生成帧对齐计划（只算不改）：吸附 start_time / duration，并同步 out_point。

    保守边界：
    * 只吸附到**最近帧**；duration 至少 1 帧；
    * out_point 仅在有值且 > in_point 时按 `delta * speed` 同步（保源内容窗口自洽）；
    * 源窗会越界的片段进 skipped，不强行修；
    * 重叠/大缝隙不在本刀自动修（需要波纹/联动语义，留给下一刀）。
    """
    clips = [c for c in (clips or []) if isinstance(c, dict)]
    rate = _fps_of(clips, fps)
    frame = 1.0 / rate
    changes: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    for clip in clips:
        if len(changes) >= max_changes:
            skipped.append({"clip_id": str(clip.get("id") or ""), "reason": "达到 max_changes 上限"})
            continue
        clip_id = str(clip.get("id") or "")
        if not clip_id:
            skipped.append({"clip_id": "", "reason": "缺少 clip id"})
            continue
        start = _num(clip.get("start_time"))
        duration = _num(clip.get("duration"))
        speed = _num(clip.get("speed"), 1.0)
        in_point = _num(clip.get("in_point"))
        out_point = _num(clip.get("out_point"))
        new_start = snap_seconds(start, rate)
        new_duration = max(frame, snap_seconds(duration, rate))
        new_out = out_point
        if out_point > 0 and out_point > in_point:
            new_out = out_point + (new_duration - duration) * max(speed, 1e-9)
            if new_out <= in_point + frame * 0.5:
                skipped.append({
                    "clip_id": clip_id,
                    "reason": f"out_point 吸附后会 <= in_point（{new_out:.6f}s <= {in_point:.6f}s）",
                })
                continue
        if abs(new_start - start) < 1e-9 and abs(new_duration - duration) < 1e-9:
            continue
        changes.append({
            "clip_id": clip_id,
            "before": {
                "start_time": round(start, 6),
                "duration": round(duration, 6),
                "out_point": round(out_point, 6) if out_point else None,
            },
            "after": {
                "start_time": round(new_start, 6),
                "duration": round(new_duration, 6),
                "out_point": round(new_out, 6) if new_out else None,
            },
            "delta_frames": {
                "start": round((new_start - start) * rate, 3),
                "duration": round((new_duration - duration) * rate, 3),
            },
        })

    return {
        "fps": rate,
        "change_count": len(changes),
        "changes": changes,
        "skipped": skipped,
    }

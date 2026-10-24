"""时间线互操作适配器 · OpenTimelineIO（OTIO）
==============================================
把项目自研的 ``timeline_dsl.Timeline`` 与业界标准的 OTIO 时间线双向映射，
一次性打通 OTIO / EDL(CMX3600) / FCPXML 等专业剪辑互操作格式。

设计原则
--------
1. **不硬依赖**：未安装 ``opentimelineio`` 时 :func:`is_available` 返回 False，
   导出 / 导入抛出含安装命令的明确指引，**绝不静默失败或产出假文件**。
2. **无损优先**：OTIO 无法原生表达的字段（transform / opacity / volume / 特效 /
   blend mode / 关键帧）统一塞进 ``item.metadata["shiguang"]``，反向导入原样还原。
3. **时间基准**：项目以「秒」为准，OTIO 以 ``RationalTime(rate=fps)`` 为准，
   换算统一走 :func:`_rt` / :func:`_seconds`，避免各处散落取整逻辑。

参考：OpenTimelineIO（Pixar / ASWF，Apache-2.0）。
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from app.core.timeline_dsl import (
    BlendMode,
    Clip,
    ClipProperty,
    ClipTransform,
    ClipType,
    Keyframe,
    KeyframeInterpolation,
    Marker,
    Resolution,
    TimeRange,
    Timeline,
    TimelineSettings,
    Track,
    TrackType,
    Transition,
)

logger = logging.getLogger("AI短剧编辑器.interchange.otio")

_DEFAULT_FPS = 30.0
_NS = "shiguang"  # OTIO metadata 命名空间


def _safe_unlink(path: str) -> None:
    """尽力删除中转临时文件；失败仅记 debug（残留临时文件不影响功能）。

    统一收敛四处 `finally: os.unlink(...)`：既避免重复代码，也让
    「清理失败」这件事有日志可查（静默 except 是稳定性门禁的违规项）。
    """
    try:
        os.unlink(path)
    except OSError:
        logger.debug("清理 OTIO 中转临时文件失败: %s", path, exc_info=True)


# ============================================================
# 可用性 / 依赖
# ============================================================

def is_available() -> bool:
    """opentimelineio 是否已安装。

    **只用 find_spec 探测，绝不真正 import** —— opentimelineio 的 C 扩展在
    PyQt6 **之后**加载会段错误（access violation）；Qt GUI 进程必然先加载 PyQt6，
    因此主进程绝不能 import 它。真正的读写在独立子进程完成（见 :func:`_run_worker`）。
    """
    import importlib.util

    try:
        return importlib.util.find_spec("opentimelineio") is not None
    except Exception:
        return False


def _otio():
    """惰性导入 opentimelineio；不可用时抛带指引的 RuntimeError。"""
    try:
        import opentimelineio as otio
    except Exception as exc:  # pragma: no cover - 环境相关
        raise RuntimeError(
            "未安装 opentimelineio，无法进行时间线互操作（OTIO/EDL/FCPXML）。"
            "请执行：pip install opentimelineio"
        ) from exc
    return otio


_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)


def _run_worker(args: List[str], timeout: float = 180.0) -> Tuple[int, str, str]:
    """在**无 Qt 的独立子进程**里跑 OTIO 转换。

    主进程（Qt GUI）绝不能 import opentimelineio —— 其 C 扩展在 PyQt6 之后加载
    会段错误（`import PyQt6.QtCore, opentimelineio` → access violation；反序正常）。
    故所有 OTIO 读写都交给子进程。返回 (returncode, stdout, stderr)。
    """
    import subprocess
    import sys

    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = _PROJECT_ROOT + os.pathsep + env.get("PYTHONPATH", "")
    cmd = [sys.executable, "-m", "app.core.interchange._otio_worker", *args]
    no_window = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        proc = subprocess.run(
            cmd, capture_output=True, timeout=timeout, cwd=_PROJECT_ROOT,
            env=env, creationflags=no_window,
        )
    except subprocess.TimeoutExpired:
        return 124, "", f"OTIO 子进程超时（{timeout}s）"
    except OSError as exc:
        return 1, "", f"无法启动 OTIO 子进程：{exc}"
    return (
        proc.returncode,
        proc.stdout.decode("utf-8", "replace"),
        proc.stderr.decode("utf-8", "replace"),
    )


def available_export_formats() -> List[str]:
    """当前环境可用的 OTIO 适配器名（otio_json / cmx_3600 / fcp_xml ...）。"""
    if not is_available():
        return []
    rc, out, _err = _run_worker(["formats"], timeout=60)
    if rc != 0:
        return []
    try:
        return sorted(json.loads(out.strip() or "[]"))
    except Exception:
        return []


# ============================================================
# 时间换算
# ============================================================

def _rt(seconds: float, fps: float):
    otio = _otio()
    return otio.opentime.RationalTime(int(round(float(seconds) * fps)), fps)


def _tr(start_s: float, dur_s: float, fps: float):
    otio = _otio()
    return otio.opentime.TimeRange(_rt(start_s, fps), _rt(dur_s, fps))


def _seconds(value: Any, fps: float) -> float:
    """RationalTime → 秒。"""
    try:
        return float(value.to_seconds())
    except Exception:
        try:
            return float(value.value) / float(value.rate or fps)
        except Exception:
            return 0.0


def _track_kind(track_type: TrackType) -> str:
    """OTIO 只有 Video / Audio 两种轨道 kind，其余归 Video 并用 metadata 保留原类型。"""
    return "Audio" if track_type == TrackType.AUDIO else "Video"


# ============================================================
# 导出：Timeline → OTIO
# ============================================================

def _clip_meta(clip: Clip) -> Dict[str, Any]:
    """把 OTIO 无法原生表达的字段打进 metadata["shiguang"]。"""
    return {
        "id": clip.id,
        "type": clip.type.value,
        "timeline_start": clip.range.start,
        "timeline_end": clip.range.end,
        "blend_mode": clip.blend_mode.value,
        "volume": clip.volume,
        "transform": {
            "x": clip.transform.x,
            "y": clip.transform.y,
            "scale_x": clip.transform.scale_x,
            "scale_y": clip.transform.scale_y,
            "rotation": clip.transform.rotation,
            "opacity": clip.transform.opacity,
            "anchor_x": clip.transform.anchor_x,
            "anchor_y": clip.transform.anchor_y,
        },
        "effects": list(clip.effects or []),
        "properties": [
            {
                "name": p.name,
                "default_value": p.default_value,
                "keyframes": [
                    {"time": k.time, "value": k.value, "interpolation": k.interpolation.value}
                    for k in p.keyframes
                ],
            }
            for p in clip.properties
        ],
        "locked": clip.locked,
        "visible": clip.visible,
        "muted": clip.muted,
        "color": clip.color,
        "notes": clip.notes,
        "extra": dict(clip.metadata or {}),
    }


def _clip_to_otio(clip: Clip, fps: float):
    otio = _otio()
    dur = max(0.0, clip.range.duration)
    src_start = clip.source_range.start
    src_dur = clip.source_range.duration or dur
    media = otio.schema.ExternalReference(target_url=clip.source or "")
    if src_start > 0 or src_dur > 0:
        media.available_range = _tr(0.0, max(src_dur, src_start + dur), fps)
    otio_clip = otio.schema.Clip(
        name=clip.name or clip.id,
        source_range=_tr(src_start, max(src_dur, 0.0), fps),
        media_reference=media,
    )
    otio_clip.metadata[_NS] = _clip_meta(clip)
    return otio_clip


def _track_to_otio(track: Track, fps: float):
    otio = _otio()
    otio_track = otio.schema.Track(name=track.name or track.id, kind=_track_kind(track.type))
    otio_track.metadata[_NS] = {
        "id": track.id,
        "type": track.type.value,
        "locked": track.locked,
        "visible": track.visible,
        "muted": track.muted,
        "solo": track.solo,
        "height": track.height,
        "collapsed": track.collapsed,
        "extra": dict(track.metadata or {}),
    }
    cursor = 0.0
    for clip in sorted(track.clips, key=lambda c: c.range.start):
        start = float(clip.range.start)
        if start > cursor + 1e-6:  # 用 Gap 补齐空档，保持时间位置精确
            otio_track.append(otio.schema.Gap(source_range=_tr(0.0, start - cursor, fps)))
        otio_track.append(_clip_to_otio(clip, fps))
        cursor = max(cursor, float(clip.range.end))
    return otio_track


def _marker_to_otio(marker: Marker, fps: float):
    otio = _otio()
    otio_marker = otio.schema.Marker(
        name=marker.name or marker.id,
        marked_range=_tr(marker.time, 0.0, fps),
        color=marker.color or "",
    )
    otio_marker.metadata[_NS] = {
        "id": marker.id,
        "type": marker.type,
        "notes": marker.notes,
    }
    return otio_marker


def _transition_to_otio(trans: Transition, fps: float):
    otio = _otio()
    otio_trans = otio.schema.Transition(
        name=trans.type or trans.id,
        in_offset=_rt(trans.duration, fps),
        out_offset=_rt(trans.duration, fps),
    )
    otio_trans.metadata[_NS] = {
        "id": trans.id,
        "from_clip_id": trans.from_clip_id,
        "to_clip_id": trans.to_clip_id,
        "type": trans.type,
        "params": dict(trans.params or {}),
    }
    return otio_trans


def timeline_to_otio(timeline: Timeline, rate: Optional[float] = None):
    """项目 Timeline → OTIO Timeline。"""
    otio = _otio()
    fps = float(rate or timeline.settings.fps or _DEFAULT_FPS)
    otio_tl = otio.schema.Timeline(name=timeline.name or "ShiguangTimeline")
    otio_tl.metadata[_NS] = {
        "id": timeline.id,
        "version": timeline.version,
        "author": timeline.author,
        "description": timeline.description,
        "tags": list(timeline.tags or []),
        "resolution": {
            "width": timeline.settings.resolution.width,
            "height": timeline.settings.resolution.height,
        },
        "fps": fps,
        "sample_rate": timeline.settings.sample_rate,
        "extra": dict(timeline.metadata or {}),
    }
    for track in timeline.tracks:
        otio_tl.tracks.append(_track_to_otio(track, fps))
    for marker in timeline.markers:
        otio_tl.markers.append(_marker_to_otio(marker, fps))
    return otio_tl


# ============================================================
# 导入：OTIO → Timeline
# ============================================================

def _meta_of(item: Any) -> Dict[str, Any]:
    try:
        return _plain(dict(item.metadata.get(_NS) or {}))
    except Exception:
        return {}


def _clip_from_otio(otio_clip: Any, meta: Dict[str, Any], fps: float) -> Clip:
    tr = getattr(otio_clip, "source_range", None)
    src_start = _seconds(tr.start_time, fps) if tr else 0.0
    src_dur = _seconds(tr.duration, fps) if tr else 0.0
    start = float(meta.get("timeline_start", 0.0))
    end = float(meta.get("timeline_end", start + src_dur))
    transform = meta.get("transform") or {}
    try:
        clip_type = ClipType(meta.get("type", "video"))
    except ValueError:
        clip_type = ClipType.VIDEO
    try:
        blend = BlendMode(meta.get("blend_mode", "normal"))
    except ValueError:
        blend = BlendMode.NORMAL
    return Clip(
        id=meta.get("id") or getattr(otio_clip, "name", "") or "clip",
        name=getattr(otio_clip, "name", "") or "",
        type=clip_type,
        source=_media_url(otio_clip),
        range=TimeRange(start=start, end=end),
        source_range=TimeRange(start=src_start, end=src_start + src_dur),
        transform=ClipTransform(
            x=transform.get("x", 0.0),
            y=transform.get("y", 0.0),
            scale_x=transform.get("scale_x", 1.0),
            scale_y=transform.get("scale_y", 1.0),
            rotation=transform.get("rotation", 0.0),
            opacity=transform.get("opacity", 1.0),
            anchor_x=transform.get("anchor_x", 0.5),
            anchor_y=transform.get("anchor_y", 0.5),
        ),
        blend_mode=blend,
        volume=float(meta.get("volume", 1.0)),
        properties=[
            ClipProperty(
                name=p.get("name", ""),
                default_value=p.get("default_value"),
                keyframes=[
                    Keyframe(
                        time=float(k.get("time", 0.0)),
                        value=k.get("value"),
                        interpolation=_kp_interp(k.get("interpolation", "linear")),
                    )
                    for k in p.get("keyframes", [])
                ],
            )
            for p in meta.get("properties", [])
        ],
        effects=list(meta.get("effects", []) or []),
        locked=bool(meta.get("locked", False)),
        visible=bool(meta.get("visible", True)),
        muted=bool(meta.get("muted", False)),
        color=meta.get("color", ""),
        notes=meta.get("notes", ""),
        metadata=_plain(meta.get("extra", {}) or {}),
    )


def _kp_interp(value: Any) -> KeyframeInterpolation:
    try:
        return KeyframeInterpolation(value)
    except ValueError:
        return KeyframeInterpolation.LINEAR


def _media_url(otio_clip: Any) -> str:
    ref = getattr(otio_clip, "media_reference", None)
    url = getattr(ref, "target_url", "") if ref is not None else ""
    if not url:
        return ""
    if url.startswith("file://"):
        from urllib.parse import unquote, urlparse

        return unquote(urlparse(url).path)
    return url


def otio_to_timeline(otio_tl: Any, fps: Optional[float] = None) -> Timeline:
    """OTIO Timeline → 项目 Timeline。"""
    tl_meta = _meta_of(otio_tl)
    fps = float(fps or tl_meta.get("fps") or _DEFAULT_FPS)
    res = _plain(tl_meta.get("resolution") or {})
    tracks: List[Track] = []
    for otio_track in _iter_children(otio_tl.tracks):
        tracks.append(_track_from_otio(otio_track, fps))
    markers = [
        Marker(
            id=_meta_of(m).get("id") or f"marker_{i}",
            time=_seconds(m.marked_range.start_time, fps) if m.marked_range else 0.0,
            name=m.name or "",
            type=_meta_of(m).get("type", "marker"),
            notes=_meta_of(m).get("notes", ""),
        )
        for i, m in enumerate(getattr(otio_tl, "markers", []) or [])
    ]
    return Timeline(
        id=tl_meta.get("id", ""),
        name=tl_meta.get("name") or getattr(otio_tl, "name", "") or "",
        version=tl_meta.get("version", "1.0.0"),
        settings=TimelineSettings(
            resolution=Resolution(
                width=int(res.get("width", 1920)), height=int(res.get("height", 1080))
            ),
            fps=fps,
            sample_rate=int(tl_meta.get("sample_rate", 44100)),
        ),
        tracks=tracks,
        markers=markers,
        author=tl_meta.get("author", ""),
        description=tl_meta.get("description", ""),
        tags=list(_plain(tl_meta.get("tags", [])) or []),
        metadata=_plain(tl_meta.get("extra", {}) or {}),
    )


def _iter_children(stack: Any):
    try:
        return list(getattr(stack, "children", None) or stack or [])
    except Exception:
        return []


def _plain(obj: Any) -> Any:
    """把 OTIO 的 ``AnyDictionary`` / ``AnyVector`` 递归转成纯 Python dict/list。

    OTIO 反序列化出的 metadata 是 ``AnyDictionary``（MutableMapping），
    **不是** ``dict`` 子类，直接塞进 ``Timeline.metadata`` 会导致
    ``to_json()`` 抛 ``TypeError: Object of type AnyDictionary is not JSON serializable``。
    故所有从 OTIO 读出的 metadata 都先过一遍本函数。
    """
    from collections.abc import Mapping, Sequence

    if isinstance(obj, Mapping):
        return {str(k): _plain(v) for k, v in obj.items()}
    if isinstance(obj, Sequence) and not isinstance(obj, (str, bytes, bytearray)):
        return [_plain(v) for v in obj]
    return obj


def _track_from_otio(otio_track: Any, fps: float) -> Track:
    meta = _meta_of(otio_track)
    try:
        ttype = TrackType(meta.get("type", "video"))
    except ValueError:
        ttype = TrackType.AUDIO if getattr(otio_track, "kind", "") == "Audio" else TrackType.VIDEO
    track = Track(
        id=meta.get("id") or getattr(otio_track, "name", "") or "track",
        name=getattr(otio_track, "name", "") or "",
        type=ttype,
        locked=bool(meta.get("locked", False)),
        visible=bool(meta.get("visible", True)),
        muted=bool(meta.get("muted", False)),
        solo=bool(meta.get("solo", False)),
        height=int(meta.get("height", 60)),
        collapsed=bool(meta.get("collapsed", False)),
        metadata=_plain(meta.get("extra", {}) or {}),
    )
    cursor = 0.0
    for child in _iter_children(otio_track):
        schema = getattr(child, "schema_name", lambda: "")()
        if schema == "Gap":
            tr = getattr(child, "source_range", None)
            if tr is not None:
                cursor += _seconds(tr.duration, fps)
            continue
        if schema == "Clip":
            cmeta = _meta_of(child)
            clip = _clip_from_otio(child, cmeta, fps)
            if "timeline_start" not in cmeta:  # 无我方 metadata 的外部 OTIO：按顺序推导
                src = getattr(child, "source_range", None)
                dur = _seconds(src.duration, fps) if src else 0.0
                clip.range = TimeRange(start=cursor, end=cursor + dur)
            cursor = max(cursor, float(clip.range.end))
            track.add_clip(clip)
    return track


# ============================================================
# EDL 单轨收敛（CMX3600 只认一条视频轨）
# ============================================================

#: 只支持单条视频轨的适配器（实测 cmx_3600 多轨会 NotSupportedError）
_EDL_ADAPTERS = frozenset({"cmx_3600"})


def _is_edl(path: str, adapter: Optional[str]) -> bool:
    if adapter:
        return adapter in _EDL_ADAPTERS
    return os.path.splitext(str(path))[1].lower() == ".edl"


def _edl_single_track(otio_tl: Any):
    """为 CMX3600(EDL) 收敛出「单条视频轨」时间线。

    EDL 格式本身无法表达多视频轨（cmx_3600 会直接 ``NotSupportedError``）。
    此处取**片段最多的视频轨**为「主力轨」，其余视频轨的数量与被丢弃的轨名
    写进 metadata 并记录日志 —— **显式告知，不静默丢弃**。
    """
    otio = _otio()
    video_tracks = [
        t for t in _iter_children(otio_tl.tracks) if getattr(t, "kind", "") == "Video"
    ]
    if len(video_tracks) <= 1:
        return otio_tl  # 0/1 条：原样交给适配器（空时间线仍由其自行报错，属真实情况）

    primary = max(video_tracks, key=lambda t: len(_iter_children(t)))
    dropped = [getattr(t, "name", "") or "?" for t in video_tracks if t is not primary]
    subset = otio.schema.Timeline(name=getattr(otio_tl, "name", "") or "ShiguangEDL")
    base_meta = dict(otio_tl.metadata.get(_NS) or {})
    base_meta["edl_primary_track"] = getattr(primary, "name", "")
    base_meta["edl_dropped_video_tracks"] = dropped
    subset.metadata.update(otio_tl.metadata)
    subset.metadata[_NS] = base_meta
    subset.tracks.append(primary.deepcopy())
    for m in getattr(otio_tl, "markers", []) or []:
        subset.markers.append(m.deepcopy())
    logger.warning(
        "EDL(CMX3600) 仅支持单条视频轨：取主力轨 %r（%d 个片段），"
        "已丢弃其余 %d 条视频轨 %s；如需保留请改用 FCPXML / OTIO 导出。",
        getattr(primary, "name", ""), len(_iter_children(primary)), len(dropped), dropped,
    )
    return subset


# ============================================================
# 顶层出入口
# ============================================================

def write_inprocess(timeline: Timeline, path: str, adapter: Optional[str] = None,
                    rate: Optional[float] = None) -> str:
    """**仅供子进程 worker 调用**：真正写盘（此处才 import opentimelineio）。"""
    otio = _otio()
    otio_tl = timeline_to_otio(timeline, rate=rate)
    if _is_edl(path, adapter):
        otio_tl = _edl_single_track(otio_tl)
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    otio.adapters.write_to_file(otio_tl, path, adapter_name=adapter)
    return path


def read_inprocess(path: str, adapter: Optional[str] = None) -> Timeline:
    """**仅供子进程 worker 调用**：真正读盘。

    显式传 ``adapter`` 很关键：OTIO 默认按扩展名挑适配器，而 ``.fcpxml``
    并非 fcp_xml 适配器注册的扩展名（它只认 ``.xml``），不指定会抛
    ``NoKnownAdapterForExtensionError``。
    """
    otio = _otio()
    otio_tl = otio.adapters.read_from_file(path, adapter_name=adapter)
    return otio_to_timeline(otio_tl)


_INSTALL_HINT = (
    "请执行：pip install opentimelineio"
    "（EDL / FCPXML 另需 pip install otio-cmx3600-adapter otio-fcp-adapter）"
)


def export_otio(timeline: Timeline, path: str, adapter: Optional[str] = None) -> str:
    """把项目 Timeline 写出为 OTIO / EDL / FCPXML（按扩展名或 adapter 指定）。

    走**独立子进程**完成（主进程不得 import opentimelineio，见 :func:`_run_worker`）。
    返回写出的文件路径；失败抛 RuntimeError（含可操作指引）。
    """
    if not is_available():
        raise RuntimeError(f"未安装 opentimelineio，无法导出 OTIO/EDL/FCPXML。{_INSTALL_HINT}")
    import tempfile

    fd, tmp_json = tempfile.mkstemp(suffix=".json", prefix="sg_otio_")
    os.close(fd)
    try:
        with open(tmp_json, "w", encoding="utf-8") as fh:
            fh.write(timeline.to_json())
        args = ["export", tmp_json, os.path.abspath(path)]
        if adapter:
            args.append(adapter)
        rc, _out, err = _run_worker(args)
        if rc != 0:
            name = adapter or os.path.splitext(path)[1].lstrip(".") or "otio"
            avail = "、".join(available_export_formats()) or "（无）"
            raise RuntimeError(
                f"OTIO 导出失败（适配器 {name}）：{err.strip()}\n当前可用适配器：{avail}"
            )
    finally:
        _safe_unlink(tmp_json)
    logger.info("OTIO 导出成功: %s", path)
    return path


def import_otio(path: str, adapter: Optional[str] = None) -> Timeline:
    """从 OTIO / EDL / FCPXML 读入为项目 Timeline（走独立子进程）。

    ``adapter`` 可显式指定（如 ``fcp_xml``）——``.fcpxml`` 不是 OTIO 注册扩展名，
    按扩展名自动识别会失败；不传则交由 OTIO 自行判断。
    """
    if not is_available():
        raise RuntimeError(f"未安装 opentimelineio，无法读取 OTIO/EDL/FCPXML。{_INSTALL_HINT}")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"时间线文件不存在：{path}")
    import tempfile

    fd, tmp_json = tempfile.mkstemp(suffix=".json", prefix="sg_otio_")
    os.close(fd)
    try:
        args = ["import", os.path.abspath(path), tmp_json]
        if adapter:
            args.append(adapter)
        rc, _out, err = _run_worker(args)
        if rc != 0:
            raise RuntimeError(f"OTIO 读取失败：{err.strip()}")
        with open(tmp_json, "r", encoding="utf-8") as fh:
            return Timeline.from_json(fh.read())
    finally:
        _safe_unlink(tmp_json)


def otio_to_json_string(timeline: Timeline) -> str:
    """产出 OTIO 原生 JSON 文本（走独立子进程，不落盘）。"""
    import tempfile

    fd, tmp_out = tempfile.mkstemp(suffix=".otio", prefix="sg_otio_")
    os.close(fd)
    try:
        export_otio(timeline, tmp_out, adapter="otio_json")
        with open(tmp_out, "r", encoding="utf-8") as fh:
            return fh.read()
    finally:
        _safe_unlink(tmp_out)


def roundtrip_ok(timeline: Timeline) -> bool:
    """自检：Timeline → OTIO → Timeline 后轨道 / 片段数守恒（走子进程）。"""
    import tempfile

    fd, tmp_out = tempfile.mkstemp(suffix=".otio", prefix="sg_otio_")
    os.close(fd)
    try:
        export_otio(timeline, tmp_out)
        back = import_otio(tmp_out)
    except Exception:
        logger.debug("OTIO 往返自检失败", exc_info=True)
        return False
    finally:
        _safe_unlink(tmp_out)
    n0 = sum(len(t.clips) for t in timeline.tracks)
    n1 = sum(len(t.clips) for t in back.tracks)
    return n0 == n1 and len(timeline.tracks) == len(back.tracks)

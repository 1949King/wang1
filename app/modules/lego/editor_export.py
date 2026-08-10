# -*- coding: utf-8 -*-
"""多轨导出收尾（从 editor_module 抽出）。

叠上层视频 → 混独立音频。EditorModule 通过薄包装调用，降低上帝类体积。
不改播放/画布/变换 bake 冻结区。
"""
from __future__ import annotations

import os
import logging
import subprocess
import shutil
import tempfile
from typing import Any, Callable, Dict, List, Optional, Protocol

logger = logging.getLogger(__name__)


class _EditorExportHost(Protocol):
    _clips: list
    _timeline_widget: Any
    _master_volume: float
    _pip_x: Any
    _pip_y: Any
    _pip_size: Any

    def _preview_frame_size(self) -> tuple: ...
    def _track_volume_for_clip(self, clip) -> float: ...
    def _is_linked_video_audio_clip(self, clip) -> bool: ...
    def _notify_edit(self, msg: str) -> None: ...
    def _probe_video_duration(self, file_path: str) -> float: ...


def is_export_audio_clip(editor: _EditorExportHost, c: Optional[dict]) -> bool:
    if not c:
        return False
    if str(c.get("type", "")).lower() == "audio":
        return True
    ti = int(c.get("track", 0) or 0)
    tw = getattr(editor, "_timeline_widget", None)
    if tw is not None:
        tracks = getattr(tw, "_tracks", []) or []
        if 0 <= ti < len(tracks) and tracks[ti].get("type") == "audio":
            return True
    path = str(c.get("path") or "").lower()
    return path.endswith((".mp3", ".wav", ".aac", ".m4a", ".flac", ".ogg"))


def collect_export_audio_clips(editor: _EditorExportHost) -> list:
    """独立音频轨（跳过与视频联动的内嵌音）。"""
    out = []
    for c in getattr(editor, "_clips", []) or []:
        if not is_export_audio_clip(editor, c):
            continue
        if editor._is_linked_video_audio_clip(c):
            continue
        if not c.get("path") or not os.path.exists(c.get("path")):
            continue
        item = dict(c)
        item["volume"] = float(c.get("volume", 1.0) or 1.0) * editor._track_volume_for_clip(c)
        out.append(item)
    return out


def collect_export_overlay_clips(editor: _EditorExportHost, base_track: int) -> list:
    """高于主视频轨的视频片，用于归一化坐标叠轨导出。"""
    def_x, def_y, def_s = 0.75, 0.80, 0.35
    try:
        if hasattr(editor, "_pip_x") and editor._pip_x:
            def_x = float(editor._pip_x.value()) / 100.0
        if hasattr(editor, "_pip_y") and editor._pip_y:
            def_y = float(editor._pip_y.value()) / 100.0
        if hasattr(editor, "_pip_size") and editor._pip_size:
            def_s = float(editor._pip_size.value()) / 100.0
    except Exception as e:
        logger.debug("读取PIP默认值失败: %s", e)
    fw, fh = 1920, 1080
    try:
        sf = getattr(editor, "_sequence_format", None)
        if sf is not None and int(getattr(sf, "width", 0) or 0) > 0:
            fw, fh = int(sf.width), int(sf.height)
        else:
            fw, fh = editor._preview_frame_size()
    except Exception as e:
        logger.debug("获取预览帧尺寸失败: %s", e)
    try:
        from app.modules.lego.clip_transform import normalize_clip_transform
    except Exception:
        from app.modules.lego.video_processor import normalize_clip_transform
    try:
        from app.modules.lego.video_processor import collect_clip_keyframes
    except Exception:
        collect_clip_keyframes = None  # type: ignore

    defaults = {"x": def_x, "y": def_y, "scale": def_s, "opacity": 1.0}
    out = []
    for c in getattr(editor, "_clips", []) or []:
        if is_export_audio_clip(editor, c):
            continue
        if not c.get("path") or not os.path.exists(c.get("path")):
            continue
        ti = int(c.get("track", 0) or 0)
        if ti <= base_track:
            continue
        item = dict(c)
        tf = normalize_clip_transform(c, fw, fh, defaults)
        item["opacity"] = tf["opacity"]
        item["pip_x"] = tf["x"]
        item["pip_y"] = tf["y"]
        item["pip_scale"] = tf["scale"]
        item["rotation"] = tf.get("rotation", 0)
        item["transform"] = {
            "x": tf["x"], "y": tf["y"],
            "scale": tf["scale"], "opacity": tf["opacity"],
            "rotation": tf.get("rotation", 0),
            "anchor": tf.get("anchor", "中心"),
        }
        if collect_clip_keyframes is not None:
            x_kfs = collect_clip_keyframes(c, "x")
            y_kfs = collect_clip_keyframes(c, "y")
            sc_kfs = collect_clip_keyframes(c, "scale")
            rot_kfs = collect_clip_keyframes(c, "rotation")
            op_kfs = collect_clip_keyframes(c, "opacity")
            if x_kfs or y_kfs or sc_kfs or rot_kfs or op_kfs:
                item["_prebake_transform"] = True
                item["_x_kfs"] = x_kfs
                item["_y_kfs"] = y_kfs
                item["_sc_kfs"] = sc_kfs
                item["_rot_kfs"] = rot_kfs
                if op_kfs:
                    item["_op_kfs"] = op_kfs
        out.append(item)
    return sorted(
        out,
        key=lambda x: (int(x.get("track", 0) or 0), float(x.get("start_time", 0) or 0)),
    )


def prebake_overlay_clips_for_export(
    overlays: list,
    frame_w: int = 1920,
    frame_h: int = 1080,
    ffmpeg_path: str = "ffmpeg",
) -> list:
    """叠轨 KF：默认保留关键帧供连续 overlay；``_force_segment_overlay`` 时拆段。"""
    del frame_w, frame_h, ffmpeg_path  # 连续路径不需要；分段路径保留签名兼容
    if not overlays:
        return overlays
    need_fallback = any(
        bool(it.get("_force_segment_overlay")) and it.get("_prebake_transform")
        for it in overlays
    )
    if not need_fallback:
        out = []
        for item in overlays:
            neu = dict(item)
            neu.pop("_prebake_transform", None)
            out.append(neu)
        return out
    try:
        from app.modules.lego.video_processor import _build_transform_segments
    except Exception:
        return overlays
    out = []
    for item in overlays:
        if not (item.get("_prebake_transform") and item.get("_force_segment_overlay")):
            neu = dict(item)
            neu.pop("_prebake_transform", None)
            out.append(neu)
            continue
        in_p = max(0.0, float(item.get("in_point", 0) or 0))
        out_p = float(item.get("out_point", 0) or 0)
        if out_p <= in_p + 0.01:
            out_p = in_p + max(0.05, float(item.get("duration", 1) or 1))
        local_dur = max(0.05, out_p - in_p)
        tf = item.get("transform") or {}
        try:
            segs = _build_transform_segments(
                local_dur,
                scale=float(tf.get("scale", item.get("pip_scale", 0.35)) or 0.35),
                x=float(tf.get("x", item.get("pip_x", 0.75)) or 0.75),
                y=float(tf.get("y", item.get("pip_y", 0.80)) or 0.80),
                rotation=float(tf.get("rotation", item.get("rotation", 0)) or 0),
                scale_keyframes=item.get("_sc_kfs") or None,
                x_keyframes=item.get("_x_kfs") or None,
                y_keyframes=item.get("_y_kfs") or None,
                rotation_keyframes=item.get("_rot_kfs") or None,
            )
        except Exception as e:
            print(f"叠轨关键帧分段失败，回退静态: {e}")
            neu = dict(item)
            neu.pop("_prebake_transform", None)
            out.append(neu)
            continue
        base_st = float(item.get("start_time", 0) or 0)
        for t0, t1, sc, px, py, rot in segs:
            neu = dict(item)
            neu["in_point"] = in_p + t0
            neu["out_point"] = in_p + t1
            neu["start_time"] = base_st + t0
            neu["duration"] = max(0.05, t1 - t0)
            neu["pip_x"] = px
            neu["pip_y"] = py
            neu["pip_scale"] = sc
            neu["rotation"] = rot
            neu["transform"] = {
                "x": px, "y": py, "scale": sc,
                "opacity": float(item.get("opacity", 1.0) or 1.0),
                "rotation": rot,
            }
            for k in (
                "_prebake_transform", "_x_kfs", "_y_kfs", "_sc_kfs", "_rot_kfs",
                "_baked_temp", "_trim_temp", "_force_segment_overlay",
            ):
                neu.pop(k, None)
            out.append(neu)
    return out


def finalize_multitrack_export(
    editor: _EditorExportHost,
    video_path: str,
    ffmpeg_path: str = "ffmpeg",
) -> str:
    """主线成片后：叠上层视频轨 → 混入独立音频轨。失败则保留原片并提示。"""
    if not video_path or not os.path.exists(video_path):
        return video_path
    current = video_path
    warnings: List[str] = []
    notify: Callable[[str], None] = getattr(editor, "_notify_edit", lambda _m: None)

    base_track = 0
    video_clips = [
        c for c in (getattr(editor, "_clips", []) or [])
        if c.get("path") and os.path.exists(c.get("path")) and not is_export_audio_clip(editor, c)
    ]
    if video_clips:
        base_track = min(int(c.get("track", 0) or 0) for c in video_clips)
    overlays = collect_export_overlay_clips(editor, base_track)
    if overlays:
        notify(f"正在叠轨导出（{len(overlays)} 层）…")
        baked_temps: List[str] = []
        try:
            from app.modules.lego.video_processor import overlay_timeline_videos
            ov_out = tempfile.mktemp(suffix="_ov.mp4")
            bw, bh = 1920, 1080
            try:
                import cv2
                cap = cv2.VideoCapture(current)
                if cap.isOpened():
                    bw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or bw
                    bh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or bh
                cap.release()
            except Exception as e:
                logger.debug("读取视频分辨率失败: %s", e)
            overlays_raw = [dict(x) for x in overlays]
            overlays = prebake_overlay_clips_for_export(overlays, bw, bh, ffmpeg_path)
            for it in overlays:
                if it.get("_baked_temp"):
                    baked_temps.append(it["_baked_temp"])
                if it.get("_trim_temp"):
                    baked_temps.append(it["_trim_temp"])
            ok_ov = overlay_timeline_videos(current, overlays, ov_out, ffmpeg_path, (bw, bh))
            if not ok_ov:
                print("叠轨连续表达式失败，回退分段静态")
                for it in overlays_raw:
                    if it.get("_x_kfs") or it.get("_y_kfs") or it.get("_sc_kfs") or it.get("_rot_kfs"):
                        it["_prebake_transform"] = True
                        it["_force_segment_overlay"] = True
                overlays = prebake_overlay_clips_for_export(
                    overlays_raw, bw, bh, ffmpeg_path
                )
                try:
                    if os.path.exists(ov_out):
                        os.remove(ov_out)
                except Exception as e:
                    logger.debug("删除叠轨临时文件失败: %s", e)
                ok_ov = overlay_timeline_videos(
                    current, overlays, ov_out, ffmpeg_path, (bw, bh)
                )
            if ok_ov:
                if current != video_path:
                    try:
                        os.remove(current)
                    except Exception as e:
                        logger.debug("删除原视频临时文件失败: %s", e)
                current = ov_out
                notify("叠轨完成")
            else:
                warnings.append("上层视频叠轨失败，已保留主轨画面")
                try:
                    if os.path.exists(ov_out):
                        os.remove(ov_out)
                except Exception as e:
                    logger.debug("删除叠轨失败临时文件失败: %s", e)
        except Exception as e:
            warnings.append(f"叠轨跳过: {e}")
            print(f"叠轨导出跳过: {e}")
        finally:
            for tp in baked_temps:
                try:
                    if tp and os.path.exists(tp):
                        os.remove(tp)
                except Exception as e:
                    logger.debug("清理临时文件失败: %s", e)

    audio_clips = collect_export_audio_clips(editor)
    if audio_clips:
        notify(f"正在混入音频轨（{len(audio_clips)} 段）…")
        try:
            from app.modules.lego.video_processor import mix_timeline_audio
            mix_out = tempfile.mktemp(suffix="_mix.mp4")
            master = float(getattr(editor, "_master_volume", 1.0) or 1.0)
            if mix_timeline_audio(
                current, audio_clips, mix_out, ffmpeg_path, master_volume=master
            ):
                if current != video_path:
                    try:
                        os.remove(current)
                    except Exception as e:
                        logger.debug("删除混音前原视频临时文件失败: %s", e)
                try:
                    shutil.move(mix_out, video_path)
                    notify("音频轨混音完成")
                    if warnings:
                        notify("；".join(warnings))
                    return video_path
                except Exception:
                    if warnings:
                        notify("；".join(warnings))
                    return mix_out
            warnings.append("独立音频混音失败，成片可能缺少 BGM")
            try:
                if os.path.exists(mix_out):
                    os.remove(mix_out)
            except Exception as e:
                logger.debug("删除混音失败临时文件失败: %s", e)
        except Exception as e:
            warnings.append(f"音频轨跳过: {e}")
            print(f"音频轨导出跳过: {e}")

    if warnings:
        notify("；".join(warnings))
    if current != video_path:
        try:
            shutil.move(current, video_path)
            return video_path
        except Exception:
            return current
    return video_path


def build_edited_video(editor, output_path: str) -> bool:
    """依据 self._clips 的 in/out 点，从源视频裁剪各段、烘焙滤镜/转场，再按时间顺序拼接成成品。

    工具栏的剪切(成段)/删除(缺段)/复制粘贴(多段) 以及 滤镜/转场 现在都会真实反映在导出的视频里
    （此前滤镜/转场仅在预览里显示，不进成品）。
    返回是否成功。
    """
    clips = [c for c in getattr(editor, "_clips", [])
             if c.get("path") and os.path.exists(c.get("path"))]
    # 导出主故事线：视频轨；音频/上层轨在 _finalize_multitrack_export 处理
    clips = [c for c in clips if not is_export_audio_clip(editor, c)]
    clips = sorted(clips, key=lambda c: (int(c.get("track", 0) or 0), float(c.get("start_time", 0))))
    # 同时刻多层：最低轨作主线；上层叠轨在 finalize 中画中画
    if clips:
        base_track = min(int(c.get("track", 0) or 0) for c in clips)
        clips = [c for c in clips if int(c.get("track", 0) or 0) == base_track]
    clips = sorted(clips, key=lambda c: float(c.get("start_time", 0)))
    clips = [c for c in clips
             if float(c.get("out_point", 0)) - float(c.get("in_point", 0)) > 0.01]
    if not clips:
        return False
    import tempfile
    try:
        from app.modules.lego.video_processor import (
            trim_video, merge_videos, apply_video_filter,
            merge_with_transitions, map_filter_to_vf,
            bake_clip_transform, collect_clip_keyframes,
        )
        from app.core.editor_scheduler import editor_scheduler
        ffmpeg_path = getattr(editor_scheduler.get_video_processor(), "ffmpeg_path", "ffmpeg")
    except Exception:
        try:
            from app.modules.lego.video_processor import (
                trim_video, merge_videos, apply_video_filter,
                merge_with_transitions, map_filter_to_vf,
                bake_clip_transform, collect_clip_keyframes,
            )
        except Exception:
            return False
        ffmpeg_path = "ffmpeg"
    tmp_segments = []
    filtered_segments = []
    durations = []
    transitions = []
    try:
        # 记录上一段在时间线上的结束位置（用于处理空隙）
        last_end_time = 0.0
        # 获取视频分辨率用于生成黑场
        first_clip_path = clips[0].get("path") if clips else ""
        frame_width, frame_height = 1920, 1080
        if first_clip_path:
            try:
                import cv2
                cap = cv2.VideoCapture(first_clip_path)
                if cap.isOpened():
                    frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                cap.release()
            except Exception as e:
                logger.debug("读取视频分辨率失败: %s", e)

        for clip in clips:
            src = clip.get("path")
            # 导出禁止误用代理文件（预览用 proxy_path，成片必须原片）
            try:
                from app.modules.lego.editor_preview_ux import is_proxy_path
                if is_proxy_path(str(src or "")):
                    alt = str(clip.get("original_path") or "")
                    if alt and os.path.isfile(alt):
                        src = alt
                        clip["path"] = alt
                    else:
                        logger.error("导出跳过疑似代理路径片段: %s", src)
                        continue
            except Exception:
                pass
            dur = editor._probe_video_duration(src) or 0.0
            in_p = float(clip.get("in_point", 0))
            out_p = float(clip.get("out_point", dur))
            clip_start_time = float(clip.get("start_time", 0))

            # ── 处理时间线空隙：当前片段起点与上一段终点之间的空白 ──
            gap_duration = clip_start_time - last_end_time
            if gap_duration > 0.01:
                # 生成黑场视频填充空隙
                gap_seg = tempfile.mktemp(suffix=".mp4")
                try:
                    cmd = [
                        ffmpeg_path, "-y",
                        "-f", "lavfi",
                        "-i", f"color=c=black:s={frame_width}x{frame_height}:r=30:d={gap_duration}",
                        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo:d=" + str(gap_duration),
                        "-c:v", "libx264", "-c:a", "aac",
                        "-shortest", gap_seg
                    ]
                    r = subprocess.run(
                        cmd, capture_output=True, timeout=600,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                    )
                    if r.returncode == 0 and os.path.exists(gap_seg):
                        tmp_segments.append(gap_seg)
                        filtered_segments.append(gap_seg)
                        durations.append(gap_duration)
                        if len(filtered_segments) >= 2:
                            transitions.append({"type": "淡入淡出", "duration": 0.1})
                except Exception as e:
                    print(f"生成空隙黑场失败: {e}")

            if out_p - in_p <= 0.01:
                continue
            seg = tempfile.mktemp(suffix=".mp4")
            if not trim_video(src, seg, in_p, out_p, ffmpeg_path):
                continue
            tmp_segments.append(seg)
            # ── 烘焙滤镜：把预览级 filter 真正写进视频段 ──
            # 安全读取 effects：可能是 dict（已应用滤镜/调节）或 list/缺失
            _eff = clip.get("effects")
            if not isinstance(_eff, dict):
                _eff = {}
            _filter_name = clip.get("filter") or _eff.get("filter", "")
            _intensity = float(clip.get("filter_intensity", _eff.get("filter_intensity", 0.7)))
            vf = map_filter_to_vf(
                _filter_name,
                _intensity,
                _eff.get("color_params"),
            )
            final_seg = seg
            if vf:
                fseg = tempfile.mktemp(suffix=".mp4")
                if apply_video_filter(seg, fseg, vf, ffmpeg_path):
                    tmp_segments.append(fseg)
                    final_seg = fseg
            # 片段速度
            speed = float(clip.get("speed", 1.0) or 1.0)
            if abs(speed - 1.0) > 0.01:
                sseg = tempfile.mktemp(suffix=".mp4")
                try:
                    cmd = [
                        ffmpeg_path, "-y", "-i", final_seg,
                        "-filter:v", f"setpts={1.0/speed}*PTS",
                        "-filter:a", f"atempo={max(0.5, min(2.0, speed))}",
                        "-c:v", "libx264", "-c:a", "aac", sseg,
                    ]
                    r = subprocess.run(
                        cmd, capture_output=True, timeout=600,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                    )
                    if r.returncode == 0 and os.path.exists(sseg):
                        tmp_segments.append(sseg)
                        final_seg = sseg
                except Exception as e:
                    print(f"变速烘焙失败: {e}")
            # 音量（片段 × 轨道）；若有 volume 关键帧则交给 transform 烘焙
            vol = float(clip.get("volume", 1.0) or 1.0) * editor._track_volume_for_clip(clip)
            vol_kfs = collect_clip_keyframes(clip, "volume")
            op_kfs = collect_clip_keyframes(clip, "opacity")
            if not vol_kfs and abs(vol - 1.0) > 0.01:
                vseg = tempfile.mktemp(suffix=".mp4")
                try:
                    cmd = [
                        ffmpeg_path, "-y", "-i", final_seg,
                        "-af", f"volume={vol}",
                        "-c:v", "copy", vseg,
                    ]
                    r = subprocess.run(
                        cmd, capture_output=True, timeout=600,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                    )
                    if r.returncode == 0 and os.path.exists(vseg):
                        tmp_segments.append(vseg)
                        final_seg = vseg
                except Exception as e:
                    print(f"音量烘焙失败: {e}")

            # 缩放 / 不透明度（静态 + 关键帧）→ 成片
            scale = 1.0
            opacity = 1.0
            try:
                scale = float(clip.get("scale", 1.0) or 1.0)
                if isinstance(_eff, dict) and _eff.get("scale") is not None:
                    scale = float(_eff.get("scale") or scale)
            except (TypeError, ValueError):
                scale = 1.0
            try:
                opacity = float(clip.get("opacity", 1.0) or 1.0)
                if isinstance(_eff, dict) and _eff.get("opacity") is not None:
                    opacity = float(_eff.get("opacity") or opacity)
            except (TypeError, ValueError):
                opacity = 1.0
            sc_kfs = collect_clip_keyframes(clip, "scale")
            x_kfs = collect_clip_keyframes(clip, "x")
            y_kfs = collect_clip_keyframes(clip, "y")
            rot_kfs = collect_clip_keyframes(clip, "rotation")
            try:
                rotation = float(clip.get("rotation", 0) or 0)
                if isinstance(_eff, dict) and _eff.get("rotation") is not None:
                    rotation = float(_eff.get("rotation") or rotation)
                tf = clip.get("transform") if isinstance(clip.get("transform"), dict) else {}
                if tf.get("rotation") is not None:
                    rotation = float(tf.get("rotation") or rotation)
            except (TypeError, ValueError):
                rotation = 0.0
            try:
                from app.modules.lego.clip_transform import normalize_clip_transform as _nct
                _tf0 = _nct(clip, frame_width, frame_height, {"x": 0.5, "y": 0.5, "scale": scale})
                pos_x = float(_tf0.get("x", 0.5))
                pos_y = float(_tf0.get("y", 0.5))
            except Exception:
                pos_x, pos_y = 0.5, 0.5
            # 音量关键帧：轨音量 × 关键帧值（片段 volume 由关键帧替代）
            xf_base_vol = float(editor._track_volume_for_clip(clip)) if vol_kfs else 1.0
            need_xf = (
                abs(scale - 1.0) > 0.01
                or opacity < 0.995
                or abs(rotation) > 0.05
                or abs(pos_x - 0.5) > 0.01
                or abs(pos_y - 0.5) > 0.01
                or len(op_kfs) >= 1
                or len(vol_kfs) >= 1
                or len(sc_kfs) >= 1
                or len(x_kfs) >= 1
                or len(y_kfs) >= 1
                or len(rot_kfs) >= 1
            )
            if need_xf:
                tseg = tempfile.mktemp(suffix="_xf.mp4")
                if bake_clip_transform(
                    final_seg,
                    tseg,
                    scale=scale,
                    opacity=opacity,
                    rotation=rotation,
                    x=pos_x,
                    y=pos_y,
                    frame_width=frame_width,
                    frame_height=frame_height,
                    opacity_keyframes=op_kfs or None,
                    volume_keyframes=vol_kfs or None,
                    scale_keyframes=sc_kfs or None,
                    x_keyframes=x_kfs or None,
                    y_keyframes=y_kfs or None,
                    rotation_keyframes=rot_kfs or None,
                    base_volume=xf_base_vol,
                    ffmpeg_path=ffmpeg_path,
                ):
                    tmp_segments.append(tseg)
                    final_seg = tseg
                else:
                    print("变换/关键帧烘焙跳过（保持原片）")

            filtered_segments.append(final_seg)
            seg_dur = (out_p - in_p) / max(0.05, speed)
            durations.append(seg_dur)
            # 更新上一段结束时间（用于下一段计算空隙）
            last_end_time = clip_start_time + seg_dur
            # 收集「本段与前一段」之间的转场（取本段记录的入场转场）
            if len(filtered_segments) >= 2:
                trans = clip.get("transition") or (clip.get("transitions") or [None])[-1]
                transitions.append(trans if isinstance(trans, dict) else
                                   {"type": "淡入淡出", "duration": 0.5})

        if not filtered_segments:
            return False
        if len(filtered_segments) == 1:
            import shutil
            shutil.copy(filtered_segments[0], output_path)
            return os.path.exists(output_path)
        # 存在转场则用 xfade 融合拼接，否则普通 concat
        if transitions:
            return merge_with_transitions(
                filtered_segments, transitions, output_path, ffmpeg_path, None, durations)
        return merge_videos(filtered_segments, output_path, ffmpeg_path)
    finally:
        for seg in tmp_segments:
            try:
                os.remove(seg)
            except Exception as _e:
                logger.warning("操作异常（已忽略）: %s", _e)


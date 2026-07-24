"""
MLT 风格专业视频引擎 (MLTEngine)
===============================
基于 MLT 架构理念，用 Python 实现的完整视频编辑引擎。

核心架构 (仿 MLT Producer-Playlist-Consumer 模型):
  Timeline → Track[] → Clip[] → Filter[] + Keyframe[]
                                          ↓
                                     Transition[]
                                          ↓
                                     Consumer (导出/预览)

底层: PyAV (帧精确) + FFmpeg CLI (编码)
"""
import os
import json
import time
import logging
import subprocess
import sys
import re as _re
from typing import Dict, List, Optional, Tuple, Callable, Union
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("AI短剧编辑器.mlt_engine")


# ============================================================
# 数据结构
# ============================================================

class BlendMode(Enum):
    """混合模式"""
    OVER = "over"       # 正常叠加(上遮下)
    ALPHA = "alpha"     # Alpha 混合
    ADD = "add"         # 加法混合
    SCREEN = "screen"   # 滤色
    MULTIPLY = "multiply"  # 正片叠底

class TransitionType(Enum):
    """转场类型"""
    FADE = "fade"           # 淡入淡出
    DISSOLVE = "dissolve"   # 交叉溶解
    WIPE_LEFT = "wipe_left"
    WIPE_RIGHT = "wipe_right"
    SLIDE_UP = "slide_up"
    SLIDE_DOWN = "slide_down"
    ZOOM_IN = "zoom_in"
    ZOOM_OUT = "zoom_out"
    NONE = "none"

class KeyframeInterpolation(Enum):
    """关键帧插值"""
    LINEAR = "linear"
    EASE_IN = "ease_in"
    EASE_OUT = "ease_out"
    EASE_IN_OUT = "ease_in_out"


@dataclass
class Keyframe:
    """关键帧"""
    frame: int            # 帧号
    value: float          # 值
    interpolation: KeyframeInterpolation = KeyframeInterpolation.LINEAR

@dataclass
class Filter:
    """滤镜/特效"""
    name: str              # brightness, contrast, saturation, blur, etc.
    params: Dict[str, float] = field(default_factory=dict)
    keyframes: Dict[str, List[Keyframe]] = field(default_factory=dict)

@dataclass
class Transition:
    """转场"""
    type: TransitionType = TransitionType.FADE
    duration: float = 0.5  # 秒

@dataclass
class Clip:
    """时间线上的片段"""
    source: str                    # 文件路径
    track_index: int = 0           # 所在轨道
    position: float = 0.0          # 在时间线上的起始位置(秒)
    duration: float = 0.0          # 持续时长(秒, 0=自动计算)
    in_point: float = 0.0          # 源文件内起始(秒)
    speed: float = 1.0             # 播放速度
    volume: float = 1.0            # 音量
    opacity: float = 1.0           # 不透明度
    filters: List[Filter] = field(default_factory=list)
    transition: Optional[Transition] = None
    blend: BlendMode = BlendMode.OVER
    meta: Dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.meta:
            try:
                from app.core.video_processing.pyav_engine import get_pyav_engine
                engine = get_pyav_engine()
                probe = engine.probe(self.source)
                if probe:
                    self.meta = {
                        "width": probe.width, "height": probe.height,
                        "fps": probe.fps, "duration": probe.duration,
                        "has_audio": probe.has_audio,
                    }
                    if self.duration <= 0:
                        self.duration = probe.duration - self.in_point
            except Exception:
                pass


@dataclass
class Track:
    """轨道"""
    index: int
    name: str = ""
    clips: List[Clip] = field(default_factory=list)
    muted: bool = False
    locked: bool = False
    blend: BlendMode = BlendMode.OVER

    @property
    def duration(self) -> float:
        if not self.clips:
            return 0.0
        return max((c.position + c.duration / c.speed) for c in self.clips)


@dataclass
class Timeline:
    """时间线 (MLT 的核心概念)"""
    name: str = "未命名项目"
    width: int = 1920
    height: int = 1080
    fps: float = 30.0
    tracks: List[Track] = field(default_factory=list)
    master_volume: float = 1.0

    @property
    def video_tracks(self) -> List[Track]:
        return self.tracks  # 目前所有轨道都含视频

    @property
    def duration(self) -> float:
        return max((t.duration for t in self.tracks), default=0.0)


# ============================================================
# MLT 风格引擎
# ============================================================

class MLTEngine:
    """MLT 风格视频编辑引擎 — 多轨时间线 + 关键帧 + 转场"""

    def __init__(self):
        self._timeline: Optional[Timeline] = None
        self._profiles = {
            "hd_1080p_30": (1920, 1080, 30),
            "hd_1080p_60": (1920, 1080, 60),
            "vertical_1080p_30": (1080, 1920, 30),   # 抖音/快手
            "vertical_1080p_60": (1080, 1920, 60),
            "square_1k_30": (1080, 1080, 30),         # 小红书
        }

    # ---- Timeline ----

    def create_timeline(self, name: str = "未命名",
                        profile: str = "hd_1080p_30") -> Timeline:
        """创建新时间线"""
        w, h, fps = self._profiles.get(profile, (1920, 1080, 30))
        self._timeline = Timeline(name=name, width=w, height=h, fps=fps)
        return self._timeline

    def add_track(self, name: str = "", blend: BlendMode = BlendMode.OVER) -> Track:
        """添加轨道"""
        if not self._timeline:
            self.create_timeline()
        idx = len(self._timeline.tracks)
        track = Track(index=idx, name=name or f"轨道{idx+1}", blend=blend)
        self._timeline.tracks.append(track)
        return track

    # ---- Clip ----

    def add_clip(self, source: str, track_index: int = 0,
                 position: float = 0, duration: float = 0,
                 in_point: float = 0, speed: float = 1.0,
                 volume: float = 1.0) -> Optional[Clip]:
        """向轨道添加片段"""
        if not self._timeline:
            self.create_timeline()

        # 确保轨道存在
        while len(self._timeline.tracks) <= track_index:
            self.add_track()

        clip = Clip(source=source, track_index=track_index,
                    position=position, duration=duration,
                    in_point=in_point, speed=speed, volume=volume)
        self._timeline.tracks[track_index].clips.append(clip)
        return clip

    # ---- Filter / Effect ----

    def add_filter(self, clip: Clip, name: str, params: Dict[str, float] = None) -> Filter:
        """给片段添加滤镜"""
        f = Filter(name=name, params=params or {})
        clip.filters.append(f)
        return f

    def set_keyframe(self, clip: Clip, property_name: str,
                     frame: int, value: float,
                     interpolation: KeyframeInterpolation = KeyframeInterpolation.LINEAR):
        """设置关键帧（用于动画属性：opacity, scale, position等）"""
        # 查找或创建该属性的关键帧列表
        kf_list = []
        for f in clip.filters:
            if property_name in f.keyframes:
                kf_list = f.keyframes[property_name]
                break
        if not kf_list:
            # 创建 opacity filter 存储通用关键帧
            kf_list = []
            clip.filters.append(Filter(name="_keyframes", keyframes={property_name: kf_list}))

        kf_list.append(Keyframe(frame=frame, value=value, interpolation=interpolation))
        kf_list.sort(key=lambda k: k.frame)

    # ---- Transition ----

    def add_transition(self, clip: Clip, type: TransitionType, duration: float = 0.5):
        """给片段入点添加转场"""
        clip.transition = Transition(type=type, duration=duration)

    # ---- 渲染 ----

    def render(self, output_path: str, codec: str = "libx264",
               crf: int = 23, preset: str = "medium",
               progress_cb: Callable = None) -> bool:
        """渲染完整时间线到视频文件"""
        if not self._timeline:
            logger.error("无时间线可渲染")
            return False

        tl = self._timeline
        total_frames = int(tl.duration * tl.fps)
        logger.info(f"渲染: {tl.width}x{tl.height}@{tl.fps}fps, "
                    f"{len(tl.tracks)}轨, {total_frames}帧")

        # 使用 FFmpeg 命令行构造复杂滤镜图
        cmd = self._build_render_command(output_path, codec, crf, preset)

        if not cmd:
            return False

        try:
            last_pct = 0
            creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                universal_newlines=True, encoding='utf-8', errors='ignore',
                creationflags=creationflags,
            )
            while True:
                line = process.stderr.readline()
                if not line and process.poll() is not None:
                    break
                if line and progress_cb:
                    m = _re.search(r'time=(\d+):(\d+):(\d+\.\d+)', line)
                    if m:
                        h, mn, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
                        elapsed = h * 3600 + mn * 60 + s
                        pct = min(99, elapsed / max(tl.duration, 0.1) * 100)
                        if pct > last_pct + 1:
                            last_pct = pct
                            try:
                                progress_cb(pct, 0, 0)
                            except TypeError:
                                progress_cb(pct)

            if progress_cb:
                try:
                    progress_cb(100, 0, 0)
                except TypeError:
                    progress_cb(100)

            return process.poll() == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 0

        except Exception as e:
            logger.error(f"渲染失败: {e}")
            return False

    def _build_render_command(self, output: str, codec: str,
                              crf: int, preset: str) -> Optional[List[str]]:
        """构建 FFmpeg 渲染命令"""
        tl = self._timeline
        sources: Dict[str, int] = {}

        # 收集所有唯一源文件
        for track in tl.tracks:
            for clip in track.clips:
                src = os.path.abspath(clip.source)
                if src not in sources:
                    sources[src] = len(sources)

        # 获取 ffmpeg 可执行文件路径
        try:
            from app.core.ffmpeg_utils import get_ffmpeg, detect_hardware_encoders
            ffmpeg_exe = get_ffmpeg()
        except ImportError:
            ffmpeg_exe = "ffmpeg"

        # 检测硬件编码器
        try:
            hw_enc = detect_hardware_encoders(ffmpeg_exe)
            if hw_enc and codec == "libx264":
                codec = hw_enc.get("h264", codec)
        except Exception:
            pass

        # 输入文件
        cmd = [ffmpeg_exe]
        for src in sorted(sources, key=sources.get):
            cmd += ["-i", src]

        # 构建滤镜图
        filter_parts = []
        overlay_chain = []

        for track_idx, track in enumerate(tl.tracks):
            for clip in track.clips:
                src_idx = sources[os.path.abspath(clip.source)]

                # Trim + speed
                chain = f"[{src_idx}:v]"
                if clip.in_point > 0:
                    chain += f"trim=start={clip.in_point}"
                if clip.duration > 0 and clip.speed > 0:
                    chain += f",trim=duration={clip.duration}"
                if clip.speed != 1.0:
                    chain += f",setpts=PTS/{clip.speed}"

                # Filters
                for f in clip.filters:
                    if f.name == "brightness":
                        chain += f",eq=brightness={f.params.get('value', 0)}"
                    elif f.name == "contrast":
                        chain += f",eq=contrast={f.params.get('value', 1.0)}"
                    elif f.name == "saturation":
                        chain += f",eq=saturation={f.params.get('value', 1.0)}"
                    elif f.name == "blur":
                        chain += f",boxblur={f.params.get('sigma', 2)}"

                # Scale to timeline size
                chain += f",scale={tl.width}:{tl.height}:force_original_aspect_ratio=decrease"
                chain += f",pad={tl.width}:{tl.height}:(ow-iw)/2:(oh-ih)/2"
                chain += f",format=yuva420p"

                # Transition (add fade in/out)
                if clip.transition and clip.transition.type != TransitionType.NONE:
                    dur_frames = int(clip.transition.duration * tl.fps)
                    chain += f",fade=in:0:{dur_frames},fade=out:{max(0, int(clip.duration*tl.fps) - dur_frames)}:{dur_frames}"

                tag = f"t{track_idx}c{len(overlay_chain)}"
                chain += f"[{tag}]"

                filter_parts.append(chain)
                overlay_chain.append(tag)

        if not filter_parts:
            return None

        # 单轨单片段：直接 trim + encode
        if len(tl.tracks) == 1 and len(tl.tracks[0].clips) == 1:
            clip = tl.tracks[0].clips[0]
            filter_str = filter_parts[0].split("]")[0].split("[")[1] + "]"

            final_cmd = [ffmpeg_exe, "-y"]
            final_cmd += cmd[len(ffmpeg_exe.split()):]
            final_cmd += ["-vf", filter_str]
            final_cmd += self._output_args(output, codec, crf, preset)
            return final_cmd

        # 多轨：构建 overlay 链
        base = overlay_chain[0]
        for i, ov in enumerate(overlay_chain[1:], 1):
            base = f"{base}[{ov}]overlay=0:0:format=auto[{ov}_out]"

        filter_str = ";".join(filter_parts) + ";" + base

        final_cmd = [ffmpeg_exe, "-y"]
        final_cmd += cmd[len(ffmpeg_exe.split()):]
        final_cmd += ["-filter_complex", filter_str]
        if len(overlay_chain) > 1:
            final_cmd += ["-map", f"[{overlay_chain[-1]}_out]"]
        final_cmd += self._output_args(output, codec, crf, preset)
        return final_cmd

    def _output_args(self, output: str, codec: str, crf: int, preset: str) -> List[str]:
        """导出参数"""
        return [
            "-c:v", codec, "-crf", str(crf), "-preset", preset,
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            "-y", output
        ]

    # ---- 序列化 ----

    def save_project(self, path: str):
        """保存项目为 JSON"""
        if not self._timeline:
            return
        data = {
            "name": self._timeline.name,
            "width": self._timeline.width,
            "height": self._timeline.height,
            "fps": self._timeline.fps,
            "tracks": []
        }
        for track in self._timeline.tracks:
            tdata = {"name": track.name, "index": track.index, "clips": []}
            for clip in track.clips:
                tdata["clips"].append({
                    "source": clip.source,
                    "position": clip.position,
                    "duration": clip.duration,
                    "in_point": clip.in_point,
                    "speed": clip.speed,
                    "volume": clip.volume,
                    "opacity": clip.opacity,
                    "transition": clip.transition.type.value if clip.transition else None,
                    "transition_duration": clip.transition.duration if clip.transition else 0,
                })
            data["tracks"].append(tdata)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_project(self, path: str) -> Optional[Timeline]:
        """从 JSON 加载项目"""
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self._timeline = Timeline(
            name=data["name"], width=data["width"],
            height=data["height"], fps=data["fps"]
        )
        for tdata in data.get("tracks", []):
            track = self.add_track(name=tdata.get("name", ""))
            for cdata in tdata.get("clips", []):
                clip = Clip(
                    source=cdata["source"], track_index=track.index,
                    position=cdata.get("position", 0),
                    duration=cdata.get("duration", 0),
                    in_point=cdata.get("in_point", 0),
                    speed=cdata.get("speed", 1.0),
                    volume=cdata.get("volume", 1.0),
                    opacity=cdata.get("opacity", 1.0),
                )
                if cdata.get("transition"):
                    clip.transition = Transition(
                        type=TransitionType(cdata["transition"]),
                        duration=cdata.get("transition_duration", 0.5)
                    )
                track.clips.append(clip)
        return self._timeline


# ============================================================
# 全局实例
# ============================================================

_mlt_instance: Optional[MLTEngine] = None

def get_mlt_engine() -> MLTEngine:
    global _mlt_instance
    if _mlt_instance is None:
        _mlt_instance = MLTEngine()
    return _mlt_instance

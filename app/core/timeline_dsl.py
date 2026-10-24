"""
时间轴 JSON-DSL 数据契约 (TimelineDSL)
======================================
标准化的时间轴数据格式，作为 UI层、Agent层、渲染层之间的统一契约。

设计原则:
1. 结构明确: 每个字段都有明确定义的类型和语义
2. 前后端通用: 前后端共享同一份数据契约
3. 可序列化: 完整支持 JSON 序列化/反序列化
4. 可扩展: 通过 metadata 字段支持扩展属性
"""
import json
import time
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, field, asdict
from enum import Enum
from datetime import datetime


# ============================================================
# 枚举类型
# ============================================================

class TrackType(str, Enum):
    """轨道类型"""
    VIDEO = "video"
    AUDIO = "audio"
    SUBTITLE = "subtitle"
    EFFECT = "effect"
    OVERLAY = "overlay"


class ClipType(str, Enum):
    """片段类型"""
    VIDEO = "video"
    AUDIO = "audio"
    IMAGE = "image"
    TEXT = "text"
    SUBTITLE = "subtitle"
    TRANSITION = "transition"
    EFFECT = "effect"


class BlendMode(str, Enum):
    """混合模式"""
    NORMAL = "normal"
    MULTIPLY = "multiply"
    SCREEN = "screen"
    OVERLAY = "overlay"
    DARKEN = "darken"
    LIGHTEN = "lighten"
    SOFT_LIGHT = "soft_light"


class KeyframeInterpolation(str, Enum):
    """关键帧插值类型"""
    LINEAR = "linear"
    EASE_IN = "ease_in"
    EASE_OUT = "ease_out"
    EASE_IN_OUT = "ease_in_out"
    HOLD = "hold"  # 阶跃保持


# ============================================================
# 核心数据结构
# ============================================================

@dataclass
class TimeRange:
    """时间范围"""
    start: float = 0.0   # 开始时间(秒)
    end: float = 0.0     # 结束时间(秒)

    @property
    def duration(self) -> float:
        return max(0, self.end - self.start)

    def overlaps(self, other: "TimeRange") -> bool:
        """检测时间重叠"""
        return self.start < other.end and other.start < self.end

    def contains(self, time: float) -> bool:
        return self.start <= time <= self.end


@dataclass
class Resolution:
    """分辨率"""
    width: int = 1920
    height: int = 1080

    @property
    def aspect_ratio(self) -> float:
        return self.width / self.height if self.height else 1.0

    @property
    def is_vertical(self) -> bool:
        return self.height > self.width


@dataclass
class ClipTransform:
    """片段变换"""
    x: float = 0.0
    y: float = 0.0
    scale_x: float = 1.0
    scale_y: float = 1.0
    rotation: float = 0.0       # 度
    opacity: float = 1.0        # 0-1
    anchor_x: float = 0.5       # 锚点百分比
    anchor_y: float = 0.5


@dataclass
class Keyframe:
    """关键帧"""
    time: float                 # 时间点(秒)
    value: Any                  # 值 (float/str/List)
    interpolation: KeyframeInterpolation = KeyframeInterpolation.LINEAR
    easing_params: List[float] = field(default_factory=list)


@dataclass
class ClipProperty:
    """片段动态属性 (含关键帧)"""
    name: str                   # 属性名 (e.g. "opacity", "position_x")
    default_value: Any = None
    keyframes: List[Keyframe] = field(default_factory=list)

    def get_value_at(self, time: float) -> Any:
        """获取指定时间的插值"""
        if not self.keyframes:
            return self.default_value
        # 简单线性插值 (实际渲染引擎负责)
        sorted_kf = sorted(self.keyframes, key=lambda k: k.time)
        if time <= sorted_kf[0].time:
            return sorted_kf[0].value
        if time >= sorted_kf[-1].time:
            return sorted_kf[-1].value
        for i in range(len(sorted_kf) - 1):
            if sorted_kf[i].time <= time <= sorted_kf[i + 1].time:
                t = (time - sorted_kf[i].time) / (sorted_kf[i + 1].time - sorted_kf[i].time)
                return sorted_kf[i].value + t * (sorted_kf[i + 1].value - sorted_kf[i].value)
        return self.default_value


@dataclass
class Clip:
    """时间轴片段"""
    id: str                     # 唯一 ID
    name: str = ""              # 片段名称
    type: ClipType = ClipType.VIDEO
    source: str = ""            # 素材路径
    range: TimeRange = field(default_factory=TimeRange)  # 在时间轴上的位置
    source_range: TimeRange = field(default_factory=TimeRange)  # 在素材中的范围

    # 外观
    transform: ClipTransform = field(default_factory=ClipTransform)
    blend_mode: BlendMode = BlendMode.NORMAL
    volume: float = 1.0         # 音量 (仅音频)

    # 动画 & 特效
    properties: List[ClipProperty] = field(default_factory=list)
    effects: List[str] = field(default_factory=list)   # 特效 ID 列表

    # 状态
    locked: bool = False
    visible: bool = True
    muted: bool = False         # 静音

    # 标记
    color: str = ""             # 颜色标记
    notes: str = ""             # 备注

    # 扩展
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Track:
    """时间轴轨道"""
    id: str                     # 唯一 ID
    name: str = ""              # 轨道名称
    type: TrackType = TrackType.VIDEO
    clips: List[Clip] = field(default_factory=list)

    # 状态
    locked: bool = False
    visible: bool = True
    muted: bool = False
    solo: bool = False          # 独奏

    # 布局
    height: int = 60            # 轨道高度(像素)
    collapsed: bool = False     # 是否折叠

    # 扩展
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_clip(self, clip: Clip) -> bool:
        """添加片段并排序"""
        self.clips.append(clip)
        self.clips.sort(key=lambda c: c.range.start)
        return True

    def remove_clip(self, clip_id: str) -> bool:
        initial = len(self.clips)
        self.clips = [c for c in self.clips if c.id != clip_id]
        return len(self.clips) < initial

    def get_clip_at(self, time: float) -> Optional[Clip]:
        """获取指定时间点的片段"""
        for clip in self.clips:
            if clip.range.contains(time):
                return clip
        return None

    @property
    def total_duration(self) -> float:
        if not self.clips:
            return 0.0
        return max(c.range.end for c in self.clips)


@dataclass
class Marker:
    """时间轴标记"""
    id: str
    time: float
    name: str = ""
    color: str = "#1e6bde"
    type: str = "marker"  # marker, chapter, in_point, out_point
    notes: str = ""


@dataclass
class Transition:
    """转场"""
    id: str
    from_clip_id: str
    to_clip_id: str
    type: str = "dissolve"      # dissolve, wipe, slide, fade, cross_zoom, 闪白
    duration: float = 0.5       # 转场时长(秒)
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Effect:
    """特效定义"""
    id: str
    name: str
    type: str                   # filter, overlay, lut, blend
    params: Dict[str, Any] = field(default_factory=dict)
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TimelineSettings:
    """时间轴设置"""
    resolution: Resolution = field(default_factory=Resolution)
    fps: float = 30.0
    sample_rate: int = 44100    # 音频采样率
    duration: float = 0.0       # 总时长(秒)
    zoom: float = 1.0           # 缩放级别
    scroll_x: float = 0.0       # 水平滚动位置
    scroll_y: float = 0.0       # 垂直滚动位置
    current_time: float = 0.0   # 当前播放头位置
    snap_enabled: bool = True   # 是否启用吸附
    ripple_enabled: bool = True # 是否启用波纹编辑


@dataclass
class Timeline:
    """时间轴 (顶层数据结构)"""
    # 基础
    id: str = ""
    name: str = ""
    version: str = "1.0.0"          # DSL 版本
    created_at: str = ""
    modified_at: str = ""

    # 数据
    settings: TimelineSettings = field(default_factory=TimelineSettings)
    tracks: List[Track] = field(default_factory=list)
    markers: List[Marker] = field(default_factory=list)
    transitions: List[Transition] = field(default_factory=list)
    effects: List[Effect] = field(default_factory=list)

    # 元数据
    author: str = ""
    description: str = ""
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ---- 工厂方法 ----

    @classmethod
    def create_default(cls, name: str = "新时间轴",
                       width: int = 1920, height: int = 1080,
                       fps: float = 30.0) -> "Timeline":
        """创建默认时间轴 (3条标准轨道)"""
        tl = cls(
            id=f"timeline_{int(time.time() * 1000)}",
            name=name,
            created_at=datetime.now().isoformat(),
            modified_at=datetime.now().isoformat(),
            settings=TimelineSettings(
                resolution=Resolution(width=width, height=height),
                fps=fps,
            ),
            tracks=[
                Track(id="track_v_1", name="视频轨道 1", type=TrackType.VIDEO, height=80),
                Track(id="track_a_1", name="音频轨道 1", type=TrackType.AUDIO, height=50),
                Track(id="track_s_1", name="字幕轨道 1", type=TrackType.SUBTITLE, height=40),
            ],
        )
        return tl

    @classmethod
    def from_json(cls, data: Union[str, Dict]) -> "Timeline":
        """从 JSON 反序列化"""
        if isinstance(data, str):
            data = json.loads(data)
        return cls._deserialize(data)

    # ---- 轨道操作 ----

    def add_track(self, name: str, track_type: TrackType = TrackType.VIDEO) -> Track:
        """添加轨道"""
        track = Track(
            id=f"track_{track_type.value}_{len(self.tracks) + 1}_{int(time.time() * 1000)}",
            name=name,
            type=track_type,
        )
        self.tracks.append(track)
        return track

    def remove_track(self, track_id: str) -> bool:
        """删除轨道"""
        initial = len(self.tracks)
        self.tracks = [t for t in self.tracks if t.id != track_id]
        return len(self.tracks) < initial

    def move_track(self, track_id: str, new_index: int) -> bool:
        """移动轨道顺序"""
        target = None
        for t in self.tracks:
            if t.id == track_id:
                target = t
                break
        if target is None:
            return False
        self.tracks.remove(target)
        self.tracks.insert(max(0, min(new_index, len(self.tracks))), target)
        return True

    def get_track(self, track_id: str) -> Optional[Track]:
        for t in self.tracks:
            if t.id == track_id:
                return t
        return None

    # ---- 片段操作 ----

    def add_clip_to_track(self, track_id: str, clip: Clip) -> bool:
        """添加片段到指定轨道"""
        track = self.get_track(track_id)
        if track is None:
            return False
        track.add_clip(clip)
        self._update_duration()
        return True

    def add_clip(self, track_index: int, clip: Clip) -> bool:
        """添加片段到指定索引的轨道"""
        if track_index >= len(self.tracks):
            return False
        self.tracks[track_index].add_clip(clip)
        self._update_duration()
        return True

    def remove_clip(self, clip_id: str) -> bool:
        """删除片段"""
        found = False
        for track in self.tracks:
            if track.remove_clip(clip_id):
                found = True
        if found:
            self._update_duration()
        return found

    def get_clip(self, clip_id: str) -> Optional[Clip]:
        """获取片段"""
        for track in self.tracks:
            for clip in track.clips:
                if clip.id == clip_id:
                    return clip
        return None

    def move_clip(self, clip_id: str, new_start: float) -> bool:
        """移动片段时间位置"""
        clip = self.get_clip(clip_id)
        if clip is None:
            return False
        duration = clip.range.duration
        clip.range.start = new_start
        clip.range.end = new_start + duration
        return True

    def trim_clip(self, clip_id: str, start: float, end: float) -> bool:
        """裁剪片段"""
        clip = self.get_clip(clip_id)
        if clip is None or start >= end:
            return False
        clip.range.start = start
        clip.range.end = end
        return True

    def split_clip(self, clip_id: str, split_time: float) -> Optional[Clip]:
        """分割片段"""
        clip = self.get_clip(clip_id)
        if clip is None or not clip.range.contains(split_time):
            return None

        # 找到所在轨道
        for track in self.tracks:
            if clip in track.clips:
                right_clip = Clip(
                    id=f"{clip.id}_split_{int(time.time() * 1000)}",
                    name=f"{clip.name} (2)",
                    type=clip.type,
                    source=clip.source,
                    range=TimeRange(
                        start=split_time,
                        end=clip.range.end
                    ),
                    source_range=TimeRange(
                        start=clip.source_range.start + (split_time - clip.range.start),
                        end=clip.source_range.end,
                    ),
                )
                clip.range.end = split_time
                clip.source_range.end = clip.source_range.start + clip.range.duration
                track.add_clip(right_clip)
                return right_clip
        return None

    # ---- 内部方法 ----

    def _update_duration(self):
        """更新总时长"""
        self.settings.duration = max(
            (track.total_duration for track in self.tracks),
            default=0.0
        )

    # ---- 序列化 ----

    def to_json(self, indent: int = 2) -> str:
        """序列化为 JSON"""
        return json.dumps(self._serialize(), ensure_ascii=False, indent=indent)

    def to_dict(self) -> Dict[str, Any]:
        """转为字典"""
        return self._serialize()

    def _serialize(self) -> Dict[str, Any]:
        """序列化"""
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "created_at": self.created_at,
            "modified_at": datetime.now().isoformat(),
            "settings": {
                "resolution": {
                    "width": self.settings.resolution.width,
                    "height": self.settings.resolution.height,
                },
                "fps": self.settings.fps,
                "sample_rate": self.settings.sample_rate,
                "duration": self.settings.duration,
                "zoom": self.settings.zoom,
                "scroll_x": self.settings.scroll_x,
                "scroll_y": self.settings.scroll_y,
                "current_time": self.settings.current_time,
                "snap_enabled": self.settings.snap_enabled,
                "ripple_enabled": self.settings.ripple_enabled,
            },
            "tracks": [self._serialize_track(t) for t in self.tracks],
            "markers": [self._serialize_marker(m) for m in self.markers],
            "transitions": [self._serialize_transition(tr) for tr in self.transitions],
            "effects": [self._serialize_effect(e) for e in self.effects],
            "author": self.author,
            "description": self.description,
            "tags": self.tags,
            "metadata": self.metadata,
        }

    @classmethod
    def _deserialize(cls, data: Dict[str, Any]) -> "Timeline":
        """从字典反序列化"""
        settings_data = data.get("settings", {})
        res_data = settings_data.get("resolution", {})

        tl = cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            version=data.get("version", "1.0.0"),
            created_at=data.get("created_at", ""),
            modified_at=data.get("modified_at", ""),
            settings=TimelineSettings(
                resolution=Resolution(
                    width=res_data.get("width", 1920),
                    height=res_data.get("height", 1080),
                ),
                fps=settings_data.get("fps", 30.0),
                sample_rate=settings_data.get("sample_rate", 44100),
                duration=settings_data.get("duration", 0.0),
                zoom=settings_data.get("zoom", 1.0),
                scroll_x=settings_data.get("scroll_x", 0.0),
                scroll_y=settings_data.get("scroll_y", 0.0),
                current_time=settings_data.get("current_time", 0.0),
                snap_enabled=settings_data.get("snap_enabled", True),
                ripple_enabled=settings_data.get("ripple_enabled", True),
            ),
            tracks=[Track(**cls._deserialize_track_data(t)) for t in data.get("tracks", [])],
            markers=[Marker(**m) for m in data.get("markers", [])],
            transitions=[Transition(**t) for t in data.get("transitions", [])],
            effects=[Effect(**e) for e in data.get("effects", [])],
            author=data.get("author", ""),
            description=data.get("description", ""),
            tags=data.get("tags", []),
            metadata=data.get("metadata", {}),
        )
        return tl

    # ---- 序列化辅助方法 ----

    def _serialize_track(self, track: Track) -> Dict[str, Any]:
        return {
            "id": track.id,
            "name": track.name,
            "type": track.type.value,
            "clips": [self._serialize_clip(c) for c in track.clips],
            "locked": track.locked,
            "visible": track.visible,
            "muted": track.muted,
            "solo": track.solo,
            "height": track.height,
            "collapsed": track.collapsed,
            "metadata": track.metadata,
        }

    def _serialize_clip(self, clip: Clip) -> Dict[str, Any]:
        return {
            "id": clip.id,
            "name": clip.name,
            "type": clip.type.value,
            "source": clip.source,
            "range": {"start": clip.range.start, "end": clip.range.end},
            "source_range": {"start": clip.source_range.start, "end": clip.source_range.end},
            "transform": {
                "x": clip.transform.x, "y": clip.transform.y,
                "scale_x": clip.transform.scale_x, "scale_y": clip.transform.scale_y,
                "rotation": clip.transform.rotation, "opacity": clip.transform.opacity,
                "anchor_x": clip.transform.anchor_x, "anchor_y": clip.transform.anchor_y,
            },
            "blend_mode": clip.blend_mode.value,
            "volume": clip.volume,
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
            "effects": clip.effects,
            "locked": clip.locked,
            "visible": clip.visible,
            "muted": clip.muted,
            "color": clip.color,
            "notes": clip.notes,
            "metadata": clip.metadata,
        }

    def _serialize_marker(self, m: Marker) -> Dict[str, Any]:
        return {"id": m.id, "time": m.time, "name": m.name,
                "color": m.color, "type": m.type, "notes": m.notes}

    def _serialize_transition(self, tr: Transition) -> Dict[str, Any]:
        return {"id": tr.id, "from_clip_id": tr.from_clip_id,
                "to_clip_id": tr.to_clip_id, "type": tr.type,
                "duration": tr.duration, "params": tr.params}

    def _serialize_effect(self, e: Effect) -> Dict[str, Any]:
        return {"id": e.id, "name": e.name, "type": e.type,
                "params": e.params, "meta": e.meta}

    @classmethod
    def _deserialize_track_data(cls, data: Dict) -> Dict:
        """将 track 数据从 type:str 转换为包含 clips 的字典"""
        result = {k: v for k, v in data.items() if k != "clips"}
        result["type"] = TrackType(data.get("type", "video"))
        result["clips"] = [cls._deserialize_clip(c) for c in data.get("clips", [])]
        return result

    @classmethod
    def _deserialize_clip(cls, data: Dict) -> Clip:
        range_data = data.get("range", {})
        src_range = data.get("source_range", {})
        xf = data.get("transform", {})
        props_data = data.get("properties", [])

        return Clip(
            id=data.get("id", ""),
            name=data.get("name", ""),
            type=ClipType(data.get("type", "video")),
            source=data.get("source", ""),
            range=TimeRange(start=range_data.get("start", 0), end=range_data.get("end", 0)),
            source_range=TimeRange(start=src_range.get("start", 0), end=src_range.get("end", 0)),
            transform=ClipTransform(
                x=xf.get("x", 0), y=xf.get("y", 0),
                scale_x=xf.get("scale_x", 1), scale_y=xf.get("scale_y", 1),
                rotation=xf.get("rotation", 0), opacity=xf.get("opacity", 1),
                anchor_x=xf.get("anchor_x", 0.5), anchor_y=xf.get("anchor_y", 0.5),
            ),
            blend_mode=BlendMode(data.get("blend_mode", "normal")),
            volume=data.get("volume", 1.0),
            properties=[
                ClipProperty(
                    name=p.get("name", ""),
                    default_value=p.get("default_value"),
                    keyframes=[
                        Keyframe(
                            time=k.get("time", 0),
                            value=k.get("value"),
                            interpolation=KeyframeInterpolation(k.get("interpolation", "linear")),
                        )
                        for k in p.get("keyframes", [])
                    ],
                )
                for p in props_data
            ],
            effects=data.get("effects", []),
            locked=data.get("locked", False),
            visible=data.get("visible", True),
            muted=data.get("muted", False),
            color=data.get("color", ""),
            notes=data.get("notes", ""),
            metadata=data.get("metadata", {}),
        )


# ============================================================
# JSON Schema (用于验证)
# ============================================================

TIMELINE_JSON_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Timeline DSL Schema",
    "type": "object",
    "required": ["id", "name", "version", "settings", "tracks"],
    "properties": {
        "id": {"type": "string"},
        "name": {"type": "string"},
        "version": {"type": "string", "pattern": "^\\d+\\.\\d+\\.\\d+$"},
        "created_at": {"type": "string"},
        "modified_at": {"type": "string"},
        "settings": {
            "type": "object",
            "required": ["resolution", "fps"],
            "properties": {
                "resolution": {
                    "type": "object",
                    "required": ["width", "height"],
                    "properties": {
                        "width": {"type": "integer", "minimum": 1},
                        "height": {"type": "integer", "minimum": 1},
                    },
                },
                "fps": {"type": "number", "minimum": 1, "maximum": 120},
                "sample_rate": {"type": "integer"},
                "duration": {"type": "number"},
            },
        },
        "tracks": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "type"],
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "type": {"enum": ["video", "audio", "subtitle", "effect", "overlay"]},
                    "clips": {"type": "array"},
                },
            },
        },
        "markers": {"type": "array"},
        "transitions": {"type": "array"},
        "effects": {"type": "array"},
    },
}


# ============================================================
# 验证工具
# ============================================================

def validate_timeline(data: Dict[str, Any]) -> List[str]:
    """
    验证时间轴数据是否符合 DSL 规范
    返回错误列表，空列表表示通过
    """
    errors = []

    if "id" not in data:
        errors.append("缺失 id 字段")
    if "name" not in data:
        errors.append("缺失 name 字段")
    if "version" not in data:
        errors.append("缺失 version 字段")
    if "settings" not in data:
        errors.append("缺失 settings 字段")
    else:
        settings = data["settings"]
        if "resolution" not in settings:
            errors.append("settings 缺失 resolution")
        if "fps" not in settings:
            errors.append("settings 缺失 fps")
    if "tracks" not in data:
        errors.append("缺失 tracks 字段")
    else:
        for i, track in enumerate(data["tracks"]):
            if "id" not in track:
                errors.append(f"tracks[{i}] 缺失 id")
            if "type" not in track:
                errors.append(f"tracks[{i}] ({track.get('id', '?')}) 缺失 type")
            for j, clip in enumerate(track.get("clips", [])):
                if "id" not in clip:
                    errors.append(f"tracks[{i}].clips[{j}] 缺失 id")
                if "range" not in clip:
                    errors.append(f"tracks[{i}].clips[{j}] ({clip.get('id', '?')}) 缺失 range")

    return errors


# ============================================================
# 从现有 TimelineManager 迁移工具
# ============================================================

def convert_from_v1(data: Dict[str, Any]) -> Timeline:
    """
    从旧版 TimelineManager 格式迁移到 DSL 格式
    """
    timeline_data = {
        "id": data.get("id", f"migrated_{int(time.time() * 1000)}"),
        "name": data.get("name", "迁移的时间轴"),
        "version": "1.0.0",
        "created_at": data.get("created_at", ""),
        "modified_at": data.get("last_modified", ""),
        "settings": {
            "resolution": {"width": 1920, "height": 1080},
            "fps": data.get("settings", {}).get("fps", 30.0),
            "duration": data.get("settings", {}).get("duration", 0),
        },
        "tracks": [],
        "markers": [],
        "transitions": [],
        "effects": [],
    }

    for old_track in data.get("tracks", []):
        track = {
            "id": old_track.get("id", ""),
            "name": old_track.get("name", ""),
            "type": old_track.get("type", "video"),
            "clips": [],
            "locked": old_track.get("locked", False),
            "visible": old_track.get("visible", True),
            "metadata": old_track.get("metadata", {}),
        }
        for old_clip in old_track.get("clips", []):
            clip = {
                "id": old_clip.get("id", ""),
                "name": old_clip.get("name", ""),
                "type": old_clip.get("type", "video"),
                "source": old_clip.get("source", old_clip.get("file_path", "")),
                "range": {
                    "start": old_clip.get("start_time", old_clip.get("start", 0)),
                    "end": old_clip.get("end_time", old_clip.get("end", 0)),
                },
                "source_range": {
                    "start": old_clip.get("trim_start", 0),
                    "end": old_clip.get("trim_end", 0),
                },
                "metadata": old_clip.get("metadata", {}),
            }
            track["clips"].append(clip)
        timeline_data["tracks"].append(track)

    return Timeline._deserialize(timeline_data)

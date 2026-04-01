"""
多轨道编辑器
提供专业的多轨道编辑功能
"""

from typing import Dict, List, Optional, Any, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum
from threading import RLock
from datetime import datetime
import uuid


class TrackType(Enum):
    """轨道类型"""
    VIDEO = "video"
    AUDIO = "audio"
    SUBTITLE = "subtitle"
    EFFECT = "effect"
    TITLE = "title"
    OVERLAY = "overlay"


class TrackState(Enum):
    """轨道状态"""
    NORMAL = "normal"
    LOCKED = "locked"
    HIDDEN = "hidden"
    MUTED = "muted"
    SOLO = "solo"


class EditMode(Enum):
    """编辑模式"""
    NORMAL = "normal"
    RIPPLE = "ripple"
    ROLLING = "rolling"
    SLIP = "slip"
    SLIDE = "slide"


class ClipState(Enum):
    """片段状态"""
    NORMAL = "normal"
    SELECTED = "selected"
    LOCKED = "locked"
    DISABLED = "disabled"


@dataclass
class Track:
    """轨道"""
    id: str
    name: str
    track_type: TrackType
    index: int
    state: TrackState = TrackState.NORMAL
    height: int = 100
    volume: float = 1.0
    pan: float = 0.0
    clips: List['Clip'] = field(default_factory=list)
    color: str = "#3498db"
    locked: bool = False
    muted: bool = False
    solo: bool = False
    visible: bool = True
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def add_clip(self, clip: 'Clip') -> bool:
        """添加片段"""
        self.clips.append(clip)
        self.updated_at = datetime.now().isoformat()
        return True
    
    def remove_clip(self, clip_id: str) -> bool:
        """移除片段"""
        for i, clip in enumerate(self.clips):
            if clip.id == clip_id:
                self.clips.pop(i)
                self.updated_at = datetime.now().isoformat()
                return True
        return False
    
    def get_clip(self, clip_id: str) -> Optional['Clip']:
        """获取片段"""
        for clip in self.clips:
            if clip.id == clip_id:
                return clip
        return None
    
    def get_clips_in_range(self, start: float, end: float) -> List['Clip']:
        """获取时间范围内的片段"""
        return [
            clip for clip in self.clips
            if not (clip.end <= start or clip.start >= end)
        ]
    
    def get_clip_at_position(self, position: float) -> Optional['Clip']:
        """获取指定位置的片段"""
        for clip in self.clips:
            if clip.start <= position < clip.end:
                return clip
        return None
    
    def lock(self) -> None:
        """锁定轨道"""
        self.state = TrackState.LOCKED
        self.locked = True
        self.updated_at = datetime.now().isoformat()
    
    def unlock(self) -> None:
        """解锁轨道"""
        self.state = TrackState.NORMAL
        self.locked = False
        self.updated_at = datetime.now().isoformat()
    
    def mute(self) -> None:
        """静音轨道"""
        self.state = TrackState.MUTED
        self.muted = True
        self.updated_at = datetime.now().isoformat()
    
    def unmute(self) -> None:
        """取消静音"""
        self.state = TrackState.NORMAL
        self.muted = False
        self.updated_at = datetime.now().isoformat()
    
    def hide(self) -> None:
        """隐藏轨道"""
        self.state = TrackState.HIDDEN
        self.visible = False
        self.updated_at = datetime.now().isoformat()
    
    def show(self) -> None:
        """显示轨道"""
        self.state = TrackState.NORMAL
        self.visible = True
        self.updated_at = datetime.now().isoformat()
    
    def set_solo(self, solo: bool) -> None:
        """设置独奏"""
        self.solo = solo
        self.updated_at = datetime.now().isoformat()


@dataclass
class Clip:
    """片段"""
    id: str
    track_id: str
    name: str
    start: float
    end: float
    source_start: float
    source_end: float
    media_path: str
    state: ClipState = ClipState.NORMAL
    speed: float = 1.0
    volume: float = 1.0
    opacity: float = 1.0
    rotation: float = 0.0
    scale_x: float = 1.0
    scale_y: float = 1.0
    position_x: float = 0.0
    position_y: float = 0.0
    filters: List[Dict[str, Any]] = field(default_factory=list)
    effects: List[Dict[str, Any]] = field(default_factory=list)
    transitions: List[Dict[str, Any]] = field(default_factory=list)
    locked: bool = False
    selected: bool = False
    enabled: bool = True
    color: str = "#e74c3c"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    @property
    def duration(self) -> float:
        """片段时长"""
        return self.end - self.start
    
    @property
    def source_duration(self) -> float:
        """源时长"""
        return self.source_end - self.source_start
    
    def contains(self, position: float) -> bool:
        """检查是否包含指定位置"""
        return self.start <= position < self.end
    
    def overlaps(self, other: 'Clip') -> bool:
        """检查是否与其他片段重叠"""
        return not (self.end <= other.start or self.start >= other.end)
    
    def split(self, position: float) -> Tuple[Optional['Clip'], Optional['Clip']]:
        """分割片段"""
        if position <= self.start or position >= self.end:
            return None, None
        
        split_ratio = (position - self.start) / self.duration
        source_split = self.source_start + self.source_duration * split_ratio
        
        left_clip = Clip(
            id=str(uuid.uuid4()),
            track_id=self.track_id,
            name=f"{self.name}_L",
            start=self.start,
            end=position,
            source_start=self.source_start,
            source_end=source_split,
            media_path=self.media_path,
            state=self.state,
            speed=self.speed,
            volume=self.volume,
            opacity=self.opacity,
            rotation=self.rotation,
            scale_x=self.scale_x,
            scale_y=self.scale_y,
            position_x=self.position_x,
            position_y=self.position_y,
            filters=self.filters.copy(),
            effects=self.effects.copy(),
            transitions=self.transitions.copy(),
            locked=self.locked,
            selected=self.selected,
            enabled=self.enabled,
            color=self.color
        )
        
        right_clip = Clip(
            id=str(uuid.uuid4()),
            track_id=self.track_id,
            name=f"{self.name}_R",
            start=position,
            end=self.end,
            source_start=source_split,
            source_end=self.source_end,
            media_path=self.media_path,
            state=self.state,
            speed=self.speed,
            volume=self.volume,
            opacity=self.opacity,
            rotation=self.rotation,
            scale_x=self.scale_x,
            scale_y=self.scale_y,
            position_x=self.position_x,
            position_y=self.position_y,
            filters=self.filters.copy(),
            effects=self.effects.copy(),
            transitions=self.transitions.copy(),
            locked=self.locked,
            selected=self.selected,
            enabled=self.enabled,
            color=self.color
        )
        
        return left_clip, right_clip
    
    def trim(self, new_start: Optional[float] = None, new_end: Optional[float] = None) -> bool:
        """裁剪片段"""
        if new_start is not None:
            if new_start < self.start or new_start >= self.end:
                return False
            
            trim_ratio = (new_start - self.start) / self.duration
            self.source_start += self.source_duration * trim_ratio
            self.start = new_start
        
        if new_end is not None:
            if new_end <= self.start or new_end > self.end:
                return False
            
            trim_ratio = (self.end - new_end) / self.duration
            self.source_end -= self.source_duration * trim_ratio
            self.end = new_end
        
        self.updated_at = datetime.now().isoformat()
        return True
    
    def move(self, delta: float) -> bool:
        """移动片段"""
        self.start += delta
        self.end += delta
        self.updated_at = datetime.now().isoformat()
        return True
    
    def resize(self, new_duration: float, anchor: str = "start") -> bool:
        """调整片段大小"""
        if new_duration <= 0:
            return False
        
        old_duration = self.duration
        delta = new_duration - old_duration
        
        if anchor == "start":
            self.end += delta
        elif anchor == "end":
            self.start -= delta
        elif anchor == "center":
            self.start -= delta / 2
            self.end += delta / 2
        
        self.updated_at = datetime.now().isoformat()
        return True


@dataclass
class Marker:
    """时间轴标记"""
    id: str
    position: float
    name: str
    color: str = "#f39c12"
    comment: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class TrackGroup:
    """轨道组"""
    id: str
    name: str
    track_ids: List[str] = field(default_factory=list)
    color: str = "#9b59b6"
    collapsed: bool = False
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


class MultiTrackEditor:
    """多轨道编辑器"""
    
    def __init__(self):
        self._tracks: Dict[str, Track] = {}
        self._track_index: int = 0
        self._edit_mode: EditMode = EditMode.NORMAL
        self._markers: List[Marker] = []
        self._track_groups: Dict[str, TrackGroup] = {}
        self._selected_clips: Set[str] = set()
        self._lock = RLock()
    
    def create_track(self, name: str, track_type: TrackType,
                    index: Optional[int] = None) -> Track:
        """创建轨道"""
        with self._lock:
            if index is None:
                index = self._track_index
                self._track_index += 1
            
            track = Track(
                id=str(uuid.uuid4()),
                name=name,
                track_type=track_type,
                index=index
            )
            
            self._tracks[track.id] = track
            return track
    
    def delete_track(self, track_id: str) -> bool:
        """删除轨道"""
        with self._lock:
            if track_id not in self._tracks:
                return False
            
            del self._tracks[track_id]
            return True
    
    def get_track(self, track_id: str) -> Optional[Track]:
        """获取轨道"""
        return self._tracks.get(track_id)
    
    def get_tracks(self, track_type: Optional[TrackType] = None) -> List[Track]:
        """获取轨道列表"""
        tracks = list(self._tracks.values())
        
        if track_type:
            tracks = [t for t in tracks if t.track_type == track_type]
        
        return sorted(tracks, key=lambda t: t.index)
    
    def lock_track(self, track_id: str) -> bool:
        """锁定轨道"""
        track = self.get_track(track_id)
        if track:
            track.lock()
            return True
        return False
    
    def unlock_track(self, track_id: str) -> bool:
        """解锁轨道"""
        track = self.get_track(track_id)
        if track:
            track.unlock()
            return True
        return False
    
    def mute_track(self, track_id: str) -> bool:
        """静音轨道"""
        track = self.get_track(track_id)
        if track:
            track.mute()
            return True
        return False
    
    def unmute_track(self, track_id: str) -> bool:
        """取消静音"""
        track = self.get_track(track_id)
        if track:
            track.unmute()
            return True
        return False
    
    def hide_track(self, track_id: str) -> bool:
        """隐藏轨道"""
        track = self.get_track(track_id)
        if track:
            track.hide()
            return True
        return False
    
    def show_track(self, track_id: str) -> bool:
        """显示轨道"""
        track = self.get_track(track_id)
        if track:
            track.show()
            return True
        return False
    
    def set_track_solo(self, track_id: str, solo: bool) -> bool:
        """设置轨道独奏"""
        track = self.get_track(track_id)
        if track:
            track.set_solo(solo)
            return True
        return False
    
    def reorder_tracks(self, track_ids: List[str]) -> bool:
        """重新排序轨道"""
        with self._lock:
            for i, track_id in enumerate(track_ids):
                track = self.get_track(track_id)
                if track:
                    track.index = i
            return True
    
    def create_clip(self, track_id: str, name: str, media_path: str,
                   start: float, end: float, source_start: float = 0.0,
                   source_end: Optional[float] = None) -> Optional[Clip]:
        """创建片段"""
        track = self.get_track(track_id)
        if not track:
            return None
        
        if source_end is None:
            source_end = source_start + (end - start)
        
        clip = Clip(
            id=str(uuid.uuid4()),
            track_id=track_id,
            name=name,
            start=start,
            end=end,
            source_start=source_start,
            source_end=source_end,
            media_path=media_path
        )
        
        track.add_clip(clip)
        return clip
    
    def delete_clip(self, clip_id: str) -> bool:
        """删除片段"""
        for track in self._tracks.values():
            if track.remove_clip(clip_id):
                self._selected_clips.discard(clip_id)
                return True
        return False
    
    def get_clip(self, clip_id: str) -> Optional[Clip]:
        """获取片段"""
        for track in self._tracks.values():
            clip = track.get_clip(clip_id)
            if clip:
                return clip
        return None
    
    def move_clip(self, clip_id: str, delta: float,
                  mode: Optional[EditMode] = None) -> bool:
        """移动片段"""
        clip = self.get_clip(clip_id)
        if not clip:
            return False
        
        if mode is None:
            mode = self._edit_mode
        
        if mode == EditMode.RIPPLE:
            self._ripple_edit(clip, delta)
        elif mode == EditMode.ROLLING:
            self._rolling_edit(clip, delta)
        elif mode == EditMode.SLIP:
            self._slip_edit(clip, delta)
        elif mode == EditMode.SLIDE:
            self._slide_edit(clip, delta)
        else:
            clip.move(delta)
        
        return True
    
    def resize_clip(self, clip_id: str, new_duration: float,
                   anchor: str = "start") -> bool:
        """调整片段大小"""
        clip = self.get_clip(clip_id)
        if not clip:
            return False
        
        return clip.resize(new_duration, anchor)
    
    def split_clip(self, clip_id: str, position: float) -> Tuple[Optional[str], Optional[str]]:
        """分割片段"""
        clip = self.get_clip(clip_id)
        if not clip:
            return None, None
        
        left_clip, right_clip = clip.split(position)
        if not left_clip or not right_clip:
            return None, None
        
        track = self.get_track(clip.track_id)
        if not track:
            return None, None
        
        track.remove_clip(clip_id)
        track.add_clip(left_clip)
        track.add_clip(right_clip)
        
        return left_clip.id, right_clip.id
    
    def trim_clip(self, clip_id: str, new_start: Optional[float] = None,
                new_end: Optional[float] = None) -> bool:
        """裁剪片段"""
        clip = self.get_clip(clip_id)
        if not clip:
            return False
        
        return clip.trim(new_start, new_end)
    
    def select_clip(self, clip_id: str, selected: bool = True) -> bool:
        """选择片段"""
        clip = self.get_clip(clip_id)
        if not clip:
            return False
        
        clip.selected = selected
        
        if selected:
            self._selected_clips.add(clip_id)
        else:
            self._selected_clips.discard(clip_id)
        
        return True
    
    def get_selected_clips(self) -> List[Clip]:
        """获取选中的片段"""
        clips = []
        for clip_id in self._selected_clips:
            clip = self.get_clip(clip_id)
            if clip:
                clips.append(clip)
        return clips
    
    def clear_selection(self) -> None:
        """清除选择"""
        for clip_id in self._selected_clips:
            clip = self.get_clip(clip_id)
            if clip:
                clip.selected = False
        
        self._selected_clips.clear()
    
    def select_clips_in_range(self, start: float, end: float) -> int:
        """选择时间范围内的片段"""
        count = 0
        for track in self._tracks.values():
            for clip in track.clips:
                if clip.overlaps(Clip(
                    id="", track_id="", name="", start=start, end=end,
                    source_start=0, source_end=0, media_path=""
                )):
                    self.select_clip(clip.id, True)
                    count += 1
        return count
    
    def _ripple_edit(self, clip: Clip, delta: float) -> None:
        """波纹编辑"""
        old_start = clip.start
        clip.move(delta)
        
        for track in self._tracks.values():
            for other_clip in track.clips:
                if other_clip.id != clip.id and other_clip.start >= old_start:
                    other_clip.move(delta)
    
    def _rolling_edit(self, clip: Clip, delta: float) -> None:
        """滚动编辑"""
        clip.resize(clip.duration + delta, anchor="start")
    
    def _slip_edit(self, clip: Clip, delta: float) -> None:
        """滑动编辑"""
        clip.source_start += delta
        clip.source_end += delta
    
    def _slide_edit(self, clip: Clip, delta: float) -> None:
        """滑移编辑"""
        clip.move(delta)
        clip.source_start -= delta
        clip.source_end -= delta
    
    def set_edit_mode(self, mode: EditMode) -> None:
        """设置编辑模式"""
        self._edit_mode = mode
    
    def get_edit_mode(self) -> EditMode:
        """获取编辑模式"""
        return self._edit_mode
    
    def add_marker(self, position: float, name: str, color: str = "#f39c12",
                  comment: str = "") -> Marker:
        """添加标记"""
        marker = Marker(
            id=str(uuid.uuid4()),
            position=position,
            name=name,
            color=color,
            comment=comment
        )
        
        self._markers.append(marker)
        return marker
    
    def remove_marker(self, marker_id: str) -> bool:
        """移除标记"""
        for i, marker in enumerate(self._markers):
            if marker.id == marker_id:
                self._markers.pop(i)
                return True
        return False
    
    def get_markers(self) -> List[Marker]:
        """获取所有标记"""
        return sorted(self._markers, key=lambda m: m.position)
    
    def get_marker_at(self, position: float, tolerance: float = 0.1) -> Optional[Marker]:
        """获取指定位置的标记"""
        for marker in self._markers:
            if abs(marker.position - position) <= tolerance:
                return marker
        return None
    
    def create_track_group(self, name: str, track_ids: List[str]) -> TrackGroup:
        """创建轨道组"""
        group = TrackGroup(
            id=str(uuid.uuid4()),
            name=name,
            track_ids=track_ids
        )
        
        self._track_groups[group.id] = group
        return group
    
    def delete_track_group(self, group_id: str) -> bool:
        """删除轨道组"""
        if group_id in self._track_groups:
            del self._track_groups[group_id]
            return True
        return False
    
    def get_track_group(self, group_id: str) -> Optional[TrackGroup]:
        """获取轨道组"""
        return self._track_groups.get(group_id)
    
    def get_track_groups(self) -> List[TrackGroup]:
        """获取所有轨道组"""
        return list(self._track_groups.values())
    
    def add_track_to_group(self, group_id: str, track_id: str) -> bool:
        """添加轨道到组"""
        group = self.get_track_group(group_id)
        if not group:
            return False
        
        if track_id not in group.track_ids:
            group.track_ids.append(track_id)
            return True
        
        return False
    
    def remove_track_from_group(self, group_id: str, track_id: str) -> bool:
        """从组中移除轨道"""
        group = self.get_track_group(group_id)
        if not group:
            return False
        
        if track_id in group.track_ids:
            group.track_ids.remove(track_id)
            return True
        
        return False
    
    def get_timeline_range(self) -> Tuple[float, float]:
        """获取时间轴范围"""
        if not self._tracks:
            return 0.0, 0.0
        
        start = float('inf')
        end = float('-inf')
        
        for track in self._tracks.values():
            for clip in track.clips:
                if clip.start < start:
                    start = clip.start
                if clip.end > end:
                    end = clip.end
        
        if start == float('inf'):
            start = 0.0
        if end == float('-inf'):
            end = 0.0
        
        return start, end
    
    def get_clips_at(self, position: float) -> List[Clip]:
        """获取指定位置的所有片段"""
        clips = []
        for track in self._tracks.values():
            clip = track.get_clip_at_position(position)
            if clip:
                clips.append(clip)
        return clips
    
    def get_overlapping_clips(self, track_id: str, clip: Clip) -> List[Clip]:
        """获取重叠的片段"""
        track = self.get_track(track_id)
        if not track:
            return []
        
        overlapping = []
        for other_clip in track.clips:
            if other_clip.id != clip.id and clip.overlaps(other_clip):
                overlapping.append(other_clip)
        
        return overlapping
    
    def clear_all(self) -> None:
        """清除所有内容"""
        with self._lock:
            self._tracks.clear()
            self._markers.clear()
            self._track_groups.clear()
            self._selected_clips.clear()
            self._track_index = 0
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        total_tracks = len(self._tracks)
        total_clips = sum(len(track.clips) for track in self._tracks.values())
        total_duration = 0.0
        
        for track in self._tracks.values():
            for clip in track.clips:
                if clip.end > total_duration:
                    total_duration = clip.end
        
        return {
            "total_tracks": total_tracks,
            "total_clips": total_clips,
            "total_duration": total_duration,
            "total_markers": len(self._markers),
            "total_groups": len(self._track_groups),
            "selected_clips": len(self._selected_clips),
            "by_type": {
                "video": len(self.get_tracks(TrackType.VIDEO)),
                "audio": len(self.get_tracks(TrackType.AUDIO)),
                "subtitle": len(self.get_tracks(TrackType.SUBTITLE)),
                "effect": len(self.get_tracks(TrackType.EFFECT)),
                "title": len(self.get_tracks(TrackType.TITLE)),
                "overlay": len(self.get_tracks(TrackType.OVERLAY))
            }
        }

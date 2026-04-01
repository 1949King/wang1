"""
虚拟化时间轴 - 第一阶段核心组件
==============================
实现轻量级时间轴操作，解决预览拖影、延迟问题
目标：支持快速操作、虚拟化渲染、低配设备流畅
"""

import time
import threading
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from collections import OrderedDict

from app.modules.utils.logger import logger

class TimelineEventType(Enum):
    """时间轴事件类型"""
    CLIP_ADDED = "clip_added"
    CLIP_REMOVED = "clip_removed"
    CLIP_MOVED = "clip_moved"
    CLIP_RESIZED = "clip_resized"
    TRACK_ADDED = "track_added"
    TRACK_REMOVED = "track_removed"
    SELECTION_CHANGED = "selection_changed"

@dataclass
class VirtualClip:
    """虚拟剪辑片段"""
    id: str
    track_id: str
    start_time: float
    end_time: float
    duration: float
    type: str  # video, audio, subtitle
    locked: bool = False
    muted: bool = False
    visible: bool = True
    color: str = "#4A90E2"  # 默认蓝色
    label: str = ""

@dataclass
class VirtualTrack:
    """虚拟轨道"""
    id: str
    name: str
    type: str  # video, audio, subtitle
    clips: List[VirtualClip] = field(default_factory=list)
    height: int = 80  # 轨道高度
    visible: bool = True
    locked: bool = False
    muted: bool = False
    volume: float = 1.0  # 音量

@dataclass
class TimelineSelection:
    """时间轴选择"""
    clip_ids: List[str] = field(default_factory=list)
    track_ids: List[str] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0

@dataclass
class TimelineConfig:
    """时间轴配置"""
    duration: float = 180.0  # 默认3分钟
    fps: float = 30.0  # 帧率
    pixel_ratio: str = "9:16"  # 短剧竖屏比例
    snap_to_grid: bool = True  # 磁吸网格
    snap_to_frame: bool = True  # 磁吸帧
    grid_size: float = 1.0  # 网格大小（秒）
    min_clip_duration: float = 0.5  # 最小片段时长

class VirtualTimeline:
    """虚拟化时间轴"""
    
    def __init__(self, config: Optional[TimelineConfig] = None):
        self.config = config or TimelineConfig()
        self._tracks: OrderedDict[str, VirtualTrack] = OrderedDict()
        self._selection = TimelineSelection()
        self._lock = threading.Lock()
        self._event_listeners = {event_type: [] for event_type in TimelineEventType}
        self._undo_stack = []
        self._redo_stack = []
        self._max_undo_levels = 50
        
        # 初始化默认轨道
        self._init_default_tracks()
        
        logger.info(f"虚拟化时间轴初始化: {self.config.duration}秒, {self.config.fps}FPS")
    
    def _init_default_tracks(self):
        """初始化默认轨道"""
        # 视频轨道
        self.add_track("video_1", "视频轨道1", "video")
        self.add_track("video_2", "视频轨道2", "video")
        
        # 音频轨道
        self.add_track("audio_1", "音频轨道1", "audio")
        
        # 字幕轨道
        self.add_track("subtitle_1", "字幕轨道1", "subtitle")
    
    def add_track(self, track_id: str, name: str, track_type: str) -> bool:
        """添加轨道"""
        with self._lock:
            if track_id in self._tracks:
                logger.warning(f"轨道已存在: {track_id}")
                return False
            
            track = VirtualTrack(
                id=track_id,
                name=name,
                type=track_type
            )
            
            self._tracks[track_id] = track
            self._notify_listeners(TimelineEventType.TRACK_ADDED, track)
            
            logger.debug(f"添加轨道: {track_id}")
            return True
    
    def remove_track(self, track_id: str) -> bool:
        """移除轨道"""
        with self._lock:
            if track_id not in self._tracks:
                logger.warning(f"轨道不存在: {track_id}")
                return False
            
            track = self._tracks[track_id]
            del self._tracks[track_id]
            
            self._notify_listeners(TimelineEventType.TRACK_REMOVED, track)
            
            logger.debug(f"移除轨道: {track_id}")
            return True
    
    def add_clip(self, track_id: str, clip: VirtualClip) -> bool:
        """添加剪辑片段"""
        with self._lock:
            if track_id not in self._tracks:
                logger.warning(f"轨道不存在: {track_id}")
                return False
            
            track = self._tracks[track_id]
            
            # 验证时间范围
            if clip.start_time < 0 or clip.end_time > self.config.duration:
                logger.error(f"片段时间超出范围: {clip.start_time}-{clip.end_time}")
                return False
            
            track.clips.append(clip)
            self._notify_listeners(TimelineEventType.CLIP_ADDED, clip)
            
            logger.debug(f"添加片段: {clip.id} 到轨道 {track_id}")
            return True
    
    def remove_clip(self, clip_id: str) -> bool:
        """移除剪辑片段"""
        with self._lock:
            for track in self._tracks.values():
                for i, clip in enumerate(track.clips):
                    if clip.id == clip_id:
                        track.clips.pop(i)
                        self._notify_listeners(TimelineEventType.CLIP_REMOVED, clip)
                        logger.debug(f"移除片段: {clip_id}")
                        return True
            
            logger.warning(f"片段不存在: {clip_id}")
            return False
    
    def move_clip(self, clip_id: str, new_start_time: float) -> bool:
        """移动剪辑片段"""
        with self._lock:
            for track in self._tracks.values():
                for clip in track.clips:
                    if clip.id == clip_id:
                        old_start = clip.start_time
                        clip.start_time = new_start_time
                        clip.end_time = new_start_time + clip.duration
                        
                        self._notify_listeners(TimelineEventType.CLIP_MOVED, clip)
                        
                        logger.debug(f"移动片段: {clip.id} {old_start} -> {new_start_time}")
                        return True
            
            logger.warning(f"片段不存在: {clip_id}")
            return False
    
    def resize_clip(self, clip_id: str, new_duration: float) -> bool:
        """调整剪辑片段时长"""
        with self._lock:
            for track in self._tracks.values():
                for clip in track.clips:
                    if clip.id == clip_id:
                        old_duration = clip.duration
                        clip.duration = new_duration
                        clip.end_time = clip.start_time + new_duration
                        
                        self._notify_listeners(TimelineEventType.CLIP_RESIZED, clip)
                        
                        logger.debug(f"调整片段时长: {clip.id} {old_duration} -> {new_duration}")
                        return True
            
            logger.warning(f"片段不存在: {clip_id}")
            return False
    
    def select_clips(self, clip_ids: List[str]):
        """选择多个片段"""
        with self._lock:
            self._selection.clip_ids = clip_ids
            
            # 计算选择范围
            start_times = []
            end_times = []
            
            for track in self._tracks.values():
                for clip in track.clips:
                    if clip.id in clip_ids:
                        start_times.append(clip.start_time)
                        end_times.append(clip.end_time)
            
            if start_times:
                self._selection.start_time = min(start_times)
                self._selection.end_time = max(end_times)
            
            self._notify_listeners(TimelineEventType.SELECTION_CHANGED, self._selection)
            
            logger.debug(f"选择片段: {len(clip_ids)}个")
    
    def clear_selection(self):
        """清除选择"""
        with self._lock:
            self._selection = TimelineSelection()
            self._notify_listeners(TimelineEventType.SELECTION_CHANGED, self._selection)
            logger.debug("清除选择")
    
    def get_clips_at_time(self, time: float) -> List[VirtualClip]:
        """获取指定时间的所有片段"""
        clips_at_time = []
        
        with self._lock:
            for track in self._tracks.values():
                for clip in track.clips:
                    if clip.start_time <= time <= clip.end_time:
                        clips_at_time.append(clip)
        
        return clips_at_time
    
    def get_timeline_range(self) -> Tuple[float, float]:
        """获取时间轴范围"""
        if not self._tracks:
            return (0.0, self.config.duration)
        
        min_time = float('inf')
        max_time = 0.0
        
        with self._lock:
            for track in self._tracks.values():
                for clip in track.clips:
                    min_time = min(min_time, clip.start_time)
                    max_time = max(max_time, clip.end_time)
        
        return (min_time, max_time)
    
    def snap_to_grid(self, time: float) -> float:
        """磁吸到网格"""
        if not self.config.snap_to_grid:
            return time
        
        grid_size = self.config.grid_size
        snapped_time = round(time / grid_size) * grid_size
        
        return snapped_time
    
    def snap_to_frame(self, time: float) -> float:
        """磁吸到帧"""
        if not self.config.snap_to_frame:
            return time
        
        frame_duration = 1.0 / self.config.fps
        frame_index = round(time / frame_duration)
        snapped_time = frame_index * frame_duration
        
        return snapped_time
    
    def add_listener(self, event_type: TimelineEventType, callback):
        """添加事件监听器"""
        if event_type in self._event_listeners:
            self._event_listeners[event_type].append(callback)
            logger.debug(f"添加监听器: {event_type}")
    
    def remove_listener(self, event_type: TimelineEventType, callback):
        """移除事件监听器"""
        if event_type in self._event_listeners:
            if callback in self._event_listeners[event_type]:
                self._event_listeners[event_type].remove(callback)
                logger.debug(f"移除监听器: {event_type}")
    
    def _notify_listeners(self, event_type: TimelineEventType, data: Any):
        """通知监听器"""
        if event_type in self._event_listeners:
            for callback in self._event_listeners[event_type]:
                try:
                    callback(data)
                except Exception as e:
                    logger.error(f"监听器回调失败: {e}")
    
    def save_state(self) -> str:
        """保存时间轴状态（用于撤销）"""
        with self._lock:
            state = {
                'tracks': {tid: {'clips': [clip.__dict__ for clip in track.clips], 
                                'name': track.name, 
                                'type': track.type}
                         for tid, track in self._tracks.items()},
                'selection': {'clip_ids': self._selection.clip_ids,
                           'track_ids': self._selection.track_ids,
                           'start_time': self._selection.start_time,
                           'end_time': self._selection.end_time},
                'timestamp': time.time()
            }
        
        import json
        return json.dumps(state, ensure_ascii=False)
    
    def restore_state(self, state_str: str) -> bool:
        """恢复时间轴状态"""
        try:
            import json
            state = json.loads(state_str)
            
            with self._lock:
                # 清空当前状态
                self._tracks.clear()
                
                # 恢复轨道和片段
                for track_id, track_data in state['tracks'].items():
                    clips = [VirtualClip(**clip_data) for clip_data in track_data['clips']]
                    track = VirtualTrack(
                        id=track_id,
                        name=track_data['name'],
                        type=track_data['type'],
                        clips=clips
                    )
                    self._tracks[track_id] = track
                
                # 恢复选择
                selection_data = state.get('selection', {})
                self._selection = TimelineSelection(
                    clip_ids=selection_data.get('clip_ids', []),
                    track_ids=selection_data.get('track_ids', []),
                    start_time=selection_data.get('start_time', 0.0),
                    end_time=selection_data.get('end_time', 0.0)
                )
            
            logger.info("时间轴状态恢复成功")
            return True
            
        except Exception as e:
            logger.error(f"时间轴状态恢复失败: {e}")
            return False
    
    def undo(self) -> bool:
        """撤销操作"""
        if not self._undo_stack:
            logger.warning("无可撤销操作")
            return False
        
        # 恢复上一个状态
        previous_state = self._undo_stack.pop()
        self._redo_stack.append(self.save_state())
        self.restore_state(previous_state)
        
        logger.debug("执行撤销")
        return True
    
    def redo(self) -> bool:
        """重做操作"""
        if not self._redo_stack:
            logger.warning("无可重做操作")
            return False
        
        # 恢复下一个状态
        next_state = self._redo_stack.pop()
        self._undo_stack.append(self.save_state())
        self.restore_state(next_state)
        
        logger.debug("执行重做")
        return True
    
    def can_undo(self) -> bool:
        """是否可以撤销"""
        return len(self._undo_stack) > 0
    
    def can_redo(self) -> bool:
        """是否可以重做"""
        return len(self._redo_stack) > 0
    
    def get_stats(self) -> Dict[str, Any]:
        """获取时间轴统计信息"""
        with self._lock:
            total_clips = sum(len(track.clips) for track in self._tracks.values())
            total_duration = 0.0
            total_tracks = len(self._tracks)
            
            for track in self._tracks.values():
                for clip in track.clips:
                    total_duration += clip.duration
            
            return {
                'total_tracks': total_tracks,
                'total_clips': total_clips,
                'total_duration': total_duration,
                'selected_clips': len(self._selection.clip_ids),
                'undo_levels': len(self._undo_stack),
                'redo_levels': len(self._redo_stack),
                'config': {
                    'duration': self.config.duration,
                    'fps': self.config.fps,
                    'pixel_ratio': self.config.pixel_ratio
                }
            }

# 全局虚拟化时间轴实例
virtual_timeline = None

def get_virtual_timeline() -> VirtualTimeline:
    """获取虚拟化时间轴实例（单例模式）"""
    global virtual_timeline
    if virtual_timeline is None:
        virtual_timeline = VirtualTimeline()
    return virtual_timeline
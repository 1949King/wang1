"""
内核核心模块（Core）
==================
乐高底板 - 绝对不动、最稳定的核心组件

包含：
- EventBus: 全局事件总线（模块通信）
- MasterClock: 全局时钟（时间同步）
- DataBus: 数据总线（数据共享）
"""

from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
import time
import threading
import logging
import uuid
from collections import defaultdict
import json

_logger = logging.getLogger("lego.core")


class EventType(Enum):
    PROJECT_CREATED = "project_created"
    PROJECT_SAVED = "project_saved"
    PROJECT_LOADED = "project_loaded"
    
    VIDEO_LOADED = "video_loaded"
    VIDEO_SAVED = "video_saved"
    VIDEO_EXPORTED = "video_exported"
    
    CLIP_ADDED = "clip_added"
    CLIP_REMOVED = "clip_removed"
    CLIP_MODIFIED = "clip_modified"
    
    TRACK_ADDED = "track_added"
    TRACK_REMOVED = "track_removed"
    TRACK_MODIFIED = "track_modified"
    
    SUBTITLE_GENERATED = "subtitle_generated"
    SUBTITLE_MODIFIED = "subtitle_modified"
    
    DRAMA_SELECTED = "drama_selected"
    COPY_GENERATED = "copy_generated"
    VIDEO_CLIPPED = "video_clipped"
    WORKFLOW_COMPLETED = "workflow_completed"
    PUBLISH_RESULT = "publish_result"
    
    TASK_STARTED = "task_started"
    TASK_PROGRESS = "task_progress"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    
    BLOCK_STARTED = "block_started"
    BLOCK_PROGRESS = "block_progress"
    BLOCK_COMPLETED = "block_completed"
    BLOCK_FAILED = "block_failed"
    
    MODULE_ACTIVATED = "module_activated"
    MODULE_DEACTIVATED = "module_deactivated"
    MODULE_CONFIG_CHANGED = "module_config_changed"  # 功能开关变更（设置面板保存后触发）
    THEME_CHANGED = "theme_changed"  # 主题切换（设置面板主题下拉框变更时触发）
    
    PERFORMANCE_WARNING = "performance_warning"
    ERROR_OCCURRED = "error_occurred"
    
    MATERIAL_TO_TIMELINE = "material_to_timeline"  # 素材库 → 时间线拖拽推送

    CUSTOM = "custom"

    # === 统一调用层 & 反馈闭环（新增） ===
    CAPABILITY_INVOKED = "capability_invoked"            # 调用层开始执行
    CAPABILITY_COMPLETED = "capability_completed"        # 调用层执行完成
    AGENT_FEEDBACK_AVAILABLE = "agent_feedback_available"  # 有新反馈可供 Agent 参考
    AGENT_MARKERS_UPDATED = "agent_markers_updated"        # Agent 反馈标记更新（供 TimelineMarkerLayer 渲染）
    MEMORY_WRITTEN = "memory_written"                    # 长期记忆写入

    # === Agent 全量双向闭环业务流程（新增） ===
    PIPELINE_ROUTED = "pipeline_routed"                  # 业务分流完成
    GENERATION_INSPECTION_FAILED = "generation_inspection_failed"  # AI生成初检失败
    PREVIEW_VALIDATION_FAILED = "preview_validation_failed"        # 预览校验失败
    SCORING_COMPLETED = "scoring_completed"              # 五维打分完成
    EDITING_SCRIPT_GENERATED = "editing_script_generated"  # 剪辑脚本生成


@dataclass
class Event:
    type: EventType
    data: Dict[str, Any] = field(default_factory=dict)
    source: str = ""
    timestamp: float = field(default_factory=time.time)
    id: str = ""
    
    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())[:8]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type.value,
            "data": self.data,
            "source": self.source,
            "timestamp": self.timestamp,
            "id": self.id
        }


class EventBus:
    """
    全局事件总线 - 模块之间通信的唯一通道
    
    所有模块之间绝对不直接调用对方，全部通过 EventBus 通信。
    这就是专业软件不卡、不崩、不乱的秘密。
    """
    
    _instance: Optional['EventBus'] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._listeners: Dict[EventType, List[Callable]] = defaultdict(list)
        self._once_listeners: Dict[EventType, List[Callable]] = defaultdict(list)
        self._event_history: List[Event] = []
        self._max_history = 100
        self._lock = threading.RLock()  # 可重入锁，避免回调中 emit 导致死锁
    
    def on(self, event_type: EventType, callback: Callable[[Event], None]) -> 'EventBus':
        """注册事件监听器"""
        with self._lock:
            if callback not in self._listeners[event_type]:
                self._listeners[event_type].append(callback)
        return self
    
    def once(self, event_type: EventType, callback: Callable[[Event], None]) -> 'EventBus':
        """注册一次性事件监听器"""
        with self._lock:
            if callback not in self._once_listeners[event_type]:
                self._once_listeners[event_type].append(callback)
        return self
    
    def off(self, event_type: EventType, callback: Callable[[Event], None]) -> 'EventBus':
        """移除事件监听器"""
        with self._lock:
            if callback in self._listeners[event_type]:
                self._listeners[event_type].remove(callback)
            if callback in self._once_listeners[event_type]:
                self._once_listeners[event_type].remove(callback)
        return self
    
    def emit(self, event_type: EventType, data: Dict[str, Any] = None, source: str = "") -> Event:
        """发送事件"""
        event = Event(
            type=event_type,
            data=data or {},
            source=source
        )
        
        with self._lock:
            self._event_history.append(event)
            if len(self._event_history) > self._max_history:
                self._event_history = self._event_history[-self._max_history:]
            
            listeners = self._listeners[event_type].copy()
            once_listeners = self._once_listeners[event_type].copy()
            self._once_listeners[event_type].clear()
        
        for callback in listeners:
            try:
                callback(event)
            except Exception as e:
                _logger.error(
                    f"EventBus callback error for {event_type.value}: {e}",
                    exc_info=True
                )
        
        for callback in once_listeners:
            try:
                callback(event)
            except Exception as e:
                _logger.error(
                    f"EventBus once callback error for {event_type.value}: {e}",
                    exc_info=True
                )
        
        return event
    
    def get_history(self, event_type: EventType = None) -> List[Event]:
        """获取事件历史"""
        with self._lock:
            if event_type:
                return [e for e in self._event_history if e.type == event_type]
            return self._event_history.copy()
    
    def clear(self):
        """清空所有监听器"""
        with self._lock:
            self._listeners.clear()
            self._once_listeners.clear()
    
    @classmethod
    def get_instance(cls) -> 'EventBus':
        return cls()


class MasterClock:
    """
    全局时钟 - 时间同步的核心
    
    用于：
    - 播放时间同步
    - 帧精确控制
    - 时间码管理
    """
    
    _instance: Optional['MasterClock'] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._fps: float = 30.0
        self._current_frame: int = 0
        self._total_frames: int = 0
        self._playing: bool = False
        self._start_time: float = 0.0
        self._pause_time: float = 0.0
        self._lock = threading.Lock()
        self._event_bus = EventBus.get_instance()
    
    @property
    def fps(self) -> float:
        return self._fps
    
    @fps.setter
    def fps(self, value: float):
        with self._lock:
            self._fps = value
    
    @property
    def current_frame(self) -> int:
        return self._current_frame
    
    @property
    def current_time(self) -> float:
        return self._current_frame / self._fps if self._fps > 0 else 0
    
    @property
    def total_frames(self) -> int:
        return self._total_frames
    
    @total_frames.setter
    def total_frames(self, value: int):
        with self._lock:
            self._total_frames = value
    
    @property
    def total_time(self) -> float:
        return self._total_frames / self._fps if self._fps > 0 else 0
    
    @property
    def is_playing(self) -> bool:
        return self._playing
    
    def set_frame(self, frame: int):
        """设置当前帧"""
        with self._lock:
            self._current_frame = max(0, min(frame, self._total_frames))
    
    def set_time(self, time_seconds: float):
        """设置当前时间（秒）"""
        self.set_frame(int(time_seconds * self._fps))
    
    def frame_to_timecode(self, frame: int = None) -> str:
        """帧转时间码"""
        frame = frame if frame is not None else self._current_frame
        total_seconds = frame / self._fps if self._fps > 0 else 0
        hours = int(total_seconds // 3600)
        minutes = int((total_seconds % 3600) // 60)
        seconds = int(total_seconds % 60)
        frames = int((total_seconds % 1) * self._fps)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frames:02d}"
    
    def timecode_to_frame(self, timecode: str) -> int:
        """时间码转帧"""
        parts = timecode.split(':')
        if len(parts) != 4:
            return 0
        hours, minutes, seconds, frames = map(int, parts)
        total_seconds = hours * 3600 + minutes * 60 + seconds + frames / self._fps
        return int(total_seconds * self._fps)
    
    def play(self):
        """开始播放"""
        with self._lock:
            if not self._playing:
                self._playing = True
                self._start_time = time.time() - self.current_time
    
    def pause(self):
        """暂停播放"""
        with self._lock:
            if self._playing:
                self._playing = False
                self._pause_time = time.time()
    
    def stop(self):
        """停止播放"""
        with self._lock:
            self._playing = False
            self._current_frame = 0
    
    def seek(self, frame: int):
        """跳转到指定帧"""
        self.set_frame(frame)
    
    def seek_to_start(self):
        """跳转到开始"""
        self.set_frame(0)
    
    def seek_to_end(self):
        """跳转到结束"""
        self.set_frame(self._total_frames)
    
    def step_forward(self, frames: int = 1):
        """向前步进"""
        self.set_frame(self._current_frame + frames)
    
    def step_backward(self, frames: int = 1):
        """向后步进"""
        self.set_frame(self._current_frame - frames)
    
    def tick(self) -> int:
        """
        时钟滴答 - 播放时每帧调用
        返回当前帧
        """
        with self._lock:
            if self._playing and self._total_frames > 0:
                elapsed = time.time() - self._start_time
                self._current_frame = int(elapsed * self._fps)
                if self._current_frame >= self._total_frames:
                    self._current_frame = self._total_frames
                    self._playing = False
            return self._current_frame
    
    @classmethod
    def get_instance(cls) -> 'MasterClock':
        return cls()


class DataBus:
    """
    数据总线 - 模块间数据共享
    
    用于：
    - 项目数据共享
    - 配置数据共享
    - 临时数据传递
    """
    
    _instance: Optional['DataBus'] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._data: Dict[str, Any] = {}
        self._lock = threading.RLock()  # 可重入锁，避免嵌套调用死锁
    
    def set(self, key: str, value: Any):
        """设置数据"""
        with self._lock:
            self._data[key] = value
    
    def get(self, key: str, default: Any = None) -> Any:
        """获取数据"""
        with self._lock:
            return self._data.get(key, default)
    
    def has(self, key: str) -> bool:
        """检查数据是否存在"""
        with self._lock:
            return key in self._data
    
    def delete(self, key: str):
        """删除数据"""
        with self._lock:
            if key in self._data:
                del self._data[key]
    
    def clear(self):
        """清空所有数据"""
        with self._lock:
            self._data.clear()
    
    def keys(self) -> List[str]:
        """获取所有键"""
        with self._lock:
            return list(self._data.keys())
    
    def to_dict(self) -> Dict[str, Any]:
        """导出为字典"""
        with self._lock:
            return self._data.copy()
    
    def from_dict(self, data: Dict[str, Any]):
        """从字典导入"""
        with self._lock:
            self._data.update(data)
    
    @classmethod
    def get_instance(cls) -> 'DataBus':
        return cls()


class TimelineModel:
    """
    轨道/时间轴模型 - 视频编辑的核心数据结构
    """
    
    def __init__(self):
        self._tracks: List[Dict[str, Any]] = []
        self._duration: float = 0.0
        self._fps: float = 30.0
        self._lock = threading.Lock()
        self._event_bus = EventBus.get_instance()
    
    @property
    def duration(self) -> float:
        return self._duration
    
    @property
    def fps(self) -> float:
        return self._fps
    
    @fps.setter
    def fps(self, value: float):
        self._fps = value
    
    @property
    def track_count(self) -> int:
        return len(self._tracks)
    
    def add_track(self, track_type: str = "video", name: str = "") -> Dict[str, Any]:
        """添加轨道"""
        with self._lock:
            track = {
                "id": str(uuid.uuid4())[:8],
                "type": track_type,
                "name": name or f"{track_type}_{len(self._tracks)}",
                "clips": [],
                "muted": False,
                "locked": False,
                "visible": True
            }
            self._tracks.append(track)
        self._event_bus.emit(EventType.TRACK_ADDED, {"track": track})
        return track
    
    def remove_track(self, track_id: str) -> bool:
        """移除轨道"""
        removed = None
        with self._lock:
            for i, track in enumerate(self._tracks):
                if track["id"] == track_id:
                    removed = self._tracks.pop(i)
                    break
        if removed:
            self._event_bus.emit(EventType.TRACK_REMOVED, {"track": removed})
            return True
        return False
    
    def get_track(self, track_id: str) -> Optional[Dict[str, Any]]:
        """获取轨道"""
        with self._lock:
            for track in self._tracks:
                if track["id"] == track_id:
                    return track
        return None
    
    def get_tracks_by_type(self, track_type: str) -> List[Dict[str, Any]]:
        """按类型获取轨道"""
        with self._lock:
            return [t for t in self._tracks if t["type"] == track_type]
    
    def add_clip(self, track_id: str, clip: Dict[str, Any]) -> bool:
        """添加剪辑片段"""
        with self._lock:
            track = self._get_track_unsafe(track_id)
            if not track:
                return False
            if "id" not in clip:
                clip["id"] = str(uuid.uuid4())[:8]
            track["clips"].append(clip)
            self._update_duration_unsafe()
        self._event_bus.emit(EventType.CLIP_ADDED, {"track_id": track_id, "clip": clip})
        return True
    
    def remove_clip(self, track_id: str, clip_id: str) -> bool:
        """移除剪辑片段"""
        removed = None
        with self._lock:
            track = self._get_track_unsafe(track_id)
            if not track:
                return False
            for i, clip in enumerate(track["clips"]):
                if clip["id"] == clip_id:
                    removed = track["clips"].pop(i)
                    self._update_duration_unsafe()
                    break
        if removed:
            self._event_bus.emit(EventType.CLIP_REMOVED, {"track_id": track_id, "clip": removed})
            return True
        return False
    
    def _get_track_unsafe(self, track_id: str) -> Optional[Dict[str, Any]]:
        """内部使用：不加锁的轨道查找（调用方必须持有锁）"""
        for track in self._tracks:
            if track["id"] == track_id:
                return track
        return None
    
    def _update_duration_unsafe(self):
        """内部使用：不加锁的时长更新（调用方必须持有锁）"""
        max_end = 0.0
        for track in self._tracks:
            for clip in track["clips"]:
                end = clip.get("start", 0) + clip.get("duration", 0)
                if end > max_end:
                    max_end = end
        self._duration = max_end
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化"""
        with self._lock:
            return {
                "tracks": list(self._tracks),
                "duration": self._duration,
                "fps": self._fps
            }
    
    def from_dict(self, data: Dict[str, Any]):
        """反序列化"""
        with self._lock:
            self._tracks = data.get("tracks", [])
            self._duration = data.get("duration", 0.0)
            self._fps = data.get("fps", 30.0)


event_bus = EventBus.get_instance()
master_clock = MasterClock.get_instance()
data_bus = DataBus.get_instance()

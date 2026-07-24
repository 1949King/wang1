"""
剪辑引擎接口标准化 - Week 5核心组件
=====================================
定义统一的剪辑接口标准，实现编辑器、时间轴、轨道、片段、特效等接口
目标：接口标准化、模块解耦、易于扩展
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from enum import Enum
import uuid
import time
import threading
from datetime import datetime

from app.modules.utils.logger import logger

class EditMode(Enum):
    """编辑模式"""
    NORMAL = "normal"      # 正常编辑
    RIPPLE = "ripple"      # 波纹编辑
    ROLLING = "rolling"    # 滚动编辑
    SLIP = "slip"        # 滑动编辑

class TrackType(Enum):
    """轨道类型"""
    VIDEO = "video"
    AUDIO = "audio"
    SUBTITLE = "subtitle"
    EFFECT = "effect"

class ClipState(Enum):
    """片段状态"""
    ACTIVE = "active"
    LOCKED = "locked"
    MUTED = "muted"
    HIDDEN = "hidden"

class EditAction(Enum):
    """编辑操作类型"""
    CREATE_CLIP = "create_clip"
    DELETE_CLIP = "delete_clip"
    MOVE_CLIP = "move_clip"
    RESIZE_CLIP = "resize_clip"
    SPLIT_CLIP = "split_clip"
    TRIM_CLIP = "trim_clip"
    SPEED_CHANGE = "speed_change"
    REVERSE = "reverse"
    ROTATE = "rotate"
    CROP = "crop"
    APPLY_EFFECT = "apply_effect"
    APPLY_TRANSITION = "apply_transition"
    APPLY_FILTER = "apply_filter"

@dataclass
class TrackInfo:
    """轨道信息"""
    track_id: str
    track_type: TrackType
    name: str
    locked: bool = False
    muted: bool = False
    hidden: bool = False
    volume: float = 1.0
    pan: float = 0.0
    solo: bool = False

@dataclass
class ClipInfo:
    """片段信息"""
    clip_id: str
    track_id: str
    start_time: float
    end_time: float
    duration: float
    state: ClipState = ClipState.ACTIVE
    effects: List[str] = field(default_factory=list)
    transitions: List[str] = field(default_factory=list)
    filters: List[str] = field(default_factory=list)
    speed: float = 1.0
    in_point: float = 0.0
    out_point: float = 0.0

@dataclass
class TimelineInfo:
    """时间轴信息"""
    duration: float
    fps: float
    pixel_ratio: str
    tracks: List[TrackInfo] = field(default_factory=list)
    clips: List[ClipInfo] = field(default_factory=list)
    markers: List[Dict[str, Any]] = field(default_factory=list)

@dataclass
class EditResult:
    """编辑结果"""
    success: bool
    action: EditAction
    affected_objects: List[str] = field(default_factory=list)
    message: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

class IEditor(ABC):
    """编辑器基础接口"""
    
    @abstractmethod
    def initialize(self) -> bool:
        """初始化编辑器"""
        pass
    
    @abstractmethod
    def shutdown(self) -> bool:
        """关闭编辑器"""
        pass
    
    @abstractmethod
    def get_timeline_info(self) -> Optional[TimelineInfo]:
        """获取时间轴信息"""
        pass
    
    @abstractmethod
    def create_track(self, track_type: TrackType, name: str, 
                   position: int = 0) -> str:
        """创建轨道
        
        Args:
            track_type: 轨道类型
            name: 轨道名称
            position: 轨道位置
            
        Returns:
            轨道ID
        """
        pass
    
    @abstractmethod
    def delete_track(self, track_id: str) -> bool:
        """删除轨道"""
        pass
    
    @abstractmethod
    def update_track(self, track_id: str, **kwargs) -> bool:
        """更新轨道信息"""
        pass
    
    @abstractmethod
    def create_clip(self, track_id: str, start_time: float, 
                   end_time: float, **kwargs) -> str:
        """创建片段
        
        Args:
            track_id: 轨道ID
            start_time: 开始时间
            end_time: 结束时间
            **kwargs: 其他参数
            
        Returns:
            片段ID
        """
        pass
    
    @abstractmethod
    def delete_clip(self, clip_id: str) -> bool:
        """删除片段"""
        pass
    
    @abstractmethod
    def update_clip(self, clip_id: str, **kwargs) -> bool:
        """更新片段信息"""
        pass
    
    @abstractmethod
    def move_clip(self, clip_id: str, new_track_id: Optional[str] = None, 
                 new_start_time: Optional[float] = None) -> bool:
        """移动片段"""
        pass
    
    @abstractmethod
    def resize_clip(self, clip_id: str, new_start_time: Optional[float] = None, 
                   new_end_time: Optional[float] = None) -> bool:
        """调整片段时长"""
        pass
    
    @abstractmethod
    def split_clip(self, clip_id: str, split_time: float) -> Tuple[str, str]:
        """分割片段"""
        pass
    
    @abstractmethod
    def trim_clip(self, clip_id: str, new_start_time: float, 
                 new_end_time: float) -> bool:
        """裁剪片段"""
        pass
    
    @abstractmethod
    def change_speed(self, clip_id: str, speed: float) -> bool:
        """改变播放速度"""
        pass
    
    @abstractmethod
    def reverse_clip(self, clip_id: str) -> bool:
        """反转片段"""
        pass
    
    @abstractmethod
    def rotate_clip(self, clip_id: str, angle: float) -> bool:
        """旋转片段"""
        pass
    
    @abstractmethod
    def crop_clip(self, clip_id: str, x: int, y: int, 
                width: int, height: int) -> bool:
        """裁剪片段"""
        pass
    
    @abstractmethod
    def apply_effect(self, clip_id: str, effect_id: str, 
                   parameters: Dict[str, Any] = None) -> bool:
        """应用特效"""
        pass
    
    @abstractmethod
    def apply_transition(self, clip_id: str, transition_id: str, 
                     parameters: Dict[str, Any] = None) -> bool:
        """应用转场"""
        pass
    
    @abstractmethod
    def apply_filter(self, clip_id: str, filter_id: str, 
                   parameters: Dict[str, Any] = None) -> bool:
        """应用滤镜"""
        pass
    
    @abstractmethod
    def undo(self) -> bool:
        """撤销操作"""
        pass
    
    @abstractmethod
    def redo(self) -> bool:
        """重做操作"""
        pass
    
    @abstractmethod
    def get_history(self, max_items: int = 50) -> List[EditResult]:
        """获取编辑历史"""
        pass
    
    @abstractmethod
    def clear_history(self) -> bool:
        """清空编辑历史"""
        pass

class ITimelineEditor(IEditor):
    """时间轴编辑器接口"""
    
    @abstractmethod
    def add_track(self, track_type: TrackType, name: str, 
                   position: int = 0) -> str:
        """添加轨道"""
        pass
    
    @abstractmethod
    def remove_track(self, track_id: str) -> bool:
        """移除轨道"""
        pass
    
    @abstractmethod
    def move_track(self, track_id: str, new_position: int) -> bool:
        """移动轨道位置"""
        pass
    
    @abstractmethod
    def lock_track(self, track_id: str) -> bool:
        """锁定轨道"""
        pass
    
    @abstractmethod
    def unlock_track(self, track_id: str) -> bool:
        """解锁轨道"""
        pass
    
    @abstractmethod
    def mute_track(self, track_id: str) -> bool:
        """静音轨道"""
        pass
    
    @abstractmethod
    def unmute_track(self, track_id: str) -> bool:
        """取消静音"""
        pass
    
    @abstractmethod
    def hide_track(self, track_id: str) -> bool:
        """隐藏轨道"""
        pass
    
    @abstractmethod
    def show_track(self, track_id: str) -> bool:
        """显示轨道"""
        pass
    
    @abstractmethod
    def set_track_volume(self, track_id: str, volume: float) -> bool:
        """设置轨道音量"""
        pass
    
    @abstractmethod
    def set_track_pan(self, track_id: str, pan: float) -> bool:
        """设置轨道声像"""
        pass

class IClipEditor(IEditor):
    """片段编辑器接口"""
    
    @abstractmethod
    def create_clip(self, track_id: str, start_time: float, 
                   end_time: float, **kwargs) -> str:
        """创建片段"""
        pass
    
    @abstractmethod
    def delete_clip(self, clip_id: str) -> bool:
        """删除片段"""
        pass
    
    @abstractmethod
    def update_clip(self, clip_id: str, **kwargs) -> bool:
        """更新片段"""
        pass
    
    @abstractmethod
    def move_clip(self, clip_id: str, new_track_id: Optional[str] = None, 
                 new_start_time: Optional[float] = None) -> bool:
        """移动片段"""
        pass
    
    @abstractmethod
    def resize_clip(self, clip_id: str, new_start_time: Optional[float] = None, 
                   new_end_time: Optional[float] = None) -> bool:
        """调整时长"""
        pass
    
    @abstractmethod
    def split_clip(self, clip_id: str, split_time: float) -> Tuple[str, str]:
        """分割片段"""
        pass
    
    @abstractmethod
    def trim_clip(self, clip_id: str, new_start_time: float, 
                   new_end_time: float) -> bool:
        """裁剪片段"""
        pass
    
    @abstractmethod
    def change_speed(self, clip_id: str, speed: float) -> bool:
        """改变播放速度"""
        pass
    
    @abstractmethod
    def reverse_clip(self, clip_id: str) -> bool:
        """反转片段"""
        pass
    
    @abstractmethod
    def rotate_clip(self, clip_id: str, angle: float) -> bool:
        """旋转片段"""
        pass
    
    @abstractmethod
    def crop_clip(self, clip_id: str, x: int, y: int, 
                width: int, height: int) -> bool:
        """裁剪片段"""
        pass
    
    @abstractmethod
    def apply_effect(self, clip_id: str, effect_id: str, 
                   parameters: Dict[str, Any] = None) -> bool:
        """应用特效"""
        pass
    
    @abstractmethod
    def apply_transition(self, clip_id: str, transition_id: str, 
                     parameters: Dict[str, Any] = None) -> bool:
        """应用转场"""
        pass
    
    @abstractmethod
    def apply_filter(self, clip_id: str, filter_id: str, 
                   parameters: Dict[str, Any] = None) -> bool:
        """应用滤镜"""
        pass

class IEffectEditor(IEditor):
    """特效编辑器接口"""
    
    @abstractmethod
    def apply_effect(self, clip_id: str, effect_id: str, 
                   parameters: Dict[str, Any] = None) -> bool:
        """应用特效到片段"""
        pass
    
    @abstractmethod
    def remove_effect(self, clip_id: str, effect_id: str) -> bool:
        """移除片段特效"""
        pass
    
    @abstractmethod
    def get_available_effects(self) -> List[Dict[str, Any]]:
        """获取可用特效列表"""
        pass
    
    @abstractmethod
    def get_effect_parameters(self, effect_id: str) -> Dict[str, Any]:
        """获取特效参数"""
        pass

class ITransitionEditor(IEditor):
    """转场编辑器接口"""
    
    @abstractmethod
    def apply_transition(self, clip_id: str, transition_id: str, 
                     parameters: Dict[str, Any] = None) -> bool:
        """应用转场"""
        pass
    
    @abstractmethod
    def remove_transition(self, clip_id: str, transition_id: str) -> bool:
        """移除转场"""
        pass
    
    @abstractmethod
    def get_available_transitions(self) -> List[Dict[str, Any]]:
        """获取可用转场列表"""
        pass
    
    @abstractmethod
    def get_transition_parameters(self, transition_id: str) -> Dict[str, Any]:
        """获取转场参数"""
        pass

class IFilterEditor(IEditor):
    """滤镜编辑器接口"""
    
    @abstractmethod
    def apply_filter(self, clip_id: str, filter_id: str, 
                   parameters: Dict[str, Any] = None) -> bool:
        """应用滤镜"""
        pass
    
    @abstractmethod
    def remove_filter(self, clip_id: str, filter_id: str) -> bool:
        """移除滤镜"""
        pass
    
    @abstractmethod
    def get_available_filters(self) -> List[Dict[str, Any]]:
        """获取可用滤镜列表"""
        pass
    
    @abstractmethod
    def get_filter_parameters(self, filter_id: str) -> Dict[str, Any]:
        """获取滤镜参数"""
        pass

class EditorFactory:
    """编辑器工厂"""
    
    @staticmethod
    def create_editor(editor_type: str) -> Optional[IEditor]:
        """创建编辑器实例"""
        if editor_type == "timeline":
            from app.modules.lego.video_editor.timeline_editor import TimelineEditor
            return TimelineEditor()
        elif editor_type == "clip":
            from app.modules.lego.video_editor.clip_editor import ClipEditor
            return ClipEditor()
        elif editor_type == "effect":
            from app.modules.lego.video_editor.effect_editor import EffectEditor
            return EffectEditor()
        elif editor_type == "transition":
            from app.modules.lego.video_editor.transition_editor import TransitionEditor
            return TransitionEditor()
        elif editor_type == "filter":
            from app.modules.lego.video_editor.filter_editor import FilterEditor
            return FilterEditor()
        else:
            logger.warning(f"未知编辑器类型: {editor_type}")
            return None

class UnifiedEditor(IEditor):
    """统一编辑器"""
    
    def __init__(self):
        self._timeline_editor = None
        self._clip_editor = None
        self._effect_editor = None
        self._transition_editor = None
        self._filter_editor = None
        self._initialized = False
        self._edit_history = []
        self._max_history = 100
        self._lock = threading.Lock()
        
        logger.info("统一编辑器初始化")
    
    def initialize(self) -> bool:
        """初始化统一编辑器"""
        try:
            # 初始化各个子编辑器
            self._timeline_editor = EditorFactory.create_editor("timeline")
            self._clip_editor = EditorFactory.create_editor("clip")
            self._effect_editor = EditorFactory.create_editor("effect")
            self._transition_editor = EditorFactory.create_editor("transition")
            self._filter_editor = EditorFactory.create_editor("filter")
            
            # 初始化子编辑器
            if self._timeline_editor:
                self._timeline_editor.initialize()
            if self._clip_editor:
                self._clip_editor.initialize()
            if self._effect_editor:
                self._effect_editor.initialize()
            if self._transition_editor:
                self._transition_editor.initialize()
            if self._filter_editor:
                self._filter_editor.initialize()
            
            self._initialized = True
            logger.info("统一编辑器初始化成功")
            return True
            
        except Exception as e:
            logger.error(f"统一编辑器初始化失败: {e}")
            return False
    
    def get_timeline_info(self) -> Optional[TimelineInfo]:
        """获取时间轴信息"""
        if not self._initialized:
            logger.warning("编辑器未初始化")
            return None
        
        return self._timeline_editor.get_timeline_info()
    
    def create_track(self, track_type: TrackType, name: str, 
                   position: int = 0) -> str:
        """创建轨道"""
        if not self._initialized:
            logger.warning("编辑器未初始化")
            return ""
        
        return self._timeline_editor.create_track(track_type, name, position)
    
    def delete_track(self, track_id: str) -> bool:
        """删除轨道"""
        if not self._initialized:
            logger.warning("编辑器未初始化")
            return False
        
        return self._timeline_editor.delete_track(track_id)
    
    def update_track(self, track_id: str, **kwargs) -> bool:
        """更新轨道"""
        if not self._initialized:
            logger.warning("编辑器未初始化")
            return False
        
        return self._timeline_editor.update_track(track_id, **kwargs)
    
    def create_clip(self, track_id: str, start_time: float, 
                   end_time: float, **kwargs) -> str:
        """创建片段"""
        if not self._initialized:
            logger.warning("编辑器未初始化")
            return ""
        
        return self._clip_editor.create_clip(track_id, start_time, end_time, **kwargs)
    
    def delete_clip(self, clip_id: str) -> bool:
        """删除片段"""
        if not self._initialized:
            logger.warning("编辑器未初始化")
            return False
        
        return self._clip_editor.delete_clip(clip_id)
    
    def update_clip(self, clip_id: str, **kwargs) -> bool:
        """更新片段"""
        if not self._initialized:
            logger.warning("编辑器未初始化")
            return False
        
        return self._clip_editor.update_clip(clip_id, **kwargs)
    
    def move_clip(self, clip_id: str, new_track_id: Optional[str] = None, 
                 new_start_time: Optional[float] = None) -> bool:
        """移动片段"""
        if not self._initialized:
            logger.warning("编辑器未初始化")
            return False
        
        return self._clip_editor.move_clip(clip_id, new_track_id, new_start_time)
    
    def resize_clip(self, clip_id: str, new_start_time: Optional[float] = None, 
                   new_end_time: Optional[float] = None) -> bool:
        """调整时长"""
        if not self._initialized:
            logger.warning("编辑器未初始化")
            return False
        
        return self._clip_editor.resize_clip(clip_id, new_start_time, new_end_time)
    
    def split_clip(self, clip_id: str, split_time: float) -> Tuple[str, str]:
        """分割片段"""
        if not self._initialized:
            logger.warning("编辑器未初始化")
            return ("", "")
        
        return self._clip_editor.split_clip(clip_id, split_time)
    
    def trim_clip(self, clip_id: str, new_start_time: float, 
                   new_end_time: float) -> bool:
        """裁剪片段"""
        if not self._initialized:
            logger.warning("编辑器未初始化")
            return False
        
        return self._clip_editor.trim_clip(clip_id, new_start_time, new_end_time)
    
    def change_speed(self, clip_id: str, speed: float) -> bool:
        """改变播放速度"""
        if not self._initialized:
            logger.warning("编辑器未初始化")
            return False
        
        return self._clip_editor.change_speed(clip_id, speed)
    
    def reverse_clip(self, clip_id: str) -> bool:
        """反转片段"""
        if not self._initialized:
            logger.warning("编辑器未初始化")
            return False
        
        return self._clip_editor.reverse_clip(clip_id)
    
    def rotate_clip(self, clip_id: str, angle: float) -> bool:
        """旋转片段"""
        if not self._initialized:
            logger.warning("编辑器未初始化")
            return False
        
        return self._clip_editor.rotate_clip(clip_id, angle)
    
    def crop_clip(self, clip_id: str, x: int, y: int, 
                width: int, height: int) -> bool:
        """裁剪片段"""
        if not self._initialized:
            logger.warning("编辑器未初始化")
            return False
        
        return self._clip_editor.crop_clip(clip_id, x, y, width, height)
    
    def apply_effect(self, clip_id: str, effect_id: str, 
                   parameters: Dict[str, Any] = None) -> bool:
        """应用特效"""
        if not self._initialized:
            logger.warning("编辑器未初始化")
            return False
        
        return self._clip_editor.apply_effect(clip_id, effect_id, parameters)
    
    def apply_transition(self, clip_id: str, transition_id: str, 
                     parameters: Dict[str, Any] = None) -> bool:
        """应用转场"""
        if not self._initialized:
            logger.warning("编辑器未初始化")
            return False
        
        return self._clip_editor.apply_transition(clip_id, transition_id, parameters)
    
    def apply_filter(self, clip_id: str, filter_id: str, 
                   parameters: Dict[str, Any] = None) -> bool:
        """应用滤镜"""
        if not self._initialized:
            logger.warning("编辑器未初始化")
            return False
        
        return self._clip_editor.apply_filter(clip_id, filter_id, parameters)
    
    def undo(self) -> bool:
        """撤销操作"""
        if not self._initialized:
            logger.warning("编辑器未初始化")
            return False
        
        return self._clip_editor.undo()
    
    def redo(self) -> bool:
        """重做操作"""
        if not self._initialized:
            logger.warning("编辑器未初始化")
            return False
        
        return self._clip_editor.redo()
    
    def get_history(self, max_items: int = 50) -> List[EditResult]:
        """获取编辑历史"""
        if not self._initialized:
            logger.warning("编辑器未初始化")
            return []
        
        return self._clip_editor.get_history(max_items)
    
    def clear_history(self) -> bool:
        """清空编辑历史"""
        if not self._initialized:
            logger.warning("编辑器未初始化")
            return False
        
        return self._clip_editor.clear_history()
    
    def shutdown(self) -> bool:
        """关闭编辑器"""
        if not self._initialized:
            logger.warning("编辑器未初始化")
            return False
        
        # 关闭所有子编辑器
        if self._timeline_editor:
            self._timeline_editor.shutdown()
        if self._clip_editor:
            self._clip_editor.shutdown()
        if self._effect_editor:
            self._effect_editor.shutdown()
        if self._transition_editor:
            self._transition_editor.shutdown()
        if self._filter_editor:
            self._filter_editor.shutdown()
        
        self._initialized = False
        logger.info("统一编辑器已关闭")
        return True
    
    def get_stats(self) -> Dict[str, Any]:
        """获取编辑器统计"""
        if not self._initialized:
            return {
                'initialized': False,
                'timeline_tracks': 0,
                'total_clips': 0,
                'history_items': 0
            }
        
        with self._lock:
            return {
                'initialized': self._initialized,
                'timeline_tracks': self._timeline_editor.get_stats().get('total_tracks', 0),
                'total_clips': self._clip_editor.get_stats().get('total_clips', 0),
                'history_items': len(self._edit_history),
                'active_effects': self._effect_editor.get_stats().get('active_effects', 0),
                'active_transitions': self._transition_editor.get_stats().get('active_transitions', 0),
                'active_filters': self._filter_editor.get_stats().get('active_filters', 0)
            }

# 全局统一编辑器实例
unified_editor = None
_editor_lock = threading.Lock()

def get_unified_editor() -> UnifiedEditor:
    """获取统一编辑器实例（单例模式）"""
    global unified_editor
    if unified_editor is None:
        with _editor_lock:
            if unified_editor is None:
                unified_editor = UnifiedEditor()
    return unified_editor
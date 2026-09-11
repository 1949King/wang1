"""
撤销/重做管理系统
==================
提供全局撤销/重做功能，支持多级操作历史管理
"""

from typing import Dict, List, Optional, Any, Callable
from PyQt6.QtCore import QObject, pyqtSignal
from collections import deque
import logging
import os

logger = logging.getLogger("AI短剧编辑器.undo_manager")


class ActionType:
    """操作类型"""
    CLIP_ADD = "clip_add"
    CLIP_REMOVE = "clip_remove"
    CLIP_MOVE = "clip_move"
    CLIP_RESIZE = "clip_resize"
    CLIP_SPLIT = "clip_split"
    EFFECT_APPLY = "effect_apply"
    EFFECT_REMOVE = "effect_remove"
    SUBTITLE_ADD = "subtitle_add"
    SUBTITLE_REMOVE = "subtitle_remove"
    MATERIAL_ADD = "material_add"
    MATERIAL_REMOVE = "material_remove"
    TIMELINE_CHANGE = "timeline_change"
    TRACK_ADD = "track_add"
    TRACK_REMOVE = "track_remove"
    CUSTOM = "custom"


class UndoAction:
    """撤销操作"""
    
    def __init__(self, action_type: str, description: str, data: Dict[str, Any], 
                 timestamp: float, undo_callable: Optional[Callable] = None):
        self.action_type = action_type
        self.description = description
        self.data = data
        self.timestamp = timestamp
        self.undo_callable = undo_callable
    
    def execute_undo(self) -> None:
        """执行撤销操作"""
        if self.undo_callable:
            self.undo_callable(self.data)
            logger.info(f"执行撤销操作: {self.action_type} - {self.description}")
        else:
            logger.warning(f"撤销操作没有回调函数: {self.action_type}")
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'action_type': self.action_type,
            'description': self.description,
            'data': self.data,
            'timestamp': self.timestamp
        }


class UndoManager(QObject):
    """撤销/重做管理器"""
    
    undo_performed = pyqtSignal(str)
    redo_performed = pyqtSignal(str)
    history_changed = pyqtSignal(int)
    can_undo_changed = pyqtSignal(bool)
    can_redo_changed = pyqtSignal(bool)
    
    def __init__(self):
        super().__init__()
        self._undo_stack = deque(maxlen=100)
        self._redo_stack = deque(maxlen=100)
        self._current_position = -1
        self._max_history = 100
        self._auto_save_enabled = True
        self._save_interval = 30  # 自动保存间隔（秒）
        
        self._action_handlers = {}
        self._register_default_handlers()
    
    def _register_default_handlers(self):
        """注册默认操作处理器"""
        self._action_handlers = {
            ActionType.CLIP_ADD: self._handle_clip_add,
            ActionType.CLIP_REMOVE: self._handle_clip_remove,
            ActionType.CLIP_MOVE: self._handle_clip_move,
            ActionType.CLIP_RESIZE: self._handle_clip_resize,
            ActionType.CLIP_SPLIT: self._handle_clip_split,
            ActionType.EFFECT_APPLY: self._handle_effect_apply,
            ActionType.EFFECT_REMOVE: self._handle_effect_remove,
            ActionType.SUBTITLE_ADD: self._handle_subtitle_add,
            ActionType.SUBTITLE_REMOVE: self._handle_subtitle_remove,
            ActionType.MATERIAL_ADD: self._handle_material_add,
            ActionType.MATERIAL_REMOVE: self._handle_material_remove,
            ActionType.TIMELINE_CHANGE: self._handle_timeline_change,
            ActionType.TRACK_ADD: self._handle_track_add,
            ActionType.TRACK_REMOVE: self._handle_track_remove,
        }
    
    def register_handler(self, action_type: str, handler: Callable) -> None:
        """注册自定义操作处理器"""
        self._action_handlers[action_type] = handler
        logger.info(f"注册操作处理器: {action_type}")
    
    def perform_action(self, action: UndoAction) -> bool:
        """执行操作"""
        try:
            handler = self._action_handlers.get(action.action_type)
            if handler:
                handler(action)
                self._add_to_undo_stack(action)
                self._clear_redo_stack()
                self._update_history_signals()
                logger.info(f"执行操作: {action.action_type} - {action.description}")
                return True
            else:
                logger.error(f"未找到操作处理器: {action.action_type}")
                return False
        except Exception as e:
            logger.error(f"执行操作失败: {e}")
            return False
    
    def _add_to_undo_stack(self, action: UndoAction) -> None:
        """添加到撤销栈"""
        self._undo_stack.append(action)
        self._current_position += 1
        
        if len(self._undo_stack) > self._max_history:
            self._undo_stack.popleft()  # 移除最旧的操作
            logger.info(f"撤销栈已满，移除最旧操作")
    
    def _clear_redo_stack(self) -> None:
        """清空重做栈"""
        self._redo_stack.clear()
        logger.info("清空重做栈")
    
    def _update_history_signals(self) -> None:
        """更新历史信号"""
        self.can_undo_changed.emit(self.can_undo())
        self.can_redo_changed.emit(self.can_redo())
        self.history_changed.emit(len(self._undo_stack))
    
    def undo(self) -> bool:
        """撤销上一个操作"""
        if not self.can_undo():
            logger.warning("无法撤销：没有可撤销的操作")
            return False
        
        try:
            action = self._undo_stack.pop()
            if action:
                action.execute_undo()
                self._current_position -= 1
                self._update_history_signals()
                self.undo_performed.emit(action.action_type)
                logger.info(f"撤销操作: {action.action_type}")
                return True
            else:
                logger.warning("撤销操作为空")
                return False
        except Exception as e:
            logger.error(f"撤销失败: {e}")
            return False
    
    def redo(self) -> bool:
        """重做下一个操作"""
        if not self.can_redo():
            logger.warning("无法重做：没有可重做的操作")
            return False
        
        try:
            action = self._redo_stack.pop()
            if action:
                action.execute_undo()
                self._add_to_undo_stack(action)
                self._update_history_signals()
                self.redo_performed.emit(action.action_type)
                logger.info(f"重做操作: {action.action_type}")
                return True
            else:
                logger.warning("重做操作为空")
                return False
        except Exception as e:
            logger.error(f"重做失败: {e}")
            return False
    
    def can_undo(self) -> bool:
        """是否可以撤销"""
        return len(self._undo_stack) > 0
    
    def can_redo(self) -> bool:
        """是否可以重做"""
        return len(self._redo_stack) > 0
    
    def get_history_count(self) -> int:
        """获取历史记录数量"""
        return len(self._undo_stack)
    
    def get_redo_count(self) -> int:
        """获取重做栈数量"""
        return len(self._redo_stack)
    
    def get_current_position(self) -> int:
        """获取当前位置"""
        return self._current_position
    
    def clear_history(self) -> None:
        """清空历史记录"""
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._current_position = -1
        self._update_history_signals()
        logger.info("清空历史记录")
    
    def get_history(self) -> List[Dict[str, Any]]:
        """获取历史记录"""
        return [action.to_dict() for action in self._undo_stack]
    
    def get_redo_history(self) -> List[Dict[str, Any]]:
        """获取重做历史"""
        return [action.to_dict() for action in self._redo_stack]
    
    def set_max_history(self, max_size: int) -> None:
        """设置最大历史记录数量"""
        self._max_history = max_size
        
        # 调整栈大小
        while len(self._undo_stack) > max_size:
            self._undo_stack.popleft()
        
        while len(self._redo_stack) > max_size:
            self._redo_stack.pop()
        
        logger.info(f"设置最大历史记录数量: {max_size}")
    
    def set_auto_save(self, enabled: bool, interval: int = 30) -> None:
        """设置自动保存"""
        self._auto_save_enabled = enabled
        self._save_interval = interval
        logger.info(f"自动保存: {'启用' if enabled else '禁用'}，间隔: {interval}秒")
    
    def save_state(self, state_name: str, state_data: Dict[str, Any]) -> None:
        """保存状态（用于自动保存）"""
        if not self._auto_save_enabled:
            return
        
        try:
            import json
            state_file = f"state_{state_name}.json"
            
            with open(state_file, 'w', encoding='utf-8') as f:
                json.dump(state_data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"保存状态: {state_name}")
        except Exception as e:
            logger.error(f"保存状态失败: {e}")
    
    def load_state(self, state_name: str) -> Optional[Dict[str, Any]]:
        """加载状态"""
        try:
            import json
            state_file = f"state_{state_name}.json"
            
            if not os.path.exists(state_file):
                logger.warning(f"状态文件不存在: {state_file}")
                return None
            
            with open(state_file, 'r', encoding='utf-8') as f:
                state_data = json.load(f)
            
            logger.info(f"加载状态: {state_name}")
            return state_data
        except Exception as e:
            logger.error(f"加载状态失败: {e}")
            return None
    
    def _handle_clip_add(self, action: UndoAction) -> None:
        """处理片段添加"""
        logger.info(f"处理片段添加: {action.data}")
    
    def _handle_clip_remove(self, action: UndoAction) -> None:
        """处理片段删除"""
        logger.info(f"处理片段删除: {action.data}")
    
    def _handle_clip_move(self, action: UndoAction) -> None:
        """处理片段移动"""
        logger.info(f"处理片段移动: {action.data}")
    
    def _handle_clip_resize(self, action: UndoAction) -> None:
        """处理片段调整大小"""
        logger.info(f"处理片段调整: {action.data}")
    
    def _handle_clip_split(self, action: UndoAction) -> None:
        """处理片段分割"""
        logger.info(f"处理片段分割: {action.data}")
    
    def _handle_effect_apply(self, action: UndoAction) -> None:
        """处理效果应用"""
        logger.info(f"处理效果应用: {action.data}")
    
    def _handle_effect_remove(self, action: UndoAction) -> None:
        """处理效果删除"""
        logger.info(f"处理效果删除: {action.data}")
    
    def _handle_subtitle_add(self, action: UndoAction) -> None:
        """处理字幕添加"""
        logger.info(f"处理字幕添加: {action.data}")
    
    def _handle_subtitle_remove(self, action: UndoAction) -> None:
        """处理字幕删除"""
        logger.info(f"处理字幕删除: {action.data}")
    
    def _handle_material_add(self, action: UndoAction) -> None:
        """处理素材添加"""
        logger.info(f"处理素材添加: {action.data}")
    
    def _handle_material_remove(self, action: UndoAction) -> None:
        """处理素材删除"""
        logger.info(f"处理素材删除: {action.data}")
    
    def _handle_timeline_change(self, action: UndoAction) -> None:
        """处理时间线变更"""
        logger.info(f"处理时间线变更: {action.data}")
    
    def _handle_track_add(self, action: UndoAction) -> None:
        """处理轨道添加"""
        logger.info(f"处理轨道添加: {action.data}")
    
    def _handle_track_remove(self, action: UndoAction) -> None:
        """处理轨道删除"""
        logger.info(f"处理轨道删除: {action.data}")


# 全局撤销/重做管理器实例
undo_manager = UndoManager()
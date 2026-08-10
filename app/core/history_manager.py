"""
历史管理器 - 带状态快照的操作撤销/重做系统
"""

import json
import copy
from typing import Dict, Any, Optional, Callable, List


class HistoryAction:
    """历史操作记录"""

    def __init__(self, action_type: str, description: str,
                 forward_data: Dict = None, backward_data: Dict = None,
                 forward_callback: Callable = None, backward_callback: Callable = None):
        self.action_type = action_type
        self.description = description
        self.forward_data = forward_data or {}
        self.backward_data = backward_data or {}
        self._forward_cb = forward_callback
        self._backward_cb = backward_callback
        self._applied = True

    def revert(self) -> bool:
        if self._backward_cb:
            self._backward_cb(self.backward_data)
        self._applied = False
        return True

    def reapply(self) -> bool:
        if self._forward_cb:
            self._forward_cb(self.forward_data)
        self._applied = True
        return True


class HistoryManager:
    """操作历史管理器 - 支持撤销/重做流水线"""

    def __init__(self, max_history: int = 50):
        self._undo_stack: List[HistoryAction] = []
        self._redo_stack: List[HistoryAction] = []
        self.max_history = max_history
        self._observers: List[Callable] = []

    def add_action(self, action_type: str, description: str,
                   forward_data: Dict = None, backward_data: Dict = None,
                   forward_callback: Callable = None, backward_callback: Callable = None):
        """添加可撤销的操作"""
        action = HistoryAction(
            action_type=action_type,
            description=description,
            forward_data=forward_data,
            backward_data=backward_data,
            forward_callback=forward_callback,
            backward_callback=backward_callback,
        )
        self._undo_stack.append(action)
        self._redo_stack.clear()
        if len(self._undo_stack) > self.max_history:
            self._undo_stack.pop(0)
        self._notify()

    def add_simple(self, description: str):
        """添加简单的不可撤销操作标记"""
        action = HistoryAction(action_type="marker", description=description)
        self._undo_stack.append(action)
        self._redo_stack.clear()
        if len(self._undo_stack) > self.max_history:
            self._undo_stack.pop(0)
        self._notify()

    def undo(self) -> Optional[HistoryAction]:
        """撤销最近一步操作"""
        if not self._undo_stack:
            return None
        action = self._undo_stack.pop()
        action.revert()
        self._redo_stack.append(action)
        self._notify()
        return action

    def redo(self) -> Optional[HistoryAction]:
        """重做最近撤销的操作"""
        if not self._redo_stack:
            return None
        action = self._redo_stack.pop()
        action.reapply()
        self._undo_stack.append(action)
        self._notify()
        return action

    def can_undo(self) -> bool:
        return len(self._undo_stack) > 0

    def can_redo(self) -> bool:
        return len(self._redo_stack) > 0

    def undo_count(self) -> int:
        return len(self._undo_stack)

    def redo_count(self) -> int:
        return len(self._redo_stack)

    def clear(self):
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._notify()

    def on_change(self, callback: Callable):
        self._observers.append(callback)

    def _notify(self):
        for cb in self._observers:
            try:
                cb()
            except Exception as e:
                logger.debug(f"[HistoryManager] 通知观察者失败: {e}")

    def to_list(self) -> List[Dict]:
        return [{
            'type': a.action_type,
            'desc': a.description,
            'applied': a._applied,
        } for a in self._undo_stack]

    def snapshot_state(self, state_getter: Callable) -> Dict:
        """获取当前状态快照"""
        try:
            state = state_getter()
            return copy.deepcopy(state)
        except Exception:
            return {}

    def attach_state_restore(self, action_type: str, description: str,
                              before_state: Dict, after_state: Dict,
                              restore_callback: Callable):
        """附加状态快照的撤销操作"""
        self.add_action(
            action_type=action_type,
            description=description,
            forward_data={'state': after_state},
            backward_data={'state': before_state},
            forward_callback=lambda d: restore_callback(d['state']),
            backward_callback=lambda d: restore_callback(d['state']),
        )

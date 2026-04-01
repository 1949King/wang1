class HistoryManager:
    def __init__(self, max_history=50):
        self.history_stack = []
        self.redo_stack = []
        self.max_history = max_history
    
    def add_action(self, action, description):
        """添加操作到历史记录"""
        self.history_stack.append({
            "action": action,
            "description": description
        })
        # 清空重做栈
        self.redo_stack = []
        # 限制历史记录数量
        if len(self.history_stack) > self.max_history:
            self.history_stack.pop(0)
    
    def undo(self):
        """撤销上一步操作"""
        if not self.history_stack:
            return None
        
        action = self.history_stack.pop()
        self.redo_stack.append(action)
        return action
    
    def redo(self):
        """重做上一步撤销的操作"""
        if not self.redo_stack:
            return None
        
        action = self.redo_stack.pop()
        self.history_stack.append(action)
        return action
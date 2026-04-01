from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTextEdit, QComboBox
from PyQt5.QtCore import Qt, pyqtSignal

class AgentPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        self.task_label = QLabel("Agent任务面板")
        layout.addWidget(self.task_label)
        
        self.task_combo = QComboBox()
        self.task_combo.addItems(["分析视频", "生成文案", "智能剪辑", "批量处理"])
        layout.addWidget(self.task_combo)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        layout.addWidget(self.log_text)
        
        btn_layout = QHBoxLayout()
        self.run_btn = QPushButton("运行")
        self.stop_btn = QPushButton("停止")
        btn_layout.addWidget(self.run_btn)
        btn_layout.addWidget(self.stop_btn)
        layout.addLayout(btn_layout)
        
        self.setLayout(layout)
    
    def log(self, message: str):
        self.log_text.append(message)
    
    def clear_log(self):
        self.log_text.clear()

def add_agent_button_to_toolbar(toolbar, callback=None):
    btn = QPushButton("Agent")
    if callback:
        btn.clicked.connect(callback)
    toolbar.addWidget(btn)
    return btn

__all__ = ['AgentPanel', 'add_agent_button_to_toolbar']

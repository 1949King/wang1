"""
base_module.py — 模块基类
=========================
从 modules.py 提取，解除子模块 → modules.py 的循环导入依赖。

所有业务模块继承 BaseModule，获得：
- EventBus / DataBus / MasterClock / SkillEngine 自动注入
- 统一的 set_theme() 接口
- on_activated() / on_deactivated() 生命周期
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

from .core import EventBus, DataBus, MasterClock
from .skill_engine import SkillEngine


class BaseModule(QWidget):
    """
    模块基类 - 所有模块必须继承此类

    特性:
    - 独立 QWidget
    - 只依赖内核,不依赖其他模块
    - 通过 EventBus 通信
    """

    module_id: str = "base"
    module_name: str = "基础模块"
    module_icon: str = "📦"

    def __init__(self):
        super().__init__()
        self._event_bus = EventBus.get_instance()
        self._data_bus = DataBus.get_instance()
        self._clock = MasterClock.get_instance()
        self._skill_engine = SkillEngine.get_instance()
        self._setup_ui()
        self._setup_event_handlers()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        title = QLabel(f"{self.module_icon} {self.module_name}")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #ffffff;")
        layout.addWidget(title)

    def _setup_event_handlers(self):
        pass

    def on_activated(self):
        pass

    def on_deactivated(self):
        pass

    def set_theme(self, theme: str):
        """设置主题 - 通过 theme 属性让全局 QSS 属性选择器自动响应"""
        self.setProperty("theme", theme)
        for child in self.findChildren(QWidget):
            child.setProperty("theme", theme)

"""
Qt6 主窗口 - 剪映同款标签页布局
==============================
专业级架构：左侧导航 + 标签页切换 + 底部状态栏
"""

from typing import Dict, List, Optional, Type
from dataclasses import dataclass
from enum import Enum
import logging

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QLabel, QPushButton, QFrame,
    QStatusBar, QSizePolicy, QScrollArea, QSpacerItem,
    QTabWidget, QSplitter, QToolBar
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QTimer
from PyQt6.QtGui import QIcon, QFont, QColor, QAction

from .core import EventBus, EventType, MasterClock, DataBus

logger = logging.getLogger("AI短剧编辑器.main_window")


class User:
    """用户信息类"""
    def __init__(self):
        self.name = "测试用户"
        self.email = "test@example.com"
        self.is_vip = True
        self.vip_expire = 9999999999  # 修改为合理的时间戳
        self.nickname = "测试用户"


class AuthService:
    """授权服务模拟类"""
    def __init__(self):
        self.is_logged_in = True
        self.current_user = User()


auth_service = AuthService()


class ModuleState(Enum):
    LOADED = "loaded"
    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"


@dataclass
class ModuleInfo:
    id: str
    name: str
    icon: str
    description: str
    widget_class: Optional[Type[QWidget]] = None
    instance: Optional[QWidget] = None
    state: ModuleState = ModuleState.INACTIVE


class NavigationButton(QPushButton):
    """导航按钮 - 剪映风格"""
    
    def __init__(self, text: str, icon: str = "", module_id: str = ""):
        super().__init__()
        self.module_id = module_id
        self._is_active = False
        self._is_hovered = False
        
        self.setText(f"  {icon}  {text}" if icon else text)
        self.setMinimumHeight(44)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        self._update_style()
    
    def set_active(self, active: bool):
        self._is_active = active
        self._update_style()
    
    def enterEvent(self, event):
        self._is_hovered = True
        if not self._is_active:
            self._update_style()
        super().enterEvent(event)
    
    def leaveEvent(self, event):
        self._is_hovered = False
        if not self._is_active:
            self._update_style()
        super().leaveEvent(event)
    
    def _update_style(self):
        if self._is_active:
            self.setStyleSheet("""
                QPushButton {
                background-color: #1e6bde;
                color: white;
                border: none;
                border-radius: 8px;
                text-align: left;
                padding-left: 16px;
                font-size: 14px;
                font-weight: 600;
                box-shadow: 0 2px 8px rgba(30, 107, 222, 0.4);
                text-shadow: 1px 1px 1px rgba(255, 255, 255, 0.3);
            }
            """)
        elif self._is_hovered:
            self.setStyleSheet("""
                QPushButton {
                    background-color: #2a2a2a;
                    color: #ffffff;
                    border: 1px solid #3a3a3a;
                    border-radius: 8px;
                    text-align: left;
                    padding-left: 16px;
                    font-size: 14px;
                    font-weight: 500;
                    text-shadow: 1px 1px 1px rgba(255, 255, 255, 0.3);
                }
            """)
        else:
            self.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    color: #ffffff;
                    border: 1px solid transparent;
                    border-radius: 8px;
                    text-align: left;
                    padding-left: 16px;
                    font-size: 14px;
                    font-weight: 400;
                    text-shadow: 1px 1px 1px rgba(255, 255, 255, 0.2);
                }
                QPushButton:hover {
                    background-color: #2a2a2a;
                    color: #ffffff;
                    border: 1px solid #3a3a3a;
                    text-shadow: 1px 1px 1px rgba(255, 255, 255, 0.3);
                }
            """)


class NavigationBar(QWidget):
    """左侧导航栏 - 剪映深色风格"""
    
    module_selected = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self._buttons: Dict[str, NavigationButton] = {}
        self._current_module: Optional[str] = None
        self._setup_ui()
    
    def _setup_ui(self):
        self.setFixedWidth(220)
        self.setStyleSheet("""
            QWidget {
                background-color: #2a2a2a;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 20, 16, 20)
        layout.setSpacing(12)
        
        logo_widget = QWidget()
        logo_layout = QVBoxLayout(logo_widget)
        logo_layout.setContentsMargins(0, 0, 0, 0)
        
        logo_label = QLabel("🎬 拾光剪影")
        logo_label.setStyleSheet("""
            QLabel {
                font-size: 18px;
                font-weight: bold;
                color: #ffffff;
                padding: 10px 0;
            }
        """)
        logo_layout.addWidget(logo_label)
        
        version_label = QLabel("v3.0 Qt6版")
        version_label.setStyleSheet("color: #ffffff; font-size: 12px; padding-left: 2px;")
        logo_layout.addWidget(version_label)
        
        layout.addWidget(logo_widget)
        
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet("background-color: #444444; max-height: 1px; margin: 16px 0;")
        layout.addWidget(separator)
        
        self._button_container = QWidget()
        self._button_layout = QVBoxLayout(self._button_container)
        self._button_layout.setContentsMargins(0, 0, 0, 0)
        self._button_layout.setSpacing(8)
        layout.addWidget(self._button_container)
        
        layout.addStretch()
    
    def add_module(self, module_id: str, name: str, icon: str = ""):
        button = NavigationButton(name, icon, module_id)
        button.clicked.connect(lambda: self._on_button_clicked(module_id))
        self._buttons[module_id] = button
        self._button_layout.addWidget(button)
    
    def _on_button_clicked(self, module_id: str):
        if self._current_module:
            self._buttons[self._current_module].set_active(False)
        
        self._current_module = module_id
        self._buttons[module_id].set_active(True)
        self.module_selected.emit(module_id)
    
    def select_module(self, module_id: str):
        if module_id in self._buttons:
            self._on_button_clicked(module_id)


class MainWindow(QMainWindow):
    """
    主窗口 - 剪映同款标签页布局
    
    结构：
    ├── 左侧导航栏（固定）
    │     ├── 首页
    │     ├── 剪辑
    │     ├── 文案生成
    │     ├── 多任务
    │     ├── 短剧筛选
    │     ├── 账号运营
    │     ├── 素材库
    │     ├── 插件中心
    │     └── 性能监控
    ├── 中央内容区（标签页切换）
    └── 底部状态栏（全局提示、监控）
    """
    
    def __init__(self):
        super().__init__()
        self._modules: Dict[str, ModuleInfo] = {}
        self._event_bus = EventBus.get_instance()
        
        self._lazy_loaded_modules: Dict[str, bool] = {}
        self._module_loading_queue: List[str] = []
        self._current_loading_module: Optional[str] = None
        self._preload_priority: Dict[str, int] = {
            'home': 1,
            'editor': 2,
            'copywriting': 3,
            'tasks': 4,
            'drama': 5,
            'account': 6,
            'materials': 7,
            'plugins': 8,
            'performance': 9,
            'models': 10,
            'settings': 11,
            'help': 12
        }
        
        self._auth_service = auth_service
        self._setup_ui()
        self._setup_default_modules()
        self._update_auth_status()
        
        self._setup_lazy_loading()
    
    def _setup_lazy_loading(self):
        """设置延迟加载"""
        self._preload_module("home")
        self._start_background_loading()
    
    def _preload_module(self, module_id: str):
        """预加载指定模块"""
        if module_id in self._lazy_loaded_modules:
            return
        
        try:
            if module_id in self._modules and self._modules[module_id].widget_class:
                self._lazy_loaded_modules[module_id] = True
                logger.info(f"模块 {module_id} 已预加载")
        except Exception as e:
            logger.warning(f"模块 {module_id} 预加载失败: {e}")
    
    def _start_background_loading(self):
        """启动后台加载"""
        QTimer.singleShot(100, self._load_next_module)
    
    def _load_next_module(self):
        """加载下一个模块"""
        if self._current_loading_module:
            return
        
        for module_id, priority in sorted(self._preload_priority.items(), key=lambda x: x[1]):
            if module_id not in self._lazy_loaded_modules and module_id not in self._module_loading_queue:
                self._module_loading_queue.append(module_id)
                self._current_loading_module = module_id
                self._load_module_async(module_id)
                break
    
    def _load_module_async(self, module_id: str):
        """异步加载模块"""
        try:
            if module_id in self._modules and self._modules[module_id].widget_class:
                QTimer.singleShot(50, lambda: self._on_module_selected(module_id))
                logger.info(f"异步加载模块: {module_id}")
        except Exception as e:
            logger.error(f"异步加载模块失败: {e}")
            self._current_loading_module = None
            if module_id in self._module_loading_queue:
                self._module_loading_queue.remove(module_id)
    
    def get_loading_status(self) -> Dict[str, Any]:
        """获取加载状态"""
        return {
            'loaded_modules': list(self._lazy_loaded_modules.keys()),
            'loading_queue': self._module_loading_queue.copy(),
            'current_loading': self._current_loading_module,
            'total_modules': len(self._modules),
            'loading_progress': len(self._lazy_loaded_modules) / len(self._modules) * 100
        }
    
    def preload_all_modules(self):
        """预加载所有模块"""
        for module_id in self._preload_priority.keys():
            self._preload_module(module_id)
    
    def clear_lazy_cache(self):
        """清理延迟加载缓存"""
        self._lazy_loaded_modules.clear()
        self._module_loading_queue.clear()
        self._current_loading_module = None
        logger.info("延迟加载缓存已清理")
    
    def _setup_ui(self):
        self.setWindowTitle("拾光剪影 v3.0 - Qt6版")
        self.setMinimumSize(1400, 900)
        self.resize(1600, 1000)
        
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1a1a1a;
            }
            QWidget {
                color: #ffffff;
            }
            QLabel {
                color: #ffffff;
            }
            QPushButton {
                color: #ffffff;
            }
            QScrollBar:vertical {
                background-color: #2a2a2a;
                width: 8px;
                margin: 0;
            }
            QScrollBar::handle:vertical {
                background-color: #4a4a4a;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #5a5a5a;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
            QScrollBar:horizontal {
                background-color: #2a2a2a;
                height: 8px;
                margin: 0;
            }
            QScrollBar::handle:horizontal {
                background-color: #4a4a4a;
                border-radius: 4px;
            }
            QScrollBar::handle:horizontal:hover {
                background-color: #5a5a5a;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0;
            }
            QTabWidget::pane {
                border: none;
                background-color: #1a1a1a;
            }
            QTabBar::tab {
                background-color: #2a2a2a;
                color: #ffffff;
                padding: 10px 20px;
                margin-right: 2px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                font-size: 13px;
            }
            QTabBar::tab:selected {
                background-color: #3a3a3a;
                color: #ffffff;
            }
            QTabBar::tab:hover:!selected {
                background-color: #303030;
                color: #ffffff;
            }
        """)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        nav_content_layout = QHBoxLayout()
        nav_content_layout.setContentsMargins(0, 0, 0, 0)
        nav_content_layout.setSpacing(0)
        
        self._nav_bar = NavigationBar()
        self._nav_bar.module_selected.connect(self._on_module_selected)
        nav_content_layout.addWidget(self._nav_bar)
        
        content_widget = QWidget()
        content_widget.setStyleSheet("background-color: #1a1a1a;")
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        
        # 顶部状态栏 - 显示授权状态
        self._top_status_bar = QWidget()
        self._top_status_bar.setFixedHeight(40)
        self._top_status_bar.setStyleSheet("background-color: #2a2a2a;")
        top_layout = QHBoxLayout(self._top_status_bar)
        top_layout.setContentsMargins(16, 0, 16, 0)
        top_layout.setSpacing(12)
        
        # 左侧状态信息
        self._status_label = QLabel("未登录 / 未授权")
        self._status_label.setStyleSheet("color: #f59e0b; font-size: 13px; font-weight: 500;")
        top_layout.addWidget(self._status_label)
        
        top_layout.addStretch()
        
        # 右侧操作按钮

        self._login_btn = QPushButton("登录")
        self._login_btn.setFixedHeight(28)
        self._login_btn.setFixedWidth(80)
        self._login_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e6bde;
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #2575f0;
            }
        """)
        self._login_btn.clicked.connect(self._on_login_clicked)
        top_layout.addWidget(self._login_btn)

        self._activate_btn = QPushButton("激活")
        self._activate_btn.setFixedHeight(28)
        self._activate_btn.setFixedWidth(80)
        self._activate_btn.setStyleSheet("""
            QPushButton {
                background-color: #1a1a1a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 4px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #252525;
            }
        """)
        self._activate_btn.clicked.connect(self._on_activate_clicked)
        top_layout.addWidget(self._activate_btn)
        
        content_layout.addWidget(self._top_status_bar)
        
        self._tab_widget = QTabWidget()
        self._tab_widget.setDocumentMode(True)
        self._tab_widget.setTabsClosable(False)
        self._tab_widget.setMovable(True)
        self._tab_widget.tabBar().hide()
        self._tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: none;
                background-color: #0d0d0d;
            }
            QTabBar::tab {
                background-color: #1a1a1a;
                color: #ffffff;
                padding: 10px 20px;
                margin-right: 2px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                font-size: 13px;
            }
            QTabBar::tab:selected {
                background-color: #2a2a2a;
                color: #ffffff;
            }
            QTabBar::tab:hover:!selected {
                background-color: #252525;
                color: #ffffff;
            }
        """)
        content_layout.addWidget(self._tab_widget)
        
        nav_content_layout.addWidget(content_widget, 1)
        
        main_layout.addLayout(nav_content_layout, 1)
        
        self._setup_event_handlers()
    
    def _setup_event_handlers(self):
        self._event_bus.on(EventType.MODULE_ACTIVATED, self._on_module_activated)
    
    def _setup_default_modules(self):
        # 导入模块类
        from .modules import (
            HomeModule, EditorModule, CopywritingModule,
            TasksModule, DramaFinderModule, AccountOpsModule,
            MaterialsModule, PluginsModule, PerformanceModule
        )
        from .model_management import ModelManagementModule
        from .settings_module import SettingsModule, HelpModule
        
        default_modules = [
            ("home", "首页", "🏠", "首页概览", HomeModule),
            ("editor", "剪辑", "🎬", "视频剪辑", EditorModule),
            ("copywriting", "文案生成", "✍️", "AI文案生成", CopywritingModule),
            ("tasks", "多任务", "📋", "任务管理", TasksModule),
            ("drama", "短剧筛选", "🎭", "短剧筛选", DramaFinderModule),
            ("account", "账号运营", "👤", "账号运营", AccountOpsModule),
            ("materials", "素材库", "📁", "素材管理", MaterialsModule),
            ("plugins", "插件中心", "🧩", "插件管理", PluginsModule),
            ("performance", "性能监控", "📊", "性能监控", PerformanceModule),
            ("models", "模型管理", "🤖", "模型管理", ModelManagementModule),
            ("settings", "设置", "⚙️", "应用设置", SettingsModule),
            ("help", "帮助", "❓", "使用帮助", HelpModule),
        ]
        
        for module_id, name, icon, desc, widget_class in default_modules:
            self.register_module(module_id, name, icon, desc, widget_class)
        
        self._nav_bar.select_module("home")
    
    def register_module(self, module_id: str, name: str, icon: str, description: str,
                       widget_class: Type[QWidget] = None):
        """注册模块"""
        info = ModuleInfo(
            id=module_id,
            name=name,
            icon=icon,
            description=description,
            widget_class=widget_class
        )
        self._modules[module_id] = info
        self._nav_bar.add_module(module_id, name, icon)
    
    def set_module_widget(self, module_id: str, widget: QWidget):
        """设置模块界面"""
        if module_id not in self._modules:
            return
        
        info = self._modules[module_id]
        
        if info.instance:
            for i in range(self._tab_widget.count()):
                if self._tab_widget.tabText(i) == f"{info.icon} {info.name}":
                    self._tab_widget.removeTab(i)
                    break
        
        info.instance = widget
        self._tab_widget.addTab(widget, f"{info.icon} {info.name}")
    
    def get_module_widget(self, module_id: str) -> Optional[QWidget]:
        """获取模块界面"""
        if module_id in self._modules:
            return self._modules[module_id].instance
        return None
    
    def _on_module_selected(self, module_id: str):
        """模块选中事件"""
        if module_id not in self._modules:
            return
        
        info = self._modules[module_id]
        
        if not info.instance and info.widget_class:
            widget = info.widget_class()
            
            # 如果是设置模块，连接settings_changed信号
            if module_id == "settings":
                widget.settings_changed.connect(self._on_settings_changed)
            
            self.set_module_widget(module_id, widget)
        
        if info.instance:
            for i in range(self._tab_widget.count()):
                if self._tab_widget.tabText(i) == f"{info.icon} {info.name}":
                    self._tab_widget.setCurrentIndex(i)
                    break
        
        info.state = ModuleState.ACTIVE
        self._event_bus.emit(
            EventType.MODULE_ACTIVATED,
            {"module_id": module_id, "module_name": info.name}
        )
    
    def _on_settings_changed(self, setting_type, settings):
        """设置更改事件处理"""
        if "theme" in settings:
            self._apply_theme(settings["theme"])
    
    def _apply_theme(self, theme):
        """应用主题"""
        if theme == "light":
            self._apply_light_theme()
        else:
            self._apply_dark_theme()
    
    def _apply_dark_theme(self):
        """应用深色主题"""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1a1a1a;
            }
            QWidget {
                color: #ffffff;
            }
            QLabel {
                color: #ffffff;
            }
            QPushButton {
                color: #ffffff;
            }
            QScrollBar:vertical {
                background-color: #2a2a2a;
                width: 8px;
                margin: 0;
            }
            QScrollBar::handle:vertical {
                background-color: #4a4a4a;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #5a5a5a;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
            QScrollBar:horizontal {
                background-color: #2a2a2a;
                height: 8px;
                margin: 0;
            }
            QScrollBar::handle:horizontal {
                background-color: #4a4a4a;
                border-radius: 4px;
            }
            QScrollBar::handle:horizontal:hover {
                background-color: #5a5a5a;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0;
            }
            QTabWidget::pane {
                border: none;
                background-color: #1a1a1a;
            }
            QTabBar::tab {
                background-color: #2a2a2a;
                color: #ffffff;
                padding: 10px 20px;
                margin-right: 2px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                font-size: 13px;
            }
            QTabBar::tab:selected {
                background-color: #3a3a3a;
                color: #ffffff;
            }
            QTabBar::tab:hover:!selected {
                background-color: #303030;
                color: #ffffff;
            }
        """)
        
        # 更新导航栏样式
        if hasattr(self, "_nav_bar"):
            self._nav_bar.setStyleSheet("""
                QWidget {
                    background-color: #2a2a2a;
                }
            """)
        
        # 更新内容区域样式
        if hasattr(self, "_tab_widget"):
            self._tab_widget.setStyleSheet("""
                QTabWidget::pane {
                    border: none;
                    background-color: #0d0d0d;
                }
                QTabBar::tab {
                    background-color: #1a1a1a;
                    color: #ffffff;
                    padding: 10px 20px;
                    margin-right: 2px;
                    border-top-left-radius: 6px;
                    border-top-right-radius: 6px;
                    font-size: 13px;
                }
                QTabBar::tab:selected {
                    background-color: #2a2a2a;
                    color: #ffffff;
                }
                QTabBar::tab:hover:!selected {
                    background-color: #252525;
                    color: #ffffff;
                }
            """)
    
    def _apply_light_theme(self):
        """应用浅色主题"""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f5f5f5;
            }
            QWidget {
                color: #333333;
            }
            QLabel {
                color: #333333;
            }
            QPushButton {
                color: #333333;
            }
            QScrollBar:vertical {
                background-color: #e0e0e0;
                width: 8px;
                margin: 0;
            }
            QScrollBar::handle:vertical {
                background-color: #bdbdbd;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #9e9e9e;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
            QScrollBar:horizontal {
                background-color: #e0e0e0;
                height: 8px;
                margin: 0;
            }
            QScrollBar::handle:horizontal {
                background-color: #bdbdbd;
                border-radius: 4px;
            }
            QScrollBar::handle:horizontal:hover {
                background-color: #9e9e9e;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0;
            }
            QTabWidget::pane {
                border: none;
                background-color: #ffffff;
            }
            QTabBar::tab {
                background-color: #e0e0e0;
                color: #333333;
                padding: 10px 20px;
                margin-right: 2px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                font-size: 13px;
            }
            QTabBar::tab:selected {
                background-color: #ffffff;
                color: #333333;
                border: 1px solid #e0e0e0;
                border-bottom: none;
            }
            QTabBar::tab:hover:!selected {
                background-color: #f0f0f0;
                color: #333333;
            }
        """)
        
        # 更新导航栏样式
        if hasattr(self, "_nav_bar"):
            self._nav_bar.setStyleSheet("""
                QWidget {
                    background-color: #ffffff;
                }
            """)
        
        # 更新内容区域样式
        if hasattr(self, "_tab_widget"):
            self._tab_widget.setStyleSheet("""
                QTabWidget::pane {
                    border: none;
                    background-color: #ffffff;
                }
                QTabBar::tab {
                    background-color: #e0e0e0;
                    color: #333333;
                    padding: 10px 20px;
                    margin-right: 2px;
                    border-top-left-radius: 6px;
                    border-top-right-radius: 6px;
                    font-size: 13px;
                }
                QTabBar::tab:selected {
                    background-color: #ffffff;
                    color: #333333;
                    border: 1px solid #e0e0e0;
                    border-bottom: none;
                }
                QTabBar::tab:hover:!selected {
                    background-color: #f0f0f0;
                    color: #333333;
                }
            """)
    
    def _on_module_activated(self, event):
        """模块激活事件处理"""
        target = event.data.get("target")
        if target:
            self._nav_bar.select_module(target)
    
    def switch_to_module(self, module_id: str):
        """切换到指定模块"""
        self._nav_bar.select_module(module_id)
    
    def show_status(self, message: str, color: str = "#808080"):
        """显示状态消息"""
        pass
    
    def _show_help(self):
        """显示帮助信息"""
        from .settings_module import HelpModule
        if "help" in self._modules and not self._modules["help"].instance:
            self.set_module_widget("help", HelpModule())
        self.switch_to_module("help")
    
    def _show_settings(self):
        """显示设置界面"""
        from .settings_module import SettingsModule
        if "settings" in self._modules and not self._modules["settings"].instance:
            self.set_module_widget("settings", SettingsModule())
        self.switch_to_module("settings")
    
    def _on_login_clicked(self):
        """登录按钮点击事件"""
        from .login_window import LoginWindow
        login_window = LoginWindow()
        
        login_success = [False]
        
        def on_login_success():
            login_success[0] = True
            login_window.close()
        
        login_window.login_success.connect(on_login_success)
        login_window.show()
        
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        while login_window.isVisible():
            app.processEvents()
        
        if login_success[0]:
            self._update_auth_status()
    
    def _on_activate_clicked(self):
        """激活按钮点击事件"""
        from .login_window import ActivationWindow
        activation_window = ActivationWindow()
        activation_window.show()
        
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        while activation_window.isVisible():
            app.processEvents()
        
        self._update_auth_status()
    
    def _update_auth_status(self):
        """更新授权状态"""
        if self._auth_service.is_logged_in:
            user = self._auth_service.current_user
            if user and user.is_vip:
                expire_date = user.vip_expire
                if expire_date > 0:
                    from datetime import datetime
                    expire_str = datetime.fromtimestamp(expire_date).strftime("%Y-%m-%d")
                    self._status_label.setText(f"已登录 - VIP 到期: {expire_str}")
                    self._status_label.setStyleSheet("color: #4caf50; font-size: 13px; font-weight: 500;")
                else:
                    self._status_label.setText("已登录 - VIP")
                    self._status_label.setStyleSheet("color: #4caf50; font-size: 13px; font-weight: 600;")
            else:
                self._status_label.setText(f"已登录 - {user.nickname}")
                self._status_label.setStyleSheet("color: #4caf50; font-size: 13px; font-weight: 500;")
        else:
            self._status_label.setText("未登录 / 未授权")
            self._status_label.setStyleSheet("color: #f59e0b; font-size: 13px; font-weight: 500;")
    
    def closeEvent(self, event):
        """关闭事件"""
        logger.info("用户关闭主窗口")
        logger.info("保存项目状态...")
        self._event_bus.emit(EventType.PROJECT_SAVED, {})
        logger.info("清理资源...")
        
        for module_name, module_info in self._modules.items():
            if module_info.instance:
                try:
                    if hasattr(module_info.instance, 'cleanup'):
                        module_info.instance.cleanup()
                    logger.debug(f"模块 {module_name} 已清理")
                except Exception as e:
                    logger.warning(f"清理模块 {module_name} 失败: {e}")
        
        logger.info("应用关闭完成")
        event.accept()

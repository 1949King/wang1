"""
Qt6 主窗口 - 剪映同款标签页布局
==============================
专业级架构：左侧导航 + 标签页切换 + 底部状态栏
"""

from typing import Dict, List, Optional, Type, Any
from dataclasses import dataclass
from enum import Enum
import logging

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QLabel, QPushButton, QFrame,
    QStatusBar, QSizePolicy, QScrollArea, QSpacerItem,
    QTabWidget, QSplitter, QToolBar, QApplication
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QTimer, QSettings
from PyQt6.QtGui import QIcon, QFont, QColor, QAction

from .core import EventBus, EventType, MasterClock, DataBus
from .auth import auth_service  # 修复 P0-A: 移除 main_window.py 内的伪 User/AuthService,统一从 auth 模块导入
from .module_registry import get_registry, ModuleTier  # 模块注册表：分级 + 开关
from .theme_manager import ThemeManager  # 全局主题管理器
from app.version import __version__

logger = logging.getLogger("AI短剧编辑器.main_window")


class ModuleState(Enum):
    NOT_LOADED = "not_loaded"
    LOADING = "loading"
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
        self._theme = "dark"  # 默认深色主题
        
        self.setText(f"  {icon}  {text}" if icon else text)
        self.setMinimumHeight(44)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        self._update_style()
    
    def set_theme(self, theme: str):
        """设置主题"""
        self._theme = theme
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
        palette = {
            "light": {
                "text": "#172033",
                "muted": "#56657a",
                "surface": "#fcfdff",
                "hover": "#dde7f4",
                "active": "#2563eb",
                "active_hover": "#1d4ed8",
                "active_text": "#f8fbff",
                "border": "#d7e0ec",
            },
            "dark": {
                "text": "#edf3ff",
                "muted": "#aab6cc",
                "surface": "#101621",
                "hover": "#1f2b42",
                "active": "#2f7bff",
                "active_hover": "#4d8dff",
                "active_text": "#f8fbff",
                "border": "#253044",
            },
        }["light" if self._theme == "light" else "dark"]

        # 侧栏是高频入口，选中、悬停、默认态必须一眼可分辨。
        if self._theme == "light":
            if self._is_active:
                self.setStyleSheet("""
                    QPushButton {
                        background-color: %(active)s;
                        color: %(active_text)s;
                        border: 1px solid %(active)s;
                        border-radius: 10px;
                        text-align: left;
                        padding-left: 16px;
                        font-size: 14px;
                        font-weight: 700;
                    }
                    QPushButton:hover {
                        background-color: %(active_hover)s;
                    }
                """ % palette)
            elif self._is_hovered:
                self.setStyleSheet("""
                    QPushButton {
                        background-color: %(hover)s;
                        color: %(text)s;
                        border: 1px solid %(border)s;
                        border-radius: 10px;
                        text-align: left;
                        padding-left: 16px;
                        font-size: 14px;
                        font-weight: 500;
                    }
                """ % palette)
            else:
                self.setStyleSheet("""
                    QPushButton {
                        background-color: transparent;
                        color: %(muted)s;
                        border: 1px solid transparent;
                        border-radius: 10px;
                        text-align: left;
                        padding-left: 16px;
                        font-size: 14px;
                        font-weight: 400;
                    }
                    QPushButton:hover {
                        background-color: %(hover)s;
                        color: %(text)s;
                        border: 1px solid %(border)s;
                    }
                """ % palette)
        else:  # 深色主题
            if self._is_active:
                self.setStyleSheet("""
                    QPushButton {
                        background-color: %(active)s;
                        color: %(active_text)s;
                        border: 1px solid %(active)s;
                        border-radius: 10px;
                        text-align: left;
                        padding-left: 16px;
                        font-size: 14px;
                        font-weight: 700;
                    }
                    QPushButton:hover {
                        background-color: %(active_hover)s;
                    }
                """ % palette)
            elif self._is_hovered:
                self.setStyleSheet("""
                    QPushButton {
                        background-color: %(hover)s;
                        color: %(text)s;
                        border: 1px solid %(border)s;
                        border-radius: 10px;
                        text-align: left;
                        padding-left: 16px;
                        font-size: 14px;
                        font-weight: 500;
                    }
                """ % palette)
            else:
                self.setStyleSheet("""
                    QPushButton {
                        background-color: transparent;
                        color: %(muted)s;
                        border: 1px solid transparent;
                        border-radius: 10px;
                        text-align: left;
                        padding-left: 16px;
                        font-size: 14px;
                        font-weight: 400;
                    }
                    QPushButton:hover {
                        background-color: %(hover)s;
                        color: %(text)s;
                        border: 1px solid %(border)s;
                    }
                """ % palette)


class NavigationBar(QWidget):
    """左侧导航栏 - 剪映深色风格"""
    
    module_selected = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self._buttons: Dict[str, NavigationButton] = {}
        self._current_module: Optional[str] = None
        self._theme = "dark"
        self._setup_ui()
    
    def set_theme(self, theme: str):
        """设置导航栏主题 - 通过theme属性让全局QSS自动响应"""
        # 更新所有导航按钮的主题
        self._theme = "light" if theme == "light" else "dark"
        for button in self._buttons.values():
            button.set_theme(self._theme)
        
        # 设置theme属性，让全局QSS属性选择器自动响应
        self.setProperty("theme", self._theme)
        for child in self.findChildren(QWidget):
            child.setProperty("theme", self._theme)
        
        # 更新logo标签颜色（内联样式，不受全局QSS影响）
        if theme == "light":
            self._logo_label.setStyleSheet("""
                QLabel {
                    font-size: 18px;
                    font-weight: 800;
                    color: #2563eb;
                    padding: 10px 0;
                }
            """)
            # 更新版本标签颜色
            self._version_label.setStyleSheet("color: #56657a; font-size: 12px; padding-left: 2px;")
            # 更新分隔线颜色
            self._separator.setStyleSheet("background-color: #e3eaf3; max-height: 1px; margin: 16px 0;")
        else:
            self._logo_label.setStyleSheet("""
                QLabel {
                    font-size: 18px;
                    font-weight: 800;
                    color: #edf3ff;
                    padding: 10px 0;
                }
            """)
            # 更新版本标签颜色
            self._version_label.setStyleSheet("color: #aab6cc; font-size: 12px; padding-left: 2px;")
            # 更新分隔线颜色
            self._separator.setStyleSheet("background-color: #1c2638; max-height: 1px; margin: 16px 0;")
    
    def _setup_ui(self):
        self.setFixedWidth(220)
        self.setObjectName("sideBar")
        # 不设置硬编码背景样式，由全局QSS根据theme属性自动应用
        self.setProperty("theme", self._theme)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 20, 16, 20)
        layout.setSpacing(12)
        
        logo_widget = QWidget()
        logo_layout = QVBoxLayout(logo_widget)
        logo_layout.setContentsMargins(0, 0, 0, 0)
        
        self._logo_label = QLabel("🎬 拾光剪影")
        self._logo_label.setStyleSheet("""
            QLabel {
                font-size: 18px;
                font-weight: 800;
                color: #edf3ff;
                padding: 10px 0;
            }
        """)
        logo_layout.addWidget(self._logo_label)
        
        self._version_label = QLabel(f"v{__version__} Qt6版")
        self._version_label.setStyleSheet("color: #aab6cc; font-size: 12px; padding-left: 2px;")
        logo_layout.addWidget(self._version_label)
        
        layout.addWidget(logo_widget)
        
        self._separator = QFrame()
        self._separator.setFrameShape(QFrame.Shape.HLine)
        self._separator.setStyleSheet("background-color: #1c2638; max-height: 1px; margin: 16px 0;")
        layout.addWidget(self._separator)
        
        self._button_container = QWidget()
        self._button_layout = QVBoxLayout(self._button_container)
        self._button_layout.setContentsMargins(0, 0, 0, 0)
        self._button_layout.setSpacing(8)
        layout.addWidget(self._button_container)
        
        layout.addStretch()
    
    def add_module(self, module_id: str, name: str, icon: str = ""):
        """添加导航按钮（已存在则不重复添加）"""
        if module_id in self._buttons:
            return
        button = NavigationButton(name, icon, module_id)
        button.set_theme(self._theme)
        button.clicked.connect(lambda: self._on_button_clicked(module_id))
        self._buttons[module_id] = button
        self._button_layout.addWidget(button)

    def remove_module(self, module_id: str):
        """移除导航按钮（运行时开关关闭时调用）"""
        if module_id not in self._buttons:
            return
        btn = self._buttons.pop(module_id)
        btn.setParent(None)
        btn.deleteLater()
        # 如果移除的是当前选中项，则切回 home
        if self._current_module == module_id:
            self._current_module = None
            if "home" in self._buttons:
                self._on_button_clicked("home")

    def has_module(self, module_id: str) -> bool:
        return module_id in self._buttons

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
        self._pending_module_actions: Dict[str, dict] = {}
        self._preload_priority: Dict[str, int] = {
            'home': 1,
            'editor': 2,
            'copywriting': 3,
            'tasks': 4,
            'characters': 5,
            'account': 6,
            'materials': 7,
            'plugins': 8,
            'performance': 9,
            'models': 10,
            'settings': 11,
            'help': 12
        }
        
        self._auth_service = auth_service
        self._settings = QSettings("拾光剪影", "Settings")
        self._setup_ui()
        self._setup_default_modules()
        self._update_auth_status()

        # 修复：窗口几何保存钩子刻意不放进 closeEvent（该方法属于 exit-media
        # 冻结区，未解冻不能碰），改用 QApplication.aboutToQuit 信号，
        # 效果等价（真正退出前触发一次）但不触碰冻结符号。
        try:
            app = QApplication.instance()
            if app is not None:
                app.aboutToQuit.connect(self._save_window_geometry)
        except Exception as e:
            logger.debug(f"绑定窗口几何保存钩子失败: {e}")
        
        self._apply_initial_theme()
        self._setup_lazy_loading()
    
    def _apply_initial_theme(self):
        """应用初始主题（通过 ThemeManager 统一管理）"""
        tm = ThemeManager.instance()
        saved_theme = self._settings.value("theme")
        if saved_theme:
            tm.apply_theme(saved_theme, main_window=self)
        else:
            # 根据时间自动切换
            from datetime import datetime
            hour = datetime.now().hour
            tm.apply_theme("light" if 6 <= hour < 18 else "dark", main_window=self)
    
    def _apply_time_based_theme(self):
        """根据时间自动应用主题（兼容旧调用）"""
        from datetime import datetime
        hour = datetime.now().hour
        ThemeManager.instance().apply_theme(
            "light" if 6 <= hour < 18 else "dark", main_window=self
        )
    
    def _setup_lazy_loading(self):
        """延迟加载：仅标记首页；禁止后台 _on_module_selected（会抢激活并卡主线程）。"""
        self._preload_module("home")
    
    def _preload_module(self, module_id: str):
        """预加载指定模块（仅标记，不实例化、不切换）。"""
        if module_id in self._lazy_loaded_modules:
            return
        
        try:
            if module_id in self._modules and self._modules[module_id].widget_class:
                self._lazy_loaded_modules[module_id] = True
                logger.info(f"模块 {module_id} 已预加载")
        except Exception as e:
            logger.warning(f"模块 {module_id} 预加载失败: {e}")
    
    def _start_background_loading(self):
        """兼容旧调用：已禁用后台抢激活加载。"""
        return
    
    def _load_next_module(self):
        """兼容旧调用：已禁用。"""
        return
    
    def _load_module_async(self, module_id: str):
        """兼容旧调用：已禁用（勿再走 _on_module_selected）。"""
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
        self.setWindowTitle(f"拾光剪影 v{__version__} - AI短剧编辑器")
        self.setMinimumSize(1400, 900)
        self.resize(1600, 1000)
        self._restore_window_geometry()
        
        central_widget = QWidget()
        central_widget.setObjectName("contentContainer")
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
        content_widget.setObjectName("moduleContainer")
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        
        # 顶部状态栏 - 显示授权状态
        self._top_status_bar = QFrame()
        self._top_status_bar.setObjectName("headerBar")
        self._top_status_bar.setFixedHeight(40)
        top_layout = QHBoxLayout(self._top_status_bar)
        top_layout.setContentsMargins(16, 0, 16, 0)
        top_layout.setSpacing(12)
        
        # 左侧状态信息
        self._status_label = QLabel("未登录 / 未授权")
        self._status_label.setStyleSheet("color: #fbbf24; font-size: 13px; font-weight: 600;")
        top_layout.addWidget(self._status_label)
        
        top_layout.addStretch()
        
        # 右侧操作按钮

        self._login_btn = QPushButton("登录")
        self._login_btn.setObjectName("primaryBtn")
        self._login_btn.setFixedHeight(28)
        self._login_btn.setFixedWidth(80)
        self._login_btn.clicked.connect(self._on_login_clicked)
        top_layout.addWidget(self._login_btn)

        self._activate_btn = QPushButton("激活")
        self._activate_btn.setFixedHeight(28)
        self._activate_btn.setFixedWidth(80)
        self._activate_btn.clicked.connect(self._on_activate_clicked)
        top_layout.addWidget(self._activate_btn)
        
        content_layout.addWidget(self._top_status_bar)
        
        self._tab_widget = QTabWidget()
        self._tab_widget.setDocumentMode(True)
        self._tab_widget.setTabsClosable(False)
        self._tab_widget.setMovable(True)
        self._tab_widget.tabBar().hide()
        content_layout.addWidget(self._tab_widget)
        
        nav_content_layout.addWidget(content_widget, 1)
        
        main_layout.addLayout(nav_content_layout, 1)
        
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        
        self._setup_event_handlers()
    
    def _setup_event_handlers(self):
        self._event_bus.on(EventType.MODULE_ACTIVATED, self._on_module_activated)
        # 功能开关变更：动态刷新导航栏
        self._event_bus.on(EventType.MODULE_CONFIG_CHANGED,
                           lambda _evt: self.apply_module_changes())
        # 主题切换：同步更新全局UI
        self._event_bus.on(EventType.THEME_CHANGED, self._on_theme_changed)
    
    def _setup_default_modules(self):
        """从模块注册表读取并注册已启用的模块（核心 + 开启的高级/实验）"""
        registry = get_registry()

        enabled = registry.enabled_modules()
        logger.info(
            "注册表启动：共 %d 个模块定义，当前启用 %d 个，关闭 %d 个",
            len(registry.all_modules()),
            len(enabled),
            len(registry.disabled_modules()),
        )

        for mod in enabled:
            module_id = mod["id"]
            name = mod["name"]
            icon = mod.get("icon", "")
            desc = mod.get("description", "")
            widget_class = self._lazy_import_widget_class(mod)
            if widget_class is None:
                # 可选模块（如 character_management_module）导入失败则静默跳过
                continue
            self.register_module(module_id, name, icon, desc, widget_class)

        # 预加载优先级按注册表顺序自动生成
        for idx, mod in enumerate(enabled):
            self._preload_priority[mod["id"]] = idx + 1

        self._nav_bar.select_module("home")

    def _lazy_import_widget_class(self, mod_def: dict):
        """
        延迟导入：按需 import 模块类，避免启动时一次性加载所有 UI 代码。
        对 optional=True 的模块，导入失败时静默跳过。
        """
        import_module = mod_def.get("import_module")
        import_class = mod_def.get("import_class")
        is_optional = mod_def.get("optional", False)

        if not import_module or not import_class:
            return None

        try:
            # 相对导入：from .xxx import YYY
            package = "app.modules.lego" if import_module.startswith(".") else None
            # 使用 importlib 做相对导入
            import importlib
            if package and import_module.startswith("."):
                module = importlib.import_module(import_module, package=package)
            else:
                module = importlib.import_module(import_module)
            widget_class = getattr(module, import_class, None)
            return widget_class
        except Exception as e:
            if not is_optional:
                logger.warning("模块 %s (%s) 导入失败: %s", mod_def.get("id"), import_class, e)
            return None

    def apply_module_changes(self):
        """
        运行时刷新导航栏：根据注册表最新开关状态动态增删导航按钮。
        由设置面板的「功能开关」保存后调用。
        使用 QTimer 延迟到下一个事件循环，避免阻塞UI
        """
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, self._apply_module_changes_impl)

    def _apply_module_changes_impl(self):
        """实际执行模块变更（延迟到下一个事件循环）"""
        registry = get_registry()
        current_enabled = {m["id"] for m in registry.enabled_modules()}

        # 1) 新增：注册表中已启用但导航栏尚未显示
        for mod in registry.enabled_modules():
            mid = mod["id"]
            if not self._nav_bar.has_module(mid):
                # 懒加载 widget_class（不立即实例化）
                self.register_module_lazy(
                    mid, mod["name"], mod.get("icon", ""),
                    mod.get("description", ""), mod
                )
                logger.info("运行时启用模块: %s", mid)

        # 2) 移除：导航栏中显示但注册表已关闭
        for mid in list(self._modules.keys()):
            info = self._modules[mid]
            if mid not in current_enabled:
                # 从导航栏移除按钮
                self._nav_bar.remove_module(mid)
                # 从标签页移除实例
                if info.instance is not None:
                    for i in range(self._tab_widget.count()):
                        if self._tab_widget.tabText(i) == f"{info.icon} {info.name}":
                            self._tab_widget.removeTab(i)
                            break
                    info.instance.deleteLater()
                    info.instance = None
                info.state = ModuleState.INACTIVE
                logger.info("运行时关闭模块: %s", mid)

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

    def register_module_lazy(self, module_id: str, name: str, icon: str, description: str,
                            mod_def: dict):
        """懒加载注册模块（不立即导入widget_class，避免阻塞UI）"""
        # 存储模块定义，但不立即导入 widget_class
        info = ModuleInfo(
            id=module_id,
            name=name,
            icon=icon,
            description=description,
            widget_class=None  # 延迟到首次激活时导入
        )
        info._mod_def = mod_def  # 保存模块定义用于延迟加载
        self._modules[module_id] = info
        self._nav_bar.add_module(module_id, name, icon)
    
    def _get_widget_class_lazy(self, module_id: str):
        """延迟获取 widget_class"""
        info = self._modules.get(module_id)
        if not info or info.widget_class:
            return info.widget_class if info else None

        mod_def = getattr(info, '_mod_def', None)
        if not mod_def:
            return None

        widget_class = self._lazy_import_widget_class(mod_def)
        if widget_class:
            info.widget_class = widget_class
        return widget_class

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
        current_theme = ThemeManager.instance().current_theme
        widget.setProperty("theme", current_theme)
        for child in widget.findChildren(QWidget):
            child.setProperty("theme", current_theme)
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

        if info.instance:
            self._activate_module(module_id, info)
            return

        if info.widget_class and info.state == ModuleState.INACTIVE:
            info.state = ModuleState.LOADING
            self._show_loading_indicator(module_id)
            self._load_module_with_progress(module_id)

    def _show_loading_indicator(self, module_id: str):
        """显示加载指示器"""
        info = self._modules.get(module_id)
        if not info:
            return

        loading_widget = QWidget()
        loading_layout = QVBoxLayout(loading_widget)
        loading_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        spinner = QLabel("⏳")
        spinner.setStyleSheet("font-size: 48px;")
        loading_layout.addWidget(spinner)

        loading_label = QLabel(f"正在加载 {info.name}...")
        loading_label.setStyleSheet("color: #ffffff; font-size: 16px;")
        loading_layout.addWidget(loading_label)

        self.set_module_widget(module_id, loading_widget)

    def _load_module_with_progress(self, module_id: str):
        """带进度的模块加载"""
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(50, lambda: self._perform_module_load(module_id))

    def _perform_module_load(self, module_id: str):
        """执行模块加载（在主线程中）"""
        info = self._modules.get(module_id)
        if not info:
            return

        # 如果是懒加载注册的模块，先获取 widget_class
        if not info.widget_class:
            widget_class = self._get_widget_class_lazy(module_id)
            if not widget_class:
                self._show_module_error(module_id, "无法加载模块类")
                return

        try:
            widget = info.widget_class()

            if module_id == "settings":
                widget.settings_changed.connect(self._on_settings_changed)

            info.state = ModuleState.LOADED
            info.instance = widget
            self.set_module_widget(module_id, widget)
            self._activate_module(module_id, info)
        except Exception as e:
            import traceback
            logger.error(f"模块 {module_id} 加载失败: {e}")
            traceback.print_exc()
            self._show_module_error(module_id, str(e))

    def _show_module_error(self, module_id: str, error_msg: str):
        """显示模块加载错误"""
        info = self._modules.get(module_id)
        if not info:
            return

        info.state = ModuleState.ERROR
        error_widget = QWidget()
        error_layout = QVBoxLayout(error_widget)
        error_label = QLabel(f"模块 {info.name} 加载失败\n错误信息: {error_msg}")
        error_label.setStyleSheet("color: #ff4757; padding: 20px;")
        error_layout.addWidget(error_label)
        self.set_module_widget(module_id, error_widget)

    def _activate_module(self, module_id: str, info):
        """激活并显示模块"""
        if info.instance:
            for i in range(self._tab_widget.count()):
                if self._tab_widget.tabText(i) == f"{info.icon} {info.name}":
                    self._tab_widget.setCurrentIndex(i)
                    break
        
        if info.state != ModuleState.ERROR:
            info.state = ModuleState.ACTIVE
            self._event_bus.emit(
                EventType.MODULE_ACTIVATED,
                {"module_id": module_id, "module_name": info.name}
            )
            self._flush_pending_module_action(module_id)
    
    def _on_settings_changed(self, setting_type, settings):
        """设置更改事件处理"""
        if "theme" in settings:
            theme = settings["theme"]
            self._apply_theme(theme)
            # 持久化主题设置
            self._settings.setValue("theme", theme)
        
        if "font_size" in settings or "font_family" in settings:
            self._apply_font_settings(settings)
    
    def _on_theme_changed(self, event):
        """响应设置模块的主题切换事件，同步全局UI（通过 ThemeManager 统一处理）"""
        theme = event.data.get("theme", "dark")
        self._apply_theme(theme)

    def _apply_theme(self, theme):
        """
        应用主题 - 通过 ThemeManager 统一管理

        历史问题修复：
        1. 卡死 → ThemeManager 内置 _applying 防递归标志位，避免 EventBus 往复触发死循环
        2. 未生效 → 通过 QApplication.setStyleSheet() 全局应用 QSS，
                    主窗口 setProperty("theme", ...) 让所有子控件自动级联响应
        3. 性能 → 不再使用 findChildren + unpolish/polish 暴力遍历
        """
        tm = ThemeManager.instance()
        tm.apply_theme(theme, main_window=self)
        actual_theme = tm.current_theme

        # 更新导航栏主题（保留模块自身的导航栏样式逻辑）
        if hasattr(self, "_nav_bar"):
            try:
                self._nav_bar.set_theme(actual_theme)
            except Exception as e:
                logger.debug("导航栏主题更新失败: %s", e)

        # 给所有已加载模块设置 theme 属性（不调用 set_theme 避免重复触发）
        for module_id, module_info in self._modules.items():
            if module_info.instance:
                try:
                    module_info.instance.setProperty("theme", actual_theme)
                    for child in module_info.instance.findChildren(QWidget):
                        child.setProperty("theme", actual_theme)
                except Exception as e:
                    logger.debug("模块 %s 主题属性设置失败: %s", module_id, e)

        # 持久化主题设置
        self._settings.setValue("theme", theme)
        self._settings.setValue("resolved_theme", actual_theme)

    def _apply_font_settings(self, settings):
        """应用字体设置"""
        font_size = settings.get("font_size", 14)
        font_family = settings.get("font_family", "Microsoft YaHei")
        
        # 应用字体设置到整个应用
        font = self.font()
        font.setFamily(font_family)
        font.setPointSize(font_size)
        self.setFont(font)
        
        # 应用字体设置到子控件
        def apply_font_to_widget(widget):
            widget.setFont(font)
            for child in widget.children():
                if hasattr(child, 'setFont'):
                    apply_font_to_widget(child)
        
        # 应用到中央部件
        apply_font_to_widget(self.centralWidget())
        
        # 应用到导航栏
        if hasattr(self, "_nav_bar"):
            apply_font_to_widget(self._nav_bar)
        
        # 应用到所有模块
        for module_id, module_info in self._modules.items():
            if module_info.instance:
                apply_font_to_widget(module_info.instance)
    
    # NOTE: _apply_dark_theme / _apply_light_theme 已被 ThemeManager 取代，不再需要
    # 主题 QSS 现在统一由 ThemeManager._build_qss() 生成，通过 QApplication 级别应用
    
    def _flush_pending_module_action(self, module_id: str) -> None:
        """交付 MODULE_ACTIVATED 携带的子页跳转 / 工作流提示（模块懒加载完成后调用）。"""
        pending = self._pending_module_actions.pop(module_id, None)
        if not pending:
            return

        widget = self.get_module_widget(module_id)
        action = pending.get("action")
        workflow_hint = pending.get("workflow_hint")
        nav_hint = pending.get("hint")

        # 携带数据交付（如文案模块「推送到剪辑模块」）：此时模块已确定加载
        # 完成、监听器已注册，emit 才是真正有接收方的
        data_payload = pending.get("data")
        if data_payload:
            self._event_bus.emit(EventType.COPY_GENERATED, data_payload)

        # 修复：首页「最近项目」双击此前只切到编辑器页签，从不真正加载工程——
        # 这里补上真正的打开逻辑
        if module_id == "editor" and action == "open_project":
            project_path = pending.get("project")
            if widget is not None and project_path and hasattr(widget, "import_project"):
                try:
                    widget.import_project(project_path)
                except Exception as e:
                    self.show_status(f"打开工程失败: {e}", "#f97316")
            return

        # M1：短剧筛选宿主为拓展中心；兼容旧 id=plugins
        if module_id in ("extensions", "plugins") and action == "drama_finder":
            if widget is not None:
                if hasattr(widget, "_open_drama_finder"):
                    widget._open_drama_finder()
                elif hasattr(widget, "_open_drama_finder_tab"):
                    widget._open_drama_finder_tab()
            if nav_hint:
                self.show_status(nav_hint, "#a78bfa")
            return

        if module_id == "editor" and workflow_hint and widget:
            if hasattr(widget, "_on_workflow_hint_received"):
                widget._on_workflow_hint_received(workflow_hint)
            elif nav_hint:
                self.show_status(nav_hint, "#ea580c")

    def _on_module_activated(self, event):
        """模块激活事件处理 — 支持携带数据、子页跳转与工作流提示"""
        data = event.data if isinstance(event.data, dict) else {}
        target = data.get("target") or event.data
        payload = data.get("data")
        action = data.get("action")
        workflow_hint = data.get("workflow_hint")
        nav_hint = data.get("hint")
        project_path = data.get("project")

        if not target:
            return

        # M1：旧事件 target=plugins → 拓展中心 extensions
        if target == "plugins":
            target = "extensions"

        registry = get_registry()
        if not registry.is_enabled(target):
            self.show_status(f"模块「{target}」未启用，请在设置 → 功能开关中打开", "#f97316")
            return

        if target not in self._modules or not self._nav_bar.has_module(target):
            self.show_status(f"导航中无模块「{target}」", "#f97316")
            return

        if action or workflow_hint or nav_hint or payload:
            self._pending_module_actions[target] = {
                "action": action,
                "workflow_hint": workflow_hint,
                "hint": nav_hint,
                "project": project_path,
                "data": payload,
            }

        self._nav_bar.select_module(target)

        # 模块已实例化时 select_module 不会再次走 _activate_module，需立即交付
        info = self._modules.get(target)
        if info and info.instance and info.state != ModuleState.ERROR:
            QTimer.singleShot(0, lambda mid=target: self._flush_pending_module_action(mid))
        # 修复：此前不管目标模块是否已加载，这里都会立即 emit COPY_GENERATED，
        # 但如果模块还没加载（懒加载走 QTimer.singleShot(50,...) 异步创建），
        # 此刻根本没有监听者，payload 会直接丢失且没有任何提示——用户以为
        # "推送成功"，编辑器里实际什么都没收到。现在统一改为通过
        # _pending_module_actions → _flush_pending_module_action 交付，
        # 保证只在模块真正加载完成（监听器已注册）之后才发送。
    
    def switch_to_module(self, module_id: str):
        """切换到指定模块"""
        self._nav_bar.select_module(module_id)
    
    def show_status(self, message: str, color: str = "#808080"):
        """显示状态消息"""
        self._status_bar.showMessage(message, 3000)  # 3秒后自动消失
        self._status_bar.setStyleSheet(f"""
            QStatusBar {{
                background-color: #2a2a2a;
                color: {color};
                font-size: 13px;
                font-weight: 500;
            }}
        """)
    
    def _show_help(self):
        """显示帮助信息"""
        from .help_module import HelpModule
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
        """登录按钮点击事件 - 异步非阻塞方式"""
        from .login_window import LoginWindow
        login_window = LoginWindow(parent=self)
        login_window.login_success.connect(self._on_login_success)
        login_window.show()
    
    def _on_login_success(self):
        """登录成功回调"""
        self._update_auth_status()
        self.show_status("登录成功", "#4caf50")
    
    def _on_activate_clicked(self):
        """激活按钮点击事件 - 异步非阻塞方式"""
        from .login_window import ActivationWindow
        activation_window = ActivationWindow(parent=self)
        activation_window.activation_success.connect(self._on_activation_success)
        activation_window.show()
    
    def _on_activation_success(self):
        """激活成功回调"""
        self._update_auth_status()
        self.show_status("激活成功", "#4caf50")
    
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
    
    def _restore_window_geometry(self):
        """按「记住窗口大小和位置」设置恢复上次退出时的窗口几何信息。

        修复：设置页里的"记住窗口大小和位置"复选框此前只是创建出来摆在
        UI 上，从未和任何真实的保存/恢复逻辑接线——不管勾不勾都没有任何
        效果，窗口每次启动都是写死的 1600x1000。
        """
        try:
            if not self._settings.value("remember_window", True, type=bool):
                return
            geometry = self._settings.value("window_geometry")
            if geometry:
                self.restoreGeometry(geometry)
        except Exception as e:
            logger.debug(f"恢复窗口几何信息失败: {e}")

    def _save_window_geometry(self):
        """退出前按设置保存窗口几何信息（配合 _restore_window_geometry）。"""
        try:
            if self._settings.value("remember_window", True, type=bool):
                self._settings.setValue("window_geometry", self.saveGeometry())
            else:
                self._settings.remove("window_geometry")
        except Exception as e:
            logger.debug(f"保存窗口几何信息失败: {e}")

    def closeEvent(self, event):
        """关闭事件"""
        logger.info("用户关闭主窗口")
        # 先停一切媒体，再存盘/拆控件，避免 Windows WMF 关窗后仍出声
        self._stop_all_media_on_exit()
        logger.info("保存项目状态...")
        self._event_bus.emit(EventType.PROJECT_SAVED, {})
        logger.info("清理资源...")
        
        for module_name, module_info in self._modules.items():
            if module_info.instance:
                try:
                    if hasattr(module_info.instance, 'cleanup'):
                        module_info.instance.cleanup()
                    elif hasattr(module_info.instance, 'on_deactivated'):
                        module_info.instance.on_deactivated()
                    logger.debug(f"模块 {module_name} 已清理")
                except Exception as e:
                    logger.warning(f"清理模块 {module_name} 失败: {e}")
        
        try:
            from modules.lego.async_track_renderer import shutdown_async_track_renderer
            shutdown_async_track_renderer()
            logger.info("异步轨道渲染系统已关闭")
        except ImportError as e:
            logger.debug("异步轨道渲染模块未启用: %s", e)
        except Exception as e:
            logger.debug(f"关闭异步渲染系统: {e}")
        
        logger.info("应用关闭完成")
        for child in self.findChildren(QWidget):
            try:
                child.close()
            except Exception as e:
                logger.debug("子窗口关闭失败: %s", e)
        event.accept()

    # >>> FROZEN:exit-media:main-window BEGIN
    def _stop_all_media_on_exit(self):
        """关闭前强制停止所有 QMediaPlayer，防止幽灵音频。"""
        try:
            from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
            from PyQt6.QtCore import QUrl
        except Exception:
            return
        # 模块级（剪辑主音/BGM）
        for module_info in self._modules.values():
            inst = module_info.instance
            if not inst:
                continue
            try:
                if hasattr(inst, "cleanup"):
                    inst.cleanup()
                elif hasattr(inst, "_shutdown_media"):
                    inst._shutdown_media(release_source=True)
                elif hasattr(inst, "on_deactivated"):
                    inst.on_deactivated()
            except Exception as e:
                logger.debug("模块媒体停止失败: %s", e)
        # 兜底：窗口树内所有播放器
        try:
            for player in self.findChildren(QMediaPlayer):
                try:
                    ao = player.audioOutput()
                    if isinstance(ao, QAudioOutput):
                        ao.setMuted(True)
                        ao.setVolume(0.0)
                except Exception as e:
                    logger.debug("播放器静音失败: %s", e)
                try:
                    player.stop()
                    player.setSource(QUrl())
                except Exception as e:
                    logger.debug("播放器停止失败: %s", e)
        except Exception as e:
            logger.debug("全局 QMediaPlayer 停止失败: %s", e)
    # <<< FROZEN:exit-media:main-window END

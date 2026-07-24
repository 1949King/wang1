"""
插件热加载机制
支持特效、转场、滤镜等组件的动态加载/卸载

B3 收敛标记 (2026-05-31): 动态热加载, 与 plugin_hotloader.py 互补
"""

import os
import sys
import importlib
import importlib.util
import json
import hashlib
import threading
import logging
from typing import Dict, List, Optional, Type, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod
from pathlib import Path
from datetime import datetime

logger = logging.getLogger("plugin_loader")


class PluginType(Enum):
    """插件类型"""
    EFFECT = "effect"
    TRANSITION = "transition"
    FILTER = "filter"
    SUBTITLE = "subtitle"
    AUDIO = "audio"
    EXPORT = "export"
    AI = "ai"
    CUSTOM = "custom"


class PluginCategory(Enum):
    """插件分类（短剧专属）"""
    COUNTERATTACK = "逆袭"
    EMOTION = "情感"
    SUSPENSE = "悬疑"
    SELLING = "带货"
    COMEDY = "喜剧"
    ROMANCE = "爱情"
    ACTION = "动作"
    HORROR = "恐怖"
    FANTASY = "奇幻"
    GENERAL = "通用"


class PluginState(Enum):
    """插件状态"""
    UNLOADED = "unloaded"
    LOADING = "loading"
    LOADED = "loaded"
    INITIALIZING = "initializing"
    INITIALIZED = "initialized"
    ERROR = "error"
    DISABLED = "disabled"


@dataclass
class PluginInfo:
    """插件信息"""
    id: str
    name: str
    version: str
    description: str
    author: str
    plugin_type: PluginType
    category: PluginCategory
    file_path: str
    dependencies: List[str] = field(default_factory=list)
    api_version: str = "1.0.0"
    min_engine_version: str = "1.0.0"
    icon: Optional[str] = None
    preview_image: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def copy(self):
        """复制插件信息"""
        from copy import deepcopy
        return deepcopy(self)


@dataclass
class PluginDependency:
    """插件依赖"""
    plugin_id: str
    min_version: str
    max_version: Optional[str] = None
    required: bool = True


class IPlugin(ABC):
    """插件接口"""
    
    @property
    @abstractmethod
    def plugin_info(self) -> PluginInfo:
        """获取插件信息"""
        pass
    
    @abstractmethod
    def initialize(self, context: Dict[str, Any]) -> bool:
        """初始化插件"""
        pass
    
    @abstractmethod
    def shutdown(self) -> bool:
        """关闭插件"""
        pass
    
    @abstractmethod
    def get_ui_config(self) -> Dict[str, Any]:
        """获取UI配置"""
        pass
    
    def on_enable(self) -> None:
        """插件启用时调用"""
        pass
    
    def on_disable(self) -> None:
        """插件禁用时调用"""
        pass
    
    def validate(self) -> bool:
        """验证插件"""
        return True


class IEffectPlugin(IPlugin):
    """特效插件接口"""
    
    @abstractmethod
    def apply_effect(self, frame_data: Any, params: Dict[str, Any]) -> Any:
        """应用特效"""
        pass
    
    @abstractmethod
    def get_effect_params(self) -> Dict[str, Any]:
        """获取特效参数"""
        pass


class ITransitionPlugin(IPlugin):
    """转场插件接口"""
    
    @abstractmethod
    def apply_transition(self, from_frame: Any, to_frame: Any, 
                        progress: float, params: Dict[str, Any]) -> Any:
        """应用转场"""
        pass
    
    @abstractmethod
    def get_transition_params(self) -> Dict[str, Any]:
        """获取转场参数"""
        pass


class IFilterPlugin(IPlugin):
    """滤镜插件接口"""
    
    @abstractmethod
    def apply_filter(self, frame_data: Any, params: Dict[str, Any]) -> Any:
        """应用滤镜"""
        pass
    
    @abstractmethod
    def get_filter_params(self) -> Dict[str, Any]:
        """获取滤镜参数"""
        pass


class IDockablePlugin(IPlugin):
    """可停靠插件接口（参考 Inline-AI-Video-Editor 的 dockable widget 扩展机制）"""
    
    @abstractmethod
    def create_dock_widget(self, parent=None) -> Any:
        """创建可停靠的UI部件"""
        pass
    
    @abstractmethod
    def get_dock_config(self) -> Dict[str, Any]:
        """获取停靠配置"""
        pass
    
    @abstractmethod
    def on_dock_closed(self):
        """停靠窗口关闭时调用"""
        pass


class PluginLoadError(Exception):
    """插件加载错误"""
    pass


class PluginDependencyError(Exception):
    """插件依赖错误"""
    pass


class PluginValidator:
    """插件验证器"""
    
    @staticmethod
    def validate_plugin_info(info: PluginInfo) -> bool:
        """验证插件信息"""
        if not info.id or not info.name or not info.version:
            return False
        
        if not isinstance(info.plugin_type, PluginType):
            return False
        
        if not isinstance(info.category, PluginCategory):
            return False
        
        if not os.path.exists(info.file_path):
            return False
        
        return True
    
    @staticmethod
    def validate_plugin_class(plugin_class: Type[IPlugin]) -> bool:
        """验证插件类"""
        if not issubclass(plugin_class, IPlugin):
            return False
        
        required_methods = ['plugin_info', 'initialize', 'shutdown', 'get_ui_config']
        for method in required_methods:
            if not hasattr(plugin_class, method):
                return False
        
        return True


class PluginDependencyResolver:
    """插件依赖解析器"""
    
    def __init__(self):
        self._dependency_graph: Dict[str, List[str]] = {}
        self._plugin_versions: Dict[str, str] = {}
    
    def add_plugin(self, plugin_id: str, version: str, dependencies: List[PluginDependency]):
        """添加插件到依赖图"""
        self._plugin_versions[plugin_id] = version
        self._dependency_graph[plugin_id] = []
        
        for dep in dependencies:
            self._dependency_graph[plugin_id].append(dep.plugin_id)
    
    def resolve_load_order(self, plugin_ids: List[str]) -> List[str]:
        """解析加载顺序（拓扑排序）"""
        visited = set()
        temp_visited = set()
        load_order = []
        
        def visit(plugin_id: str):
            if plugin_id in temp_visited:
                raise PluginDependencyError(f"循环依赖检测: {plugin_id}")
            
            if plugin_id in visited:
                return
            
            temp_visited.add(plugin_id)
            
            for dep_id in self._dependency_graph.get(plugin_id, []):
                visit(dep_id)
            
            temp_visited.remove(plugin_id)
            visited.add(plugin_id)
            load_order.append(plugin_id)
        
        for plugin_id in plugin_ids:
            visit(plugin_id)
        
        return load_order
    
    def check_dependencies(self, plugin_id: str, 
                          available_plugins: Dict[str, PluginInfo]) -> bool:
        """检查依赖是否满足"""
        if plugin_id not in self._dependency_graph:
            return True
        
        for dep_id in self._dependency_graph[plugin_id]:
            if dep_id not in available_plugins:
                return False
        
        return True


class PluginLoader:
    """插件加载器"""
    
    def __init__(self):
        self._plugins: Dict[str, IPlugin] = {}
        self._plugin_infos: Dict[str, PluginInfo] = {}
        self._plugin_states: Dict[str, PluginState] = {}
        self._plugin_modules: Dict[str, Any] = {}
        self._plugin_contexts: Dict[str, Dict[str, Any]] = {}
        
        self._validator = PluginValidator()
        self._dependency_resolver = PluginDependencyResolver()
        self._lock = threading.RLock()
        
        self._plugin_dirs: List[str] = []
        self._initialize_plugin_dirs()
    
    def _initialize_plugin_dirs(self):
        """初始化插件目录"""
        default_dirs = [
            "plugins",
            "app/plugins",
            os.path.join(os.path.dirname(__file__), "..", "plugins"),
            os.path.expanduser("~/.ai-video-editor/plugins")
        ]
        
        for directory in default_dirs:
            if os.path.exists(directory):
                self._plugin_dirs.append(directory)
    
    def add_plugin_dir(self, directory: str) -> bool:
        """添加插件目录"""
        if os.path.exists(directory) and directory not in self._plugin_dirs:
            self._plugin_dirs.append(directory)
            return True
        return False
    
    def discover_plugins(self) -> List[PluginInfo]:
        """发现插件"""
        discovered = []
        seen_ids = set()
        
        for plugin_dir in self._plugin_dirs:
            if not os.path.exists(plugin_dir):
                continue
            
            for item in os.listdir(plugin_dir):
                item_path = os.path.join(plugin_dir, item)
                
                if os.path.isfile(item_path) and item.endswith(".py"):
                    if item == "__init__.py":
                        continue
                    info = self._discover_plugin_from_file(item_path)
                    if info and info.id not in seen_ids:
                        discovered.append(info)
                        seen_ids.add(info.id)
                
                elif os.path.isdir(item_path):
                    info = self._discover_plugin_from_package(item_path)
                    if info and info.id not in seen_ids:
                        discovered.append(info)
                        seen_ids.add(info.id)
        
        return discovered
    
    def _discover_plugin_from_file(self, file_path: str) -> Optional[PluginInfo]:
        """从文件发现插件"""
        try:
            spec = importlib.util.spec_from_file_location(
                os.path.basename(file_path), 
                file_path
            )
            if spec is None:
                return None
            
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            if hasattr(module, "Plugin"):
                plugin_class = module.Plugin
                if self._validator.validate_plugin_class(plugin_class):
                    instance = plugin_class()
                    info = instance.plugin_info
                    if self._validator.validate_plugin_info(info):
                        return info
        
        except Exception as e:
            logger.warning(f"发现插件失败 {file_path}: {e}", exc_info=True)
        
        return None
    
    def _discover_plugin_from_package(self, package_path: str) -> Optional[PluginInfo]:
        """从包发现插件"""
        try:
            init_file = os.path.join(package_path, "__init__.py")
            if not os.path.exists(init_file):
                return None
            
            package_name = os.path.basename(package_path)
            spec = importlib.util.spec_from_file_location(
                package_name, 
                init_file
            )
            if spec is None:
                return None
            
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            if hasattr(module, "Plugin"):
                plugin_class = module.Plugin
                if self._validator.validate_plugin_class(plugin_class):
                    instance = plugin_class()
                    info = instance.plugin_info
                    if self._validator.validate_plugin_info(info):
                        return info
        
        except Exception as e:
            logger.warning(f"发现插件包失败 {package_path}: {e}", exc_info=True)
        
        return None
    
    def load_plugin(self, plugin_id: str, context: Optional[Dict[str, Any]] = None) -> bool:
        """加载插件"""
        with self._lock:
            if plugin_id in self._plugins:
                return True
            
            self._plugin_states[plugin_id] = PluginState.LOADING
            
            try:
                plugin_info = self._plugin_infos.get(plugin_id)
                if not plugin_info:
                    raise PluginLoadError(f"插件信息不存在: {plugin_id}")
                
                module = self._load_module(plugin_info.file_path)
                if not module:
                    raise PluginLoadError(f"加载模块失败: {plugin_info.file_path}")
                
                plugin_class = module.Plugin
                plugin_instance = plugin_class()
                
                if not plugin_instance.validate():
                    raise PluginLoadError(f"插件验证失败: {plugin_id}")
                
                self._plugin_states[plugin_id] = PluginState.LOADED
                self._plugins[plugin_id] = plugin_instance
                self._plugin_modules[plugin_id] = module
                self._plugin_contexts[plugin_id] = context or {}
                
                return True
            
            except Exception as e:
                self._plugin_states[plugin_id] = PluginState.ERROR
                logger.error(f"加载插件失败 {plugin_id}: {e}", exc_info=True)
                return False
    
    def _load_module(self, file_path: str) -> Optional[Any]:
        """加载模块"""
        try:
            if os.path.isfile(file_path):
                module_name = os.path.splitext(os.path.basename(file_path))[0]
                spec = importlib.util.spec_from_file_location(module_name, file_path)
            else:
                module_name = os.path.basename(file_path)
                init_file = os.path.join(file_path, "__init__.py")
                spec = importlib.util.spec_from_file_location(module_name, init_file)
            
            if spec is None:
                return None
            
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            
            return module
        
        except Exception as e:
            logger.error(f"加载模块失败 {file_path}: {e}", exc_info=True)
            return None
    
    def unload_plugin(self, plugin_id: str) -> bool:
        """卸载插件"""
        with self._lock:
            if plugin_id not in self._plugins:
                return False
            
            try:
                plugin = self._plugins[plugin_id]
                plugin.shutdown()
                
                del self._plugins[plugin_id]
                self._plugin_states[plugin_id] = PluginState.UNLOADED
                
                if plugin_id in self._plugin_modules:
                    module_name = self._plugin_modules[plugin_id].__name__
                    if module_name in sys.modules:
                        del sys.modules[module_name]
                    del self._plugin_modules[plugin_id]
                
                if plugin_id in self._plugin_contexts:
                    del self._plugin_contexts[plugin_id]
                
                return True
            
            except Exception as e:
                logger.error(f"卸载插件失败 {plugin_id}: {e}", exc_info=True)
                return False
    
    def reload_plugin(self, plugin_id: str) -> bool:
        """重新加载插件"""
        with self._lock:
            if plugin_id not in self._plugins:
                return False
            
            plugin_info = self._plugin_infos[plugin_id].copy()
            file_path = plugin_info.file_path
            
            if not self.unload_plugin(plugin_id):
                return False
            
            self._plugin_infos[plugin_id] = plugin_info
            
            try:
                module = self._load_module(file_path)
                if not module:
                    raise PluginLoadError(f"加载模块失败: {file_path}")
                
                plugin_class = module.Plugin
                plugin_instance = plugin_class()
                
                if not plugin_instance.validate():
                    raise PluginLoadError(f"插件验证失败: {plugin_id}")
                
                self._plugins[plugin_id] = plugin_instance
                self._plugin_modules[plugin_id] = module
                self._plugin_states[plugin_id] = PluginState.LOADED
                return True
            
            except Exception as e:
                self._plugin_states[plugin_id] = PluginState.ERROR
                logger.error(f"重新加载插件失败 {plugin_id}: {e}", exc_info=True)
                return False
    
    def initialize_plugin(self, plugin_id: str) -> bool:
        """初始化插件"""
        with self._lock:
            if plugin_id not in self._plugins:
                return False
            
            self._plugin_states[plugin_id] = PluginState.INITIALIZING
            
            try:
                plugin = self._plugins[plugin_id]
                context = self._plugin_contexts.get(plugin_id, {})
                
                if plugin.initialize(context):
                    self._plugin_states[plugin_id] = PluginState.INITIALIZED
                    return True
                else:
                    self._plugin_states[plugin_id] = PluginState.ERROR
                    return False
            
            except Exception as e:
                self._plugin_states[plugin_id] = PluginState.ERROR
                logger.error(f"初始化插件失败 {plugin_id}: {e}", exc_info=True)
                return False
    
    def enable_plugin(self, plugin_id: str) -> bool:
        """启用插件"""
        with self._lock:
            if plugin_id not in self._plugins:
                return False
            
            try:
                plugin = self._plugins[plugin_id]
                plugin.on_enable()
                return True
            except Exception as e:
                logger.error(f"启用插件失败 {plugin_id}: {e}", exc_info=True)
                return False
    
    def disable_plugin(self, plugin_id: str) -> bool:
        """禁用插件"""
        with self._lock:
            if plugin_id not in self._plugins:
                return False
            
            try:
                plugin = self._plugins[plugin_id]
                plugin.on_disable()
                return True
            except Exception as e:
                logger.error(f"禁用插件失败 {plugin_id}: {e}", exc_info=True)
                return False
    
    def get_plugin(self, plugin_id: str) -> Optional[IPlugin]:
        """获取插件实例"""
        return self._plugins.get(plugin_id)
    
    def get_plugin_info(self, plugin_id: str) -> Optional[PluginInfo]:
        """获取插件信息"""
        return self._plugin_infos.get(plugin_id)
    
    def get_plugin_state(self, plugin_id: str) -> Optional[PluginState]:
        """获取插件状态"""
        return self._plugin_states.get(plugin_id)
    
    def list_plugins(self, plugin_type: Optional[PluginType] = None,
                    category: Optional[PluginCategory] = None,
                    state: Optional[PluginState] = None) -> List[PluginInfo]:
        """列出插件"""
        plugins = list(self._plugin_infos.values())
        
        if plugin_type:
            plugins = [p for p in plugins if p.plugin_type == plugin_type]
        
        if category:
            plugins = [p for p in plugins if p.category == category]
        
        if state:
            plugins = [p for p in plugins if self._plugin_states.get(p.id) == state]
        
        return plugins
    
    def search_plugins(self, query: str) -> List[PluginInfo]:
        """搜索插件"""
        query = query.lower()
        results = []
        
        for plugin_info in self._plugin_infos.values():
            if (query in plugin_info.name.lower() or
                query in plugin_info.description.lower() or
                query in plugin_info.author.lower() or
                any(query in tag.lower() for tag in plugin_info.tags)):
                results.append(plugin_info)
        
        return results
    
    def load_plugins_batch(self, plugin_ids: List[str], 
                          context: Optional[Dict[str, Any]] = None) -> Dict[str, bool]:
        """批量加载插件"""
        results = {}
        
        for plugin_id in plugin_ids:
            results[plugin_id] = self.load_plugin(plugin_id, context)
        
        return results
    
    def unload_all(self) -> bool:
        """卸载所有插件"""
        plugin_ids = list(self._plugins.keys())
        success = True
        
        for plugin_id in plugin_ids:
            if not self.unload_plugin(plugin_id):
                success = False
        
        return success
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        stats = {
            "total_plugins": len(self._plugin_infos),
            "loaded_plugins": len(self._plugins),
            "initialized_plugins": sum(1 for s in self._plugin_states.values() 
                                      if s == PluginState.INITIALIZED),
            "error_plugins": sum(1 for s in self._plugin_states.values() 
                                if s == PluginState.ERROR),
            "by_type": {},
            "by_category": {}
        }
        
        for plugin_info in self._plugin_infos.values():
            plugin_type = plugin_info.plugin_type.value
            category = plugin_info.category.value
            
            stats["by_type"][plugin_type] = stats["by_type"].get(plugin_type, 0) + 1
            stats["by_category"][category] = stats["by_category"].get(category, 0) + 1
        
        return stats

    def get_dockable_plugins(self) -> List[str]:
        """获取所有可停靠插件的ID列表"""
        dockable_ids = []
        for plugin_id, plugin in self._plugins.items():
            if isinstance(plugin, IDockablePlugin):
                dockable_ids.append(plugin_id)
        return dockable_ids

    def create_dock_widget(self, plugin_id: str, parent=None) -> Any:
        """创建插件的可停靠部件"""
        plugin = self._plugins.get(plugin_id)
        if isinstance(plugin, IDockablePlugin):
            return plugin.create_dock_widget(parent)
        return None

    def get_dock_config(self, plugin_id: str) -> Dict[str, Any]:
        """获取插件的停靠配置"""
        plugin = self._plugins.get(plugin_id)
        if isinstance(plugin, IDockablePlugin):
            return plugin.get_dock_config()
        return {}

    def notify_dock_closed(self, plugin_id: str):
        """通知插件停靠窗口已关闭"""
        plugin = self._plugins.get(plugin_id)
        if isinstance(plugin, IDockablePlugin):
            plugin.on_dock_closed()


class PluginHotLoader:
    """插件热加载器（支持监控文件变化自动重载）"""
    
    def __init__(self, loader: PluginLoader):
        self._loader = loader
        self._file_hashes: Dict[str, str] = {}
        self._dir_hashes: Dict[str, str] = {}
        self._monitoring = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._registry = None  # 插件注册表引用
    
    def set_registry(self, registry):
        """设置插件注册表"""
        self._registry = registry
    
    def start_monitoring(self, interval: float = 1.0):
        """开始监控"""
        if self._monitoring:
            return
        
        self._monitoring = True
        self._stop_event.clear()
        
        # 初始化文件哈希
        self._initialize_hashes()
        
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            args=(interval,),
            daemon=True
        )
        self._monitor_thread.start()
    
    def stop_monitoring(self):
        """停止监控"""
        if not self._monitoring:
            return
        
        self._monitoring = False
        self._stop_event.set()
        
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5.0)
    
    def _initialize_hashes(self):
        """初始化文件哈希"""
        # 初始化插件文件哈希
        for plugin_id, plugin_info in self._loader._plugin_infos.items():
            file_path = plugin_info.file_path
            if os.path.exists(file_path):
                self._file_hashes[plugin_id] = self._calculate_file_hash(file_path)
        
        # 初始化插件目录哈希
        for plugin_dir in self._loader._plugin_dirs:
            if os.path.exists(plugin_dir):
                self._dir_hashes[plugin_dir] = self._calculate_dir_hash(plugin_dir)
    
    def _monitor_loop(self, interval: float):
        """监控循环"""
        while not self._stop_event.is_set():
            try:
                self._check_file_changes()
                self._check_directory_changes()
            except Exception as e:
                logger.warning(f"监控插件变化失败: {e}", exc_info=True)
            
            self._stop_event.wait(interval)
    
    def _check_file_changes(self):
        """检查文件变化"""
        for plugin_id, plugin_info in list(self._loader._plugin_infos.items()):
            file_path = plugin_info.file_path
            
            if not os.path.exists(file_path):
                # 插件文件被删除
                if plugin_id in self._file_hashes:
                    del self._file_hashes[plugin_id]
                continue
            
            current_hash = self._calculate_file_hash(file_path)
            
            if plugin_id in self._file_hashes:
                if current_hash != self._file_hashes[plugin_id]:
                    logger.info(f"检测到插件变化: {plugin_id}")
                    # 重新加载插件
                    if self._loader.reload_plugin(plugin_id):
                        # 重新初始化插件
                        self._loader.initialize_plugin(plugin_id)
            else:
                # 新插件文件
                self._file_hashes[plugin_id] = current_hash
    
    def _check_directory_changes(self):
        """检查目录变化（发现新插件）"""
        for plugin_dir in self._loader._plugin_dirs:
            if not os.path.exists(plugin_dir):
                continue
            
            current_hash = self._calculate_dir_hash(plugin_dir)
            
            if plugin_dir in self._dir_hashes:
                if current_hash != self._dir_hashes[plugin_dir]:
                    logger.info(f"检测到插件目录变化: {plugin_dir}")
                    # 发现新插件
                    self._discover_new_plugins(plugin_dir)
            
            self._dir_hashes[plugin_dir] = current_hash
    
    def _discover_new_plugins(self, plugin_dir: str):
        """发现新插件"""
        try:
            discovered = []
            seen_ids = set(self._loader._plugin_infos.keys())
            
            for item in os.listdir(plugin_dir):
                item_path = os.path.join(plugin_dir, item)
                
                if os.path.isfile(item_path) and item.endswith(".py"):
                    if item == "__init__.py":
                        continue
                    info = self._discover_plugin_from_file(item_path)
                    if info and info.id not in seen_ids:
                        discovered.append(info)
                        seen_ids.add(info.id)
                
                elif os.path.isdir(item_path):
                    info = self._discover_plugin_from_package(item_path)
                    if info and info.id not in seen_ids:
                        discovered.append(info)
                        seen_ids.add(info.id)
            
            if discovered:
                logger.info(f"发现 {len(discovered)} 个新插件")
                # 注册新插件
                for info in discovered:
                    self._loader._plugin_infos[info.id] = info
                    if self._registry:
                        self._registry.register(info)
                    # 加载新插件
                    self._loader.load_plugin(info.id)
                    self._loader.initialize_plugin(info.id)
        except Exception as e:
            logger.warning(f"发现新插件失败: {e}", exc_info=True)
    
    def _discover_plugin_from_file(self, file_path: str) -> Optional[PluginInfo]:
        """从文件发现插件"""
        try:
            spec = importlib.util.spec_from_file_location(
                os.path.basename(file_path), 
                file_path
            )
            if spec is None:
                return None
            
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            if hasattr(module, "Plugin"):
                plugin_class = module.Plugin
                validator = PluginValidator()
                if validator.validate_plugin_class(plugin_class):
                    instance = plugin_class()
                    info = instance.plugin_info
                    if validator.validate_plugin_info(info):
                        return info
        except Exception as e:
            logger.warning(f"发现插件失败 {file_path}: {e}", exc_info=True)
        return None
    
    def _discover_plugin_from_package(self, package_path: str) -> Optional[PluginInfo]:
        """从包发现插件"""
        try:
            init_file = os.path.join(package_path, "__init__.py")
            if not os.path.exists(init_file):
                return None
            
            package_name = os.path.basename(package_path)
            spec = importlib.util.spec_from_file_location(
                package_name, 
                init_file
            )
            if spec is None:
                return None
            
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            if hasattr(module, "Plugin"):
                plugin_class = module.Plugin
                validator = PluginValidator()
                if validator.validate_plugin_class(plugin_class):
                    instance = plugin_class()
                    info = instance.plugin_info
                    if validator.validate_plugin_info(info):
                        return info
        except Exception as e:
            logger.warning(f"发现插件包失败 {package_path}: {e}", exc_info=True)
        return None
    
    def _calculate_file_hash(self, file_path: str) -> str:
        """计算文件哈希"""
        if os.path.isfile(file_path):
            try:
                with open(file_path, 'rb') as f:
                    return hashlib.md5(f.read()).hexdigest()
            except Exception:
                return ""
        elif os.path.isdir(file_path):
            hash_obj = hashlib.md5()
            try:
                for root, dirs, files in os.walk(file_path):
                    for file in sorted(files):
                        file_path_full = os.path.join(root, file)
                        if file.endswith('.py'):
                            try:
                                with open(file_path_full, 'rb') as f:
                                    hash_obj.update(f.read())
                            except Exception:
                                pass
                return hash_obj.hexdigest()
            except Exception:
                return ""
        return ""
    
    def _calculate_dir_hash(self, dir_path: str) -> str:
        """计算目录哈希"""
        hash_obj = hashlib.md5()
        try:
            for root, dirs, files in os.walk(dir_path):
                # 只监控一级目录变化
                if root == dir_path:
                    for item in sorted(dirs + files):
                        item_path = os.path.join(root, item)
                        if os.path.isfile(item_path) and item.endswith('.py'):
                            hash_obj.update(item.encode('utf-8'))
                        elif os.path.isdir(item_path):
                            hash_obj.update(item.encode('utf-8'))
            return hash_obj.hexdigest()
        except Exception:
            return ""


class PluginRegistry:
    """插件注册表"""
    
    def __init__(self):
        self._registry: Dict[str, PluginInfo] = {}
        self._type_index: Dict[PluginType, List[str]] = {}
        self._category_index: Dict[PluginCategory, List[str]] = {}
        self._tag_index: Dict[str, List[str]] = {}
        self._lock = threading.RLock()
    
    def register(self, plugin_info: PluginInfo) -> bool:
        """注册插件"""
        with self._lock:
            if plugin_info.id in self._registry:
                return False
            
            self._registry[plugin_info.id] = plugin_info
            
            plugin_type = plugin_info.plugin_type
            if plugin_type not in self._type_index:
                self._type_index[plugin_type] = []
            self._type_index[plugin_type].append(plugin_info.id)
            
            category = plugin_info.category
            if category not in self._category_index:
                self._category_index[category] = []
            self._category_index[category].append(plugin_info.id)
            
            for tag in plugin_info.tags:
                if tag not in self._tag_index:
                    self._tag_index[tag] = []
                self._tag_index[tag].append(plugin_info.id)
            
            return True
    
    def unregister(self, plugin_id: str) -> bool:
        """注销插件"""
        with self._lock:
            if plugin_id not in self._registry:
                return False
            
            plugin_info = self._registry[plugin_id]
            
            plugin_type = plugin_info.plugin_type
            if plugin_type in self._type_index:
                self._type_index[plugin_type] = [
                    pid for pid in self._type_index[plugin_type] 
                    if pid != plugin_id
                ]
            
            category = plugin_info.category
            if category in self._category_index:
                self._category_index[category] = [
                    pid for pid in self._category_index[category] 
                    if pid != plugin_id
                ]
            
            for tag in plugin_info.tags:
                if tag in self._tag_index:
                    self._tag_index[tag] = [
                        pid for pid in self._tag_index[tag] 
                        if pid != plugin_id
                    ]
            
            del self._registry[plugin_id]
            return True
    
    def get(self, plugin_id: str) -> Optional[PluginInfo]:
        """获取插件信息"""
        return self._registry.get(plugin_id)
    
    def get_by_type(self, plugin_type: PluginType) -> List[PluginInfo]:
        """按类型获取插件"""
        plugin_ids = self._type_index.get(plugin_type, [])
        return [self._registry[pid] for pid in plugin_ids if pid in self._registry]
    
    def get_by_category(self, category: PluginCategory) -> List[PluginInfo]:
        """按分类获取插件"""
        plugin_ids = self._category_index.get(category, [])
        return [self._registry[pid] for pid in plugin_ids if pid in self._registry]
    
    def get_by_tag(self, tag: str) -> List[PluginInfo]:
        """按标签获取插件"""
        plugin_ids = self._tag_index.get(tag, [])
        return [self._registry[pid] for pid in plugin_ids if pid in self._registry]
    
    def list_all(self) -> List[PluginInfo]:
        """列出所有插件"""
        return list(self._registry.values())
    
    def export_registry(self, file_path: str) -> bool:
        """导出注册表"""
        try:
            data = {
                "plugins": [
                    {
                        "id": info.id,
                        "name": info.name,
                        "version": info.version,
                        "description": info.description,
                        "author": info.author,
                        "plugin_type": info.plugin_type.value,
                        "category": info.category.value,
                        "file_path": info.file_path,
                        "dependencies": info.dependencies,
                        "api_version": info.api_version,
                        "min_engine_version": info.min_engine_version,
                        "icon": info.icon,
                        "preview_image": info.preview_image,
                        "tags": info.tags,
                        "created_at": info.created_at,
                        "updated_at": info.updated_at
                    }
                    for info in self._registry.values()
                ]
            }
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            return True
        except Exception as e:
            logger.error(f"导出注册表失败: {e}", exc_info=True)
            return False
    
    def import_registry(self, file_path: str) -> bool:
        """导入注册表"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            for plugin_data in data.get("plugins", []):
                plugin_info = PluginInfo(
                    id=plugin_data["id"],
                    name=plugin_data["name"],
                    version=plugin_data["version"],
                    description=plugin_data["description"],
                    author=plugin_data["author"],
                    plugin_type=PluginType(plugin_data["plugin_type"]),
                    category=PluginCategory(plugin_data["category"]),
                    file_path=plugin_data["file_path"],
                    dependencies=plugin_data.get("dependencies", []),
                    api_version=plugin_data.get("api_version", "1.0.0"),
                    min_engine_version=plugin_data.get("min_engine_version", "1.0.0"),
                    icon=plugin_data.get("icon"),
                    preview_image=plugin_data.get("preview_image"),
                    tags=plugin_data.get("tags", []),
                    created_at=plugin_data.get("created_at", datetime.now().isoformat()),
                    updated_at=plugin_data.get("updated_at", datetime.now().isoformat())
                )
                self.register(plugin_info)
            
            return True
        except Exception as e:
            logger.error(f"导入注册表失败: {e}", exc_info=True)
            return False

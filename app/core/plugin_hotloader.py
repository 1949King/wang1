"""
插件管理器
整合插件加载、热加载、注册等功能
"""

import os
import json
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass
from enum import Enum
from threading import RLock
from pathlib import Path

from .plugin_loader import (
    PluginType, PluginCategory, PluginState, PluginInfo,
    IPlugin, IEffectPlugin, ITransitionPlugin, IFilterPlugin,
    PluginLoader, PluginHotLoader, PluginRegistry,
    PluginLoadError, PluginDependencyError
)

from .plugin_authentication import (
    PluginSecurityLevel, PluginTestStatus, PluginCertificate,
    PluginTestResult, PluginAuthenticator, PluginTester, PluginQualityAssurance
)


@dataclass
class PluginEvent:
    """插件事件"""
    event_type: str
    plugin_id: str
    plugin_info: Optional[PluginInfo] = None
    data: Optional[Dict[str, Any]] = None


class PluginManager:
    """插件管理器"""
    
    def __init__(self):
        self._loader = PluginLoader()
        self._registry = PluginRegistry()
        self._hot_loader = PluginHotLoader(self._loader)
        self._hot_loader.set_registry(self._registry)
        
        # 集成插件认证和测试系统
        self._authenticator = PluginAuthenticator()
        self._tester = PluginTester()
        self._qa = PluginQualityAssurance()
        
        self._event_handlers: Dict[str, List[Callable]] = {}
        self._lock = RLock()
        
        self._config_file = "plugin_config.json"
        self._load_config()
    
    def _load_config(self):
        """加载配置"""
        if os.path.exists(self._config_file):
            try:
                with open(self._config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    
                plugin_dirs = config.get("plugin_dirs", [])
                for directory in plugin_dirs:
                    self._loader.add_plugin_dir(directory)
                    
            except Exception as e:
                print(f"加载插件配置失败: {e}")
    
    def _save_config(self):
        """保存配置"""
        try:
            config = {
                "plugin_dirs": self._loader._plugin_dirs,
                "enabled_plugins": [
                    pid for pid, state in self._loader._plugin_states.items()
                    if state != PluginState.DISABLED
                ]
            }
            
            with open(self._config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
                
        except Exception as e:
            print(f"保存插件配置失败: {e}")
    
    def _emit_event(self, event: PluginEvent):
        """触发事件"""
        handlers = self._event_handlers.get(event.event_type, [])
        for handler in handlers:
            try:
                handler(event)
            except Exception as e:
                print(f"事件处理失败 {event.event_type}: {e}")
    
    def add_event_handler(self, event_type: str, handler: Callable):
        """添加事件处理器"""
        with self._lock:
            if event_type not in self._event_handlers:
                self._event_handlers[event_type] = []
            self._event_handlers[event_type].append(handler)
    
    def remove_event_handler(self, event_type: str, handler: Callable):
        """移除事件处理器"""
        with self._lock:
            if event_type in self._event_handlers:
                self._event_handlers[event_type] = [
                    h for h in self._event_handlers[event_type] 
                    if h != handler
                ]
    
    def discover_plugins(self) -> List[PluginInfo]:
        """发现插件"""
        discovered = self._loader.discover_plugins()
        
        for plugin_info in discovered:
            self._registry.register(plugin_info)
        
        self._emit_event(PluginEvent(
            event_type="plugins_discovered",
            plugin_id="",
            data={"count": len(discovered)}
        ))
        
        return discovered
    
    def load_plugin(self, plugin_id: str, 
                    context: Optional[Dict[str, Any]] = None,
                    auto_initialize: bool = True) -> bool:
        """加载插件"""
        with self._lock:
            plugin_info = self._registry.get(plugin_id)
            if not plugin_info:
                raise PluginLoadError(f"插件不存在: {plugin_id}")
            
            if self._loader.get_plugin_state(plugin_id) in [PluginState.LOADED, PluginState.INITIALIZED]:
                return True
            
            self._loader._plugin_infos[plugin_id] = plugin_info
            
            if self._loader.load_plugin(plugin_id, context):
                self._emit_event(PluginEvent(
                    event_type="plugin_loaded",
                    plugin_id=plugin_id,
                    plugin_info=plugin_info
                ))
                
                if auto_initialize:
                    self.initialize_plugin(plugin_id)
                
                return True
            
            self._emit_event(PluginEvent(
                event_type="plugin_load_failed",
                plugin_id=plugin_id,
                data={"error": "加载失败"}
            ))
            return False
    
    def unload_plugin(self, plugin_id: str) -> bool:
        """卸载插件"""
        with self._lock:
            if self._loader.unload_plugin(plugin_id):
                self._emit_event(PluginEvent(
                    event_type="plugin_unloaded",
                    plugin_id=plugin_id
                ))
                return True
            return False
    
    def reload_plugin(self, plugin_id: str) -> bool:
        """重新加载插件"""
        with self._lock:
            plugin_info = self._registry.get(plugin_id)
            if not plugin_info:
                return False
            
            if self._loader.reload_plugin(plugin_id):
                self._emit_event(PluginEvent(
                    event_type="plugin_reloaded",
                    plugin_id=plugin_id,
                    plugin_info=plugin_info
                ))
                return True
            return False
    
    def initialize_plugin(self, plugin_id: str) -> bool:
        """初始化插件"""
        with self._lock:
            if self._loader.initialize_plugin(plugin_id):
                self._emit_event(PluginEvent(
                    event_type="plugin_initialized",
                    plugin_id=plugin_id
                ))
                return True
            return False
    
    def enable_plugin(self, plugin_id: str) -> bool:
        """启用插件"""
        with self._lock:
            if self._loader.enable_plugin(plugin_id):
                self._emit_event(PluginEvent(
                    event_type="plugin_enabled",
                    plugin_id=plugin_id
                ))
                self._save_config()
                return True
            return False
    
    def disable_plugin(self, plugin_id: str) -> bool:
        """禁用插件"""
        with self._lock:
            if self._loader.disable_plugin(plugin_id):
                self._emit_event(PluginEvent(
                    event_type="plugin_disabled",
                    plugin_id=plugin_id
                ))
                self._save_config()
                return True
            return False
    
    def get_plugin(self, plugin_id: str) -> Optional[IPlugin]:
        """获取插件实例"""
        return self._loader.get_plugin(plugin_id)
    
    def get_plugin_info(self, plugin_id: str) -> Optional[PluginInfo]:
        """获取插件信息"""
        return self._registry.get(plugin_id)
    
    def get_plugin_state(self, plugin_id: str) -> Optional[PluginState]:
        """获取插件状态"""
        return self._loader.get_plugin_state(plugin_id)
    
    def list_plugins(self, plugin_type: Optional[PluginType] = None,
                    category: Optional[PluginCategory] = None,
                    state: Optional[PluginState] = None) -> List[PluginInfo]:
        """列出插件"""
        return self._loader.list_plugins(plugin_type, category, state)
    
    def search_plugins(self, query: str) -> List[PluginInfo]:
        """搜索插件"""
        return self._loader.search_plugins(query)
    
    def load_plugins_by_type(self, plugin_type: PluginType,
                            context: Optional[Dict[str, Any]] = None) -> Dict[str, bool]:
        """按类型加载插件"""
        plugins = self._registry.get_by_type(plugin_type)
        plugin_ids = [p.id for p in plugins]
        return self._loader.load_plugins_batch(plugin_ids, context)
    
    def load_plugins_by_category(self, category: PluginCategory,
                                context: Optional[Dict[str, Any]] = None) -> Dict[str, bool]:
        """按分类加载插件"""
        plugins = self._registry.get_by_category(category)
        plugin_ids = [p.id for p in plugins]
        return self._loader.load_plugins_batch(plugin_ids, context)
    
    def load_all_plugins(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, bool]:
        """加载所有插件"""
        plugins = self._registry.list_all()
        plugin_ids = [p.id for p in plugins]
        
        for plugin_id in plugin_ids:
            plugin_info = self._registry.get(plugin_id)
            if plugin_info:
                self._loader._plugin_infos[plugin_id] = plugin_info
        
        return self._loader.load_plugins_batch(plugin_ids, context)
    
    def unload_all_plugins(self) -> bool:
        """卸载所有插件"""
        return self._loader.unload_all()
    
    def start_hot_loading(self, interval: float = 1.0):
        """启动热加载"""
        self._hot_loader.start_monitoring(interval)
        self._emit_event(PluginEvent(
            event_type="hot_loading_started",
            plugin_id="",
            data={"interval": interval}
        ))
    
    def stop_hot_loading(self):
        """停止热加载"""
        self._hot_loader.stop_monitoring()
        self._emit_event(PluginEvent(
            event_type="hot_loading_stopped",
            plugin_id=""
        ))
    
    def add_plugin_dir(self, directory: str) -> bool:
        """添加插件目录"""
        result = self._loader.add_plugin_dir(directory)
        if result:
            self._save_config()
        return result
    
    def export_registry(self, file_path: str) -> bool:
        """导出注册表"""
        return self._registry.export_registry(file_path)
    
    def import_registry(self, file_path: str) -> bool:
        """导入注册表"""
        return self._registry.import_registry(file_path)
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return self._loader.get_statistics()
    
    def get_effect_plugins(self) -> List[IEffectPlugin]:
        """获取特效插件列表"""
        plugins = []
        for plugin_info in self._registry.get_by_type(PluginType.EFFECT):
            plugin = self._loader.get_plugin(plugin_info.id)
            if plugin and isinstance(plugin, IEffectPlugin):
                plugins.append(plugin)
        return plugins
    
    def get_transition_plugins(self) -> List[ITransitionPlugin]:
        """获取转场插件列表"""
        plugins = []
        for plugin_info in self._registry.get_by_type(PluginType.TRANSITION):
            plugin = self._loader.get_plugin(plugin_info.id)
            if plugin and isinstance(plugin, ITransitionPlugin):
                plugins.append(plugin)
        return plugins
    
    def get_filter_plugins(self) -> List[IFilterPlugin]:
        """获取滤镜插件列表"""
        plugins = []
        for plugin_info in self._registry.get_by_type(PluginType.FILTER):
            plugin = self._loader.get_plugin(plugin_info.id)
            if plugin and isinstance(plugin, IFilterPlugin):
                plugins.append(plugin)
        return plugins
    
    def apply_effect(self, plugin_id: str, frame_data: Any, 
                    params: Dict[str, Any]) -> Optional[Any]:
        """应用特效"""
        plugin = self._loader.get_plugin(plugin_id)
        if plugin and isinstance(plugin, IEffectPlugin):
            return plugin.apply_effect(frame_data, params)
        return None
    
    def apply_transition(self, plugin_id: str, from_frame: Any, to_frame: Any,
                        progress: float, params: Dict[str, Any]) -> Optional[Any]:
        """应用转场"""
        plugin = self._loader.get_plugin(plugin_id)
        if plugin and isinstance(plugin, ITransitionPlugin):
            return plugin.apply_transition(from_frame, to_frame, progress, params)
        return None
    
    def apply_filter(self, plugin_id: str, frame_data: Any,
                    params: Dict[str, Any]) -> Optional[Any]:
        """应用滤镜"""
        plugin = self._loader.get_plugin(plugin_id)
        if plugin and isinstance(plugin, IFilterPlugin):
            return plugin.apply_filter(frame_data, params)
        return None
    
    def get_plugin_ui_config(self, plugin_id: str) -> Optional[Dict[str, Any]]:
        """获取插件UI配置"""
        plugin = self._loader.get_plugin(plugin_id)
        if plugin:
            return plugin.get_ui_config()
        return None
    
    def get_plugin_params(self, plugin_id: str) -> Optional[Dict[str, Any]]:
        """获取插件参数"""
        plugin = self._loader.get_plugin(plugin_id)
        if plugin:
            if isinstance(plugin, IEffectPlugin):
                return plugin.get_effect_params()
            elif isinstance(plugin, ITransitionPlugin):
                return plugin.get_transition_params()
            elif isinstance(plugin, IFilterPlugin):
                return plugin.get_filter_params()
        return None
    
    def validate_plugin_dependencies(self, plugin_id: str) -> bool:
        """验证插件依赖"""
        plugin_info = self._registry.get(plugin_id)
        if not plugin_info:
            return False
        
        for dep_id in plugin_info.dependencies:
            dep_plugin = self._registry.get(dep_id)
            if not dep_plugin:
                return False
        
        return True
    
    def get_plugin_dependencies(self, plugin_id: str) -> List[PluginInfo]:
        """获取插件依赖"""
        plugin_info = self._registry.get(plugin_id)
        if not plugin_info:
            return []
        
        dependencies = []
        for dep_id in plugin_info.dependencies:
            dep_plugin = self._registry.get(dep_id)
            if dep_plugin:
                dependencies.append(dep_plugin)
        
        return dependencies
    
    def get_dependent_plugins(self, plugin_id: str) -> List[PluginInfo]:
        """获取依赖此插件的其他插件"""
        dependents = []
        
        for plugin_info in self._registry.list_all():
            if plugin_id in plugin_info.dependencies:
                dependents.append(plugin_info)
        
        return dependents
    
    def get_shortplay_plugins(self) -> Dict[PluginCategory, List[PluginInfo]]:
        """获取短剧专属插件（按分类）"""
        result = {}
        
        for category in PluginCategory:
            if category == PluginCategory.GENERAL:
                continue
            result[category] = self._registry.get_by_category(category)
        
        return result
    
    def initialize(self, context: Optional[Dict[str, Any]] = None) -> bool:
        """初始化插件管理器"""
        try:
            self.discover_plugins()
            self.load_all_plugins(context)
            self.start_hot_loading()
            return True
        except Exception as e:
            print(f"初始化插件管理器失败: {e}")
            return False
    
    def shutdown(self) -> bool:
        """关闭插件管理器"""
        try:
            self.stop_hot_loading()
            self.unload_all_plugins()
            self._save_config()
            return True
        except Exception as e:
            print(f"关闭插件管理器失败: {e}")
            return False
    
    def certify_plugin(self, plugin_id: str) -> Dict[str, Any]:
        """认证插件"""
        with self._lock:
            plugin_info = self._registry.get(plugin_id)
            if not plugin_info:
                return {"error": "插件不存在"}
            
            plugin = self._loader.get_plugin(plugin_id)
            if not plugin:
                return {"error": "插件未加载"}
            
            plugin_info_dict = {
                "id": plugin_info.id,
                "name": plugin_info.name,
                "version": plugin_info.version,
                "author": plugin_info.author,
                "plugin_type": plugin_info.plugin_type.value,
                "category": plugin_info.category.value,
                "file_path": plugin_info.file_path
            }
            
            success, result = self._qa.certify_plugin(plugin_info_dict, plugin)
            return result
    
    def test_plugin(self, plugin_id: str) -> Optional[PluginTestResult]:
        """测试插件"""
        with self._lock:
            plugin = self._loader.get_plugin(plugin_id)
            if not plugin:
                return None
            
            return self._tester.test_plugin(plugin_id, plugin)
    
    def get_plugin_quality_score(self, plugin_id: str) -> float:
        """获取插件质量评分"""
        return self._qa.get_plugin_quality_score(plugin_id)
    
    def generate_quality_report(self, plugin_id: str) -> Dict[str, Any]:
        """生成插件质量报告"""
        return self._qa.generate_quality_report(plugin_id)
    
    def list_certified_plugins(self) -> List[Dict[str, Any]]:
        """列出已认证的插件"""
        return self._qa.list_certified_plugins()
    
    def verify_plugin(self, plugin_id: str) -> Dict[str, Any]:
        """验证插件"""
        return self._qa.verify_plugin(plugin_id)
    
    def get_plugin_certificate(self, plugin_id: str) -> Optional[PluginCertificate]:
        """获取插件证书"""
        return self._authenticator.get_certificate(plugin_id)
    
    def get_plugin_test_result(self, plugin_id: str) -> Optional[PluginTestResult]:
        """获取插件测试结果"""
        return self._tester.get_test_result(plugin_id)


class PluginContext:
    """插件上下文"""
    
    def __init__(self):
        self._context: Dict[str, Any] = {}
    
    def set(self, key: str, value: Any):
        """设置上下文值"""
        self._context[key] = value
    
    def get(self, key: str, default: Any = None) -> Any:
        """获取上下文值"""
        return self._context.get(key, default)
    
    def has(self, key: str) -> bool:
        """检查是否存在键"""
        return key in self._context
    
    def remove(self, key: str) -> bool:
        """移除键"""
        if key in self._context:
            del self._context[key]
            return True
        return False
    
    def clear(self):
        """清空上下文"""
        self._context.clear()
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return self._context.copy()


class PluginFactory:
    """插件工厂"""
    
    @staticmethod
    def create_effect_plugin(name: str, version: str, description: str,
                            author: str, category: PluginCategory,
                            file_path: str) -> PluginInfo:
        """创建特效插件信息"""
        return PluginInfo(
            id=f"effect_{name.lower().replace(' ', '_')}",
            name=name,
            version=version,
            description=description,
            author=author,
            plugin_type=PluginType.EFFECT,
            category=category,
            file_path=file_path,
            tags=["effect", category.value]
        )
    
    @staticmethod
    def create_transition_plugin(name: str, version: str, description: str,
                                author: str, category: PluginCategory,
                                file_path: str) -> PluginInfo:
        """创建转场插件信息"""
        return PluginInfo(
            id=f"transition_{name.lower().replace(' ', '_')}",
            name=name,
            version=version,
            description=description,
            author=author,
            plugin_type=PluginType.TRANSITION,
            category=category,
            file_path=file_path,
            tags=["transition", category.value]
        )
    
    @staticmethod
    def create_filter_plugin(name: str, version: str, description: str,
                            author: str, category: PluginCategory,
                            file_path: str) -> PluginInfo:
        """创建滤镜插件信息"""
        return PluginInfo(
            id=f"filter_{name.lower().replace(' ', '_')}",
            name=name,
            version=version,
            description=description,
            author=author,
            plugin_type=PluginType.FILTER,
            category=category,
            file_path=file_path,
            tags=["filter", category.value]
        )


class PluginInstaller:
    """插件安装器"""
    
    def __init__(self, manager: PluginManager):
        self._manager = manager
        self._install_dir = "plugins"
    
    def install_from_file(self, file_path: str, 
                         plugin_info: PluginInfo) -> bool:
        """从文件安装插件"""
        try:
            if not os.path.exists(file_path):
                return False
            
            if not os.path.exists(self._install_dir):
                os.makedirs(self._install_dir)
            
            dest_path = os.path.join(self._install_dir, os.path.basename(file_path))
            
            if os.path.isfile(file_path):
                import shutil
                shutil.copy2(file_path, dest_path)
            elif os.path.isdir(file_path):
                import shutil
                shutil.copytree(file_path, dest_path, dirs_exist_ok=True)
            
            plugin_info.file_path = dest_path
            self._manager._registry.register(plugin_info)
            
            return True
        except Exception as e:
            print(f"安装插件失败: {e}")
            return False
    
    def uninstall_plugin(self, plugin_id: str) -> bool:
        """卸载插件"""
        try:
            plugin_info = self._manager.get_plugin_info(plugin_id)
            if not plugin_info:
                return False
            
            self._manager.unload_plugin(plugin_id)
            self._manager._registry.unregister(plugin_id)
            
            if os.path.exists(plugin_info.file_path):
                if os.path.isfile(plugin_info.file_path):
                    os.remove(plugin_info.file_path)
                elif os.path.isdir(plugin_info.file_path):
                    import shutil
                    shutil.rmtree(plugin_info.file_path)
            
            return True
        except Exception as e:
            print(f"卸载插件失败: {e}")
            return False
    
    def install_from_package(self, package_path: str) -> bool:
        """从包安装插件"""
        try:
            if package_path.endswith('.zip'):
                import zipfile
                import tempfile
                
                with tempfile.TemporaryDirectory() as temp_dir:
                    with zipfile.ZipFile(package_path, 'r') as zip_ref:
                        zip_ref.extractall(temp_dir)
                    
                    for item in os.listdir(temp_dir):
                        item_path = os.path.join(temp_dir, item)
                        if os.path.isdir(item_path):
                            plugin_info = self._extract_plugin_info(item_path)
                            if plugin_info:
                                self.install_from_file(item_path, plugin_info)
            
            return True
        except Exception as e:
            print(f"从包安装插件失败: {e}")
            return False
    
    def _extract_plugin_info(self, package_path: str) -> Optional[PluginInfo]:
        """从包中提取插件信息"""
        try:
            init_file = os.path.join(package_path, "__init__.py")
            if not os.path.exists(init_file):
                return None
            
            import importlib.util
            package_name = os.path.basename(package_path)
            spec = importlib.util.spec_from_file_location(package_name, init_file)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            if hasattr(module, "Plugin"):
                plugin_class = module.Plugin
                instance = plugin_class()
                return instance.plugin_info
            
            return None
        except Exception as e:
            print(f"提取插件信息失败: {e}")
            return None

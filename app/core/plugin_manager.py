import os
import importlib.util
import sys

# B3 收敛标记 (2026-05-31):
# 本文件是 plugin_manager 核心类 (PluginManager 注册中心)
# 与 plugin_loader.py / plugin_hotloader.py / plugin_marketplace.py
#     / plugin_sandbox.py / plugin_authentication.py 互补

class PluginManager:
    def __init__(self):
        self.plugins = []
        self.plugin_dirs = []
        self._initialize_plugin_dirs()
    
    def _initialize_plugin_dirs(self):
        """初始化插件目录"""
        # 默认插件目录
        default_dirs = [
            "plugins",
            "app/plugins",
            os.path.expanduser("~/.ai-video-editor/plugins")
        ]
        
        for directory in default_dirs:
            if os.path.exists(directory):
                self.plugin_dirs.append(directory)
    
    def add_plugin_dir(self, directory):
        """添加插件目录"""
        if os.path.exists(directory) and directory not in self.plugin_dirs:
            self.plugin_dirs.append(directory)
            return True
        return False
    
    def load_plugins(self):
        """加载所有插件"""
        loaded_plugins = []
        
        for plugin_dir in self.plugin_dirs:
            if not os.path.exists(plugin_dir):
                continue
            
            for item in os.listdir(plugin_dir):
                item_path = os.path.join(plugin_dir, item)
                
                # 处理Python文件
                if os.path.isfile(item_path) and item.endswith(".py"):
                    plugin = self._load_plugin_from_file(item_path)
                    if plugin:
                        loaded_plugins.append(plugin)
                
                # 处理插件目录
                elif os.path.isdir(item_path) and os.path.exists(os.path.join(item_path, "__init__.py")):
                    plugin = self._load_plugin_from_package(item_path)
                    if plugin:
                        loaded_plugins.append(plugin)
        
        self.plugins = loaded_plugins
        return loaded_plugins
    
    def _load_plugin_from_file(self, file_path):
        """从文件加载插件"""
        try:
            spec = importlib.util.spec_from_file_location(os.path.basename(file_path), file_path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            
            if hasattr(module, "Plugin"):
                plugin_instance = module.Plugin()
                plugin_instance._file_path = file_path
                plugin_instance._type = "file"
                return self._validate_plugin(plugin_instance)
        except Exception as e:
            print(f"Error loading plugin from file {file_path}: {e}")
        return None
    
    def _load_plugin_from_package(self, package_path):
        """从包加载插件"""
        try:
            package_name = os.path.basename(package_path)
            spec = importlib.util.spec_from_file_location(
                package_name, 
                os.path.join(package_path, "__init__.py")
            )
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            
            if hasattr(module, "Plugin"):
                plugin_instance = module.Plugin()
                plugin_instance._file_path = package_path
                plugin_instance._type = "package"
                return self._validate_plugin(plugin_instance)
        except Exception as e:
            print(f"Error loading plugin from package {package_path}: {e}")
        return None
    
    def _validate_plugin(self, plugin):
        """验证插件是否有效"""
        required_attributes = ["name", "version", "description"]
        required_methods = ["initialize", "run"]
        
        for attr in required_attributes:
            if not hasattr(plugin, attr):
                return None
        
        for method in required_methods:
            if not hasattr(plugin, method):
                return None
        
        # 添加插件ID
        plugin.id = f"plugin_{len(self.plugins) + 1}"
        plugin.enabled = True
        
        return plugin
    
    def list_plugins(self, enabled_only=False):
        """列出所有插件"""
        if enabled_only:
            return [p for p in self.plugins if getattr(p, "enabled", False)]
        return self.plugins
    
    def get_plugin(self, plugin_id):
        """获取插件"""
        for plugin in self.plugins:
            if getattr(plugin, "id", None) == plugin_id:
                return plugin
        return None
    
    def enable_plugin(self, plugin_id):
        """启用插件"""
        plugin = self.get_plugin(plugin_id)
        if plugin:
            plugin.enabled = True
            if hasattr(plugin, "on_enable"):
                plugin.on_enable()
            return True
        return False
    
    def disable_plugin(self, plugin_id):
        """禁用插件"""
        plugin = self.get_plugin(plugin_id)
        if plugin:
            plugin.enabled = False
            if hasattr(plugin, "on_disable"):
                plugin.on_disable()
            return True
        return False
    
    def run_plugin(self, plugin_id, **kwargs):
        """运行插件"""
        plugin = self.get_plugin(plugin_id)
        if plugin and getattr(plugin, "enabled", False):
            try:
                return plugin.run(**kwargs)
            except Exception as e:
                print(f"Error running plugin {plugin_id}: {e}")
                return None
        return None
    
    def remove_plugin(self, plugin_id):
        """移除插件"""
        plugin = self.get_plugin(plugin_id)
        if plugin:
            # 禁用插件
            self.disable_plugin(plugin_id)
            # 从列表中移除
            self.plugins = [p for p in self.plugins if p.id != plugin_id]
            # 清理模块
            if hasattr(plugin, "_module_name") and plugin._module_name in sys.modules:
                del sys.modules[plugin._module_name]
            return True
        return False
    
    def reload_plugin(self, plugin_id):
        """重新加载插件"""
        plugin = self.get_plugin(plugin_id)
        if plugin and hasattr(plugin, "_file_path"):
            # 移除旧插件
            self.remove_plugin(plugin_id)
            # 重新加载
            if plugin._type == "file":
                new_plugin = self._load_plugin_from_file(plugin._file_path)
            else:
                new_plugin = self._load_plugin_from_package(plugin._file_path)
            
            if new_plugin:
                self.plugins.append(new_plugin)
                return new_plugin
        return None
    
    def search_plugins(self, query):
        """搜索插件"""
        query = query.lower()
        return [p for p in self.plugins if 
                query in getattr(p, "name", "").lower() or 
                query in getattr(p, "description", "").lower()]
    
    def get_plugin_info(self, plugin_id):
        """获取插件信息"""
        plugin = self.get_plugin(plugin_id)
        if plugin:
            return {
                "id": plugin.id,
                "name": getattr(plugin, "name", "Unknown"),
                "version": getattr(plugin, "version", "0.0.0"),
                "description": getattr(plugin, "description", "No description"),
                "enabled": getattr(plugin, "enabled", False),
                "type": getattr(plugin, "_type", "unknown"),
                "path": getattr(plugin, "_file_path", "Unknown")
            }
        return None
    
    def initialize_plugins(self):
        """初始化所有插件"""
        for plugin in self.plugins:
            if getattr(plugin, "enabled", False):
                try:
                    plugin.initialize()
                except Exception as e:
                    print(f"Error initializing plugin {plugin.id}: {e}")
    
    def shutdown_plugins(self):
        """关闭所有插件"""
        for plugin in self.plugins:
            if hasattr(plugin, "shutdown"):
                try:
                    plugin.shutdown()
                except Exception as e:
                    print(f"Error shutting down plugin {plugin.id}: {e}")
    
    def get_plugin_categories(self):
        """获取插件分类"""
        categories = set()
        for plugin in self.plugins:
            if hasattr(plugin, "category"):
                categories.add(plugin.category)
        return list(categories)
    
    def list_plugins_by_category(self, category):
        """按分类列出插件"""
        return [p for p in self.plugins if getattr(p, "category", None) == category]
    
    def install_plugin(self, plugin_path):
        """安装插件"""
        # 这里应该实现实际的插件安装逻辑
        # 暂时返回成功
        return True
    
    def uninstall_plugin(self, plugin_id):
        """卸载插件"""
        # 这里应该实现实际的插件卸载逻辑
        # 暂时返回成功
        return self.remove_plugin(plugin_id)

# 插件基类示例
class PluginBase:
    """插件基类"""
    name = "Base Plugin"
    version = "1.0.0"
    description = "Base plugin class"
    category = "general"
    
    def initialize(self):
        """初始化插件"""
        pass
    
    def run(self, **kwargs):
        """运行插件"""
        pass
    
    def on_enable(self):
        """插件启用时调用"""
        pass
    
    def on_disable(self):
        """插件禁用时调用"""
        pass
    
    def shutdown(self):
        """关闭插件"""
        pass
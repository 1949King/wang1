import os
import importlib.util
import sys
import logging

logger = logging.getLogger("plugin_manager")

# B3 收敛标记 (2026-05-31):
# 本文件是 plugin_manager 核心类 (PluginManager 注册中心)
# 与 plugin_loader.py / plugin_hotloader.py / plugin_marketplace.py
#     / plugin_sandbox.py / plugin_authentication.py 互补

class PluginManager:
    def __init__(self):
        self.plugins = []
        self.plugin_dirs = []
        # [(path, error_message), ...] 最近一次 load_plugins 的失败记录
        self._load_errors = []
        # 插件 id 自增序号；不用 len(self.plugins)，避免批量加载时
        # self.plugins 尚未回填导致同批插件全部拿到 "plugin_1"
        self._plugin_id_seq = 0
        self._initialize_plugin_dirs()
    
    def _initialize_plugin_dirs(self):
        """初始化插件目录"""
        # 默认插件目录（相对 cwd + 相对本文件定位 app/plugins）
        here = os.path.dirname(os.path.abspath(__file__))
        app_root = os.path.dirname(here)  # app/
        default_dirs = [
            "plugins",
            "app/plugins",
            os.path.join(app_root, "plugins"),
            os.path.expanduser("~/.ai-video-editor/plugins")
        ]
        
        for directory in default_dirs:
            abs_dir = os.path.abspath(directory)
            if os.path.exists(abs_dir) and abs_dir not in self.plugin_dirs:
                self.plugin_dirs.append(abs_dir)
    
    def add_plugin_dir(self, directory):
        """添加插件目录"""
        if os.path.exists(directory) and directory not in self.plugin_dirs:
            self.plugin_dirs.append(directory)
            return True
        return False

    def get_load_errors(self):
        """最近一次 load_plugins 的失败列表 [(path, error), ...]"""
        return list(self._load_errors)

    def format_load_errors(self, limit: int = 8) -> str:
        """用户可读的加载失败摘要"""
        if not self._load_errors:
            return ""
        lines = []
        for path, err in self._load_errors[:limit]:
            name = os.path.basename(path.rstrip("\\/"))
            lines.append(f"· {name}: {err}")
        if len(self._load_errors) > limit:
            lines.append(f"· …另有 {len(self._load_errors) - limit} 项")
        return "\n".join(lines)
    
    def load_plugins(self):
        """加载所有插件"""
        loaded_plugins = []
        self._load_errors = []
        self._plugin_id_seq = 0
        
        for plugin_dir in self.plugin_dirs:
            if not os.path.exists(plugin_dir):
                continue
            
            for item in os.listdir(plugin_dir):
                item_path = os.path.join(plugin_dir, item)
                
                # 处理Python文件
                if os.path.isfile(item_path) and item.endswith(".py"):
                    if item.startswith("_"):
                        continue
                    # 非插件入口（配置/工具模块），勿当 Plugin 加载
                    if item in ("plugin_config.py",):
                        continue
                    plugin = self._load_plugin_from_file(item_path)
                    if plugin:
                        loaded_plugins.append(plugin)
                
                # 处理插件目录
                elif os.path.isdir(item_path) and os.path.exists(os.path.join(item_path, "__init__.py")):
                    plugin = self._load_plugin_from_package(item_path)
                    if plugin:
                        loaded_plugins.append(plugin)
        
        self.plugins = loaded_plugins
        if self._load_errors:
            logger.warning(
                "插件加载失败 %d 个:\n%s",
                len(self._load_errors),
                self.format_load_errors(),
            )
        return loaded_plugins

    def _record_load_error(self, path: str, error: str):
        msg = str(error).strip() or "未知错误"
        self._load_errors.append((path, msg))
        logger.warning("加载插件失败 %s: %s", path, msg)
    
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
                return self._validate_plugin(plugin_instance, file_path)
            self._record_load_error(file_path, "模块无 Plugin 入口类")
        except Exception as e:
            self._record_load_error(file_path, e)
        return None
    
    def _load_plugin_from_package(self, package_path):
        """从包加载插件"""
        try:
            package_name = os.path.basename(package_path)
            # 优先用包名作为模块名，避免与其它包冲突时被覆盖
            module_key = f"plugins_pkg_{package_name}"
            spec = importlib.util.spec_from_file_location(
                module_key, 
                os.path.join(package_path, "__init__.py")
            )
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            # 保证包内相对导入可用
            if hasattr(spec, "submodule_search_locations"):
                spec.submodule_search_locations = [package_path]
            spec.loader.exec_module(module)
            
            if hasattr(module, "Plugin"):
                plugin_instance = module.Plugin()
                plugin_instance._file_path = package_path
                plugin_instance._type = "package"
                return self._validate_plugin(plugin_instance, package_path)
            # __init__ 可能因依赖失败未导出 Plugin
            load_err = getattr(module, "PLUGIN_LOAD_ERROR", "") or "包内无 Plugin 入口"
            self._record_load_error(package_path, load_err)
        except Exception as e:
            self._record_load_error(package_path, e)
        return None
    
    def _validate_plugin(self, plugin, source_path: str = ""):
        """验证插件是否有效（兼容旧属性式 + plugin_info 式）"""
        # 兼容 IPlugin.plugin_info
        info = getattr(plugin, "plugin_info", None)
        if info is not None:
            for attr, key in (("name", "name"), ("version", "version"), ("description", "description")):
                if not hasattr(plugin, attr) or not getattr(plugin, attr):
                    try:
                        setattr(plugin, attr, getattr(info, key, "") or "")
                    except Exception as e:
                        logger.debug(f"[PluginManager] 设置插件属性 {attr} 失败: {e}")

        required_attributes = ["name", "version", "description"]
        for attr in required_attributes:
            if not hasattr(plugin, attr) or not getattr(plugin, attr):
                self._record_load_error(
                    source_path or getattr(plugin, "_file_path", "?"),
                    f"缺少属性 {attr}（或 plugin_info.{attr}）",
                )
                return None
        
        if not hasattr(plugin, "initialize") or not callable(getattr(plugin, "initialize")):
            self._record_load_error(
                source_path or getattr(plugin, "_file_path", "?"),
                "缺少 initialize() 方法",
            )
            return None

        # 旧插件要 run；特效插件可用 apply_effect / get_ui_config 代替
        has_run = hasattr(plugin, "run") and callable(getattr(plugin, "run"))
        has_effect = hasattr(plugin, "apply_effect") and callable(getattr(plugin, "apply_effect"))
        has_ui = hasattr(plugin, "get_ui_config") and callable(getattr(plugin, "get_ui_config"))
        if not (has_run or has_effect or has_ui):
            self._record_load_error(
                source_path or getattr(plugin, "_file_path", "?"),
                "缺少 run / apply_effect / get_ui_config 之一",
            )
            return None

        if not has_run:
            # 给 PluginManager 列表/开关用的空 run，避免调用方 AttributeError
            plugin.run = lambda *a, **k: True
        
        self._plugin_id_seq += 1
        plugin.id = f"plugin_{self._plugin_id_seq}"
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
                logger.error(f'Error running plugin {plugin_id}: {e}')
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
                    logger.error(f'Error initializing plugin {plugin.id}: {e}')
    
    def shutdown_plugins(self):
        """关闭所有插件"""
        for plugin in self.plugins:
            if hasattr(plugin, "shutdown"):
                try:
                    plugin.shutdown()
                except Exception as e:
                    logger.error(f'Error shutting down plugin {plugin.id}: {e}')
    
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
        """安装插件

        修复：此前无任何安装逻辑却恒 return True，调用方（plugins_module 回退路径）
        会弹"安装成功"，但插件其实完全没有被复制/注册——纯粹的假成功。
        这里如实返回 False，让调用方走既有的"请手动放入 plugins/ 目录"提示，
        而不是撒谎说已经装好了。真正的安装应走 PluginStore.install_item()。
        """
        logger.warning(f"[PluginManager] install_plugin 未实现真实安装逻辑，跳过: {plugin_path}")
        return False
    
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
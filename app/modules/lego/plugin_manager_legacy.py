"""
插件管理模块 (PluginManager)
===========================
支持内置插件和外部插件的管理、加载、启用/禁用等
"""

import os
import json
import shutil
import zipfile
import importlib.util
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


class Config:
    """配置类"""
    APP_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


class PluginManager:
    """插件管理类（支持内置插件和外部插件）"""
    
    def __init__(self, output_dir: Optional[str] = None):
        self.builtin_plugins_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "plugins")
        self.external_plugins_dir = os.path.join(Config.APP_DATA_DIR, "plugins")
        self.loaded_plugins: Dict[str, Any] = {}
        self.plugin_metadata: Dict[str, Dict] = {}
        
        os.makedirs(self.builtin_plugins_dir, exist_ok=True)
        os.makedirs(self.external_plugins_dir, exist_ok=True)
        
        self.load_all_plugins()
    
    def load_all_plugins(self):
        """加载所有插件（内置+外部）"""
        self.loaded_plugins.clear()
        self.plugin_metadata.clear()
        
        self.load_plugins_from_dir(self.builtin_plugins_dir, source="builtin")
        self.load_plugins_from_dir(self.external_plugins_dir, source="external")
        
        logger.info(f"插件加载完成，共加载 {len(self.loaded_plugins)} 个插件")
    
    def load_plugins_from_dir(self, plugins_dir: str, source: str = "builtin"):
        """从指定目录加载插件"""
        if not os.path.exists(plugins_dir):
            return
        
        for plugin_name in os.listdir(plugins_dir):
            plugin_path = os.path.join(plugins_dir, plugin_name)
            
            if os.path.isdir(plugin_path):
                metadata_path = os.path.join(plugin_path, "metadata.json")
                main_path = os.path.join(plugin_path, "main.py")
                
                if os.path.exists(metadata_path) and os.path.exists(main_path):
                    try:
                        with open(metadata_path, "r", encoding="utf-8") as f:
                            metadata = json.load(f)
                        
                        metadata["source"] = source
                        metadata["path"] = plugin_path
                        metadata["enabled"] = metadata.get("enabled", True)
                        
                        spec = importlib.util.spec_from_file_location(
                            f"plugins.{source}.{plugin_name}.main", 
                            main_path
                        )
                        plugin_module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(plugin_module)
                        
                        if hasattr(plugin_module, "Plugin"):
                            plugin_instance = plugin_module.Plugin()
                            
                            self.loaded_plugins[plugin_name] = plugin_instance
                            self.plugin_metadata[plugin_name] = metadata
                            
                            logger.info(f"加载{source}插件成功: {metadata.get('name', plugin_name)} v{metadata.get('version', '1.0.0')}")
                        else:
                            logger.error(f"插件 {plugin_name} 缺少Plugin类")
                    except Exception as e:
                        logger.error(f"加载插件 {plugin_name} 失败: {e}", exc_info=True)
    
    def import_plugin(self, plugin_path: str) -> bool:
        """导入外部插件（支持目录或zip压缩包）"""
        try:
            if os.path.isdir(plugin_path):
                return self.install_plugin(plugin_path)
            elif os.path.isfile(plugin_path) and plugin_path.endswith(".zip"):
                temp_dir = os.path.join(Config.APP_DATA_DIR, "temp", f"plugin_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
                os.makedirs(temp_dir, exist_ok=True)
                
                with zipfile.ZipFile(plugin_path, 'r') as zip_ref:
                    zip_ref.extractall(temp_dir)
                
                extracted_items = os.listdir(temp_dir)
                if len(extracted_items) == 1 and os.path.isdir(os.path.join(temp_dir, extracted_items[0])):
                    plugin_dir = os.path.join(temp_dir, extracted_items[0])
                    result = self.install_plugin(plugin_dir)
                    shutil.rmtree(temp_dir)
                    return result
                else:
                    logger.error("压缩包格式不正确，应该只包含一个插件目录")
                    shutil.rmtree(temp_dir)
                    return False
            else:
                logger.error("插件格式不正确，应该是目录或zip压缩包")
                return False
        except Exception as e:
            logger.error(f"导入插件失败: {e}", exc_info=True)
            return False
    
    def install_plugin(self, plugin_dir: str) -> bool:
        """安装插件到外部插件目录"""
        metadata_path = os.path.join(plugin_dir, "metadata.json")
        if not os.path.exists(metadata_path):
            logger.error("插件缺少metadata.json文件")
            return False
        
        with open(metadata_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)
        
        plugin_name = metadata.get("name", os.path.basename(plugin_dir))
        plugin_name = plugin_name.replace(" ", "_").replace("/", "_").replace("\\", "_")
        
        target_path = os.path.join(self.external_plugins_dir, plugin_name)
        
        if os.path.exists(target_path):
            logger.warning(f"插件 {plugin_name} 已存在，将覆盖现有版本")
            shutil.rmtree(target_path)
        
        shutil.copytree(plugin_dir, target_path)
        self.load_all_plugins()
        
        logger.info(f"插件 {plugin_name} 安装成功")
        return True
    
    def uninstall_plugin(self, plugin_name: str) -> bool:
        """卸载外部插件（内置插件不能卸载）"""
        if plugin_name not in self.plugin_metadata:
            logger.error(f"插件 {plugin_name} 不存在")
            return False
        
        plugin_info = self.plugin_metadata[plugin_name]
        if plugin_info["source"] == "builtin":
            logger.error("不能卸载内置插件")
            return False
        
        plugin_path = plugin_info["path"]
        if os.path.exists(plugin_path):
            shutil.rmtree(plugin_path)
        
        self.load_all_plugins()
        
        logger.info(f"插件 {plugin_name} 卸载成功")
        return True
    
    def get_plugin(self, plugin_name: str) -> Optional[Any]:
        """获取插件实例"""
        return self.loaded_plugins.get(plugin_name)
    
    def get_all_plugins(self) -> List[Dict]:
        """获取所有已加载的插件"""
        return list(self.plugin_metadata.values())
    
    def enable_plugin(self, plugin_name: str) -> bool:
        """启用插件"""
        if plugin_name in self.loaded_plugins:
            try:
                plugin = self.loaded_plugins[plugin_name]
                if hasattr(plugin, "enable"):
                    plugin.enable()
                if plugin_name in self.plugin_metadata:
                    self.plugin_metadata[plugin_name]["enabled"] = True
                    self.save_plugin_metadata(plugin_name)
                logger.info(f"启用插件成功: {plugin_name}")
                return True
            except Exception as e:
                logger.error(f"启用插件 {plugin_name} 失败: {e}", exc_info=True)
        return False
    
    def disable_plugin(self, plugin_name: str) -> bool:
        """禁用插件"""
        if plugin_name in self.loaded_plugins:
            try:
                plugin = self.loaded_plugins[plugin_name]
                if hasattr(plugin, "disable"):
                    plugin.disable()
                if plugin_name in self.plugin_metadata:
                    self.plugin_metadata[plugin_name]["enabled"] = False
                    self.save_plugin_metadata(plugin_name)
                logger.info(f"禁用插件成功: {plugin_name}")
                return True
            except Exception as e:
                logger.error(f"禁用插件 {plugin_name} 失败: {e}", exc_info=True)
        return False
    
    def save_plugin_metadata(self, plugin_name: str):
        """保存插件元数据到文件"""
        if plugin_name not in self.plugin_metadata:
            return
        
        plugin_info = self.plugin_metadata[plugin_name]
        metadata_path = os.path.join(plugin_info["path"], "metadata.json")
        
        try:
            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(plugin_info, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存插件元数据失败: {e}", exc_info=True)
    
    def get_enabled_plugins(self) -> List[Dict]:
        """获取所有已启用的插件"""
        return [
            self.plugin_metadata[name]
            for name in self.plugin_metadata
            if self.plugin_metadata[name].get("enabled", True)
        ]
    
    def get_builtin_plugins(self) -> List[Dict]:
        """获取所有内置插件"""
        return [
            self.plugin_metadata[name]
            for name in self.plugin_metadata
            if self.plugin_metadata[name].get("source") == "builtin"
        ]
    
    def get_external_plugins(self) -> List[Dict]:
        """获取所有外部插件"""
        return [
            self.plugin_metadata[name]
            for name in self.plugin_metadata
            if self.plugin_metadata[name].get("source") == "external"
        ]
    
    def search_plugins(self, keyword: str) -> List[Dict]:
        """搜索插件"""
        keyword = keyword.lower()
        results = []
        for name, metadata in self.plugin_metadata.items():
            if (keyword in name.lower() or 
                keyword in metadata.get("name", "").lower() or
                keyword in metadata.get("description", "").lower() or
                keyword in metadata.get("author", "").lower()):
                results.append(metadata)
        return results
    
    def filter_by_category(self, category: str) -> List[Dict]:
        """按分类筛选插件"""
        if category == "所有":
            return self.get_all_plugins()
        
        return [
            self.plugin_metadata[name]
            for name in self.plugin_metadata
            if self.plugin_metadata[name].get("category") == category
        ]


_plugin_manager_instance: Optional[PluginManager] = None


def get_plugin_manager() -> PluginManager:
    """获取插件管理器实例"""
    global _plugin_manager_instance
    
    if _plugin_manager_instance is None:
        _plugin_manager_instance = PluginManager()
    
    return _plugin_manager_instance

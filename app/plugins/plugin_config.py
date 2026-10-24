"""
插件配置
定义插件的元数据和配置
"""

import os
import json
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum


import logging
logger = logging.getLogger("AI短剧编辑器.plugins.plugin_config")

class PluginStatus(Enum):
    """插件状态"""
    DISABLED = "disabled"
    ENABLED = "enabled"
    ERROR = "error"
    LOADING = "loading"


@dataclass
class PluginMetadata:
    """插件元数据"""
    id: str
    name: str
    version: str
    description: str
    author: str
    type: str  # effect, transition, filter, subtitle, audio
    category: str  # counterattack, emotion, suspense, selling, general
    icon: str = ""
    preview_image: str = ""
    min_version: str = "1.0.0"
    dependencies: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    status: PluginStatus = PluginStatus.DISABLED
    config: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "type": self.type,
            "category": self.category,
            "icon": self.icon,
            "preview_image": self.preview_image,
            "min_version": self.min_version,
            "dependencies": self.dependencies,
            "tags": self.tags,
            "status": self.status.value,
            "config": self.config
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'PluginMetadata':
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            version=data.get("version", "1.0.0"),
            description=data.get("description", ""),
            author=data.get("author", ""),
            type=data.get("type", "effect"),
            category=data.get("category", "general"),
            icon=data.get("icon", ""),
            preview_image=data.get("preview_image", ""),
            min_version=data.get("min_version", "1.0.0"),
            dependencies=data.get("dependencies", []),
            tags=data.get("tags", []),
            status= PluginStatus(data.get("status", "disabled")),
            config=data.get("config", {})
        )


class PluginConfig:
    """插件配置管理器"""
    
    def __init__(self, config_file: str = "plugins_config.json"):
        self.config_file = config_file
        self._config: Dict[str, Dict] = {}
        self._load_config()
    
    def _load_config(self):
        """加载配置"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self._config = json.load(f)
        except Exception as e:
            logger.error(f'加载插件配置失败: {e}')
    
    def _save_config(self):
        """保存配置"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self._config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f'保存插件配置失败: {e}')
    
    def get_plugin_config(self, plugin_id: str) -> Dict:
        """获取插件配置"""
        return self._config.get(plugin_id, {})
    
    def set_plugin_config(self, plugin_id: str, config: Dict):
        """设置插件配置"""
        self._config[plugin_id] = config
        self._save_config()
    
    def enable_plugin(self, plugin_id: str):
        """启用插件"""
        if plugin_id in self._config:
            self._config[plugin_id]["enabled"] = True
            self._save_config()
    
    def disable_plugin(self, plugin_id: str):
        """禁用插件"""
        if plugin_id in self._config:
            self._config[plugin_id]["enabled"] = False
            self._save_config()
    
    def get_enabled_plugins(self) -> List[str]:
        """获取启用的插件列表"""
        return [
            plugin_id for plugin_id, config in self._config.items()
            if config.get("enabled", False)
        ]
    
    def get_all_plugins(self) -> Dict[str, PluginMetadata]:
        """获取所有插件"""
        plugins = {}
        for plugin_id, config in self._config.items():
            plugins[plugin_id] = PluginMetadata.from_dict(config)
        return plugins

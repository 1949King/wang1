"""
积木加载器（BlockLoader）
=======================
管理积木的生命周期：加载、卸载、启用、禁用
"""

import os
import importlib.util
import json
from typing import Dict, List, Optional, Type, Any
from dataclasses import dataclass, field
from pathlib import Path
import threading

from .base_block import LegoBlock, BlockMeta, BlockState


import logging
logger = logging.getLogger("AI短剧编辑器.modules.lego.block_loader")

@dataclass
class BlockInfo:
    name: str
    version: str
    author: str
    description: str
    category: str
    tags: List[str]
    icon: str
    file_path: str
    enabled: bool = True
    installed_at: float = 0.0
    last_used: float = 0.0
    use_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "author": self.author,
            "description": self.description,
            "category": self.category,
            "tags": self.tags,
            "icon": self.icon,
            "file_path": self.file_path,
            "enabled": self.enabled,
            "installed_at": self.installed_at,
            "last_used": self.last_used,
            "use_count": self.use_count
        }


class BlockRegistry:
    """
    积木注册表 - 存储所有已注册的积木类
    """
    
    _instance: Optional['BlockRegistry'] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._blocks: Dict[str, Type[LegoBlock]] = {}
        self._block_infos: Dict[str, BlockInfo] = {}
        self._instances: Dict[str, LegoBlock] = {}
        self._lock = threading.Lock()
    
    def register(self, block_class: Type[LegoBlock]) -> bool:
        """注册积木类"""
        try:
            temp_instance = block_class()
            meta = temp_instance.info()
            name = meta.name
            
            with self._lock:
                self._blocks[name] = block_class
            
            return True
        except Exception as e:
            logger.error(f'注册积木失败: {e}')
            return False
    
    def unregister(self, name: str) -> bool:
        """注销积木"""
        with self._lock:
            if name in self._blocks:
                del self._blocks[name]
                return True
            return False
    
    def get_block_class(self, name: str) -> Optional[Type[LegoBlock]]:
        """获取积木类"""
        return self._blocks.get(name)
    
    def get_all_blocks(self) -> Dict[str, Type[LegoBlock]]:
        """获取所有积木类"""
        return self._blocks.copy()
    
    def create_instance(self, name: str) -> Optional[LegoBlock]:
        """创建积木实例"""
        block_class = self.get_block_class(name)
        if block_class:
            return block_class()
        return None
    
    def list_blocks(self) -> List[str]:
        """列出所有积木名称"""
        return list(self._blocks.keys())
    
    def has_block(self, name: str) -> bool:
        """检查积木是否存在"""
        return name in self._blocks
    
    @classmethod
    def get_instance(cls) -> 'BlockRegistry':
        return cls()


class BlockLoader:
    """
    积木加载器 - 负责从文件系统加载积木
    """
    
    def __init__(self, blocks_dir: str = None):
        self._registry = BlockRegistry.get_instance()
        self._blocks_dir = blocks_dir or os.path.join(os.path.dirname(__file__), "blocks")
        self._block_infos: Dict[str, BlockInfo] = {}
        self._lock = threading.Lock()
        self._ensure_blocks_dir()
    
    def _ensure_blocks_dir(self):
        """确保积木目录存在"""
        os.makedirs(self._blocks_dir, exist_ok=True)
    
    def scan_blocks(self) -> List[str]:
        """扫描积木目录，返回发现的积木列表"""
        discovered = []
        
        if not os.path.exists(self._blocks_dir):
            return discovered
        
        for file in os.listdir(self._blocks_dir):
            if file.endswith(".py") and not file.startswith("_"):
                file_path = os.path.join(self._blocks_dir, file)
                try:
                    info = self._extract_block_info(file_path)
                    if info:
                        discovered.append(info.name)
                        with self._lock:
                            self._block_infos[info.name] = info
                except Exception as e:
                    logger.error(f'扫描积木失败 {file}: {e}')
        
        return discovered
    
    def _extract_block_info(self, file_path: str) -> Optional[BlockInfo]:
        """从文件提取积木信息"""
        try:
            spec = importlib.util.spec_from_file_location("block_module", file_path)
            if not spec or not spec.loader:
                return None
            
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type) and 
                    issubclass(attr, LegoBlock) and 
                    attr != LegoBlock):
                    
                    temp_instance = attr()
                    meta = temp_instance.info()
                    
                    return BlockInfo(
                        name=meta.name,
                        version=meta.version,
                        author=meta.author,
                        description=meta.description,
                        category=meta.category,
                        tags=meta.tags,
                        icon=meta.icon,
                        file_path=file_path
                    )
            
            return None
        except Exception as e:
            logger.error(f'提取积木信息失败: {e}')
            return None
    
    def load_block(self, name: str) -> Optional[Type[LegoBlock]]:
        """加载指定积木"""
        info = self._block_infos.get(name)
        if not info:
            self.scan_blocks()
            info = self._block_infos.get(name)
        
        if not info or not os.path.exists(info.file_path):
            return None
        
        try:
            spec = importlib.util.spec_from_file_location(f"block_{name}", info.file_path)
            if not spec or not spec.loader:
                return None
            
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type) and 
                    issubclass(attr, LegoBlock) and 
                    attr != LegoBlock):
                    self._registry.register(attr)
                    return attr
            
            return None
        except Exception as e:
            logger.error(f'加载积木失败 {name}: {e}')
            return None
    
    def load_all_blocks(self) -> Dict[str, Type[LegoBlock]]:
        """加载所有积木"""
        self.scan_blocks()
        loaded = {}
        for name in self._block_infos:
            block_class = self.load_block(name)
            if block_class:
                loaded[name] = block_class
        return loaded
    
    def unload_block(self, name: str) -> bool:
        """卸载积木"""
        return self._registry.unregister(name)
    
    def install_block(self, name: str, code: str) -> bool:
        """安装新积木"""
        try:
            file_path = os.path.join(self._blocks_dir, f"{name}.py")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(code)
            
            info = self._extract_block_info(file_path)
            if info:
                with self._lock:
                    self._block_infos[name] = info
                return self.load_block(name) is not None
            
            return False
        except Exception as e:
            logger.error(f'安装积木失败: {e}')
            return False
    
    def uninstall_block(self, name: str) -> bool:
        """卸载积木（删除文件）"""
        try:
            info = self._block_infos.get(name)
            if info and os.path.exists(info.file_path):
                os.remove(info.file_path)
            
            with self._lock:
                if name in self._block_infos:
                    del self._block_infos[name]
            
            return self.unload_block(name)
        except Exception as e:
            logger.error(f'卸载积木失败: {e}')
            return False
    
    def get_block_info(self, name: str) -> Optional[BlockInfo]:
        """获取积木信息"""
        return self._block_infos.get(name)
    
    def get_all_block_infos(self) -> Dict[str, BlockInfo]:
        """获取所有积木信息"""
        return self._block_infos.copy()
    
    def enable_block(self, name: str) -> bool:
        """启用积木"""
        info = self._block_infos.get(name)
        if info:
            info.enabled = True
            return True
        return False
    
    def disable_block(self, name: str) -> bool:
        """禁用积木"""
        info = self._block_infos.get(name)
        if info:
            info.enabled = False
            return True
        return False
    
    def create_block_instance(self, name: str) -> Optional[LegoBlock]:
        """创建积木实例"""
        return self._registry.create_instance(name)
    
    def save_registry(self, file_path: str = None):
        """保存注册表到文件"""
        file_path = file_path or os.path.join(self._blocks_dir, "registry.json")
        data = {
            name: info.to_dict() 
            for name, info in self._block_infos.items()
        }
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def load_registry(self, file_path: str = None):
        """从文件加载注册表"""
        file_path = file_path or os.path.join(self._blocks_dir, "registry.json")
        if not os.path.exists(file_path):
            return
        
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        for name, info_dict in data.items():
            self._block_infos[name] = BlockInfo(
                name=info_dict["name"],
                version=info_dict["version"],
                author=info_dict["author"],
                description=info_dict["description"],
                category=info_dict["category"],
                tags=info_dict["tags"],
                icon=info_dict["icon"],
                file_path=info_dict["file_path"],
                enabled=info_dict.get("enabled", True),
                installed_at=info_dict.get("installed_at", 0),
                last_used=info_dict.get("last_used", 0),
                use_count=info_dict.get("use_count", 0)
            )


block_registry = BlockRegistry.get_instance()

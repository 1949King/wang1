"""
插件商店模块 (PluginStore)
==========================
支持插件和 Skill 商品的浏览、安装、管理
"""

import os
import json
import shutil
import zipfile
import time
import threading
import requests
from typing import Optional, Dict, List, Any, Callable, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class ItemType(Enum):
    """商品类型"""
    PLUGIN = "plugin"
    SKILL = "skill"


class ItemCategory(Enum):
    """商品分类"""
    VIDEO_PROCESSING = "视频处理"
    AI_TOOLS = "AI工具"
    EXPORT_TOOLS = "导出工具"
    OPERATION_TOOLS = "运营工具"
    SUBTITLE_TOOLS = "字幕工具"
    AUDIO_TOOLS = "音频工具"
    EFFECT_TOOLS = "特效工具"
    OTHER = "其他"


@dataclass
class StoreItem:
    """商店商品"""
    id: str
    name: str
    type: ItemType
    category: ItemCategory
    version: str
    author: str
    description: str
    icon: str = ""
    price: float = 0.0
    is_free: bool = True
    rating: float = 0.0
    downloads: int = 0
    tags: List[str] = field(default_factory=list)
    screenshots: List[str] = field(default_factory=list)
    changelog: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    min_version: str = "1.0.0"
    created_at: str = ""
    updated_at: str = ""
    download_url: str = ""
    local_path: str = ""
    is_installed: bool = False
    is_official: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type.value,
            "category": self.category.value,
            "version": self.version,
            "author": self.author,
            "description": self.description,
            "icon": self.icon,
            "price": self.price,
            "is_free": self.is_free,
            "rating": self.rating,
            "downloads": self.downloads,
            "tags": self.tags,
            "min_version": self.min_version,
            "download_url": self.download_url,
            "is_installed": self.is_installed,
            "is_official": self.is_official
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'StoreItem':
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            type=ItemType(data.get("type", "plugin")),
            category=ItemCategory(data.get("category", "其他")),
            version=data.get("version", "1.0.0"),
            author=data.get("author", ""),
            description=data.get("description", ""),
            icon=data.get("icon", ""),
            price=data.get("price", 0.0),
            is_free=data.get("is_free", True),
            rating=data.get("rating", 0.0),
            downloads=data.get("downloads", 0),
            tags=data.get("tags", []),
            min_version=data.get("min_version", "1.0.0"),
            download_url=data.get("download_url", ""),
            is_installed=data.get("is_installed", False),
            is_official=data.get("is_official", False)
        )


class PluginStore:
    """插件商店"""
    
    _instance: Optional['PluginStore'] = None
    _lock = threading.Lock()
    
    STORE_URL = "https://store.aishortdrama.com/api"
    
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
        
        self._items: Dict[str, StoreItem] = {}
        self._installed_items: Dict[str, StoreItem] = {}
        
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        self._data_dir = os.path.join(base_dir, "data", "store")
        self._plugins_dir = os.path.join(base_dir, "plugins", "external")
        self._skills_dir = os.path.join(base_dir, "skills", "custom")
        
        os.makedirs(self._data_dir, exist_ok=True)
        os.makedirs(self._plugins_dir, exist_ok=True)
        os.makedirs(self._skills_dir, exist_ok=True)
        
        self._load_local_items()
        self._load_installed_items()
        
        # 初始化官方商品
        init_official_items(self)
    
    def _load_local_items(self):
        """加载本地商品数据"""
        items_file = os.path.join(self._data_dir, "items.json")
        if os.path.exists(items_file):
            try:
                with open(items_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for item_data in data.get("items", []):
                    item = StoreItem.from_dict(item_data)
                    self._items[item.id] = item
            except Exception as e:
                logger.warning(f"加载商品数据失败: {e}")
    
    def _save_local_items(self):
        """保存本地商品数据"""
        items_file = os.path.join(self._data_dir, "items.json")
        data = {
            "items": [item.to_dict() for item in self._items.values()],
            "updated_at": datetime.now().isoformat()
        }
        with open(items_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def _load_installed_items(self):
        """加载已安装商品"""
        installed_file = os.path.join(self._data_dir, "installed.json")
        if os.path.exists(installed_file):
            try:
                with open(installed_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for item_data in data.get("items", []):
                    item = StoreItem.from_dict(item_data)
                    item.is_installed = True
                    self._installed_items[item.id] = item
                    if item.id in self._items:
                        self._items[item.id].is_installed = True
            except Exception as e:
                logger.warning(f"加载已安装商品失败: {e}")
    
    def _save_installed_items(self):
        """保存已安装商品"""
        installed_file = os.path.join(self._data_dir, "installed.json")
        data = {
            "items": [item.to_dict() for item in self._installed_items.values()],
            "updated_at": datetime.now().isoformat()
        }
        with open(installed_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def fetch_store_items(self, force: bool = False) -> List[StoreItem]:
        """从商店获取商品列表"""
        if not force and self._items:
            return list(self._items.values())
        
        try:
            response = requests.get(
                f"{self.STORE_URL}/items",
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                for item_data in data.get("items", []):
                    item = StoreItem.from_dict(item_data)
                    if item.id in self._installed_items:
                        item.is_installed = True
                    self._items[item.id] = item
                self._save_local_items()
        except Exception as e:
            logger.warning(f"获取商店商品失败: {e}")
        
        return list(self._items.values())
    
    def get_items(
        self,
        item_type: Optional[ItemType] = None,
        category: Optional[ItemCategory] = None,
        search: str = "",
        installed_only: bool = False
    ) -> List[StoreItem]:
        """获取商品列表"""
        items = list(self._items.values())
        
        if installed_only:
            items = [item for item in items if item.is_installed]
        
        if item_type:
            items = [item for item in items if item.type == item_type]
        
        if category:
            items = [item for item in items if item.category == category]
        
        if search:
            search_lower = search.lower()
            items = [
                item for item in items
                if search_lower in item.name.lower()
                or search_lower in item.description.lower()
                or any(search_lower in tag.lower() for tag in item.tags)
            ]
        
        return items
    
    def get_item(self, item_id: str) -> Optional[StoreItem]:
        """获取单个商品"""
        return self._items.get(item_id)
    
    def install_item(
        self,
        item_id: str,
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> Tuple[bool, str]:
        """安装商品"""
        item = self._items.get(item_id)
        if not item:
            return False, "商品不存在"
        
        if item.is_installed:
            return False, "已安装"
        
        try:
            if progress_callback:
                progress_callback(10, "准备下载...")
            
            if item.download_url:
                response = requests.get(item.download_url, stream=True, timeout=300)
                
                if response.status_code != 200:
                    return False, "下载失败"
                
                total_size = int(response.headers.get('content-length', 0))
                downloaded = 0
                
                temp_file = os.path.join(self._data_dir, f"{item_id}.zip")
                
                with open(temp_file, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size and progress_callback:
                            progress = int(10 + (downloaded / total_size) * 60)
                            progress_callback(progress, "下载中...")
                
                if progress_callback:
                    progress_callback(70, "解压安装...")
                
                target_dir = self._plugins_dir if item.type == ItemType.PLUGIN else self._skills_dir
                install_dir = os.path.join(target_dir, item.id)
                
                with zipfile.ZipFile(temp_file, 'r') as zip_ref:
                    zip_ref.extractall(install_dir)
                
                os.remove(temp_file)
            else:
                target_dir = self._plugins_dir if item.type == ItemType.PLUGIN else self._skills_dir
                install_dir = os.path.join(target_dir, item.id)
                os.makedirs(install_dir, exist_ok=True)
                
                metadata = {
                    "id": item.id,
                    "name": item.name,
                    "version": item.version,
                    "author": item.author,
                    "description": item.description,
                    "installed_at": datetime.now().isoformat()
                }
                
                with open(os.path.join(install_dir, "metadata.json"), 'w', encoding='utf-8') as f:
                    json.dump(metadata, f, ensure_ascii=False, indent=2)
            
            if progress_callback:
                progress_callback(90, "完成安装...")
            
            item.is_installed = True
            item.local_path = install_dir
            self._installed_items[item_id] = item
            self._save_installed_items()
            
            if progress_callback:
                progress_callback(100, "安装完成")
            
            return True, "安装成功"
            
        except Exception as e:
            logger.error(f"安装商品失败: {e}")
            return False, f"安装失败: {str(e)}"
    
    def uninstall_item(self, item_id: str) -> Tuple[bool, str]:
        """卸载商品"""
        if item_id not in self._installed_items:
            return False, "未安装"
        
        item = self._installed_items[item_id]
        
        try:
            if item.local_path and os.path.exists(item.local_path):
                shutil.rmtree(item.local_path)
            
            del self._installed_items[item_id]
            
            if item_id in self._items:
                self._items[item_id].is_installed = False
            
            self._save_installed_items()
            
            return True, "卸载成功"
            
        except Exception as e:
            logger.error(f"卸载商品失败: {e}")
            return False, f"卸载失败: {str(e)}"
    
    def import_item_from_file(self, file_path: str, item_type: ItemType) -> Tuple[bool, str]:
        """从文件导入商品"""
        try:
            if not os.path.exists(file_path):
                return False, "文件不存在"
            
            target_dir = self._plugins_dir if item_type == ItemType.PLUGIN else self._skills_dir
            
            if file_path.endswith('.zip'):
                with zipfile.ZipFile(file_path, 'r') as zip_ref:
                    temp_dir = os.path.join(self._data_dir, "temp_import")
                    os.makedirs(temp_dir, exist_ok=True)
                    zip_ref.extractall(temp_dir)
                    
                    extracted = os.listdir(temp_dir)
                    if len(extracted) == 1:
                        extracted_dir = os.path.join(temp_dir, extracted[0])
                    else:
                        extracted_dir = temp_dir
                    
                    metadata_file = os.path.join(extracted_dir, "metadata.json")
                    if os.path.exists(metadata_file):
                        with open(metadata_file, 'r', encoding='utf-8') as f:
                            metadata = json.load(f)
                        
                        item_id = metadata.get("id", f"imported_{int(time.time())}")
                        target_path = os.path.join(target_dir, item_id)
                        
                        if os.path.exists(target_path):
                            shutil.rmtree(target_path)
                        
                        shutil.move(extracted_dir, target_path)
                        
                        item = StoreItem(
                            id=item_id,
                            name=metadata.get("name", "导入商品"),
                            type=item_type,
                            category=ItemCategory.OTHER,
                            version=metadata.get("version", "1.0.0"),
                            author=metadata.get("author", "本地导入"),
                            description=metadata.get("description", ""),
                            local_path=target_path,
                            is_installed=True
                        )
                        
                        self._items[item_id] = item
                        self._installed_items[item_id] = item
                        self._save_local_items()
                        self._save_installed_items()
                        
                        return True, f"导入成功: {item.name}"
                    else:
                        shutil.rmtree(temp_dir)
                        return False, "缺少 metadata.json 文件"
            else:
                return False, "不支持的文件格式"
                
        except Exception as e:
            logger.error(f"导入商品失败: {e}")
            return False, f"导入失败: {str(e)}"
    
    def get_categories(self) -> List[ItemCategory]:
        """获取所有分类"""
        return list(ItemCategory)
    
    def rate_item(self, item_id: str, rating: float, comment: str = "") -> bool:
        """评价商品"""
        if item_id not in self._items:
            return False
        
        ratings_file = os.path.join(self._data_dir, "ratings.json")
        ratings = {}
        
        if os.path.exists(ratings_file):
            with open(ratings_file, 'r', encoding='utf-8') as f:
                ratings = json.load(f)
        
        if item_id not in ratings:
            ratings[item_id] = []
        
        ratings[item_id].append({
            "rating": rating,
            "comment": comment,
            "timestamp": datetime.now().isoformat()
        })
        
        with open(ratings_file, 'w', encoding='utf-8') as f:
            json.dump(ratings, f, ensure_ascii=False, indent=2)
        
        return True


OFFICIAL_ITEMS = [
    StoreItem(
        id="auto-clip",
        name="智能剪辑",
        type=ItemType.PLUGIN,
        category=ItemCategory.VIDEO_PROCESSING,
        version="1.0.0",
        author="官方",
        description="AI 驱动的智能剪辑插件，自动识别精彩片段",
        is_free=True,
        is_official=True,
        tags=["AI", "剪辑", "自动化"]
    ),
    StoreItem(
        id="subtitle-gen",
        name="字幕生成",
        type=ItemType.SKILL,
        category=ItemCategory.SUBTITLE_TOOLS,
        version="1.0.0",
        author="官方",
        description="自动生成视频字幕，支持多语言",
        is_free=True,
        is_official=True,
        tags=["字幕", "AI", "多语言"]
    ),
    StoreItem(
        id="drama-remix",
        name="短剧二创",
        type=ItemType.SKILL,
        category=ItemCategory.VIDEO_PROCESSING,
        version="1.0.0",
        author="官方",
        description="短剧漫剧二创剪辑，自动生成二创内容",
        is_free=True,
        is_official=True,
        tags=["短剧", "二创", "漫剧"]
    ),
    StoreItem(
        id="matrix-publish",
        name="矩阵发布",
        type=ItemType.SKILL,
        category=ItemCategory.OPERATION_TOOLS,
        version="1.0.0",
        author="官方",
        description="多平台矩阵发布，一键分发到多个账号",
        is_free=True,
        is_official=True,
        tags=["运营", "发布", "矩阵"]
    ),
    StoreItem(
        id="drama-finder",
        name="短剧筛选",
        type=ItemType.SKILL,
        category=ItemCategory.OPERATION_TOOLS,
        version="1.0.0",
        author="官方",
        description="智能筛选热门短剧，分析热度与佣金",
        is_free=True,
        is_official=True,
        tags=["短剧", "筛选", "数据分析"]
    ),
]


def init_official_items(store):
    """初始化官方商品"""
    for item in OFFICIAL_ITEMS:
        if item.id not in store._items:
            store._items[item.id] = item
    store._save_local_items()


plugin_store = PluginStore()

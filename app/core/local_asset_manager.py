"""
本地素材管理系统 (LocalAssetManager)
==============================
实现本地素材的导入、分类、搜索和管理
"""

import os
import json
import time
import hashlib
import shutil
from typing import Optional, Dict, List, Any, Tuple
from dataclasses import dataclass, field
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class AssetInfo:
    """素材信息"""
    id: str
    name: str
    type: str
    path: str
    size: int
    duration: float
    resolution: str
    format: str
    tags: List[str]
    category: str
    create_time: str
    update_time: str
    used: bool = False
    project_id: Optional[str] = None
    last_used_time: Optional[str] = None
    thumbnail: Optional[str] = None
    description: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "path": self.path,
            "size": self.size,
            "duration": self.duration,
            "resolution": self.resolution,
            "format": self.format,
            "tags": self.tags,
            "category": self.category,
            "create_time": self.create_time,
            "update_time": self.update_time,
            "used": self.used,
            "project_id": self.project_id,
            "last_used_time": self.last_used_time,
            "thumbnail": self.thumbnail,
            "description": self.description,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AssetInfo':
        """从字典创建"""
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            type=data.get("type", ""),
            path=data.get("path", ""),
            size=data.get("size", 0),
            duration=data.get("duration", 0.0),
            resolution=data.get("resolution", ""),
            format=data.get("format", ""),
            tags=data.get("tags", []),
            category=data.get("category", ""),
            create_time=data.get("create_time", ""),
            update_time=data.get("update_time", ""),
            used=data.get("used", False),
            project_id=data.get("project_id"),
            last_used_time=data.get("last_used_time"),
            thumbnail=data.get("thumbnail"),
            description=data.get("description", ""),
            metadata=data.get("metadata", {})
        )


class LocalAssetManager:
    """本地素材管理器"""
    
    _instance: Optional['LocalAssetManager'] = None
    
    ASSET_TYPES = {
        "video": {"extensions": [".mp4", ".mov", ".avi", ".wmv", ".mkv", ".webm", ".flv"], "name": "视频"},
        "audio": {"extensions": [".mp3", ".wav", ".aac", ".flac", ".ogg", ".m4a"], "name": "音频"},
        "image": {"extensions": [".jpg", ".jpeg", ".png", ".gif", ".svg", ".bmp", ".webp"], "name": "图片"},
        "subtitle": {"extensions": [".srt", ".ass", ".vtt", ".sbv"], "name": "字幕"},
        "template": {"extensions": [".json", ".prproj", ".aep", ".fcpxml"], "name": "模板"},
        "effect": {"extensions": [".json"], "name": "特效"},
        "transition": {"extensions": [".json"], "name": "转场"},
        "sticker": {"extensions": [".png", ".gif", ".webp", ".svg"], "name": "贴纸"}
    }
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        
        # 初始化素材库路径
        self._base_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "data", "assets"
        )
        self._metadata_file = os.path.join(self._base_dir, "metadata.json")
        
        # 创建目录结构
        self._create_directory_structure()
        
        # 加载素材元数据
        self._assets: Dict[str, AssetInfo] = {}
        self._load_metadata()
        
        # 索引
        self._index_by_type: Dict[str, List[str]] = {}
        self._index_by_category: Dict[str, List[str]] = {}
        self._index_by_tag: Dict[str, List[str]] = {}
        self._index_by_project: Dict[str, List[str]] = {}
        self._build_indexes()
        
        # 最近使用的素材ID列表（按使用时间倒序）
        self._recently_used: List[str] = []
        self._update_recently_used()
    
    def _update_recently_used(self):
        """更新最近使用的素材列表"""
        # 筛选有使用时间的素材
        used_assets = [(asset.last_used_time, asset_id) for asset_id, asset in self._assets.items() if asset.last_used_time]
        # 按使用时间倒序排序
        used_assets.sort(key=lambda x: x[0], reverse=True)
        # 提取前20个最近使用的素材ID
        self._recently_used = [asset_id for _, asset_id in used_assets[:20]]
    
    def _create_directory_structure(self):
        """创建目录结构"""
        # 基础目录
        os.makedirs(self._base_dir, exist_ok=True)
        
        # 分类目录
        for asset_type in self.ASSET_TYPES:
            type_dir = os.path.join(self._base_dir, asset_type)
            os.makedirs(type_dir, exist_ok=True)
        
        # 缩略图目录
        thumbnail_dir = os.path.join(self._base_dir, "thumbnails")
        os.makedirs(thumbnail_dir, exist_ok=True)
    
    def _load_metadata(self):
        """加载素材元数据"""
        if os.path.exists(self._metadata_file):
            try:
                with open(self._metadata_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                for asset_id, asset_data in data.items():
                    try:
                        asset = AssetInfo.from_dict(asset_data)
                        # 验证素材是否存在
                        if os.path.exists(asset.path):
                            self._assets[asset_id] = asset
                        else:
                            logger.warning(f"素材不存在: {asset.path}")
                    except Exception as e:
                        logger.error(f"加载素材元数据失败: {e}")
            except Exception as e:
                logger.error(f"加载元数据文件失败: {e}")
    
    def _save_metadata(self):
        """保存素材元数据"""
        try:
            data = {}
            for asset_id, asset in self._assets.items():
                data[asset_id] = asset.to_dict()
            
            with open(self._metadata_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存元数据失败: {e}")
    
    def _build_indexes(self):
        """构建索引"""
        self._index_by_type = {}
        self._index_by_category = {}
        self._index_by_tag = {}
        self._index_by_project = {}
        
        for asset_id, asset in self._assets.items():
            # 按类型索引
            if asset.type not in self._index_by_type:
                self._index_by_type[asset.type] = []
            self._index_by_type[asset.type].append(asset_id)
            
            # 按分类索引
            if asset.category not in self._index_by_category:
                self._index_by_category[asset.category] = []
            self._index_by_category[asset.category].append(asset_id)
            
            # 按标签索引
            for tag in asset.tags:
                if tag not in self._index_by_tag:
                    self._index_by_tag[tag] = []
                self._index_by_tag[tag].append(asset_id)
            
            # 按项目索引
            if asset.project_id:
                if asset.project_id not in self._index_by_project:
                    self._index_by_project[asset.project_id] = []
                self._index_by_project[asset.project_id].append(asset_id)
    
    def _get_asset_type(self, file_path: str) -> Optional[str]:
        """获取素材类型"""
        ext = os.path.splitext(file_path)[1].lower()
        for asset_type, info in self.ASSET_TYPES.items():
            if ext in info["extensions"]:
                return asset_type
        return None
    
    def _generate_asset_id(self, file_path: str) -> str:
        """生成素材ID"""
        # 使用文件路径和修改时间生成唯一ID
        mtime = os.path.getmtime(file_path)
        data = f"{file_path}_{mtime}"
        return hashlib.md5(data.encode('utf-8')).hexdigest()
    
    def _extract_metadata(self, file_path: str, asset_type: str) -> Dict[str, Any]:
        """提取素材元数据"""
        metadata = {
            "size": os.path.getsize(file_path),
            "format": os.path.splitext(file_path)[1].lstrip('.'),
            "duration": 0.0,
            "resolution": ""
        }
        
        if asset_type == "video":
            try:
                import cv2
                cap = cv2.VideoCapture(file_path)
                if cap.isOpened():
                    metadata["duration"] = cap.get(cv2.CAP_PROP_FRAME_COUNT) / cap.get(cv2.CAP_PROP_FPS)
                    metadata["resolution"] = f"{int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}"
                    cap.release()
            except ImportError as e:
                logger.debug(f"[LocalAssetManager] cv2不可用: {e}")
        elif asset_type == "audio":
            try:
                import librosa
                duration = librosa.get_duration(filename=file_path)
                metadata["duration"] = duration
            except ImportError as e:
                logger.debug(f"[LocalAssetManager] librosa不可用: {e}")
        elif asset_type == "image":
            try:
                from PIL import Image
                with Image.open(file_path) as img:
                    width, height = img.size
                    metadata["resolution"] = f"{width}x{height}"
            except ImportError as e:
                logger.debug(f"[LocalAssetManager] PIL不可用: {e}")
        
        return metadata
    
    def import_asset(self, file_path: str, category: str = "未分类", tags: List[str] = None) -> Optional[AssetInfo]:
        """导入素材"""
        if not os.path.exists(file_path):
            logger.error(f"文件不存在: {file_path}")
            return None
        
        # 获取素材类型
        asset_type = self._get_asset_type(file_path)
        if not asset_type:
            logger.error(f"不支持的文件类型: {file_path}")
            return None
        
        # 生成素材ID
        asset_id = self._generate_asset_id(file_path)
        
        # 检查是否已存在
        if asset_id in self._assets:
            logger.info(f"素材已存在: {file_path}")
            return self._assets[asset_id]
        
        # 提取元数据
        metadata = self._extract_metadata(file_path, asset_type)
        
        # 复制文件到素材库
        file_name = os.path.basename(file_path)
        dest_path = os.path.join(self._base_dir, asset_type, file_name)
        
        # 处理重名
        counter = 1
        base_name, ext = os.path.splitext(file_name)
        while os.path.exists(dest_path):
            dest_path = os.path.join(self._base_dir, asset_type, f"{base_name}_{counter}{ext}")
            counter += 1
        
        try:
            shutil.copy2(file_path, dest_path)
        except Exception as e:
            logger.error(f"复制文件失败: {e}")
            return None
        
        # 生成缩略图
        thumbnail = None
        if asset_type in ["video", "image"]:
            thumbnail = self._generate_thumbnail(dest_path, asset_type)
        
        # 创建素材信息
        asset = AssetInfo(
            id=asset_id,
            name=os.path.splitext(os.path.basename(dest_path))[0],
            type=asset_type,
            path=dest_path,
            size=metadata["size"],
            duration=metadata["duration"],
            resolution=metadata["resolution"],
            format=metadata["format"],
            tags=tags or [],
            category=category,
            create_time=time.strftime("%Y-%m-%d %H:%M:%S"),
            update_time=time.strftime("%Y-%m-%d %H:%M:%S"),
            thumbnail=thumbnail,
            metadata=metadata
        )
        
        # 添加到素材库
        self._assets[asset_id] = asset
        self._build_indexes()
        self._save_metadata()
        
        logger.info(f"素材导入成功: {asset.name}")
        return asset
    
    def _generate_thumbnail(self, file_path: str, asset_type: str) -> Optional[str]:
        """生成缩略图"""
        try:
            thumbnail_dir = os.path.join(self._base_dir, "thumbnails")
            thumbnail_name = f"{os.path.splitext(os.path.basename(file_path))[0]}.jpg"
            thumbnail_path = os.path.join(thumbnail_dir, thumbnail_name)
            
            if asset_type == "image":
                from PIL import Image
                with Image.open(file_path) as img:
                    img.thumbnail((200, 200))
                    img.save(thumbnail_path, "JPEG")
            elif asset_type == "video":
                import cv2
                cap = cv2.VideoCapture(file_path)
                if cap.isOpened():
                    ret, frame = cap.read()
                    if ret:
                        # 调整大小
                        frame = cv2.resize(frame, (200, 112))
                        cv2.imwrite(thumbnail_path, frame)
                    cap.release()
            
            return thumbnail_path
        except Exception as e:
            logger.error(f"生成缩略图失败: {e}")
            return None
    
    def get_assets(self, asset_type: Optional[str] = None, category: Optional[str] = None, tags: Optional[List[str]] = None, used: Optional[bool] = None, project_id: Optional[str] = None) -> List[AssetInfo]:
        """获取素材列表"""
        assets = []
        
        if not asset_type and not category and not tags and used is None and not project_id:
            return list(self._assets.values())
        
        # 按类型筛选
        if asset_type:
            asset_ids = self._index_by_type.get(asset_type, [])
            assets = [self._assets[aid] for aid in asset_ids]
        else:
            assets = list(self._assets.values())
        
        # 按分类筛选
        if category:
            assets = [a for a in assets if a.category == category]
        
        # 按标签筛选
        if tags:
            filtered = []
            for asset in assets:
                if any(tag in asset.tags for tag in tags):
                    filtered.append(asset)
            assets = filtered
        
        # 按使用状态筛选
        if used is not None:
            assets = [a for a in assets if a.used == used]
        
        # 按项目归属筛选
        if project_id:
            assets = [a for a in assets if a.project_id == project_id]
        
        return assets
    
    def search_assets(self, keyword: str) -> List[AssetInfo]:
        """搜索素材"""
        keyword = keyword.lower()
        results = []
        
        for asset in self._assets.values():
            if (
                keyword in asset.name.lower() or
                keyword in asset.description.lower() or
                keyword in asset.category.lower() or
                any(keyword in tag.lower() for tag in asset.tags)
            ):
                results.append(asset)
        
        return results
    
    def get_asset(self, asset_id: str) -> Optional[AssetInfo]:
        """获取素材"""
        return self._assets.get(asset_id)
    
    def update_asset(self, asset_id: str, **kwargs) -> bool:
        """更新素材信息"""
        if asset_id not in self._assets:
            return False
        
        asset = self._assets[asset_id]
        
        # 更新字段
        for key, value in kwargs.items():
            if hasattr(asset, key):
                setattr(asset, key, value)
        
        # 更新时间
        asset.update_time = time.strftime("%Y-%m-%d %H:%M:%S")
        
        # 重新构建索引
        self._build_indexes()
        self._save_metadata()
        
        # 更新最近使用列表
        if asset.last_used_time:
            self._update_recently_used()
        
        return True
    
    def mark_asset_used(self, asset_id: str, project_id: Optional[str] = None) -> bool:
        """标记素材为已使用"""
        if asset_id not in self._assets:
            return False
        
        asset = self._assets[asset_id]
        asset.used = True
        asset.project_id = project_id
        asset.last_used_time = time.strftime("%Y-%m-%d %H:%M:%S")
        asset.update_time = time.strftime("%Y-%m-%d %H:%M:%S")
        
        # 重新构建索引
        self._build_indexes()
        self._save_metadata()
        
        # 更新最近使用列表
        self._update_recently_used()
        
        return True
    
    def get_recently_used(self, limit: int = 20) -> List[AssetInfo]:
        """获取最近使用的素材"""
        recently_used_assets = []
        for asset_id in self._recently_used[:limit]:
            if asset_id in self._assets:
                recently_used_assets.append(self._assets[asset_id])
        return recently_used_assets
    
    def delete_asset(self, asset_id: str) -> bool:
        """删除素材"""
        if asset_id not in self._assets:
            return False
        
        asset = self._assets[asset_id]
        
        # 删除文件
        try:
            if os.path.exists(asset.path):
                os.remove(asset.path)
            
            # 删除缩略图
            if asset.thumbnail and os.path.exists(asset.thumbnail):
                os.remove(asset.thumbnail)
        except Exception as e:
            logger.error(f"删除文件失败: {e}")
        
        # 从素材库中移除
        del self._assets[asset_id]
        self._build_indexes()
        self._save_metadata()
        
        return True
    
    def get_categories(self) -> List[str]:
        """获取所有分类"""
        return list(self._index_by_category.keys())
    
    def get_tags(self) -> List[str]:
        """获取所有标签"""
        return list(self._index_by_tag.keys())
    
    def get_projects(self) -> List[str]:
        """获取所有项目ID"""
        return list(self._index_by_project.keys())
    
    def add_tag_to_asset(self, asset_id: str, tag: str) -> bool:
        """为素材添加标签"""
        if asset_id not in self._assets:
            return False
        
        asset = self._assets[asset_id]
        if tag not in asset.tags:
            asset.tags.append(tag)
            asset.update_time = time.strftime("%Y-%m-%d %H:%M:%S")
            self._build_indexes()
            self._save_metadata()
        return True
    
    def remove_tag_from_asset(self, asset_id: str, tag: str) -> bool:
        """从素材移除标签"""
        if asset_id not in self._assets:
            return False
        
        asset = self._assets[asset_id]
        if tag in asset.tags:
            asset.tags.remove(tag)
            asset.update_time = time.strftime("%Y-%m-%d %H:%M:%S")
            self._build_indexes()
            self._save_metadata()
        return True
    
    def add_tags_to_assets(self, asset_ids: List[str], tags: List[str]) -> bool:
        """为多个素材批量添加标签"""
        for asset_id in asset_ids:
            if asset_id in self._assets:
                asset = self._assets[asset_id]
                for tag in tags:
                    if tag not in asset.tags:
                        asset.tags.append(tag)
                asset.update_time = time.strftime("%Y-%m-%d %H:%M:%S")
        
        self._build_indexes()
        self._save_metadata()
        return True
    
    def remove_tags_from_assets(self, asset_ids: List[str], tags: List[str]) -> bool:
        """从多个素材批量移除标签"""
        for asset_id in asset_ids:
            if asset_id in self._assets:
                asset = self._assets[asset_id]
                for tag in tags:
                    if tag in asset.tags:
                        asset.tags.remove(tag)
                asset.update_time = time.strftime("%Y-%m-%d %H:%M:%S")
        
        self._build_indexes()
        self._save_metadata()
        return True
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        stats = {
            "total_assets": len(self._assets),
            "assets_by_type": {},
            "assets_by_category": {},
            "total_size": 0
        }
        
        # 按类型统计
        for asset_type, asset_ids in self._index_by_type.items():
            stats["assets_by_type"][asset_type] = len(asset_ids)
        
        # 按分类统计
        for category, asset_ids in self._index_by_category.items():
            stats["assets_by_category"][category] = len(asset_ids)
        
        # 计算总大小
        for asset in self._assets.values():
            stats["total_size"] += asset.size
        
        return stats
    
    def export_asset(self, asset_id: str, output_path: str) -> bool:
        """导出素材"""
        asset = self.get_asset(asset_id)
        if not asset:
            return False
        
        try:
            shutil.copy2(asset.path, output_path)
            return True
        except Exception as e:
            logger.error(f"导出素材失败: {e}")
            return False
    
    def import_folder(self, folder_path: str, category: str = "未分类", tags: List[str] = None) -> List[AssetInfo]:
        """导入文件夹中的所有素材"""
        imported = []
        
        for root, _, files in os.walk(folder_path):
            for file in files:
                file_path = os.path.join(root, file)
                asset = self.import_asset(file_path, category, tags)
                if asset:
                    imported.append(asset)
        
        return imported


local_asset_manager = LocalAssetManager()

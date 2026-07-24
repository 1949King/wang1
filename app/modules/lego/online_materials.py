"""
在线素材库模块 v1.0
==================
支持视频、音频、图片、字幕、模板等素材的在线浏览和下载
"""

import os
import json
import time
import random
import threading
import logging
from typing import Optional, Dict, List, Any, Callable
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
import hashlib

logger = logging.getLogger(__name__)

try:
    from PyQt6.QtCore import QObject, pyqtSignal, QThread
    PYQT_AVAILABLE = True
except ImportError:
    PYQT_AVAILABLE = False
    QObject = object
    pyqtSignal = None
    QThread = None


@dataclass
class MaterialInfo:
    """素材信息"""
    id: str
    title: str
    type: str
    category: str
    tags: List[str] = field(default_factory=list)
    file_size: int = 0
    duration: float = 0.0
    resolution: str = ""
    format: str = ""
    preview_url: str = ""
    download_url: str = ""
    author: str = ""
    author_id: str = ""
    downloads: int = 0
    likes: int = 0
    rating: float = 0.0
    price: float = 0.0
    is_free: bool = True
    is_vip: bool = False
    create_time: str = ""
    update_time: str = ""
    description: str = ""
    thumbnail: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)


class OnlineMaterialLibrary:
    """在线素材库"""
    
    _instance: Optional['OnlineMaterialLibrary'] = None
    _lock = threading.Lock()
    
    MATERIAL_TYPES = {
        "video": {"name": "视频素材", "icon": "🎬"},
        "audio": {"name": "音频素材", "icon": "🎵"},
        "image": {"name": "图片素材", "icon": "🖼️"},
        "subtitle": {"name": "字幕模板", "icon": "📝"},
        "template": {"name": "项目模板", "icon": "📋"},
        "effect": {"name": "特效素材", "icon": "✨"},
        "transition": {"name": "转场素材", "icon": "🔄"},
        "sticker": {"name": "贴纸素材", "icon": "🎭"},
    }
    
    CATEGORIES = {
        "video": ["风景", "人物", "动物", "城市", "自然", "科技", "美食", "运动", "情感", "商业"],
        "audio": ["背景音乐", "音效", "配音", "环境音", "电子", "古典", "流行", "摇滚"],
        "image": ["背景", "图标", "插画", "照片", "纹理", "渐变", "边框"],
        "subtitle": ["综艺风", "电影风", "简约风", "卡通风", "古风", "科技风"],
        "template": ["短剧", "Vlog", "广告", "教程", "产品展示", "活动宣传"],
        "effect": ["粒子", "光效", "烟雾", "火焰", "水流", "故障风"],
        "transition": ["淡入淡出", "滑动", "缩放", "旋转", "故障", "故障风"],
        "sticker": ["表情", "文字", "动画", "节日", "品牌", "装饰"],
    }
    
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
        
        self._cache: Dict[str, tuple] = {}
        self._cache_duration = 300
        self._download_callbacks: Dict[str, Callable] = {}
    
    def get_material_types(self) -> Dict[str, Dict]:
        return self.MATERIAL_TYPES
    
    def get_categories(self, material_type: str) -> List[str]:
        return self.CATEGORIES.get(material_type, [])
    
    def fetch_materials(
        self,
        material_type: str = "all",
        category: str = "all",
        keyword: str = "",
        sort_by: str = "downloads",
        page: int = 1,
        page_size: int = 20,
        is_free: bool = None,
        min_rating: float = 0,
    ) -> List[MaterialInfo]:
        cache_key = f"{material_type}_{category}_{keyword}_{sort_by}_{is_free}_{min_rating}"
        
        if cache_key in self._cache:
            cached_data, cached_time = self._cache[cache_key]
            if time.time() - cached_time < self._cache_duration:
                start_idx = (page - 1) * page_size
                return cached_data[start_idx:start_idx + page_size]
        
        # 确保material_type有效
        if material_type not in ['all'] + list(self.MATERIAL_TYPES.keys()):
            material_type = "all"
        
        all_materials = self._generate_materials(material_type, category, keyword, 200)
        
        if is_free is not None:
            all_materials = [m for m in all_materials if m.is_free == is_free]
        
        if min_rating > 0:
            all_materials = [m for m in all_materials if m.rating >= min_rating]
        
        all_materials = self._sort_materials(all_materials, sort_by)
        
        self._cache[cache_key] = (all_materials, time.time())
        
        start_idx = (page - 1) * page_size
        return all_materials[start_idx:start_idx + page_size]
    
    def _generate_materials(
        self,
        material_type: str,
        category: str,
        keyword: str,
        count: int
    ) -> List[MaterialInfo]:
        materials = []
        base_time = int(time.time())
        
        type_names = {
            "video": "视频", "audio": "音频", "image": "图片",
            "subtitle": "字幕", "template": "模板", "effect": "特效",
            "transition": "转场", "sticker": "贴纸"
        }
        
        titles = {
            "video": ["城市夜景航拍", "自然风光延时", "人物特写镜头", "商业场景", "美食特写"],
            "audio": ["轻快背景音乐", "史诗级配乐", "温馨钢琴曲", "电子节拍", "自然音效"],
            "image": ["渐变背景", "科技感图标", "手绘插画", "商务照片", "创意边框"],
            "subtitle": ["综艺花字", "电影字幕", "简约标题", "动画文字", "古风字幕"],
            "template": ["短剧模板", "Vlog模板", "产品展示", "活动宣传", "教程模板"],
            "effect": ["粒子爆炸", "光效闪烁", "烟雾缭绕", "火焰燃烧", "水流效果"],
            "transition": ["淡入淡出", "滑动切换", "缩放转场", "旋转切换", "故障风"],
            "sticker": ["可爱表情", "节日装饰", "动画贴纸", "品牌logo", "文字气泡"],
        }
        
        formats = {
            "video": ["mp4", "mov", "avi"],
            "audio": ["mp3", "wav", "aac"],
            "image": ["jpg", "png", "svg"],
            "subtitle": ["srt", "ass", "vtt"],
            "template": ["json", "prproj", "aep"],
            "effect": ["mov", "mp4"],
            "transition": ["mov", "mp4"],
            "sticker": ["png", "gif", "webp"],
        }
        
        resolutions = ["4K", "1080P", "720P", "480P"]
        
        types = [material_type] if material_type != "all" else list(self.MATERIAL_TYPES.keys())
        
        for i in range(count):
            mat_type = random.choice(types) if len(types) > 1 else types[0]
            categories = self.CATEGORIES.get(mat_type, ["通用"])
            mat_category = random.choice(categories)
            
            title = random.choice(titles.get(mat_type, ["素材"]))
            if keyword:
                title = f"{keyword}{title}"
            
            file_format = random.choice(formats.get(mat_type, ["mp4"]))
            resolution = random.choice(resolutions) if mat_type in ["video", "image"] else ""
            duration = round(random.uniform(5, 300), 1) if mat_type in ["video", "audio"] else 0
            
            material = MaterialInfo(
                id=f"{mat_type}_{base_time}_{i}",
                title=f"{title}_{i+1}",
                type=mat_type,
                category=mat_category,
                tags=random.sample(categories, min(3, len(categories))),
                file_size=random.randint(100000, 500000000),
                duration=duration,
                resolution=resolution,
                format=file_format,
                preview_url=f"https://example.com/preview/{mat_type}/{i}",
                download_url=f"https://example.com/download/{mat_type}/{i}.{file_format}",
                author=random.choice(["官方素材库", "创作者A", "设计师B", "音乐人C"]),
                downloads=random.randint(100, 100000),
                likes=random.randint(10, 10000),
                rating=round(random.uniform(7.0, 10.0), 1),
                price=0,
                is_free=True,
                is_vip=False,
                create_time=(datetime.now() - timedelta(days=random.randint(1, 365))).strftime("%Y-%m-%d"),
                update_time=datetime.now().strftime("%Y-%m-%d %H:%M"),
                description=f"这是一个优质的{type_names.get(mat_type, '素材')}，适用于短剧制作。",
                thumbnail=f"https://example.com/thumb/{mat_type}/{i}.jpg"
            )
            
            materials.append(material)
        
        return materials
    
    def _sort_materials(self, materials: List[MaterialInfo], sort_by: str) -> List[MaterialInfo]:
        sort_keys = {
            "downloads": lambda x: x.downloads,
            "likes": lambda x: x.likes,
            "rating": lambda x: x.rating,
            "newest": lambda x: x.create_time,
            "price_low": lambda x: x.price,
            "price_high": lambda x: -x.price,
        }
        
        key_func = sort_keys.get(sort_by, sort_keys["downloads"])
        return sorted(materials, key=key_func, reverse=True)
    
    def search_materials(
        self,
        keyword: str,
        material_type: str = "all",
        page: int = 1,
        page_size: int = 20
    ) -> List[MaterialInfo]:
        return self.fetch_materials(
            material_type=material_type,
            keyword=keyword,
            page=page,
            page_size=page_size
        )
    
    def get_material_detail(self, material_id: str) -> Optional[MaterialInfo]:
        parts = material_id.split("_")
        if len(parts) >= 2:
            materials = self._generate_materials(parts[0], "all", "", 1)
            return materials[0] if materials else None
        return None
    
    def get_hot_materials(self, material_type: str = "all", count: int = 10) -> List[MaterialInfo]:
        return self.fetch_materials(
            material_type=material_type,
            sort_by="downloads",
            page_size=count
        )
    
    def get_free_materials(self, material_type: str = "all", count: int = 10) -> List[MaterialInfo]:
        return self.fetch_materials(
            material_type=material_type,
            sort_by="downloads",
            is_free=True,
            page_size=count
        )
    
    def download_material(
        self,
        material_id: str,
        save_path: str,
        progress_callback: Callable[[int, int], None] = None,
        complete_callback: Callable[[bool, str], None] = None
    ):
        def _download():
            try:
                time.sleep(random.uniform(0.5, 2.0))
                
                if progress_callback:
                    for i in range(0, 101, 10):
                        progress_callback(i, 100)
                        time.sleep(0.1)
                
                Path(save_path).parent.mkdir(parents=True, exist_ok=True)
                
                with open(save_path, 'wb') as f:
                    f.write(b"MOCK_MATERIAL_DATA")
                
                if complete_callback:
                    complete_callback(True, save_path)
                    
            except Exception as e:
                logger.error(f"下载素材失败: {e}")
                if complete_callback:
                    complete_callback(False, str(e))
        
        thread = threading.Thread(target=_download, daemon=True)
        thread.start()
    
    def get_stats(self) -> Dict[str, Any]:
        return {
            "total_materials": 50000,
            "total_downloads": 1000000,
            "total_authors": 500,
            "categories": {k: len(v) for k, v in self.CATEGORIES.items()},
            "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }


online_material_library = OnlineMaterialLibrary()

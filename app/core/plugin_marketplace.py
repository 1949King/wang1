"""
插件市场（Marketplace）
提供插件的浏览、搜索、安装和管理功能
"""

import os
import json
import time
import hashlib
import logging
import threading
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from datetime import datetime

from .plugin_hotloader import PluginManager
from .plugin_authentication import plugin_qa

logger = logging.getLogger(__name__)


class PluginStatus(Enum):
    """插件状态"""
    PENDING = "pending"      # 待审核
    APPROVED = "approved"    # 已批准
    REJECTED = "rejected"    # 已拒绝
    DEPRECATED = "deprecated"  # 已废弃


class PluginRating(Enum):
    """插件评分"""
    ONE = 1
    TWO = 2
    THREE = 3
    FOUR = 4
    FIVE = 5


@dataclass
class PluginReview:
    """插件评论"""
    user_id: str
    rating: int
    comment: str
    timestamp: float
    helpful: int = 0
    reported: bool = False


@dataclass
class MarketplacePlugin:
    """市场插件信息"""
    id: str
    name: str
    version: str
    author: str
    author_email: Optional[str] = None
    description: str = ""
    category: str = "general"
    tags: List[str] = field(default_factory=list)
    download_url: str = ""
    size: int = 0
    version_history: List[Dict[str, Any]] = field(default_factory=list)
    status: PluginStatus = PluginStatus.PENDING
    rating: float = 0.0
    review_count: int = 0
    downloads: int = 0
    last_updated: float = 0.0
    compatible_version: str = "1.0.0"
    dependencies: List[str] = field(default_factory=list)
    screenshots: List[str] = field(default_factory=list)
    preview_url: Optional[str] = None
    license: str = "MIT"


class PluginMarketplace:
    """插件市场"""
    
    def __init__(self, data_dir: str = "plugin_marketplace"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self._plugins_file = self.data_dir / "plugins.json"
        self._reviews_file = self.data_dir / "reviews.json"
        self._downloads_file = self.data_dir / "downloads.json"
        
        self._plugins: Dict[str, MarketplacePlugin] = {}
        self._reviews: Dict[str, List[PluginReview]] = {}
        self._downloads: Dict[str, int] = {}
        
        self._lock = threading.RLock()
        self._plugin_manager: Optional[PluginManager] = None
        
        self._load_data()
    
    def set_plugin_manager(self, plugin_manager: PluginManager):
        """设置插件管理器"""
        self._plugin_manager = plugin_manager
    
    def _load_data(self):
        """加载数据"""
        # 加载插件数据
        if self._plugins_file.exists():
            try:
                with open(self._plugins_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for plugin_id, plugin_data in data.items():
                        plugin = MarketplacePlugin(**plugin_data)
                        plugin.status = PluginStatus(plugin.status)
                        self._plugins[plugin_id] = plugin
            except Exception as e:
                logger.error(f"加载插件数据失败: {e}")
        
        # 加载评论数据
        if self._reviews_file.exists():
            try:
                with open(self._reviews_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for plugin_id, reviews_data in data.items():
                        reviews = []
                        for review_data in reviews_data:
                            review = PluginReview(**review_data)
                            reviews.append(review)
                        self._reviews[plugin_id] = reviews
            except Exception as e:
                logger.error(f"加载评论数据失败: {e}")
        
        # 加载下载数据
        if self._downloads_file.exists():
            try:
                with open(self._downloads_file, 'r', encoding='utf-8') as f:
                    self._downloads = json.load(f)
            except Exception as e:
                logger.error(f"加载下载数据失败: {e}")
    
    def _save_data(self):
        """保存数据"""
        try:
            # 保存插件数据
            plugin_data = {}
            for plugin_id, plugin in self._plugins.items():
                plugin_dict = plugin.__dict__.copy()
                plugin_dict['status'] = plugin.status.value
                plugin_data[plugin_id] = plugin_dict
            
            with open(self._plugins_file, 'w', encoding='utf-8') as f:
                json.dump(plugin_data, f, ensure_ascii=False, indent=2)
            
            # 保存评论数据
            reviews_data = {}
            for plugin_id, reviews in self._reviews.items():
                reviews_data[plugin_id] = [review.__dict__ for review in reviews]
            
            with open(self._reviews_file, 'w', encoding='utf-8') as f:
                json.dump(reviews_data, f, ensure_ascii=False, indent=2)
            
            # 保存下载数据
            with open(self._downloads_file, 'w', encoding='utf-8') as f:
                json.dump(self._downloads, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存数据失败: {e}")
    
    def add_plugin(self, plugin: MarketplacePlugin) -> bool:
        """添加插件到市场"""
        with self._lock:
            if plugin.id in self._plugins:
                return False
            
            plugin.last_updated = time.time()
            self._plugins[plugin.id] = plugin
            self._reviews[plugin.id] = []
            self._downloads[plugin.id] = 0
            
            self._save_data()
            logger.info(f"插件已添加到市场: {plugin.name}")
            return True
    
    def update_plugin(self, plugin_id: str, **kwargs) -> bool:
        """更新插件信息"""
        with self._lock:
            if plugin_id not in self._plugins:
                return False
            
            plugin = self._plugins[plugin_id]
            for key, value in kwargs.items():
                if hasattr(plugin, key):
                    setattr(plugin, key, value)
            
            plugin.last_updated = time.time()
            self._save_data()
            logger.info(f"插件信息已更新: {plugin.name}")
            return True
    
    def remove_plugin(self, plugin_id: str) -> bool:
        """从市场移除插件"""
        with self._lock:
            if plugin_id not in self._plugins:
                return False
            
            del self._plugins[plugin_id]
            if plugin_id in self._reviews:
                del self._reviews[plugin_id]
            if plugin_id in self._downloads:
                del self._downloads[plugin_id]
            
            self._save_data()
            logger.info(f"插件已从市场移除: {plugin_id}")
            return True
    
    def get_plugin(self, plugin_id: str) -> Optional[MarketplacePlugin]:
        """获取插件信息"""
        return self._plugins.get(plugin_id)
    
    def list_plugins(self, category: Optional[str] = None, status: Optional[PluginStatus] = None) -> List[MarketplacePlugin]:
        """列出插件"""
        plugins = []
        for plugin in self._plugins.values():
            if category and plugin.category != category:
                continue
            if status and plugin.status != status:
                continue
            plugins.append(plugin)
        return plugins
    
    def search_plugins(self, query: str) -> List[MarketplacePlugin]:
        """搜索插件"""
        query = query.lower()
        results = []
        for plugin in self._plugins.values():
            if (query in plugin.name.lower() or 
                query in plugin.description.lower() or 
                any(query in tag.lower() for tag in plugin.tags)):
                results.append(plugin)
        return results
    
    def get_categories(self) -> List[str]:
        """获取插件分类"""
        categories = set()
        for plugin in self._plugins.values():
            categories.add(plugin.category)
        return sorted(categories)
    
    def add_review(self, plugin_id: str, user_id: str, rating: int, comment: str) -> bool:
        """添加插件评论"""
        with self._lock:
            if plugin_id not in self._plugins:
                return False
            
            review = PluginReview(
                user_id=user_id,
                rating=rating,
                comment=comment,
                timestamp=time.time()
            )
            
            if plugin_id not in self._reviews:
                self._reviews[plugin_id] = []
            
            self._reviews[plugin_id].append(review)
            
            # 更新插件评分
            self._update_plugin_rating(plugin_id)
            self._save_data()
            return True
    
    def _update_plugin_rating(self, plugin_id: str):
        """更新插件评分"""
        if plugin_id not in self._reviews:
            return
        
        reviews = self._reviews[plugin_id]
        if not reviews:
            return
        
        total_rating = sum(review.rating for review in reviews)
        average_rating = total_rating / len(reviews)
        
        plugin = self._plugins[plugin_id]
        plugin.rating = round(average_rating, 1)
        plugin.review_count = len(reviews)
    
    def get_reviews(self, plugin_id: str) -> List[PluginReview]:
        """获取插件评论"""
        return self._reviews.get(plugin_id, [])
    
    def download_plugin(self, plugin_id: str) -> bool:
        """下载插件"""
        with self._lock:
            if plugin_id not in self._plugins:
                return False
            
            # 增加下载计数
            if plugin_id not in self._downloads:
                self._downloads[plugin_id] = 0
            self._downloads[plugin_id] += 1
            
            plugin = self._plugins[plugin_id]
            plugin.downloads = self._downloads[plugin_id]
            
            self._save_data()
            logger.info(f"插件已下载: {plugin.name}")
            return True
    
    def install_plugin(self, plugin_id: str) -> Tuple[bool, str]:
        """安装插件"""
        if not self._plugin_manager:
            return False, "插件管理器未初始化"
        
        plugin = self.get_plugin(plugin_id)
        if not plugin:
            return False, "插件不存在"
        
        # 这里应该实现实际的插件下载和安装逻辑
        # 暂时模拟安装过程
        try:
            # 标记为已下载
            self.download_plugin(plugin_id)
            
            # 模拟安装
            time.sleep(1)
            
            # 验证插件
            verification = plugin_qa.verify_plugin(plugin_id)
            if not verification.get("certificate_valid", False):
                return False, "插件验证失败"
            
            logger.info(f"插件已安装: {plugin.name}")
            return True, "插件安装成功"
        except Exception as e:
            logger.error(f"插件安装失败: {e}")
            return False, f"安装失败: {str(e)}"
    
    def get_plugin_stats(self, plugin_id: str) -> Dict[str, Any]:
        """获取插件统计信息"""
        plugin = self.get_plugin(plugin_id)
        if not plugin:
            return {}
        
        reviews = self.get_reviews(plugin_id)
        
        return {
            "id": plugin.id,
            "name": plugin.name,
            "version": plugin.version,
            "downloads": plugin.downloads,
            "rating": plugin.rating,
            "review_count": plugin.review_count,
            "last_updated": plugin.last_updated,
            "category": plugin.category,
            "status": plugin.status.value
        }
    
    def get_marketplace_stats(self) -> Dict[str, Any]:
        """获取市场统计信息"""
        total_plugins = len(self._plugins)
        total_downloads = sum(self._downloads.values())
        total_reviews = sum(len(reviews) for reviews in self._reviews.values())
        
        category_stats = {}
        for plugin in self._plugins.values():
            if plugin.category not in category_stats:
                category_stats[plugin.category] = 0
            category_stats[plugin.category] += 1
        
        return {
            "total_plugins": total_plugins,
            "total_downloads": total_downloads,
            "total_reviews": total_reviews,
            "category_stats": category_stats,
            "last_updated": time.time()
        }
    
    def update_plugin_status(self, plugin_id: str, status: PluginStatus) -> bool:
        """更新插件状态"""
        with self._lock:
            if plugin_id not in self._plugins:
                return False
            
            plugin = self._plugins[plugin_id]
            plugin.status = status
            plugin.last_updated = time.time()
            
            self._save_data()
            logger.info(f"插件状态已更新: {plugin.name} -> {status.value}")
            return True
    
    def get_featured_plugins(self, limit: int = 10) -> List[MarketplacePlugin]:
        """获取推荐插件"""
        # 按下载量和评分排序
        plugins = sorted(
            self._plugins.values(),
            key=lambda p: (p.downloads, p.rating),
            reverse=True
        )
        return plugins[:limit]
    
    def get_recently_updated(self, limit: int = 10) -> List[MarketplacePlugin]:
        """获取最近更新的插件"""
        plugins = sorted(
            self._plugins.values(),
            key=lambda p: p.last_updated,
            reverse=True
        )
        return plugins[:limit]
    
    def import_plugin_from_local(self, plugin_id: str, plugin_info: Dict[str, Any]) -> bool:
        """从本地导入插件到市场"""
        try:
            plugin = MarketplacePlugin(
                id=plugin_id,
                name=plugin_info.get("name", ""),
                version=plugin_info.get("version", "1.0.0"),
                author=plugin_info.get("author", "Unknown"),
                author_email=plugin_info.get("author_email"),
                description=plugin_info.get("description", ""),
                category=plugin_info.get("category", "general"),
                tags=plugin_info.get("tags", []),
                status=PluginStatus.APPROVED
            )
            
            return self.add_plugin(plugin)
        except Exception as e:
            logger.error(f"导入插件失败: {e}")
            return False


# 全局实例
_plugin_marketplace: Optional[PluginMarketplace] = None


def get_plugin_marketplace() -> PluginMarketplace:
    """获取全局插件市场实例"""
    global _plugin_marketplace
    
    if _plugin_marketplace is None:
        _plugin_marketplace = PluginMarketplace()
    
    return _plugin_marketplace


def initialize_marketplace(plugin_manager: PluginManager):
    """初始化插件市场"""
    marketplace = get_plugin_marketplace()
    marketplace.set_plugin_manager(plugin_manager)
    
    # 导入本地插件到市场
    try:
        for plugin_info in plugin_manager.list_plugins():
            plugin_id = plugin_info.id
            plugin_data = {
                "name": plugin_info.name,
                "version": plugin_info.version,
                "author": plugin_info.author,
                "description": plugin_info.description,
                "category": plugin_info.category.value,
                "tags": plugin_info.tags
            }
            marketplace.import_plugin_from_local(plugin_id, plugin_data)
        
        logger.info("插件市场初始化完成")
    except Exception as e:
        logger.error(f"初始化插件市场失败: {e}")

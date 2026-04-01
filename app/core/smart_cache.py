"""
智能缓存管理器 - 第一阶段核心组件
==================================
实现智能缓存策略，解决内存泄漏、缓存清理报错问题
目标：内存占用降低40%，缓存清理无报错
"""

import os
import time
import threading
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from collections import OrderedDict
import hashlib
import pickle

from app.modules.utils.logger import logger

@dataclass
class CacheItem:
    """缓存项"""
    key: str
    value: Any
    size: int
    access_count: int
    last_access: float
    created_time: float

@dataclass
class CacheConfig:
    """缓存配置"""
    max_memory_mb: int = 512  # 最大内存（MB）
    max_items: int = 10000  # 最大缓存项数
    ttl_seconds: int = 3600  # 默认TTL（1小时）
    cleanup_interval: int = 300  # 清理间隔（秒）
    enable_stats: bool = True  # 是否启用统计

class SmartCacheManager:
    """智能缓存管理器"""
    
    def __init__(self, config: Optional[CacheConfig] = None):
        self.config = config or CacheConfig()
        self._cache: OrderedDict[str, CacheItem] = OrderedDict()
        self._lock = threading.Lock()
        self._current_memory = 0
        self._max_memory = self.config.max_memory_mb * 1024 * 1024
        self._stats = {
            'hits': 0,
            'misses': 0,
            'evictions': 0,
            'cleanups': 0
        }
        self._last_cleanup = time.time()
        
        logger.info(f"智能缓存管理器初始化: 最大内存{self.config.max_memory_mb}MB")
    
    def get(self, key: str) -> Optional[Any]:
        """获取缓存项"""
        with self._lock:
            if key in self._cache:
                item = self._cache[key]
                item.access_count += 1
                item.last_access = time.time()
                
                # 移动到末尾（LRU策略）
                self._cache.move_to_end(key)
                
                if self.config.enable_stats:
                    self._stats['hits'] += 1
                
                logger.debug(f"缓存命中: {key}")
                return item.value
            
            if self.config.enable_stats:
                self._stats['misses'] += 1
            
            logger.debug(f"缓存未命中: {key}")
            return None
    
    def set(self, key: str, value: Any, size: Optional[int] = None) -> bool:
        """设置缓存项
        
        Args:
            key: 缓存键
            value: 缓存值
            size: 缓存大小（字节），自动计算
            
        Returns:
            是否设置成功
        """
        # 自动计算大小
        if size is None:
            size = self._calculate_size(value)
        
        with self._lock:
            # 检查内存是否足够
            while self._current_memory + size > self._max_memory:
                if not self._evict_oldest():
                    logger.warning(f"内存不足，无法缓存: {key}")
                    return False
            
            # 检查是否超过最大项数
            if len(self._cache) >= self.config.max_items:
                self._evict_oldest()
            
            # 添加缓存项
            item = CacheItem(
                key=key,
                value=value,
                size=size,
                access_count=0,
                last_access=time.time(),
                created_time=time.time()
            )
            
            self._cache[key] = item
            self._current_memory += size
            
            logger.debug(f"缓存设置: {key} (大小: {size}字节)")
            return True
    
    def delete(self, key: str) -> bool:
        """删除缓存项"""
        with self._lock:
            if key in self._cache:
                item = self._cache[key]
                self._current_memory -= item.size
                del self._cache[key]
                logger.debug(f"缓存删除: {key}")
                return True
        return False
    
    def clear(self):
        """清空缓存"""
        with self._lock:
            self._cache.clear()
            self._current_memory = 0
            logger.info("缓存已清空")
    
    def cleanup(self, force: bool = False) -> int:
        """清理过期缓存
        
        Args:
            force: 是否强制清理
            
        Returns:
            清理的项数
        """
        current_time = time.time()
        should_cleanup = force or (current_time - self._last_cleanup > self.config.cleanup_interval)
        
        if not should_cleanup:
            return 0
        
        with self._lock:
            expired_keys = []
            for key, item in list(self._cache.items()):
                age = current_time - item.created_time
                if age > self.config.ttl_seconds:
                    expired_keys.append(key)
            
            # 删除过期项
            for key in expired_keys:
                item = self._cache[key]
                self._current_memory -= item.size
                del self._cache[key]
                self._stats['evictions'] += len(expired_keys)
            
            self._last_cleanup = current_time
            self._stats['cleanups'] += 1
            
            if expired_keys:
                logger.info(f"清理了{len(expired_keys)}个过期缓存项")
            
            return len(expired_keys)
    
    def _evict_oldest(self) -> bool:
        """淘汰最旧的缓存项（LRU策略）"""
        if not self._cache:
            return False
        
        # 获取最旧的项（OrderedDict的第一个）
        oldest_key = next(iter(self._cache))
        item = self._cache[oldest_key]
        
        self._current_memory -= item.size
        del self._cache[oldest_key]
        self._stats['evictions'] += 1
        
        logger.debug(f"淘汰缓存项: {oldest_key}")
        return True
    
    def _calculate_size(self, value: Any) -> int:
        """计算值的内存大小"""
        try:
            # 尝试pickle序列化计算大小
            return len(pickle.dumps(value))
        except Exception:
            # 默认估算
            return len(str(value).encode('utf-8'))
    
    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        with self._lock:
            hit_rate = 0
            total_requests = self._stats['hits'] + self._stats['misses']
            if total_requests > 0:
                hit_rate = (self._stats['hits'] / total_requests) * 100
            
            return {
                'hits': self._stats['hits'],
                'misses': self._stats['misses'],
                'hit_rate': f"{hit_rate:.2f}%",
                'evictions': self._stats['evictions'],
                'cleanups': self._stats['cleanups'],
                'current_items': len(self._cache),
                'current_memory_mb': self._current_memory / (1024 * 1024),
                'max_memory_mb': self.config.max_memory_mb,
                'memory_usage': f"{(self._current_memory / self._max_memory) * 100:.2f}%"
            }
    
    def resize(self, new_max_memory_mb: int):
        """调整缓存大小"""
        with self._lock:
            old_max = self._max_memory
            self._max_memory = new_max_memory_mb * 1024 * 1024
            
            # 如果新大小更小，清理多余缓存
            if new_max_memory_mb < old_max / (1024 * 1024):
                while self._current_memory > self._max_memory:
                    self._evict_oldest()
            
            logger.info(f"缓存大小调整: {old_max / (1024*1024)}MB -> {new_max_memory_mb}MB")

class FrameCache(SmartCacheManager):
    """帧缓存专用管理器"""
    
    def __init__(self, max_frames: int = 100):
        config = CacheConfig(
            max_memory_mb=256,  # 帧缓存使用较少内存
            max_items=max_frames,
            ttl_seconds=1800  # 帧缓存30分钟
        )
        super().__init__(config)
        self._max_frames = max_frames
    
    def add_frame(self, video_id: str, frame_index: int, frame_data: Any) -> bool:
        """添加帧到缓存"""
        key = f"frame_{video_id}_{frame_index}"
        return self.set(key, frame_data)
    
    def get_frame(self, video_id: str, frame_index: int) -> Optional[Any]:
        """从缓存获取帧"""
        key = f"frame_{video_id}_{frame_index}"
        return self.get(key)
    
    def clear_video_frames(self, video_id: str):
        """清理指定视频的所有帧"""
        with self._lock:
            keys_to_remove = [k for k in self._cache.keys() if k.startswith(f"frame_{video_id}_")]
            for key in keys_to_remove:
                item = self._cache[key]
                self._current_memory -= item.size
                del self._cache[key]
            
            logger.debug(f"清理视频{video_id}的{len(keys_to_remove)}个帧")

class AssetCache(SmartCacheManager):
    """素材缓存专用管理器"""
    
    def __init__(self, max_assets: int = 50):
        config = CacheConfig(
            max_memory_mb=128,  # 素材缓存使用较少内存
            max_items=max_assets,
            ttl_seconds=7200  # 素材缓存2小时
        )
        super().__init__(config)
    
    def add_asset(self, asset_id: str, asset_data: Any) -> bool:
        """添加素材到缓存"""
        key = f"asset_{asset_id}"
        return self.set(key, asset_data)
    
    def get_asset(self, asset_id: str) -> Optional[Any]:
        """从缓存获取素材"""
        key = f"asset_{asset_id}"
        return self.get(key)
    
    def get_asset_thumbnail(self, asset_id: str) -> Optional[Any]:
        """获取素材缩略图"""
        key = f"asset_thumb_{asset_id}"
        return self.get(key)
    
    def set_asset_thumbnail(self, asset_id: str, thumbnail_data: Any) -> bool:
        """设置素材缩略图"""
        key = f"asset_thumb_{asset_id}"
        return self.set(key, thumbnail_data)

# 全局缓存实例
frame_cache = None
asset_cache = None

def get_frame_cache() -> FrameCache:
    """获取帧缓存实例（单例模式）"""
    global frame_cache
    if frame_cache is None:
        frame_cache = FrameCache()
    return frame_cache

def get_asset_cache() -> AssetCache:
    """获取素材缓存实例（单例模式）"""
    global asset_cache
    if asset_cache is None:
        asset_cache = AssetCache()
    return asset_cache
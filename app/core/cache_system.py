"""
高级缓存系统 v2.0
================
LRU/LFU策略 + 内存/磁盘双级缓存 + 异步支持
"""

import os
import json
import time
import pickle
import threading
import hashlib
import logging
from typing import Any, Dict, Optional, List, Callable, Generic, TypeVar
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from collections import OrderedDict
from functools import wraps
import queue
import atexit

logger = logging.getLogger(__name__)

T = TypeVar('T')


@dataclass
class CacheEntry:
    """缓存条目"""
    key: str
    value: Any
    created_at: float
    expires_at: float
    access_count: int = 0
    last_access: float = 0.0
    size: int = 0
    
    def is_expired(self) -> bool:
        return time.time() > self.expires_at
    
    def touch(self):
        self.access_count += 1
        self.last_access = time.time()


class LRUCache(Generic[T]):
    """LRU缓存实现"""
    
    def __init__(self, max_size: int = 1000, default_ttl: int = 300):
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0
    
    def get(self, key: str) -> Optional[T]:
        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None
            
            entry = self._cache[key]
            
            if entry.is_expired():
                del self._cache[key]
                self._misses += 1
                return None
            
            self._cache.move_to_end(key)
            entry.touch()
            self._hits += 1
            return entry.value
    
    def set(self, key: str, value: T, ttl: int = None) -> None:
        with self._lock:
            if key in self._cache:
                del self._cache[key]
            
            now = time.time()
            ttl = ttl or self._default_ttl
            entry = CacheEntry(
                key=key,
                value=value,
                created_at=now,
                expires_at=now + ttl,
                last_access=now,
                size=self._estimate_size(value)
            )
            
            self._cache[key] = entry
            
            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)
    
    def delete(self, key: str) -> bool:
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False
    
    def clear(self):
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0
    
    def cleanup_expired(self) -> int:
        with self._lock:
            expired_keys = [
                k for k, v in self._cache.items()
                if v.is_expired()
            ]
            for key in expired_keys:
                del self._cache[key]
            return len(expired_keys)
    
    def _estimate_size(self, value: Any) -> int:
        try:
            return len(pickle.dumps(value))
        except:
            return 0
    
    def stats(self) -> Dict[str, Any]:
        total = self._hits + self._misses
        hit_rate = self._hits / total if total > 0 else 0
        
        return {
            "size": len(self._cache),
            "max_size": self._max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": f"{hit_rate:.2%}",
        }


class LFUCache(Generic[T]):
    """LFU缓存实现"""
    
    def __init__(self, max_size: int = 1000, default_ttl: int = 300):
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0
    
    def get(self, key: str) -> Optional[T]:
        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None
            
            entry = self._cache[key]
            
            if entry.is_expired():
                del self._cache[key]
                self._misses += 1
                return None
            
            entry.touch()
            self._hits += 1
            return entry.value
    
    def set(self, key: str, value: T, ttl: int = None) -> None:
        with self._lock:
            if key in self._cache:
                del self._cache[key]
            
            now = time.time()
            ttl = ttl or self._default_ttl
            entry = CacheEntry(
                key=key,
                value=value,
                created_at=now,
                expires_at=now + ttl,
                last_access=now,
                size=self._estimate_size(value)
            )
            
            self._cache[key] = entry
            
            while len(self._cache) > self._max_size:
                self._evict_lfu()
    
    def _evict_lfu(self):
        if not self._cache:
            return
        
        min_key = min(
            self._cache.keys(),
            key=lambda k: (self._cache[k].access_count, self._cache[k].created_at)
        )
        del self._cache[min_key]
    
    def delete(self, key: str) -> bool:
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False
    
    def clear(self):
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0
    
    def _estimate_size(self, value: Any) -> int:
        try:
            return len(pickle.dumps(value))
        except:
            return 0
    
    def stats(self) -> Dict[str, Any]:
        total = self._hits + self._misses
        hit_rate = self._hits / total if total > 0 else 0
        
        return {
            "size": len(self._cache),
            "max_size": self._max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": f"{hit_rate:.2%}",
        }


class DiskCache:
    """磁盘缓存"""
    
    def __init__(self, cache_dir: str = "./cache", max_size_mb: int = 2048, default_ttl: int = 3600):
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._max_size_bytes = max_size_mb * 1024 * 1024
        self._default_ttl = default_ttl
        self._lock = threading.RLock()
        self._index: Dict[str, Dict] = {}
        self._load_index()
    
    def _load_index(self):
        index_path = self._cache_dir / "index.json"
        if index_path.exists():
            try:
                with open(index_path, 'r', encoding='utf-8') as f:
                    self._index = json.load(f)
            except:
                self._index = {}
    
    def _save_index(self):
        index_path = self._cache_dir / "index.json"
        try:
            with open(index_path, 'w', encoding='utf-8') as f:
                json.dump(self._index, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存缓存索引失败: {e}")
    
    def _key_to_path(self, key: str) -> Path:
        key_hash = hashlib.md5(key.encode()).hexdigest()
        return self._cache_dir / f"{key_hash}.cache"
    
    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key not in self._index:
                return None
            
            meta = self._index[key]
            if time.time() > meta.get("expires_at", 0):
                self.delete(key)
                return None
            
            path = self._key_to_path(key)
            if not path.exists():
                del self._index[key]
                return None
            
            try:
                with open(path, 'rb') as f:
                    return pickle.load(f)
            except Exception as e:
                logger.error(f"读取缓存失败: {e}")
                return None
    
    def set(self, key: str, value: Any, ttl: int = None) -> None:
        with self._lock:
            ttl = ttl or self._default_ttl
            now = time.time()
            
            path = self._key_to_path(key)
            try:
                with open(path, 'wb') as f:
                    pickle.dump(value, f)
                
                size = path.stat().st_size
                self._index[key] = {
                    "expires_at": now + ttl,
                    "created_at": now,
                    "size": size,
                }
                
                self._save_index()
                self._check_size_limit()
                
            except Exception as e:
                logger.error(f"写入缓存失败: {e}")
    
    def delete(self, key: str) -> bool:
        with self._lock:
            if key not in self._index:
                return False
            
            path = self._key_to_path(key)
            try:
                if path.exists():
                    path.unlink()
                del self._index[key]
                self._save_index()
                return True
            except Exception as e:
                logger.error(f"删除缓存失败: {e}")
                return False
    
    def _check_size_limit(self):
        total_size = sum(m.get("size", 0) for m in self._index.values())
        
        if total_size > self._max_size_bytes:
            sorted_keys = sorted(
                self._index.keys(),
                key=lambda k: self._index[k].get("created_at", 0)
            )
            
            for key in sorted_keys:
                if total_size <= self._max_size_bytes * 0.8:
                    break
                total_size -= self._index[key].get("size", 0)
                self.delete(key)
    
    def cleanup_expired(self) -> int:
        with self._lock:
            now = time.time()
            expired_keys = [
                k for k, v in self._index.items()
                if v.get("expires_at", 0) < now
            ]
            
            for key in expired_keys:
                self.delete(key)
            
            return len(expired_keys)
    
    def clear(self):
        with self._lock:
            for key in list(self._index.keys()):
                path = self._key_to_path(key)
                try:
                    if path.exists():
                        path.unlink()
                except:
                    pass
            self._index.clear()
            self._save_index()
    
    def stats(self) -> Dict[str, Any]:
        total_size = sum(m.get("size", 0) for m in self._index.values())
        
        return {
            "count": len(self._index),
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "max_size_mb": self._max_size_bytes / (1024 * 1024),
        }


class HybridCache:
    _instance: Optional['HybridCache'] = None
    _lock = threading.Lock()
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls, *args, **kwargs)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, memory_max_items: int = 1000, disk_max_mb: int = 2048,
                 default_ttl: int = 300, cache_dir: str = "./cache"):
        if self._initialized:
            return
            
        self._initialized = True
        self._default_ttl = default_ttl
        self._memory_cache = LRUCache(max_size=memory_max_items, default_ttl=default_ttl)
        self._disk_cache = DiskCache(cache_dir=cache_dir, max_size_mb=disk_max_mb, default_ttl=default_ttl * 4)
        self._cleanup_thread: Optional[threading.Thread] = None
        self._optimization_thread: Optional[threading.Thread] = None
        self._running = False
        
        self._cache_stats = {
            'hit_count': 0,
            'miss_count': 0,
            'total_requests': 0,
            'avg_hit_rate': 0.0,
            'memory_usage_mb': 0.0,
            'disk_usage_mb': 0.0,
            'last_cleanup_time': None,
            'last_optimization_time': None,
            'compression_savings_mb': 0.0
        }
        
        self._priority_queue: Dict[str, int] = {}
        self._compression_enabled = True
        self._compression_threshold = 1024  # bytes
        self._smart_eviction_enabled = True
        
        self._start_cleanup_thread()
        self._start_optimization_thread()
    
    def _start_cleanup_thread(self):
        self._running = True
        self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._cleanup_thread.start()
        atexit.register(self._stop_cleanup_thread)
    
    def _start_optimization_thread(self):
        self._optimization_thread = threading.Thread(target=self._optimization_loop, daemon=True)
        self._optimization_thread.start()
        atexit.register(self._stop_optimization_thread)
    
    def _stop_cleanup_thread(self):
        self._running = False
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=5)
    
    def _stop_optimization_thread(self):
        if self._optimization_thread and self._optimization_thread.is_alive():
            self._optimization_thread.join(timeout=5)
    
    def _cleanup_loop(self):
        while self._running:
            try:
                self._memory_cache.cleanup_expired()
                self._disk_cache.cleanup_expired()
                self._update_cache_stats()
                time.sleep(300)
            except Exception as e:
                logger.error(f"缓存清理失败: {e}")
    
    def _optimization_loop(self):
        """缓存优化循环"""
        while self._running:
            try:
                self._optimize_cache()
                time.sleep(600)  # 每10分钟优化一次
            except Exception as e:
                logger.error(f"缓存优化失败: {e}")
    
    def _optimize_cache(self):
        """智能优化缓存"""
        try:
            # 分析缓存性能
            memory_stats = self._memory_cache.stats()
            disk_stats = self._disk_cache.stats()
            
            # 智能调整内存缓存大小
            if memory_stats.get('hit_rate', '0%') < '70%' and memory_stats.get('size', 0) < self._memory_cache._max_size * 0.8:
                # 低命中率且有空间，增加缓存大小
                new_size = min(self._memory_cache._max_size * 1.2, 5000)
                self._memory_cache._max_size = int(new_size)
                logger.info(f"调整内存缓存大小: {self._memory_cache._max_size}")
            
            # 智能压缩
            if self._compression_enabled:
                self._optimize_compression()
            
            # 智能驱逐
            if self._smart_eviction_enabled:
                self._optimize_eviction()
            
            self._cache_stats['last_optimization_time'] = time.time()
            logger.info("缓存优化完成")
        except Exception as e:
            logger.error(f"缓存优化失败: {e}")
    
    def _optimize_compression(self):
        """优化压缩策略"""
        # 这里可以实现智能压缩逻辑
        # 例如根据数据大小和访问频率决定是否压缩
        pass
    
    def _optimize_eviction(self):
        """优化驱逐策略"""
        # 这里可以实现智能驱逐逻辑
        # 例如根据访问模式调整驱逐策略
        pass
    
    def _update_cache_stats(self):
        """更新缓存统计
        
        从内存缓存和磁盘缓存中收集统计信息，
        包括命中率、内存使用和磁盘使用等。
        """
        try:
            # 使用stats()方法获取统计信息，避免直接访问私有属性
            memory_stats = self._memory_cache.stats()
            disk_stats = self._disk_cache.stats()
            
            self._cache_stats['hit_count'] = memory_stats.get('hits', 0)
            self._cache_stats['miss_count'] = memory_stats.get('misses', 0)
            self._cache_stats['total_requests'] = self._cache_stats['hit_count'] + self._cache_stats['miss_count']
            
            if self._cache_stats['total_requests'] > 0:
                self._cache_stats['avg_hit_rate'] = self._cache_stats['hit_count'] / self._cache_stats['total_requests']
            else:
                self._cache_stats['avg_hit_rate'] = 0.0
            
            self._cache_stats['memory_usage_mb'] = memory_stats.get('size', 0) / (1024 * 1024)
            self._cache_stats['disk_usage_mb'] = disk_stats.get('total_size_mb', 0)
            self._cache_stats['last_cleanup_time'] = time.time()
        except Exception as e:
            logger.error(f"更新缓存统计失败: {e}")
    
    def get(self, key: str) -> Optional[Any]:
        value = self._memory_cache.get(key)
        if value is not None:
            return value
        
        value = self._disk_cache.get(key)
        if value is not None:
            self._memory_cache.set(key, value, self._default_ttl)
            return value
        
        return None
    
    def set(self, key: str, value: Any, ttl: int = None, persist: bool = False) -> None:
        self._memory_cache.set(key, value, ttl)
        
        if persist or ttl and ttl > self._default_ttl:
            self._disk_cache.set(key, value, ttl)
    
    def delete(self, key: str) -> bool:
        mem_deleted = self._memory_cache.delete(key)
        disk_deleted = self._disk_cache.delete(key)
        return mem_deleted or disk_deleted
    
    def clear(self):
        self._memory_cache.clear()
        self._disk_cache.clear()
    
    def stats(self) -> Dict[str, Any]:
        return {
            "memory": self._memory_cache.stats(),
            "disk": self._disk_cache.stats(),
        }


def cached(ttl: int = 300, key_prefix: str = "", persist: bool = False):
    """缓存装饰器"""
    def decorator(func: Callable) -> Callable:
        cache = HybridCache()
        
        @wraps(func)
        def wrapper(*args, **kwargs):
            cache_key = f"{key_prefix}:{func.__name__}:{hash(str(args) + str(kwargs))}"
            
            result = cache.get(cache_key)
            if result is not None:
                return result
            
            result = func(*args, **kwargs)
            cache.set(cache_key, result, ttl, persist)
            
            return result
        
        wrapper.cache_clear = lambda: cache.clear()
        wrapper.cache_stats = lambda: cache.stats()
        
        return wrapper
    return decorator


hybrid_cache = HybridCache()

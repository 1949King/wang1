"""
缓存策略优化模块
================
实现智能缓存策略和自适应缓存管理
"""

import os
import logging
import threading
import time
import json
from typing import Optional, Dict, Any, List, Callable, Tuple
from dataclasses import dataclass, field
from enum import Enum
from collections import OrderedDict
from pathlib import Path
import hashlib

from app.core.logging_enhanced import monitor_performance
from app.core.exceptions import CacheError, ErrorCode

logger = logging.getLogger(__name__)


class CacheStrategy(Enum):
    """缓存策略"""
    LRU = "lru"
    LFU = "lfu"
    FIFO = "fifo"
    ADAPTIVE = "adaptive"
    PREDICTIVE = "predictive"


class CacheLevel(Enum):
    """缓存级别"""
    HOT = "hot"
    WARM = "warm"
    COLD = "cold"


@dataclass
class CacheEntry:
    """缓存条目"""
    key: str
    value: Any
    size: int
    level: CacheLevel
    access_count: int = 0
    created_at: float = 0.0
    last_access: float = 0.0
    ttl: float = 300.0
    
    def is_expired(self) -> bool:
        """检查是否过期"""
        return time.time() > self.created_at + self.ttl
    
    def touch(self):
        """更新访问信息"""
        self.access_count += 1
        self.last_access = time.time()
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'key': self.key,
            'size': self.size,
            'level': self.level.value,
            'access_count': self.access_count,
            'created_at': self.created_at,
            'last_access': self.last_access,
            'ttl': self.ttl,
            'is_expired': self.is_expired()
        }


class CachePolicy:
    """缓存策略基类"""
    
    def __init__(self, max_size: int, max_items: int = 1000):
        self.max_size = max_size
        self.max_items = max_items
        self._current_size = 0
        self._lock = threading.RLock()
    
    def should_evict(self, entry: CacheEntry, cache_size: int, 
                   item_count: int) -> bool:
        """判断是否需要驱逐缓存"""
        raise NotImplementedError
    
    def select_eviction_candidate(self, 
                             cache: 'OrderedDict[str, CacheEntry]') -> Optional[str]:
        """选择要驱逐的缓存项"""
        raise NotImplementedError
    
    def update_entry(self, entry: CacheEntry):
        """更新缓存条目信息"""
        entry.touch()


class LRUPolicy(CachePolicy):
    """LRU缓存策略"""
    
    def should_evict(self, entry: CacheEntry, cache_size: int, 
                   item_count: int) -> bool:
        return cache_size >= self.max_size or item_count >= self.max_items
    
    def select_eviction_candidate(self, 
                             cache: 'OrderedDict[str, CacheEntry]') -> Optional[str]:
        if not cache:
            return None
        return next(iter(cache.keys()))
    
    def update_entry(self, entry: CacheEntry):
        super().update_entry(entry)


class LFUPolicy(CachePolicy):
    """LFU缓存策略"""
    
    def should_evict(self, entry: CacheEntry, cache_size: int, 
                   item_count: int) -> bool:
        return cache_size >= self.max_size or item_count >= self.max_items
    
    def select_eviction_candidate(self, 
                             cache: 'OrderedDict[str, CacheEntry]') -> Optional[str]:
        if not cache:
            return None
        
        min_key = min(
            cache.keys(),
            key=lambda k: cache[k].access_count
        )
        return min_key
    
    def update_entry(self, entry: CacheEntry):
        super().update_entry(entry)


class FIFOPolicy(CachePolicy):
    """FIFO缓存策略"""
    
    def should_evict(self, entry: CacheEntry, cache_size: int, 
                   item_count: int) -> bool:
        return cache_size >= self.max_size or item_count >= self.max_items
    
    def select_eviction_candidate(self, 
                             cache: 'OrderedDict[str, CacheEntry]') -> Optional[str]:
        if not cache:
            return None
        return next(iter(cache.keys()))
    
    def update_entry(self, entry: CacheEntry):
        pass


class AdaptivePolicy(CachePolicy):
    """自适应缓存策略"""
    
    def __init__(self, max_size: int, max_items: int = 1000):
        super().__init__(max_size, max_items)
        self._access_history: List[Tuple[str, float]] = []
        self._max_history = 1000
        self._current_strategy = CacheStrategy.LRU
        self._strategy_performance = {
            CacheStrategy.LRU: 0.0,
            CacheStrategy.LFU: 0.0,
            CacheStrategy.FIFO: 0.0
        }
    
    def should_evict(self, entry: CacheEntry, cache_size: int, 
                   item_count: int) -> bool:
        return cache_size >= self.max_size or item_count >= self.max_items
    
    def select_eviction_candidate(self, 
                             cache: 'OrderedDict[str, CacheEntry]') -> Optional[str]:
        if not cache:
            return None
        
        if self._current_strategy == CacheStrategy.LRU:
            return next(iter(cache.keys()))
        elif self._current_strategy == CacheStrategy.LFU:
            min_key = min(
                cache.keys(),
                key=lambda k: cache[k].access_count
            )
            return min_key
        else:
            return next(iter(cache.keys()))
    
    def update_entry(self, entry: CacheEntry):
        super().update_entry(entry)
        self._record_access(entry.key)
        self._evaluate_strategies()
    
    def _record_access(self, key: str):
        """记录访问历史"""
        self._access_history.append((key, time.time()))
        
        if len(self._access_history) > self._max_history:
            self._access_history.pop(0)
    
    def _evaluate_strategies(self):
        """评估各策略性能"""
        if len(self._access_history) < 100:
            return
        
        recent_accesses = self._access_history[-100:]
        
        for strategy in [CacheStrategy.LRU, CacheStrategy.LFU, CacheStrategy.FIFO]:
            performance = self._calculate_strategy_performance(strategy, recent_accesses)
            self._strategy_performance[strategy] = performance
        
        # 选择最佳策略
        best_strategy = max(
            self._strategy_performance.keys(),
            key=lambda s: self._strategy_performance[s]
        )
        
        if best_strategy != self._current_strategy:
            logger.info(f"切换缓存策略: {self._current_strategy.value} -> {best_strategy.value}")
            self._current_strategy = best_strategy
    
    def _calculate_strategy_performance(self, strategy: CacheStrategy,
                                    accesses: List[Tuple[str, float]]) -> float:
        """计算策略性能"""
        if strategy == CacheStrategy.LRU:
            return self._calculate_lru_performance(accesses)
        elif strategy == CacheStrategy.LFU:
            return self._calculate_lfu_performance(accesses)
        elif strategy == CacheStrategy.FIFO:
            return self._calculate_fifo_performance(accesses)
        return 0.0
    
    def _calculate_lru_performance(self, accesses: List[Tuple[str, float]]) -> float:
        """计算LRU策略性能"""
        unique_keys = set(k for k, _ in accesses)
        return len(unique_keys) / len(accesses) if accesses else 0.0
    
    def _calculate_lfu_performance(self, accesses: List[Tuple[str, float]]) -> float:
        """计算LFU策略性能"""
        key_counts = {}
        for key, _ in accesses:
            key_counts[key] = key_counts.get(key, 0) + 1
        
        if not key_counts:
            return 0.0
        
        avg_count = sum(key_counts.values()) / len(key_counts)
        return avg_count / max(key_counts.values()) if key_counts else 0.0
    
    def _calculate_fifo_performance(self, accesses: List[Tuple[str, float]]) -> float:
        """计算FIFO策略性能"""
        return len(set(k for k, _ in accesses)) / len(accesses) if accesses else 0.0


class PredictivePolicy(CachePolicy):
    """预测性缓存策略"""
    
    def __init__(self, max_size: int, max_items: int = 1000):
        super().__init__(max_size, max_items)
        self._access_patterns: Dict[str, List[float]] = {}
        self._prediction_window = 100
    
    def should_evict(self, entry: CacheEntry, cache_size: int, 
                   item_count: int) -> bool:
        return cache_size >= self.max_size or item_count >= self.max_items
    
    def select_eviction_candidate(self, 
                             cache: 'OrderedDict[str, CacheEntry]') -> Optional[str]:
        if not cache:
            return None
        
        # 预测未来访问概率
        predictions = {}
        for key, entry in cache.items():
            predictions[key] = self._predict_access_probability(key)
        
        # 选择访问概率最低的项
        min_key = min(predictions.keys(), key=lambda k: predictions[k])
        return min_key
    
    def update_entry(self, entry: CacheEntry):
        super().update_entry(entry)
        self._update_access_pattern(entry.key)
    
    def _update_access_pattern(self, key: str):
        """更新访问模式"""
        current_time = time.time()
        
        if key not in self._access_patterns:
            self._access_patterns[key] = []
        
        self._access_patterns[key].append(current_time)
        
        # 保留最近N次访问
        if len(self._access_patterns[key]) > self._prediction_window:
            self._access_patterns[key].pop(0)
    
    def _predict_access_probability(self, key: str) -> float:
        """预测访问概率"""
        if key not in self._access_patterns:
            return 0.0
        
        access_times = self._access_patterns[key]
        
        if len(access_times) < 2:
            return 0.5
        
        # 计算访问间隔
        intervals = []
        for i in range(1, len(access_times)):
            interval = access_times[i] - access_times[i-1]
            intervals.append(interval)
        
        if not intervals:
            return 0.5
        
        # 预测下次访问时间
        avg_interval = sum(intervals) / len(intervals)
        last_access = access_times[-1]
        predicted_next_access = last_access + avg_interval
        
        # 计算访问概率
        time_since_last_access = time.time() - last_access
        probability = max(0.0, 1.0 - time_since_last_access / avg_interval)
        
        return probability


class SmartCache:
    """智能缓存系统"""
    
    def __init__(self, max_size_mb: int = 512, 
                 max_items: int = 1000,
                 strategy: CacheStrategy = CacheStrategy.ADAPTIVE):
        self.max_size = max_size_mb * 1024 * 1024
        self.max_items = max_items
        self.strategy = strategy
        
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = threading.RLock()
        
        self._policy = self._create_policy(strategy)
        
        self._stats = {
            'total_requests': 0,
            'hits': 0,
            'misses': 0,
            'evictions': 0,
            'size_by_level': {
                CacheLevel.HOT: 0,
                CacheLevel.WARM: 0,
                CacheLevel.COLD: 0
            },
            'count_by_level': {
                CacheLevel.HOT: 0,
                CacheLevel.WARM: 0,
                CacheLevel.COLD: 0
            }
        }
        
        self._level_thresholds = {
            CacheLevel.HOT: 10,      # 访问次数>=10
            CacheLevel.WARM: 3,      # 访问次数>=3
            CacheLevel.COLD: 0       # 其他
        }
    
    def _create_policy(self, strategy: CacheStrategy) -> CachePolicy:
        """创建缓存策略"""
        if strategy == CacheStrategy.LRU:
            return LRUPolicy(self.max_size, self.max_items)
        elif strategy == CacheStrategy.LFU:
            return LFUPolicy(self.max_size, self.max_items)
        elif strategy == CacheStrategy.FIFO:
            return FIFOPolicy(self.max_size, self.max_items)
        elif strategy == CacheStrategy.ADAPTIVE:
            return AdaptivePolicy(self.max_size, self.max_items)
        elif strategy == CacheStrategy.PREDICTIVE:
            return PredictivePolicy(self.max_size, self.max_items)
        else:
            return AdaptivePolicy(self.max_size, self.max_items)
    
    @monitor_performance(threshold_warning=0.01, threshold_critical=0.05)
    def get(self, key: str) -> Optional[Any]:
        """获取缓存值"""
        with self._lock:
            self._stats['total_requests'] += 1
            
            if key not in self._cache:
                self._stats['misses'] += 1
                return None
            
            entry = self._cache[key]
            
            if entry.is_expired():
                self._remove_entry(key)
                self._stats['misses'] += 1
                return None
            
            self._policy.update_entry(entry)
            self._stats['hits'] += 1
            
            return entry.value
    
    def set(self, key: str, value: Any, ttl: float = 300.0,
            force_update: bool = False) -> bool:
        """设置缓存值
        
        Args:
            key: 缓存键
            value: 缓存值
            ttl: 生存时间（秒）
            force_update: 是否强制更新
        
        Returns:
            是否设置成功
        """
        with self._lock:
            # 检查是否需要驱逐
            if key in self._cache and not force_update:
                return False
            
            # 估算大小
            size = self._estimate_size(value)
            
            # 检查是否需要驱逐旧缓存
            current_size = sum(entry.size for entry in self._cache.values())
            if self._policy.should_evict(None, current_size + size, len(self._cache)):
                self._evict_entries(size)
            
            # 创建缓存条目
            entry = CacheEntry(
                key=key,
                value=value,
                size=size,
                level=self._determine_level(0),
                created_at=time.time(),
                last_access=time.time(),
                ttl=ttl
            )
            
            self._cache[key] = entry
            self._update_level_stats(entry)
            
            return True
    
    def delete(self, key: str) -> bool:
        """删除缓存项"""
        with self._lock:
            if key not in self._cache:
                return False
            
            entry = self._cache[key]
            self._remove_entry(key)
            
            return True
    
    def _remove_entry(self, key: str):
        """移除缓存条目"""
        if key not in self._cache:
            return
        
        entry = self._cache[key]
        self._update_level_stats(entry, remove=True)
        del self._cache[key]
    
    def _evict_entries(self, required_size: int):
        """驱逐缓存项"""
        evicted_count = 0
        freed_size = 0
        
        while freed_size < required_size and self._cache:
            key = self._policy.select_eviction_candidate(self._cache)
            if key is None:
                break
            
            entry = self._cache[key]
            freed_size += entry.size
            self._remove_entry(key)
            evicted_count += 1
            self._stats['evictions'] += 1
        
        logger.debug(f"驱逐了 {evicted_count} 个缓存项，释放 {freed_size} 字节")
    
    def _determine_level(self, access_count: int) -> CacheLevel:
        """确定缓存级别"""
        if access_count >= self._level_thresholds[CacheLevel.HOT]:
            return CacheLevel.HOT
        elif access_count >= self._level_thresholds[CacheLevel.WARM]:
            return CacheLevel.WARM
        else:
            return CacheLevel.COLD
    
    def _update_level_stats(self, entry: CacheEntry, remove: bool = False):
        """更新级别统计"""
        level = entry.level
        multiplier = -1 if remove else 1
        
        self._stats['size_by_level'][level] += entry.size * multiplier
        self._stats['count_by_level'][level] += multiplier
    
    def _estimate_size(self, value: Any) -> int:
        """估算数据大小"""
        try:
            import pickle
            return len(pickle.dumps(value))
        except:
            if isinstance(value, str):
                return len(value.encode('utf-8'))
            elif isinstance(value, (list, tuple)):
                return sum(self._estimate_size(item) for item in value)
            elif isinstance(value, dict):
                return sum(self._estimate_size(k) + self._estimate_size(v) 
                           for k, v in value.items())
            else:
                return 0
    
    def clear(self):
        """清空缓存"""
        with self._lock:
            self._cache.clear()
            
            for level in self._stats['size_by_level']:
                self._stats['size_by_level'][level] = 0
            for level in self._stats['count_by_level']:
                self._stats['count_by_level'][level] = 0
            
            logger.info("智能缓存已清空")
    
    def cleanup_expired(self) -> int:
        """清理过期缓存"""
        with self._lock:
            expired_keys = [
                key for key, entry in self._cache.items()
                if entry.is_expired()
            ]
            
            for key in expired_keys:
                self._remove_entry(key)
            
            logger.info(f"清理了 {len(expired_keys)} 个过期缓存项")
            return len(expired_keys)
    
    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        with self._lock:
            total_requests = self._stats['total_requests']
            hit_rate = self._stats['hits'] / total_requests if total_requests > 0 else 0.0
            
            current_size = sum(entry.size for entry in self._cache.values())
            
            return {
                'total_items': len(self._cache),
                'max_items': self._max_items,
                'current_size_mb': current_size / (1024 * 1024),
                'max_size_mb': self.max_size / (1024 * 1024),
                'total_requests': total_requests,
                'hits': self._stats['hits'],
                'misses': self._stats['misses'],
                'hit_rate': f"{hit_rate:.2%}",
                'evictions': self._stats['evictions'],
                'strategy': self.strategy.value,
                'size_by_level': {
                    level.value: size / (1024 * 1024)
                    for level, size in self._stats['size_by_level'].items()
                },
                'count_by_level': {
                    level.value: count
                    for level, count in self._stats['count_by_level'].items()
                }
            }
    
    def optimize(self):
        """优化缓存"""
        with self._lock:
            # 清理过期项
            self.cleanup_expired()
            
            # 重新计算缓存级别
            for key, entry in self._cache.items():
                old_level = entry.level
                new_level = self._determine_level(entry.access_count)
                
                if old_level != new_level:
                    entry.level = new_level
                    self._update_level_stats(entry, remove=True)
                    self._update_level_stats(entry)
            
            logger.info("缓存优化完成")


# 全局实例
_global_smart_cache: Optional[SmartCache] = None


def get_smart_cache(max_size_mb: int = 512,
                  max_items: int = 1000,
                  strategy: CacheStrategy = CacheStrategy.ADAPTIVE) -> SmartCache:
    """获取全局智能缓存"""
    global _global_smart_cache
    
    if _global_smart_cache is None:
        _global_smart_cache = SmartCache(max_size_mb, max_items, strategy)
    
    return _global_smart_cache


def optimize_cache_system():
    """优化缓存系统"""
    logger.info("开始优化缓存系统...")
    
    cache = get_smart_cache()
    cache.optimize()
    
    stats = cache.get_stats()
    logger.info(f"缓存系统优化完成: {stats}")
    
    return stats
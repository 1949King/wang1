"""
缓存安全增强模块
================
为现有缓存系统添加安全清理机制和监控功能

B2 收敛标记 (2026-05-31):
本文件是 cache 监控/清理增强 (CacheMonitorMetrics / CacheMonitor / SafeCacheCleaner)
与 core/cache_system.py 和 core/cache_strategy_optimization.py 功能不重叠
保留但标记为扩展层, 监控告警接入主程序待 #C 任务
"""

import os
import time
import threading
import logging
from typing import Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from app.core.cache_system import DiskCache, LRUCache, HybridCache

logger = logging.getLogger(__name__)


@dataclass
class CacheMonitorMetrics:
    """缓存监控指标"""
    timestamp: float
    memory_hits: int
    memory_misses: int
    disk_count: int
    disk_size_mb: float
    cleanup_count: int
    error_count: int
    last_cleanup_time: Optional[float] = None


class CacheMonitor:
    """缓存监控器"""
    
    def __init__(self, cache: HybridCache, monitor_interval: int = 60):
        self._cache = cache
        self._monitor_interval = monitor_interval
        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._metrics_history: list = []
        self._max_history_size = 1000
        self._alert_callbacks: list = []
        self._lock = threading.Lock()
        
        self._cleanup_count = 0
        self._error_count = 0
        
        self._thresholds = {
            'memory_usage_warning': 0.8,
            'memory_usage_critical': 0.9,
            'disk_usage_warning': 0.8,
            'disk_usage_critical': 0.9,
            'hit_rate_warning': 0.5,
            'error_rate_warning': 0.1
        }
    
    def start(self):
        """启动监控"""
        if self._running:
            logger.warning("缓存监控器已在运行")
            return
        
        self._running = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
        logger.info("缓存监控器已启动")
    
    def stop(self):
        """停止监控"""
        if not self._running:
            return
        
        self._running = False
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=5)
        logger.info("缓存监控器已停止")
    
    def _monitor_loop(self):
        """监控循环"""
        while self._running:
            try:
                metrics = self._collect_metrics()
                self._store_metrics(metrics)
                self._check_alerts(metrics)
            except Exception as e:
                self._error_count += 1
                logger.error(f"缓存监控异常: {e}")
            
            time.sleep(self._monitor_interval)
    
    def _collect_metrics(self) -> CacheMonitorMetrics:
        """收集监控指标"""
        stats = self._cache.stats()
        memory_stats = stats.get('memory', {})
        disk_stats = stats.get('disk', {})
        
        return CacheMonitorMetrics(
            timestamp=time.time(),
            memory_hits=memory_stats.get('hits', 0),
            memory_misses=memory_stats.get('misses', 0),
            disk_count=disk_stats.get('count', 0),
            disk_size_mb=disk_stats.get('total_size_mb', 0),
            cleanup_count=self._cleanup_count,
            error_count=self._error_count,
            last_cleanup_time=getattr(self._cache, '_cache_stats', {}).get('last_cleanup_time')
        )
    
    def _store_metrics(self, metrics: CacheMonitorMetrics):
        """存储监控指标"""
        with self._lock:
            self._metrics_history.append(metrics)
            if len(self._metrics_history) > self._max_history_size:
                self._metrics_history.pop(0)
    
    def _check_alerts(self, metrics: CacheMonitorMetrics):
        """检查告警条件"""
        stats = self._cache.stats()
        
        # 检查内存使用率
        memory_stats = stats.get('memory', {})
        memory_size = memory_stats.get('size', 0)
        memory_max = memory_stats.get('max_size', 1)
        if memory_max > 0:
            memory_usage = memory_size / memory_max
            if memory_usage > self._thresholds['memory_usage_critical']:
                self._trigger_alert('critical', f"内存使用率过高: {memory_usage:.2%}")
            elif memory_usage > self._thresholds['memory_usage_warning']:
                self._trigger_alert('warning', f"内存使用率较高: {memory_usage:.2%}")
        
        # 检查磁盘使用率
        disk_stats = stats.get('disk', {})
        disk_size = disk_stats.get('total_size_mb', 0)
        disk_max = disk_stats.get('max_size_mb', 1)
        if disk_max > 0:
            disk_usage = disk_size / disk_max
            if disk_usage > self._thresholds['disk_usage_critical']:
                self._trigger_alert('critical', f"磁盘使用率过高: {disk_usage:.2%}")
            elif disk_usage > self._thresholds['disk_usage_warning']:
                self._trigger_alert('warning', f"磁盘使用率较高: {disk_usage:.2%}")
        
        # 检查命中率
        total_requests = metrics.memory_hits + metrics.memory_misses
        if total_requests > 0:
            hit_rate = metrics.memory_hits / total_requests
            if hit_rate < self._thresholds['hit_rate_warning']:
                self._trigger_alert('warning', f"缓存命中率过低: {hit_rate:.2%}")
    
    def _trigger_alert(self, level: str, message: str):
        """触发告警"""
        alert = {
            'level': level,
            'message': message,
            'timestamp': time.time()
        }
        
        logger.warning(f"缓存告警 [{level}]: {message}")
        
        for callback in self._alert_callbacks:
            try:
                callback(alert)
            except Exception as e:
                logger.error(f"告警回调执行失败: {e}")
    
    def add_alert_callback(self, callback: Callable[[Dict], None]):
        """添加告警回调"""
        self._alert_callbacks.append(callback)
    
    def get_metrics_history(self, limit: int = 100) -> list:
        """获取监控指标历史"""
        with self._lock:
            return self._metrics_history[-limit:]
    
    def get_current_metrics(self) -> Optional[CacheMonitorMetrics]:
        """获取当前监控指标"""
        with self._lock:
            return self._metrics_history[-1] if self._metrics_history else None
    
    def get_summary(self) -> Dict[str, Any]:
        """获取监控摘要"""
        with self._lock:
            if not self._metrics_history:
                return {}
            
            latest = self._metrics_history[-1]
            stats = self._cache.stats()
            
            total_requests = latest.memory_hits + latest.memory_misses
            hit_rate = latest.memory_hits / total_requests if total_requests > 0 else 0
            
            return {
                'timestamp': latest.timestamp,
                'memory_hit_rate': f"{hit_rate:.2%}",
                'memory_hits': latest.memory_hits,
                'memory_misses': latest.memory_misses,
                'disk_count': latest.disk_count,
                'disk_size_mb': latest.disk_size_mb,
                'cleanup_count': latest.cleanup_count,
                'error_count': latest.error_count,
                'last_cleanup_time': latest.last_cleanup_time,
                'stats': stats
            }


class SafeCacheCleaner:
    """安全缓存清理器"""
    
    def __init__(self, cache: HybridCache, monitor: CacheMonitor):
        self._cache = cache
        self._monitor = monitor
        self._lock = threading.Lock()
        self._cleanup_stats = {
            'total_cleanups': 0,
            'successful_cleanups': 0,
            'failed_cleanups': 0,
            'items_cleaned': 0,
            'last_cleanup_time': None,
            'last_cleanup_error': None
        }
    
    def safe_cleanup(self, max_retries: int = 3, delay: float = 1.0) -> int:
        """安全的清理方法，带有重试机制
        
        Args:
            max_retries: 最大重试次数
            delay: 重试延迟（秒）
        
        Returns:
            成功清理的缓存项数量
        """
        cleaned_count = 0
        last_error = None
        
        with self._lock:
            self._cleanup_stats['total_cleanups'] += 1
        
        for attempt in range(max_retries):
            try:
                # 清理内存缓存
                memory_cleaned = self._cache._memory_cache.cleanup_expired()
                
                # 清理磁盘缓存
                disk_cleaned = self._cache._disk_cache.cleanup_expired()
                
                cleaned_count = memory_cleaned + disk_cleaned
                
                with self._lock:
                    self._cleanup_stats['successful_cleanups'] += 1
                    self._cleanup_stats['items_cleaned'] += cleaned_count
                    self._cleanup_stats['last_cleanup_time'] = time.time()
                    self._cleanup_stats['last_cleanup_error'] = None
                
                logger.info(f"安全清理完成，清理了 {cleaned_count} 个过期项")
                return cleaned_count
                
            except Exception as e:
                last_error = e
                with self._lock:
                    self._cleanup_stats['failed_cleanups'] += 1
                    self._cleanup_stats['last_cleanup_error'] = str(e)
                
                logger.warning(f"清理尝试 {attempt + 1}/{max_retries} 失败: {e}")
                if attempt < max_retries - 1:
                    time.sleep(delay)
        
        logger.error(f"安全清理失败，已重试 {max_retries} 次，最后错误: {last_error}")
        return cleaned_count
    
    def emergency_cleanup(self) -> int:
        """紧急清理，清空所有缓存
        
        Returns:
            清理的缓存项数量
        """
        try:
            stats_before = self._cache.stats()
            memory_size_before = stats_before.get('memory', {}).get('size', 0)
            disk_count_before = stats_before.get('disk', {}).get('count', 0)
            
            # 清空所有缓存
            self._cache.clear()
            
            with self._lock:
                self._cleanup_stats['items_cleaned'] += memory_size_before + disk_count_before
                self._cleanup_stats['last_cleanup_time'] = time.time()
                self._cleanup_stats['last_cleanup_error'] = None
            
            logger.warning(f"紧急清理完成，清空了 {memory_size_before + disk_count_before} 个缓存项")
            return memory_size_before + disk_count_before
            
        except Exception as e:
            with self._lock:
                self._cleanup_stats['failed_cleanups'] += 1
                self._cleanup_stats['last_cleanup_error'] = str(e)
            
            logger.error(f"紧急清理失败: {e}")
            return 0
    
    def get_cleanup_stats(self) -> Dict[str, Any]:
        """获取清理统计信息"""
        with self._lock:
            return self._cleanup_stats.copy()


def create_enhanced_cache_system(
    memory_max_items: int = 1000,
    disk_max_mb: int = 2048,
    default_ttl: int = 300,
    cache_dir: str = "./cache",
    enable_monitoring: bool = True,
    monitor_interval: int = 60
) -> tuple:
    """创建增强的缓存系统
    
    Args:
        memory_max_items: 内存缓存最大项目数
        disk_max_mb: 磁盘缓存最大大小（MB）
        default_ttl: 默认TTL（秒）
        cache_dir: 缓存目录
        enable_monitoring: 是否启用监控
        monitor_interval: 监控间隔（秒）
    
    Returns:
        (cache, monitor, cleaner) 缓存实例、监控器、清理器
    """
    cache = HybridCache(
        memory_max_items=memory_max_items,
        disk_max_mb=disk_max_mb,
        default_ttl=default_ttl,
        cache_dir=cache_dir
    )
    
    monitor = None
    cleaner = None
    
    if enable_monitoring:
        monitor = CacheMonitor(cache, monitor_interval)
        cleaner = SafeCacheCleaner(cache, monitor)
        monitor.start()
    
    return cache, monitor, cleaner


# 全局增强缓存系统实例
_enhanced_cache = None
_cache_monitor = None
_cache_cleaner = None


def get_enhanced_cache_system() -> tuple:
    """获取全局增强缓存系统"""
    global _enhanced_cache, _cache_monitor, _cache_cleaner
    
    if _enhanced_cache is None:
        _enhanced_cache, _cache_monitor, _cache_cleaner = create_enhanced_cache_system()
    
    return _enhanced_cache, _cache_monitor, _cache_cleaner
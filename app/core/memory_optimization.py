"""
流式处理和内存管理优化模块
============================
实现高效的流式处理和智能内存管理
"""

import os
import logging
import threading
import time
import gc
import atexit
from typing import Optional, Dict, Any, List, Callable, Iterator, Tuple
from dataclasses import dataclass, field
from enum import Enum
from collections import OrderedDict
import numpy as np
from pathlib import Path

from app.core.logging_enhanced import monitor_performance
from app.core.exceptions import RenderError, ErrorCode

logger = logging.getLogger(__name__)


class MemoryStrategy(Enum):
    """内存管理策略"""
    LRU = "lru"
    FIFO = "fifo"
    LFU = "lfu"
    ADAPTIVE = "adaptive"


@dataclass
class MemoryBlock:
    """内存块"""
    key: str
    data: Any
    size: int
    timestamp: float
    access_count: int = 0
    last_access: float = 0.0
    
    def touch(self):
        """更新访问信息"""
        self.access_count += 1
        self.last_access = time.time()


class MemoryPool:
    """内存池管理器"""
    
    def __init__(self, max_size_mb: int = 512, strategy: MemoryStrategy = MemoryStrategy.ADAPTIVE):
        self.max_size = max_size_mb * 1024 * 1024
        self.current_size = 0
        self.strategy = strategy
        self._blocks: OrderedDict[str, MemoryBlock] = OrderedDict()
        self._lock = threading.RLock()
        self._monitor_thread = None
        self._running = False
        
        self._stats = {
            'total_allocations': 0,
            'total_deallocations': 0,
            'evictions': 0,
            'hits': 0,
            'misses': 0,
            'memory_pressure': 0.0,
            'last_optimization': 0.0
        }
        
        self._adaptive_thresholds = {
            'low_usage': 0.4,
            'high_usage': 0.7,
            'critical_usage': 0.9,
            'eviction_batch_size': 10,
            'monitor_interval': 5.0
        }
        
        self._start_monitor()
        atexit.register(self._stop_monitor)
    
    def allocate(self, key: str, data: Any, size: Optional[int] = None) -> bool:
        """分配内存
        
        Args:
            key: 内存块键
            data: 数据对象
            size: 数据大小（字节），如果为None则自动计算
        
        Returns:
            是否分配成功
        """
        if size is None:
            size = self._estimate_size(data)
        
        with self._lock:
            # 检查是否已存在
            if key in self._blocks:
                self._blocks[key].data = data
                self._blocks[key].size = size
                self._blocks[key].touch()
                self._stats['hits'] += 1
                return True
            
            # 检查内存是否足够
            if self.current_size + size > self.max_size:
                # 清理内存
                if not self._cleanup(size):
                    logger.warning(f"内存不足，无法分配: {key} (需要: {size} 字节)")
                    self._stats['misses'] += 1
                    return False
            
            # 创建内存块
            block = MemoryBlock(
                key=key,
                data=data,
                size=size,
                timestamp=time.time()
            )
            
            self._blocks[key] = block
            self.current_size += size
            self._stats['total_allocations'] += 1
            
            logger.debug(f"分配内存: {key} (大小: {size} 字节)")
            return True
    
    def deallocate(self, key: str) -> bool:
        """释放内存
        
        Args:
            key: 内存块键
        
        Returns:
            是否释放成功
        """
        with self._lock:
            if key in self._blocks:
                block = self._blocks[key]
                self.current_size -= block.size
                del self._blocks[key]
                self._stats['total_deallocations'] += 1
                
                # 手动释放内存
                del block.data
                
                logger.debug(f"释放内存: {key} (大小: {block.size} 字节)")
                return True
            
            return False
    
    def get(self, key: str) -> Optional[Any]:
        """获取内存块数据
        
        Args:
            key: 内存块键
        
        Returns:
            数据对象或None
        """
        with self._lock:
            if key in self._blocks:
                block = self._blocks[key]
                block.touch()
                self._stats['hits'] += 1
                return block.data
            
            self._stats['misses'] += 1
            return None
    
    def _cleanup(self, required_size: int) -> bool:
        """清理内存
        
        Args:
            required_size: 需要的内存大小
        
        Returns:
            是否清理成功
        """
        if self.strategy == MemoryStrategy.LRU:
            return self._cleanup_lru(required_size)
        elif self.strategy == MemoryStrategy.FIFO:
            return self._cleanup_fifo(required_size)
        elif self.strategy == MemoryStrategy.LFU:
            return self._cleanup_lfu(required_size)
        elif self.strategy == MemoryStrategy.ADAPTIVE:
            return self._cleanup_adaptive(required_size)
        else:
            return self._cleanup_lru(required_size)
    
    def _cleanup_lru(self, required_size: int) -> bool:
        """LRU清理策略"""
        freed = 0
        keys_to_remove = []
        
        for key in list(self._blocks.keys()):
            if freed >= required_size:
                break
            
            block = self._blocks[key]
            freed += block.size
            keys_to_remove.append(key)
        
        for key in keys_to_remove:
            self.deallocate(key)
            self._stats['evictions'] += 1
        
        return freed >= required_size
    
    def _cleanup_fifo(self, required_size: int) -> bool:
        """FIFO清理策略"""
        freed = 0
        keys_to_remove = []
        
        for key in list(self._blocks.keys()):
            if freed >= required_size:
                break
            
            block = self._blocks[key]
            freed += block.size
            keys_to_remove.append(key)
        
        for key in keys_to_remove:
            self.deallocate(key)
            self._stats['evictions'] += 1
        
        return freed >= required_size
    
    def _cleanup_lfu(self, required_size: int) -> bool:
        """LFU清理策略"""
        freed = 0
        keys_to_remove = []
        
        # 按访问频率排序
        sorted_blocks = sorted(
            self._blocks.items(),
            key=lambda x: x[1].access_count
        )
        
        for key, block in sorted_blocks:
            if freed >= required_size:
                break
            
            freed += block.size
            keys_to_remove.append(key)
        
        for key in keys_to_remove:
            self.deallocate(key)
            self._stats['evictions'] += 1
        
        return freed >= required_size
    
    def _cleanup_adaptive(self, required_size: int) -> bool:
        """自适应清理策略"""
        usage_ratio = self.current_size / self.max_size
        
        if usage_ratio < self._adaptive_thresholds['low_usage']:
            # 低使用率，使用FIFO
            return self._cleanup_fifo(required_size)
        elif usage_ratio > self._adaptive_thresholds['high_usage']:
            # 高使用率，使用LRU
            return self._cleanup_lru(required_size)
        else:
            # 中等使用率，使用LFU
            return self._cleanup_lfu(required_size)
    
    def _estimate_size(self, data: Any) -> int:
        """估算数据大小"""
        try:
            if isinstance(data, np.ndarray):
                return data.nbytes
            elif isinstance(data, (str, bytes)):
                return len(data)
            elif isinstance(data, (list, tuple)):
                return sum(self._estimate_size(item) for item in data)
            elif isinstance(data, dict):
                return sum(self._estimate_size(k) + self._estimate_size(v) 
                           for k, v in data.items())
            else:
                # 使用pickle估算
                import pickle
                return len(pickle.dumps(data))
        except Exception:
            pass
            return 0
    
    def clear(self):
        """清空内存池"""
        with self._lock:
            keys = list(self._blocks.keys())
            for key in keys:
                self.deallocate(key)
            
            logger.info("内存池已清空")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取内存池统计信息"""
        with self._lock:
            total_requests = self._stats['hits'] + self._stats['misses']
            hit_rate = self._stats['hits'] / total_requests if total_requests > 0 else 0
            usage_ratio = self.current_size / self.max_size if self.max_size > 0 else 0
            memory_pressure = self._stats['memory_pressure']
            
            return {
                'max_size_mb': self.max_size / (1024 * 1024),
                'current_size_mb': self.current_size / (1024 * 1024),
                'usage_ratio': f"{usage_ratio:.2%}",
                'memory_pressure': f"{memory_pressure:.2%}",
                'block_count': len(self._blocks),
                'total_allocations': self._stats['total_allocations'],
                'total_deallocations': self._stats['total_deallocations'],
                'evictions': self._stats['evictions'],
                'hits': self._stats['hits'],
                'misses': self._stats['misses'],
                'hit_rate': f"{hit_rate:.2%}",
                'strategy': self.strategy.value,
                'last_optimization': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self._stats['last_optimization'])) if self._stats['last_optimization'] > 0 else 'Never'
            }
    
    def _start_monitor(self):
        """启动内存监控线程"""
        self._running = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
    
    def _stop_monitor(self):
        """停止内存监控线程"""
        self._running = False
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=5)
    
    def _monitor_loop(self):
        """内存监控循环"""
        while self._running:
            try:
                self._check_memory_pressure()
                time.sleep(self._adaptive_thresholds['monitor_interval'])
            except Exception as e:
                logger.error(f"内存监控失败: {e}")
    
    def _check_memory_pressure(self):
        """检查内存压力并自动优化"""
        with self._lock:
            usage_ratio = self.current_size / self.max_size if self.max_size > 0 else 0
            self._stats['memory_pressure'] = usage_ratio
            
            # 根据内存压力自动优化
            if usage_ratio > self._adaptive_thresholds['critical_usage']:
                # 严重内存压力，立即清理
                self._emergency_cleanup()
            elif usage_ratio > self._adaptive_thresholds['high_usage']:
                # 高内存压力，主动清理
                self.optimize_memory()
    
    def _emergency_cleanup(self):
        """紧急内存清理"""
        freed = 0
        target_size = self.max_size * self._adaptive_thresholds['low_usage']
        keys_to_remove = []
        
        # 按最后访问时间排序，优先清理最久未使用的
        sorted_blocks = sorted(
            self._blocks.items(),
            key=lambda x: x[1].last_access
        )
        
        for key, block in sorted_blocks:
            if self.current_size - freed <= target_size:
                break
            freed += block.size
            keys_to_remove.append(key)
        
        for key in keys_to_remove:
            self.deallocate(key)
            self._stats['evictions'] += 1
        
        if keys_to_remove:
            logger.warning(f"紧急内存清理，释放了 {freed / (1024 * 1024):.2f} MB 内存")
    
    def optimize_memory(self):
        """优化内存使用"""
        with self._lock:
            # 触发垃圾回收
            gc.collect()
            
            # 清理未使用的内存块
            current_time = time.time()
            keys_to_remove = []
            
            for key, block in self._blocks.items():
                # 清理超过30分钟未访问的块
                if current_time - block.last_access > 1800:
                    keys_to_remove.append(key)
            
            for key in keys_to_remove:
                self.deallocate(key)
            
            if keys_to_remove:
                freed = sum(self._blocks[key].size for key in keys_to_remove)
                logger.info(f"优化内存，清理了 {len(keys_to_remove)} 个未使用块，释放 {freed / (1024 * 1024):.2f} MB")
                
            self._stats['last_optimization'] = current_time


class StreamingProcessor:
    """流式处理器"""
    
    def __init__(self, chunk_size: int = 1024 * 1024):
        self.chunk_size = chunk_size
        self._memory_pool = MemoryPool(max_size_mb=256, strategy=MemoryStrategy.LRU)
        self._processing_stats = {
            'total_chunks': 0,
            'total_bytes': 0,
            'processing_time': 0.0
        }
    
    @monitor_performance(threshold_warning=1.0, threshold_critical=5.0)
    def process_stream(self, input_path: str, 
                     output_path: str,
                     process_func: Callable,
                     chunk_size: Optional[int] = None) -> bool:
        """流式处理文件
        
        Args:
            input_path: 输入文件路径
            output_path: 输出文件路径
            process_func: 处理函数
            chunk_size: 块大小
        
        Returns:
            是否处理成功
        """
        chunk_size = chunk_size or self.chunk_size
        
        logger.info(f"开始流式处理: {input_path} -> {output_path}")
        
        try:
            # 创建输出目录
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            # 流式读取和处理
            with open(input_path, 'rb') as input_file:
                with open(output_path, 'wb') as output_file:
                    chunk_number = 0
                    
                    while True:
                        chunk = input_file.read(chunk_size)
                        if not chunk:
                            break
                        
                        # 处理块
                        processed_chunk = process_func(chunk, chunk_number)
                        
                        # 写入输出
                        output_file.write(processed_chunk)
                        
                        # 更新统计
                        self._processing_stats['total_chunks'] += 1
                        self._processing_stats['total_bytes'] += len(chunk)
                        
                        chunk_number += 1
                        
                        # 定期优化内存
                        if chunk_number % 100 == 0:
                            self._memory_pool.optimize_memory()
            
            logger.info(f"流式处理完成: {chunk_number} 个块")
            return True
            
        except Exception as e:
            logger.error(f"流式处理失败: {e}")
            raise RenderError(
                ErrorCode.RENDER_ERROR,
                f"流式处理失败: {str(e)}",
                details={'input_path': input_path, 'output_path': output_path}
            )
    
    def process_video_stream(self, input_path: str,
                         output_path: str,
                         process_func: Callable,
                         frame_callback: Optional[Callable] = None) -> bool:
        """流式处理视频文件
        
        Args:
            input_path: 输入视频路径
            output_path: 输出视频路径
            process_func: 处理函数
            frame_callback: 帧回调函数
        
        Returns:
            是否处理成功
        """
        logger.info(f"开始流式处理视频: {input_path}")
        
        try:
            import cv2
            
            # 打开视频文件
            cap = cv2.VideoCapture(input_path)
            if not cap.isOpened():
                raise RenderError(
                    ErrorCode.VIDEO_LOAD_ERROR,
                    f"无法打开视频文件: {input_path}"
                )
            
            # 获取视频信息
            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            
            # 创建视频写入器
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
            
            # 流式处理帧
            frame_number = 0
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                
                # 处理帧
                processed_frame = process_func(frame, frame_number)
                
                # 写入输出
                out.write(processed_frame)
                
                # 帧回调
                if frame_callback:
                    frame_callback(frame_number, frame_count)
                
                # 更新统计
                self._processing_stats['total_chunks'] += 1
                
                frame_number += 1
                
                # 定期优化内存
                if frame_number % 100 == 0:
                    self._memory_pool.optimize_memory()
            
            # 释放资源
            cap.release()
            out.release()
            
            logger.info(f"视频流式处理完成: {frame_number} 帧")
            return True
            
        except Exception as e:
            logger.error(f"视频流式处理失败: {e}")
            raise RenderError(
                ErrorCode.VIDEO_RENDER_ERROR,
                f"视频流式处理失败: {str(e)}",
                details={'input_path': input_path}
            )
    
    def process_frames_stream(self, input_path: str,
                          process_func: Callable,
                          batch_size: int = 10) -> Iterator[Any]:
        """流式处理视频帧
        
        Args:
            input_path: 输入视频路径
            process_func: 处理函数
            batch_size: 批次大小
        
        Yields:
            处理结果
        """
        logger.info(f"开始流式处理视频帧: {input_path}")
        
        try:
            import cv2
            
            # 打开视频文件
            cap = cv2.VideoCapture(input_path)
            if not cap.isOpened():
                raise RenderError(
                    ErrorCode.VIDEO_LOAD_ERROR,
                    f"无法打开视频文件: {input_path}"
                )
            
            # 流式读取和处理帧
            frame_batch = []
            frame_number = 0
            
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                
                frame_batch.append(frame)
                
                # 批次处理
                if len(frame_batch) >= batch_size:
                    results = process_func(frame_batch, frame_number)
                    yield results
                    frame_batch = []
                    
                    # 定期优化内存
                    if frame_number % 100 == 0:
                        self._memory_pool.optimize_memory()
                
                frame_number += 1
            
            # 处理剩余帧
            if frame_batch:
                results = process_func(frame_batch, frame_number)
                yield results
            
            # 释放资源
            cap.release()
            
            logger.info(f"视频帧流式处理完成: {frame_number} 帧")
            
        except Exception as e:
            logger.error(f"视频帧流式处理失败: {e}")
            raise
    
    def get_memory_pool(self) -> MemoryPool:
        """获取内存池"""
        return self._memory_pool
    
    def get_processing_stats(self) -> Dict[str, Any]:
        """获取处理统计信息"""
        return self._processing_stats.copy()
    
    def reset_stats(self):
        """重置统计信息"""
        self._processing_stats = {
            'total_chunks': 0,
            'total_bytes': 0,
            'processing_time': 0.0
        }


# 全局实例
_global_memory_pool: Optional[MemoryPool] = None
_global_streaming_processor: Optional[StreamingProcessor] = None


def get_memory_pool(max_size_mb: int = 512,
                  strategy: MemoryStrategy = MemoryStrategy.LRU) -> MemoryPool:
    """获取全局内存池"""
    global _global_memory_pool
    
    if _global_memory_pool is None:
        _global_memory_pool = MemoryPool(max_size_mb, strategy)
    
    return _global_memory_pool


def get_streaming_processor(chunk_size: int = 1024 * 1024) -> StreamingProcessor:
    """获取全局流式处理器"""
    global _global_streaming_processor
    
    if _global_streaming_processor is None:
        _global_streaming_processor = StreamingProcessor(chunk_size)
    
    return _global_streaming_processor


def optimize_system_memory():
    """优化系统内存"""
    logger.info("开始优化系统内存...")
    
    # 触发垃圾回收
    gc.collect()
    
    # 获取内存池并优化
    memory_pool = get_memory_pool()
    memory_pool.optimize_memory()
    
    # 获取内存统计
    stats = memory_pool.get_stats()
    logger.info(f"内存优化完成: {stats}")
    
    return stats
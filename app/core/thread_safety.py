"""
线程安全工具模块 - Week 2核心组件
==================================
提供线程安全的资源访问、锁管理、同步原语
目标：解决多线程竞争、死锁、资源冲突问题
"""

import threading
import time
from typing import Optional, Callable, Any, Dict
from contextlib import contextmanager
from dataclasses import dataclass, field

from app.modules.utils.logger import logger

@dataclass
class LockInfo:
    """锁信息"""
    lock: threading.Lock
    name: str
    acquire_count: int = 0
    wait_time: float = 0.0
    held_time: float = 0.0

class ThreadSafetyManager:
    """线程安全管理器"""
    
    def __init__(self):
        self._locks: Dict[str, threading.Lock] = {}
        self._lock_stats: Dict[str, LockInfo] = {}
        self._manager_lock = threading.Lock()
        self._deadlock_detector = DeadlockDetector()
        
        logger.info("线程安全管理器初始化")
    
    def create_lock(self, name: str, timeout: Optional[float] = None) -> threading.Lock:
        """创建命名锁
        
        Args:
            name: 锁名称
            timeout: 获取锁的超时时间（秒）
            
        Returns:
            线程锁对象
        """
        with self._manager_lock:
            if name not in self._locks:
                lock = threading.Lock()
                self._locks[name] = lock
                self._lock_stats[name] = LockInfo(
                    lock=lock,
                    name=name,
                    acquire_count=0,
                    wait_time=0.0,
                    held_time=0.0
                )
                logger.debug(f"创建锁: {name}")
                return lock
            
            return self._locks[name]
    
    def acquire_lock(self, name: str, timeout: Optional[float] = None) -> bool:
        """获取锁"""
        lock_info = self._lock_stats.get(name)
        if not lock_info:
            logger.warning(f"锁不存在: {name}")
            return False
        
        start_time = time.time()
        
        try:
            acquired = lock_info.lock.acquire(timeout=timeout)
            
            if acquired:
                lock_info.acquire_count += 1
                lock_info.wait_time = time.time() - start_time
                
                if lock_info.wait_time > 5.0:  # 警告：等待超过5秒
                    logger.warning(f"锁{name}等待时间过长: {lock_info.wait_time:.2f}秒")
                
                return True
            else:
                logger.warning(f"获取锁{name}超时")
                return False
                
        except Exception as e:
            logger.error(f"获取锁{name}失败: {e}")
            return False
    
    def release_lock(self, name: str):
        """释放锁"""
        lock_info = self._lock_stats.get(name)
        if not lock_info:
            logger.warning(f"锁不存在: {name}")
            return
        
        if lock_info.held_time > 0:
            hold_duration = time.time() - lock_info.held_time
            lock_info.held_time = 0.0
            
            if hold_duration > 10.0:  # 警告：持有超过10秒
                logger.warning(f"锁{name}持有时间过长: {hold_duration:.2f}秒")
        
        try:
            lock_info.lock.release()
            logger.debug(f"释放锁: {name}")
            return True
        except Exception as e:
            logger.error(f"释放锁{name}失败: {e}")
            return False
    
    @contextmanager
    def with_lock(self, name: str):
        """上下文管理器：自动获取和释放锁"""
        lock = self.create_lock(name)
        
        try:
            self.acquire_lock(name)
            yield lock
        finally:
            self.release_lock(name)
    
    def get_lock_stats(self) -> Dict[str, Dict[str, Any]]:
        """获取所有锁的统计信息"""
        with self._manager_lock:
            stats = {}
            for name, info in self._lock_stats.items():
                stats[name] = {
                    'acquire_count': info.acquire_count,
                    'current_held': info.held_time > 0,
                    'held_duration': info.held_time if info.held_time > 0 else 0.0
                }
            return stats
    
    def cleanup_unused_locks(self, max_idle_time: float = 60.0):
        """清理闲置的锁"""
        with self._manager_lock:
            current_time = time.time()
            locks_to_remove = []
            
            for name, info in self._lock_stats.items():
                if info.held_time > 0:
                    idle_time = current_time - info.held_time
                    if idle_time > max_idle_time:
                        locks_to_remove.append(name)
            
            for name in locks_to_remove:
                del self._locks[name]
                del self._lock_stats[name]
                logger.debug(f"清理闲置锁: {name}")
            
            if locks_to_remove:
                logger.info(f"清理了{len(locks_to_remove)}个闲置锁")

class DeadlockDetector:
    """死锁检测器"""
    
    def __init__(self, detection_interval: float = 5.0):
        self.detection_interval = detection_interval
        self._lock_graph: Dict[str, set] = {}
        self._last_check = time.time()
        self._detector_thread = None
        self._running = False
    
    def register_lock(self, name: str):
        """注册锁"""
        self._lock_graph[name] = set()
        logger.debug(f"注册锁: {name}")
    
    def acquire(self, name: str):
        """记录锁获取"""
        if name in self._lock_graph:
            thread_id = threading.current_thread().name
            self._lock_graph[name].add(thread_id)
            logger.debug(f"锁{name}被{thread_id}获取")
    
    def release(self, name: str):
        """记录锁释放"""
        if name in self._lock_graph:
            thread_id = threading.current_thread().name
            if thread_id in self._lock_graph[name]:
                self._lock_graph[name].remove(thread_id)
                logger.debug(f"锁{name}被{thread_id}释放")
    
    def start_detection(self):
        """启动死锁检测"""
        if self._running:
            return
        
        self._running = True
        self._detector_thread = threading.Thread(
            target=self._detect_deadlock,
            daemon=True
        )
        self._detector_thread.start()
        logger.info("死锁检测已启动")
    
    def stop_detection(self):
        """停止死锁检测"""
        self._running = False
        if self._detector_thread:
            self._detector_thread.join(timeout=5)
            logger.info("死锁检测已停止")
    
    def _detect_deadlock(self):
        """检测死锁"""
        while self._running:
            current_time = time.time()
            
            # 检查是否有锁持有时间过长
            for name, threads in self._lock_graph.items():
                if len(threads) > 0:
                    # 检测可能的死锁
                    if len(threads) > 1:
                        logger.warning(f"检测到潜在死锁: {name}, 持有线程: {len(threads)}")
            
            time.sleep(self.detection_interval)
    
    def get_status(self) -> Dict[str, Any]:
        """获取检测状态"""
        return {
            'running': self._running,
            'registered_locks': len(self._lock_graph),
            'potential_deadlocks': sum(1 for threads in self._lock_graph.values() if len(threads) > 1)
        }

class ThreadSafeCounter:
    """线程安全计数器"""
    
    def __init__(self, initial_value: int = 0):
        self._value = initial_value
        self._lock = threading.Lock()
    
    def increment(self, amount: int = 1) -> int:
        """原子递增"""
        with self._lock:
            self._value += amount
            return self._value
    
    def decrement(self, amount: int = 1) -> int:
        """原子递减"""
        with self._lock:
            self._value -= amount
            return self._value
    
    def get_value(self) -> int:
        """获取当前值"""
        with self._lock:
            return self._value
    
    def reset(self, value: int = 0):
        """重置计数器"""
        with self._lock:
            self._value = value

class ThreadSafeDict:
    """线程安全字典"""
    
    def __init__(self):
        self._dict: Dict[str, Any] = {}
        self._lock = threading.RLock()  # 可重入锁
    
    def get(self, key: str, default: Any = None) -> Any:
        """获取值"""
        with self._lock:
            return self._dict.get(key, default)
    
    def set(self, key: str, value: Any):
        """设置值"""
        with self._lock:
            self._dict[key] = value
    
    def delete(self, key: str):
        """删除键"""
        with self._lock:
            if key in self._dict:
                del self._dict[key]
    
    def pop(self, key: str, default: Any = None) -> Any:
        """弹出值"""
        with self._lock:
            return self._dict.pop(key, default)
    
    def clear(self):
        """清空字典"""
        with self._lock:
            self._dict.clear()
    
    def keys(self):
        """获取所有键"""
        with self._lock:
            return list(self._dict.keys())
    
    def values(self):
        """获取所有值"""
        with self._lock:
            return list(self._dict.values())
    
    def items(self):
        """获取所有项"""
        with self._lock:
            return list(self._dict.items())
    
    def __len__(self):
        """获取字典大小"""
        with self._lock:
            return len(self._dict)
    
    def __contains__(self, key: str):
        """检查键是否存在"""
        with self._lock:
            return key in self._dict

class ThreadSafeQueue:
    """线程安全队列"""
    
    def __init__(self, max_size: int = 1000):
        self._queue = []
        self._lock = threading.Lock()
        self._max_size = max_size
        self._not_empty = threading.Condition(self._lock)
    
    def put(self, item: Any):
        """添加项"""
        with self._lock:
            while len(self._queue) >= self._max_size:
                # 队列满，移除最旧的项
                self._queue.pop(0)
            
            self._queue.append(item)
            self._not_empty.notify()
            logger.debug(f"队列添加项，当前大小: {len(self._queue)}")
    
    def get(self, timeout: Optional[float] = None) -> Any:
        """获取项"""
        with self._lock:
            if not self._queue:
                self._not_empty.wait(timeout=timeout)
            
            if self._queue:
                return self._queue.pop(0)
            
            return None
    
    def peek(self) -> Optional[Any]:
        """查看队首项但不移除"""
        with self._lock:
            if self._queue:
                return self._queue[0]
            return None
    
    def qsize(self) -> int:
        """获取队列大小"""
        with self._lock:
            return len(self._queue)
    
    def clear(self):
        """清空队列"""
        with self._lock:
            self._queue.clear()
            logger.debug("队列已清空")

# 全局线程安全管理器实例
thread_safety_manager = None

def get_thread_safety_manager() -> ThreadSafetyManager:
    """获取线程安全管理器实例（单例模式）"""
    global thread_safety_manager
    if thread_safety_manager is None:
        thread_safety_manager = ThreadSafetyManager()
    return thread_safety_manager
"""
增强线程池管理模块 - Week 2核心组件
=======================================
提供线程池管理、任务队列、线程安全、性能监控
目标：支持多线程并发、线程安全、性能优化
"""

import threading
import queue
import time
import gc
from typing import Callable, Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, Future
import traceback

from app.modules.utils.logger import logger

class TaskPriority(Enum):
    """任务优先级"""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4

class ThreadState(Enum):
    """线程状态"""
    IDLE = "idle"
    RUNNING = "running"
    BUSY = "busy"
    ERROR = "error"
    STOPPED = "stopped"

@dataclass
class TaskInfo:
    """任务信息"""
    task_id: str
    func: Callable
    priority: TaskPriority = TaskPriority.NORMAL
    submit_time: float
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    result: Optional[Any] = None
    error: Optional[Exception] = None

@dataclass
class ThreadInfo:
    """线程信息"""
    thread_id: str
    state: ThreadState = ThreadState.IDLE
    current_task: Optional[TaskInfo] = None
    completed_tasks: int = 0
    total_tasks: int = 0
    error_count: int = 0

@dataclass
class ThreadPoolConfig:
    """线程池配置"""
    max_workers: int = 4
    min_workers: int = 2
    task_timeout: int = 300  # 任务超时时间（秒）
    queue_size: int = 1000  # 任务队列最大长度
    enable_stats: bool = True  # 是否启用统计
    auto_gc_interval: int = 5  # 自动垃圾回收间隔（任务数）
    max_retries: int = 3  # 最大重试次数

class EnhancedThreadPool:
    """增强线程池管理器"""
    
    def __init__(self, config: Optional[ThreadPoolConfig] = None):
        self.config = config or ThreadPoolConfig()
        self._tasks: queue.PriorityQueue()  # 优先级队列
        self._workers: List[threading.Thread] = []
        self._worker_threads: Dict[str, threading.Thread] = {}
        self._running = False
        self._lock = threading.Lock()
        self._task_counter = 0
        self._stats = {
            'total_submitted': 0,
            'total_completed': 0,
            'total_failed': 0,
            'total_timeout': 0,
            'avg_execution_time': 0.0,
            'max_execution_time': 0.0,
            'min_execution_time': 0.0
        }
        
        logger.info(f"增强线程池初始化: 最大{self.config.max_workers}个工作线程")
    
    def start(self):
        """启动线程池"""
        with self._lock:
            if self._running:
                logger.warning("线程池已在运行")
                return
            
            self._running = True
            
            # 创建工作线程
            for i in range(self.config.max_workers):
                worker = threading.Thread(
                    target=self._worker,
                    name=f"Worker-{i}",
                    daemon=True
                )
                worker.start()
                self._workers.append(worker)
                self._worker_threads[worker.name] = {
                    'thread': worker,
                    'state': ThreadState.IDLE,
                    'info': ThreadInfo(
                        thread_id=worker.name,
                        state=ThreadState.IDLE,
                        completed_tasks=0,
                        total_tasks=0,
                        error_count=0
                    )
                }
            
            logger.info(f"线程池已启动: {self.config.max_workers}个工作线程")
    
    def submit(self, task: Callable, task_id: Optional[str] = None, 
               priority: TaskPriority = TaskPriority.NORMAL, submit_time: Optional[float] = None) -> str:
        """提交任务到线程池
        
        Args:
            task: 要执行的任务函数
            priority: 任务优先级
            task_id: 任务ID（可选）
            
        Returns:
            任务ID
        """
        if not self._running:
            self.start()
        
        # 生成任务ID
        if task_id is None:
            task_id = f"task_{self._task_counter}"
            self._task_counter += 1
        
        # 创建任务信息
        task_info = TaskInfo(
            task_id=task_id,
            func=task,
            priority=priority,
            submit_time=submit_time or time.time()
        )
        
        # 提交到优先级队列
        try:
            self._tasks.put((priority.value, task_info))
            self._stats['total_submitted'] += 1
            
            logger.debug(f"任务已提交: {task_id}, 优先级: {priority.name}")
            return task_id
            
        except Exception as e:
            logger.error(f"任务提交失败: {e}")
            raise
    
    def submit_with_retry(self, task: Callable, priority: TaskPriority = TaskPriority.NORMAL,
                     task_id: Optional[str] = None, max_retries: Optional[int] = None) -> str:
        """提交任务并支持重试
        
        Args:
            task: 要执行的任务函数
            priority: 任务优先级
            task_id: 任务ID（可选）
            max_retries: 最大重试次数
            
        Returns:
            任务ID
        """
        max_retries = max_retries or self.config.max_retries
        
        def wrapped_task():
            for attempt in range(max_retries):
                try:
                    return task()
                except Exception as e:
                    if attempt == max_retries - 1:
                        logger.error(f"任务重试{max_retries}次后仍失败: {e}")
                        raise
                    logger.warning(f"任务执行失败，第{attempt + 1}次重试: {e}")
                    time.sleep(1 * (attempt + 1))  # 指数退避
        
        return self.submit(wrapped_task, priority, task_id)
    
    def shutdown(self, wait: bool = True, timeout: int = 30):
        """关闭线程池
        
        Args:
            wait: 是否等待所有任务完成
            timeout: 超时时间（秒）
            
        Returns:
            是否成功关闭
        """
        with self._lock:
            if not self._running:
                return True
            
            logger.info("开始关闭线程池...")
            
            # 停止接受新任务
            self._running = False
            
            # 等待队列清空
            if wait:
                start_time = time.time()
                while not self._tasks.empty():
                    if time.time() - start_time > timeout:
                        logger.warning(f"关闭超时，队列中仍有{self._tasks.qsize()}个任务")
                        break
                    time.sleep(0.1)
            
            # 通知所有工作线程退出
            for _ in range(self.config.max_workers):
                self._tasks.put((TaskPriority.CRITICAL.value, None))  # 发送停止信号
            
            # 等待所有线程结束
            for worker in self._workers:
                worker.join(timeout=5)
            
            logger.info(f"线程池已关闭，处理了{self._stats['total_completed']}个任务")
            return True
    
    def _worker(self):
        """工作线程主循环"""
        thread_name = threading.current_thread().name
        worker_info = self._worker_threads[thread_name]
        
        logger.debug(f"工作线程启动: {thread_name}")
        
        while self._running:
            try:
                # 从优先级队列获取任务
                priority, task_info = self._tasks.get(timeout=1.0)
                
                # 检查是否为停止信号
                if task_info is None:
                    logger.debug(f"工作线程收到停止信号: {thread_name}")
                    break
                
                # 更新线程状态
                worker_info.state = ThreadState.RUNNING
                worker_info.current_task = task_info
                
                # 执行任务
                start_time = time.time()
                try:
                    result = task_info.func()
                    end_time = time.time()
                    execution_time = end_time - start_time
                    
                    # 更新任务信息
                    task_info.start_time = start_time
                    task_info.end_time = end_time
                    task_info.result = result
                    
                    # 更新统计
                    self._stats['total_completed'] += 1
                    self._stats['avg_execution_time'] = (
                        self._stats['avg_execution_time'] * (self._stats['total_completed'] - 1) + execution_time
                    ) / self._stats['total_completed']
                    
                    if execution_time > self._stats['max_execution_time']:
                        self._stats['max_execution_time'] = execution_time
                    
                    if execution_time < self._stats['min_execution_time'] or self._stats['min_execution_time'] == 0:
                        self._stats['min_execution_time'] = execution_time
                    
                    # 更新线程信息
                    worker_info.completed_tasks += 1
                    worker_info.total_tasks += 1
                    
                    logger.debug(f"任务完成: {task_info.task_id}, 耗时: {execution_time:.3f}秒")
                
                except Exception as e:
                    error_time = time.time()
                    execution_time = error_time - start_time
                    
                    # 更新任务信息
                    task_info.start_time = start_time
                    task_info.end_time = error_time
                    task_info.error = e
                    
                    # 更新统计
                    self._stats['total_failed'] += 1
                    worker_info.error_count += 1
                    
                    logger.error(f"任务执行失败: {task_info.task_id}, 错误: {str(e)}")
                
                # 自动垃圾回收
                worker_info.completed_tasks += 1
                if worker_info.completed_tasks % self.config.auto_gc_interval == 0:
                    gc.collect()
                    logger.debug(f"执行垃圾回收: {thread_name}")
            
            except Exception as e:
                logger.error(f"工作线程异常: {thread_name}, 错误: {str(e)}")
                worker_info.state = ThreadState.ERROR
                break
            
            finally:
                worker_info.state = ThreadState.IDLE
                worker_info.current_task = None
                logger.debug(f"工作线程空闲: {thread_name}")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取线程池统计信息"""
        with self._lock:
            active_workers = sum(
                1 for info in self._worker_threads.values() 
                if info.state == ThreadState.RUNNING
            )
            idle_workers = sum(
                1 for info in self._worker_threads.values() 
                if info.state == ThreadState.IDLE
            )
            error_workers = sum(
                1 for info in self._worker_threads.values() 
                if info.state == ThreadState.ERROR
            )
            
            return {
                'config': {
                    'max_workers': self.config.max_workers,
                    'min_workers': self.config.min_workers,
                    'task_timeout': self.config.task_timeout,
                    'queue_size': self.config.queue_size
                },
                'workers': {
                    'total': len(self._workers),
                    'active': active_workers,
                    'idle': idle_workers,
                    'error': error_workers
                },
                'tasks': {
                    'pending': self._tasks.qsize(),
                    'total_submitted': self._stats['total_submitted'],
                    'total_completed': self._stats['total_completed'],
                    'total_failed': self._stats['total_failed'],
                    'success_rate': f"{(self._stats['total_completed'] / max(self._stats['total_submitted'], 1)) * 100:.2f}%" if self._stats['total_submitted'] > 0 else "0%"
                },
                'performance': {
                    'avg_execution_time': f"{self._stats['avg_execution_time']:.3f}秒",
                    'max_execution_time': f"{self._stats['max_execution_time']:.3f}秒",
                    'min_execution_time': f"{self._stats['min_execution_time']:.3f}秒"
                }
            }
    
    def get_worker_info(self, thread_id: str) -> Optional[ThreadInfo]:
        """获取指定线程的信息"""
        with self._lock:
            return self._worker_threads.get(thread_id)
    
    def resize_pool(self, new_max_workers: int):
        """动态调整线程池大小"""
        if new_max_workers < self.config.min_workers:
            logger.warning(f"新工作线程数{new_max_workers}小于最小值{self.config.min_workers}")
            return False
        
        with self._lock:
            old_size = len(self._workers)
            self.config.max_workers = new_max_workers
            
            if new_max_workers > old_size:
                # 增加工作线程
                for i in range(old_size, new_max_workers):
                    worker = threading.Thread(
                        target=self._worker,
                        name=f"Worker-{i}",
                        daemon=True
                    )
                    worker.start()
                    self._workers.append(worker)
                    self._worker_threads[worker.name] = {
                        'thread': worker,
                        'state': ThreadState.IDLE,
                        'info': ThreadInfo(
                            thread_id=worker.name,
                            state=ThreadState.IDLE,
                            completed_tasks=0,
                            total_tasks=0,
                            error_count=0
                        )
                    }
                
                logger.info(f"线程池扩容: {old_size} -> {new_max_workers}")
            
            elif new_max_workers < old_size:
                # 减少工作线程
                workers_to_remove = self._workers[new_max_workers:]
                for worker in workers_to_remove:
                    thread_name = worker.name
                    
                    # 发送停止信号
                    self._tasks.put((TaskPriority.CRITICAL.value, None))
                    
                    # 等待线程结束
                    worker.join(timeout=5)
                    
                    if worker in self._workers:
                        self._workers.remove(worker)
                    
                    if thread_name in self._worker_threads:
                        del self._worker_threads[thread_name]
                
                logger.info(f"线程池缩容: {old_size} -> {new_max_workers}")
    
    def clear_stats(self):
        """清空统计数据"""
        with self._lock:
            self._stats = {
                'total_submitted': 0,
                'total_completed': 0,
                'total_failed': 0,
                'total_timeout': 0,
                'avg_execution_time': 0.0,
                'max_execution_time': 0.0,
                'min_execution_time': 0.0
            }
        
        logger.info("统计数据已清空")

# 全局增强线程池实例
_enhanced_thread_pool = None
_thread_pool_lock = threading.Lock()

def get_enhanced_thread_pool(config: Optional[ThreadPoolConfig] = None) -> EnhancedThreadPool:
    """获取增强线程池实例（单例模式）"""
    global _enhanced_thread_pool
    
    if _enhanced_thread_pool is None:
        with _thread_pool_lock:
            if _enhanced_thread_pool is None:
                _enhanced_thread_pool = EnhancedThreadPool(config)
                _enhanced_thread_pool.start()
    
    return _enhanced_thread_pool

def shutdown_thread_pool():
    """关闭全局线程池"""
    global _enhanced_thread_pool
    
    if _enhanced_thread_pool is not None:
        _enhanced_thread_pool.shutdown(wait=True, timeout=30)
        _enhanced_thread_pool = None
        logger.info("全局线程池已关闭")
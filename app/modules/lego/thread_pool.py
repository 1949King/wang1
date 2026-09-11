"""
线程池管理模块 (ThreadPool)
=========================
提供高效的线程池管理，支持任务队列和并发控制
"""

import threading
import queue
import gc
from typing import Callable, Optional


import logging
logger = logging.getLogger("AI短剧编辑器.modules.lego.thread_pool")

class ThreadPool:
    """线程池管理类"""
    
    def __init__(self, max_workers: int = 4):
        self.max_workers = max_workers
        self.tasks: queue.Queue = queue.Queue()
        self.workers: list = []
        self.running = False
        self._lock = threading.Lock()
    
    def start(self):
        """启动线程池"""
        with self._lock:
            if self.running:
                return
            self.running = True
            
        for i in range(self.max_workers):
            worker = threading.Thread(target=self._worker, daemon=True)
            worker.start()
            self.workers.append(worker)
    
    def _worker(self):
        """工作线程"""
        task_count = 0
        while self.running:
            try:
                task = self.tasks.get(timeout=0.1)
                
                task()
                
                self.tasks.task_done()
                
                task_count += 1
                if task_count >= 5:
                    gc.collect()
                    task_count = 0
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f'线程池工作线程错误: {e}')
    
    def submit(self, task: Callable):
        """提交任务到线程池"""
        if not self.running:
            self.start()
        self.tasks.put(task)
    
    def shutdown(self, wait: bool = True):
        """关闭线程池"""
        self.running = False
        
        if wait:
            self.tasks.join()
        
        for worker in self.workers:
            worker.join(timeout=1)
        
        self.workers.clear()
    
    def get_pending_count(self) -> int:
        """获取待处理任务数量"""
        return self.tasks.qsize()
    
    def get_active_count(self) -> int:
        """获取活跃线程数量"""
        return sum(1 for w in self.workers if w.is_alive())


_thread_pool_instance: Optional[ThreadPool] = None
_thread_pool_lock = threading.Lock()


def get_thread_pool(max_workers: int = 4) -> ThreadPool:
    """获取全局线程池实例"""
    global _thread_pool_instance
    
    if _thread_pool_instance is None:
        with _thread_pool_lock:
            if _thread_pool_instance is None:
                _thread_pool_instance = ThreadPool(max_workers)
                _thread_pool_instance.start()
    
    return _thread_pool_instance

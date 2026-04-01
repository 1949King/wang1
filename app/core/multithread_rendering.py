"""
多线程渲染和批量处理优化模块
==============================
实现高效的多线程渲染和批量任务处理
"""

import os
import logging
import threading
import time
import queue
from typing import Optional, Dict, Any, List, Callable, Tuple
from dataclasses import dataclass, field
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from pathlib import Path
import numpy as np

from app.core.logging_enhanced import monitor_performance
from app.core.exceptions import RenderError, ErrorCode
from app.core.gpu_acceleration import get_auto_gpu_renderer

logger = logging.getLogger(__name__)


class TaskPriority(Enum):
    """任务优先级"""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    URGENT = 4


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class RenderTask:
    """渲染任务"""
    task_id: str
    input_path: str
    output_path: str
    resolution: Tuple[int, int]
    priority: TaskPriority = TaskPriority.NORMAL
    status: TaskStatus = TaskStatus.PENDING
    progress: float = 0.0
    error_message: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'task_id': self.task_id,
            'input_path': self.input_path,
            'output_path': self.output_path,
            'resolution': self.resolution,
            'priority': self.priority.value,
            'status': self.status.value,
            'progress': self.progress,
            'error_message': self.error_message,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'metadata': self.metadata
        }


class MultiThreadRenderer:
    """多线程渲染器"""
    
    def __init__(self, max_workers: int = 4, use_gpu: bool = True):
        self.max_workers = max_workers
        self.use_gpu = use_gpu
        self._executor: Optional[ThreadPoolExecutor] = None
        self._gpu_renderer = None
        self._task_queue: queue.PriorityQueue = queue.PriorityQueue()
        self._active_tasks: Dict[str, RenderTask] = {}
        self._completed_tasks: List[RenderTask] = []
        self._failed_tasks: List[RenderTask] = []
        self._lock = threading.Lock()
        self._running = False
        self._worker_threads: List[threading.Thread] = []
        
        self._performance_stats = {
            'total_tasks': 0,
            'completed_tasks': 0,
            'failed_tasks': 0,
            'total_time': 0.0,
            'avg_time': 0.0
        }
        
        self._progress_callbacks: List[Callable] = []
    
    def initialize(self) -> bool:
        """初始化渲染器
        
        Returns:
            是否初始化成功
        """
        try:
            # 初始化GPU渲染器
            if self.use_gpu:
                self._gpu_renderer = get_auto_gpu_renderer()
                self._gpu_renderer.initialize()
            
            # 创建线程池
            self._executor = ThreadPoolExecutor(max_workers=self.max_workers)
            
            logger.info(f"多线程渲染器初始化成功，工作线程数: {self.max_workers}")
            return True
            
        except Exception as e:
            logger.error(f"多线程渲染器初始化失败: {e}")
            return False
    
    def add_task(self, task: RenderTask) -> bool:
        """添加渲染任务
        
        Args:
            task: 渲染任务
        
        Returns:
            是否添加成功
        """
        try:
            with self._lock:
                self._active_tasks[task.task_id] = task
                self._performance_stats['total_tasks'] += 1
            
            # 添加到优先级队列
            self._task_queue.put((task.priority.value, task))
            
            logger.info(f"添加渲染任务: {task.task_id}")
            return True
            
        except Exception as e:
            logger.error(f"添加渲染任务失败: {e}")
            return False
    
    def add_tasks(self, tasks: List[RenderTask]) -> int:
        """批量添加渲染任务
        
        Args:
            tasks: 渲染任务列表
        
        Returns:
            成功添加的任务数量
        """
        success_count = 0
        for task in tasks:
            if self.add_task(task):
                success_count += 1
        
        logger.info(f"批量添加渲染任务: {success_count}/{len(tasks)}")
        return success_count
    
    def start_processing(self):
        """开始处理任务"""
        if self._running:
            logger.warning("任务处理已在运行")
            return
        
        self._running = True
        
        # 启动工作线程
        for i in range(self.max_workers):
            worker_thread = threading.Thread(
                target=self._worker_loop,
                name=f"RenderWorker-{i}",
                daemon=True
            )
            worker_thread.start()
            self._worker_threads.append(worker_thread)
        
        logger.info(f"启动 {len(self._worker_threads)} 个工作线程")
    
    def stop_processing(self, wait_for_completion: bool = True):
        """停止处理任务
        
        Args:
            wait_for_completion: 是否等待当前任务完成
        """
        self._running = False
        
        if wait_for_completion:
            # 等待所有工作线程完成
            for thread in self._worker_threads:
                if thread.is_alive():
                    thread.join(timeout=30)
        
        logger.info("任务处理已停止")
    
    def _worker_loop(self):
        """工作线程循环"""
        while self._running:
            try:
                # 从队列获取任务
                try:
                    priority, task = self._task_queue.get(timeout=1)
                except queue.Empty:
                    continue
                
                # 处理任务
                self._process_task(task)
                
                # 标记任务完成
                self._task_queue.task_done()
                
            except Exception as e:
                logger.error(f"工作线程异常: {e}")
    
    @monitor_performance(threshold_warning=2.0, threshold_critical=10.0)
    def _process_task(self, task: RenderTask):
        """处理单个渲染任务"""
        task.status = TaskStatus.RUNNING
        task.start_time = time.time()
        
        try:
            logger.info(f"开始处理任务: {task.task_id}")
            
            # 读取输入文件
            frame_data = self._load_input_file(task.input_path)
            
            # 渲染帧
            if self._gpu_renderer:
                rendered_frame = self._gpu_renderer.render(frame_data, task.resolution)
            else:
                rendered_frame = self._render_with_cpu(frame_data, task.resolution)
            
            # 保存输出文件
            self._save_output_file(rendered_frame, task.output_path)
            
            # 更新任务状态
            task.status = TaskStatus.COMPLETED
            task.progress = 100.0
            task.end_time = time.time()
            
            # 更新统计
            with self._lock:
                self._completed_tasks.append(task)
                self._performance_stats['completed_tasks'] += 1
                if task.task_id in self._active_tasks:
                    del self._active_tasks[task.task_id]
            
            # 通知进度回调
            self._notify_progress(task)
            
            logger.info(f"任务完成: {task.task_id} (耗时: {task.end_time - task.start_time:.2f}s)")
            
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error_message = str(e)
            task.end_time = time.time()
            
            # 更新统计
            with self._lock:
                self._failed_tasks.append(task)
                self._performance_stats['failed_tasks'] += 1
                if task.task_id in self._active_tasks:
                    del self._active_tasks[task.task_id]
            
            logger.error(f"任务失败: {task.task_id} - {e}")
    
    def _load_input_file(self, file_path: str) -> np.ndarray:
        """加载输入文件"""
        try:
            import cv2
            
            frame = cv2.imread(file_path)
            if frame is None:
                raise RenderError(
                    ErrorCode.RENDER_ERROR,
                    f"无法读取文件: {file_path}"
                )
            
            return frame
            
        except Exception as e:
            raise RenderError(
                ErrorCode.RENDER_ERROR,
                f"文件加载失败: {str(e)}",
                details={'file_path': file_path}
            )
    
    def _render_with_cpu(self, frame_data: np.ndarray,
                       resolution: Tuple[int, int]) -> np.ndarray:
        """使用CPU渲染"""
        try:
            import cv2
            
            # 调整分辨率
            if frame_data.shape[:2] != resolution:
                return cv2.resize(frame_data, resolution, interpolation=cv2.INTER_LINEAR)
            else:
                return frame_data.copy()
                
        except Exception as e:
            raise RenderError(
                ErrorCode.RENDER_ERROR,
                f"CPU渲染失败: {str(e)}"
            )
    
    def _save_output_file(self, frame_data: np.ndarray, file_path: str):
        """保存输出文件"""
        try:
            import cv2
            
            # 创建输出目录
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            
            # 保存文件
            cv2.imwrite(file_path, frame_data)
            
        except Exception as e:
            raise RenderError(
                ErrorCode.RENDER_ERROR,
                f"文件保存失败: {str(e)}",
                details={'file_path': file_path}
            )
    
    def _notify_progress(self, task: RenderTask):
        """通知进度更新"""
        for callback in self._progress_callbacks:
            try:
                callback(task)
            except Exception as e:
                logger.error(f"进度回调执行失败: {e}")
    
    def add_progress_callback(self, callback: Callable[[RenderTask], None]):
        """添加进度回调函数"""
        self._progress_callbacks.append(callback)
    
    def get_task_status(self, task_id: str) -> Optional[RenderTask]:
        """获取任务状态"""
        with self._lock:
            return self._active_tasks.get(task_id)
    
    def get_active_tasks(self) -> List[RenderTask]:
        """获取活动任务列表"""
        with self._lock:
            return list(self._active_tasks.values())
    
    def get_completed_tasks(self, limit: int = 100) -> List[RenderTask]:
        """获取已完成任务列表"""
        with self._lock:
            return self._completed_tasks[-limit:]
    
    def get_failed_tasks(self, limit: int = 100) -> List[RenderTask]:
        """获取失败任务列表"""
        with self._lock:
            return self._failed_tasks[-limit:]
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """获取性能统计"""
        with self._lock:
            stats = self._performance_stats.copy()
            
            if stats['completed_tasks'] > 0:
                completed_tasks = [t for t in self._completed_tasks if t.end_time and t.start_time]
                if completed_tasks:
                    total_time = sum(t.end_time - t.start_time for t in completed_tasks)
                    stats['avg_time'] = total_time / len(completed_tasks)
                    stats['total_time'] = total_time
            
            return stats
    
    def clear_completed_tasks(self):
        """清空已完成任务列表"""
        with self._lock:
            count = len(self._completed_tasks)
            self._completed_tasks.clear()
            logger.info(f"清空已完成任务: {count} 个")
    
    def clear_failed_tasks(self):
        """清空失败任务列表"""
        with self._lock:
            count = len(self._failed_tasks)
            self._failed_tasks.clear()
            logger.info(f"清空失败任务: {count} 个")
    
    def shutdown(self):
        """关闭渲染器"""
        self.stop_processing(wait_for_completion=True)
        
        if self._executor:
            self._executor.shutdown(wait=True)
        
        if self._gpu_renderer:
            self._gpu_renderer.shutdown()
        
        logger.info("多线程渲染器已关闭")


class BatchProcessor:
    """批量处理器"""
    
    def __init__(self, max_workers: int = 4, use_multiprocessing: bool = False):
        self.max_workers = max_workers
        self.use_multiprocessing = use_multiprocessing
        self._executor = None
        self._task_queue = queue.Queue()
        self._results = []
        self._lock = threading.Lock()
        self._running = False
        
        self._stats = {
            'total_tasks': 0,
            'completed_tasks': 0,
            'failed_tasks': 0,
            'total_time': 0.0
        }
    
    def initialize(self) -> bool:
        """初始化批量处理器"""
        try:
            if self.use_multiprocessing:
                self._executor = ProcessPoolExecutor(max_workers=self.max_workers)
            else:
                self._executor = ThreadPoolExecutor(max_workers=self.max_workers)
            
            logger.info(f"批量处理器初始化成功，工作进程/线程数: {self.max_workers}")
            return True
            
        except Exception as e:
            logger.error(f"批量处理器初始化失败: {e}")
            return False
    
    def process_batch(self, tasks: List[Any], 
                    process_func: Callable,
                    batch_size: int = 10) -> List[Any]:
        """批量处理任务
        
        Args:
            tasks: 任务列表
            process_func: 处理函数
            batch_size: 批次大小
        
        Returns:
            处理结果列表
        """
        if not self._executor:
            raise RuntimeError("批量处理器未初始化")
        
        results = []
        total_tasks = len(tasks)
        
        logger.info(f"开始批量处理: {total_tasks} 个任务，批大小: {batch_size}")
        
        # 分批处理
        for i in range(0, total_tasks, batch_size):
            batch = tasks[i:i + batch_size]
            
            # 提交批次任务
            futures = []
            for task in batch:
                future = self._executor.submit(process_func, task)
                futures.append(future)
            
            # 收集结果
            for future in as_completed(futures):
                try:
                    result = future.result()
                    results.append(result)
                    
                    with self._lock:
                        self._stats['completed_tasks'] += 1
                        
                except Exception as e:
                    logger.error(f"任务处理失败: {e}")
                    
                    with self._lock:
                        self._stats['failed_tasks'] += 1
            
            logger.info(f"批次完成: {i + len(batch)}/{total_tasks}")
        
        with self._lock:
            self._stats['total_tasks'] = total_tasks
        
        logger.info(f"批量处理完成: {len(results)}/{total_tasks} 成功")
        return results
    
    def process_parallel(self, tasks: List[Any],
                      process_func: Callable) -> List[Any]:
        """并行处理任务
        
        Args:
            tasks: 任务列表
            process_func: 处理函数
        
        Returns:
            处理结果列表
        """
        if not self._executor:
            raise RuntimeError("批量处理器未初始化")
        
        logger.info(f"开始并行处理: {len(tasks)} 个任务")
        
        # 提交所有任务
        futures = []
        for task in tasks:
            future = self._executor.submit(process_func, task)
            futures.append(future)
        
        # 收集结果
        results = []
        for future in as_completed(futures):
            try:
                result = future.result()
                results.append(result)
                
                with self._lock:
                    self._stats['completed_tasks'] += 1
                    
            except Exception as e:
                logger.error(f"任务处理失败: {e}")
                
                with self._lock:
                    self._stats['failed_tasks'] += 1
        
        with self._lock:
            self._stats['total_tasks'] = len(tasks)
        
        logger.info(f"并行处理完成: {len(results)}/{len(tasks)} 成功")
        return results
    
    def get_stats(self) -> Dict[str, Any]:
        """获取处理统计"""
        with self._lock:
            return self._stats.copy()
    
    def shutdown(self):
        """关闭批量处理器"""
        if self._executor:
            self._executor.shutdown(wait=True)
        
        logger.info("批量处理器已关闭")


# 全局实例
_global_multi_thread_renderer: Optional[MultiThreadRenderer] = None
_global_batch_processor: Optional[BatchProcessor] = None


def get_multi_thread_renderer(max_workers: int = 4, 
                           use_gpu: bool = True) -> MultiThreadRenderer:
    """获取全局多线程渲染器"""
    global _global_multi_thread_renderer
    
    if _global_multi_thread_renderer is None:
        _global_multi_thread_renderer = MultiThreadRenderer(max_workers, use_gpu)
        _global_multi_thread_renderer.initialize()
    
    return _global_multi_thread_renderer


def get_batch_processor(max_workers: int = 4,
                     use_multiprocessing: bool = False) -> BatchProcessor:
    """获取全局批量处理器"""
    global _global_batch_processor
    
    if _global_batch_processor is None:
        _global_batch_processor = BatchProcessor(max_workers, use_multiprocessing)
        _global_batch_processor.initialize()
    
    return _global_batch_processor
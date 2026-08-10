"""
批量任务队列管理系统
====================
管理批量视频处理任务，支持优先级、暂停、恢复、进度跟踪
"""

import os
import json
import time
import threading
import queue
import logging
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
import uuid

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "等待中"
    RUNNING = "运行中"
    PAUSED = "已暂停"
    COMPLETED = "已完成"
    FAILED = "失败"
    CANCELLED = "已取消"


class TaskPriority(Enum):
    """任务优先级"""
    LOW = 3
    NORMAL = 2
    HIGH = 1
    URGENT = 0


@dataclass
class BatchTask:
    """批量任务"""
    task_id: str
    name: str
    task_type: str                    # smart_clip, viral_predict, export, etc.
    params: Dict[str, Any]
    priority: TaskPriority
    status: TaskStatus
    progress: float                   # 0-100
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional[Dict] = None
    error_message: Optional[str] = None
    callback: Optional[Callable] = field(default=None, repr=False)

    # T-1: 任务依赖 — 依赖的任务ID列表，全部COMPLETED后才执行
    depends_on: List[str] = field(default_factory=list)

    # T-3: 失败重试
    max_retries: int = 0
    retry_count: int = 0
    retry_delay: float = 5.0

    # T-6: 定时调度 — 设定时间后自动入队执行
    scheduled_at: Optional[datetime] = None


@dataclass
class TaskQueue:
    """任务队列"""
    queue_id: str
    name: str
    tasks: List[BatchTask]
    status: TaskStatus
    created_at: datetime
    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0


class BatchTaskManager:
    """
    批量任务队列管理器
    
    功能：
    1. 任务队列管理 - 支持多队列、优先级
    2. 任务调度 - 自动调度、负载均衡
    3. 进度跟踪 - 实时进度、历史记录
    4. 任务控制 - 暂停、恢复、取消
    5. 批量操作 - 批量添加、批量处理
    """
    
    _instance: Optional["BatchTaskManager"] = None

    @classmethod
    def get_instance(cls, max_workers: int = 4) -> "BatchTaskManager":
        """获取跨模块共享的单例。

        修复：此前 tasks_module.py 每次都 `BatchTaskManager(max_workers=2)` 各建一份
        实例，performance_module.py / modules.py(首页) 又都尝试用
        `BatchTaskManager.get_instance()`（此前根本不存在这个方法）去读"全局"任务
        状态——`hasattr` 检查为 False，永远读不到真实数据，只能显示"就绪"占位值。
        现在提供真正的单例，三处都读同一份数据。
        """
        if cls._instance is None:
            cls._instance = cls(max_workers=max_workers)
        return cls._instance

    def __init__(self, max_workers: int = 4):
        """
        初始化管理器
        
        Args:
            max_workers: 最大并行工作线程数
        """
        self.max_workers = max_workers
        self.task_queues: Dict[str, TaskQueue] = {}
        self.active_tasks: Dict[str, threading.Thread] = {}
        self.task_history: List[BatchTask] = []
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._worker_semaphore = threading.Semaphore(max_workers)  # T-0: 并发控制

        # T-6: 定时调度
        self._scheduled_tasks: Dict[str, BatchTask] = {}
        self._scheduler_thread: Optional[threading.Thread] = None
        self._scheduler_running = False

        # 任务处理器映射
        self._processors: Dict[str, Callable] = {}
        
        logger.info(f"📋 批量任务管理器初始化完成")
        logger.info(f"   最大工作线程: {max_workers}")
        logger.info(f"   定时调度器: 待启动")
    
    def register_processor(self, task_type: str, processor: Callable):
        """
        注册任务处理器
        
        Args:
            task_type: 任务类型
            processor: 处理函数
        """
        self._processors[task_type] = processor
        logger.info(f"   注册处理器: {task_type}")
    
    def create_queue(self, name: str) -> str:
        """
        创建任务队列
        
        Args:
            name: 队列名称
            
        Returns:
            str: 队列ID
        """
        queue_id = str(uuid.uuid4())[:8]
        task_queue = TaskQueue(
            queue_id=queue_id,
            name=name,
            tasks=[],
            status=TaskStatus.PENDING,
            created_at=datetime.now()
        )
        
        with self._lock:
            self.task_queues[queue_id] = task_queue
        
        logger.info(f"✅ 创建队列: {name} (ID: {queue_id})")
        return queue_id
    
    def add_task(self, queue_id: str, name: str, task_type: str,
                params: Dict[str, Any],
                priority: TaskPriority = TaskPriority.NORMAL,
                callback: Optional[Callable] = None,
                depends_on: List[str] = None,
                max_retries: int = 0,
                retry_delay: float = 5.0,
                scheduled_at: datetime = None) -> str:
        """
        添加任务到队列
        
        Args:
            queue_id: 队列ID
            name: 任务名称
            task_type: 任务类型
            params: 任务参数
            priority: 优先级
            callback: 完成回调
            depends_on: T-1 依赖的任务ID列表
            max_retries: T-3 最大重试次数
            retry_delay: T-3 重试间隔(秒)
            scheduled_at: T-6 定时执行时间
            
        Returns:
            str: 任务ID
        """
        task_id = str(uuid.uuid4())[:8]
        
        # T-6: 如果有 scheduled_at 且是未来时间，状态保持 PENDING 但不立即入队
        now = datetime.now()
        if scheduled_at and scheduled_at > now:
            effective_status = TaskStatus.PENDING
        else:
            effective_status = TaskStatus.PENDING
            scheduled_at = None  # 过去的时间视为立即执行
        
        task = BatchTask(
            task_id=task_id,
            name=name,
            task_type=task_type,
            params=params,
            priority=priority,
            status=effective_status,
            progress=0.0,
            created_at=now,
            callback=callback,
            depends_on=depends_on or [],
            max_retries=max_retries,
            retry_count=0,
            retry_delay=retry_delay,
            scheduled_at=scheduled_at,
        )
        
        with self._lock:
            if queue_id in self.task_queues:
                self.task_queues[queue_id].tasks.append(task)
                self.task_queues[queue_id].total_tasks += 1
                logger.info(f"➕ 添加任务: {name} (ID: {task_id}) 到队列 {queue_id}")
                if depends_on:
                    logger.info(f"   T-1 依赖: {depends_on}")
                if scheduled_at:
                    logger.info(f"   T-6 定时: {scheduled_at}")
            else:
                raise ValueError(f"队列不存在: {queue_id}")
        
        # T-6: 自动注册到调度器
        if scheduled_at:
            self._register_scheduled(task)

        return task_id

    # ════════════════════════════════════════════════════════════════
    # T-1: 任务依赖管理
    # ════════════════════════════════════════════════════════════════

    def add_dependency(self, task_id: str, depends_on_id: str) -> bool:
        """添加任务依赖 (T-1)
        
        Args:
            task_id: 当前任务ID
            depends_on_id: 依赖的任务ID
        
        Returns:
            是否添加成功
        """
        with self._lock:
            for q_id, queue in self.task_queues.items():
                for task in queue.tasks:
                    if task.task_id == task_id:
                        if depends_on_id not in task.depends_on:
                            task.depends_on.append(depends_on_id)
                        logger.info(f"🔗 T-1 依赖: {task.name} → {depends_on_id}")
                    return True
        return False

    def _check_dependencies_met(self, task: BatchTask) -> bool:
        """检查任务的所有依赖是否已完成 (T-1)
        
        Returns:
            True 如果所有依赖都已完成
        """
        if not task.depends_on:
            return True
        
        with self._lock:
            for q_id, queue in self.task_queues.items():
                for t in queue.tasks:
                    if t.task_id in task.depends_on:
                        if t.status != TaskStatus.COMPLETED:
                            return False
        return True

    # ════════════════════════════════════════════════════════════════
    # T-6: 定时任务调度
    # ════════════════════════════════════════════════════════════════

    def schedule_task(self, queue_id: str, name: str, task_type: str,
                      params: Dict[str, Any],
                      scheduled_at: datetime,
                      priority: TaskPriority = TaskPriority.NORMAL,
                      callback: Optional[Callable] = None,
                      depends_on: List[str] = None) -> str:
        """创建定时任务 (T-6)
        
        Args:
            queue_id: 目标队列
            name: 任务名称
            task_type: 任务类型
            params: 任务参数
            scheduled_at: 执行时间
            priority: 优先级
            callback: 完成回调
            depends_on: 依赖任务
            
        Returns:
            任务ID
        """
        return self.add_task(
            queue_id=queue_id,
            name=name,
            task_type=task_type,
            params=params,
            priority=priority,
            callback=callback,
            depends_on=depends_on,
            scheduled_at=scheduled_at,
        )

    def _register_scheduled(self, task: BatchTask):
        """注册定时任务到后台调度线程"""
        with self._lock:
            self._scheduled_tasks[task.task_id] = task
        
        # 若调度线程未启动则启动
        if not self._scheduler_running:
            self._start_scheduler()

    def _start_scheduler(self):
        """启动后台定时调度线程 (T-6)"""
        if self._scheduler_running:
            return
        
        self._scheduler_running = True
        self._scheduler_thread = threading.Thread(
            target=self._scheduler_loop,
            daemon=True,
            name="scheduler"
        )
        self._scheduler_thread.start()
        logger.info("🕐 T-6 定时调度器已启动")

    def _scheduler_loop(self):
        """定时调度器主循环 (每秒检查)"""
        while self._scheduler_running and not self._stop_event.is_set():
            try:
                now = datetime.now()
                due_tasks = []
                
                with self._lock:
                    for task_id, task in list(self._scheduled_tasks.items()):
                        if task.scheduled_at and task.scheduled_at <= now:
                            due_tasks.append(task)
                            del self._scheduled_tasks[task_id]
                
                # 到期任务: 清除 scheduled_at 使其变为普通任务
                for task in due_tasks:
                    task.scheduled_at = None
                    logger.info(f"⏰ T-6 到期执行: {task.name} (ID: {task.task_id})")
            except Exception as e:
                logger.warning(f"⚠️ 调度器错误: {e}")
            
            time.sleep(1)
    
    def add_tasks_batch(self, queue_id: str, tasks: List[Dict]) -> List[str]:
        """
        批量添加任务
        
        Args:
            queue_id: 队列ID
            tasks: 任务列表，每个任务是一个字典
            
        Returns:
            List[str]: 任务ID列表
        """
        task_ids = []
        for task_info in tasks:
            task_id = self.add_task(
                queue_id=queue_id,
                name=task_info.get("name", "未命名任务"),
                task_type=task_info.get("task_type", "unknown"),
                params=task_info.get("params", {}),
                priority=task_info.get("priority", TaskPriority.NORMAL),
                callback=task_info.get("callback")
            )
            task_ids.append(task_id)
        
        return task_ids
    
    def start_queue(self, queue_id: str):
        """
        启动队列处理
        
        Args:
            queue_id: 队列ID
        """
        with self._lock:
            if queue_id not in self.task_queues:
                raise ValueError(f"队列不存在: {queue_id}")
            
            queue = self.task_queues[queue_id]
            if queue.status == TaskStatus.RUNNING:
                logger.warning(f"⚠️ 队列 {queue_id} 已在运行中")
                return
            
            queue.status = TaskStatus.RUNNING
        
        # 启动处理线程
        thread = threading.Thread(
            target=self._process_queue,
            args=(queue_id,),
            daemon=True
        )
        thread.start()
        
        self.active_tasks[queue_id] = thread
        logger.info(f"▶️ 启动队列: {queue_id}")
    
    def _process_queue(self, queue_id: str):
        """处理队列中的任务 (含 T-1 / T-3 / T-6 增强)"""
        while not self._stop_event.is_set():
            with self._lock:
                if queue_id not in self.task_queues:
                    break
                
                queue = self.task_queues[queue_id]
                
                # 检查队列状态
                if queue.status == TaskStatus.PAUSED:
                    time.sleep(1)
                    continue
                
                if queue.status == TaskStatus.CANCELLED:
                    break
                
                # 获取待处理任务（排除未来定时任务）
                now = datetime.now()
                pending_tasks = [
                    t for t in queue.tasks
                    if t.status == TaskStatus.PENDING
                    and (t.scheduled_at is None or t.scheduled_at <= now)
                ]
                if not pending_tasks:
                    # 所有任务完成
                    if all(t.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED] 
                           for t in queue.tasks):
                        queue.status = TaskStatus.COMPLETED
                        logger.info(f"✅ 队列 {queue_id} 处理完成")
                        break
                    time.sleep(0.5)
                    continue
                
                # 按优先级排序
                pending_tasks.sort(key=lambda t: t.priority.value)
                
                # T-1: 找到第一个依赖已满足的任务
                task_to_run = None
                for task in pending_tasks:
                    if self._check_dependencies_met(task):
                        task_to_run = task
                        break

                if task_to_run is None:
                    # 所有待处理任务都有未满足的依赖
                    time.sleep(1)
                    continue

                task_to_run.status = TaskStatus.RUNNING
                task_to_run.started_at = datetime.now()
            
            # 处理任务 (T-3: 重试逻辑)
            try:
                self._worker_semaphore.acquire()
                try:
                    self._execute_task_with_retry(task_to_run)
                finally:
                    self._worker_semaphore.release()
            except Exception as e:
                task_to_run.status = TaskStatus.FAILED
                task_to_run.error_message = str(e)
                logger.error(f"❌ 任务 {task_to_run.task_id} 失败: {e}")
            
            # 更新队列统计
            with self._lock:
                if queue_id in self.task_queues:
                    queue = self.task_queues[queue_id]
                    queue.completed_tasks = sum(1 for t in queue.tasks if t.status == TaskStatus.COMPLETED)
                    queue.failed_tasks = sum(1 for t in queue.tasks if t.status == TaskStatus.FAILED)
    
    def _execute_task_with_retry(self, task: BatchTask):
        """执行任务 (支持 T-3 自动重试)"""
        max_attempts = task.max_retries + 1
        
        for attempt in range(max_attempts):
            try:
                self._execute_task(task)
                return  # 成功
            except Exception as e:
                task.retry_count = attempt + 1
                if attempt < max_attempts - 1:
                    logger.info(f"🔄 T-3 重试 {task.name} (第{task.retry_count}次, {task.retry_delay}s后)")
                    time.sleep(task.retry_delay)
                    task.status = TaskStatus.RUNNING  # 重置状态准备重试
                else:
                    raise  # 所有重试失败
    
    def _execute_task(self, task: BatchTask):
        """执行单个任务"""
        logger.info(f"🚀 执行任务: {task.name} (ID: {task.task_id})")
        
        # 获取处理器
        processor = self._processors.get(task.task_type)
        if not processor:
            raise ValueError(f"未找到任务类型 {task.task_type} 的处理器")
        
        # 执行处理
        def progress_callback(progress, message=""):
            task.progress = progress
            if message:
                print(f"   {task.name}: {message}")
        
        try:
            result = processor(task.params, progress_callback)

            # 修复：此前只要 processor 不抛异常就一律标 COMPLETED，
            # 但 tasks_module.py 里几个处理器（剪辑/AI生成/导出/转码）在缺视频
            # 等前置条件不满足时会如实返回 {"status": "pending"/"error", ...}
            # 而不是抛异常——导致"未处理"的任务在 UI 上也显示"已完成 100%"。
            # 这里显式识别这类返回值，转为失败，而不是把它们当成功处理。
            if isinstance(result, dict) and result.get("status") in ("pending", "error"):
                reason = result.get("note") or result.get("error") or "任务未满足执行条件"
                raise RuntimeError(reason)

            task.result = result
            task.status = TaskStatus.COMPLETED
            task.progress = 100.0
            task.completed_at = datetime.now()
            
            # 调用回调
            if task.callback:
                task.callback(task)
            
            logger.info(f"✅ 任务完成: {task.name}")
            
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error_message = str(e)
            logger.error(f"❌ 任务失败: {task.name} - {e}")
            raise
    
    def pause_queue(self, queue_id: str):
        """暂停队列"""
        with self._lock:
            if queue_id in self.task_queues:
                self.task_queues[queue_id].status = TaskStatus.PAUSED
                logger.info(f"⏸️ 暂停队列: {queue_id}")
    
    def resume_queue(self, queue_id: str):
        """恢复队列"""
        with self._lock:
            if queue_id in self.task_queues:
                self.task_queues[queue_id].status = TaskStatus.RUNNING
                logger.info(f"▶️ 恢复队列: {queue_id}")
    
    def cancel_queue(self, queue_id: str):
        """取消队列"""
        with self._lock:
            if queue_id in self.task_queues:
                queue = self.task_queues[queue_id]
                queue.status = TaskStatus.CANCELLED
                
                # 取消所有待处理任务
                for task in queue.tasks:
                    if task.status == TaskStatus.PENDING:
                        task.status = TaskStatus.CANCELLED
                
                logger.info(f"⏹️ 取消队列: {queue_id}")
    
    def get_queue_status(self, queue_id: str) -> Dict[str, Any]:
        """获取队列状态"""
        with self._lock:
            if queue_id not in self.task_queues:
                return {}
            
            queue = self.task_queues[queue_id]
            return {
                "queue_id": queue.queue_id,
                "name": queue.name,
                "status": queue.status.value,
                "total_tasks": queue.total_tasks,
                "completed_tasks": queue.completed_tasks,
                "failed_tasks": queue.failed_tasks,
                "progress": (queue.completed_tasks / queue.total_tasks * 100) if queue.total_tasks > 0 else 0,
                "tasks": [
                    {
                        "task_id": t.task_id,
                        "name": t.name,
                        "status": t.status.value,
                        "progress": t.progress,
                        "priority": t.priority.name
                    }
                    for t in queue.tasks
                ]
            }
    
    def get_all_queues(self) -> List[Dict[str, Any]]:
        """获取所有队列状态"""
        with self._lock:
            return [self.get_queue_status(qid) for qid in self.task_queues.keys()]
    
    def remove_completed_tasks(self, queue_id: str):
        """清理已完成的任务"""
        with self._lock:
            if queue_id in self.task_queues:
                queue = self.task_queues[queue_id]
                completed = [t for t in queue.tasks if t.status == TaskStatus.COMPLETED]
                queue.tasks = [t for t in queue.tasks if t.status != TaskStatus.COMPLETED]
                
                # 添加到历史
                self.task_history.extend(completed)
                
                logger.info(f"🧹 清理队列 {queue_id}: 移除 {len(completed)} 个已完成任务")
    
    def export_queue_report(self, queue_id: str, output_path: str):
        """导出队列报告"""
        status = self.get_queue_status(queue_id)
        
        report = {
            "generated_at": datetime.now().isoformat(),
            "queue_info": status,
            "summary": {
                "success_rate": (status.get("completed_tasks", 0) / status.get("total_tasks", 1) * 100),
                "failure_rate": (status.get("failed_tasks", 0) / status.get("total_tasks", 1) * 100),
            }
        }
        
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        logger.info(f"📊 报告已导出: {output_path}")
    
    def shutdown(self):
        """关闭管理器"""
        logger.info("🛑 关闭批量任务管理器...")
        self._stop_event.set()
        
        # 等待所有线程结束
        for thread in self.active_tasks.values():
            thread.join(timeout=5)
        
        logger.info("✅ 批量任务管理器已关闭")


# 使用示例
if __name__ == "__main__":
    # 创建管理器
    manager = BatchTaskManager(max_workers=2)
    
    # 注册处理器
    def example_processor(params, progress_callback):
        """示例处理器"""
        total_steps = 5
        for i in range(total_steps):
            time.sleep(0.5)
            progress = (i + 1) / total_steps * 100
            progress_callback(progress, f"步骤 {i+1}/{total_steps}")
        return {"status": "success", "output": "处理完成"}
    
    manager.register_processor("example", example_processor)
    
    # 创建队列
    queue_id = manager.create_queue("测试队列")
    
    # 添加任务
    for i in range(5):
        manager.add_task(
            queue_id=queue_id,
            name=f"任务 {i+1}",
            task_type="example",
            params={"input": f"data_{i}"},
            priority=TaskPriority.NORMAL
        )
    
    # 启动队列
    manager.start_queue(queue_id)
    
    # 等待处理完成
    time.sleep(10)
    
    # 获取状态
    status = manager.get_queue_status(queue_id)
    print(f"\n队列状态:")
    print(f"  总任务: {status['total_tasks']}")
    print(f"  已完成: {status['completed_tasks']}")
    print(f"  失败: {status['failed_tasks']}")
    print(f"  进度: {status['progress']:.1f}%")
    
    # 关闭
    manager.shutdown()

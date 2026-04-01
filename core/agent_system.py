from enum import Enum
from dataclasses import dataclass
from typing import Optional, Callable, Any
import threading
import queue
import time

class TaskPriority(Enum):
    LOW = 1
    NORMAL = 2
    HIGH = 3
    URGENT = 4

@dataclass
class AgentTask:
    name: str
    func: Callable
    args: tuple = ()
    kwargs: dict = None
    priority: TaskPriority = TaskPriority.NORMAL
    callback: Optional[Callable] = None
    
    def __post_init__(self):
        if self.kwargs is None:
            self.kwargs = {}

class AgentManager:
    def __init__(self, max_workers: int = 4):
        self.max_workers = max_workers
        self.task_queue = queue.PriorityQueue()
        self.workers = []
        self.running = False
        self.results = {}
    
    def start(self):
        self.running = True
        for _ in range(self.max_workers):
            worker = threading.Thread(target=self._worker, daemon=True)
            worker.start()
            self.workers.append(worker)
    
    def stop(self):
        self.running = False
        for worker in self.workers:
            worker.join(timeout=1)
        self.workers = []
    
    def _worker(self):
        while self.running:
            try:
                priority, task = self.task_queue.get(timeout=0.5)
                try:
                    result = task.func(*task.args, **task.kwargs)
                    self.results[task.name] = result
                    if task.callback:
                        task.callback(result)
                except Exception as e:
                    print(f"Agent任务执行失败: {e}")
                    self.results[task.name] = None
            except queue.Empty:
                continue
    
    def submit_task(self, task: AgentTask):
        self.task_queue.put((-task.priority.value, task))
    
    def get_result(self, task_name: str) -> Any:
        return self.results.get(task_name)

_agent_manager = None

def initialize_agent_system(max_workers: int = 4) -> AgentManager:
    global _agent_manager
    if _agent_manager is None:
        _agent_manager = AgentManager(max_workers)
        _agent_manager.start()
    return _agent_manager

def shutdown_agent_system():
    global _agent_manager
    if _agent_manager:
        _agent_manager.stop()
        _agent_manager = None

__all__ = [
    'AgentManager', 'AgentTask', 'TaskPriority',
    'initialize_agent_system', 'shutdown_agent_system'
]

"""
Skill 执行引擎
=============
步骤调度、状态管理、数据流的核心引擎
支持 ComfyUI 式节点数据流
"""

from typing import Dict, Any, List, Optional, Callable, Type
from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod
import time
import uuid
import threading
import json

from .core import EventBus, EventType, DataBus


class SkillState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"


class StepState(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass
class StepResult:
    success: bool
    output: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SkillStep:
    id: str
    name: str
    description: str = ""
    handler: Optional[Callable] = None
    condition: Optional[Callable[[Dict], bool]] = None
    retry_count: int = 0
    timeout: float = 300.0
    state: StepState = StepState.PENDING
    result: Optional[StepResult] = None
    dependencies: List[str] = field(default_factory=list)
    
    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())[:8]


@dataclass
class SkillContext:
    """Skill 执行上下文"""
    skill_id: str
    inputs: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)
    variables: Dict[str, Any] = field(default_factory=dict)
    step_results: Dict[str, StepResult] = field(default_factory=dict)
    start_time: float = 0.0
    current_step: Optional[str] = None
    
    def set_variable(self, key: str, value: Any):
        self.variables[key] = value
    
    def get_variable(self, key: str, default: Any = None) -> Any:
        return self.variables.get(key, default)
    
    def set_output(self, key: str, value: Any):
        self.outputs[key] = value
    
    def get_input(self, key: str, default: Any = None) -> Any:
        return self.inputs.get(key, default)


class Skill(ABC):
    """
    Skill 基类 - 所有 Skill 必须继承此类
    
    Skill 是一组有序步骤的集合，每个步骤可以：
    - 依赖其他步骤
    - 有条件执行
    - 支持重试和超时
    """
    
    skill_id: str = ""
    skill_name: str = ""
    skill_description: str = ""
    skill_category: str = "通用"
    skill_icon: str = "⚙️"
    skill_version: str = "1.0.0"
    
    def __init__(self):
        self._steps: List[SkillStep] = []
        self._state = SkillState.IDLE
        self._context: Optional[SkillContext] = None
        self._event_bus = EventBus.get_instance()
        self._data_bus = DataBus.get_instance()
        self._progress_callback: Optional[Callable[[int, str], None]] = None
        self._lock = threading.Lock()
        self._cancel_flag = False
        self._pause_flag = False
        
        self._setup_steps()
    
    @abstractmethod
    def _setup_steps(self):
        """设置步骤（子类实现）"""
        pass
    
    @property
    def state(self) -> SkillState:
        return self._state
    
    @property
    def steps(self) -> List[SkillStep]:
        return self._steps
    
    def add_step(self, step: SkillStep) -> 'Skill':
        """添加步骤"""
        self._steps.append(step)
        return self
    
    def step(self, name: str, handler: Callable = None, 
             condition: Callable[[Dict], bool] = None,
             dependencies: List[str] = None,
             retry_count: int = 0,
             timeout: float = 300.0) -> 'Skill':
        """添加步骤的便捷方法"""
        step = SkillStep(
            id="",
            name=name,
            handler=handler,
            condition=condition,
            dependencies=dependencies or [],
            retry_count=retry_count,
            timeout=timeout
        )
        self._steps.append(step)
        return self
    
    def set_progress_callback(self, callback: Callable[[int, str], None]):
        """设置进度回调"""
        self._progress_callback = callback
    
    def _report_progress(self, progress: int, message: str):
        """报告进度"""
        if self._progress_callback:
            self._progress_callback(progress, message)
    
    def _get_step_order(self) -> List[str]:
        """获取拓扑排序后的步骤执行顺序"""
        step_map = {s.id: s for s in self._steps}
        in_degree = {s.id: 0 for s in self._steps}
        
        for step in self._steps:
            for dep_id in step.dependencies:
                if dep_id in in_degree:
                    in_degree[step.id] += 1
        
        queue = [sid for sid, deg in in_degree.items() if deg == 0]
        result = []
        
        while queue:
            current = queue.pop(0)
            result.append(current)
            
            for step in self._steps:
                if current in step.dependencies:
                    in_degree[step.id] -= 1
                    if in_degree[step.id] == 0:
                        queue.append(step.id)
        
        return result
    
    def execute(self, inputs: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        执行 Skill
        """
        self._context = SkillContext(
            skill_id=self.skill_id or str(uuid.uuid4())[:8],
            inputs=inputs or {}
        )
        self._context.start_time = time.time()
        self._state = SkillState.RUNNING
        self._cancel_flag = False
        self._pause_flag = False
        
        self._event_bus.emit(EventType.TASK_STARTED, {
            "skill_id": self.skill_id,
            "skill_name": self.skill_name
        })
        
        step_order = self._get_step_order()
        total_steps = len(step_order)
        
        for i, step_id in enumerate(step_order):
            if self._cancel_flag:
                self._state = SkillState.CANCELLED
                break
            
            while self._pause_flag:
                time.sleep(0.1)
            
            step = next((s for s in self._steps if s.id == step_id), None)
            if not step:
                continue
            
            self._context.current_step = step_id
            
            progress = int((i / total_steps) * 100) if total_steps > 0 else 100
            self._report_progress(progress, f"执行步骤: {step.name}")
            
            self._event_bus.emit(EventType.BLOCK_STARTED, {
                "skill_id": self.skill_id,
                "step_id": step_id,
                "step_name": step.name
            })
            
            if step.condition:
                try:
                    if not step.condition(self._context.variables):
                        step.state = StepState.SKIPPED
                        continue
                except Exception as e:
                    step.state = StepState.ERROR
                    step.result = StepResult(success=False, error=str(e))
                    continue
            
            step.state = StepState.RUNNING
            
            for attempt in range(step.retry_count + 1):
                try:
                    if step.handler:
                        result = step.handler(self._context)
                    else:
                        result = StepResult(success=True)
                    
                    if isinstance(result, StepResult):
                        step.result = result
                    else:
                        step.result = StepResult(success=True, output=result)
                    
                    if step.result.success:
                        step.state = StepState.COMPLETED
                        self._context.step_results[step_id] = step.result
                        
                        if step.result.output:
                            if isinstance(step.result.output, dict):
                                self._context.variables.update(step.result.output)
                        
                        self._event_bus.emit(EventType.BLOCK_COMPLETED, {
                            "skill_id": self.skill_id,
                            "step_id": step_id,
                            "step_name": step.name
                        })
                        break
                    else:
                        if attempt == step.retry_count:
                            step.state = StepState.ERROR
                            self._event_bus.emit(EventType.BLOCK_FAILED, {
                                "skill_id": self.skill_id,
                                "step_id": step_id,
                                "step_name": step.name,
                                "error": step.result.error
                            })
                
                except Exception as e:
                    step.result = StepResult(success=False, error=str(e))
                    if attempt == step.retry_count:
                        step.state = StepState.ERROR
                        self._event_bus.emit(EventType.BLOCK_FAILED, {
                            "skill_id": self.skill_id,
                            "step_id": step_id,
                            "step_name": step.name,
                            "error": str(e)
                        })
        
        execution_time = time.time() - self._context.start_time
        
        if self._state == SkillState.RUNNING:
            has_error = any(s.state == StepState.ERROR for s in self._steps)
            self._state = SkillState.ERROR if has_error else SkillState.COMPLETED
        
        self._event_bus.emit(
            EventType.TASK_COMPLETED if self._state == SkillState.COMPLETED else EventType.TASK_FAILED,
            {
                "skill_id": self.skill_id,
                "skill_name": self.skill_name,
                "execution_time": execution_time,
                "state": self._state.value
            }
        )
        
        self._report_progress(100, "执行完成" if self._state == SkillState.COMPLETED else "执行失败")
        
        return {
            "success": self._state == SkillState.COMPLETED,
            "outputs": self._context.outputs,
            "step_results": {sid: {"success": r.success, "output": r.output, "error": r.error} 
                            for sid, r in self._context.step_results.items()},
            "execution_time": execution_time,
            "state": self._state.value
        }
    
    def pause(self):
        """暂停执行"""
        self._pause_flag = True
        self._state = SkillState.PAUSED
    
    def resume(self):
        """恢复执行"""
        self._pause_flag = False
        self._state = SkillState.RUNNING
    
    def cancel(self):
        """取消执行"""
        self._cancel_flag = True
    
    def reset(self):
        """重置状态"""
        self._state = SkillState.IDLE
        self._context = None
        self._cancel_flag = False
        self._pause_flag = False
        for step in self._steps:
            step.state = StepState.PENDING
            step.result = None
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化"""
        return {
            "skill_id": self.skill_id,
            "skill_name": self.skill_name,
            "skill_description": self.skill_description,
            "skill_category": self.skill_category,
            "skill_version": self.skill_version,
            "steps": [
                {
                    "id": s.id,
                    "name": s.name,
                    "description": s.description,
                    "dependencies": s.dependencies,
                    "retry_count": s.retry_count,
                    "timeout": s.timeout
                }
                for s in self._steps
            ]
        }


class SkillRegistry:
    """Skill 注册表"""
    
    _instance: Optional['SkillRegistry'] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._skills: Dict[str, Type[Skill]] = {}
        self._lock = threading.Lock()
    
    def register(self, skill_class: Type[Skill]) -> bool:
        """注册 Skill"""
        try:
            temp = skill_class()
            skill_id = temp.skill_id or skill_class.__name__
            with self._lock:
                self._skills[skill_id] = skill_class
            return True
        except Exception as e:
            print(f"注册 Skill 失败: {e}")
            return False
    
    def unregister(self, skill_id: str) -> bool:
        """注销 Skill"""
        with self._lock:
            if skill_id in self._skills:
                del self._skills[skill_id]
                return True
            return False
    
    def get_skill_class(self, skill_id: str) -> Optional[Type[Skill]]:
        """获取 Skill 类"""
        return self._skills.get(skill_id)
    
    def create_instance(self, skill_id: str) -> Optional[Skill]:
        """创建 Skill 实例"""
        skill_class = self.get_skill_class(skill_id)
        if skill_class:
            return skill_class()
        return None
    
    def list_skills(self) -> List[Dict[str, Any]]:
        """列出所有 Skill"""
        result = []
        for skill_id, skill_class in self._skills.items():
            temp = skill_class()
            result.append({
                "skill_id": skill_id,
                "skill_name": temp.skill_name,
                "skill_description": temp.skill_description,
                "skill_category": temp.skill_category,
                "skill_icon": temp.skill_icon,
                "skill_version": temp.skill_version
            })
        return result
    
    @classmethod
    def get_instance(cls) -> 'SkillRegistry':
        return cls()


class SkillEngine:
    """
    Skill 执行引擎 - 管理所有 Skill 的执行
    """
    
    _instance: Optional['SkillEngine'] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._registry = SkillRegistry.get_instance()
        self._running_skills: Dict[str, Skill] = {}
        self._event_bus = EventBus.get_instance()
        self._lock = threading.Lock()
    
    def register_skill(self, skill_class: Type[Skill]) -> bool:
        """注册 Skill"""
        return self._registry.register(skill_class)
    
    def execute_skill(self, skill_id: str, inputs: Dict[str, Any] = None,
                     progress_callback: Callable[[int, str], None] = None,
                     async_mode: bool = False) -> Dict[str, Any]:
        """执行 Skill"""
        skill = self._registry.create_instance(skill_id)
        if not skill:
            return {"success": False, "error": f"Skill '{skill_id}' 不存在"}
        
        if progress_callback:
            skill.set_progress_callback(progress_callback)
        
        with self._lock:
            self._running_skills[skill.skill_id] = skill
        
        try:
            if async_mode:
                thread = threading.Thread(
                    target=self._execute_in_thread,
                    args=(skill, inputs)
                )
                thread.daemon = True
                thread.start()
                return {"success": True, "message": "Skill 已在后台启动", "skill_id": skill.skill_id}
            else:
                return skill.execute(inputs)
        finally:
            with self._lock:
                if skill.skill_id in self._running_skills:
                    del self._running_skills[skill.skill_id]
    
    def _execute_in_thread(self, skill: Skill, inputs: Dict[str, Any]):
        """在线程中执行 Skill"""
        skill.execute(inputs)
    
    def pause_skill(self, skill_id: str) -> bool:
        """暂停 Skill"""
        with self._lock:
            if skill_id in self._running_skills:
                self._running_skills[skill_id].pause()
                return True
        return False
    
    def resume_skill(self, skill_id: str) -> bool:
        """恢复 Skill"""
        with self._lock:
            if skill_id in self._running_skills:
                self._running_skills[skill_id].resume()
                return True
        return False
    
    def cancel_skill(self, skill_id: str) -> bool:
        """取消 Skill"""
        with self._lock:
            if skill_id in self._running_skills:
                self._running_skills[skill_id].cancel()
                return True
        return False
    
    def get_skill_state(self, skill_id: str) -> Optional[SkillState]:
        """获取 Skill 状态"""
        with self._lock:
            if skill_id in self._running_skills:
                return self._running_skills[skill_id].state
        return None
    
    def list_available_skills(self) -> List[Dict[str, Any]]:
        """列出可用的 Skill"""
        return self._registry.list_skills()
    
    def get_latest_skills(self) -> Dict[str, Any]:
        """获取最新的 Skill
        
        返回:
            Dict: 包含最新skill列表和clawhud链接的字典
        """
        try:
            # 尝试从服务器获取最新的skill
            # 这里是模拟实现，实际项目中应该调用真实的API
            import requests
            response = requests.get("https://api.example.com/skills/latest", timeout=5)
            latest_skills = response.json()
            
            return {
                "success": True,
                "skills": latest_skills,
                "clawhud_link": "https://clawhud.example.com/latest-skills"
            }
        except Exception as e:
            # 如果获取失败，返回本地可用的skill和clawhud链接
            return {
                "success": False,
                "error": str(e),
                "skills": self.list_available_skills(),
                "clawhud_link": "https://clawhud.example.com/latest-skills"
            }
    
    @classmethod
    def get_instance(cls) -> 'SkillEngine':
        return cls()


skill_registry = SkillRegistry.get_instance()
skill_engine = SkillEngine.get_instance()

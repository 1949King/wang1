"""
乐高积木基类（LegoBlock）
========================
所有积木必须遵守的统一接口协议 - 乐高的"凸点与凹孔"

铁律：
1. 不依赖 UI
2. 不依赖其他积木
3. 输入 → 输出 纯函数式
4. 只通过"标准协议"和底板通信
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable, Type
from enum import Enum
import time
import uuid


class BlockState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    ERROR = "error"
    DISABLED = "disabled"


class InputType(Enum):
    VIDEO = "video"
    AUDIO = "audio"
    IMAGE = "image"
    TEXT = "text"
    SUBTITLE = "subtitle"
    JSON = "json"
    FILE = "file"
    DIRECTORY = "directory"
    CONFIG = "config"
    ANY = "any"


class OutputType(Enum):
    VIDEO = "video"
    AUDIO = "audio"
    IMAGE = "image"
    TEXT = "text"
    SUBTITLE = "subtitle"
    JSON = "json"
    FILE = "file"
    DIRECTORY = "directory"
    ANY = "any"


@dataclass
class BlockInput:
    name: str
    type: InputType
    description: str = ""
    required: bool = True
    default: Any = None
    options: List[Any] = field(default_factory=list)
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    
    def validate(self, value: Any) -> bool:
        if value is None:
            return not self.required
        if self.options and value not in self.options:
            return False
        if self.min_value is not None and isinstance(value, (int, float)):
            if value < self.min_value:
                return False
        if self.max_value is not None and isinstance(value, (int, float)):
            if value > self.max_value:
                return False
        return True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type.value,
            "description": self.description,
            "required": self.required,
            "default": self.default,
            "options": self.options,
            "min_value": self.min_value,
            "max_value": self.max_value
        }


@dataclass
class BlockOutput:
    name: str
    type: OutputType
    description: str = ""
    value: Any = None
    
    def set_value(self, value: Any):
        self.value = value
        return self
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type.value,
            "description": self.description,
            "value": self.value
        }


@dataclass
class BlockMeta:
    name: str
    version: str = "1.0.0"
    author: str = "Unknown"
    description: str = ""
    category: str = "通用"
    tags: List[str] = field(default_factory=list)
    icon: str = ""
    dependencies: List[str] = field(default_factory=list)
    min_core_version: str = "1.0.0"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "author": self.author,
            "description": self.description,
            "category": self.category,
            "tags": self.tags,
            "icon": self.icon,
            "dependencies": self.dependencies,
            "min_core_version": self.min_core_version
        }


@dataclass
class BlockResult:
    success: bool
    outputs: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    execution_time: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


class LegoBlock(ABC):
    """
    乐高积木基类 - 所有积木必须继承此类
    
    遵守 4 条铁律：
    1. 不依赖 UI
    2. 不依赖其他积木
    3. 输入 → 输出 纯函数式
    4. 只通过"标准协议"和底板通信
    """
    
    def __init__(self):
        self._id: str = str(uuid.uuid4())
        self._state: BlockState = BlockState.IDLE
        self._inputs: Dict[str, Any] = {}
        self._outputs: Dict[str, Any] = {}
        self._progress: float = 0.0
        self._progress_callback: Optional[Callable[[float, str], None]] = None
        self._error: Optional[str] = None
        self._start_time: float = 0.0
    
    @property
    def id(self) -> str:
        return self._id
    
    @property
    def state(self) -> BlockState:
        return self._state
    
    @property
    def progress(self) -> float:
        return self._progress
    
    @abstractmethod
    def info(self) -> BlockMeta:
        """返回积木元信息（名称、版本、作者、描述等）"""
        pass
    
    @abstractmethod
    def inputs(self) -> List[BlockInput]:
        """定义输入参数（视频、字幕、配置等）"""
        pass
    
    @abstractmethod
    def outputs(self) -> List[BlockOutput]:
        """定义输出结果（视频、字幕、文本等）"""
        pass
    
    @abstractmethod
    def process(self, inputs: Dict[str, Any]) -> BlockResult:
        """
        核心处理逻辑（纯函数，无UI依赖）
        
        Args:
            inputs: 输入参数字典
            
        Returns:
            BlockResult: 包含成功状态、输出结果、错误信息等
        """
        pass
    
    def validate_inputs(self, inputs: Dict[str, Any]) -> tuple[bool, List[str]]:
        """验证输入参数"""
        errors = []
        input_defs = {inp.name: inp for inp in self.inputs()}
        
        for name, inp_def in input_defs.items():
            value = inputs.get(name)
            if value is None and inp_def.required:
                errors.append(f"缺少必需参数: {name}")
            elif value is not None and not inp_def.validate(value):
                errors.append(f"参数 {name} 验证失败")
        
        return len(errors) == 0, errors
    
    def set_progress_callback(self, callback: Callable[[float, str], None]):
        """设置进度回调"""
        self._progress_callback = callback
    
    def _report_progress(self, progress: float, message: str = ""):
        """报告进度"""
        self._progress = progress
        if self._progress_callback:
            self._progress_callback(progress, message)
    
    def run(self, inputs: Dict[str, Any]) -> BlockResult:
        """
        执行积木（带状态管理和错误处理）
        """
        is_valid, errors = self.validate_inputs(inputs)
        if not is_valid:
            return BlockResult(
                success=False,
                error="输入验证失败: " + "; ".join(errors)
            )
        
        self._state = BlockState.RUNNING
        self._inputs = inputs
        self._progress = 0.0
        self._start_time = time.time()
        
        try:
            result = self.process(inputs)
            result.execution_time = time.time() - self._start_time
            self._outputs = result.outputs
            self._state = BlockState.COMPLETED if result.success else BlockState.ERROR
            self._error = result.error
            return result
        except Exception as e:
            self._state = BlockState.ERROR
            self._error = str(e)
            return BlockResult(
                success=False,
                error=str(e),
                execution_time=time.time() - self._start_time
            )
    
    def pause(self):
        """暂停执行"""
        self._state = BlockState.PAUSED
    
    def resume(self):
        """恢复执行"""
        if self._state == BlockState.PAUSED:
            self._state = BlockState.RUNNING
    
    def cancel(self):
        """取消执行"""
        self._state = BlockState.IDLE
        self._progress = 0.0
    
    def reset(self):
        """重置状态"""
        self._state = BlockState.IDLE
        self._inputs = {}
        self._outputs = {}
        self._progress = 0.0
        self._error = None
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "id": self._id,
            "info": self.info().to_dict(),
            "inputs": [inp.to_dict() for inp in self.inputs()],
            "outputs": [out.to_dict() for out in self.outputs()],
            "state": self._state.value,
            "progress": self._progress
        }
    
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} '{self.info().name}' state={self._state.value}>"

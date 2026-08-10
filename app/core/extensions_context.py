"""
拓展执行上下文 (ExtensionsContext)
==================================
为 Skill 和 Plugin 执行提供统一的上下文环境，
类似 skill_engine.py 的 SkillContext。
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
import uuid
import time


@dataclass
class ExtensionsContext:
    """拓展执行上下文"""

    # 输入参数
    inputs: Dict[str, Any] = field(default_factory=dict)

    # 输出结果
    outputs: Dict[str, Any] = field(default_factory=dict)

    # 变量存储（跨步骤共享）
    variables: Dict[str, Any] = field(default_factory=dict)

    # 步骤执行结果
    step_results: Dict[str, Any] = field(default_factory=dict)

    # 执行元数据
    context_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    start_time: float = field(default_factory=time.time)
    current_step: Optional[str] = None
    current_extension: Optional[str] = None

    # 扩展点：可用的 Extension 注册表引用
    available_extensions: List[str] = field(default_factory=list)

    # 状态标记
    _completed: bool = False
    _error: Optional[str] = None

    def set_variable(self, key: str, value: Any):
        """设置变量"""
        self.variables[key] = value

    def get_variable(self, key: str, default: Any = None) -> Any:
        """获取变量"""
        return self.variables.get(key, default)

    def set_output(self, key: str, value: Any):
        """设置输出"""
        self.outputs[key] = value

    def get_input(self, key: str, default: Any = None) -> Any:
        """获取输入"""
        return self.inputs.get(key, default)

    def set_input(self, key: str, value: Any):
        """设置输入"""
        self.inputs[key] = value

    def get_step_result(self, step_id: str) -> Any:
        """获取步骤结果"""
        return self.step_results.get(step_id)

    def set_step_result(self, step_id: str, result: Any):
        """设置步骤结果"""
        self.step_results[step_id] = result

    @property
    def is_completed(self) -> bool:
        """是否已完成"""
        return self._completed

    @property
    def error(self) -> Optional[str]:
        """获取错误信息"""
        return self._error

    def mark_completed(self):
        """标记为完成"""
        self._completed = True

    def mark_error(self, error: str):
        """标记为错误"""
        self._error = error
        self._completed = True

    def elapsed_time(self) -> float:
        """获取已执行时间（秒）"""
        return time.time() - self.start_time

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "context_id": self.context_id,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "variables": self.variables,
            "elapsed": self.elapsed_time(),
            "completed": self._completed,
            "error": self._error,
        }


class ExtensionsContextManager:
    """
    拓展上下文管理器

    管理多个上下文实例，支持上下文复用和清理。
    """

    def __init__(self, max_contexts: int = 50):
        self._contexts: Dict[str, ExtensionsContext] = {}
        self._max_contexts = max_contexts

    def create_context(self, inputs: Dict[str, Any] = None) -> ExtensionsContext:
        """创建新上下文"""
        # 清理过期上下文
        self._cleanup_old_contexts()

        ctx = ExtensionsContext(inputs=inputs or {})
        self._contexts[ctx.context_id] = ctx
        return ctx

    def get_context(self, context_id: str) -> Optional[ExtensionsContext]:
        """获取上下文"""
        return self._contexts.get(context_id)

    def remove_context(self, context_id: str) -> bool:
        """移除上下文"""
        if context_id in self._contexts:
            del self._contexts[context_id]
            return True
        return False

    def list_contexts(self) -> List[str]:
        """列出所有上下文 ID"""
        return list(self._contexts.keys())

    def _cleanup_old_contexts(self):
        """清理过期上下文"""
        if len(self._contexts) > self._max_contexts:
            # 按时间排序，移除最旧的
            sorted_ids = sorted(
                self._contexts.keys(),
                key=lambda k: self._contexts[k].start_time,
                reverse=True
            )
            # 只保留最新的 N 个
            for old_id in sorted_ids[self._max_contexts:]:
                del self._contexts[old_id]

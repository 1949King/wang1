"""
云端 Provider 注册表（懒加载）
=============================
Sprint 2 目标：用统一的「模块注册 + 懒加载」机制，取代 cloud_api.py 中
硬编码的 ``PROVIDERS`` 字典。原字典在模块导入时即 eager import 全部 15 个
provider 类（连带拖入 requests），既拖慢启动又不利于插件化扩展。

本模块只登记「模块路径 + 类名」字符串，真正的 import 延迟到首次
resolve() 时才发生，并被缓存复用。

设计要点
--------
- register(name, module, attr): 仅登记 spec，不 import
- resolve(name): 首次访问时 importlib 动态导入并缓存，返回类对象
- names(): 列出所有已登记 provider（无需 import 任何实现）
- 插件/lego 组件迁移时可调用 register() 动态注册新 provider
"""

from __future__ import annotations

import importlib
import logging
from typing import Dict, List, Optional, Tuple, Type

from .base import BaseCloudProvider

logger = logging.getLogger(__name__)

# 15 个云端 provider 的「类全名」→ 注册用 spec。
# 注意：ollama 是本地离线 provider，由 CloudAPIService 单独处理，不在此登记。
_PROVIDER_CLASS_NAMES: Dict[str, str] = {
    "deepseek": "DeepSeekProvider",
    "doubao": "DoubaoProvider",
    "openai": "OpenAIProvider",
    "zhipu": "ZhipuProvider",
    "qwen": "QwenProvider",
    "wenxin": "WenxinProvider",
    "spark": "SparkProvider",
    "kimi": "KimiProvider",
    "baichuan": "BaichuanProvider",
    "minimax": "MiniMaxProvider",
    "claude": "ClaudeProvider",
    "groq": "GroqProvider",
    "siliconflow": "SiliconFlowProvider",
    "stepfun": "StepfunProvider",
    "yi": "YiProvider",
    "ollama": "OllamaProvider",
    "modelscope": "ModelScopeProvider",
}

_PROVIDER_MODULE = "app.modules.lego.cloud_providers.providers"


class ProviderRegistry:
    """云端 provider 的懒加载注册表。

    仅保存 name -> (module_path, class_name) 的 spec，import 推迟到 resolve()。
    """

    def __init__(self) -> None:
        # name -> (module_path, class_name)
        self._specs: Dict[str, Tuple[str, str]] = {}
        # name -> 已解析的类对象（缓存）
        self._cache: Dict[str, Type[BaseCloudProvider]] = {}
        self._lazy_failed: Dict[str, bool] = {}

    # ── 注册 ──────────────────────────────────────────────
    def register(self, name: str, module: str, attr: str) -> None:
        """登记一个 provider（只存 spec，不立即 import）。"""
        self._specs[name] = (module, attr)
        # 清掉旧缓存，确保下次 resolve 重新解析
        self._cache.pop(name, None)
        self._lazy_failed.pop(name, None)

    def register_class(self, name: str, cls: Type[BaseCloudProvider]) -> None:
        """直接登记一个已导入的类（用于测试或内建 provider）。"""
        if not (isinstance(cls, type) and issubclass(cls, BaseCloudProvider)):
            raise TypeError(f"{name} 必须继承自 BaseCloudProvider")
        self._specs[name] = (cls.__module__, cls.__qualname__)
        self._cache[name] = cls
        self._lazy_failed.pop(name, None)

    def bulk_register(self, mapping: Dict[str, str], module: str) -> None:
        """批量登记：{name: class_name} 共用同一个 module。"""
        for name, attr in mapping.items():
            self.register(name, module, attr)

    # ── 解析（懒加载核心） ───────────────────────────────
    def resolve(self, name: str) -> Optional[Type[BaseCloudProvider]]:
        """返回 provider 类；首次访问才动态 import 并缓存。失败返回 None。"""
        if name not in self._specs:
            return None
        if name in self._cache:
            return self._cache[name]
        if self._lazy_failed.get(name):
            return None
        module_path, attr = self._specs[name]
        try:
            module = importlib.import_module(module_path)
            cls = getattr(module, attr)
            if not (isinstance(cls, type) and issubclass(cls, BaseCloudProvider)):
                raise TypeError(f"{module_path}:{attr} 不是 BaseCloudProvider 子类")
            self._cache[name] = cls
            return cls
        except Exception as e:  # pragma: no cover - 依赖缺失等运行时错误
            self._lazy_failed[name] = True
            logger.error("懒加载 provider 失败 %s (%s): %s", name, module_path, e)
            return None

    # ── 查询 ──────────────────────────────────────────────
    def names(self) -> List[str]:
        """列出所有已登记 provider 名称（不触发任何 import）。"""
        return list(self._specs.keys())

    def is_registered(self, name: str) -> bool:
        return name in self._specs

    def specs(self) -> Dict[str, Tuple[str, str]]:
        """返回只读的 spec 快照（调试/UI 展示用）。"""
        return dict(self._specs)

    def clear_cache(self) -> None:
        """清空已解析类缓存（配置变更后强制下次重新 import）。"""
        self._cache.clear()
        self._lazy_failed.clear()


# 全局默认注册表：预登记 15 个云端 provider（仅 spec，import 延后）
default_registry = ProviderRegistry()
default_registry.bulk_register(_PROVIDER_CLASS_NAMES, _PROVIDER_MODULE)

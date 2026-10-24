"""
云端 API 提供者包
==================
从 cloud_api.py 拆分出来的独立提供者实现。

结构:
  base.py       — APIConfig, BaseCloudProvider (抽象基类)
  providers.py  — 15 个云厂商的具体实现

向后兼容: 所有类仍可通过 from .cloud_api import * 访问。
"""

from .base import APIConfig, BaseCloudProvider
from .providers import (
    DeepSeekProvider,
    DoubaoProvider,
    OpenAIProvider,
    ZhipuProvider,
    QwenProvider,
    WenxinProvider,
    SparkProvider,
    KimiProvider,
    BaichuanProvider,
    MiniMaxProvider,
    ClaudeProvider,
    GroqProvider,
    SiliconFlowProvider,
    StepfunProvider,
    YiProvider,
)

__all__ = [
    "APIConfig",
    "BaseCloudProvider",
    "DeepSeekProvider",
    "DoubaoProvider",
    "OpenAIProvider",
    "ZhipuProvider",
    "QwenProvider",
    "WenxinProvider",
    "SparkProvider",
    "KimiProvider",
    "BaichuanProvider",
    "MiniMaxProvider",
    "ClaudeProvider",
    "GroqProvider",
    "SiliconFlowProvider",
    "StepfunProvider",
    "YiProvider",
]

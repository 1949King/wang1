"""
云端 API 基类
=============
包含 APIConfig 数据类和 BaseCloudProvider 抽象基类。
"""

from collections.abc import Generator
from dataclasses import dataclass
from abc import ABC, abstractmethod


@dataclass
class APIConfig:
    """API 配置"""
    provider: str = "deepseek"
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    max_tokens: int = 4096
    temperature: float = 0.7
    top_p: float = 0.9


class BaseCloudProvider(ABC):
    """云端 API 基类"""

    def __init__(self, api_key: str, base_url: str = ""):
        self.api_key: str = api_key
        self.base_url: str = base_url or self.default_base_url
        # 最近一次调用的真实 token 用量（由子类在非流式/流式解析到 usage 时写入）。
        # AIEngine 优先消费此值做计量，拿不到（空/0）时降级估算。
        self.last_usage: dict[str, int] = {}

    @staticmethod
    def _extract_usage(data: dict) -> dict[str, int]:
        """从 OpenAI 兼容响应提取真实 token 用量；无 usage 时返回 0（触发降级估算）。"""
        u = data.get("usage") or {}
        return {
            "prompt_tokens": int(u.get("prompt_tokens") or 0),
            "completion_tokens": int(u.get("completion_tokens") or 0),
        }

    @property
    @abstractmethod
    def default_base_url(self) -> str:
        pass

    @property
    @abstractmethod
    def default_model(self) -> str:
        pass

    @abstractmethod
    def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        stream: bool = False,
        **kwargs: object,
    ) -> Generator[str, None, None]:
        pass

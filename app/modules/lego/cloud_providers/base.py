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

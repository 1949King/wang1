"""
云端 API 模块 (CloudAPI)
========================
云端大模型 API 服务管理（单例模式）。

支持提供商: DeepSeek / 豆包 / OpenAI / 智谱 AI / 通义千问 / 文心一言 /
             讯飞星火 / Kimi / 百川 / MiniMax / Claude / Groq /
             SiliconFlow / 阶跃星辰 / 零一万物 / Ollama

提供者实现: cloud_providers/providers.py
基类定义:   cloud_providers/base.py
"""

import json
import os
import threading
import logging
from typing import Any, cast

from .cloud_providers.base import APIConfig, BaseCloudProvider
from .cloud_providers.registry import default_registry

logger = logging.getLogger(__name__)


class CloudAPIService:
    """云端 API 服务（单例）"""

    _instance: "CloudAPIService | None" = None
    _lock: threading.Lock = threading.Lock()

    _OLLAMA_SENTINEL: str = "local"

    def __init__(self):
        if self._initialized:
            return
        self._initialized: bool = True
        # 懒加载注册表：provider 类推迟到首次使用时才 import（见 cloud_providers/registry.py）
        self._registry = default_registry
        self._configs: dict[str, APIConfig] = {}
        self._providers: dict[str, BaseCloudProvider] = {}
        self._load_configs()

        self._ollama_client: Any | None = None
        try:
            from .ollama_client import ollama_client
            self._ollama_client = ollama_client
        except ImportError:
            logger.warning("Ollama 客户端未找到")

    @property
    def PROVIDERS(self) -> dict[str, object]:
        """向后兼容：返回 name -> 已解析类 的字典（首次访问才 import 各 provider）。

        新代码请直接用 self._registry（names()/resolve()），避免触发 import。
        """
        return {name: self._registry.resolve(name) for name in self._registry.names()}

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
        self._initialized: bool = True
        self._configs: dict[str, APIConfig] = {}
        self._providers: dict[str, BaseCloudProvider] = {}
        self._load_configs()

        self._ollama_client: Any | None = None
        try:
            from .ollama_client import ollama_client
            self._ollama_client = ollama_client
        except ImportError:
            logger.warning("Ollama 客户端未找到")

    def _get_secure_storage(self):
        try:
            from app.core.config_manager import SecureStorage
            return SecureStorage()
        except ImportError:
            return None

    def _load_configs(self):
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "data", "api_configs.json"
        )
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                secure = self._get_secure_storage()
                for provider, config_data in data.items():
                    api_key = config_data.get("api_key", "")
                    if api_key == "encrypted" and secure:
                        api_key = secure.get(f"api_key:{provider}", "")
                    self._configs[provider] = APIConfig(
                        provider=provider,
                        api_key=api_key,
                        base_url=config_data.get("base_url", ""),
                        model=config_data.get("model", ""),
                        max_tokens=config_data.get("max_tokens", 4096),
                        temperature=config_data.get("temperature", 0.7),
                        top_p=config_data.get("top_p", 0.9),
                    )
            except Exception as e:
                logger.warning(f"加载 API 配置失败: {e}")

    def save_configs(self):
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "data", "api_configs.json"
        )
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        secure = self._get_secure_storage()
        data = {}
        for provider, config in self._configs.items():
            if secure and config.api_key:
                secure.set(f"api_key:{provider}", config.api_key)
                api_key_marker = "encrypted"
            else:
                api_key_marker = config.api_key
            data[provider] = {
                "api_key": api_key_marker,
                "base_url": config.base_url,
                "model": config.model,
                "max_tokens": config.max_tokens,
                "temperature": config.temperature,
                "top_p": config.top_p,
            }
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def set_config(self, provider: str, api_key: str, base_url: str = "", model: str = "",
                   max_tokens: int = 4096, temperature: float = 0.7, top_p: float = 0.9):
        self._configs[provider] = APIConfig(
            provider=provider, api_key=api_key, base_url=base_url, model=model,
            max_tokens=max_tokens, temperature=temperature, top_p=top_p,
        )
        if provider in self._providers:
            del self._providers[provider]
        self.save_configs()

    def get_config(self, provider: str) -> APIConfig | None:
        return self._configs.get(provider)

    def get_provider(self, provider: str) -> BaseCloudProvider | None:
        if provider not in self._registry.names():
            return None
        if provider in self._providers:
            return self._providers[provider]
        config = self._configs.get(provider)
        if not config or not config.api_key:
            return None
        provider_cls = cast(type[BaseCloudProvider], self._registry.resolve(provider))
        self._providers[provider] = provider_cls(
            api_key=config.api_key, base_url=config.base_url
        )
        return self._providers[provider]

    def chat(self, provider: str, messages: list[dict[str, str]], model: str | None = None,
             stream: bool = False, **kwargs: object):
        # Ollama 本地模型
        if provider == "ollama":
            if not self._ollama_client:
                yield "错误: Ollama 客户端未初始化"
                return
            if not self._ollama_client.is_available():
                yield "错误: Ollama 服务不可用，请确保 Ollama 已安装并运行"
                return
            if not model:
                models = self._ollama_client.list_models()
                if not models:
                    yield "错误: 未检测到 Ollama 模型，请先下载模型"
                    return
                model = models[0].name
            yield from self._ollama_client.chat(model, messages, stream, **kwargs)
            return

        # 云端 API
        provider_instance = self.get_provider(provider)
        if not provider_instance:
            yield f"错误: {provider} API 未配置"
            return
        config = self._configs.get(provider)
        model = model or (config.model if config else None)
        yield from provider_instance.chat(messages, model, stream, **kwargs)

    def is_configured(self, provider: str) -> bool:
        if provider == "ollama":
            return self._ollama_client is not None and self._ollama_client.is_available()
        config = self._configs.get(provider)
        return config is not None and bool(config.api_key)

    def list_providers(self) -> list[str]:
        return self._registry.names()


cloud_api_service = CloudAPIService()


PROVIDER_INFO = {
    "deepseek": {
        "name": "DeepSeek",
        "description": "高性价比，适合文案生成",
        "models": ["deepseek-chat", "deepseek-coder", "deepseek-reasoner"],
        "pricing": "约 ¥1/百万 tokens",
        "website": "https://platform.deepseek.com"
    },
    "doubao": {
        "name": "豆包",
        "description": "字节跳动，中文优化",
        "models": ["doubao-pro-4k", "doubao-pro-32k", "doubao-pro-128k"],
        "pricing": "约 ¥0.8/百万 tokens",
        "website": "https://www.volcengine.com/product/doubao"
    },
    "openai": {
        "name": "OpenAI",
        "description": "能力最强，高级功能",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "o1", "o1-mini"],
        "pricing": "约 $5/百万 tokens",
        "website": "https://platform.openai.com"
    },
    "zhipu": {
        "name": "智谱 AI",
        "description": "国产优秀，多模态支持",
        "models": ["glm-4", "glm-4-flash", "glm-4v", "glm-4-plus"],
        "pricing": "约 ¥1/百万 tokens",
        "website": "https://open.bigmodel.cn"
    },
    "qwen": {
        "name": "通义千问",
        "description": "阿里云，企业级稳定",
        "models": ["qwen-turbo", "qwen-plus", "qwen-max", "qwen-max-longcontext", "qwen-vl-max"],
        "pricing": "约 ¥0.8/百万 tokens",
        "website": "https://dashscope.aliyun.com"
    },
    "wenxin": {
        "name": "文心一言",
        "description": "百度出品，中文理解强",
        "models": ["ernie-4.0-8k", "ernie-4.0-turbo-8k", "ernie-3.5-8k"],
        "pricing": "约 ¥1.2/百万 tokens",
        "website": "https://cloud.baidu.com/product/wenxinworkshop"
    },
    "spark": {
        "name": "讯飞星火",
        "description": "科大讯飞，语音交互强",
        "models": ["generalv3.5", "generalv3", "generalv2"],
        "pricing": "约 ¥1.5/百万 tokens",
        "website": "https://xinghuo.xfyun.cn"
    },
    "kimi": {
        "name": "Kimi",
        "description": "月之暗面，超长上下文",
        "models": ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
        "pricing": "约 ¥1/百万 tokens",
        "website": "https://platform.moonshot.cn"
    },
    "baichuan": {
        "name": "百川",
        "description": "百川智能，开源领先",
        "models": ["Baichuan4", "Baichuan3-Turbo", "Baichuan2-Turbo"],
        "pricing": "约 ¥0.8/百万 tokens",
        "website": "https://platform.baichuan-ai.com"
    },
    "minimax": {
        "name": "MiniMax",
        "description": "MiniMax，多模态创新",
        "models": ["abab6.5s-chat", "abab6.5-chat", "abab5.5-chat"],
        "pricing": "约 ¥1/百万 tokens",
        "website": "https://www.minimaxi.com"
    },
    "claude": {
        "name": "Claude",
        "description": "Anthropic，安全可靠",
        "models": ["claude-3-5-sonnet-20241022", "claude-3-opus-20240229", "claude-3-haiku-20240307"],
        "pricing": "约 $3/百万 tokens",
        "website": "https://console.anthropic.com"
    },
    "groq": {
        "name": "Groq",
        "description": "极速推理，延迟最低",
        "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"],
        "pricing": "免费额度充足",
        "website": "https://console.groq.com"
    },
    "siliconflow": {
        "name": "硅基流动",
        "description": "国内聚合平台，模型丰富",
        "models": ["Qwen/Qwen2.5-72B-Instruct", "deepseek-ai/DeepSeek-V3", "meta-llama/Llama-3.3-70B-Instruct"],
        "pricing": "按模型计费",
        "website": "https://cloud.siliconflow.cn"
    },
    "stepfun": {
        "name": "阶跃星辰",
        "description": "Step，多模态能力",
        "models": ["step-1-8k", "step-1-32k", "step-1-128k", "step-1v-8k"],
        "pricing": "约 ¥1/百万 tokens",
        "website": "https://platform.stepfun.com"
    },
    "yi": {
        "name": "零一万物",
        "description": "李开复博士创办",
        "models": ["yi-lightning", "yi-large", "yi-medium", "yi-spark"],
        "pricing": "约 ¥0.6/百万 tokens",
        "website": "https://platform.lingyiwanwu.com"
    }
}

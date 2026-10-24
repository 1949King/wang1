"""
云端 API 模块 (CloudAPI)
========================
云端大模型 API 服务管理（单例模式）。

支持提供商: DeepSeek / 豆包 / OpenAI / 智谱 AI / 通义千问 / 文心一言 /
             讯飞星火 / Kimi / 百川 / MiniMax / Claude / Groq /
             SiliconFlow / 阶跃星辰 / 零一万物 / ModelScope / ChatGPT2API / Ollama

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

    def __new__(cls):
        """单例模式实现"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """初始化（仅首次调用时执行）"""
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

    def _get_secure_storage(self):
        """安全存储句柄；None = 本机加密存储当前不可用。

        构造失败也要如实降级（旧版只接 ImportError，SecureStorage() 抛 OSError/
        ValueError 时会把整个保存动作炸成未捕获异常）。返回 None 后由
        save_configs 决定「拒绝保存并报错」，绝不静默改写明文。
        """
        try:
            from app.core.config_manager import SecureStorage
            return SecureStorage()
        except ImportError as e:
            logger.error("config_manager 不可导入，密钥加密存储不可用: %s", e)
            return None
        except Exception as e:
            logger.error("SecureStorage 初始化失败，密钥加密存储不可用: %s", e)
            return None

    def _config_path(self) -> str:
        """api_configs.json 路径（抽成方法便于单测重定向，行为不变）。"""
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "data", "api_configs.json"
        )

    def _load_configs(self):
        config_path = self._config_path()
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                secure = self._get_secure_storage()
                for provider, config_data in data.items():
                    api_key = config_data.get("api_key", "")
                    if api_key == "encrypted":
                        # 标记不是密钥。旧写法 `== "encrypted" and secure` 在
                        # secure 不可用时会把字面量 "encrypted" 当成 API Key 用
                        # ——渠道显示"已配置"、请求期才炸，且 get_provider 的
                        # `if not config.api_key` 空值判据会被它绕过。
                        api_key = secure.get(f"api_key:{provider}", "") if secure else ""
                        if not api_key:
                            logger.warning(
                                "渠道 %s 的密钥无法读回（加密存储不可用或密钥库缺该键），"
                                "本次按未配置处理", provider)
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

    def _existing_markers(self, config_path: str) -> dict:
        """读回磁盘上现存的 api_key 标记（provider -> marker），读不到给 {}。"""
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {p: str(v.get("api_key", "")) for p, v in data.items()
                    if isinstance(v, dict)}
        except Exception:
            return {}

    def save_configs(self):
        """落盘配置。没能持久化的密钥**绝不留下「已保存」假象** ——

        两条失败路径都大声失败（RuntimeError，调用方弹错误框）：
          ① 加密存储整体不可用（config_manager 导入失败 / SecureStorage 构造抛错）；
          ② 存储可用，但某渠道 set() 落盘失败（磁盘满/权限/被安全软件拦截）。

        旧行为（2026-10-21 丢 Key 事故根因）：不管有没有真写进磁盘都先标 "encrypted"，
        UI 无条件弹「✅ 已保存」⇒ 下次启动读回空 ⇒ 密钥凭空消失。
        ②分支修好后仍留着 ①：`secure` 为 None 时**静默把明文 Key 写进
        api_configs.json**（审计 2026-10-23 定 CWE-312：明文随备份盘/同步盘外泄），
        且同样是"失败伪装成成功"。现在 ① 一律拒绝降级。

        两条路径对**磁盘标记**的处置不同，是有意的：
          · ②写失败 → 标 ""：存储文件本次没写成功，内容已不可信，如实显示未配置；
          · ①不可用 → 保留原标记：本次根本没碰存储，它就是上次成功保存的样子，
            覆盖成 "" 反而会把上次已存好的密钥挡在门外。
        两种情况下内存里的配置都仍在用，所以当前会话不受影响，只是重启需重填。
        """
        config_path = self._config_path()
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        secure = self._get_secure_storage()
        data = {}
        failed: list[str] = []
        unavailable = secure is None and any(c.api_key for c in self._configs.values())
        existing = self._existing_markers(config_path) if unavailable else {}
        for provider, config in self._configs.items():
            if unavailable and config.api_key:
                # 路径①：加密存储不可用 ⇒ 不写明文、不标 encrypted、保留原标记
                failed.append(provider)
                api_key_marker = existing.get(provider, "")
            elif secure and config.api_key:
                if secure.set(f"api_key:{provider}", config.api_key):
                    api_key_marker = "encrypted"
                else:
                    # 路径②：安全存储写盘失败，绝不标 encrypted（标了下次读成空=丢密钥）
                    failed.append(provider)
                    api_key_marker = ""
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
        if failed:
            # 先落盘「真实持久化成什么就标什么」的清单（成功的渠道保留 encrypted 标记、
            # 失败渠道如实标记 ⇒ 重启后显示未配置，不会读成假可用），再抛错。
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            names = "、".join(failed)
            if unavailable:
                # 路径①：连加密存储都起不来 ⇒ 绝不退化成明文落盘
                raise RuntimeError(
                    "密钥加密存储当前不可用，已拒绝保存这些渠道的密钥：" + names
                    + "。为避免明文密钥落盘（会随备份/同步盘外泄），本次未写入密钥；"
                    "其余非密钥设置已保存，当前会话仍可继续使用，但重启需重新填写。"
                    "常见原因：程序未从安装目录启动（找不到 config_manager）、"
                    "或缺少 cryptography 依赖 —— 请从桌面快捷方式启动程序后再保存。"
                )
            raise RuntimeError(
                "密钥安全存储写入失败（" + names + "）："
                "这些渠道本次未持久化，当前会话仍可用，但重启会丢失。"
                "请检查磁盘权限/空间（被安全软件拦截时，从桌面快捷方式重启程序再保存）。"
            )
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
    "chatgpt2api": {
        "name": "ChatGPT2API",
        "description": "自托管 ChatGPT 官网能力网关，OpenAI 兼容，支持 gpt-image-2 生图",
        "models": ["gpt-image-2", "codex-gpt-image-2", "auto", "gpt-5", "gpt-5-mini"],
        "pricing": "依赖自建号池 / 订阅额度",
        "website": "https://github.com/basketikun/chatgpt2api"
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

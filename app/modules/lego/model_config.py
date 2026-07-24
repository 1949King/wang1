"""
模型管理共享配置
================
从 model_management.py 拆分出来的共享数据/常量，供所有子模块引用。
"""

import os
from dataclasses import dataclass
from typing import Any


@dataclass
class ModelConfig:
    """模型配置"""
    provider: str = ""
    model_name: str = ""
    api_key: str = ""
    base_url: str = ""
    max_tokens: int = 4096
    temperature: float = 0.7
    enabled: bool = True


PROVIDERS: dict[str, dict[str, Any]] = {
    "ollama": {"name": "Ollama 本地", "icon": "🦙", "url": "http://localhost:11434", "models": [], "is_local": True},
    "deepseek": {"name": "DeepSeek", "icon": "", "url": "https://api.deepseek.com/v1", "models": ["deepseek-chat", "deepseek-coder", "deepseek-reasoner"], "is_local": False},
    "doubao": {"name": "豆包", "icon": "🫘", "url": "https://ark.cn-beijing.volces.com/api/v3", "models": ["doubao-pro-4k", "doubao-pro-32k", "doubao-pro-128k"], "is_local": False},
    "openai": {"name": "OpenAI", "icon": "🧠", "url": "https://api.openai.com/v1", "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "o1", "o1-mini"], "is_local": False},
    "zhipu": {"name": "智谱 AI", "icon": "", "url": "https://open.bigmodel.cn/api/paas/v4", "models": ["glm-4", "glm-4-flash", "glm-4v", "glm-4-plus"], "is_local": False},
    "qwen": {"name": "通义千问", "icon": "☁️", "url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "models": ["qwen-turbo", "qwen-plus", "qwen-max", "qwen-max-longcontext"], "is_local": False},
    "wenxin": {"name": "文心一言", "icon": "📝", "url": "https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat", "models": ["ernie-4.0-8k", "ernie-4.0-turbo-8k", "ernie-3.5-8k"], "is_local": False},
    "spark": {"name": "讯飞星火", "icon": "✨", "url": "https://spark-api-open.xf-yun.com/v1", "models": ["generalv3.5", "generalv3", "generalv2"], "is_local": False},
    "kimi": {"name": "Kimi", "icon": "🌙", "url": "https://api.moonshot.cn/v1", "models": ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"], "is_local": False},
    "baichuan": {"name": "百川", "icon": "🌊", "url": "https://api.baichuan-ai.com/v1", "models": ["Baichuan4", "Baichuan3-Turbo", "Baichuan2-Turbo"], "is_local": False},
    "minimax": {"name": "MiniMax", "icon": "🎯", "url": "https://api.minimax.chat/v1", "models": ["abab6.5s-chat", "abab6.5-chat", "abab5.5-chat"], "is_local": False},
    "claude": {"name": "Claude", "icon": "🎨", "url": "https://api.anthropic.com/v1", "models": ["claude-3-5-sonnet-20241022", "claude-3-opus-20240229", "claude-3-haiku-20240307"], "is_local": False},
    "groq": {"name": "Groq", "icon": "⚡", "url": "https://api.groq.com/openai/v1", "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"], "is_local": False},
    "siliconflow": {"name": "硅基流动", "icon": "🔬", "url": "https://api.siliconflow.cn/v1", "models": ["Qwen/Qwen2.5-72B-Instruct", "deepseek-ai/DeepSeek-V3"], "is_local": False},
    "stepfun": {"name": "阶跃星辰", "icon": "⭐", "url": "https://api.stepfun.com/v1", "models": ["step-1-8k", "step-1-32k", "step-1-128k"], "is_local": False},
    "yi": {"name": "零一万物", "icon": "🔮", "url": "https://api.lingyiwanwu.com/v1", "models": ["yi-lightning", "yi-large", "yi-medium"], "is_local": False},
    "modelscope": {"name": "魔搭社区", "icon": "🏛️", "url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "models": ["qwen-turbo", "qwen-plus", "qwen-max"], "is_local": False},
}

CUSTOM_PROVIDERS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "custom_providers.json")
ACTIVE_PROVIDER_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "active_provider.json")

CARD_COLLAPSED = "collapsed"
CARD_EXPANDED = "expanded"

"""
模型管理共享配置
================
从 model_management.py 拆分出来的共享数据/常量，供所有子模块引用。
"""

import json
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
    "siliconflow": {
        "name": "硅基流动",
        "icon": "🔬",
        "url": "https://api.siliconflow.cn/v1",
        "models": [
            "Qwen/Qwen2.5-72B-Instruct",
            "deepseek-ai/DeepSeek-V3",
            "black-forest-labs/FLUX.1-schnell",
            "black-forest-labs/FLUX.1-dev",
            "black-forest-labs/FLUX.1-Kontext-pro",
            "Wan-AI/Wan2.1-T2V-14B",
            "Wan-AI/Wan2.1-I2V-14B-720P",
        ],
        "is_local": False,
    },
    "chatgpt2api": {
        "name": "ChatGPT2API",
        "icon": "🖼️",
        "url": "http://127.0.0.1:8000/v1",
        "models": [
            "gpt-image-2",
            "codex-gpt-image-2",
            "auto",
            "gpt-5",
            "gpt-5-mini",
            "gpt-5-3",
            "gpt-5-3-mini",
        ],
        "is_local": True,
        "hint": "自托管 OpenAI 兼容网关（默认本机 :8000）。填 Auth Key + Base URL，优先用于 gpt-image-2 生图。",
    },
    "stepfun": {"name": "阶跃星辰", "icon": "⭐", "url": "https://api.stepfun.com/v1", "models": ["step-1-8k", "step-1-32k", "step-1-128k", "step-1v-8k"], "is_local": False},
    "yi": {"name": "零一万物", "icon": "🔮", "url": "https://api.lingyiwanwu.com/v1", "models": ["yi-lightning", "yi-large", "yi-medium"], "is_local": False},
    "modelscope": {"name": "魔搭社区", "icon": "🏛️", "url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "models": ["qwen-turbo", "qwen-plus", "qwen-max"], "is_local": False},
    "kling": {"name": "可灵 AI", "icon": "🎬", "url": "https://api.klingai.com/v1", "models": ["kling-v1.5", "kling-v1.6", "kling-v1.6-i2v"], "is_local": False},
    "fishaudio": {"name": "Fish Audio", "icon": "🐟", "url": "https://api.fish.audio/v1", "models": ["fish-speech-v1.5", "fish-speech-v1.5-turbo", "fish-speech-v1.5-hd"], "is_local": False, "hint": "开源语音合成，自托管可填自定义 Base URL（如 http://127.0.0.1:8080/v1）"},
    "stability": {"name": "Stability AI", "icon": "🖌️", "url": "https://api.stability.ai/v2beta", "models": ["sd3-large", "sd3-medium", "sd3-large-turbo", "sdxl-base-1.0", "sdxl-turbo"], "is_local": False},
}

# ---------------------------------------------------------------------------
# 模型可读名映射：供下拉框/卡片展示，key 为 provider 名或 "*"（通配）
# 映射值为 str（直接用） 或 callable(model_id) -> str
# ---------------------------------------------------------------------------
MODEL_DISPLAY_NAMES: dict[str, dict[str, str]] = {
    "ollama": {},
    "deepseek": {
        "deepseek-chat": "DeepSeek Chat V3（对话旗舰）",
        "deepseek-coder": "DeepSeek Coder（代码专用）",
        "deepseek-reasoner": "DeepSeek Reasoner（思考推理）",
    },
    "doubao": {
        "doubao-pro-4k": "豆包 Pro 4K",
        "doubao-pro-32k": "豆包 Pro 32K（长上下文）",
        "doubao-pro-128k": "豆包 Pro 128K（超长上下文）",
    },
    "openai": {
        "gpt-4o": "GPT-4o（多模态旗舰）",
        "gpt-4o-mini": "GPT-4o Mini（轻量多模态）",
        "gpt-4-turbo": "GPT-4 Turbo",
        "o1": "o1（强推理）",
        "o1-mini": "o1-mini（轻量推理）",
    },
    "zhipu": {
        "glm-4": "GLM-4（旗舰）",
        "glm-4-flash": "GLM-4 Flash（高速）",
        "glm-4v": "GLM-4V（多模态）",
        "glm-4-plus": "GLM-4 Plus（增强）",
    },
    "qwen": {
        "qwen-turbo": "通义 Turbo（高速）",
        "qwen-plus": "通义 Plus（均衡）",
        "qwen-max": "通义 Max（旗舰）",
        "qwen-max-longcontext": "通义 Max 长上下文",
    },
    "wenxin": {
        "ernie-4.0-8k": "文心一言 4.0 8K",
        "ernie-4.0-turbo-8k": "文心一言 4.0 Turbo",
        "ernie-3.5-8k": "文心一言 3.5",
    },
    "spark": {
        "generalv3.5": "星火 V3.5",
        "generalv3": "星火 V3.0",
        "generalv2": "星火 V2.0",
    },
    "kimi": {
        "moonshot-v1-8k": "Kimi 8K",
        "moonshot-v1-32k": "Kimi 32K（长上下文）",
        "moonshot-v1-128k": "Kimi 128K（超长上下文）",
    },
    "baichuan": {
        "Baichuan4": "百川 4",
        "Baichuan3-Turbo": "百川 3 Turbo",
        "Baichuan2-Turbo": "百川 2 Turbo",
    },
    "minimax": {
        "abab6.5s-chat": "MiniMax 6.5S（极速）",
        "abab6.5-chat": "MiniMax 6.5（均衡）",
        "abab5.5-chat": "MiniMax 5.5",
    },
    "claude": {
        "claude-3-5-sonnet-20241022": "Claude 3.5 Sonnet（推荐）",
        "claude-3-opus-20240229": "Claude 3 Opus（旗舰）",
        "claude-3-haiku-20240307": "Claude 3 Haiku（轻量）",
    },
    "groq": {
        "llama-3.3-70b-versatile": "Llama 3.3 70B（高速推理）",
        "llama-3.1-8b-instant": "Llama 3.1 8B（极速）",
        "mixtral-8x7b-32768": "Mixtral 8x7B 32K",
    },
    "siliconflow": {},
    "chatgpt2api": {
        "auto": "自动（自适应）",
        "gpt-image-2": "GPT Image 2（生图）",
        "codex-gpt-image-2": "Codex GPT Image 2（代码+生图）",
        "gpt-5": "GPT-5（旗舰）",
        "gpt-5-1": "GPT-5.1",
        "gpt-5-2": "GPT-5.2（新旗舰）",
        "gpt-5-mini": "GPT-5 Mini（轻量）",
        "gpt-5-3": "GPT-5.3（新旗舰）",
        "gpt-5-3-mini": "GPT-5.3 Mini（新轻量）",
    },
    "stepfun": {
        "step-1-8k": "阶跃 1 8K",
        "step-1-32k": "阶跃 1 32K",
        "step-1-128k": "阶跃 1 128K",
        "step-1v-8k": "阶跃 1V 8K（多模态）",
    },
    "yi": {
        "yi-lightning": "零一 Lightning（极速）",
        "yi-large": "零一 Large（旗舰）",
        "yi-medium": "零一 Medium（均衡）",
    },
    "modelscope": {
        "qwen-turbo": "通义 Turbo（魔搭）",
        "qwen-plus": "通义 Plus（魔搭）",
        "qwen-max": "通义 Max（魔搭）",
    },
    "kling": {
        "kling-v1.5": "可灵 1.5",
        "kling-v1.6": "可灵 1.6",
        "kling-v1.6-i2v": "可灵 1.6 图生视频",
    },
    "fishaudio": {
        "fish-speech-v1.5": "Fish Speech 1.5",
        "fish-speech-v1.5-turbo": "Fish Speech 1.5 Turbo",
        "fish-speech-v1.5-hd": "Fish Speech 1.5 HD（高清）",
    },
    "stability": {
        "sd3-large": "SD3 Large",
        "sd3-medium": "SD3 Medium",
        "sd3-large-turbo": "SD3 Large Turbo",
        "sdxl-base-1.0": "SDXL Base 1.0",
        "sdxl-turbo": "SDXL Turbo",
    },
}


PROVIDER_ALIAS: dict[str, str] = {
    "chatgpt2api": "chatgpt2api",
    "chatgpt2_api": "chatgpt2api",
    "chatgpt": "chatgpt2api",
    "ollama": "ollama",
    "deepseek": "deepseek",
    "doubao": "doubao",
    "openai": "openai",
    "zhipu": "zhipu",
    "qwen": "qwen",
    "siliconflow": "siliconflow",
    "moonshot": "moonshot",
    "gemini": "gemini",
    "claude": "claude",
    "anthropic": "claude",
    "kimi": "moonshot",
    "glm": "zhipu",
}

MODEL_DISPLAY_NAMES["chatgpt2api"] = {
    "gpt-4o": "GPT-4o（多模态旗舰）",
    "gpt-4o-mini": "GPT-4o Mini（轻量）",
    "gpt-4-turbo": "GPT-4 Turbo",
    "gpt-5": "GPT-5（旗舰）",
    "gpt-5-1": "GPT-5.1",
    "gpt-5-2": "GPT-5.2（新旗舰）",
    "gpt-5-3": "GPT-5.3（新旗舰）",
    "gpt-5-mini": "GPT-5 Mini（轻量）",
    "gpt-5-3-mini": "GPT-5.3 Mini（新轻量）",
    "gpt-image-2": "GPT Image 2（生图）",
    "codex-gpt-image-2": "Codex GPT Image 2（代码+生图）",
    "auto": "自动（自适应）",
}

MODEL_DISPLAY_NAMES["ollama"] = {
    "qwen2.5:7b": "qwen2.5:7b（通义轻量）",
    "qwen2.5:14b": "qwen2.5:14b（通义均衡）",
    "qwen2.5:32b": "qwen2.5:32b（通义旗舰）",
    "llama3:8b": "llama3:8b",
    "llama3.1:8b": "llama3.1:8b",
    "llama3.2:1b": "llama3.2:1b（超轻量）",
    "deepseek-r1:7b": "DeepSeek R1:7b（推理）",
    "deepseek-r1:14b": "DeepSeek R1:14b（推理）",
}

MODEL_DISPLAY_NAMES["siliconflow"] = {
    "black-forest-labs/FLUX.1-schnell": "FLUX.1 Schnell（高速生图）",
    "black-forest-labs/FLUX.1-dev": "FLUX.1 Dev（精细生图）",
    "stabilityai/stable-diffusion-3-5-large": "SD3.5 Large（生图）",
    "stabilityai/stable-diffusion-3-medium": "SD3 Medium",
}


def model_display_name(provider: str, model_id: str) -> str:
    """给定 provider 和 model_id，返回人类可读的显示名；无映射则原样返回。"""
    if not model_id:
        return "自动"
    key = PROVIDER_ALIAS.get((provider or "").strip().lower(), (provider or "").strip().lower())
    table = MODEL_DISPLAY_NAMES.get(key) or {}
    if model_id in table:
        return table[model_id]
    return model_id


# 画布 / AIGC 专用：按 provider 追加生图·生视频·多模态模型（capability 供自研画布）
# 名称尽量对齐各平台 OpenAI-compatible 路由；实际可用性取决于账号开通。
AIGC_MODELS: dict[str, list[dict[str, str]]] = {
    "chatgpt2api": [
        {"name": "gpt-image-2", "capability": "image"},
        {"name": "codex-gpt-image-2", "capability": "image"},
        {"name": "auto", "capability": "image"},
        {"name": "gpt-5", "capability": "text"},
        {"name": "gpt-5-1", "capability": "text"},
        {"name": "gpt-5-2", "capability": "text"},
        {"name": "gpt-5-3", "capability": "text"},
        {"name": "gpt-5-3-mini", "capability": "text"},
        {"name": "gpt-5-mini", "capability": "text"},
    ],
    "siliconflow": [
        {"name": "Qwen/Qwen-Image", "capability": "image"},
        {"name": "Kwai-Kolors/Kolors", "capability": "image"},
        {"name": "black-forest-labs/FLUX.1-schnell", "capability": "image"},
        {"name": "black-forest-labs/FLUX.1-dev", "capability": "image"},
        {"name": "black-forest-labs/FLUX.1-Kontext-pro", "capability": "image"},
        {"name": "black-forest-labs/FLUX.1-Kontext-dev", "capability": "image"},
        {"name": "black-forest-labs/FLUX.1-Kontext-max", "capability": "image"},
        {"name": "stabilityai/stable-diffusion-3-5-large", "capability": "image"},
        {"name": "stabilityai/stable-diffusion-3-medium", "capability": "image"},
        {"name": "stabilityai/stable-diffusion-xl-base-1.0", "capability": "image"},
        {"name": "stabilityai/stable-diffusion-xl-refiner-1.0", "capability": "image"},
        {"name": "stabilityai/stable-diffusion-xl-turbo", "capability": "image"},
        {"name": "Wan-AI/Wan2.1-T2V-14B", "capability": "video"},
        {"name": "Wan-AI/Wan2.1-I2V-14B-720P", "capability": "video"},
        {"name": "Wan-AI/Wan2.2-T2V-A14B", "capability": "video"},
        {"name": "Wan-AI/Wan2.1-Fun-V1.1-14B", "capability": "video"},
        {"name": "Qwen/Qwen2.5-72B-Instruct", "capability": "text"},
        {"name": "deepseek-ai/DeepSeek-V3", "capability": "text"},
    ],
    "openai": [
        {"name": "gpt-image-2", "capability": "image"},
        {"name": "gpt-image-1", "capability": "image"},
        {"name": "gpt-image-1-mini", "capability": "image"},
        {"name": "dall-e-3", "capability": "image"},
        {"name": "dall-e-3-hd", "capability": "image"},
        {"name": "dall-e-2", "capability": "image"},
        {"name": "sora-2", "capability": "video"},
        {"name": "sora-2-turbo", "capability": "video"},
        {"name": "sora", "capability": "video"},
        {"name": "gpt-4o", "capability": "text"},
        {"name": "gpt-4o-mini", "capability": "text"},
        {"name": "gpt-4o-mini-tts", "capability": "audio"},
        {"name": "tts-1", "capability": "audio"},
        {"name": "tts-1-hd", "capability": "audio"},
    ],
    "qwen": [
        {"name": "wanx-v1", "capability": "image"},
        {"name": "wanx2.1-t2i-turbo", "capability": "image"},
        {"name": "wanx2.1-t2i-plus", "capability": "image"},
        {"name": "wanx2.1-t2i-high", "capability": "image"},
        {"name": "wanx2.1-t2v-plus", "capability": "video"},
        {"name": "wanx2.1-i2v-plus", "capability": "video"},
        {"name": "qwen-image", "capability": "image"},
        {"name": "qwen-vl-max", "capability": "text"},
        {"name": "qwen-max", "capability": "text"},
        {"name": "qwen-plus", "capability": "text"},
        {"name": "qwen-tts", "capability": "audio"},
        {"name": "cosyvoice-v2", "capability": "audio"},
    ],
    "modelscope": [
        {"name": "wanx-v1", "capability": "image"},
        {"name": "wanx2.1-t2i-turbo", "capability": "image"},
        {"name": "wanx2.1-t2i-plus", "capability": "image"},
        {"name": "qwen-image", "capability": "image"},
        {"name": "qwen-max", "capability": "text"},
    ],
    "doubao": [
        {"name": "doubao-seedream-3-0-t2i", "capability": "image"},
        {"name": "doubao-seedream-4-0", "capability": "image"},
        {"name": "doubao-seedream-4-0-t2i", "capability": "image"},
        {"name": "doubao-seedance-1-0-pro", "capability": "video"},
        {"name": "doubao-seedance-1-0-lite", "capability": "video"},
        {"name": "doubao-seedance-2-0-pro", "capability": "video"},
        {"name": "doubao-pro-32k", "capability": "text"},
    ],
    "zhipu": [
        {"name": "cogview-4", "capability": "image"},
        {"name": "cogview-4-flash", "capability": "image"},
        {"name": "cogview-3-plus", "capability": "image"},
        {"name": "cogvideox-2", "capability": "video"},
        {"name": "cogvideox-3", "capability": "video"},
        {"name": "cogvideox-3-turbo", "capability": "video"},
        {"name": "glm-4v", "capability": "text"},
        {"name": "glm-4-flash", "capability": "text"},
    ],
    "minimax": [
        {"name": "image-01", "capability": "image"},
        {"name": "image-01-live", "capability": "image"},
        {"name": "video-01", "capability": "video"},
        {"name": "video-01-live2d", "capability": "video"},
        {"name": "video-02", "capability": "video"},
        {"name": "speech-01", "capability": "audio"},
        {"name": "speech-02-hd", "capability": "audio"},
        {"name": "abab6.5s-chat", "capability": "text"},
    ],
    "stepfun": [
        {"name": "step-1x-medium", "capability": "image"},
        {"name": "step-1v-8k", "capability": "text"},
        {"name": "step-1-32k", "capability": "text"},
    ],
    "deepseek": [
        {"name": "deepseek-chat", "capability": "text"},
        {"name": "deepseek-reasoner", "capability": "text"},
    ],
    "kimi": [
        {"name": "moonshot-v1-128k", "capability": "text"},
        {"name": "moonshot-v1-32k", "capability": "text"},
    ],
    "kling": [
        {"name": "kling-v1.5", "capability": "video"},
        {"name": "kling-v1.6", "capability": "video"},
        {"name": "kling-v1.6-i2v", "capability": "video"},
        {"name": "kling-v1.6-t2i", "capability": "image"},
    ],
    "fishaudio": [
        {"name": "fish-speech-v1.5", "capability": "audio"},
        {"name": "fish-speech-v1.5-turbo", "capability": "audio"},
        {"name": "fish-speech-v1.5-hd", "capability": "audio"},
    ],
    "stability": [
        {"name": "sd3-large", "capability": "image"},
        {"name": "sd3-medium", "capability": "image"},
        {"name": "sd3-large-turbo", "capability": "image"},
        {"name": "sdxl-base-1.0", "capability": "image"},
        {"name": "sdxl-refiner-1.0", "capability": "image"},
        {"name": "sdxl-turbo", "capability": "image"},
        {"name": "sdxl-lightning", "capability": "image"},
        {"name": "stable-image-ultra", "capability": "image"},
    ],
}

# 无云端 Key 时仍注入的「目录占位」渠道（apiKey 空，用户可在画布内补）
AIGC_CATALOG_PLACEHOLDER: dict[str, Any] = {
    "id": "shiguang-aigc-catalog",
    "name": "拾光·AIGC目录",
    "baseUrl": "https://api.siliconflow.cn/v1",
    "apiKey": "",
    "apiFormat": "openai",
    "models": list(AIGC_MODELS.get("siliconflow") or []),
}

# 同步到画布时优先用这些 provider 的 Key 作为默认 AIGC 渠道
AIGC_KEY_PRIORITY: tuple[str, ...] = (
    "chatgpt2api",
    "siliconflow",
    "openai",
    "qwen",
    "doubao",
    "zhipu",
    "kling",
    "stability",
    "minimax",
    "fishaudio",
    "modelscope",
    "stepfun",
)

CAP_LABEL = {
    "image": "生图",
    "video": "生视频",
    "audio": "语音",
    "text": "对话",
}


def aigc_entries_for(provider_id: str) -> list[dict[str, str]]:
    return list(AIGC_MODELS.get(provider_id) or [])


def merge_aigc_into_providers() -> None:
    """把 AIGC 模型名并入 PROVIDERS[*].models，并打上 aigc 标记供 UI 展示。"""
    for pid, entries in AIGC_MODELS.items():
        info = PROVIDERS.get(pid)
        if not isinstance(info, dict):
            continue
        existing = list(info.get("models") or [])
        seen = set(existing)
        for ent in entries:
            name = str(ent.get("name") or "")
            if name and name not in seen:
                existing.append(name)
                seen.add(name)
        info["models"] = existing
        info["aigc"] = list(entries)
        caps = {str(e.get("capability") or "") for e in entries}
        info["has_aigc"] = bool(caps & {"image", "video", "audio"})


def provider_model_choices(provider_id: str, provider_info: dict[str, Any] | None = None) -> list[tuple[str, str]]:
    """返回 (显示文案, 真实模型名) 列表，AIGC 带能力标签。"""
    info = provider_info or PROVIDERS.get(provider_id) or {}
    aigc_map = {
        str(e.get("name")): str(e.get("capability") or "text")
        for e in (info.get("aigc") or AIGC_MODELS.get(provider_id) or [])
        if e.get("name")
    }
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for name in list(info.get("models") or []):
        if not name or name in seen:
            continue
        seen.add(name)
        cap = aigc_map.get(name)
        if cap and cap != "text":
            out.append((f"[{CAP_LABEL.get(cap, cap)}] {name}", name))
        elif cap == "text" and name in aigc_map:
            out.append((f"[对话] {name}", name))
        else:
            out.append((name, name))
    # AIGC 里有但 models 未收录的
    for name, cap in aigc_map.items():
        if name in seen:
            continue
        seen.add(name)
        out.append((f"[{CAP_LABEL.get(cap, cap)}] {name}", name))
    return out


merge_aigc_into_providers()

CUSTOM_PROVIDERS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "custom_providers.json")
ACTIVE_PROVIDER_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "active_provider.json")

CARD_COLLAPSED = "collapsed"
CARD_EXPANDED = "expanded"


def load_active_provider() -> str:
    """读取当前激活的 Provider ID（空字符串表示未激活）。"""
    try:
        if os.path.isfile(ACTIVE_PROVIDER_FILE):
            with open(ACTIVE_PROVIDER_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return str(data.get("active_provider") or "")
    except Exception:
        pass
    return ""


def save_active_provider(provider_id: str) -> bool:
    """写入激活 Provider。"""
    try:
        os.makedirs(os.path.dirname(ACTIVE_PROVIDER_FILE), exist_ok=True)
        with open(ACTIVE_PROVIDER_FILE, "w", encoding="utf-8") as f:
            json.dump({"active_provider": provider_id or ""}, f, ensure_ascii=False)
        return True
    except Exception:
        return False


def ensure_active_provider_sensible() -> str:
    """若激活为 Ollama 但本地不可用、且已有云端 Key，则切到首个可用云端（优先 deepseek）。

    返回最终激活的 provider_id（可能未变）。

    【性能】热点路径惰性化（2026-09-12）
      原实现每次调用都无条件做两件重活：
        ① 探活本机 Ollama（HTTP GET /api/tags，超时 8s，实测约 2.1s）
        ② import cloud_api 并逐个 is_configured（实测约 0.4s）
      但这只影响「未选 provider」或「选的正是 ollama」两种情况；已选定具体云端时
      结果与探测无关。改为惰性求值 + 快路径直接返回，省下约 2.5s 的同步阻塞
      （画布冷启动 / Agent 面板首帧都受益）。判定语义与原实现逐分支等价。
    """
    active = load_active_provider()

    # ── 快路径：已选定具体云端 provider → 无需任何网络探测 ──
    if active and active != "ollama":
        return active

    cloud_candidates = (
        "deepseek", "doubao", "zhipu", "qwen", "openai", "siliconflow",
        "chatgpt2api", "moonshot", "kimi",
    )

    def _ollama_ok() -> bool:
        try:
            from app.modules.lego.ollama_client import ollama_client
            return bool(ollama_client and ollama_client.is_available())
        except Exception:
            return False

    def _configured_cloud() -> list[str]:
        out: list[str] = []
        try:
            from app.modules.lego.cloud_api import cloud_api_service
        except Exception:
            return out
        for pid in cloud_candidates:
            try:
                if cloud_api_service.is_configured(pid):
                    out.append(pid)
            except Exception:
                continue
        return out

    if active == "ollama":
        # 选了 Ollama：仅当它不可用、且已有云 Key 时才切走
        if _ollama_ok():
            return active
        configured_cloud = _configured_cloud()
        if configured_cloud:
            save_active_provider(configured_cloud[0])
            return configured_cloud[0]
        return active

    # active 为空：先查云 Key（纯本地读，便宜），都没有才去探 Ollama（贵）
    configured_cloud = _configured_cloud()
    if configured_cloud:
        save_active_provider(configured_cloud[0])
        return configured_cloud[0]
    if _ollama_ok():
        save_active_provider("ollama")
        return "ollama"
    return active

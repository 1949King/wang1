"""
云厂商 API 提供者实现
=====================
云平台的具体适配实现（含自托管 OpenAI 兼容网关）。
所有类继承自 cloud_providers.base.BaseCloudProvider。
"""

import json
import logging
from collections.abc import Generator
from typing import override

import requests

from .base import BaseCloudProvider

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# 中国厂商
# ═══════════════════════════════════════════════════════════════


class DeepSeekProvider(BaseCloudProvider):
    """DeepSeek API"""

    @property
    @override
    def default_base_url(self) -> str:
        return "https://api.deepseek.com/v1"

    @property
    @override
    def default_model(self) -> str:
        return "deepseek-chat"

    @override
    def chat(self, messages: list[dict[str, str]], model: str | None = None,
             stream: bool = False, **kwargs: object) -> Generator[str, None, None]:
        model = model or self.default_model
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model, "messages": messages, "stream": stream,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "temperature": kwargs.get("temperature", 0.7)
        }
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers, json=payload, stream=stream, timeout=120
            )
            if response.status_code != 200:
                yield f"API 错误: {response.status_code} - {response.text}"
                return
            if stream:
                for line in response.iter_lines():
                    if line:
                        line = line.decode('utf-8')
                        if line.startswith("data: "):
                            data = line[6:]
                            if data == "[DONE]": break
                            try:
                                chunk = json.loads(data)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content: yield content
                            except Exception as e:
                                logger.warning(f"API请求异常: {e}")
                                yield "error"
            else:
                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                yield content
        except Exception as e:
            logger.error(f"DeepSeek API 调用失败: {e}")
            yield f"错误: {str(e)}"


class DoubaoProvider(BaseCloudProvider):
    """豆包 API (字节跳动)"""

    @property
    @override
    def default_base_url(self) -> str:
        return "https://ark.cn-beijing.volces.com/api/v3"

    @property
    @override
    def default_model(self) -> str:
        return "doubao-pro-4k"

    @override
    def chat(self, messages: list[dict[str, str]], model: str | None = None,
             stream: bool = False, **kwargs: object) -> Generator[str, None, None]:
        model = model or self.default_model
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {"model": model, "messages": messages, "stream": stream}
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers, json=payload, stream=stream, timeout=120
            )
            if response.status_code != 200:
                yield f"API 错误: {response.status_code}"
                return
            if stream:
                for line in response.iter_lines():
                    if line:
                        line = line.decode('utf-8')
                        if line.startswith("data: "):
                            data = line[6:]
                            if data == "[DONE]": break
                            try:
                                chunk = json.loads(data)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content: yield content
                            except Exception as e:
                                logger.warning(f"API error: {e}")
                                pass
            else:
                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                yield content
        except Exception as e:
            logger.error(f"豆包 API 调用失败: {e}")
            yield f"错误: {str(e)}"


class OpenAIProvider(BaseCloudProvider):
    """OpenAI API"""

    @property
    @override
    def default_base_url(self) -> str:
        return "https://api.openai.com/v1"

    @property
    @override
    def default_model(self) -> str:
        return "gpt-4o-mini"

    @override
    def chat(self, messages: list[dict[str, str]], model: str | None = None,
             stream: bool = False, **kwargs: object) -> Generator[str, None, None]:
        model = model or self.default_model
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model, "messages": messages, "stream": stream,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "temperature": kwargs.get("temperature", 0.7)
        }
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers, json=payload, stream=stream, timeout=120
            )
            if response.status_code != 200:
                yield f"API 错误: {response.status_code}"
                return
            if stream:
                for line in response.iter_lines():
                    if line:
                        line = line.decode('utf-8')
                        if line.startswith("data: "):
                            data = line[6:]
                            if data == "[DONE]": break
                            try:
                                chunk = json.loads(data)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content: yield content
                            except Exception as e:
                                logger.warning(f"API error: {e}")
                                pass
            else:
                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                yield content
        except Exception as e:
            logger.error(f"OpenAI API 调用失败: {e}")
            yield f"错误: {str(e)}"


class ZhipuProvider(BaseCloudProvider):
    """智谱 AI API"""

    @property
    @override
    def default_base_url(self) -> str:
        return "https://open.bigmodel.cn/api/paas/v4"

    @property
    @override
    def default_model(self) -> str:
        return "glm-4"

    @override
    def chat(self, messages: list[dict[str, str]], model: str | None = None,
             stream: bool = False, **kwargs: object) -> Generator[str, None, None]:
        model = model or self.default_model
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {"model": model, "messages": messages, "stream": stream}
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers, json=payload, stream=stream, timeout=120
            )
            if response.status_code != 200:
                yield f"API 错误: {response.status_code}"
                return
            if stream:
                for line in response.iter_lines():
                    if line:
                        line = line.decode('utf-8')
                        if line.startswith("data: "):
                            data = line[6:]
                            if data == "[DONE]": break
                            try:
                                chunk = json.loads(data)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content: yield content
                            except Exception as e:
                                logger.warning(f"API error: {e}")
                                pass
            else:
                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                yield content
        except Exception as e:
            logger.error(f"智谱 API 调用失败: {e}")
            yield f"错误: {str(e)}"


class QwenProvider(BaseCloudProvider):
    """通义千问 API (阿里云)"""

    @property
    @override
    def default_base_url(self) -> str:
        return "https://dashscope.aliyuncs.com/compatible-mode/v1"

    @property
    @override
    def default_model(self) -> str:
        return "qwen-turbo"

    @override
    def chat(self, messages: list[dict[str, str]], model: str | None = None,
             stream: bool = False, **kwargs: object) -> Generator[str, None, None]:
        model = model or self.default_model
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model, "messages": messages, "stream": stream,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "temperature": kwargs.get("temperature", 0.7)
        }
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers, json=payload, stream=stream, timeout=120
            )
            if response.status_code != 200:
                yield f"API 错误: {response.status_code} - {response.text}"
                return
            if stream:
                for line in response.iter_lines():
                    if line:
                        line = line.decode('utf-8')
                        if line.startswith("data: "):
                            data = line[6:]
                            if data == "[DONE]": break
                            try:
                                chunk = json.loads(data)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content: yield content
                            except Exception as e:
                                logger.warning(f"API error: {e}")
                                pass
            else:
                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                yield content
        except Exception as e:
            logger.error(f"通义千问 API 调用失败: {e}")
            yield f"错误: {str(e)}"


class WenxinProvider(BaseCloudProvider):
    """文心一言 API (百度)"""

    @property
    @override
    def default_base_url(self) -> str:
        return "https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat"

    @property
    @override
    def default_model(self) -> str:
        return "ernie-4.0-8k"

    @override
    def chat(self, messages: list[dict[str, str]], model: str | None = None,
             stream: bool = False, **kwargs: object) -> Generator[str, None, None]:
        model = model or self.default_model
        headers = {"Content-Type": "application/json"}
        payload = {
            "messages": messages, "stream": stream,
            "max_output_tokens": kwargs.get("max_tokens", 4096),
            "temperature": kwargs.get("temperature", 0.7)
        }
        try:
            response = requests.post(
                f"{self.base_url}/{model}?access_token={self.api_key}",
                headers=headers, json=payload, stream=stream, timeout=120
            )
            if response.status_code != 200:
                yield f"API 错误: {response.status_code} - {response.text}"
                return
            if stream:
                for line in response.iter_lines():
                    if line:
                        line = line.decode('utf-8')
                        try:
                            chunk = json.loads(line)
                            content = chunk.get("result", "")
                            if content: yield content
                        except Exception as e:
                            logger.warning(f"API error: {e}")
                            pass
            else:
                data = response.json()
                content = data.get("result", "")
                yield content
        except Exception as e:
            logger.error(f"文心一言 API 调用失败: {e}")
            yield f"错误: {str(e)}"


class SparkProvider(BaseCloudProvider):
    """讯飞星火 API"""

    @property
    @override
    def default_base_url(self) -> str:
        return "https://spark-api-open.xf-yun.com/v1"

    @property
    @override
    def default_model(self) -> str:
        return "generalv3.5"

    @override
    def chat(self, messages: list[dict[str, str]], model: str | None = None,
             stream: bool = False, **kwargs: object) -> Generator[str, None, None]:
        model = model or self.default_model
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model, "messages": messages, "stream": stream,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "temperature": kwargs.get("temperature", 0.7)
        }
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers, json=payload, stream=stream, timeout=120
            )
            if response.status_code != 200:
                yield f"API 错误: {response.status_code} - {response.text}"
                return
            if stream:
                for line in response.iter_lines():
                    if line:
                        line = line.decode('utf-8')
                        if line.startswith("data: "):
                            data = line[6:]
                            if data == "[DONE]": break
                            try:
                                chunk = json.loads(data)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content: yield content
                            except Exception as e:
                                logger.warning(f"API error: {e}")
                                pass
            else:
                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                yield content
        except Exception as e:
            logger.error(f"讯飞星火 API 调用失败: {e}")
            yield f"错误: {str(e)}"


class KimiProvider(BaseCloudProvider):
    """Kimi API (Moonshot)"""

    @property
    @override
    def default_base_url(self) -> str:
        return "https://api.moonshot.cn/v1"

    @property
    @override
    def default_model(self) -> str:
        return "moonshot-v1-8k"

    @override
    def chat(self, messages: list[dict[str, str]], model: str | None = None,
             stream: bool = False, **kwargs: object) -> Generator[str, None, None]:
        model = model or self.default_model
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model, "messages": messages, "stream": stream,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "temperature": kwargs.get("temperature", 0.7)
        }
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers, json=payload, stream=stream, timeout=120
            )
            if response.status_code != 200:
                yield f"API 错误: {response.status_code} - {response.text}"
                return
            if stream:
                for line in response.iter_lines():
                    if line:
                        line = line.decode('utf-8')
                        if line.startswith("data: "):
                            data = line[6:]
                            if data == "[DONE]": break
                            try:
                                chunk = json.loads(data)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content: yield content
                            except Exception as e:
                                logger.warning(f"API error: {e}")
                                pass
            else:
                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                yield content
        except Exception as e:
            logger.error(f"Kimi API 调用失败: {e}")
            yield f"错误: {str(e)}"


class BaichuanProvider(BaseCloudProvider):
    """百川 API"""

    @property
    @override
    def default_base_url(self) -> str:
        return "https://api.baichuan-ai.com/v1"

    @property
    @override
    def default_model(self) -> str:
        return "Baichuan4"

    @override
    def chat(self, messages: list[dict[str, str]], model: str | None = None,
             stream: bool = False, **kwargs: object) -> Generator[str, None, None]:
        model = model or self.default_model
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model, "messages": messages, "stream": stream,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "temperature": kwargs.get("temperature", 0.7)
        }
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers, json=payload, stream=stream, timeout=120
            )
            if response.status_code != 200:
                yield f"API 错误: {response.status_code} - {response.text}"
                return
            if stream:
                for line in response.iter_lines():
                    if line:
                        line = line.decode('utf-8')
                        if line.startswith("data: "):
                            data = line[6:]
                            if data == "[DONE]": break
                            try:
                                chunk = json.loads(data)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content: yield content
                            except Exception as e:
                                logger.warning(f"API error: {e}")
                                pass
            else:
                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                yield content
        except Exception as e:
            logger.error(f"百川 API 调用失败: {e}")
            yield f"错误: {str(e)}"


class MiniMaxProvider(BaseCloudProvider):
    """MiniMax API"""

    @property
    @override
    def default_base_url(self) -> str:
        return "https://api.minimax.chat/v1"

    @property
    @override
    def default_model(self) -> str:
        return "abab6.5s-chat"

    @override
    def chat(self, messages: list[dict[str, str]], model: str | None = None,
             stream: bool = False, **kwargs: object) -> Generator[str, None, None]:
        model = model or self.default_model
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model, "messages": messages, "stream": stream,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "temperature": kwargs.get("temperature", 0.7)
        }
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers, json=payload, stream=stream, timeout=120
            )
            if response.status_code != 200:
                yield f"API 错误: {response.status_code} - {response.text}"
                return
            if stream:
                for line in response.iter_lines():
                    if line:
                        line = line.decode('utf-8')
                        if line.startswith("data: "):
                            data = line[6:]
                            if data == "[DONE]": break
                            try:
                                chunk = json.loads(data)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content: yield content
                            except Exception as e:
                                logger.warning(f"API error: {e}")
                                pass
            else:
                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                yield content
        except Exception as e:
            logger.error(f"MiniMax API 调用失败: {e}")
            yield f"错误: {str(e)}"


class ClaudeProvider(BaseCloudProvider):
    """Claude API (Anthropic)"""

    @property
    @override
    def default_base_url(self) -> str:
        return "https://api.anthropic.com/v1"

    @property
    @override
    def default_model(self) -> str:
        return "claude-3-5-sonnet-20241022"

    @override
    def chat(self, messages: list[dict[str, str]], model: str | None = None,
             stream: bool = False, **kwargs: object) -> Generator[str, None, None]:
        model = model or self.default_model
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json"
        }
        system_message = ""
        chat_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_message = msg["content"]
            else:
                chat_messages.append(msg)
        payload = {
            "model": model, "messages": chat_messages,
            "max_tokens": kwargs.get("max_tokens", 4096),
        }
        if system_message:
            payload["system"] = system_message
        try:
            response = requests.post(
                f"{self.base_url}/messages",
                headers=headers, json=payload, stream=stream, timeout=120
            )
            if response.status_code != 200:
                yield f"API 错误: {response.status_code} - {response.text}"
                return
            if stream:
                for line in response.iter_lines():
                    if line:
                        line = line.decode('utf-8')
                        if line.startswith("data: "):
                            data = line[6:]
                            try:
                                chunk = json.loads(data)
                                if chunk.get("type") == "content_block_delta":
                                    content = chunk.get("delta", {}).get("text", "")
                                    if content: yield content
                            except Exception as e:
                                logger.warning(f"API error: {e}")
                                pass
            else:
                data = response.json()
                content_blocks = data.get("content", [])
                content = "".join([b.get("text", "") for b in content_blocks if b.get("type") == "text"])
                yield content
        except Exception as e:
            logger.error(f"Claude API 调用失败: {e}")
            yield f"错误: {str(e)}"


class GroqProvider(BaseCloudProvider):
    """Groq API (极速推理)"""

    @property
    @override
    def default_base_url(self) -> str:
        return "https://api.groq.com/openai/v1"

    @property
    @override
    def default_model(self) -> str:
        return "llama-3.3-70b-versatile"

    @override
    def chat(self, messages: list[dict[str, str]], model: str | None = None,
             stream: bool = False, **kwargs: object) -> Generator[str, None, None]:
        model = model or self.default_model
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model, "messages": messages, "stream": stream,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "temperature": kwargs.get("temperature", 0.7)
        }
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers, json=payload, stream=stream, timeout=120
            )
            if response.status_code != 200:
                yield f"API 错误: {response.status_code} - {response.text}"
                return
            if stream:
                for line in response.iter_lines():
                    if line:
                        line = line.decode('utf-8')
                        if line.startswith("data: "):
                            data = line[6:]
                            if data == "[DONE]": break
                            try:
                                chunk = json.loads(data)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content: yield content
                            except Exception as e:
                                logger.warning(f"API error: {e}")
                                pass
            else:
                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                yield content
        except Exception as e:
            logger.error(f"Groq API 调用失败: {e}")
            yield f"错误: {str(e)}"


class SiliconFlowProvider(BaseCloudProvider):
    """SiliconFlow API (硅基流动)"""

    @property
    @override
    def default_base_url(self) -> str:
        return "https://api.siliconflow.cn/v1"

    @property
    @override
    def default_model(self) -> str:
        return "Qwen/Qwen2.5-72B-Instruct"

    @override
    def chat(self, messages: list[dict[str, str]], model: str | None = None,
             stream: bool = False, **kwargs: object) -> Generator[str, None, None]:
        model = model or self.default_model
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model, "messages": messages, "stream": stream,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "temperature": kwargs.get("temperature", 0.7)
        }
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers, json=payload, stream=stream, timeout=120
            )
            if response.status_code != 200:
                yield f"API 错误: {response.status_code} - {response.text}"
                return
            if stream:
                for line in response.iter_lines():
                    if line:
                        line = line.decode('utf-8')
                        if line.startswith("data: "):
                            data = line[6:]
                            if data == "[DONE]": break
                            try:
                                chunk = json.loads(data)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content: yield content
                            except Exception as e:
                                logger.warning(f"API error: {e}")
                                pass
            else:
                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                yield content
        except Exception as e:
            logger.error(f"SiliconFlow API 调用失败: {e}")
            yield f"错误: {str(e)}"


class StepfunProvider(BaseCloudProvider):
    """阶跃星辰 API (Step)"""

    @property
    @override
    def default_base_url(self) -> str:
        return "https://api.stepfun.com/v1"

    @property
    @override
    def default_model(self) -> str:
        return "step-1-8k"

    @override
    def chat(self, messages: list[dict[str, str]], model: str | None = None,
             stream: bool = False, **kwargs: object) -> Generator[str, None, None]:
        model = model or self.default_model
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model, "messages": messages, "stream": stream,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "temperature": kwargs.get("temperature", 0.7)
        }
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers, json=payload, stream=stream, timeout=120
            )
            if response.status_code != 200:
                yield f"API 错误: {response.status_code} - {response.text}"
                return
            if stream:
                for line in response.iter_lines():
                    if line:
                        line = line.decode('utf-8')
                        if line.startswith("data: "):
                            data = line[6:]
                            if data == "[DONE]": break
                            try:
                                chunk = json.loads(data)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content: yield content
                            except Exception as e:
                                logger.warning(f"API error: {e}")
                                pass
            else:
                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                yield content
        except Exception as e:
            logger.error(f"阶跃星辰 API 调用失败: {e}")
            yield f"错误: {str(e)}"


class YiProvider(BaseCloudProvider):
    """零一万物 API (Yi)"""

    @property
    @override
    def default_base_url(self) -> str:
        return "https://api.lingyiwanwu.com/v1"

    @property
    @override
    def default_model(self) -> str:
        return "yi-lightning"

    @override
    def chat(self, messages: list[dict[str, str]], model: str | None = None,
             stream: bool = False, **kwargs: object) -> Generator[str, None, None]:
        model = model or self.default_model
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model, "messages": messages, "stream": stream,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "temperature": kwargs.get("temperature", 0.7)
        }
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers, json=payload, stream=stream, timeout=120
            )
            if response.status_code != 200:
                yield f"API 错误: {response.status_code} - {response.text}"
                return
            if stream:
                for line in response.iter_lines():
                    if line:
                        line = line.decode('utf-8')
                        if line.startswith("data: "):
                            data = line[6:]
                            if data == "[DONE]": break
                            try:
                                chunk = json.loads(data)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content: yield content
                            except Exception as e:
                                logger.warning(f"API error: {e}")
                                pass
            else:
                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                yield content
        except Exception as e:
            logger.error(f"零一万物 API 调用失败: {e}")
            yield f"错误: {str(e)}"


class OllamaProvider(BaseCloudProvider):
    """Ollama 本地模型 API"""

    @property
    @override
    def default_base_url(self) -> str:
        return "http://localhost:11434/v1"

    @property
    @override
    def default_model(self) -> str:
        return "qwen2:7b"

    @override
    def chat(self, messages: list[dict[str, str]], model: str | None = None,
             stream: bool = False, **kwargs: object) -> Generator[str, None, None]:
        model = model or self.default_model
        headers = {
            "Content-Type": "application/json"
        }
        payload = {
            "model": model, "messages": messages, "stream": stream,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "temperature": kwargs.get("temperature", 0.7)
        }
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers, json=payload, stream=stream, timeout=300,
                trust_env=False
            )
            if response.status_code != 200:
                yield f"API 错误: {response.status_code} - {response.text}"
                return
            if stream:
                for line in response.iter_lines():
                    if line:
                        line = line.decode('utf-8')
                        if line.startswith("data: "):
                            data = line[6:]
                            if data == "[DONE]": break
                            try:
                                chunk = json.loads(data)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content: yield content
                            except Exception as e:
                                logger.warning(f"API error: {e}")
                                pass
            else:
                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                yield content
        except requests.exceptions.ConnectionError:
            yield "错误: 无法连接 Ollama 服务，请确认 Ollama 已安装并启动（运行 'ollama serve'）"
        except Exception as e:
            logger.error(f"Ollama API 调用失败: {e}")
            yield f"错误: {str(e)}"


class ModelScopeProvider(BaseCloudProvider):
    """魔搭社区 API (ModelScope)"""

    @property
    @override
    def default_base_url(self) -> str:
        return "https://dashscope.aliyuncs.com/compatible-mode/v1"

    @property
    @override
    def default_model(self) -> str:
        return "qwen-turbo"

    @override
    def chat(self, messages: list[dict[str, str]], model: str | None = None,
             stream: bool = False, **kwargs: object) -> Generator[str, None, None]:
        model = model or self.default_model
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model, "messages": messages, "stream": stream,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "temperature": kwargs.get("temperature", 0.7)
        }
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers, json=payload, stream=stream, timeout=120
            )
            if response.status_code != 200:
                yield f"API 错误: {response.status_code} - {response.text}"
                return
            if stream:
                for line in response.iter_lines():
                    if line:
                        line = line.decode('utf-8')
                        if line.startswith("data: "):
                            data = line[6:]
                            if data == "[DONE]": break
                            try:
                                chunk = json.loads(data)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content: yield content
                            except Exception as e:
                                logger.warning(f"API error: {e}")
                                pass
            else:
                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                yield content
        except Exception as e:
            logger.error(f"魔搭社区 API 调用失败: {e}")
            yield f"错误: {str(e)}"


class ChatGPT2APIProvider(BaseCloudProvider):
    """ChatGPT2API — 自托管 OpenAI 兼容网关（gpt-image-2 / gpt-5*）。

    默认本机 ``http://127.0.0.1:8000/v1``；Auth Key 与 Base URL 在模型广场卡片配置。
    """

    @property
    @override
    def default_base_url(self) -> str:
        return "http://127.0.0.1:8000/v1"

    @property
    @override
    def default_model(self) -> str:
        return "gpt-image-2"

    @override
    def chat(self, messages: list[dict[str, str]], model: str | None = None,
             stream: bool = False, **kwargs: object) -> Generator[str, None, None]:
        model = model or self.default_model
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "temperature": kwargs.get("temperature", 0.7),
        }
        try:
            response = requests.post(
                f"{self.base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json=payload,
                stream=stream,
                timeout=180,
            )
            if response.status_code != 200:
                yield f"API 错误: {response.status_code} - {response.text[:400]}"
                return
            if stream:
                for line in response.iter_lines():
                    if line:
                        line = line.decode("utf-8")
                        if line.startswith("data: "):
                            data = line[6:]
                            if data == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield content
                            except Exception as e:
                                logger.warning(f"API error: {e}")
            else:
                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                yield content
        except requests.exceptions.ConnectionError:
            yield "错误: 无法连接 ChatGPT2API，请确认服务已启动（默认 http://127.0.0.1:8000）"
        except Exception as e:
            logger.error(f"ChatGPT2API 调用失败: {e}")
            yield f"错误: {str(e)}"


class KlingProvider(BaseCloudProvider):
    """可灵 AI Provider — 快手视频生成大模型（OpenAI-compatible chat/completions）。

    视频/生图走画布 AIGC 专用路由；文本对话复用 chat/completions。
    """

    @property
    @override
    def default_base_url(self) -> str:
        return "https://api.klingai.com/v1"

    @property
    @override
    def default_model(self) -> str:
        return "kling-v1.6"

    @override
    def chat(self, messages: list[dict[str, str]], model: str | None = None,
             stream: bool = False, **kwargs: object) -> Generator[str, None, None]:
        model = model or self.default_model
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "temperature": kwargs.get("temperature", 0.7),
        }
        try:
            response = requests.post(
                f"{self.base_url.rstrip('/')}/chat/completions",
                headers=headers, json=payload, stream=stream, timeout=180,
            )
            if response.status_code != 200:
                yield f"API 错误: {response.status_code} - {response.text[:400]}"
                return
            if stream:
                for line in response.iter_lines():
                    if line:
                        line = line.decode("utf-8")
                        if line.startswith("data: "):
                            data = line[6:]
                            if data == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield content
                            except Exception as e:
                                logger.warning(f"Kling stream error: {e}")
            else:
                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                yield content
        except Exception as e:
            logger.error(f"Kling API 调用失败: {e}")
            yield f"错误: {str(e)}"


class FishAudioProvider(BaseCloudProvider):
    """Fish Audio Provider — 开源语音合成（OpenAI-compatible）。

    支持云端 https://api.fish.audio/v1 或自托管（本地部署填自定义 Base URL）。
    """

    @property
    @override
    def default_base_url(self) -> str:
        return "https://api.fish.audio/v1"

    @property
    @override
    def default_model(self) -> str:
        return "fish-speech-v1.5"

    @override
    def chat(self, messages: list[dict[str, str]], model: str | None = None,
             stream: bool = False, **kwargs: object) -> Generator[str, None, None]:
        model = model or self.default_model
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "temperature": kwargs.get("temperature", 0.7),
        }
        try:
            response = requests.post(
                f"{self.base_url.rstrip('/')}/chat/completions",
                headers=headers, json=payload, stream=stream, timeout=180,
            )
            if response.status_code != 200:
                yield f"API 错误: {response.status_code} - {response.text[:400]}"
                return
            if stream:
                for line in response.iter_lines():
                    if line:
                        line = line.decode("utf-8")
                        if line.startswith("data: "):
                            data = line[6:]
                            if data == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield content
                            except Exception as e:
                                logger.warning(f"FishAudio stream error: {e}")
            else:
                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                yield content
        except Exception as e:
            logger.error(f"FishAudio API 调用失败: {e}")
            yield f"错误: {str(e)}"


class StabilityProvider(BaseCloudProvider):
    """Stability AI Provider — 直接对接 Stability AI v2beta API。

    区别于 siliconflow 中转：此处用官方 api.stability.ai，需官方 API Key。
    生图走 images/generations 路由；文本对话走 chat/completions。
    """

    @property
    @override
    def default_base_url(self) -> str:
        return "https://api.stability.ai/v2beta"

    @property
    @override
    def default_model(self) -> str:
        return "sd3-large"

    @override
    def chat(self, messages: list[dict[str, str]], model: str | None = None,
             stream: bool = False, **kwargs: object) -> Generator[str, None, None]:
        model = model or self.default_model
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "temperature": kwargs.get("temperature", 0.7),
        }
        try:
            response = requests.post(
                f"{self.base_url.rstrip('/')}/chat/completions",
                headers=headers, json=payload, stream=stream, timeout=180,
            )
            if response.status_code != 200:
                yield f"API 错误: {response.status_code} - {response.text[:400]}"
                return
            if stream:
                for line in response.iter_lines():
                    if line:
                        line = line.decode("utf-8")
                        if line.startswith("data: "):
                            data = line[6:]
                            if data == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield content
                            except Exception as e:
                                logger.warning(f"Stability stream error: {e}")
            else:
                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                yield content
        except Exception as e:
            logger.error(f"Stability AI API 调用失败: {e}")
            yield f"错误: {str(e)}"

"""
云端 API 模块 (CloudAPI)
========================
支持多种云端大模型 API
DeepSeek / 豆包 / OpenAI / 智谱 AI / 通义千问 / 文心一言 / 讯飞星火 / Kimi / 百川 / MiniMax / Claude / Groq / SiliconFlow
"""

import json
import time
import threading
import requests
from typing import Optional, Dict, List, Any, Generator, Callable
from dataclasses import dataclass
from abc import ABC, abstractmethod
import logging

logger = logging.getLogger(__name__)


@dataclass
class APIConfig:
    """API 配置"""
    provider: str = "deepseek"
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    max_tokens: int = 4096
    temperature: float = 0.7


class BaseCloudProvider(ABC):
    """云端 API 基类"""
    
    def __init__(self, api_key: str, base_url: str = ""):
        self.api_key = api_key
        self.base_url = base_url or self.default_base_url
    
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
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        stream: bool = False,
        **kwargs
    ) -> Generator[str, None, None]:
        pass


class DeepSeekProvider(BaseCloudProvider):
    """DeepSeek API"""
    
    @property
    def default_base_url(self) -> str:
        return "https://api.deepseek.com/v1"
    
    @property
    def default_model(self) -> str:
        return "deepseek-chat"
    
    def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        stream: bool = False,
        **kwargs
    ) -> Generator[str, None, None]:
        
        model = model or self.default_model
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "temperature": kwargs.get("temperature", 0.7)
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                stream=stream,
                timeout=120
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
                            if data == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield content
                            except:
                                pass
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
    def default_base_url(self) -> str:
        return "https://ark.cn-beijing.volces.com/api/v3"
    
    @property
    def default_model(self) -> str:
        return "doubao-pro-4k"
    
    def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        stream: bool = False,
        **kwargs
    ) -> Generator[str, None, None]:
        
        model = model or self.default_model
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                stream=stream,
                timeout=120
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
                            if data == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield content
                            except:
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
    def default_base_url(self) -> str:
        return "https://api.openai.com/v1"
    
    @property
    def default_model(self) -> str:
        return "gpt-4o-mini"
    
    def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        stream: bool = False,
        **kwargs
    ) -> Generator[str, None, None]:
        
        model = model or self.default_model
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "temperature": kwargs.get("temperature", 0.7)
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                stream=stream,
                timeout=120
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
                            if data == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield content
                            except:
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
    def default_base_url(self) -> str:
        return "https://open.bigmodel.cn/api/paas/v4"
    
    @property
    def default_model(self) -> str:
        return "glm-4"
    
    def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        stream: bool = False,
        **kwargs
    ) -> Generator[str, None, None]:
        
        model = model or self.default_model
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                stream=stream,
                timeout=120
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
                            if data == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield content
                            except:
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
    def default_base_url(self) -> str:
        return "https://dashscope.aliyuncs.com/compatible-mode/v1"
    
    @property
    def default_model(self) -> str:
        return "qwen-turbo"
    
    def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        stream: bool = False,
        **kwargs
    ) -> Generator[str, None, None]:
        
        model = model or self.default_model
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "temperature": kwargs.get("temperature", 0.7)
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                stream=stream,
                timeout=120
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
                            if data == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield content
                            except:
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
    def default_base_url(self) -> str:
        return "https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat"
    
    @property
    def default_model(self) -> str:
        return "ernie-4.0-8k"
    
    def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        stream: bool = False,
        **kwargs
    ) -> Generator[str, None, None]:
        
        model = model or self.default_model
        
        headers = {
            "Content-Type": "application/json"
        }
        
        payload = {
            "messages": messages,
            "stream": stream,
            "max_output_tokens": kwargs.get("max_tokens", 4096),
            "temperature": kwargs.get("temperature", 0.7)
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/{model}?access_token={self.api_key}",
                headers=headers,
                json=payload,
                stream=stream,
                timeout=120
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
                            if content:
                                yield content
                        except:
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
    def default_base_url(self) -> str:
        return "https://spark-api-open.xf-yun.com/v1"
    
    @property
    def default_model(self) -> str:
        return "generalv3.5"
    
    def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        stream: bool = False,
        **kwargs
    ) -> Generator[str, None, None]:
        
        model = model or self.default_model
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "temperature": kwargs.get("temperature", 0.7)
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                stream=stream,
                timeout=120
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
                            if data == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield content
                            except:
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
    def default_base_url(self) -> str:
        return "https://api.moonshot.cn/v1"
    
    @property
    def default_model(self) -> str:
        return "moonshot-v1-8k"
    
    def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        stream: bool = False,
        **kwargs
    ) -> Generator[str, None, None]:
        
        model = model or self.default_model
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "temperature": kwargs.get("temperature", 0.7)
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                stream=stream,
                timeout=120
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
                            if data == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield content
                            except:
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
    def default_base_url(self) -> str:
        return "https://api.baichuan-ai.com/v1"
    
    @property
    def default_model(self) -> str:
        return "Baichuan4"
    
    def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        stream: bool = False,
        **kwargs
    ) -> Generator[str, None, None]:
        
        model = model or self.default_model
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "temperature": kwargs.get("temperature", 0.7)
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                stream=stream,
                timeout=120
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
                            if data == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield content
                            except:
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
    def default_base_url(self) -> str:
        return "https://api.minimax.chat/v1"
    
    @property
    def default_model(self) -> str:
        return "abab6.5s-chat"
    
    def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        stream: bool = False,
        **kwargs
    ) -> Generator[str, None, None]:
        
        model = model or self.default_model
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "temperature": kwargs.get("temperature", 0.7)
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                stream=stream,
                timeout=120
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
                            if data == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield content
                            except:
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
    def default_base_url(self) -> str:
        return "https://api.anthropic.com/v1"
    
    @property
    def default_model(self) -> str:
        return "claude-3-5-sonnet-20241022"
    
    def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        stream: bool = False,
        **kwargs
    ) -> Generator[str, None, None]:
        
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
            "model": model,
            "messages": chat_messages,
            "max_tokens": kwargs.get("max_tokens", 4096),
        }
        
        if system_message:
            payload["system"] = system_message
        
        try:
            response = requests.post(
                f"{self.base_url}/messages",
                headers=headers,
                json=payload,
                stream=stream,
                timeout=120
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
                                    if content:
                                        yield content
                            except:
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
    def default_base_url(self) -> str:
        return "https://api.groq.com/openai/v1"
    
    @property
    def default_model(self) -> str:
        return "llama-3.3-70b-versatile"
    
    def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        stream: bool = False,
        **kwargs
    ) -> Generator[str, None, None]:
        
        model = model or self.default_model
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "temperature": kwargs.get("temperature", 0.7)
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                stream=stream,
                timeout=120
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
                            if data == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield content
                            except:
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
    def default_base_url(self) -> str:
        return "https://api.siliconflow.cn/v1"
    
    @property
    def default_model(self) -> str:
        return "Qwen/Qwen2.5-72B-Instruct"
    
    def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        stream: bool = False,
        **kwargs
    ) -> Generator[str, None, None]:
        
        model = model or self.default_model
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "temperature": kwargs.get("temperature", 0.7)
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                stream=stream,
                timeout=120
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
                            if data == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield content
                            except:
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
    def default_base_url(self) -> str:
        return "https://api.stepfun.com/v1"
    
    @property
    def default_model(self) -> str:
        return "step-1-8k"
    
    def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        stream: bool = False,
        **kwargs
    ) -> Generator[str, None, None]:
        
        model = model or self.default_model
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "temperature": kwargs.get("temperature", 0.7)
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                stream=stream,
                timeout=120
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
                            if data == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield content
                            except:
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
    def default_base_url(self) -> str:
        return "https://api.lingyiwanwu.com/v1"
    
    @property
    def default_model(self) -> str:
        return "yi-lightning"
    
    def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        stream: bool = False,
        **kwargs
    ) -> Generator[str, None, None]:
        
        model = model or self.default_model
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "temperature": kwargs.get("temperature", 0.7)
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                stream=stream,
                timeout=120
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
                            if data == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield content
                            except:
                                pass
            else:
                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                yield content
                
        except Exception as e:
            logger.error(f"零一万物 API 调用失败: {e}")
            yield f"错误: {str(e)}"


class CloudAPIService:
    """云端 API 服务"""
    
    _instance: Optional['CloudAPIService'] = None
    _lock = threading.Lock()
    
    PROVIDERS = {
        "deepseek": DeepSeekProvider,
        "doubao": DoubaoProvider,
        "openai": OpenAIProvider,
        "zhipu": ZhipuProvider,
        "qwen": QwenProvider,
        "wenxin": WenxinProvider,
        "spark": SparkProvider,
        "kimi": KimiProvider,
        "baichuan": BaichuanProvider,
        "minimax": MiniMaxProvider,
        "claude": ClaudeProvider,
        "groq": GroqProvider,
        "siliconflow": SiliconFlowProvider,
        "stepfun": StepfunProvider,
        "yi": YiProvider,
        "ollama": "local"  # 本地 Ollama 模型
    }
    
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
        self._initialized = True
        
        self._configs: Dict[str, APIConfig] = {}
        self._providers: Dict[str, BaseCloudProvider] = {}
        self._load_configs()
        
        # 尝试导入 Ollama 客户端
        self._ollama_client = None
        try:
            from .ollama_client import ollama_client
            self._ollama_client = ollama_client
        except ImportError:
            logger.warning("Ollama 客户端未找到")
    
    def _load_configs(self):
        """加载 API 配置"""
        import os
        import json
        
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "data", "api_configs.json"
        )
        
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                for provider, config_data in data.items():
                    self._configs[provider] = APIConfig(
                        provider=provider,
                        api_key=config_data.get("api_key", ""),
                        base_url=config_data.get("base_url", ""),
                        model=config_data.get("model", "")
                    )
            except Exception as e:
                logger.warning(f"加载 API 配置失败: {e}")
    
    def save_configs(self):
        """保存 API 配置"""
        import os
        import json
        
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "data", "api_configs.json"
        )
        
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        
        data = {}
        for provider, config in self._configs.items():
            data[provider] = {
                "api_key": config.api_key,
                "base_url": config.base_url,
                "model": config.model
            }
        
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def set_config(self, provider: str, api_key: str, base_url: str = "", model: str = ""):
        """设置 API 配置"""
        self._configs[provider] = APIConfig(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=model
        )
        
        if provider in self._providers:
            del self._providers[provider]
        
        self.save_configs()
    
    def get_config(self, provider: str) -> Optional[APIConfig]:
        """获取 API 配置"""
        return self._configs.get(provider)
    
    def get_provider(self, provider: str) -> Optional[BaseCloudProvider]:
        """获取 API 提供者实例"""
        if provider not in self.PROVIDERS:
            return None
        
        if provider in self._providers:
            return self._providers[provider]
        
        config = self._configs.get(provider)
        if not config or not config.api_key:
            return None
        
        provider_class = self.PROVIDERS[provider]
        self._providers[provider] = provider_class(
            api_key=config.api_key,
            base_url=config.base_url
        )
        
        return self._providers[provider]
    
    def chat(
        self,
        provider: str,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        stream: bool = False,
        **kwargs
    ) -> Generator[str, None, None]:
        """调用聊天 API"""
        # 处理 Ollama 本地模型
        if provider == "ollama":
            if not self._ollama_client:
                yield "错误: Ollama 客户端未初始化"
                return
            
            if not self._ollama_client.is_available():
                yield "错误: Ollama 服务不可用，请确保 Ollama 已安装并运行"
                return
            
            # 使用默认模型或用户指定的模型
            if not model:
                models = self._ollama_client.list_models()
                if not models:
                    yield "错误: 未检测到 Ollama 模型，请先下载模型"
                    return
                model = models[0].name
            
            yield from self._ollama_client.chat(model, messages, stream, **kwargs)
            return
        
        # 处理云端 API
        provider_instance = self.get_provider(provider)
        
        if not provider_instance:
            yield f"错误: {provider} API 未配置"
            return
        
        config = self._configs.get(provider)
        model = model or (config.model if config else None)
        
        yield from provider_instance.chat(messages, model, stream, **kwargs)
    
    def is_configured(self, provider: str) -> bool:
        """检查是否已配置"""
        if provider == "ollama":
            return self._ollama_client is not None and self._ollama_client.is_available()
        
        config = self._configs.get(provider)
        return config is not None and bool(config.api_key)
    
    def list_providers(self) -> List[str]:
        """列出所有支持的提供者"""
        return list(self.PROVIDERS.keys())


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

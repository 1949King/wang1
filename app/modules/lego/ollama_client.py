"""
Ollama 客户端模块 (OllamaClient)
================================
本地大模型 Ollama 集成
支持本地 AI 推理，无需云端 API
"""

import json
import requests
import subprocess
import os
import time
import threading
from typing import Optional, Dict, List, Any, Generator, Callable
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class OllamaModel:
    """Ollama 模型信息"""
    name: str
    size: str
    modified_at: str
    digest: str
    
    @property
    def display_name(self) -> str:
        """显示名称"""
        if ":" in self.name:
            return self.name
        return f"{self.name}:latest"


@dataclass
class OllamaConfig:
    """Ollama 配置"""
    host: str = "http://localhost"
    port: int = 11434
    timeout: int = 300
    
    @property
    def base_url(self) -> str:
        return f"{self.host}:{self.port}"


class OllamaClient:
    """Ollama 客户端"""
    
    _instance: Optional['OllamaClient'] = None
    _lock = threading.Lock()
    
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
        
        self._config = OllamaConfig()
        self._available: Optional[bool] = None
        self._models: List[OllamaModel] = []
        self._last_check: float = 0
    
    @property
    def base_url(self) -> str:
        return self._config.base_url
    
    def is_available(self, force_check: bool = False) -> bool:
        """检查 Ollama 服务是否可用"""
        now = time.time()
        
        if not force_check and self._available is not None and now - self._last_check < 60:
            return self._available
        
        try:
            response = requests.get(
                f"{self.base_url}/api/tags",
                timeout=5
            )
            self._available = response.status_code == 200
            self._last_check = now
            return self._available
        except Exception as e:
            logger.debug(f"Ollama 服务不可用: {e}")
            self._available = False
            self._last_check = now
            return False
    
    def list_models(self, force_refresh: bool = False) -> List[OllamaModel]:
        """获取已安装的模型列表"""
        if not force_refresh and self._models:
            return self._models
        
        if not self.is_available():
            return []
        
        try:
            response = requests.get(
                f"{self.base_url}/api/tags",
                timeout=10
            )
            
            if response.status_code != 200:
                return []
            
            data = response.json()
            models = []
            
            for model_data in data.get("models", []):
                models.append(OllamaModel(
                    name=model_data.get("name", ""),
                    size=model_data.get("size", ""),
                    modified_at=model_data.get("modified_at", ""),
                    digest=model_data.get("digest", "")
                ))
            
            self._models = models
            return models
            
        except Exception as e:
            logger.error(f"获取模型列表失败: {e}")
            return []
    
    def pull_model(self, model_name: str, progress_callback: Optional[Callable[[str], None]] = None) -> bool:
        """拉取模型"""
        try:
            response = requests.post(
                f"{self.base_url}/api/pull",
                json={"name": model_name},
                stream=True,
                timeout=3600
            )
            
            for line in response.iter_lines():
                if line:
                    data = json.loads(line)
                    status = data.get("status", "")
                    
                    if progress_callback:
                        progress_callback(status)
                    
                    if status == "success":
                        self._models = []
                        return True
            
            return False
            
        except Exception as e:
            logger.error(f"拉取模型失败: {e}")
            return False
    
    def delete_model(self, model_name: str) -> bool:
        """删除模型"""
        try:
            response = requests.delete(
                f"{self.base_url}/api/delete",
                json={"name": model_name},
                timeout=30
            )
            
            if response.status_code == 200:
                self._models = []
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"删除模型失败: {e}")
            return False
    
    def generate(
        self,
        model: str,
        prompt: str,
        system: Optional[str] = None,
        context: Optional[List[int]] = None,
        stream: bool = False,
        options: Optional[Dict[str, Any]] = None
    ) -> Generator[str, None, None]:
        """生成文本 (流式输出)"""
        
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": stream
        }
        
        if system:
            payload["system"] = system
        
        if context:
            payload["context"] = context
        
        if options:
            payload["options"] = options
        
        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json=payload,
                stream=True,
                timeout=self._config.timeout
            )
            
            full_response = ""
            
            for line in response.iter_lines():
                if line:
                    data = json.loads(line)
                    token = data.get("response", "")
                    full_response += token
                    
                    if stream:
                        yield token
            
            if not stream:
                yield full_response
                
        except Exception as e:
            logger.error(f"生成文本失败: {e}")
            yield f"错误: {str(e)}"
    
    def chat(
        self,
        model: str,
        messages: List[Dict[str, str]],
        stream: bool = False,
        options: Optional[Dict[str, Any]] = None
    ) -> Generator[str, None, None]:
        """对话模式"""
        
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream
        }
        
        if options:
            payload["options"] = options
        
        try:
            response = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                stream=True,
                timeout=self._config.timeout
            )
            
            full_response = ""
            
            for line in response.iter_lines():
                if line:
                    data = json.loads(line)
                    message = data.get("message", {})
                    content = message.get("content", "")
                    full_response += content
                    
                    if stream:
                        yield content
            
            if not stream:
                yield full_response
                
        except Exception as e:
            logger.error(f"对话失败: {e}")
            yield f"错误: {str(e)}"
    
    def embeddings(self, model: str, prompt: str) -> Optional[List[float]]:
        """获取文本嵌入向量"""
        try:
            response = requests.post(
                f"{self.base_url}/api/embeddings",
                json={
                    "model": model,
                    "prompt": prompt
                },
                timeout=60
            )
            
            if response.status_code == 200:
                data = response.json()
                return data.get("embedding", [])
            
            return None
            
        except Exception as e:
            logger.error(f"获取嵌入向量失败: {e}")
            return None
    
    def get_model_info(self, model_name: str) -> Optional[Dict[str, Any]]:
        """获取模型详细信息"""
        try:
            response = requests.post(
                f"{self.base_url}/api/show",
                json={"name": model_name},
                timeout=30
            )
            
            if response.status_code == 200:
                return response.json()
            
            return None
            
        except Exception as e:
            logger.error(f"获取模型信息失败: {e}")
            return None
    
    def start_ollama_server(self) -> bool:
        """尝试启动 Ollama 服务"""
        try:
            if os.name == 'nt':
                subprocess.Popen(
                    ["ollama", "serve"],
                    creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
                )
            else:
                subprocess.Popen(
                    ["ollama", "serve"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )
            
            time.sleep(3)
            return self.is_available(force_check=True)
            
        except Exception as e:
            logger.error(f"启动 Ollama 服务失败: {e}")
            return False


ollama_client = OllamaClient()


RECOMMENDED_MODELS = [
    {"name": "llama3:8b", "size": "4.7GB", "description": "Meta Llama 3 8B - 通用对话模型"},
    {"name": "llama3:70b", "size": "40GB", "description": "Meta Llama 3 70B - 高性能模型"},
    {"name": "qwen2:7b", "size": "4.4GB", "description": "通义千问 2 7B - 中文优化"},
    {"name": "qwen2:72b", "size": "41GB", "description": "通义千问 2 72B - 高性能中文"},
    {"name": "deepseek-coder:6.7b", "size": "3.8GB", "description": "DeepSeek Coder - 代码生成"},
    {"name": "deepseek-v2:16b", "size": "9GB", "description": "DeepSeek V2 - 中文优化"},
    {"name": "gemma2:9b", "size": "5.4GB", "description": "Google Gemma 2 - 多任务"},
    {"name": "mistral:7b", "size": "4.1GB", "description": "Mistral 7B - 高效推理"},
    {"name": "codellama:7b", "size": "3.8GB", "description": "Code Llama - 代码生成"},
    {"name": "phi3:mini", "size": "2.2GB", "description": "Phi-3 Mini - 轻量级"},
]


def get_recommended_models() -> List[Dict[str, str]]:
    """获取推荐模型列表"""
    return RECOMMENDED_MODELS

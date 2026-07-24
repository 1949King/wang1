"""
统一配置管理模块 v1.0
====================
安全存储敏感数据 + 环境变量支持 + 配置验证
"""

import os
import json
import base64
import hashlib
import secrets
import platform
from pathlib import Path
from typing import Any, Dict, Optional, List
from dataclasses import dataclass, field, asdict
from datetime import datetime
import threading
import logging

logger = logging.getLogger(__name__)


@dataclass
class APIConfig:
    """API配置"""
    deepseek_api_key: str = ""
    doubao_api_key: str = ""
    dashscope_api_key: str = ""
    anthropic_api_key: str = ""
    zhipuai_api_key: str = ""
    openai_api_key: str = ""
    openai_base_url: str = ""
    
    def get_available_providers(self) -> List[str]:
        providers = []
        if self.deepseek_api_key:
            providers.append("deepseek")
        if self.doubao_api_key:
            providers.append("doubao")
        if self.dashscope_api_key:
            providers.append("dashscope")
        if self.anthropic_api_key:
            providers.append("anthropic")
        if self.zhipuai_api_key:
            providers.append("zhipuai")
        if self.openai_api_key:
            providers.append("openai")
        return providers


@dataclass
class PathConfig:
    """路径配置"""
    bgms_path: str = "./bgms"
    stickers_path: str = "./stickers"
    output_path: str = "./output"
    temp_path: str = "./temp"
    models_path: str = "./models"
    logs_path: str = "./logs"
    cache_path: str = "./cache"
    
    def ensure_directories(self):
        for attr in ['bgms_path', 'stickers_path', 'output_path', 'temp_path', 
                     'models_path', 'logs_path', 'cache_path']:
            path = Path(getattr(self, attr))
            path.mkdir(parents=True, exist_ok=True)


@dataclass
class ProcessingConfig:
    """处理配置"""
    whisper_model: str = "tiny"
    max_script_length: int = 1000
    device: str = "cpu"
    cpu_threads: int = 4
    max_parallel: int = 15
    max_retries: int = 3
    timeout: int = 300


@dataclass
class CacheConfig:
    """缓存配置"""
    enabled: bool = True
    max_memory_mb: int = 512
    max_disk_mb: int = 2048
    default_ttl: int = 300
    lru_max_items: int = 1000


@dataclass
class SecurityConfig:
    """安全配置"""
    password_min_length: int = 8
    password_require_upper: bool = True
    password_require_lower: bool = True
    password_require_digit: bool = True
    password_require_special: bool = False
    session_timeout: int = 3600
    max_login_attempts: int = 5
    lockout_duration: int = 300


class SecureStorage:
    """安全存储 - 加密敏感数据"""
    
    _instance: Optional['SecureStorage'] = None
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
        
        self._key = self._derive_key()
        self._storage_path = self._get_storage_path()
        self._secrets: Dict[str, str] = {}
        self._load_secrets()
    
    def _get_storage_path(self) -> Path:
        if platform.system() == "Windows":
            base = Path(os.environ.get("APPDATA", Path.home()))
        elif platform.system() == "Darwin":
            base = Path.home() / "Library" / "Application Support"
        else:
            base = Path.home() / ".config"
        
        storage_dir = base / "AI短剧编辑器" / "secure"
        storage_dir.mkdir(parents=True, exist_ok=True)
        return storage_dir / "secrets.enc"
    
    def _derive_key(self) -> bytes:
        machine_id = self._get_machine_id()
        return hashlib.pbkdf2_hmac(
            'sha256',
            machine_id.encode(),
            b'ai_drama_editor_salt_v1',
            100000,
            dklen=32
        )
    
    def _get_machine_id(self) -> str:
        components = [
            platform.node(),
            platform.system(),
            platform.machine(),
            str(os.cpu_count() or 0),
        ]
        
        try:
            if platform.system() == "Windows":
                import subprocess
                result = subprocess.run(
                    ["wmic", "csproduct", "get", "UUID"],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    uuid_line = [l.strip() for l in result.stdout.split('\n') if l.strip() and l.strip() != 'UUID']
                    if uuid_line:
                        components.append(uuid_line[0])
        except Exception:
            pass
            pass
        
        return hashlib.sha256('|'.join(components).encode()).hexdigest()[:32]
    
    def _encrypt(self, data: str) -> bytes:
        nonce = secrets.token_bytes(16)
        key = self._key
        
        cipher = bytearray()
        for i, byte in enumerate(data.encode()):
            cipher.append(byte ^ key[i % len(key)])
        
        return base64.b64encode(nonce + bytes(cipher))
    
    def _decrypt(self, data: bytes) -> str:
        try:
            decoded = base64.b64decode(data)
            nonce = decoded[:16]
            cipher = decoded[16:]
            key = self._key
            
            plain = bytearray()
            for i, byte in enumerate(cipher):
                plain.append(byte ^ key[i % len(key)])
            
            return plain.decode()
        except Exception as e:
            logger.error(f"解密失败: {e}")
            return ""
    
    def _load_secrets(self):
        if self._storage_path.exists():
            try:
                with open(self._storage_path, 'rb') as f:
                    encrypted = f.read()
                decrypted = self._decrypt(encrypted)
                self._secrets = json.loads(decrypted) if decrypted else {}
            except Exception as e:
                logger.warning(f"加载密钥失败: {e}")
                self._secrets = {}
    
    def _save_secrets(self):
        try:
            encrypted = self._encrypt(json.dumps(self._secrets))
            with open(self._storage_path, 'wb') as f:
                f.write(encrypted)
        except Exception as e:
            logger.error(f"保存密钥失败: {e}")
    
    def get(self, key: str, default: str = "") -> str:
        return self._secrets.get(key, default)
    
    def set(self, key: str, value: str):
        self._secrets[key] = value
        self._save_secrets()
    
    def delete(self, key: str):
        if key in self._secrets:
            del self._secrets[key]
            self._save_secrets()
    
    def clear(self):
        self._secrets.clear()
        self._save_secrets()


class ConfigManager:
    """统一配置管理器"""
    
    _instance: Optional['ConfigManager'] = None
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
        
        self._config_path = self._get_config_path()
        self._secure_storage = SecureStorage()
        
        self.api = APIConfig()
        self.paths = PathConfig()
        self.processing = ProcessingConfig()
        self.cache = CacheConfig()
        self.security = SecurityConfig()
        
        self._load_config()
        self._load_from_env()
        self.paths.ensure_directories()
    
    def _get_config_path(self) -> Path:
        if platform.system() == "Windows":
            base = Path(os.environ.get("APPDATA", Path.home()))
        elif platform.system() == "Darwin":
            base = Path.home() / "Library" / "Application Support"
        else:
            base = Path.home() / ".config"
        
        return base / "AI短剧编辑器" / "config.json"
    
    def _load_config(self):
        if self._config_path.exists():
            try:
                with open(self._config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                if 'api' in data:
                    for key, value in data['api'].items():
                        if hasattr(self.api, key):
                            setattr(self.api, key, value)
                
                if 'paths' in data:
                    for key, value in data['paths'].items():
                        if hasattr(self.paths, key):
                            setattr(self.paths, key, value)
                
                if 'processing' in data:
                    for key, value in data['processing'].items():
                        if hasattr(self.processing, key):
                            setattr(self.processing, key, value)
                
                if 'cache' in data:
                    for key, value in data['cache'].items():
                        if hasattr(self.cache, key):
                            setattr(self.cache, key, value)
                
                if 'security' in data:
                    for key, value in data['security'].items():
                        if hasattr(self.security, key):
                            setattr(self.security, key, value)
                
                logger.info("配置加载成功")
            except Exception as e:
                logger.warning(f"加载配置失败: {e}")
    
    def _load_from_env(self):
        env_mappings = {
            'DEEPSEEK_API_KEY': ('api', 'deepseek_api_key'),
            'DOUBAO_API_KEY': ('api', 'doubao_api_key'),
            'DASHSCOPE_API_KEY': ('api', 'dashscope_api_key'),
            'ANTHROPIC_API_KEY': ('api', 'anthropic_api_key'),
            'ZHIPUAI_API_KEY': ('api', 'zhipuai_api_key'),
            'OPENAI_API_KEY': ('api', 'openai_api_key'),
            'OPENAI_BASE_URL': ('api', 'openai_base_url'),
            'CPU_THREADS': ('processing', 'cpu_threads'),
            'MAX_PARALLEL': ('processing', 'max_parallel'),
        }
        
        for env_key, (section, attr) in env_mappings.items():
            value = os.getenv(env_key)
            if value:
                obj = getattr(self, section)
                if hasattr(obj, attr):
                    current = getattr(obj, attr)
                    if isinstance(current, int):
                        try:
                            setattr(obj, attr, int(value))
                        except ValueError:
                            pass
                    else:
                        setattr(obj, attr, value)
        
        for key in ['deepseek_api_key', 'doubao_api_key', 'dashscope_api_key',
                    'anthropic_api_key', 'zhipuai_api_key', 'openai_api_key']:
            secure_value = self._secure_storage.get(key)
            if secure_value:
                setattr(self.api, key, secure_value)
    
    def save_config(self):
        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            
            data = {
                'api': asdict(self.api),
                'paths': asdict(self.paths),
                'processing': asdict(self.processing),
                'cache': asdict(self.cache),
                'security': asdict(self.security),
            }
            
            sensitive_keys = ['deepseek_api_key', 'doubao_api_key', 'dashscope_api_key',
                            'anthropic_api_key', 'zhipuai_api_key', 'openai_api_key']
            
            for key in sensitive_keys:
                if data['api'].get(key):
                    self._secure_storage.set(key, data['api'][key])
                    data['api'][key] = '***SECURE***'
            
            with open(self._config_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            logger.info("配置保存成功")
        except Exception as e:
            logger.error(f"保存配置失败: {e}")
    
    def get_api_key(self, provider: str) -> str:
        key_map = {
            'deepseek': self.api.deepseek_api_key,
            'doubao': self.api.doubao_api_key,
            'dashscope': self.api.dashscope_api_key,
            'anthropic': self.api.anthropic_api_key,
            'zhipuai': self.api.zhipuai_api_key,
            'openai': self.api.openai_api_key,
        }
        return key_map.get(provider, "")
    
    def set_api_key(self, provider: str, key: str):
        key_map = {
            'deepseek': 'deepseek_api_key',
            'doubao': 'doubao_api_key',
            'dashscope': 'dashscope_api_key',
            'anthropic': 'anthropic_api_key',
            'zhipuai': 'zhipuai_api_key',
            'openai': 'openai_api_key',
        }
        if provider in key_map:
            setattr(self.api, key_map[provider], key)
            self._secure_storage.set(key_map[provider], key)
            self.save_config()
    
    def validate(self) -> List[str]:
        errors = []
        
        if self.processing.cpu_threads < 1:
            errors.append("CPU线程数必须大于0")
        
        if self.processing.max_parallel < 1:
            errors.append("最大并行数必须大于0")
        
        if self.cache.max_memory_mb < 64:
            errors.append("缓存内存至少64MB")
        
        if self.security.password_min_length < 6:
            errors.append("密码最小长度至少6位")
        
        return errors
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'api': {k: '***' if 'key' in k else v for k, v in asdict(self.api).items()},
            'paths': asdict(self.paths),
            'processing': asdict(self.processing),
            'cache': asdict(self.cache),
            'security': asdict(self.security),
        }


config = ConfigManager()

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
from dataclasses import dataclass, asdict
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
    """安全存储 - 加密敏感数据

    V4.46.1（2026-10-20 安全刀）：加密从自研 XOR 升级为 Fernet（AES-128-CBC+HMAC，
    cryptography 库，requirements.txt 已声明）。文件带 `sgv2:` 前缀标记新格式；
    旧 XOR 文件**透明迁移**（读出成功后重写为新格式）。解密失败不再静默置空：
    损坏文件改名保留（.corrupt-<ts>）+ 明确 error 日志，提示重填密钥。
    cryptography 缺失时回退旧 XOR（记录 warning，不假装更强）。
    """

    _ENC_MARKER = b"sgv2:"

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
        
        # 2026-10-23：**不再**用机器码派生钥匙写库（XOR 写入路由已弃用）。
        # `_key` 仍赋值为「现行机器码」的结果，仅用于：①读取历史 XOR 文件时
        # 试钥匙（`_legacy_key_candidates` 的首候选就是它）；②测试手工构造旧格式样本。
        self._key = self._derive_key()
        self._storage_path = self._get_storage_path()
        self._fernet_cached = False
        self._fernet = None
        self._secrets: Dict[str, str] = {}
        self._load_secrets()

    def _get_fernet(self):
        """惰性取用户级 Fernet（与 secure_store 同一把钥匙）；不可用返回 None。"""
        if not self._fernet_cached:
            self._fernet_cached = True
            try:
                from app.core.secure_store import get_fernet
            except ImportError:
                try:
                    from core.secure_store import get_fernet  # type: ignore
                except ImportError:
                    get_fernet = None  # type: ignore
            if get_fernet is not None:
                try:
                    self._fernet = get_fernet()
                except Exception as e:
                    logger.warning(f"获取 Fernet 密钥失败: {e}")
        return self._fernet
    
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
    
    def _machine_id_from(self, components: List[str]) -> str:
        """由部件列表算机器码（纯函数，便于多候选共存）。"""
        return hashlib.sha256('|'.join(components).encode()).hexdigest()[:32]

    def _machine_components(self, *, with_uuid: bool) -> List[str]:
        components = [
            platform.node(),
            platform.system(),
            platform.machine(),
            str(os.cpu_count() or 0),
        ]
        if not with_uuid:
            return components
        try:
            if platform.system() == "Windows":
                # ★ A-14（2026-10-05）：改用统一 WMI 助手（CIM 优先 / wmic 兜底）。
                #   ⚠️ **取值形状必须逐字不变** —— 这个 UUID 参与机器码 → 加密密钥派生，
                #   变了会让用户**已保存的加密配置解不开**。`machine_uuid()` 返回的正是
                #   旧实现（wmic 输出过滤掉表头后那一行）的同一个值。
                from app.core.win_query import machine_uuid

                uuid = machine_uuid()
                if uuid:
                    components.append(uuid)
        except Exception as e:
            logger.debug(f"[ConfigManager] 获取机器UUID失败 (Windows): {e}")
        return components

    def _get_machine_id(self) -> str:
        return self._machine_id_from(self._machine_components(with_uuid=True))

    def _legacy_key_candidates(self) -> List[bytes]:
        """旧 XOR 格式的**密钥候选**（新→旧）。

        为什么需要多候选：机器码参与 PBKDF2，而 `_get_machine_id()` 在 A-14
        （2026-10-05）之后追加了 WMI UUID 部件。此前版本写下的旧 XOR 文件是
        「无 UUID」机器码加密的 ⇒ 用现行单值永远解不开，每次启动都误判为
        「文件损坏」并隔离。此处把两种算法都列出来逐次尝试：
          ① 现行（含 UUID）—— 与 `_key` 同一个值，先试，绝不改变新文件行为
          ② 历史（不含 UUID）—— 只为读回 A-14 之前写下的文件
        只作用于**旧 XOR 分支**；sgv2 走 Fernet，与机器码无关。
        """
        seen: List[bytes] = []
        candidates = [
            self._machine_id_from(self._machine_components(with_uuid=True)),
            self._machine_id_from(self._machine_components(with_uuid=False)),
        ]
        for machine_id in candidates:
            key = hashlib.pbkdf2_hmac(
                'sha256',
                machine_id.encode(),
                b'ai_drama_editor_salt_v1',
                100000,
                dklen=32
            )
            if key not in seen:
                seen.append(key)
        return seen

    def _encrypt(self, data: str) -> bytes:
        """加密并落盘格式 = `sgv2:` + Fernet。

        2026-10-23 起**只有这一条写入路由**：旧 XOR 分支已弃用（不再写 XOR），
        因为 XOR 的钥匙来自机器码，改机器名/换硬件即永久失效。Fernet 钥匙
        改由 DPAPI 守护的纯随机值提供（见 `secure_store.py` / `dpapi.py`），
        与硬件指纹解耦。Fernet 不可用时返回空字节，由 `_save_secrets` 判失败
        —— 绝不回退 XOR 写盘（宁可保存失败并如实报错，也不产生下一个解不开的库）。
        """
        f = self._get_fernet()
        if f is None:
            logger.error(
                "Fernet 不可用（cryptography 缺失或密钥不可用）：拒绝以旧 XOR 格式写盘。"
                "请安装 cryptography 后重试保存。"
            )
            return b""
        token = f.encrypt(data.encode("utf-8"))
        return self._ENC_MARKER + base64.b64encode(token)

    def _decrypt(self, data: bytes) -> str:
        try:
            if data.startswith(self._ENC_MARKER):
                f = self._get_fernet()
                if f is None:
                    logger.error("存储已是 Fernet 格式但密钥不可用：请检查 cryptography 安装与 secret.key")
                    return ""
                token = base64.b64decode(data[len(self._ENC_MARKER):])
                return f.decrypt(token).decode("utf-8")
            # 旧 XOR 格式（sgv2 之前）：机器码一致才能解开。
            # 逐候选尝试（见 _legacy_key_candidates）——A-14 前后的机器码不同，
            # 只认现行单值会把旧文件误判成“损坏”而隔离。
            decoded = base64.b64decode(data)
            cipher = decoded[16:]  # 前 16 字节为旧格式 nonce（XOR 模式未参与密钥流，忽略）
            last_error: Optional[Exception] = None
            for key in self._legacy_key_candidates():
                try:
                    plain = bytearray()
                    for i, byte in enumerate(cipher):
                        plain.append(byte ^ key[i % len(key)])
                    return plain.decode()
                except Exception as e:  # 候选不对 ⇒ 解出乱码，换下一个
                    last_error = e
                    continue
            raise last_error or ValueError("旧格式解密无可用密钥候选")
        except Exception as e:
            logger.error(f"解密失败: {e}")
            return ""

    def _quarantine_corrupt(self) -> None:
        """解密失败：损坏文件改名保留（可人工找回），不再静默吞掉。

        并发安全：`run_all_checks` 的 103 项每项都会新建一次（单例已重置），
        同一文件可能被判定多轮。先 `os.replace` 抢名字，抢到的人负责改名；
        `FileNotFoundError` 说明别人已隔离，静默返回即正确结论（不是失败）。
        """
        try:
            if not self._storage_path.exists() or self._storage_path.stat().st_size == 0:
                return
            ts = datetime.now().strftime("%Y%m%d%H%M%S")
            bad = self._storage_path.with_name(
                f"{self._storage_path.stem}.corrupt-{ts}{self._storage_path.suffix}"
            )
            os.replace(self._storage_path, bad)
            logger.error(
                "密钥存储无法解密，已隔离到 %s（本机指纹变化或文件损坏；"
                "请到模型管理重新填写各渠道 Key）",
                bad,
            )
        except FileNotFoundError:
            # 并发下已被另一方隔离 ⇒ 目标状态已达成。记 debug 留痕，不静默吞。
            logger.debug("密钥库已被其他调用方隔离（目标状态已达成）: %s", self._storage_path)
        except OSError as e:
            logger.error(f"隔离损坏密钥文件失败: {e}")

    def _load_secrets(self):
        if self._storage_path.exists():
            try:
                with open(self._storage_path, "rb") as f:
                    encrypted = f.read()
            except OSError as e:
                logger.error(f"读取密钥存储失败: {e}")
                self._secrets = {}
                return
            was_legacy = not encrypted.startswith(self._ENC_MARKER)
            decrypted = self._decrypt(encrypted)
            if not decrypted:
                self._quarantine_corrupt()
                self._secrets = {}
                return
            try:
                self._secrets = json.loads(decrypted)
            except Exception as e:
                logger.error(f"密钥存储 JSON 解析失败: {e}（文件已隔离保留）")
                self._quarantine_corrupt()
                self._secrets = {}
                return
            # 透明迁移：旧 XOR 文件 + Fernet 可用 ⇒ 立即重写为 sgv2 新格式
            if was_legacy and self._get_fernet() is not None:
                self._save_secrets()

    def _save_secrets(self) -> bool:
        """落盘密钥库；成功 True / 失败 False（不再静默吞）。

        调用方（cloud_api.save_configs）据此决定能否写 "encrypted" 标记 ——
        写失败还标 encrypted = 下次启动读到空 = 用户密钥「凭空消失」。

        空密文即失败：`_encrypt` 在 Fernet 不可用时返回 `b""`（拒绝写 XOR），
        此处必须拦下，否则会把 0 字节文件落盘 —— 那是一个必然解不开的库。
        """
        try:
            encrypted = self._encrypt(json.dumps(self._secrets))
            if not encrypted:
                logger.error("未生成密文（Fernet 不可用），本次保存作废；磁盘原库保持不变")
                return False
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._storage_path.with_name(self._storage_path.name + ".tmp")
            with open(tmp, "wb") as f:
                f.write(encrypted)
            os.replace(tmp, self._storage_path)
            return True
        except Exception as e:
            logger.error(f"保存密钥失败: {e}")
            return False

    def get(self, key: str, default: str = "") -> str:
        return self._secrets.get(key, default)
    
    def set(self, key: str, value: str) -> bool:
        """写入并落盘；返回是否真的持久化成功（False=内存有、磁盘无）。"""
        self._secrets[key] = value
        return self._save_secrets()
    
    def delete(self, key: str) -> bool:
        if key in self._secrets:
            del self._secrets[key]
            return self._save_secrets()
        return True
    
    def clear(self) -> bool:
        self._secrets.clear()
        return self._save_secrets()


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
                        except ValueError as e:
                            logger.debug(f"[ConfigManager] 设置环境变量 {env_key} 失败: {e}")
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
                    # 与 cloud_api.save_configs 同纪律：写盘失败不标 SECURE，
                    # 否则下次启动读到标记→取回空→密钥凭空消失。
                    if self._secure_storage.set(key, data['api'][key]):
                        data['api'][key] = '***SECURE***'
                    else:
                        logger.error(
                            "密钥 %s 未能持久化，config.json 保留原值（重启后需重填）", key
                        )
            
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

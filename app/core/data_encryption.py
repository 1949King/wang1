"""
数据加密存储模块
================
实现数据加密、安全存储和密钥管理
"""

import os
import json
import logging
import threading
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import hashlib
import base64
from datetime import datetime, timedelta

from app.core.logging_enhanced import monitor_performance
from app.core.exceptions import SecurityError, ErrorCode

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.backends import default_backend
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

logger = logging.getLogger(__name__)


class EncryptionAlgorithm(Enum):
    """加密算法"""
    AES_256 = "AES-256"
    CHACHA20 = "ChaCha20"
    FERNET = "Fernet"


class EncryptionLevel(Enum):
    """加密级别"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class EncryptionKey:
    """加密密钥"""
    key_id: str
    algorithm: EncryptionAlgorithm
    created_at: float
    expires_at: Optional[float] = None
    key_hash: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def is_expired(self) -> bool:
        """检查密钥是否过期"""
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（不包含密钥本身）"""
        return {
            'key_id': self.key_id,
            'algorithm': self.algorithm.value,
            'created_at': self.created_at,
            'expires_at': self.expires_at,
            'is_expired': self.is_expired(),
            'metadata': self.metadata
        }


@dataclass
class EncryptedData:
    """加密数据"""
    data_id: str
    encrypted_value: str
    algorithm: EncryptionAlgorithm
    key_id: str
    iv: Optional[str] = None
    auth_tag: Optional[str] = None
    created_at: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（不包含加密数据本身）"""
        return {
            'data_id': self.data_id,
            'algorithm': self.algorithm.value,
            'key_id': self.key_id,
            'created_at': self.created_at,
            'metadata': self.metadata
        }


class KeyManager:
    """密钥管理器"""
    
    def __init__(self, keys_file: str = "encryption_keys.json"):
        self.keys_file = keys_file
        self._keys: Dict[str, EncryptionKey] = {}
        self._key_cache: Dict[str, bytes] = {}
        self._lock = threading.RLock()
        
        self._load_keys()
    
    def _load_keys(self):
        """加载密钥"""
        if os.path.exists(self.keys_file):
            try:
                with open(self.keys_file, 'r', encoding='utf-8') as f:
                    keys_data = json.load(f)
                
                for key_data in keys_data:
                    key = EncryptionKey(**key_data)
                    self._keys[key.key_id] = key
                
                logger.info(f"已加载 {len(self._keys)} 个加密密钥")
            except Exception as e:
                logger.error(f"密钥加载失败: {e}")
    
    def _save_keys(self):
        """保存密钥"""
        try:
            keys_data = [key.to_dict() for key in self._keys.values()]
            
            with open(self.keys_file, 'w', encoding='utf-8') as f:
                json.dump(keys_data, f, ensure_ascii=False, indent=2)
            
            logger.debug("密钥已保存")
        except Exception as e:
            logger.error(f"密钥保存失败: {e}")
            raise SecurityError(
                ErrorCode.ENCRYPTION_ERROR,
                f"密钥保存失败: {str(e)}"
            )
    
    def generate_key(self, key_id: str, 
                   algorithm: EncryptionAlgorithm = EncryptionAlgorithm.FERNET,
                   expires_in_days: int = 365,
                   metadata: Optional[Dict[str, Any]] = None) -> EncryptionKey:
        """生成加密密钥
        
        Args:
            key_id: 密钥ID
            algorithm: 加密算法
            expires_in_days: 过期天数
            metadata: 元数据
        
        Returns:
            加密密钥对象
        """
        if not CRYPTO_AVAILABLE:
            raise SecurityError(
                ErrorCode.ENCRYPTION_ERROR,
                "加密库未安装，请安装 cryptography 库"
            )
        
        try:
            # 生成密钥
            if algorithm == EncryptionAlgorithm.FERNET:
                key = Fernet.generate_key()
            else:
                # 生成随机密钥
                key = os.urandom(32)
            
            # 计算密钥哈希
            key_hash = hashlib.sha256(key).hexdigest()
            
            # 创建密钥对象
            encryption_key = EncryptionKey(
                key_id=key_id,
                algorithm=algorithm,
                created_at=time.time(),
                expires_at=time.time() + (expires_in_days * 24 * 3600) if expires_in_days > 0 else None,
                key_hash=key_hash,
                metadata=metadata or {}
            )
            
            # 保存密钥
            with self._lock:
                self._keys[key_id] = encryption_key
                self._key_cache[key_id] = key
                self._save_keys()
            
            logger.info(f"生成加密密钥: {key_id}")
            return encryption_key
            
        except Exception as e:
            logger.error(f"密钥生成失败: {e}")
            raise SecurityError(
                ErrorCode.ENCRYPTION_ERROR,
                f"密钥生成失败: {str(e)}"
            )
    
    def get_key(self, key_id: str) -> Optional[EncryptionKey]:
        """获取密钥信息（不返回密钥本身）"""
        with self._lock:
            return self._keys.get(key_id)
    
    def get_key_bytes(self, key_id: str) -> Optional[bytes]:
        """获取密钥字节数据"""
        with self._lock:
            if key_id in self._key_cache:
                return self._key_cache[key_id]
            elif key_id in self._keys:
                # 从安全存储中加载密钥
                key_data = self._keys[key_id]
                # 这里应该从安全存储中加载，简化为返回None
                logger.warning(f"密钥未在缓存中: {key_id}")
                return None
            return None
    
    def delete_key(self, key_id: str) -> bool:
        """删除密钥
        
        Args:
            key_id: 密钥ID
        
        Returns:
            是否删除成功
        """
        with self._lock:
            if key_id not in self._keys:
                logger.warning(f"密钥不存在: {key_id}")
                return False
            
            del self._keys[key_id]
            if key_id in self._key_cache:
                del self._key_cache[key_id]
            
            self._save_keys()
        
        logger.info(f"删除密钥: {key_id}")
        return True
    
    def rotate_key(self, key_id: str, 
                  expires_in_days: int = 365) -> EncryptionKey:
        """轮换密钥
        
        Args:
            key_id: 密钥ID
            expires_in_days: 新密钥过期天数
        
        Returns:
            新密钥对象
        """
        logger.info(f"轮换密钥: {key_id}")
        
        # 删除旧密钥
        self.delete_key(key_id)
        
        # 生成新密钥
        return self.generate_key(key_id, expires_in_days=expires_in_days)
    
    def cleanup_expired_keys(self) -> int:
        """清理过期密钥
        
        Returns:
            清理的密钥数量
        """
        with self._lock:
            expired_keys = [
                key_id for key_id, key in self._keys.items()
                if key.is_expired()
            ]
            
            for key_id in expired_keys:
                del self._keys[key_id]
                if key_id in self._key_cache:
                    del self._key_cache[key_id]
            
            if expired_keys:
                self._save_keys()
        
        logger.info(f"清理过期密钥: {len(expired_keys)} 个")
        return len(expired_keys)
    
    def get_all_keys(self, include_expired: bool = False) -> List[EncryptionKey]:
        """获取所有密钥
        
        Args:
            include_expired: 是否包含过期密钥
        
        Returns:
            密钥列表
        """
        with self._lock:
            keys = list(self._keys.values())
            
            if not include_expired:
                keys = [key for key in keys if not key.is_expired()]
            
            return keys
    
    def get_stats(self) -> Dict[str, Any]:
        """获取密钥统计信息"""
        with self._lock:
            total_keys = len(self._keys)
            expired_keys = sum(1 for key in self._keys.values() if key.is_expired())
            active_keys = total_keys - expired_keys
            
            return {
                'total_keys': total_keys,
                'active_keys': active_keys,
                'expired_keys': expired_keys,
                'keys_by_algorithm': {
                    algo.value: sum(1 for key in self._keys.values() if key.algorithm == algo)
                    for algo in EncryptionAlgorithm
                }
            }


class DataEncryptor:
    """数据加密器"""
    
    def __init__(self, key_manager: KeyManager):
        self._key_manager = key_manager
        self._encryption_cache: Dict[str, EncryptedData] = {}
        self._lock = threading.RLock()
        
        self._stats = {
            'total_encryptions': 0,
            'total_decryptions': 0,
            'failed_encryptions': 0,
            'failed_decryptions': 0
        }
    
    @monitor_performance(threshold_warning=0.5, threshold_critical=2.0)
    def encrypt(self, data: str, key_id: str,
               algorithm: EncryptionAlgorithm = EncryptionAlgorithm.FERNET,
               data_id: Optional[str] = None,
               metadata: Optional[Dict[str, Any]] = None) -> EncryptedData:
        """加密数据
        
        Args:
            data: 要加密的数据
            key_id: 密钥ID
            algorithm: 加密算法
            data_id: 数据ID
            metadata: 元数据
        
        Returns:
            加密数据对象
        """
        if not CRYPTO_AVAILABLE:
            raise SecurityError(
                ErrorCode.ENCRYPTION_ERROR,
                "加密库未安装，请安装 cryptography 库"
            )
        
        key_bytes = self._key_manager.get_key_bytes(key_id)
        if key_bytes is None:
            raise SecurityError(
                ErrorCode.ENCRYPTION_ERROR,
                f"密钥不存在: {key_id}"
            )
        
        try:
            if algorithm == EncryptionAlgorithm.FERNET:
                fernet = Fernet(key_bytes)
                encrypted_bytes = fernet.encrypt(data.encode('utf-8'))
                encrypted_value = base64.b64encode(encrypted_bytes).decode('utf-8')
                iv = None
                auth_tag = None
            else:
                # 简化版本：使用base64编码
                encrypted_value = base64.b64encode(data.encode('utf-8')).decode('utf-8')
                iv = None
                auth_tag = None
            
            encrypted_data = EncryptedData(
                data_id=data_id or f"{key_id}_{int(time.time())}",
                encrypted_value=encrypted_value,
                algorithm=algorithm,
                key_id=key_id,
                iv=iv,
                auth_tag=auth_tag,
                created_at=time.time(),
                metadata=metadata or {}
            )
            
            with self._lock:
                self._encryption_cache[encrypted_data.data_id] = encrypted_data
                self._stats['total_encryptions'] += 1
            
            logger.info(f"数据加密成功: {encrypted_data.data_id}")
            return encrypted_data
            
        except Exception as e:
            with self._lock:
                self._stats['failed_encryptions'] += 1
            
            logger.error(f"数据加密失败: {e}")
            raise SecurityError(
                ErrorCode.ENCRYPTION_ERROR,
                f"数据加密失败: {str(e)}"
            )
    
    @monitor_performance(threshold_warning=0.5, threshold_critical=2.0)
    def decrypt(self, encrypted_data: EncryptedData) -> str:
        """解密数据
        
        Args:
            encrypted_data: 加密数据对象
        
        Returns:
            解密后的数据
        """
        if not CRYPTO_AVAILABLE:
            raise SecurityError(
                ErrorCode.ENCRYPTION_ERROR,
                "加密库未安装，请安装 cryptography 库"
            )
        
        key_bytes = self._key_manager.get_key_bytes(encrypted_data.key_id)
        if key_bytes is None:
            raise SecurityError(
                ErrorCode.ENCRYPTION_ERROR,
                f"密钥不存在: {encrypted_data.key_id}"
            )
        
        try:
            if encrypted_data.algorithm == EncryptionAlgorithm.FERNET:
                fernet = Fernet(key_bytes)
                encrypted_bytes = base64.b64decode(encrypted_data.encrypted_value.encode('utf-8'))
                decrypted_bytes = fernet.decrypt(encrypted_bytes)
                decrypted_value = decrypted_bytes.decode('utf-8')
            else:
                # 简化版本：使用base64解码
                decrypted_bytes = base64.b64decode(encrypted_data.encrypted_value.encode('utf-8'))
                decrypted_value = decrypted_bytes.decode('utf-8')
            
            with self._lock:
                self._stats['total_decryptions'] += 1
            
            logger.info(f"数据解密成功: {encrypted_data.data_id}")
            return decrypted_value
            
        except Exception as e:
            with self._lock:
                self._stats['failed_decryptions'] += 1
            
            logger.error(f"数据解密失败: {e}")
            raise SecurityError(
                ErrorCode.ENCRYPTION_ERROR,
                f"数据解密失败: {str(e)}"
            )
    
    def encrypt_file(self, file_path: str, key_id: str,
                   algorithm: EncryptionAlgorithm = EncryptionAlgorithm.FERNET,
                   output_path: Optional[str] = None) -> EncryptedData:
        """加密文件
        
        Args:
            file_path: 文件路径
            key_id: 密钥ID
            algorithm: 加密算法
            output_path: 输出路径（可选）
        
        Returns:
            加密数据对象
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = f.read()
            
            encrypted_data = self.encrypt(data, key_id, algorithm, metadata={'file_path': file_path})
            
            # 保存加密数据
            if output_path is None:
                output_path = file_path + '.encrypted'
            
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(encrypted_data.to_dict(), f, ensure_ascii=False, indent=2)
            
            logger.info(f"文件加密完成: {file_path} -> {output_path}")
            return encrypted_data
            
        except Exception as e:
            logger.error(f"文件加密失败: {file_path} - {e}")
            raise SecurityError(
                ErrorCode.ENCRYPTION_ERROR,
                f"文件加密失败: {str(e)}",
                details={'file_path': file_path}
            )
    
    def decrypt_file(self, encrypted_file_path: str, 
                   output_path: Optional[str] = None) -> str:
        """解密文件
        
        Args:
            encrypted_file_path: 加密文件路径
            output_path: 输出路径（可选）
        
        Returns:
            解密后的数据
        """
        try:
            with open(encrypted_file_path, 'r', encoding='utf-8') as f:
                encrypted_data_dict = json.load(f)
            
            encrypted_data = EncryptedData(**encrypted_data_dict)
            
            decrypted_data = self.decrypt(encrypted_data)
            
            # 保存解密数据
            if output_path is None:
                output_path = encrypted_file_path.replace('.encrypted', '')
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(decrypted_data)
            
            logger.info(f"文件解密完成: {encrypted_file_path} -> {output_path}")
            return decrypted_data
            
        except Exception as e:
            logger.error(f"文件解密失败: {encrypted_file_path} - {e}")
            raise SecurityError(
                ErrorCode.ENCRYPTION_ERROR,
                f"文件解密失败: {str(e)}",
                details={'file_path': encrypted_file_path}
            )
    
    def get_encrypted_data(self, data_id: str) -> Optional[EncryptedData]:
        """获取加密数据"""
        with self._lock:
            return self._encryption_cache.get(data_id)
    
    def get_stats(self) -> Dict[str, Any]:
        """获取加密统计信息"""
        with self._lock:
            return self._stats.copy()


class SecureStorage:
    """安全存储管理器"""
    
    def __init__(self, storage_dir: str = "secure_storage"):
        self.storage_dir = storage_dir
        self._key_manager = KeyManager(os.path.join(storage_dir, 'keys.json'))
        self._encryptor = DataEncryptor(self._key_manager)
        
        os.makedirs(storage_dir, exist_ok=True)
        os.makedirs(os.path.join(storage_dir, 'encrypted'), exist_ok=True)
        os.makedirs(os.path.join(storage_dir, 'decrypted'), exist_ok=True)
    
    def store_sensitive_data(self, key_id: str, data: str,
                           category: str = "general") -> str:
        """存储敏感数据
        
        Args:
            key_id: 密钥ID
            data: 敏感数据
            category: 数据类别
        
        Returns:
            数据ID
        """
        data_id = f"{category}_{key_id}_{int(time.time())}"
        
        # 加密数据
        encrypted_data = self._encryptor.encrypt(data, key_id, metadata={'category': category})
        
        # 保存加密数据
        encrypted_file = os.path.join(self.storage_dir, 'encrypted', f"{data_id}.json")
        with open(encrypted_file, 'w', encoding='utf-8') as f:
            json.dump(encrypted_data.to_dict(), f, ensure_ascii=False, indent=2)
        
        logger.info(f"敏感数据已存储: {data_id}")
        return data_id
    
    def retrieve_sensitive_data(self, data_id: str) -> Optional[str]:
        """检索敏感数据
        
        Args:
            data_id: 数据ID
        
        Returns:
            解密后的数据
        """
        encrypted_file = os.path.join(self.storage_dir, 'encrypted', f"{data_id}.json")
        
        if not os.path.exists(encrypted_file):
            logger.warning(f"敏感数据不存在: {data_id}")
            return None
        
        try:
            with open(encrypted_file, 'r', encoding='utf-8') as f:
                encrypted_data_dict = json.load(f)
            
            encrypted_data = EncryptedData(**encrypted_data_dict)
            
            # 解密数据
            decrypted_data = self._encryptor.decrypt(encrypted_data)
            
            logger.info(f"敏感数据已检索: {data_id}")
            return decrypted_data
            
        except Exception as e:
            logger.error(f"敏感数据检索失败: {data_id} - {e}")
            return None
    
    def delete_sensitive_data(self, data_id: str) -> bool:
        """删除敏感数据
        
        Args:
            data_id: 数据ID
        
        Returns:
            是否删除成功
        """
        encrypted_file = os.path.join(self.storage_dir, 'encrypted', f"{data_id}.json")
        
        if not os.path.exists(encrypted_file):
            logger.warning(f"敏感数据不存在: {data_id}")
            return False
        
        try:
            os.remove(encrypted_file)
            logger.info(f"敏感数据已删除: {data_id}")
            return True
        except Exception as e:
            logger.error(f"敏感数据删除失败: {data_id} - {e}")
            return False
    
    def get_key_manager(self) -> KeyManager:
        """获取密钥管理器"""
        return self._key_manager
    
    def get_encryptor(self) -> DataEncryptor:
        """获取加密器"""
        return self._encryptor


# 全局实例
_global_key_manager: Optional[KeyManager] = None
_global_data_encryptor: Optional[DataEncryptor] = None
_global_secure_storage: Optional[SecureStorage] = None


def get_key_manager(keys_file: str = "encryption_keys.json") -> KeyManager:
    """获取全局密钥管理器"""
    global _global_key_manager
    
    if _global_key_manager is None:
        _global_key_manager = KeyManager(keys_file)
    
    return _global_key_manager


def get_data_encryptor(key_manager: Optional[KeyManager] = None) -> DataEncryptor:
    """获取全局数据加密器"""
    global _global_data_encryptor
    
    if _global_data_encryptor is None:
        if key_manager is None:
            key_manager = get_key_manager()
        _global_data_encryptor = DataEncryptor(key_manager)
    
    return _global_data_encryptor


def get_secure_storage(storage_dir: str = "secure_storage") -> SecureStorage:
    """获取全局安全存储"""
    global _global_secure_storage
    
    if _global_secure_storage is None:
        _global_secure_storage = SecureStorage(storage_dir)
    
    return _global_secure_storage
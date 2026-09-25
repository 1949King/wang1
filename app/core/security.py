"""
文件路径安全检查模块
====================
提供全面的文件路径安全检查和防护功能
"""

import os
import re
import stat
import hashlib
import time
import random
import secrets
from typing import Optional, List, Dict, Any, Set, Tuple
from dataclasses import dataclass
from enum import Enum
import logging

from .exceptions import SecurityError, ErrorCode

logger = logging.getLogger(__name__)


class SecurityLevel(Enum):
    """安全级别"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class PathSecurityResult:
    """路径安全检查结果"""
    is_safe: bool
    path: str
    normalized_path: str
    security_level: SecurityLevel
    warnings: List[str]
    errors: List[str]
    metadata: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'is_safe': self.is_safe,
            'path': self.path,
            'normalized_path': self.normalized_path,
            'security_level': self.security_level.value,
            'warnings': self.warnings,
            'errors': self.errors,
            'metadata': self.metadata
        }


class PathSecurityChecker:
    """路径安全检查器"""
    
    # 危险路径模式
    DANGEROUS_PATTERNS = [
        r'\.\./',          # 路径遍历
        r'\.\.\\',         # Windows路径遍历
        r'^/',             # 绝对路径
        r'^\\',            # Windows绝对路径
        r'~/',             # 用户目录
        r'\$[A-Za-z_]+/',  # 环境变量
    ]
    
    # 危险文件名
    DANGEROUS_FILENAMES = [
        '.htaccess',
        '.htpasswd',
        'web.config',
        'php.ini',
        '.env',
        'id_rsa',
        'id_rsa.pub',
    ]
    
    # 系统关键目录
    SYSTEM_DIRECTORIES = [
        '/etc',
        '/usr/bin',
        '/usr/sbin',
        '/bin',
        '/sbin',
        '/boot',
        '/proc',
        '/sys',
        '/dev',
        'C:\\Windows',
        'C:\\Program Files',
        'C:\\Program Files (x86)',
    ]
    
    def __init__(self, 
                 allowed_base_dirs: Optional[List[str]] = None,
                 security_level: SecurityLevel = SecurityLevel.MEDIUM):
        self.allowed_base_dirs = [os.path.abspath(d) for d in (allowed_base_dirs or [])]
        self.security_level = security_level
        self._blocked_paths: Set[str] = set()
        self._suspicious_activities: List[Dict[str, Any]] = []
    
    def check_path(self, file_path: str, 
                   check_existence: bool = True,
                   check_permissions: bool = True) -> PathSecurityResult:
        """检查路径安全性
        
        Args:
            file_path: 要检查的文件路径
            check_existence: 是否检查文件存在性
            check_permissions: 是否检查文件权限
        
        Returns:
            路径安全检查结果
        """
        result = PathSecurityResult(
            is_safe=True,
            path=file_path,
            normalized_path=self._normalize_path(file_path),
            security_level=self.security_level,
            warnings=[],
            errors=[],
            metadata={}
        )
        
        try:
            # 基础安全检查
            self._check_basic_security(result)
            
            # 路径遍历检查
            self._check_path_traversal(result)
            
            # 系统目录检查
            self._check_system_directories(result)
            
            # 允许目录检查
            self._check_allowed_directories(result)
            
            # 文件名检查
            self._check_filename(result)
            
            # 文件存在性检查
            if check_existence:
                self._check_file_existence(result)
            
            # 文件权限检查
            if check_permissions and os.path.exists(result.normalized_path):
                self._check_file_permissions(result)
            
            # 符号链接检查
            if os.path.exists(result.normalized_path):
                self._check_symlinks(result)
            
            # 文件大小检查
            if os.path.isfile(result.normalized_path):
                self._check_file_size(result)
            
            # 记录元数据
            self._collect_metadata(result)
            
            # 判断最终安全性
            result.is_safe = len(result.errors) == 0
            
            # 记录可疑活动
            if not result.is_safe or result.warnings:
                self._record_suspicious_activity(result)
            
        except Exception as e:
            result.errors.append(f"安全检查异常: {str(e)}")
            result.is_safe = False
            logger.error(f"路径安全检查异常: {e}", exc_info=True)
        
        return result
    
    def _normalize_path(self, file_path: str) -> str:
        """标准化路径"""
        try:
            # 转换为绝对路径
            abs_path = os.path.abspath(file_path)
            
            # 解析符号链接
            real_path = os.path.realpath(abs_path)
            
            return real_path
        except Exception as e:
            logger.warning(f"路径标准化失败: {e}")
            return file_path
    
    def _check_basic_security(self, result: PathSecurityResult):
        """基础安全检查"""
        # 检查空路径
        if not result.path or not result.path.strip():
            result.errors.append("文件路径为空")
            return
        
        # 检查路径长度
        if len(result.path) > 4096:
            result.warnings.append("文件路径过长")
        
        # 检查特殊字符
        dangerous_chars = ['\0', '\n', '\r']
        if any(char in result.path for char in dangerous_chars):
            result.errors.append("文件路径包含非法字符")
    
    def _check_path_traversal(self, result: PathSecurityResult):
        """检查路径遍历攻击"""
        for pattern in self.DANGEROUS_PATTERNS:
            if re.search(pattern, result.path, re.IGNORECASE):
                result.errors.append(f"检测到路径遍历攻击模式: {pattern}")
        
        # 检查标准化后的路径是否仍在允许范围内
        if self.allowed_base_dirs:
            is_allowed = any(
                result.normalized_path.startswith(base_dir)
                for base_dir in self.allowed_base_dirs
            )
            
            if not is_allowed:
                result.errors.append(
                    f"文件路径不在允许的目录范围内。路径: {result.normalized_path}"
                )
    
    def _check_system_directories(self, result: PathSecurityResult):
        """检查系统关键目录"""
        for sys_dir in self.SYSTEM_DIRECTORIES:
            if result.normalized_path.startswith(sys_dir):
                result.errors.append(f"尝试访问系统关键目录: {sys_dir}")
    
    def _check_allowed_directories(self, result: PathSecurityResult):
        """检查允许的目录"""
        if not self.allowed_base_dirs:
            return
        
        is_allowed = any(
            result.normalized_path.startswith(base_dir)
            for base_dir in self.allowed_base_dirs
        )
        
        if not is_allowed:
            result.errors.append(
                "文件路径不在允许的目录范围内"
            )
    
    def _check_filename(self, result: PathSecurityResult):
        """检查文件名"""
        filename = os.path.basename(result.normalized_path)
        
        # 检查危险文件名
        if filename.lower() in [name.lower() for name in self.DANGEROUS_FILENAMES]:
            result.warnings.append(f"访问敏感配置文件: {filename}")
        
        # 检查文件名长度
        if len(filename) > 255:
            result.warnings.append("文件名过长")
        
        # 检查保留字符
        reserved_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
        if any(char in filename for char in reserved_chars):
            result.errors.append("文件名包含保留字符")
    
    def _check_file_existence(self, result: PathSecurityResult):
        """检查文件存在性"""
        if not os.path.exists(result.normalized_path):
            result.warnings.append("文件不存在")
        elif not os.access(result.normalized_path, os.F_OK):
            result.errors.append("文件访问被拒绝")
    
    def _check_file_permissions(self, result: PathSecurityResult):
        """检查文件权限"""
        try:
            # 检查读取权限
            if not os.access(result.normalized_path, os.R_OK):
                result.warnings.append("文件不可读")
            
            # 检查写入权限
            if not os.access(result.normalized_path, os.W_OK):
                result.warnings.append("文件不可写")
            
            # 检查文件权限位
            file_stat = os.stat(result.normalized_path)
            file_mode = file_stat.st_mode
            
            # 检查是否为可执行文件
            if os.path.isfile(result.normalized_path) and (file_mode & stat.S_IXUSR):
                result.warnings.append("文件具有可执行权限")
            
            # 检查其他用户权限
            if file_mode & (stat.S_IWGRP | stat.S_IWOTH):
                result.warnings.append("文件对其他用户可写")
                
        except Exception as e:
            result.warnings.append(f"文件权限检查失败: {e}")
    
    def _check_symlinks(self, result: PathSecurityResult):
        """检查符号链接"""
        try:
            if os.path.islink(result.normalized_path):
                link_target = os.readlink(result.normalized_path)
                
                # 检查符号链接目标是否安全
                target_result = self.check_path(link_target, check_existence=False)
                
                if not target_result.is_safe:
                    result.errors.append(f"符号链接目标不安全: {link_target}")
                else:
                    result.warnings.append(f"文件是符号链接，目标: {link_target}")
                    
        except Exception as e:
            result.warnings.append(f"符号链接检查失败: {e}")
    
    def _check_file_size(self, result: PathSecurityResult):
        """检查文件大小"""
        try:
            file_size = os.path.getsize(result.normalized_path)
            result.metadata['file_size'] = file_size
            
            # 检查超大文件
            if file_size > 1024 * 1024 * 1024:  # 1GB
                result.warnings.append(f"文件较大: {file_size / (1024*1024):.2f}MB")
            
            # 检查空文件
            if file_size == 0:
                result.warnings.append("文件为空")
                
        except Exception as e:
            result.warnings.append(f"文件大小检查失败: {e}")
    
    def _collect_metadata(self, result: PathSecurityResult):
        """收集文件元数据"""
        try:
            if os.path.exists(result.normalized_path):
                file_stat = os.stat(result.normalized_path)
                
                result.metadata.update({
                    'size': file_stat.st_size,
                    'modified_time': file_stat.st_mtime,
                    'created_time': file_stat.st_ctime,
                    'is_file': os.path.isfile(result.normalized_path),
                    'is_directory': os.path.isdir(result.normalized_path),
                    'is_link': os.path.islink(result.normalized_path),
                })
                
                # 计算文件哈希（仅对小文件）
                if os.path.isfile(result.normalized_path) and file_stat.st_size < 1024 * 1024:
                    result.metadata['md5'] = self._calculate_file_hash(result.normalized_path)
                    
        except Exception as e:
            logger.warning(f"元数据收集失败: {e}")
    
    def _calculate_file_hash(self, file_path: str) -> str:
        """计算文件哈希"""
        try:
            with open(file_path, 'rb') as f:
                return hashlib.md5(f.read()).hexdigest()
        except Exception as e:
            logger.warning(f"文件哈希计算失败: {e}")
            return ""
    
    def _record_suspicious_activity(self, result: PathSecurityResult):
        """记录可疑活动"""
        if result.errors or result.warnings:
            activity = {
                'timestamp': time.time(),
                'path': result.path,
                'normalized_path': result.normalized_path,
                'errors': result.errors,
                'warnings': result.warnings,
                'is_safe': result.is_safe
            }
            
            self._suspicious_activities.append(activity)
            
            # 限制历史记录大小
            if len(self._suspicious_activities) > 1000:
                self._suspicious_activities.pop(0)
            
            # 记录到日志
            if result.errors:
                logger.warning(f"路径安全检查失败: {result.path}, 错误: {result.errors}")
            elif result.warnings:
                logger.info(f"路径安全检查警告: {result.path}, 警告: {result.warnings}")
    
    def get_suspicious_activities(self, limit: int = 100) -> List[Dict[str, Any]]:
        """获取可疑活动记录"""
        return self._suspicious_activities[-limit:]
    
    def block_path(self, file_path: str):
        """阻止特定路径"""
        normalized_path = self._normalize_path(file_path)
        self._blocked_paths.add(normalized_path)
        logger.info(f"已阻止路径: {normalized_path}")
    
    def is_path_blocked(self, file_path: str) -> bool:
        """检查路径是否被阻止"""
        normalized_path = self._normalize_path(file_path)
        return normalized_path in self._blocked_paths
    
    def clear_blocked_paths(self):
        """清空阻止的路径"""
        count = len(self._blocked_paths)
        self._blocked_paths.clear()
        logger.info(f"已清空 {count} 个阻止的路径")


class SecureFileHandler:
    """安全文件处理器"""
    
    def __init__(self, security_checker: PathSecurityChecker):
        self._security_checker = security_checker
        self._operation_log: List[Dict[str, Any]] = []
    
    def safe_read(self, file_path: str, 
                 mode: str = 'r',
                 encoding: str = 'utf-8',
                 max_size: int = 1024 * 1024 * 100) -> Optional[str]:
        """安全读取文件
        
        Args:
            file_path: 文件路径
            mode: 读取模式
            encoding: 文件编码
            max_size: 最大文件大小（字节）
        
        Returns:
            文件内容或None
        
        Raises:
            SecurityError: 安全检查失败时抛出
        """
        # 安全检查
        result = self._security_checker.check_path(file_path)
        
        if not result.is_safe:
            raise SecurityError(
                ErrorCode.PATH_TRAVERSAL_ERROR,
                "文件路径安全检查失败",
                details=result.to_dict()
            )
        
        if not os.path.exists(result.normalized_path):
            return None
        
        try:
            # 检查文件大小
            file_size = os.path.getsize(result.normalized_path)
            if file_size > max_size:
                raise SecurityError(
                    ErrorCode.FILE_READ_ERROR,
                    f"文件过大: {file_size} > {max_size}",
                    details={'file_path': file_path, 'file_size': file_size}
                )
            
            # 读取文件
            with open(result.normalized_path, mode, encoding=encoding) as f:
                content = f.read()
            
            # 记录操作
            self._log_operation('read', file_path, {'size': len(content)})
            
            return content
            
        except SecurityError:
            raise
        except Exception as e:
            raise SecurityError(
                ErrorCode.FILE_READ_ERROR,
                f"文件读取失败: {str(e)}",
                details={'file_path': file_path}
            )
    
    def safe_write(self, file_path: str, 
                  content: str,
                  mode: str = 'w',
                  encoding: str = 'utf-8',
                  create_dirs: bool = True) -> bool:
        """安全写入文件
        
        Args:
            file_path: 文件路径
            content: 文件内容
            mode: 写入模式
            encoding: 文件编码
            create_dirs: 是否创建目录
        
        Returns:
            是否写入成功
        
        Raises:
            SecurityError: 安全检查失败时抛出
        """
        # 安全检查
        result = self._security_checker.check_path(file_path, check_existence=False)
        
        if not result.is_safe:
            raise SecurityError(
                ErrorCode.PATH_TRAVERSAL_ERROR,
                "文件路径安全检查失败",
                details=result.to_dict()
            )
        
        try:
            # 创建目录
            if create_dirs:
                os.makedirs(os.path.dirname(result.normalized_path), exist_ok=True)
            
            # 写入文件
            with open(result.normalized_path, mode, encoding=encoding) as f:
                f.write(content)
            
            # 记录操作
            self._log_operation('write', file_path, {'size': len(content)})
            
            return True
            
        except SecurityError:
            raise
        except Exception as e:
            raise SecurityError(
                ErrorCode.FILE_WRITE_ERROR,
                f"文件写入失败: {str(e)}",
                details={'file_path': file_path}
            )
    
    def safe_delete(self, file_path: str) -> bool:
        """安全删除文件
        
        Args:
            file_path: 文件路径
        
        Returns:
            是否删除成功
        
        Raises:
            SecurityError: 安全检查失败时抛出
        """
        # 安全检查
        result = self._security_checker.check_path(file_path)
        
        if not result.is_safe:
            raise SecurityError(
                ErrorCode.PATH_TRAVERSAL_ERROR,
                "文件路径安全检查失败",
                details=result.to_dict()
            )
        
        if not os.path.exists(result.normalized_path):
            return False
        
        try:
            # 删除文件
            if os.path.isfile(result.normalized_path):
                os.remove(result.normalized_path)
            elif os.path.isdir(result.normalized_path):
                import shutil
                shutil.rmtree(result.normalized_path)
            
            # 记录操作
            self._log_operation('delete', file_path, {})
            
            return True
            
        except SecurityError:
            raise
        except Exception as e:
            raise SecurityError(
                ErrorCode.FILE_DELETE_ERROR,
                f"文件删除失败: {str(e)}",
                details={'file_path': file_path}
            )
    
    def _log_operation(self, operation: str, file_path: str, metadata: Dict[str, Any]):
        """记录文件操作"""
        log_entry = {
            'timestamp': time.time(),
            'operation': operation,
            'file_path': file_path,
            'metadata': metadata
        }
        
        self._operation_log.append(log_entry)
        
        # 限制日志大小
        if len(self._operation_log) > 1000:
            self._operation_log.pop(0)
        
        logger.debug(f"文件操作: {operation} {file_path}")
    
    def get_operation_log(self, limit: int = 100) -> List[Dict[str, Any]]:
        """获取操作日志"""
        return self._operation_log[-limit:]


@dataclass
class ValidationResult:
    """验证结果"""
    is_valid: bool
    errors: List[str]
    warnings: List[str]


class PasswordHasher:
    """密码哈希器（bcrypt优先，自动兼容旧格式）"""
    
    @staticmethod
    def hash(password: str) -> str:
        """哈希密码（bcrypt，成本因子12）"""
        try:
            import bcrypt
            return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()
        except ImportError:
            # 降级：bcrypt不可用时使用SHA256+盐
            salt = secrets.token_hex(16)
            hashed = hashlib.sha256((password + salt).encode()).hexdigest()
            return f"sha256${salt}${hashed}"
    
    @staticmethod
    def verify(password: str, hashed: str) -> bool:
        """验证密码，支持bcrypt和旧版SHA256格式"""
        if not hashed:
            return False
        
        try:
            import bcrypt
            
            # bcrypt格式
            if hashed.startswith("$2"):
                try:
                    return bcrypt.checkpw(password.encode(), hashed.encode())
                except Exception as e:
                    logger.warning(f"bcrypt 密码验证异常: {e}")
                    return False
            
            # SHA256+盐格式
            if hashed.startswith("sha256$"):
                try:
                    _, salt, hash_value = hashed.split("$", 2)
                    computed = hashlib.sha256((password + salt).encode()).hexdigest()
                    return computed == hash_value
                except Exception as e:
                    logger.warning(f"SHA256+盐 密码验证异常: {e}")
                    return False
            
            # 旧版 salt:hash 格式
            if ':' in hashed and not hashed.startswith("$"):
                salt, hash_value = hashed.split(':', 1)
                computed_hash = hashlib.sha256((password + salt).encode()).hexdigest()
                return computed_hash == hash_value
                
        except ImportError:
            # bcrypt不可用时回退旧逻辑
            pass
        
        # 纯SHA256（无盐，极度不安全）
        try:
            return hashlib.sha256(password.encode()).hexdigest() == hashed
        except Exception as e:
            logger.warning(f"纯SHA256密码验证异常: {e}")
            return False
    
    @staticmethod
    def needs_rehash(hashed: str) -> bool:
        """检查是否需要升级到bcrypt"""
        if not hashed:
            return True
        try:
            import bcrypt  # noqa: F401  仅检测可用性：能 import 即说明 bcrypt 路径可走
            return not hashed.startswith("$2")
        except ImportError:
            return False  # bcrypt不可用，无需升级


class InputValidator:
    """输入验证器"""
    
    @staticmethod
    def validate_password(password: str, min_length: int = 8, 
                        require_upper: bool = True, 
                        require_lower: bool = True, 
                        require_digit: bool = True) -> ValidationResult:
        """验证密码"""
        errors = []
        
        if len(password) < min_length:
            errors.append(f"密码长度至少为{min_length}个字符")
        
        if require_upper and not any(c.isupper() for c in password):
            errors.append("密码必须包含至少一个大写字母")
        
        if require_lower and not any(c.islower() for c in password):
            errors.append("密码必须包含至少一个小写字母")
        
        if require_digit and not any(c.isdigit() for c in password):
            errors.append("密码必须包含至少一个数字")
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=[]
        )
    
    @staticmethod
    def validate_phone(phone: str) -> ValidationResult:
        """验证手机号"""
        errors = []
        
        if not re.match(r'^1[3-9]\d{9}$', phone):
            errors.append("手机号格式不正确")
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=[]
        )
    
    @staticmethod
    def validate_email(email: str) -> ValidationResult:
        """验证邮箱"""
        errors = []
        
        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
            errors.append("邮箱格式不正确")
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=[]
        )
    
    @staticmethod
    def validate_username(username: str) -> ValidationResult:
        """验证用户名"""
        errors = []
        
        if len(username) < 3:
            errors.append("用户名长度至少为3个字符")
        
        if not re.match(r'^[a-zA-Z0-9_]+$', username):
            errors.append("用户名只能包含字母、数字和下划线")
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=[]
        )
    
    @staticmethod
    def sanitize_input(input_str: str) -> str:
        """清理输入"""
        return input_str.strip()
    
    @staticmethod
    def validate_integer(value: int, min_val: int = None, max_val: int = None) -> ValidationResult:
        """验证整数"""
        errors = []
        
        if min_val is not None and value < min_val:
            errors.append(f"值必须大于等于{min_val}")
        
        if max_val is not None and value > max_val:
            errors.append(f"值必须小于等于{max_val}")
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=[]
        )


class LoginAttemptManager:
    """登录尝试管理器"""
    
    def __init__(self, max_attempts: int = 5, lockout_duration: int = 300):
        self.max_attempts = max_attempts
        self.lockout_duration = lockout_duration
        self.attempts: Dict[str, Dict[str, Any]] = {}
    
    def record_attempt(self, identifier: str) -> Tuple[bool, int]:
        """记录登录尝试"""
        now = time.time()
        
        if identifier not in self.attempts:
            self.attempts[identifier] = {
                'count': 0,
                'last_attempt': now,
                'locked_until': 0
            }
        
        attempt = self.attempts[identifier]
        
        if attempt['locked_until'] > now:
            return False, int(attempt['locked_until'] - now)
        
        attempt['count'] += 1
        attempt['last_attempt'] = now
        
        if attempt['count'] >= self.max_attempts:
            attempt['locked_until'] = now + self.lockout_duration
            return False, self.lockout_duration
        
        remaining = self.max_attempts - attempt['count']
        return True, remaining
    
    def is_locked(self, identifier: str) -> Tuple[bool, int]:
        """检查是否被锁定"""
        if identifier not in self.attempts:
            return False, 0
        
        attempt = self.attempts[identifier]
        now = time.time()
        
        if attempt['locked_until'] > now:
            return True, int(attempt['locked_until'] - now)
        
        return False, 0
    
    def reset(self, identifier: str):
        """重置登录尝试"""
        if identifier in self.attempts:
            del self.attempts[identifier]


class SecureToken:
    """安全令牌"""
    
    @staticmethod
    def generate() -> str:
        """生成安全令牌"""
        return secrets.token_hex(32)
    
    @staticmethod
    def generate_numeric(length: int = 6) -> str:
        """生成数字令牌"""
        return ''.join(random.choices('0123456789', k=length))
    
    @staticmethod
    def generate_session_token() -> str:
        """生成会话令牌"""
        timestamp = str(int(time.time()))
        token = secrets.token_hex(16)
        return f"{timestamp}.{token}"
    
    @staticmethod
    def verify_session_token(token: str, max_age: int = 86400) -> bool:
        """验证会话令牌"""
        try:
            timestamp_str, _ = token.split('.', 1)
            timestamp = int(timestamp_str)
            return (time.time() - timestamp) < max_age
        except Exception as e:
            logger.debug(f"[Security] 验证会话令牌失败: {e}")
            return False


class DataSanitizer:
    """数据脱敏器"""
    
    @staticmethod
    def mask_phone(phone: str) -> str:
        """掩码手机号"""
        if len(phone) >= 11:
            return f"{phone[:3]}****{phone[-4:]}"
        return phone
    
    @staticmethod
    def mask_email(email: str) -> str:
        """掩码邮箱"""
        try:
            username, domain = email.split('@', 1)
            if len(username) > 3:
                return f"{username[:3]}***@{domain}"
            return f"{username}***@{domain}"
        except Exception as e:
            logger.debug(f"[Security] 掩码邮箱失败: {e}")
            return email
    
    @staticmethod
    def mask_api_key(api_key: str) -> str:
        """掩码API密钥：保留前 4 位（如 sk-1）便于用户辨认是哪把 key，展示后 4 位供校验"""
        if len(api_key) >= 8:
            return f"{api_key[:4]}***{api_key[-4:]}"
        return api_key


# 全局安全检查器实例
_global_security_checker: Optional[PathSecurityChecker] = None
_global_file_handler: Optional[SecureFileHandler] = None
_login_attempt_manager: Optional[LoginAttemptManager] = None


def get_security_checker(allowed_base_dirs: Optional[List[str]] = None,
                        security_level: SecurityLevel = SecurityLevel.MEDIUM) -> PathSecurityChecker:
    """获取全局安全检查器"""
    global _global_security_checker
    
    if _global_security_checker is None:
        _global_security_checker = PathSecurityChecker(
            allowed_base_dirs=allowed_base_dirs,
            security_level=security_level
        )
    
    return _global_security_checker


def get_file_handler(allowed_base_dirs: Optional[List[str]] = None,
                     security_level: SecurityLevel = SecurityLevel.MEDIUM) -> SecureFileHandler:
    """获取全局文件处理器"""
    global _global_file_handler
    
    if _global_file_handler is None:
        security_checker = get_security_checker(allowed_base_dirs, security_level)
        _global_file_handler = SecureFileHandler(security_checker)
    
    return _global_file_handler

def get_login_attempt_manager() -> LoginAttemptManager:
    """获取登录尝试管理器"""
    global _login_attempt_manager
    
    if _login_attempt_manager is None:
        _login_attempt_manager = LoginAttemptManager()
    
    return _login_attempt_manager


def check_file_path_safe(file_path: str,
                       allowed_base_dirs: Optional[List[str]] = None) -> bool:
    """检查文件路径是否安全
    
    Args:
        file_path: 文件路径
        allowed_base_dirs: 允许的基础目录列表
    
    Returns:
        是否安全
    
    Raises:
        SecurityError: 路径不安全时抛出
    """
    checker = get_security_checker(allowed_base_dirs)
    result = checker.check_path(file_path)
    
    if not result.is_safe:
        raise SecurityError(
            ErrorCode.PATH_TRAVERSAL_ERROR,
            "文件路径安全检查失败",
            details=result.to_dict()
        )
    
    return True


def sanitize_file_path(file_path: str,
                     allowed_base_dirs: Optional[List[str]] = None) -> str:
    """清理和验证文件路径
    
    Args:
        file_path: 文件路径
        allowed_base_dirs: 允许的基础目录列表
    
    Returns:
        清理后的安全路径
    
    Raises:
        SecurityError: 路径不安全时抛出
    """
    checker = get_security_checker(allowed_base_dirs)
    result = checker.check_path(file_path)
    
    if not result.is_safe:
        raise SecurityError(
            ErrorCode.PATH_TRAVERSAL_ERROR,
            "文件路径安全检查失败",
            details=result.to_dict()
        )
    
    return result.normalized_path


# 导出全局实例
login_attempt_manager = get_login_attempt_manager()
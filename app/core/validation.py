"""
输入验证框架
================
统一的数据验证和安全性检查系统
"""

import os
import re
import mimetypes
from typing import Any, Dict, List, Optional, Type, Union, get_type_hints
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import logging

from app.core.exceptions import (
    BaseException,
    ErrorCode,
    ValidationError,
    SecurityError
)

logger = logging.getLogger(__name__)


class ValidationRule(Enum):
    """验证规则"""
    REQUIRED = "required"
    TYPE = "type"
    RANGE = "range"
    LENGTH = "length"
    PATTERN = "pattern"
    CUSTOM = "custom"
    FILE_EXISTS = "file_exists"
    FILE_READABLE = "file_readable"
    FILE_WRITABLE = "file_writable"
    DIRECTORY_EXISTS = "directory_exists"
    SAFE_PATH = "safe_path"
    ALLOWED_EXTENSION = "allowed_extension"
    MIME_TYPE = "mime_type"


@dataclass
class ValidationResult:
    """验证结果"""
    is_valid: bool
    field_name: str
    field_value: Any
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    def add_error(self, error: str):
        """添加错误信息"""
        self.errors.append(error)
        self.is_valid = False
    
    def add_warning(self, warning: str):
        """添加警告信息"""
        self.warnings.append(warning)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'is_valid': self.is_valid,
            'field_name': self.field_name,
            'field_value': str(self.field_value),
            'errors': self.errors,
            'warnings': self.warnings
        }


class Validator:
    """验证器基类"""
    
    def validate(self, value: Any, field_name: str = "value") -> ValidationResult:
        """验证值"""
        raise NotImplementedError
    
    def get_error_message(self, field_name: str) -> str:
        """获取错误消息"""
        return f"{field_name} 验证失败"


class RequiredValidator(Validator):
    """必填验证器"""
    
    def validate(self, value: Any, field_name: str = "value") -> ValidationResult:
        result = ValidationResult(is_valid=True, field_name=field_name, field_value=value)
        
        if value is None or (isinstance(value, str) and not value.strip()):
            result.add_error(f"{field_name} 是必填项")
        
        return result


class TypeValidator(Validator):
    """类型验证器"""
    
    def __init__(self, expected_type: Type):
        self.expected_type = expected_type
    
    def validate(self, value: Any, field_name: str = "value") -> ValidationResult:
        result = ValidationResult(is_valid=True, field_name=field_name, field_value=value)
        
        if value is not None and not isinstance(value, self.expected_type):
            result.add_error(
                f"{field_name} 类型错误，期望 {self.expected_type.__name__}，实际 {type(value).__name__}"
            )
        
        return result


class RangeValidator(Validator):
    """范围验证器"""
    
    def __init__(self, min_value: Optional[float] = None, max_value: Optional[float] = None):
        self.min_value = min_value
        self.max_value = max_value
    
    def validate(self, value: Any, field_name: str = "value") -> ValidationResult:
        result = ValidationResult(is_valid=True, field_name=field_name, field_value=value)
        
        if value is None:
            return result
        
        try:
            num_value = float(value)
            
            if self.min_value is not None and num_value < self.min_value:
                result.add_error(f"{field_name} 不能小于 {self.min_value}")
            
            if self.max_value is not None and num_value > self.max_value:
                result.add_error(f"{field_name} 不能大于 {self.max_value}")
                
        except (ValueError, TypeError):
            result.add_error(f"{field_name} 必须是数字")
        
        return result


class LengthValidator(Validator):
    """长度验证器"""
    
    def __init__(self, min_length: Optional[int] = None, max_length: Optional[int] = None):
        self.min_length = min_length
        self.max_length = max_length
    
    def validate(self, value: Any, field_name: str = "value") -> ValidationResult:
        result = ValidationResult(is_valid=True, field_name=field_name, field_value=value)
        
        if value is None:
            return result
        
        try:
            length = len(value)
            
            if self.min_length is not None and length < self.min_length:
                result.add_error(f"{field_name} 长度不能小于 {self.min_length}")
            
            if self.max_length is not None and length > self.max_length:
                result.add_error(f"{field_name} 长度不能大于 {self.max_length}")
                
        except TypeError:
            result.add_error(f"{field_name} 不支持长度检查")
        
        return result


class PatternValidator(Validator):
    """正则表达式验证器"""
    
    def __init__(self, pattern: str, flags: int = 0):
        self.pattern = pattern
        self.regex = re.compile(pattern, flags)
    
    def validate(self, value: Any, field_name: str = "value") -> ValidationResult:
        result = ValidationResult(is_valid=True, field_name=field_name, field_value=value)
        
        if value is None:
            return result
        
        if not isinstance(value, str):
            result.add_error(f"{field_name} 必须是字符串")
            return result
        
        if not self.regex.match(value):
            result.add_error(f"{field_name} 格式不正确")
        
        return result


class SafePathValidator(Validator):
    """安全路径验证器"""
    
    def __init__(self, allowed_base_dirs: Optional[List[str]] = None):
        self.allowed_base_dirs = allowed_base_dirs or []
    
    def validate(self, value: Any, field_name: str = "value") -> ValidationResult:
        result = ValidationResult(is_valid=True, field_name=field_name, field_value=value)
        
        if value is None:
            return result
        
        if not isinstance(value, (str, Path)):
            result.add_error(f"{field_name} 必须是路径")
            return result
        
        path_str = str(value)
        
        # 检查路径遍历攻击
        if '..' in path_str or path_str.startswith('/') or path_str.startswith('\\'):
            result.add_error(f"{field_name} 包含非法路径字符")
        
        # 检查是否在允许的目录下
        if self.allowed_base_dirs:
            try:
                abs_path = os.path.abspath(path_str)
                is_allowed = any(
                    abs_path.startswith(os.path.abspath(base_dir))
                    for base_dir in self.allowed_base_dirs
                )
                
                if not is_allowed:
                    result.add_error(f"{field_name} 不在允许的目录范围内")
                    
            except Exception as e:
                result.add_error(f"{field_name} 路径验证失败: {e}")
        
        return result


class FileExtensionValidator(Validator):
    """文件扩展名验证器"""
    
    def __init__(self, allowed_extensions: List[str], case_sensitive: bool = False):
        self.allowed_extensions = allowed_extensions
        self.case_sensitive = case_sensitive
        
        if not case_sensitive:
            self.allowed_extensions = [ext.lower() for ext in allowed_extensions]
    
    def validate(self, value: Any, field_name: str = "value") -> ValidationResult:
        result = ValidationResult(is_valid=True, field_name=field_name, field_value=value)
        
        if value is None:
            return result
        
        if not isinstance(value, (str, Path)):
            result.add_error(f"{field_name} 必须是文件路径")
            return result
        
        path_str = str(value)
        ext = os.path.splitext(path_str)[1]
        
        if not self.case_sensitive:
            ext = ext.lower()
        
        if ext not in self.allowed_extensions:
            result.add_error(
                f"{field_name} 文件扩展名不支持，允许的扩展名: {', '.join(self.allowed_extensions)}"
            )
        
        return result


class FileExistsValidator(Validator):
    """文件存在验证器"""
    
    def __init__(self, must_exist: bool = True):
        self.must_exist = must_exist
    
    def validate(self, value: Any, field_name: str = "value") -> ValidationResult:
        result = ValidationResult(is_valid=True, field_name=field_name, field_value=value)
        
        if value is None:
            return result
        
        if not isinstance(value, (str, Path)):
            result.add_error(f"{field_name} 必须是文件路径")
            return result
        
        path_str = str(value)
        exists = os.path.exists(path_str)
        
        if self.must_exist and not exists:
            result.add_error(f"{field_name} 文件不存在")
        elif not self.must_exist and exists:
            result.add_warning(f"{field_name} 文件已存在")
        
        return result


class MimeTypeValidator(Validator):
    """MIME类型验证器"""
    
    def __init__(self, allowed_mime_types: List[str]):
        self.allowed_mime_types = allowed_mime_types
    
    def validate(self, value: Any, field_name: str = "value") -> ValidationResult:
        result = ValidationResult(is_valid=True, field_name=field_name, field_value=value)
        
        if value is None:
            return result
        
        if not isinstance(value, (str, Path)):
            result.add_error(f"{field_name} 必须是文件路径")
            return result
        
        path_str = str(value)
        
        if not os.path.exists(path_str):
            result.add_error(f"{field_name} 文件不存在，无法检查MIME类型")
            return result
        
        mime_type, _ = mimetypes.guess_type(path_str)
        
        if mime_type not in self.allowed_mime_types:
            result.add_error(
                f"{field_name} MIME类型不支持，允许的类型: {', '.join(self.allowed_mime_types)}"
            )
        
        return result


class ValidationSchema:
    """验证模式"""
    
    def __init__(self):
        self._validators: Dict[str, List[Validator]] = {}
    
    def add_validator(self, field_name: str, validator: Validator):
        """添加验证器"""
        if field_name not in self._validators:
            self._validators[field_name] = []
        self._validators[field_name].append(validator)
    
    def validate(self, data: Dict[str, Any]) -> Dict[str, ValidationResult]:
        """验证数据"""
        results = {}
        
        for field_name, validators in self._validators.items():
            field_value = data.get(field_name)
            result = ValidationResult(is_valid=True, field_name=field_name, field_value=field_value)
            
            for validator in validators:
                validator_result = validator.validate(field_value, field_name)
                result.errors.extend(validator_result.errors)
                result.warnings.extend(validator_result.warnings)
                result.is_valid = result.is_valid and validator_result.is_valid
            
            results[field_name] = result
        
        return results
    
    def is_valid(self, data: Dict[str, Any]) -> bool:
        """检查数据是否有效"""
        results = self.validate(data)
        return all(result.is_valid for result in results.values())


class VideoImportValidator(ValidationSchema):
    """视频导入验证模式"""
    
    def __init__(self, allowed_base_dirs: Optional[List[str]] = None):
        super().__init__()
        
        # 文件路径验证
        self.add_validator('file_path', RequiredValidator())
        self.add_validator('file_path', TypeValidator(str))
        self.add_validator('file_path', SafePathValidator(allowed_base_dirs))
        self.add_validator('file_path', FileExtensionValidator([
            '.mp4', '.mov', '.avi', '.mkv', '.flv', '.wmv'
        ]))
        self.add_validator('file_path', FileExistsValidator(must_exist=True))
        self.add_validator('file_path', MimeTypeValidator([
            'video/mp4', 'video/quicktime', 'video/x-msvideo', 
            'video/x-matroska', 'video/x-flv', 'video/x-ms-wmv'
        ]))
        
        # 项目ID验证
        self.add_validator('project_id', RequiredValidator())
        self.add_validator('project_id', TypeValidator(str))
        self.add_validator('project_id', PatternValidator(r'^[a-zA-Z0-9_-]{1,64}$'))
        
        # 导入设置验证
        self.add_validator('import_settings', TypeValidator(dict))


class ProjectCreationValidator(ValidationSchema):
    """项目创建验证模式"""
    
    def __init__(self):
        super().__init__()
        
        # 项目名称验证
        self.add_validator('name', RequiredValidator())
        self.add_validator('name', TypeValidator(str))
        self.add_validator('name', LengthValidator(min_length=1, max_length=256))
        
        # 分辨率验证
        self.add_validator('resolution', TypeValidator(str))
        self.add_validator('resolution', PatternValidator(r'^\d{3,4}x\d{3,4}$'))
        
        # 帧率验证
        self.add_validator('fps', TypeValidator((int, float)))
        self.add_validator('fps', RangeValidator(min_value=1, max_value=120))


def validate_video_import(data: Dict[str, Any], 
                       allowed_base_dirs: Optional[List[str]] = None) -> Dict[str, ValidationResult]:
    """验证视频导入数据
    
    Args:
        data: 要验证的数据
        allowed_base_dirs: 允许的基础目录列表
    
    Returns:
        验证结果字典
    """
    validator = VideoImportValidator(allowed_base_dirs)
    return validator.validate(data)


def validate_project_creation(data: Dict[str, Any]) -> Dict[str, ValidationResult]:
    """验证项目创建数据
    
    Args:
        data: 要验证的数据
    
    Returns:
        验证结果字典
    """
    validator = ProjectCreationValidator()
    return validator.validate(data)


def validate_input(data: Dict[str, Any], schema: ValidationSchema) -> bool:
    """验证输入数据
    
    Args:
        data: 要验证的数据
        schema: 验证模式
    
    Returns:
        是否验证通过
    
    Raises:
        ValidationError: 验证失败时抛出
    """
    results = schema.validate(data)
    
    errors = []
    for field_name, result in results.items():
        if not result.is_valid:
            errors.extend(result.errors)
    
    if errors:
        raise ValidationError(
            ErrorCode.INVALID_PARAMETER,
            "输入验证失败",
            details={'errors': errors, 'validation_results': {k: v.to_dict() for k, v in results.items()}}
        )
    
    return True


def sanitize_file_path(file_path: str, allowed_base_dirs: Optional[List[str]] = None) -> str:
    """清理和验证文件路径
    
    Args:
        file_path: 文件路径
        allowed_base_dirs: 允许的基础目录列表
    
    Returns:
        清理后的文件路径
    
    Raises:
        SecurityError: 路径不安全时抛出
    """
    # 检查路径遍历攻击
    if '..' in file_path or file_path.startswith('/') or file_path.startswith('\\'):
        raise SecurityError(
            ErrorCode.PATH_TRAVERSAL_ERROR,
            "文件路径包含非法字符",
            details={'file_path': file_path}
        )
    
    # 转换为绝对路径
    abs_path = os.path.abspath(file_path)
    
    # 检查是否在允许的目录下
    if allowed_base_dirs:
        is_allowed = any(
            abs_path.startswith(os.path.abspath(base_dir))
            for base_dir in allowed_base_dirs
        )
        
        if not is_allowed:
            raise SecurityError(
                ErrorCode.PATH_TRAVERSAL_ERROR,
                "文件路径不在允许的目录范围内",
                details={'file_path': file_path, 'allowed_dirs': allowed_base_dirs}
            )
    
    return abs_path


def validate_file_extension(file_path: str, 
                        allowed_extensions: List[str],
                        case_sensitive: bool = False) -> bool:
    """验证文件扩展名
    
    Args:
        file_path: 文件路径
        allowed_extensions: 允许的扩展名列表
        case_sensitive: 是否区分大小写
    
    Returns:
        是否验证通过
    
    Raises:
        ValidationError: 验证失败时抛出
    """
    ext = os.path.splitext(file_path)[1]
    
    if not case_sensitive:
        ext = ext.lower()
        allowed_extensions = [e.lower() for e in allowed_extensions]
    
    if ext not in allowed_extensions:
        raise ValidationError(
            ErrorCode.UNSUPPORTED_FILE_FORMAT,
            f"不支持的文件扩展名: {ext}",
            details={
                'file_path': file_path,
                'allowed_extensions': allowed_extensions
            }
        )
    
    return True


# 常用验证模式实例
video_import_schema = VideoImportValidator()
project_creation_schema = ProjectCreationValidator()
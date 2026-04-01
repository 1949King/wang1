"""
统一异常系统
================
定义项目中所有异常的层次结构和错误码
"""

import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum
import traceback
import time

logger = logging.getLogger(__name__)


class ErrorCode(Enum):
    """错误码枚举"""
    
    # 通用错误 (1000-1999)
    SUCCESS = (1000, "操作成功")
    UNKNOWN_ERROR = (1001, "未知错误")
    INVALID_PARAMETER = (1002, "参数无效")
    OPERATION_TIMEOUT = (1003, "操作超时")
    OPERATION_CANCELLED = (1004, "操作已取消")
    
    # 文件系统错误 (2000-2999)
    FILE_NOT_FOUND = (2001, "文件不存在")
    FILE_PERMISSION_DENIED = (2002, "文件权限拒绝")
    FILE_ALREADY_EXISTS = (2003, "文件已存在")
    FILE_READ_ERROR = (2004, "文件读取错误")
    FILE_WRITE_ERROR = (2005, "文件写入错误")
    FILE_DELETE_ERROR = (2006, "文件删除错误")
    INVALID_FILE_PATH = (2007, "无效的文件路径")
    UNSUPPORTED_FILE_FORMAT = (2008, "不支持的文件格式")
    
    # 视频处理错误 (3000-3999)
    VIDEO_LOAD_ERROR = (3001, "视频加载错误")
    VIDEO_DECODE_ERROR = (3002, "视频解码错误")
    VIDEO_ENCODE_ERROR = (3003, "视频编码错误")
    VIDEO_RENDER_ERROR = (3004, "视频渲染错误")
    VIDEO_EXPORT_ERROR = (3005, "视频导出错误")
    INVALID_VIDEO_FORMAT = (3006, "无效的视频格式")
    VIDEO_CORRUPTED = (3007, "视频文件损坏")
    VIDEO_DURATION_ERROR = (3008, "视频时长错误")
    
    # 音频处理错误 (4000-4999)
    AUDIO_LOAD_ERROR = (4001, "音频加载错误")
    AUDIO_DECODE_ERROR = (4002, "音频解码错误")
    AUDIO_ENCODE_ERROR = (4003, "音频编码错误")
    INVALID_AUDIO_FORMAT = (4004, "无效的音频格式")
    AUDIO_CORRUPTED = (4005, "音频文件损坏")
    
    # 缓存系统错误 (5000-5999)
    CACHE_ERROR = (5001, "缓存错误")
    CACHE_MISS = (5002, "缓存未命中")
    CACHE_WRITE_ERROR = (5003, "缓存写入错误")
    CACHE_READ_ERROR = (5004, "缓存读取错误")
    CACHE_CLEANUP_ERROR = (5005, "缓存清理错误")
    CACHE_FULL = (5006, "缓存已满")
    
    # AI引擎错误 (6000-6999)
    AI_ENGINE_ERROR = (6001, "AI引擎错误")
    AI_MODEL_LOAD_ERROR = (6002, "AI模型加载错误")
    AI_INFERENCE_ERROR = (6003, "AI推理错误")
    AI_TIMEOUT_ERROR = (6004, "AI处理超时")
    AI_MODEL_NOT_FOUND = (6005, "AI模型未找到")
    AI_INVALID_INPUT = (6006, "AI输入无效")
    
    # 渲染引擎错误 (7000-7999)
    RENDER_ERROR = (7001, "渲染错误")
    RENDER_HARDWARE_ERROR = (7002, "渲染硬件错误")
    RENDER_MEMORY_ERROR = (7003, "渲染内存错误")
    RENDER_UNSUPPORTED_FEATURE = (7004, "不支持的渲染特性")
    
    # 插件系统错误 (8000-8999)
    PLUGIN_ERROR = (8001, "插件错误")
    PLUGIN_LOAD_ERROR = (8002, "插件加载错误")
    PLUGIN_UNLOAD_ERROR = (8003, "插件卸载错误")
    PLUGIN_NOT_FOUND = (8004, "插件未找到")
    PLUGIN_VERSION_ERROR = (8005, "插件版本错误")
    PLUGIN_PERMISSION_ERROR = (8006, "插件权限错误")
    
    # 网络错误 (9000-9999)
    NETWORK_ERROR = (9001, "网络错误")
    CONNECTION_ERROR = (9002, "连接错误")
    TIMEOUT_ERROR = (9003, "超时错误")
    DNS_ERROR = (9004, "DNS错误")
    
    # 数据库错误 (10000-10999)
    DATABASE_ERROR = (10001, "数据库错误")
    DATABASE_CONNECTION_ERROR = (10002, "数据库连接错误")
    DATABASE_QUERY_ERROR = (10003, "数据库查询错误")
    DATABASE_TRANSACTION_ERROR = (10004, "数据库事务错误")
    
    # 安全错误 (11000-11999)
    SECURITY_ERROR = (11001, "安全错误")
    AUTHENTICATION_ERROR = (11002, "认证错误")
    AUTHORIZATION_ERROR = (11003, "授权错误")
    ENCRYPTION_ERROR = (11004, "加密错误")
    PATH_TRAVERSAL_ERROR = (11005, "路径遍历攻击")
    INJECTION_ERROR = (11006, "注入攻击")
    
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
    
    def __str__(self):
        return f"[{self.code}] {self.message}"


class BaseException(Exception):
    """基础异常类"""
    
    def __init__(
        self,
        error_code: ErrorCode,
        message: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None
    ):
        self.error_code = error_code
        self.message = message or error_code.message
        self.details = details or {}
        self.cause = cause
        self.timestamp = time.time()
        
        # 构建完整的错误信息
        error_msg = f"{error_code}"
        if message:
            error_msg += f": {message}"
        
        super().__init__(error_msg)
        
        # 记录异常
        self._log_exception()
    
    def _log_exception(self):
        """记录异常日志"""
        log_level = logging.ERROR
        
        # 根据错误类型调整日志级别
        if self.error_code in [ErrorCode.CACHE_MISS]:
            log_level = logging.DEBUG
        elif self.error_code in [ErrorCode.INVALID_PARAMETER, ErrorCode.INVALID_FILE_PATH]:
            log_level = logging.WARNING
        
        logger.log(
            log_level,
            f"{self.error_code}: {self.message}",
            extra={
                'error_code': self.error_code.code,
                'error_details': self.details,
                'has_cause': self.cause is not None
            },
            exc_info=self.cause is not None
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'error_code': self.error_code.code,
            'error_message': self.message,
            'error_type': self.__class__.__name__,
            'details': self.details,
            'timestamp': self.timestamp,
            'has_cause': self.cause is not None
        }
    
    def get_user_message(self) -> str:
        """获取用户友好的错误信息"""
        return self.message


class FileSystemError(BaseException):
    """文件系统异常"""
    pass


class VideoProcessingError(BaseException):
    """视频处理异常"""
    pass


class AudioProcessingError(BaseException):
    """音频处理异常"""
    pass


class CacheError(BaseException):
    """缓存系统异常"""
    pass


class AIEngineError(BaseException):
    """AI引擎异常"""
    pass


class RenderError(BaseException):
    """渲染引擎异常"""
    pass


class PluginError(BaseException):
    """插件系统异常"""
    pass


class NetworkError(BaseException):
    """网络异常"""
    pass


class DatabaseError(BaseException):
    """数据库异常"""
    pass


class SecurityError(BaseException):
    """安全异常"""
    pass


class ValidationError(BaseException):
    """验证异常"""
    pass


class ConfigurationError(BaseException):
    """配置异常"""
    pass


@dataclass
class ErrorContext:
    """错误上下文信息"""
    module: str
    function: str
    line_number: int
    variables: Dict[str, Any] = None
    stack_trace: str = None


class ErrorHandler:
    """错误处理器"""
    
    def __init__(self):
        self._error_callbacks = []
        self._error_history = []
        self._max_history_size = 1000
    
    def handle_exception(
        self,
        exception: Exception,
        context: Optional[ErrorContext] = None,
        raise_exception: bool = False
    ) -> Optional[Dict[str, Any]]:
        """处理异常
        
        Args:
            exception: 异常对象
            context: 错误上下文
            raise_exception: 是否重新抛出异常
        
        Returns:
            错误信息字典
        """
        # 转换为标准格式
        if isinstance(exception, BaseException):
            error_info = exception.to_dict()
        else:
            error_info = {
                'error_code': ErrorCode.UNKNOWN_ERROR.code,
                'error_message': str(exception),
                'error_type': exception.__class__.__name__,
                'timestamp': time.time()
            }
        
        # 添加上下文信息
        if context:
            error_info['context'] = {
                'module': context.module,
                'function': context.function,
                'line_number': context.line_number,
                'variables': context.variables
            }
        
        # 添加堆栈跟踪
        error_info['stack_trace'] = traceback.format_exc()
        
        # 存储到历史记录
        self._store_error(error_info)
        
        # 调用回调函数
        for callback in self._error_callbacks:
            try:
                callback(error_info)
            except Exception as e:
                logger.error(f"错误回调执行失败: {e}")
        
        # 重新抛出异常
        if raise_exception:
            raise exception
        
        return error_info
    
    def _store_error(self, error_info: Dict[str, Any]):
        """存储错误信息到历史记录"""
        self._error_history.append(error_info)
        if len(self._error_history) > self._max_history_size:
            self._error_history.pop(0)
    
    def add_error_callback(self, callback):
        """添加错误回调函数"""
        self._error_callbacks.append(callback)
    
    def get_error_history(self, limit: int = 100) -> list:
        """获取错误历史记录"""
        return self._error_history[-limit:]
    
    def get_error_statistics(self) -> Dict[str, Any]:
        """获取错误统计信息"""
        if not self._error_history:
            return {}
        
        error_counts = {}
        for error in self._error_history:
            error_code = error.get('error_code', 0)
            error_counts[error_code] = error_counts.get(error_code, 0) + 1
        
        return {
            'total_errors': len(self._error_history),
            'error_counts': error_counts,
            'most_common_errors': sorted(
                error_counts.items(),
                key=lambda x: x[1],
                reverse=True
            )[:10]
        }


def create_error_context(
    module: str,
    function: str,
    line_number: int,
    variables: Dict[str, Any] = None
) -> ErrorContext:
    """创建错误上下文
    
    Args:
        module: 模块名
        function: 函数名
        line_number: 行号
        variables: 变量字典
    
    Returns:
        错误上下文对象
    """
    return ErrorContext(
        module=module,
        function=function,
        line_number=line_number,
        variables=variables,
        stack_trace=traceback.format_exc()
    )


def safe_execute(
    func,
    *args,
    error_handler: Optional[ErrorHandler] = None,
    default_return=None,
    raise_exception: bool = False,
    **kwargs
):
    """安全执行函数，自动处理异常
    
    Args:
        func: 要执行的函数
        *args: 位置参数
        error_handler: 错误处理器
        default_return: 默认返回值
        raise_exception: 是否重新抛出异常
        **kwargs: 关键字参数
    
    Returns:
        函数返回值或默认返回值
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        if error_handler:
            error_handler.handle_exception(e, raise_exception=raise_exception)
        elif raise_exception:
            raise
        else:
            logger.error(f"函数执行失败: {e}", exc_info=True)
        
        return default_return


# 全局错误处理器实例
global_error_handler = ErrorHandler()


def get_error_handler() -> ErrorHandler:
    """获取全局错误处理器"""
    return global_error_handler
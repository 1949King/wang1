"""
统一日志管理模块 v2.0
====================
日志轮转 + 敏感信息过滤 + 统一配置 + 上下文信息

B4 收敛标记 (2026-05-31):
本文件是日志子系统推荐入口 (提供 logger, 轮转, 敏感信息过滤)
相关职责文件:
  - logging_enhanced.py → 性能监控/结构化日志 (增强层)
  - log_aggregation.py  → 分布式日志聚合 (聚合层)
3 个文件职责正交 (入口/增强/聚合), 保留但层级明确化
新代码推荐: from core.log_manager import logger
"""

import os
import re
import sys
import logging
import logging.handlers
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
import threading
import functools


class SensitiveDataFilter(logging.Filter):
    """敏感信息过滤器"""
    
    SENSITIVE_PATTERNS = [
        (r'(api[_-]?key["\s:=]+["\']?)([\w\-\.]+)', r'\1***REDACTED***'),
        (r'(password["\s:=]+["\']?)([\w\-\.]+)', r'\1***REDACTED***'),
        (r'(token["\s:=]+["\']?)([\w\-\.]+)', r'\1***REDACTED***'),
        (r'(secret["\s:=]+["\']?)([\w\-\.]+)', r'\1***REDACTED***'),
        (r'(sk-[a-zA-Z0-9]{20,})', r'sk-***REDACTED***'),
        (r'(Bearer\s+)([\w\-\.]+)', r'\1***REDACTED***'),
    ]
    
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self._sanitize(record.msg)
        if hasattr(record, 'args') and record.args:
            if isinstance(record.args, dict):
                record.args = {k: self._sanitize(str(v)) if isinstance(v, str) else v 
                              for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(self._sanitize(str(a)) if isinstance(a, str) else a 
                                   for a in record.args)
        return True
    
    def _sanitize(self, text: str) -> str:
        for pattern, replacement in self.SENSITIVE_PATTERNS:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        return text


class ContextFormatter(logging.Formatter):
    """上下文格式化器"""
    
    def __init__(self, fmt: str = None, datefmt: str = None, style: str = '%'):
        default_fmt = '%(asctime)s [%(levelname)s] %(name)s:%(lineno)d - %(message)s'
        super().__init__(fmt or default_fmt, datefmt, style)
    
    def format(self, record: logging.LogRecord) -> str:
        record.thread_name = threading.current_thread().name
        return super().format(record)


class ColoredConsoleFormatter(logging.Formatter):
    """彩色控制台格式化器"""
    
    COLORS = {
        'DEBUG': '\033[36m',
        'INFO': '\033[32m',
        'WARNING': '\033[33m',
        'ERROR': '\033[31m',
        'CRITICAL': '\033[35m',
    }
    RESET = '\033[0m'
    
    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, '')
        record.levelname = f"{color}{record.levelname}{self.RESET}"
        return super().format(record)


class LogManager:
    """日志管理器"""
    
    _instance: Optional['LogManager'] = None
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
        
        self._log_dir: Optional[Path] = None
        self._app_name: str = "AI短剧编辑器"
        self._loggers: Dict[str, logging.Logger] = {}
        self._sensitive_filter = SensitiveDataFilter()
        self._root_logger: Optional[logging.Logger] = None
    
    def setup(
        self,
        app_name: str = "AI短剧编辑器",
        log_dir: str = None,
        console_level: int = logging.INFO,
        file_level: int = logging.DEBUG,
        max_bytes: int = 10 * 1024 * 1024,
        backup_count: int = 5,
        enable_console: bool = True,
        enable_file: bool = True,
    ) -> logging.Logger:
        self._app_name = app_name
        
        if log_dir:
            self._log_dir = Path(log_dir)
        else:
            self._log_dir = Path.cwd() / "logs"
        
        self._log_dir.mkdir(parents=True, exist_ok=True)
        
        self._root_logger = logging.getLogger(app_name)
        self._root_logger.setLevel(logging.DEBUG)
        
        self._root_logger.handlers.clear()
        
        self._root_logger.addFilter(self._sensitive_filter)
        
        if enable_console:
            self._add_console_handler(console_level)
        
        if enable_file:
            self._add_file_handler(file_level, max_bytes, backup_count)
        
        logging.getLogger().handlers.clear()
        logging.getLogger().setLevel(logging.WARNING)
        
        self._loggers[app_name] = self._root_logger
        
        return self._root_logger
    
    def _add_console_handler(self, level: int):
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(level)
        handler.setFormatter(ColoredConsoleFormatter(
            '%(asctime)s [%(levelname)s] %(name)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))
        self._root_logger.addHandler(handler)
    
    def _add_file_handler(self, level: int, max_bytes: int, backup_count: int):
        log_file = self._log_dir / f"app_{datetime.now().strftime('%Y%m%d')}.log"
        
        handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        handler.setLevel(level)
        handler.setFormatter(ContextFormatter(
            '%(asctime)s [%(levelname)s] %(name)s:%(lineno)d - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))
        self._root_logger.addHandler(handler)
    
    def get_logger(self, name: str = None) -> logging.Logger:
        if name is None:
            return self._root_logger or logging.getLogger(self._app_name)
        
        if name in self._loggers:
            return self._loggers[name]
        
        logger = logging.getLogger(f"{self._app_name}.{name}")
        logger.setLevel(logging.DEBUG)
        logger.addFilter(self._sensitive_filter)
        
        self._loggers[name] = logger
        return logger
    
    def log_exception(self, logger: logging.Logger, message: str, exc: Exception = None):
        if exc:
            logger.error(f"{message}: {type(exc).__name__}: {exc}", exc_info=True)
        else:
            logger.error(message, exc_info=True)
    
    def get_log_files(self) -> list:
        if not self._log_dir:
            return []
        return list(self._log_dir.glob("*.log"))
    
    def cleanup_old_logs(self, days: int = 30):
        if not self._log_dir:
            return
        
        cutoff = datetime.now().timestamp() - (days * 24 * 60 * 60)
        
        for log_file in self._log_dir.glob("*.log*"):
            if log_file.stat().st_mtime < cutoff:
                try:
                    log_file.unlink()
                except Exception:
                    pass
    
    def get_stats(self) -> Dict[str, Any]:
        return {
            "log_dir": str(self._log_dir) if self._log_dir else None,
            "app_name": self._app_name,
            "loggers_count": len(self._loggers),
            "log_files": [str(f) for f in self.get_log_files()],
        }


log_manager = LogManager()


def setup_logging(**kwargs) -> logging.Logger:
    return log_manager.setup(**kwargs)


def get_logger(name: str = None) -> logging.Logger:
    return log_manager.get_logger(name)


def log_function_call(logger: logging.Logger = None):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            nonlocal logger
            if logger is None:
                logger = get_logger(func.__module__)
            
            logger.debug(f"调用 {func.__name__}(args={len(args)}, kwargs={list(kwargs.keys())})")
            try:
                result = func(*args, **kwargs)
                logger.debug(f"完成 {func.__name__}")
                return result
            except Exception as e:
                logger.exception(f"异常 {func.__name__}: {e}")
                raise
        return wrapper
    return decorator

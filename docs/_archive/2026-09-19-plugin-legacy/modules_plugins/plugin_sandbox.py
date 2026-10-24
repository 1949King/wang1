"""
插件安全沙箱
============
提供受限的代码执行环境，防止恶意插件代码访问系统资源。
"""

import builtins
import os
import logging
from typing import Set, Dict, Any, Optional

logger = logging.getLogger(__name__)

# 白名单：允许插件使用的内置函数
_ALLOWED_BUILTINS: Set[str] = {
    # 基本类型
    'True', 'False', 'None',
    'int', 'float', 'str', 'bool', 'bytes', 'bytearray',
    'list', 'tuple', 'dict', 'set', 'frozenset',
    'len', 'range', 'enumerate', 'zip', 'map', 'filter', 'iter', 'next',
    'sorted', 'reversed', 'slice',
    # 数学运算
    'abs', 'min', 'max', 'sum', 'round', 'pow', 'divmod',
    # 字符串
    'format', 'repr', 'ascii', 'chr', 'ord',
    # 类型转换
    'type', 'isinstance', 'issubclass', 'hasattr', 'getattr',
    'callable', 'id', 'hash',
    # 异常
    'Exception', 'ValueError', 'TypeError', 'KeyError', 'IndexError',
    'AttributeError', 'RuntimeError', 'NotImplementedError',
    'super', 'object', 'property', 'staticmethod', 'classmethod',
    # 迭代
    'any', 'all',
    # 输出（受限）
    'print',
}

# 明确禁止的危险函数
_BLOCKED_BUILTINS: Set[str] = {
    'exec', 'eval', 'compile', '__import__',
    'open', 'input',
    'globals', 'locals', 'vars',
    'breakpoint',
    'memoryview',
    'help', 'copyright', 'credits', 'license',
}

# 禁止在插件代码中出现的危险模式
_DANGEROUS_PATTERNS = [
    'import os', 'import sys', 'import subprocess', 'import shutil',
    'import socket', 'import http', 'import urllib',
    'import ctypes', 'import multiprocessing',
    'import pickle', 'import marshal',
    '__import__', 'exec(', 'eval(', 'compile(',
    'open(', 'globals()', 'locals()',
    'getattr(__builtins__', 'getattr(__builtins__',
    '__subclasses__', '__bases__', '__mro__',
    '._module', '__globals__', '__code__',
    'os.', 'sys.', 'subprocess.',
    'rm -rf', 'del /', 'format c:',
    'shutdown', 'reboot',
]


def validate_plugin_code(code: str) -> tuple:
    """验证插件代码安全性，返回(是否安全, 错误信息)"""
    if not code or not code.strip():
        return False, "插件代码为空"
    
    code_lower = code.lower()
    
    for pattern in _DANGEROUS_PATTERNS:
        if pattern.lower() in code_lower:
            return False, f"检测到危险代码模式: '{pattern}'"
    
    # 检查代码大小限制
    if len(code) > 500 * 1024:  # 500KB
        return False, "插件代码超过大小限制(500KB)"
    
    return True, ""


def create_sandbox_globals(extra_globals: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """创建沙箱全局命名空间，只包含白名单内置函数"""
    sandbox_builtins = {}
    
    for name in _ALLOWED_BUILTINS:
        if hasattr(builtins, name):
            sandbox_builtins[name] = getattr(builtins, name)
    
    # 提供一个受限的 print
    original_print = builtins.print
    
    def sandbox_print(*args, **kwargs):
        kwargs.pop('file', None)  # 禁止输出重定向
        original_print(*args, **kwargs)
    
    sandbox_builtins['print'] = sandbox_print
    
    sandbox_globals = {
        '__builtins__': sandbox_builtins,
        '__name__': '__plugin_sandbox__',
    }
    
    if extra_globals:
        sandbox_globals.update(extra_globals)
    
    return sandbox_globals

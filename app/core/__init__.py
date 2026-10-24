"""
核心模块包
=========

包含配置管理、安全工具、缓存系统、异步客户端、测试框架

惰性 re-export（PEP 562）
-------------------------
本文件原为「全量 eager re-export」：任何人 import `app.core` 的任何子模块，
都会连带加载 config_manager / security / cache_system / ai_engine / llm_editor /
test_base 六个重模块。实测这一跳约 **0.58s**，其中 `ai_engine` 一条链还会把
`numpy`(0.139s) 与 `cv2`(0.233s) 整个拖进来：

    app/core/__init__.py  → from .ai_engine import (...)
      → ai_engine.py:1387 ai_engine = AIEngineEnhanced()   ← 模块级实例化
        → :1107 _init_default_adapters()
          ├─ :1112 → voice_generator.py:6  import numpy
          └─ :1143 → ai_enhanced.py:308 → :62 → import cv2

而全库 AST 普查确认：这 49 个 re-export 名 **没有任何消费方**——所有调用都走
`from app.core.<子模块> import ...`（126 个不同子模块）。也就是说这一整块
既是启动期纯负担，又是零收益。

现改为 PEP 562 模块级 `__getattr__` 惰性转发：

* `from app.core import ConfigManager` —— 语法不变，真实 import 推迟到首次访问
* `from app.core import canvas_gen_jobs` —— 子模块取用不受影响（见 __getattr__ 兜底）
* `from app.core.config_manager import config` —— 完全不受本文件影响

与 `app/modules/lego/modules.py` 的改造是同一模式。
"""

import importlib as _importlib
import os as _os
from typing import Tuple

_PKG_DIR = _os.path.dirname(_os.path.abspath(__file__))

# 名字 -> (子模块, 真实属性名)
_LAZY_REEXPORTS: dict[str, Tuple[str, str]] = {
    # ---- 配置管理 ----
    "ConfigManager": (".config_manager", "ConfigManager"),
    "SecureStorage": (".config_manager", "SecureStorage"),
    "APIConfig": (".config_manager", "APIConfig"),
    "PathConfig": (".config_manager", "PathConfig"),
    "ProcessingConfig": (".config_manager", "ProcessingConfig"),
    "CacheConfig": (".config_manager", "CacheConfig"),
    "SecurityConfig": (".config_manager", "SecurityConfig"),
    "config": (".config_manager", "config"),
    # ---- 安全工具 ----
    "PasswordHasher": (".security", "PasswordHasher"),
    "InputValidator": (".security", "InputValidator"),
    "LoginAttemptManager": (".security", "LoginAttemptManager"),
    "SecureToken": (".security", "SecureToken"),
    "DataSanitizer": (".security", "DataSanitizer"),
    "ValidationResult": (".security", "ValidationResult"),
    "login_attempt_manager": (".security", "login_attempt_manager"),
    # ---- 缓存系统 ----
    "LRUCache": (".cache_system", "LRUCache"),
    "LFUCache": (".cache_system", "LFUCache"),
    "DiskCache": (".cache_system", "DiskCache"),
    "HybridCache": (".cache_system", "HybridCache"),
    "cached": (".cache_system", "cached"),
    "hybrid_cache": (".cache_system", "hybrid_cache"),
    # ---- 异步客户端（可选依赖 aiohttp） ----
    "AsyncHTTPClient": (".async_client", "AsyncHTTPClient"),
    "RequestConfig": (".async_client", "RequestConfig"),
    "Response": (".async_client", "Response"),
    "run_async": (".async_client", "run_async"),
    "async_to_sync": (".async_client", "async_to_sync"),
    "http_client": (".async_client", "http_client"),
    # ---- AI 引擎 ----
    "AIEngine": (".ai_engine", "AIEngine"),
    "AISession": (".ai_engine", "AISession"),
    "AICallRecord": (".ai_engine", "AICallRecord"),
    "ProviderStats": (".ai_engine", "ProviderStats"),
    "ai_engine": (".ai_engine", "ai_engine"),
    # ---- LLM 编辑器 ----
    "LLMEditor": (".llm_editor", "LLMEditor"),
    "EditCommand": (".llm_editor", "EditCommand"),
    "ParseResult": (".llm_editor", "ParseResult"),
    "llm_editor": (".llm_editor", "llm_editor"),
    # ---- 测试框架（生产零消费；原先却强制每次启动加载 unittest + asyncio） ----
    "TestBase": (".test_base", "TestBase"),
    "AsyncTestBase": (".test_base", "AsyncTestBase"),
    "TestRunner": (".test_base", "TestRunner"),
    "Benchmark": (".test_base", "Benchmark"),
    "MockResponse": (".test_base", "MockResponse"),
    "MockSession": (".test_base", "MockSession"),
    "async_test": (".test_base", "async_test"),
    "test_case": (".test_base", "test_case"),
    "skip_if": (".test_base", "skip_if"),
    "timeout": (".test_base", "timeout"),
}

# 可选依赖：原实现在模块级 try/except ImportError 决定，现改为按需探测
_ASYNC_CLIENT_MODULE = ".async_client"


def _is_submodule(name: str) -> bool:
    """判断 name 是否对应包内的真实子模块（.py 或目录）。"""
    if name.startswith("_"):
        return False
    return (_os.path.isfile(_os.path.join(_PKG_DIR, name + ".py"))
            or _os.path.isdir(_os.path.join(_PKG_DIR, name)))


def __getattr__(name: str):
    """PEP 562：按需转发 re-export 名与子模块。

    仅当属性在本模块中不存在时才被调用。子模块兜底分支保证
    `from app.core import canvas_gen_jobs` 这类「从包取子模块」的写法
    （属性查找失败后本应由 import 机制回退，这里主动加速）依旧可用。
    """
    if name == "ASYNC_CLIENT_AVAILABLE":
        try:
            _importlib.import_module(_ASYNC_CLIENT_MODULE, __package__)
            value = True
        except ImportError:
            value = False
        globals()[name] = value
        return value

    target = _LAZY_REEXPORTS.get(name)
    if target is not None:
        submodule, attr = target
        try:
            mod = _importlib.import_module(submodule, __package__)
        except ImportError:
            # 与原实现对齐：async_client 缺 aiohttp 时原代码把相关名字置 None
            if submodule == _ASYNC_CLIENT_MODULE:
                globals()[name] = None
                return None
            raise
        value = getattr(mod, attr)
        globals()[name] = value          # 首次解析后缓存，后续零开销
        return value

    # 子模块兜底：app.core.xxx 以属性形式访问时自动导入
    if _is_submodule(name):
        mod = _importlib.import_module("." + name, __package__)
        globals()[name] = mod
        return mod

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    """让 dir(app.core) 仍能列出全部惰性名（保持可发现性/IDE 补全）。"""
    return sorted(set(globals().keys())
                  | set(_LAZY_REEXPORTS.keys())
                  | {"ASYNC_CLIENT_AVAILABLE"})


__all__ = [
    # 配置管理
    "ConfigManager",
    "SecureStorage",
    "APIConfig",
    "PathConfig",
    "ProcessingConfig",
    "CacheConfig",
    "SecurityConfig",
    "config",

    # 安全工具
    "PasswordHasher",
    "InputValidator",
    "LoginAttemptManager",
    "SecureToken",
    "DataSanitizer",
    "ValidationResult",
    "login_attempt_manager",

    # 缓存系统
    "LRUCache",
    "LFUCache",
    "DiskCache",
    "HybridCache",
    "cached",
    "hybrid_cache",

    # 异步客户端 (可选)
    "AsyncHTTPClient",
    "RequestConfig",
    "Response",
    "run_async",
    "async_to_sync",
    "http_client",
    "ASYNC_CLIENT_AVAILABLE",

    # AI 引擎
    "AIEngine",
    "AISession",
    "AICallRecord",
    "ProviderStats",
    "ai_engine",
    "LLMEditor",
    "EditCommand",
    "ParseResult",
    "llm_editor",

    # 测试框架
    "TestBase",
    "AsyncTestBase",
    "TestRunner",
    "Benchmark",
    "MockResponse",
    "MockSession",
    "async_test",
    "test_case",
    "skip_if",
    "timeout",
]

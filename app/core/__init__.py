"""
核心模块包
=========

包含配置管理、安全工具、缓存系统、异步客户端、测试框架
"""

from .config_manager import (
    ConfigManager,
    SecureStorage,
    APIConfig,
    PathConfig,
    ProcessingConfig,
    CacheConfig,
    SecurityConfig,
    config,
)

from .security import (
    PasswordHasher,
    InputValidator,
    LoginAttemptManager,
    SecureToken,
    DataSanitizer,
    ValidationResult,
    login_attempt_manager,
)

from .cache_system import (
    LRUCache,
    LFUCache,
    DiskCache,
    HybridCache,
    cached,
    hybrid_cache,
)

try:
    from .async_client import (
        AsyncHTTPClient,
        RequestConfig,
        Response,
        run_async,
        async_to_sync,
        http_client,
    )
    ASYNC_CLIENT_AVAILABLE = True
except ImportError:
    ASYNC_CLIENT_AVAILABLE = False
    AsyncHTTPClient = None
    RequestConfig = None
    Response = None
    run_async = None
    async_to_sync = None
    http_client = None

from .test_base import (
    TestBase,
    AsyncTestBase,
    TestRunner,
    Benchmark,
    MockResponse,
    MockSession,
    async_test,
    test_case,
    skip_if,
    timeout,
)

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

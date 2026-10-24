"""认证服务 AuthService 测试 (pytest 风格)

覆盖 P0-A/P0-B: bcrypt 密码哈希、旧哈希自动升级、登录失败锁定。
仅测纯逻辑, 绕过单例与 SQLite 落盘, 避免污染 app/data/auth.db。
运行: pytest app/tests/test_auth.py -v
"""

import hashlib
import threading

import pytest

from app.modules.lego import auth as auth_mod
from app.modules.lego.auth import AuthService


@pytest.fixture
def auth_service():
    """构造隔离的 AuthService，绕过单例与 SQLite 落盘，仅测纯逻辑"""
    service = object.__new__(AuthService)
    service._login_failures = {}
    service._failures_lock = threading.Lock()
    return service


class TestPasswordHashing:
    """密码哈希与验证测试"""

    def test_hash_format(self, auth_service):
        hashed = auth_service._hash_password("password123")
        assert isinstance(hashed, str)
        if auth_mod._HAS_BCRYPT:
            assert hashed.startswith("$2")
        else:
            assert hashed.startswith("sha256$")

    def test_hash_is_salted(self, auth_service):
        """相同密码应产生不同哈希（随机盐）"""
        assert auth_service._hash_password("same123") != auth_service._hash_password("same123")

    def test_verify_correct(self, auth_service):
        hashed = auth_service._hash_password("correct123")
        ok, _ = auth_service._verify_password("correct123", hashed)
        assert ok is True

    def test_verify_wrong(self, auth_service):
        hashed = auth_service._hash_password("correct123")
        ok, _ = auth_service._verify_password("wrong123", hashed)
        assert ok is False

    def test_legacy_sha256_auto_upgrade(self, auth_service):
        """旧版无盐 SHA256 密码应能验证并在 bcrypt 可用时返回升级哈希"""
        legacy = hashlib.sha256("legacy123".encode()).hexdigest()
        ok, new_hash = auth_service._verify_password("legacy123", legacy)
        assert ok is True
        if auth_mod._HAS_BCRYPT:
            assert new_hash is not None and new_hash.startswith("$2")

    def test_sha256_salt_format_verify(self, auth_service):
        salt = "a" * 32
        digest = hashlib.sha256(("pwd123456" + salt).encode()).hexdigest()
        stored = f"sha256${salt}${digest}"
        ok, _ = auth_service._verify_password("pwd123456", stored)
        assert ok is True


class TestLoginLockout:
    """登录失败锁定测试"""

    def test_lockout_after_max_attempts(self, auth_service):
        for _ in range(AuthService.MAX_LOGIN_ATTEMPTS):
            auth_service._record_login_failure("lock_user")
        locked, msg = auth_service._check_login_lockout("lock_user")
        assert locked is True
        assert "分钟" in msg

    def test_failure_cleared_on_success(self, auth_service):
        auth_service._record_login_failure("clear_user")
        auth_service._clear_login_failures("clear_user")
        locked, _ = auth_service._check_login_lockout("clear_user")
        assert locked is False


class TestInputValidation:
    """输入校验测试"""

    def test_phone_valid(self, auth_service):
        assert auth_service._validate_phone("13812345678") is True

    def test_phone_invalid(self, auth_service):
        assert auth_service._validate_phone("12345") is False

    def test_email_qq_only(self, auth_service):
        assert auth_service._validate_email("user@qq.com") is True
        assert auth_service._validate_email("user@gmail.com") is False

    def test_generate_code_six_digits(self, auth_service):
        code = auth_service._generate_code()
        assert len(code) == 6 and code.isdigit()
"""
安全模块测试 (pytest 风格)

运行: pytest app/tests/test_security.py -v
"""

import pytest
from core.security import (
    PasswordHasher,
    InputValidator,
    LoginAttemptManager,
    SecureToken,
    DataSanitizer,
)


class TestPasswordHasher:
    """密码哈希测试"""
    
    def test_hash_and_verify(self):
        password = "TestPassword123!"
        hashed = PasswordHasher.hash(password)
        
        assert isinstance(hashed, str)
        assert len(hashed) > 0
        assert PasswordHasher.verify(password, hashed)
    
    def test_verify_wrong_password(self):
        password = "CorrectPassword123"
        hashed = PasswordHasher.hash(password)
        assert not PasswordHasher.verify("WrongPassword", hashed)
    
    def test_different_passwords_different_hashes(self):
        """相同密码应产生不同的哈希值（因为有随机盐）"""
        password = "SamePassword123"
        hash1 = PasswordHasher.hash(password)
        hash2 = PasswordHasher.hash(password)
        assert hash1 != hash2
    
    def test_needs_rehash(self):
        old_hash = "salt:hash_value"
        assert PasswordHasher.needs_rehash(old_hash)
        
        new_hash = PasswordHasher.hash("password123")
        assert not PasswordHasher.needs_rehash(new_hash)


class TestInputValidator:
    """输入验证测试"""
    
    def test_validate_password_valid(self):
        result = InputValidator.validate_password(
            "SecurePass123",
            min_length=8, require_upper=True,
            require_lower=True, require_digit=True,
        )
        assert result.is_valid
    
    def test_validate_password_too_short(self):
        result = InputValidator.validate_password("Short1", min_length=8)
        assert not result.is_valid
        assert "密码长度" in result.errors[0]
    
    def test_validate_password_no_digit(self):
        result = InputValidator.validate_password(
            "NoDigitPassword", require_digit=True
        )
        assert not result.is_valid
    
    def test_validate_phone_valid(self):
        assert InputValidator.validate_phone("13812345678").is_valid
    
    def test_validate_phone_invalid(self):
        assert not InputValidator.validate_phone("12345").is_valid
    
    def test_validate_email_valid(self):
        assert InputValidator.validate_email("test@example.com").is_valid
    
    def test_validate_email_invalid(self):
        assert not InputValidator.validate_email("invalid-email").is_valid
    
    def test_validate_username_valid(self):
        assert InputValidator.validate_username("user123").is_valid
    
    def test_validate_username_too_short(self):
        assert not InputValidator.validate_username("a").is_valid
    
    def test_sanitize_input(self):
        dirty = "  <script>alert('xss')</script>  "
        clean = InputValidator.sanitize_input(dirty)
        assert clean.strip() == "<script>alert('xss')</script>"
    
    def test_validate_integer_valid(self):
        result = InputValidator.validate_integer(50, min_val=0, max_val=100)
        assert result.is_valid
    
    def test_validate_integer_out_of_range(self):
        result = InputValidator.validate_integer(150, min_val=0, max_val=100)
        assert not result.is_valid


class TestLoginAttemptManager:
    """登录尝试管理测试"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        self.manager = LoginAttemptManager()
    
    def test_record_attempt(self):
        allowed, remaining = self.manager.record_attempt("test_user")
        assert allowed
        assert remaining == 4
    
    def test_lockout_after_max_attempts(self):
        identifier = "lockout_test_user"
        for _ in range(5):
            self.manager.record_attempt(identifier)
        
        allowed, remaining = self.manager.record_attempt(identifier)
        assert not allowed
        assert remaining > 0
    
    def test_reset(self):
        identifier = "reset_test_user"
        for _ in range(3):
            self.manager.record_attempt(identifier)
        
        self.manager.reset(identifier)
        is_locked, _ = self.manager.is_locked(identifier)
        assert not is_locked


class TestSecureToken:
    """安全令牌测试"""
    
    def test_generate(self):
        token = SecureToken.generate()
        assert isinstance(token, str)
        assert len(token) > 0
    
    def test_generate_unique(self):
        token1 = SecureToken.generate()
        token2 = SecureToken.generate()
        assert token1 != token2
    
    def test_generate_numeric(self):
        token = SecureToken.generate_numeric(6)
        assert len(token) == 6
        assert token.isdigit()
    
    def test_session_token(self):
        token = SecureToken.generate_session_token()
        assert SecureToken.verify_session_token(token)
    
    def test_verify_expired_session_token(self):
        old_token = "1000.abc123"
        assert not SecureToken.verify_session_token(old_token, max_age=1)


class TestDataSanitizer:
    """数据脱敏测试"""
    
    def test_mask_phone(self):
        masked = DataSanitizer.mask_phone("13812345678")
        assert masked == "138****5678"
    
    def test_mask_email(self):
        masked = DataSanitizer.mask_email("test@example.com")
        assert "***" in masked
        assert "@" in masked
    
    def test_mask_api_key(self):
        masked = DataSanitizer.mask_api_key("sk-1234567890abcdef")
        assert masked == "sk-1***cdef"

"""
安全模块测试
"""

import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.test_base import TestBase
from core.security import (
    PasswordHasher,
    InputValidator,
    LoginAttemptManager,
    SecureToken,
    DataSanitizer,
)


class TestPasswordHasher(TestBase):
    """密码哈希测试"""
    
    def test_hash_and_verify(self):
        password = "TestPassword123!"
        hashed = PasswordHasher.hash(password)
        
        self.assertIsInstance(hashed, str)
        self.assertTrue(len(hashed) > 0)
        self.assertTrue(PasswordHasher.verify(password, hashed))
    
    def test_verify_wrong_password(self):
        password = "CorrectPassword123"
        hashed = PasswordHasher.hash(password)
        
        self.assertFalse(PasswordHasher.verify("WrongPassword", hashed))
    
    def test_different_passwords_different_hashes(self):
        password = "SamePassword123"
        hash1 = PasswordHasher.hash(password)
        hash2 = PasswordHasher.hash(password)
        
        self.assertNotEqual(hash1, hash2)
    
    def test_needs_rehash(self):
        old_hash = "salt:hash_value"
        self.assertTrue(PasswordHasher.needs_rehash(old_hash))
        
        new_hash = PasswordHasher.hash("password123")
        self.assertFalse(PasswordHasher.needs_rehash(new_hash))


class TestInputValidator(TestBase):
    """输入验证测试"""
    
    def test_validate_password_valid(self):
        result = InputValidator.validate_password(
            "SecurePass123",
            min_length=8,
            require_upper=True,
            require_lower=True,
            require_digit=True,
        )
        self.assertTrue(result.is_valid)
    
    def test_validate_password_too_short(self):
        result = InputValidator.validate_password("Short1", min_length=8)
        self.assertFalse(result.is_valid)
        self.assertIn("密码长度", result.errors[0])
    
    def test_validate_password_no_digit(self):
        result = InputValidator.validate_password(
            "NoDigitPassword",
            require_digit=True
        )
        self.assertFalse(result.is_valid)
    
    def test_validate_phone_valid(self):
        result = InputValidator.validate_phone("13812345678")
        self.assertTrue(result.is_valid)
    
    def test_validate_phone_invalid(self):
        result = InputValidator.validate_phone("12345")
        self.assertFalse(result.is_valid)
    
    def test_validate_email_valid(self):
        result = InputValidator.validate_email("test@example.com")
        self.assertTrue(result.is_valid)
    
    def test_validate_email_invalid(self):
        result = InputValidator.validate_email("invalid-email")
        self.assertFalse(result.is_valid)
    
    def test_validate_username_valid(self):
        result = InputValidator.validate_username("user123")
        self.assertTrue(result.is_valid)
    
    def test_validate_username_too_short(self):
        result = InputValidator.validate_username("a")
        self.assertFalse(result.is_valid)
    
    def test_sanitize_input(self):
        dirty = "  <script>alert('xss')</script>  "
        clean = InputValidator.sanitize_input(dirty)
        
        self.assertEqual(clean.strip(), "<script>alert('xss')</script>")
    
    def test_validate_integer_valid(self):
        result = InputValidator.validate_integer(50, min_val=0, max_val=100)
        self.assertTrue(result.is_valid)
    
    def test_validate_integer_out_of_range(self):
        result = InputValidator.validate_integer(150, min_val=0, max_val=100)
        self.assertFalse(result.is_valid)


class TestLoginAttemptManager(TestBase):
    """登录尝试管理测试"""
    
    def setUp(self):
        super().setUp()
        self.manager = LoginAttemptManager()
    
    def test_record_attempt(self):
        allowed, remaining = self.manager.record_attempt("test_user")
        self.assertTrue(allowed)
        self.assertEqual(remaining, 4)
    
    def test_lockout_after_max_attempts(self):
        identifier = "lockout_test_user"
        
        for _ in range(5):
            self.manager.record_attempt(identifier)
        
        allowed, remaining = self.manager.record_attempt(identifier)
        self.assertFalse(allowed)
        self.assertGreater(remaining, 0)
    
    def test_reset(self):
        identifier = "reset_test_user"
        
        for _ in range(3):
            self.manager.record_attempt(identifier)
        
        self.manager.reset(identifier)
        
        is_locked, _ = self.manager.is_locked(identifier)
        self.assertFalse(is_locked)


class TestSecureToken(TestBase):
    """安全令牌测试"""
    
    def test_generate(self):
        token = SecureToken.generate()
        self.assertIsInstance(token, str)
        self.assertTrue(len(token) > 0)
    
    def test_generate_unique(self):
        token1 = SecureToken.generate()
        token2 = SecureToken.generate()
        self.assertNotEqual(token1, token2)
    
    def test_generate_numeric(self):
        token = SecureToken.generate_numeric(6)
        self.assertEqual(len(token), 6)
        self.assertTrue(token.isdigit())
    
    def test_session_token(self):
        token = SecureToken.generate_session_token()
        self.assertTrue(SecureToken.verify_session_token(token))
    
    def test_verify_expired_session_token(self):
        old_token = "1000.abc123"
        self.assertFalse(SecureToken.verify_session_token(old_token, max_age=1))


class TestDataSanitizer(TestBase):
    """数据脱敏测试"""
    
    def test_mask_phone(self):
        masked = DataSanitizer.mask_phone("13812345678")
        self.assertEqual(masked, "138****5678")
    
    def test_mask_email(self):
        masked = DataSanitizer.mask_email("test@example.com")
        self.assertIn("***", masked)
        self.assertIn("@", masked)
    
    def test_mask_api_key(self):
        masked = DataSanitizer.mask_api_key("sk-1234567890abcdef")
        self.assertEqual(masked, "sk-1***cdef")


if __name__ == '__main__':
    unittest.main(verbosity=2)

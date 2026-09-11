"""secure_store 加密存储模块测试 (pytest 风格)

覆盖 P0-C: 平台凭证 / 会话文件 PII 加密落盘能力。
运行: pytest app/tests/test_secure_store.py -v
"""

import pytest
from pathlib import Path

# 缺少 cryptography 时跳过（secure_store 会降级为明文，无法验证加密路径）
pytest.importorskip("cryptography.fernet")

from app.core import secure_store


@pytest.fixture
def fixed_key(monkeypatch):
    """注入固定 Fernet 密钥，避免测试写入真实用户级 secret.key 文件"""
    from cryptography.fernet import Fernet

    fernet = Fernet(Fernet.generate_key())
    monkeypatch.setattr(secure_store, "_FERNET_INSTANCE", fernet)
    monkeypatch.setattr(secure_store, "_fernet", lambda: fernet)
    return fernet


class TestEncryptedFileRecognition:
    """加密文件后缀识别测试"""

    def test_enc_json_suffix_recognized(self):
        assert secure_store._is_encrypted_file(Path("session.enc.json")) is True
        assert secure_store._is_encrypted_file(Path("a.enc.json")) is True

    def test_plain_json_not_encrypted(self):
        assert secure_store._is_encrypted_file(Path("session.json")) is False


class TestStringCrypto:
    """字符串加解密往返测试"""

    def test_roundtrip(self, fixed_key):
        plain = "hello-中国-123"
        cipher = secure_store._encrypt_str(plain)
        assert cipher != plain
        assert secure_store._decrypt_str(cipher) == plain


class TestSecureJson:
    """安全 JSON 落盘/加载测试"""

    def test_save_and_load_roundtrip(self, fixed_key, tmp_path):
        path = tmp_path / "data.enc.json"
        data = {"session_id": "abc", "nickname": "张三"}
        assert secure_store.save_secure_json(str(path), data) is True
        assert secure_store.load_secure_json(str(path)) == data

    def test_ciphertext_hides_pii(self, fixed_key, tmp_path):
        """密文不得包含明文敏感信息"""
        path = tmp_path / "d.enc.json"
        secure_store.save_secure_json(str(path), {"token": "topsecret123"})
        raw = path.read_text(encoding="utf-8")
        assert "topsecret123" not in raw

    def test_rejects_plain_path(self, fixed_key, tmp_path):
        """明文路径必须被拒绝，避免误以为已加密"""
        path = tmp_path / "data.json"
        assert secure_store.save_secure_json(str(path), {"a": 1}) is False

    def test_load_missing_returns_none(self, tmp_path):
        assert secure_store.load_secure_json(str(tmp_path / "none.enc.json")) is None
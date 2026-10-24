# -*- coding: utf-8 -*-
"""SecureStorage Fernet 升级 + 旧格式迁移 + 损坏隔离（V4.46.1 安全刀）。

全部用 tmp_path 重定向存储文件，绝不碰用户真实 secrets.enc。
"""
import base64
import json

import pytest

from app.core.config_manager import SecureStorage

LEGACY_NONCE = b"\x00" * 16


@pytest.fixture()
def store_path(tmp_path):
    return tmp_path / "secrets.enc"


@pytest.fixture()
def storage(store_path, monkeypatch):
    SecureStorage._instance = None
    monkeypatch.setattr(SecureStorage, "_get_storage_path", lambda self: store_path)
    obj = SecureStorage()
    yield obj
    SecureStorage._instance = None


def _fernet_available(storage) -> bool:
    return storage._get_fernet() is not None


def test_fernet_roundtrip_and_marker(storage, store_path):
    if not _fernet_available(storage):
        pytest.skip("cryptography 不可用 ⇒ 回退 XOR 路径另行覆盖")
    storage.set("k1", "sk-secret-1")
    storage.set("k2", "sk-secret-2")
    raw = store_path.read_bytes()
    assert raw.startswith(SecureStorage._ENC_MARKER), "新存储必须带 sgv2: 标记"
    assert b"sk-secret-1" not in raw, "密文里不得出现明文 Key"
    SecureStorage._instance = None
    reloaded = SecureStorage()
    assert reloaded.get("k1") == "sk-secret-1"
    assert reloaded.get("k2") == "sk-secret-2"


def test_legacy_xor_file_migrates_transparently(store_path, monkeypatch):
    SecureStorage._instance = None
    monkeypatch.setattr(SecureStorage, "_get_storage_path", lambda self: store_path)
    first = SecureStorage()
    # 手工造一份升级前的旧 XOR 密文：base64(nonce + 逐字节 XOR)
    key = first._key
    data = json.dumps({"deepseek_api_key": "sk-legacy-abc"}).encode("utf-8")
    cipher = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
    store_path.write_bytes(base64.b64encode(LEGACY_NONCE + cipher))

    SecureStorage._instance = None
    migrated = SecureStorage()
    assert migrated.get("deepseek_api_key") == "sk-legacy-abc", "旧文件必须能读出"
    if _fernet_available(migrated):
        assert store_path.read_bytes().startswith(SecureStorage._ENC_MARKER), \
            "读旧文件成功后应透明迁移为 sgv2"
    else:
        pytest.skip("cryptography 不可用 ⇒ 保持旧格式（回退路径）")


def test_corrupt_file_is_quarantined_not_silently_emptied(store_path, monkeypatch):
    SecureStorage._instance = None
    monkeypatch.setattr(SecureStorage, "_get_storage_path", lambda self: store_path)
    junk = base64.b64encode(b"\x9a" * 64)
    store_path.write_bytes(junk)

    st = SecureStorage()
    assert st.get("anything") == ""
    assert not store_path.exists(), "损坏文件不应留在原路径（会被反复当有效数据读）"
    quarantined = list(store_path.parent.glob("secrets.corrupt-*.enc"))
    assert quarantined, "损坏文件应改名 .corrupt-<ts> 保留（可人工找回，不删数据）"
    assert quarantined[0].read_bytes() == junk


def test_decrypt_failure_logs_error_level(storage, caplog):
    if not _fernet_available(storage):
        pytest.skip("cryptography 不可用 ⇒ Fernet 分支不执行")
    with caplog.at_level("ERROR"):
        assert storage._decrypt(b"sgv2:not-base64-at-all") == ""
    assert any("解密失败" in r.message for r in caplog.records), "失败必须 ERROR 级可见"


def test_set_get_delete_roundtrip(storage, store_path):
    storage.set("openai_api_key", "sk-oai-xyz")
    assert storage.get("openai_api_key") == "sk-oai-xyz"
    assert store_path.read_bytes() != b""
    storage.delete("openai_api_key")
    assert storage.get("openai_api_key") == ""

# -*- coding: utf-8 -*-
"""密钥保存诚实失败（V4.46.3 · 修「保存成功重启却没 Key」）。

锁死三件事：
1. SecureStorage.set 返回落盘成败（False=磁盘写失败）；
2. cloud_api.save_configs 在写失败时抛 RuntimeError 且**不给失败渠道写 encrypted 标记**
   （旧行为：先标 encrypted 再谎报成功 ⇒ 重启读回空 = 密钥凭空消失）；
3. 成功渠道的标记不受失败渠道牵连（部分成功也如实记录）。
"""
import json

import pytest

import app.modules.lego.cloud_api as ca
from app.core.config_manager import SecureStorage


class _FailingStorage:
    """模拟磁盘不可写（如被安全软件/沙箱拦截）。"""

    def __init__(self, fail_keys: set[str]):
        self.fail_keys = fail_keys
        self.written: dict[str, str] = {}

    def set(self, key, value):
        if key in self.fail_keys:
            return False
        self.written[key] = value
        return True


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    """构造脱离单例的 CloudAPIService，配置路径钉到 tmp。"""
    obj = ca.CloudAPIService.__new__(ca.CloudAPIService)
    obj._initialized = True
    obj._configs = {}
    obj._providers = {}
    obj._registry = ca.default_registry
    obj._ollama_client = None
    monkeypatch.setattr(obj, "_config_path", lambda: str(tmp_path / "api_configs.json"))
    return obj, tmp_path


def test_secure_storage_set_returns_bool(tmp_path, monkeypatch):
    SecureStorage._instance = None
    monkeypatch.setattr(
        SecureStorage, "_get_storage_path", lambda self: tmp_path / "secrets.enc"
    )
    st = SecureStorage()
    assert st.set("k", "v") is True
    # 目标不可写（目录被删成文件）⇒ 返回 False 而不是静默
    bad_path = tmp_path / "blocked"
    bad_path.write_text("not a dir")
    st._storage_path = bad_path / "secrets.enc"
    assert st.set("k2", "v2") is False
    SecureStorage._instance = None


def test_save_raises_and_no_marker_on_failure(svc):
    obj, tmp = svc
    from app.modules.lego.cloud_providers.base import APIConfig

    obj._configs["deepseek"] = APIConfig(
        provider="deepseek", api_key="sk-real", base_url="u", model="m"
    )
    failing = _FailingStorage({"api_key:deepseek"})
    obj._get_secure_storage = lambda: failing
    with pytest.raises(RuntimeError, match="未持久化"):
        obj.save_configs()
    data = json.loads((tmp / "api_configs.json").read_text(encoding="utf-8"))
    # 关键：失败渠道绝不能标 encrypted（标了=重启读空=丢 Key）
    assert data["deepseek"]["api_key"] == ""
    assert failing.written == {}


def test_partial_failure_markers_honest(svc):
    obj, tmp = svc
    from app.modules.lego.cloud_providers.base import APIConfig

    obj._configs["deepseek"] = APIConfig(
        provider="deepseek", api_key="sk-ok", base_url="u", model="m"
    )
    obj._configs["kimi"] = APIConfig(provider="kimi", api_key="sk-bad", base_url="u", model="m")
    failing = _FailingStorage({"api_key:kimi"})
    obj._get_secure_storage = lambda: failing
    with pytest.raises(RuntimeError, match="kimi"):
        obj.save_configs()
    data = json.loads((tmp / "api_configs.json").read_text(encoding="utf-8"))
    assert data["deepseek"]["api_key"] == "encrypted"   # 成功渠道如实标记
    assert data["kimi"]["api_key"] == ""                # 失败渠道如实为空
    assert failing.written.get("api_key:deepseek") == "sk-ok"


def test_success_path_unchanged(svc):
    obj, tmp = svc
    from app.modules.lego.cloud_providers.base import APIConfig

    obj._configs["deepseek"] = APIConfig(
        provider="deepseek", api_key="sk-good", base_url="u", model="m"
    )
    ok_storage = _FailingStorage(set())
    obj._get_secure_storage = lambda: ok_storage
    obj.save_configs()  # 不抛
    data = json.loads((tmp / "api_configs.json").read_text(encoding="utf-8"))
    assert data["deepseek"]["api_key"] == "encrypted"
    assert ok_storage.written["api_key:deepseek"] == "sk-good"

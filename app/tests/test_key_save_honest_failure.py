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


# ── V4.46.5：加密存储「整体不可用」这一支（审计 2026-10-23 CWE-312）──────────────
# 上面几条覆盖了「存储可用但写盘失败」；本组覆盖 _get_secure_storage() 返回 None。
# 旧行为：`if secure and config.api_key` 短路进 else ⇒ 明文 Key 直写 api_configs.json，
# UI 照样弹「✅ 已保存」——既是明文落盘，又是「失败伪装成成功」。


def test_unavailable_storage_refuses_plaintext(svc):
    obj, tmp = svc
    from app.modules.lego.cloud_providers.base import APIConfig

    obj._configs["deepseek"] = APIConfig(
        provider="deepseek", api_key="sk-secret", base_url="u", model="m"
    )
    obj._get_secure_storage = lambda: None
    with pytest.raises(RuntimeError, match="拒绝保存"):
        obj.save_configs()
    data = json.loads((tmp / "api_configs.json").read_text(encoding="utf-8"))
    # 关键：明文密钥绝不允许出现在磁盘上
    assert data["deepseek"]["api_key"] == ""
    blob = (tmp / "api_configs.json").read_text(encoding="utf-8")
    assert "sk-secret" not in blob


def test_unavailable_storage_preserves_existing_marker(svc):
    """存储本次不可用 ≠ 上次没存成功：已有 encrypted 标记不能被抹掉。

    抹成 "" 会把上次已加密保存的密钥挡在门外（重启显示未配置），
    等于用「修 bug」的名义制造第二次同类事故。
    """
    obj, tmp = svc
    from app.modules.lego.cloud_providers.base import APIConfig

    (tmp / "api_configs.json").write_text(
        json.dumps({"deepseek": {"api_key": "encrypted", "base_url": "u",
                                 "model": "m", "max_tokens": 1, "temperature": 0.5,
                                 "top_p": 0.5}}),
        encoding="utf-8",
    )
    obj._configs["deepseek"] = APIConfig(
        provider="deepseek", api_key="sk-new", base_url="u", model="m"
    )
    obj._get_secure_storage = lambda: None
    with pytest.raises(RuntimeError, match="加密存储当前不可用"):
        obj.save_configs()
    data = json.loads((tmp / "api_configs.json").read_text(encoding="utf-8"))
    assert data["deepseek"]["api_key"] == "encrypted"      # 保留，未被覆盖成 ""
    assert "sk-new" not in json.dumps(data)


def test_unavailable_storage_ok_when_no_keys(svc):
    """没有密钥要存时不该惊动用户：正常落盘、不抛错。"""
    obj, tmp = svc
    from app.modules.lego.cloud_providers.base import APIConfig

    obj._configs["ollama"] = APIConfig(
        provider="ollama", api_key="", base_url="http://127.0.0.1:11434", model="m"
    )
    obj._get_secure_storage = lambda: None
    obj.save_configs()  # 不抛
    data = json.loads((tmp / "api_configs.json").read_text(encoding="utf-8"))
    assert data["ollama"]["api_key"] == ""


def test_marker_is_never_used_as_key(svc):
    """读回侧：存储不可用时 "encrypted" 标记不能被当成 API Key。

    旧写法 `if api_key == "encrypted" and secure` 在 secure=None 时整条短路，
    字面量 "encrypted" 留在 api_key 上 ⇒ 渠道显示「已配置」、请求期才炸，
    且绕过 get_provider 的 `if not config.api_key` 空值判据。
    """
    obj, tmp = svc
    (tmp / "api_configs.json").write_text(
        json.dumps({"deepseek": {"api_key": "encrypted", "base_url": "u",
                                 "model": "m", "max_tokens": 1, "temperature": 0.5,
                                 "top_p": 0.5}}),
        encoding="utf-8",
    )
    obj._get_secure_storage = lambda: None
    obj._load_configs()
    cfg = obj._configs["deepseek"]
    assert cfg.api_key != "encrypted"
    assert cfg.api_key == ""
    assert obj.get_provider("deepseek") is None   # 真被判为未配置


def test_secure_storage_init_crash_degrades_not_explodes(svc, monkeypatch):
    """SecureStorage() 构造抛错也要降级成 None（旧版只接 ImportError ⇒ 整个保存炸掉）。"""
    obj, tmp = svc
    import app.core.config_manager as cm

    def _boom():
        raise OSError("密钥库被占用")

    monkeypatch.setattr(cm.SecureStorage, "__new__", lambda cls: _boom(), raising=False)
    # _get_secure_storage 内部 import 后构造；构造异常应被吞成 None
    assert obj._get_secure_storage() is None

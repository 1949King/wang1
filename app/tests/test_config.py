"""
配置管理模块测试 (pytest 风格)

运行: pytest app/tests/test_config.py -v
"""

import pytest
from app.core.config_manager import ConfigManager, SecureStorage


class TestConfigManager:
    """配置管理器测试"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        # 重置单例以避免测试间污染
        ConfigManager._instance = None
        self.config = ConfigManager()
    
    def test_singleton(self):
        config1 = ConfigManager()
        config2 = ConfigManager()
        assert config1 is config2
    
    def test_api_config(self):
        assert hasattr(self.config, 'api')
        assert hasattr(self.config.api, 'deepseek_api_key')
    
    def test_path_config(self):
        assert hasattr(self.config, 'paths')
        assert hasattr(self.config.paths, 'output_path')
    
    def test_processing_config(self):
        assert hasattr(self.config, 'processing')
        assert self.config.processing.cpu_threads > 0
    
    def test_get_api_key(self):
        key = self.config.get_api_key('deepseek')
        assert isinstance(key, str)
    
    def test_validate(self):
        errors = self.config.validate()
        assert isinstance(errors, list)
    
    def test_to_dict(self):
        data = self.config.to_dict()
        assert isinstance(data, dict)
        assert 'api' in data
        assert 'paths' in data


class TestSecureStorage:
    """安全存储测试

    卫生：必须用 tmp_path 重定向存储文件——原实现直接写真·实
    `%APPDATA%\\AI短剧编辑器\\secure\\secrets.enc`，把测试假 Key 写进用户真实密钥库，
    还会把已存的真密钥覆盖掉（test_set_and_get / test_delete 各写盘一次）。
    """

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path, monkeypatch):
        # 重置单例 + 把存储文件钉到临时目录（绝不碰真实 AppData）
        SecureStorage._instance = None
        monkeypatch.setattr(
            SecureStorage, "_get_storage_path",
            lambda self: tmp_path / "secrets.enc",
        )
        self.storage = SecureStorage()
    
    def test_singleton(self):
        storage1 = SecureStorage()
        storage2 = SecureStorage()
        assert storage1 is storage2
    
    def test_set_and_get(self):
        self.storage.set("test_api_key_123", "sk-test-secret-key")
        retrieved = self.storage.get("test_api_key_123")
        assert retrieved == "sk-test-secret-key"
    
    def test_get_nonexistent(self):
        result = self.storage.get("nonexistent_key_xyz", "default_value")
        assert result == "default_value"
    
    def test_delete(self):
        self.storage.set("test_delete_key", "value")
        self.storage.delete("test_delete_key")
        result = self.storage.get("test_delete_key")
        assert result == ""

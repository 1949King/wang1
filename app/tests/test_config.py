"""
配置管理模块测试
"""

import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.test_base import TestBase
from core.config_manager import ConfigManager, SecureStorage, config


class TestConfigManager(TestBase):
    """配置管理器测试"""
    
    def setUp(self):
        super().setUp()
        self.config = ConfigManager()
    
    def test_singleton(self):
        config1 = ConfigManager()
        config2 = ConfigManager()
        self.assertIs(config1, config2)
    
    def test_api_config(self):
        self.assertIsInstance(self.config.api, object)
        self.assertTrue(hasattr(self.config.api, 'deepseek_api_key'))
    
    def test_path_config(self):
        self.assertIsInstance(self.config.paths, object)
        self.assertTrue(hasattr(self.config.paths, 'output_path'))
    
    def test_processing_config(self):
        self.assertIsInstance(self.config.processing, object)
        self.assertGreater(self.config.processing.cpu_threads, 0)
    
    def test_get_api_key(self):
        key = self.config.get_api_key('deepseek')
        self.assertIsInstance(key, str)
    
    def test_validate(self):
        errors = self.config.validate()
        self.assertIsInstance(errors, list)
    
    def test_to_dict(self):
        data = self.config.to_dict()
        self.assertIsInstance(data, dict)
        self.assertIn('api', data)
        self.assertIn('paths', data)


class TestSecureStorage(TestBase):
    """安全存储测试"""
    
    def setUp(self):
        super().setUp()
        self.storage = SecureStorage()
    
    def test_singleton(self):
        storage1 = SecureStorage()
        storage2 = SecureStorage()
        self.assertIs(storage1, storage2)
    
    def test_set_and_get(self):
        test_key = "test_api_key_123"
        test_value = "sk-test-secret-key"
        
        self.storage.set(test_key, test_value)
        retrieved = self.storage.get(test_key)
        
        self.assertEqual(retrieved, test_value)
    
    def test_get_nonexistent(self):
        result = self.storage.get("nonexistent_key_xyz", "default_value")
        self.assertEqual(result, "default_value")
    
    def test_delete(self):
        test_key = "test_delete_key"
        self.storage.set(test_key, "value")
        
        self.storage.delete(test_key)
        result = self.storage.get(test_key)
        
        self.assertEqual(result, "")


if __name__ == '__main__':
    unittest.main(verbosity=2)

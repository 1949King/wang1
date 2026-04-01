"""
缓存系统测试
"""

import unittest
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.test_base import TestBase
from core.cache_system import LRUCache, LFUCache, HybridCache, cached


class TestLRUCache(TestBase):
    """LRU缓存测试"""
    
    def setUp(self):
        super().setUp()
        self.cache = LRUCache(max_size=3, default_ttl=60)
    
    def test_set_and_get(self):
        self.cache.set("key1", "value1")
        result = self.cache.get("key1")
        self.assertEqual(result, "value1")
    
    def test_get_nonexistent(self):
        result = self.cache.get("nonexistent")
        self.assertIsNone(result)
    
    def test_eviction(self):
        self.cache.set("key1", "value1")
        self.cache.set("key2", "value2")
        self.cache.set("key3", "value3")
        self.cache.set("key4", "value4")
        
        result = self.cache.get("key1")
        self.assertIsNone(result)
        
        result = self.cache.get("key4")
        self.assertEqual(result, "value4")
    
    def test_lru_order(self):
        self.cache.set("key1", "value1")
        self.cache.set("key2", "value2")
        self.cache.set("key3", "value3")
        
        self.cache.get("key1")
        
        self.cache.set("key4", "value4")
        
        self.assertIsNotNone(self.cache.get("key1"))
        self.assertIsNone(self.cache.get("key2"))
    
    def test_delete(self):
        self.cache.set("key1", "value1")
        self.cache.delete("key1")
        result = self.cache.get("key1")
        self.assertIsNone(result)
    
    def test_clear(self):
        self.cache.set("key1", "value1")
        self.cache.set("key2", "value2")
        self.cache.clear()
        
        self.assertIsNone(self.cache.get("key1"))
        self.assertIsNone(self.cache.get("key2"))
    
    def test_stats(self):
        self.cache.set("key1", "value1")
        self.cache.get("key1")
        self.cache.get("nonexistent")
        
        stats = self.cache.stats()
        self.assertEqual(stats["size"], 1)
        self.assertEqual(stats["hits"], 1)
        self.assertEqual(stats["misses"], 1)


class TestLFUCache(TestBase):
    """LFU缓存测试"""
    
    def setUp(self):
        super().setUp()
        self.cache = LFUCache(max_size=3, default_ttl=60)
    
    def test_set_and_get(self):
        self.cache.set("key1", "value1")
        result = self.cache.get("key1")
        self.assertEqual(result, "value1")
    
    def test_access_count(self):
        self.cache.set("key1", "value1")
        self.cache.get("key1")
        self.cache.get("key1")
        self.cache.get("key1")
        
        self.cache.set("key2", "value2")
        self.cache.set("key3", "value3")
        self.cache.set("key4", "value4")
        
        self.assertIsNotNone(self.cache.get("key1"))


class TestHybridCache(TestBase):
    """混合缓存测试"""
    
    def setUp(self):
        super().setUp()
        self.cache = HybridCache(memory_max_items=10, disk_max_mb=10)
    
    def test_set_and_get(self):
        self.cache.set("key1", "value1")
        result = self.cache.get("key1")
        self.assertEqual(result, "value1")
    
    def test_stats(self):
        self.cache.set("key1", "value1")
        stats = self.cache.stats()
        
        self.assertIn("memory", stats)
        self.assertIn("disk", stats)


class TestCachedDecorator(TestBase):
    """缓存装饰器测试"""
    
    def test_cached_function(self):
        call_count = 0
        
        @cached(ttl=60)
        def expensive_function(n):
            nonlocal call_count
            call_count += 1
            return n * 2
        
        result1 = expensive_function(5)
        result2 = expensive_function(5)
        
        self.assertEqual(result1, 10)
        self.assertEqual(result2, 10)
        self.assertEqual(call_count, 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)

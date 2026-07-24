"""
缓存系统测试 (pytest 风格)

运行: pytest app/tests/test_cache.py -v
"""

import pytest
from core.cache_system import LRUCache, LFUCache, HybridCache, cached


class TestLRUCache:
    """LRU缓存测试"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        self.cache = LRUCache(max_size=3, default_ttl=60)
    
    def test_set_and_get(self):
        self.cache.set("key1", "value1")
        assert self.cache.get("key1") == "value1"
    
    def test_get_nonexistent(self):
        assert self.cache.get("nonexistent") is None
    
    def test_eviction(self):
        self.cache.set("key1", "value1")
        self.cache.set("key2", "value2")
        self.cache.set("key3", "value3")
        self.cache.set("key4", "value4")
        
        assert self.cache.get("key1") is None
        assert self.cache.get("key4") == "value4"
    
    def test_lru_order(self):
        self.cache.set("key1", "value1")
        self.cache.set("key2", "value2")
        self.cache.set("key3", "value3")
        
        # 访问 key1 使其变成最近使用
        self.cache.get("key1")
        
        # 插入新 key，最久未使用的 key2 应被淘汰
        self.cache.set("key4", "value4")
        
        assert self.cache.get("key1") is not None
        assert self.cache.get("key2") is None
    
    def test_delete(self):
        self.cache.set("key1", "value1")
        self.cache.delete("key1")
        assert self.cache.get("key1") is None
    
    def test_clear(self):
        self.cache.set("key1", "value1")
        self.cache.set("key2", "value2")
        self.cache.clear()
        assert self.cache.get("key1") is None
        assert self.cache.get("key2") is None
    
    def test_stats(self):
        self.cache.set("key1", "value1")
        self.cache.get("key1")
        self.cache.get("nonexistent")
        
        stats = self.cache.stats()
        assert stats["size"] == 1
        assert stats["hits"] == 1
        assert stats["misses"] == 1


class TestLFUCache:
    """LFU缓存测试"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        self.cache = LFUCache(max_size=3, default_ttl=60)
    
    def test_set_and_get(self):
        self.cache.set("key1", "value1")
        assert self.cache.get("key1") == "value1"
    
    def test_access_count_priority(self):
        """高频访问的 key 应被保留"""
        self.cache.set("key1", "value1")
        self.cache.get("key1")
        self.cache.get("key1")
        self.cache.get("key1")
        
        self.cache.set("key2", "value2")
        self.cache.set("key3", "value3")
        self.cache.set("key4", "value4")
        
        # key1 访问最频繁，应保留
        assert self.cache.get("key1") is not None


class TestHybridCache:
    """混合缓存测试"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        self.cache = HybridCache(memory_max_items=10, disk_max_mb=10)
    
    def test_set_and_get(self):
        self.cache.set("key1", "value1")
        assert self.cache.get("key1") == "value1"
    
    def test_stats(self):
        self.cache.set("key1", "value1")
        stats = self.cache.stats()
        assert "memory" in stats
        assert "disk" in stats


class TestCachedDecorator:
    """缓存装饰器测试"""
    
    def test_cached_function(self):
        call_count = [0]  # 使用列表以在闭包中可变
        
        @cached(ttl=60)
        def expensive_function(n):
            call_count[0] += 1
            return n * 2
        
        result1 = expensive_function(5)
        result2 = expensive_function(5)
        
        assert result1 == 10
        assert result2 == 10
        assert call_count[0] == 1  # 只调用了一次

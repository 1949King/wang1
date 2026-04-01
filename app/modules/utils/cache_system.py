import time

class CacheSystem:
    """缓存系统"""
    def __init__(self, max_size=1024, default_ttl=3600):
        self.cache = {}
        self.max_size = max_size
        self.default_ttl = default_ttl  # 默认缓存过期时间（秒）
        self.access_times = {}  # 最后访问时间
        self.creation_times = {}  # 创建时间
    
    def get(self, key):
        """获取缓存项"""
        # 检查缓存是否过期
        if key in self.cache:
            # 检查是否过期
            if time.time() - self.creation_times[key] > self.default_ttl:
                # 缓存过期，移除
                self._remove_key(key)
                return None
            
            # 更新访问时间
            self.access_times[key] = time.time()
            return self.cache[key]
        return None
    
    def set(self, key, value, ttl=None):
        """设置缓存项"""
        # 使用默认TTL或指定TTL
        item_ttl = ttl if ttl is not None else self.default_ttl
        
        # 检查缓存大小
        if len(self.cache) >= self.max_size:
            # 移除最久未使用的项
            self._evict_items()
        
        # 添加新项
        self.cache[key] = value
        self.access_times[key] = time.time()
        self.creation_times[key] = time.time()
    
    def _remove_key(self, key):
        """移除缓存项"""
        if key in self.cache:
            del self.cache[key]
        if key in self.access_times:
            del self.access_times[key]
        if key in self.creation_times:
            del self.creation_times[key]
    
    def _evict_items(self):
        """缓存替换策略：移除最久未使用的项"""
        # 先移除过期项
        expired_keys = []
        current_time = time.time()
        for key in self.cache:
            if current_time - self.creation_times[key] > self.default_ttl:
                expired_keys.append(key)
        
        for key in expired_keys:
            self._remove_key(key)
        
        # 如果还是满的，移除最久未使用的项
        if len(self.cache) >= self.max_size:
            oldest_key = min(self.access_times, key=lambda k: self.access_times[k])
            self._remove_key(oldest_key)
    
    def clear(self):
        """清空缓存"""
        self.cache.clear()
        self.access_times.clear()
        self.creation_times.clear()
    
    def size(self):
        """获取缓存大小"""
        # 清理过期项后返回大小
        self._cleanup_expired()
        return len(self.cache)
    
    def _cleanup_expired(self):
        """清理过期缓存项"""
        expired_keys = []
        current_time = time.time()
        for key in self.cache:
            if current_time - self.creation_times[key] > self.default_ttl:
                expired_keys.append(key)
        
        for key in expired_keys:
            self._remove_key(key)
    
    def contains(self, key):
        """检查缓存是否包含指定键"""
        if key in self.cache:
            # 检查是否过期
            if time.time() - self.creation_times[key] > self.default_ttl:
                self._remove_key(key)
                return False
            return True
        return False
    
    def remove(self, key):
        """移除指定缓存项"""
        self._remove_key(key)
    
    def get_stats(self):
        """获取缓存统计信息"""
        self._cleanup_expired()
        return {
            "size": len(self.cache),
            "max_size": self.max_size,
            "default_ttl": self.default_ttl,
            "items": list(self.cache.keys())
        }

# 全局缓存实例
cache_system = CacheSystem()

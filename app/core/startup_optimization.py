"""
延迟导入管理器
================
实现模块的延迟加载，优化启动时间
"""

import importlib
import threading
import logging
from typing import Dict, Optional, Any, Callable
from functools import wraps
import time

from app.core.logging_enhanced import monitor_performance

logger = logging.getLogger(__name__)


class LazyImportManager:
    """延迟导入管理器"""
    
    def __init__(self):
        self._modules: Dict[str, Any] = {}
        self._module_locks: Dict[str, threading.Lock] = {}
        self._lock = threading.Lock()
        self._import_stats: Dict[str, Dict[str, Any]] = {}
        
        self._preload_modules = [
            'PyQt6.QtCore',
            'PyQt6.QtWidgets',
            'PyQt6.QtGui',
        ]
    
    def get_module(self, module_path: str, preload: bool = False) -> Any:
        """获取模块，延迟加载
        
        Args:
            module_path: 模块路径
            preload: 是否预加载
        
        Returns:
            模块对象
        """
        if module_path in self._modules:
            return self._modules[module_path]
        
        # 获取或创建模块锁
        with self._lock:
            if module_path not in self._module_locks:
                self._module_locks[module_path] = threading.Lock()
            module_lock = self._module_locks[module_path]
        
        # 使用模块锁确保线程安全
        with module_lock:
            # 双重检查
            if module_path in self._modules:
                return self._modules[module_path]
            
            start_time = time.time()
            
            try:
                module = importlib.import_module(module_path)
                self._modules[module_path] = module
                
                # 记录导入统计
                import_time = time.time() - start_time
                self._import_stats[module_path] = {
                    'import_time': import_time,
                    'import_count': 1,
                    'last_import': time.time()
                }
                
                logger.debug(f"延迟导入模块: {module_path} (耗时: {import_time:.3f}s)")
                return module
                
            except ImportError as e:
                logger.error(f"模块导入失败: {module_path} - {e}")
                raise
            except Exception as e:
                logger.error(f"模块导入异常: {module_path} - {e}")
                raise
    
    def preload_essential_modules(self):
        """预加载关键模块"""
        logger.info("开始预加载关键模块...")
        
        for module_path in self._preload_modules:
            try:
                start_time = time.time()
                module = self.get_module(module_path, preload=True)
                load_time = time.time() - start_time
                logger.info(f"预加载模块: {module_path} (耗时: {load_time:.3f}s)")
            except Exception as e:
                logger.warning(f"预加载模块失败: {module_path} - {e}")
        
        logger.info("关键模块预加载完成")
    
    def get_import_stats(self) -> Dict[str, Dict[str, Any]]:
        """获取导入统计信息"""
        return self._import_stats.copy()
    
    def clear_cache(self):
        """清空模块缓存"""
        with self._lock:
            self._modules.clear()
            self._import_stats.clear()
            logger.info("模块缓存已清空")


class LazyLoader:
    """延迟加载器装饰器"""
    
    def __init__(self, module_path: str, attribute_name: Optional[str] = None):
        self.module_path = module_path
        self.attribute_name = attribute_name
        self._module: Optional[Any] = None
    
    def __call__(self, func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if self._module is None:
                lazy_manager = get_lazy_import_manager()
                self._module = lazy_manager.get_module(self.module_path)
            
            if self.attribute_name:
                return func(getattr(self._module, self.attribute_name), *args, **kwargs)
            else:
                return func(self._module, *args, **kwargs)
        
        return wrapper
    
    def load(self):
        """立即加载模块"""
        if self._module is None:
            lazy_manager = get_lazy_import_manager()
            self._module = lazy_manager.get_module(self.module_path)
        return self._module


def lazy_import(module_path: str, attribute_name: Optional[str] = None):
    """延迟导入装饰器
    
    Args:
        module_path: 模块路径
        attribute_name: 属性名称（可选）
    
    Returns:
        装饰器函数
    """
    return LazyLoader(module_path, attribute_name)


class ModuleInitializer:
    """模块初始化器"""
    
    def __init__(self):
        self._initialized_modules: set = set()
        self._init_order: list = []
        self._init_dependencies: Dict[str, list] = {}
        self._lock = threading.Lock()
    
    def register_module(self, module_name: str, dependencies: Optional[list] = None):
        """注册模块及其依赖关系
        
        Args:
            module_name: 模块名称
            dependencies: 依赖的模块列表
        """
        with self._lock:
            self._init_dependencies[module_name] = dependencies or []
            logger.debug(f"注册模块: {module_name}, 依赖: {dependencies}")
    
    def initialize_modules(self, module_names: Optional[list] = None) -> bool:
        """初始化模块
        
        Args:
            module_names: 要初始化的模块列表，如果为None则初始化所有注册的模块
        
        Returns:
            是否全部初始化成功
        """
        if module_names is None:
            module_names = list(self._init_dependencies.keys())
        
        # 拓扑排序确定初始化顺序
        init_order = self._topological_sort(module_names)
        
        success = True
        for module_name in init_order:
            try:
                self._initialize_single_module(module_name)
            except Exception as e:
                logger.error(f"模块初始化失败: {module_name} - {e}")
                success = False
        
        return success
    
    def _topological_sort(self, module_names: list) -> list:
        """拓扑排序确定初始化顺序"""
        visited = set()
        temp_visited = set()
        result = []
        
        def visit(module_name):
            if module_name in temp_visited:
                raise ValueError(f"检测到循环依赖: {module_name}")
            
            if module_name not in visited:
                temp_visited.add(module_name)
                
                dependencies = self._init_dependencies.get(module_name, [])
                for dep in dependencies:
                    if dep in module_names:
                        visit(dep)
                
                temp_visited.remove(module_name)
                visited.add(module_name)
                result.append(module_name)
        
        for module_name in module_names:
            if module_name not in visited:
                visit(module_name)
        
        return result
    
    def _initialize_single_module(self, module_name: str):
        """初始化单个模块"""
        if module_name in self._initialized_modules:
            logger.debug(f"模块已初始化: {module_name}")
            return
        
        start_time = time.time()
        
        try:
            # 这里可以调用模块的初始化函数
            # 例如：module.init()
            logger.info(f"初始化模块: {module_name}")
            
            self._initialized_modules.add(module_name)
            self._init_order.append(module_name)
            
            init_time = time.time() - start_time
            logger.info(f"模块初始化完成: {module_name} (耗时: {init_time:.3f}s)")
            
        except Exception as e:
            logger.error(f"模块初始化异常: {module_name} - {e}")
            raise
    
    def get_initialized_modules(self) -> list:
        """获取已初始化的模块列表"""
        return list(self._initialized_modules)
    
    def get_init_order(self) -> list:
        """获取初始化顺序"""
        return self._init_order.copy()


class ConfigCache:
    """配置缓存，避免重复解析"""
    
    _instance = None
    _config = None
    _config_mtime = 0
    _config_path = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        self._cache: Dict[str, Any] = {}
        self._watchers: Dict[str, float] = {}
        self._cache_hits = 0
        self._cache_misses = 0
    
    def load_config(self, config_path: str, force_reload: bool = False) -> Dict[str, Any]:
        """加载配置文件
        
        Args:
            config_path: 配置文件路径
            force_reload: 是否强制重新加载
        
        Returns:
            配置字典
        """
        import json
        import os
        
        with self._lock:
            # 检查文件是否修改
            current_mtime = os.path.getmtime(config_path) if os.path.exists(config_path) else 0
            
            if not force_reload and self._config == self._config_path and current_mtime <= self._config_mtime:
                self._cache_hits += 1
                logger.debug(f"配置缓存命中: {config_path}")
                return self._cache
            
            self._cache_misses += 1
            logger.info(f"加载配置文件: {config_path}")
            
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    self._cache = json.load(f)
                
                self._config_path = config_path
                self._config_mtime = current_mtime
                
                logger.info(f"配置加载成功: {len(self._cache)} 项配置")
                return self._cache
                
            except Exception as e:
                logger.error(f"配置加载失败: {config_path} - {e}")
                raise
    
    def get_config(self, key: str, default: Any = None) -> Any:
        """获取配置项
        
        Args:
            key: 配置键
            default: 默认值
        
        Returns:
            配置值
        """
        with self._lock:
            if self._cache is None:
                logger.warning("配置未加载，返回默认值")
                return default
            
            value = self._cache.get(key, default)
            logger.debug(f"获取配置: {key} = {value}")
            return value
    
    def set_config(self, key: str, value: Any):
        """设置配置项
        
        Args:
            key: 配置键
            value: 配置值
        """
        with self._lock:
            if self._cache is None:
                self._cache = {}
            
            self._cache[key] = value
            logger.debug(f"设置配置: {key} = {value}")
    
    def save_config(self, config_path: Optional[str] = None):
        """保存配置到文件
        
        Args:
            config_path: 配置文件路径，如果为None则使用上次加载的路径
        """
        import json
        
        if config_path is None:
            config_path = self._config_path
        
        if config_path is None:
            raise ValueError("未指定配置文件路径")
        
        with self._lock:
            try:
                with open(config_path, 'w', encoding='utf-8') as f:
                    json.dump(self._cache, f, ensure_ascii=False, indent=2)
                
                self._config_path = config_path
                logger.info(f"配置保存成功: {config_path}")
                
            except Exception as e:
                logger.error(f"配置保存失败: {config_path} - {e}")
                raise
    
    def clear_cache(self):
        """清空配置缓存"""
        with self._lock:
            self._cache.clear()
            self._config = None
            self._config_mtime = 0
            logger.info("配置缓存已清空")
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        with self._lock:
            total_requests = self._cache_hits + self._cache_misses
            hit_rate = self._cache_hits / total_requests if total_requests > 0 else 0
            
            return {
                'cache_hits': self._cache_hits,
                'cache_misses': self._cache_misses,
                'hit_rate': f"{hit_rate:.2%}",
                'config_loaded': self._config is not None,
                'config_path': self._config_path
            }


# 全局实例
_lazy_import_manager: Optional[LazyImportManager] = None
_module_initializer: Optional[ModuleInitializer] = None
_config_cache: Optional[ConfigCache] = None


def get_lazy_import_manager() -> LazyImportManager:
    """获取全局延迟导入管理器"""
    global _lazy_import_manager
    
    if _lazy_import_manager is None:
        _lazy_import_manager = LazyImportManager()
    
    return _lazy_import_manager


def get_module_initializer() -> ModuleInitializer:
    """获取全局模块初始化器"""
    global _module_initializer
    
    if _module_initializer is None:
        _module_initializer = ModuleInitializer()
    
    return _module_initializer


def get_config_cache() -> ConfigCache:
    """获取全局配置缓存"""
    global _config_cache
    
    if _config_cache is None:
        _config_cache = ConfigCache()
    
    return _config_cache


def initialize_startup_optimization():
    """初始化启动优化"""
    logger.info("初始化启动优化...")
    
    # 预加载关键模块
    lazy_manager = get_lazy_import_manager()
    lazy_manager.preload_essential_modules()
    
    # 初始化配置缓存
    config_cache = get_config_cache()
    
    logger.info("启动优化初始化完成")


@monitor_performance(threshold_warning=0.5, threshold_critical=2.0)
def optimized_import(module_path: str) -> Any:
    """优化的导入函数
    
    Args:
        module_path: 模块路径
    
    Returns:
        模块对象
    """
    lazy_manager = get_lazy_import_manager()
    return lazy_manager.get_module(module_path)
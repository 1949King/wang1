"""
cache_manager_refactor.py
=========================
B2 回滚标记 (2026-05-31):
原计划删除本文件 (与 cache_manager.py 类名重复),
但被 core/asset_manager.py:10 实际引用, 删除导致应用启动失败
回滚: 恢复原文件, 改用注释 + aliased import 解决冲突
SSOT: 推荐使用本文件的 CacheManager, 与 asset_manager 保持一致
"""
import os
from typing import List, Optional


class CacheManager:
    """缓存管理器 (重写版, 适用于 asset_manager)"""

    def __init__(self, cache_dir: str):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)

    def clean_cache(self) -> bool:
        try:
            for file in os.listdir(self.cache_dir):
                file_path = os.path.join(self.cache_dir, file)
                if os.path.isfile(file_path):
                    os.remove(file_path)
            return True
        except Exception as e:
            print(f"清理缓存失败: {e}")
            return False

    def get_cache_path(self, asset_id: str, suffix: str = "") -> str:
        if suffix:
            return os.path.join(self.cache_dir, f"{asset_id}_{suffix}")
        return os.path.join(self.cache_dir, asset_id)

    def delete_cache(self, asset_id: str) -> bool:
        try:
            path = self.get_cache_path(asset_id)
            if os.path.exists(path):
                if os.path.isfile(path):
                    os.remove(path)
                else:
                    import shutil
                    shutil.rmtree(path)
            return True
        except Exception as e:
            print(f"删除缓存失败: {e}")
            return False

    def get_cache_size(self) -> int:
        total = 0
        try:
            for dirpath, _, filenames in os.walk(self.cache_dir):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    if os.path.exists(fp):
                        total += os.path.getsize(fp)
        except Exception:
            pass
        return total

    def has_cache(self, asset_id: str) -> bool:
        return os.path.exists(self.get_cache_path(asset_id))

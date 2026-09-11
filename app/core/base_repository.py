"""
base_repository.py
==================
通用数据持久化基类 (BaseRepository)
C5 标记 (2026-05-31): 加 schema_version + migrate() 钩子
"""

import os
import json
import shutil
import threading
from typing import Dict, Any, Optional, Callable
from datetime import datetime


import logging
logger = logging.getLogger("AI短剧编辑器.core.base_repository")

# 当前 schema 版本号, 数据演进时递增
CURRENT_SCHEMA_VERSION = 1

# 默认 schema key 名 (如数据库根目录无该字段, 视为 version=0 老数据)
SCHEMA_VERSION_KEY = "_schema_version"


class BaseRepository:
    """数据持久化基类 (含 schema 版本管理)"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._data: Dict[str, Any] = {}
        # 修复 C5: 加载时检查 schema_version, 必要时迁移
        self._load_data()
        self._migrate_if_needed()

    def _load_data(self):
        """加载数据"""
        if os.path.exists(self.db_path):
            try:
                with open(self.db_path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            except Exception as e:
                logger.error(f'加载数据库失败: {e}')
                self._data = {}

    def _migrate_if_needed(self):
        """C5: 检查 schema_version, 必要时调用 _migrate(old_ver) 钩子"""
        old_ver = self._data.get(SCHEMA_VERSION_KEY, 0)
        if old_ver == CURRENT_SCHEMA_VERSION:
            return
        if old_ver > CURRENT_SCHEMA_VERSION:
            logger.info(f'⚠️ 数据库 {self.db_path} 版本 v{old_ver} > 当前 v{CURRENT_SCHEMA_VERSION}, 请升级编辑器或回滚数据')
            return

        # 备份原始数据 (C5 安全网)
        if old_ver > 0:
            backup_path = f"{self.db_path}.v{old_ver}.bak.{datetime.now().strftime('%Y%m%d%H%M%S')}"
            try:
                shutil.copy2(self.db_path, backup_path)
                logger.info(f'  📦 C5: 备份 {self.db_path} → {backup_path}')
            except Exception as e:
                logger.error(f'  ⚠️ 备份失败: {e}')

        # 调用子类钩子
        try:
            new_data = self._migrate(old_ver, CURRENT_SCHEMA_VERSION, dict(self._data))
            if new_data is not None:
                self._data = new_data
        except Exception as e:
            logger.error(f'  ❌ 迁移失败: {e}, 数据保持原样')
            return

        # 写入新版本号
        self._data[SCHEMA_VERSION_KEY] = CURRENT_SCHEMA_VERSION
        self._save_data()
        logger.info(f'  ✅ C5: {self.db_path} v{old_ver} → v{CURRENT_SCHEMA_VERSION}')

    def _migrate(self, old_ver: int, new_ver: int, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        子类覆盖此方法实现数据迁移
        默认实现: 仅加 schema_version 字段, 不改数据
        返回 None 表示放弃迁移
        """
        return data

    def _save_data(self) -> bool:
        """保存数据 (含 schema_version) - 调用方需持锁"""
        try:
            self._data.setdefault(SCHEMA_VERSION_KEY, CURRENT_SCHEMA_VERSION)
            # 原子写: 临时文件 + rename
            tmp_path = self.db_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            if os.path.exists(self.db_path):
                os.replace(tmp_path, self.db_path)
            else:
                os.rename(tmp_path, self.db_path)
            return True
        except Exception as e:
            logger.error(f'保存数据库失败: {e}')
            return False

    def get_all(self) -> Dict[str, Any]:
        """获取所有数据"""
        return self._data

    def get_by_id(self, item_id: str) -> Optional[Any]:
        """根据ID获取数据"""
        return self._data.get(item_id)

    def save(self, item_id: str, item_data: dict) -> bool:
        """保存数据"""
        with self._lock:
            self._data[item_id] = item_data
            return self._save_data()

    def delete(self, item_id: str) -> bool:
        """删除数据"""
        with self._lock:
            if item_id in self._data:
                del self._data[item_id]
                return self._save_data()
        return False

    def clear(self) -> bool:
        """清空所有数据 (保留 schema_version)"""
        with self._lock:
            version = self._data.get(SCHEMA_VERSION_KEY, CURRENT_SCHEMA_VERSION)
            self._data = {SCHEMA_VERSION_KEY: version}
            return self._save_data()

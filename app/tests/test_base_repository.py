"""
C5 单元测试: BaseRepository schema_version + migrate() 钩子
========================================================
验证:
1. 老数据 (无 _schema_version) 加载时自动迁移
2. 迁移成功后会写入新版本号
3. 已迁移数据再次加载不会重复迁移
4. 备份文件正常生成
5. clear() 保留 schema_version
"""
import sys
import json
import os
import tempfile
import importlib.util
from pathlib import Path

# 把 app/ 加进 sys.path
APP_ROOT = Path(__file__).resolve().parents[2] / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

# 直接 load base_repository.py, 避免 namespace package 问题
_br_path = APP_ROOT / "core" / "base_repository.py"
_spec = importlib.util.spec_from_file_location("base_repository_local", _br_path)
br_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(br_module)

BaseRepository = br_module.BaseRepository
CURRENT_SCHEMA_VERSION = br_module.CURRENT_SCHEMA_VERSION
SCHEMA_VERSION_KEY = br_module.SCHEMA_VERSION_KEY

import pytest


class TestBaseRepositorySchema:
    """BaseRepository schema 版本管理"""

    def setup_method(self):
        # 每个测试用独立的临时文件
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_repo.json")

    def teardown_method(self):
        # 清理临时目录
        import shutil
        if os.path.exists(self.tmpdir):
            shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_current_schema_version_is_1(self):
        """当前 schema 版本应为 1"""
        assert CURRENT_SCHEMA_VERSION == 1
        assert SCHEMA_VERSION_KEY == "_schema_version"

    def test_load_empty_file(self):
        """加载空/不存在文件应正常, version=0 → 自动迁移到 v1"""
        repo = BaseRepository(self.db_path)
        # 空文件: 数据为空, 但 schema_version=1
        assert repo.get_all().get(SCHEMA_VERSION_KEY) == CURRENT_SCHEMA_VERSION
        # 业务数据为空 (无 schema_version 这条)
        business_data = {k: v for k, v in repo.get_all().items() if k != SCHEMA_VERSION_KEY}
        assert business_data == {}

    def test_load_old_data_auto_migrate(self):
        """老数据 (无 _schema_version) 加载应自动迁移"""
        # 写入老数据 (模拟 version=0 时代的数据)
        old_data = {
            "user_001": {"name": "Alice", "score": 100},
            "user_002": {"name": "Bob", "score": 200},
        }
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump(old_data, f, ensure_ascii=False)

        # 加载 → 应自动迁移
        repo = BaseRepository(self.db_path)
        data = repo.get_all()

        # 老数据应保留
        assert data.get("user_001") == {"name": "Alice", "score": 100}
        assert data.get("user_002") == {"name": "Bob", "score": 200}
        # 新版本号应写入
        assert data.get(SCHEMA_VERSION_KEY) == CURRENT_SCHEMA_VERSION

    def test_load_already_migrated(self):
        """已迁移数据 (含 _schema_version=v1) 再次加载应直接通过"""
        # 写入已迁移数据
        migrated_data = {
            SCHEMA_VERSION_KEY: CURRENT_SCHEMA_VERSION,
            "item_1": {"x": 1},
        }
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump(migrated_data, f, ensure_ascii=False)

        # 加载 → 不应再迁移
        repo = BaseRepository(self.db_path)
        data = repo.get_all()
        assert data.get("item_1") == {"x": 1}
        assert data.get(SCHEMA_VERSION_KEY) == CURRENT_SCHEMA_VERSION

    def test_backup_created_on_migration(self):
        """v1 → v2 迁移时应生成 .bak 文件 (v0 基线不备份, v1+ 每次升级都备份)"""
        # 写入 v1 数据
        v1_data = {
            SCHEMA_VERSION_KEY: CURRENT_SCHEMA_VERSION,
            "k": "v",
        }
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump(v1_data, f, ensure_ascii=False)

        # 模拟 v1 → v2 升级 (临时改 br_module.CURRENT_SCHEMA_VERSION)
        original_ver = br_module.CURRENT_SCHEMA_VERSION
        br_module.CURRENT_SCHEMA_VERSION = 2
        try:
            repo = BaseRepository(self.db_path)
        finally:
            br_module.CURRENT_SCHEMA_VERSION = original_ver

        # 检查是否有 .v1.bak.* 文件
        parent = Path(self.db_path).parent
        bak_files = list(parent.glob(f"{Path(self.db_path).name}.v1.bak.*"))
        assert len(bak_files) == 1, f"应生成 1 个 v1 备份, 实际 {len(bak_files)}"

    def test_save_preserves_version(self):
        """save() 后 _schema_version 仍存在"""
        repo = BaseRepository(self.db_path)
        repo.save("k1", {"a": 1})
        # 重新加载
        repo2 = BaseRepository(self.db_path)
        assert repo2.get_all().get(SCHEMA_VERSION_KEY) == CURRENT_SCHEMA_VERSION
        assert repo2.get_by_id("k1") == {"a": 1}

    def test_clear_preserves_version(self):
        """clear() 后 _schema_version 仍存在 (避免下次再触发迁移)"""
        repo = BaseRepository(self.db_path)
        repo.save("k", "v")
        assert repo.clear() is True
        assert repo.get_all().get(SCHEMA_VERSION_KEY) == CURRENT_SCHEMA_VERSION
        # 重新加载不应触发迁移
        repo2 = BaseRepository(self.db_path)
        assert repo2.get_all().get(SCHEMA_VERSION_KEY) == CURRENT_SCHEMA_VERSION

    def test_atomic_write(self):
        """原子写: 临时文件 + rename"""
        repo = BaseRepository(self.db_path)
        repo.save("atomic_key", "atomic_value")

        # 检查无残留 .tmp 文件
        assert not os.path.exists(self.db_path + ".tmp"), "不应残留 .tmp"
        # 文件内容正确
        with open(self.db_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data.get("atomic_key") == "atomic_value"

    def test_subclass_migrate_hook(self):
        """子类可覆盖 _migrate() 钩子, 添加自定义迁移逻辑"""

        class V2Repo(BaseRepository):
            """模拟未来 v2 的子类"""
            pass

        # 写入老数据
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump({"old_field": "legacy"}, f, ensure_ascii=False)

        repo = V2Repo(self.db_path)
        # 基类默认 _migrate 啥也不做, 只加 version
        assert repo.get_all().get("old_field") == "legacy"
        assert repo.get_all().get(SCHEMA_VERSION_KEY) == CURRENT_SCHEMA_VERSION


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))

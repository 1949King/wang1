"""C5 测试: 直接运行, 避免输出截断"""
import sys
import os

# 把 app/ 加进 sys.path
APP_ROOT = os.path.dirname(os.path.abspath(__file__))
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from tests.test_base_repository import TestBaseRepositorySchema

TESTS = [
    "test_current_schema_version_is_1",
    "test_load_empty_file",
    "test_load_old_data_auto_migrate",
    "test_load_already_migrated",
    "test_backup_created_on_migration",
    "test_save_preserves_version",
    "test_clear_preserves_version",
    "test_atomic_write",
    "test_subclass_migrate_hook",
]

print("=" * 60)
print("C5 BaseRepository 测试")
print("=" * 60)

passed = 0
failed = []
for test_name in TESTS:
    t = TestBaseRepositorySchema()
    t.setup_method()
    try:
        getattr(t, test_name)()
        print(f"  ✅ {test_name}")
        passed += 1
    except Exception as e:
        print(f"  ❌ {test_name}: {e}")
        failed.append(test_name)
    t.teardown_method()

print("=" * 60)
print(f"总计: {passed}/{len(TESTS)} 通过")
if failed:
    print(f"失败: {failed}")
sys.exit(0 if not failed else 1)

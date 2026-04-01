"""
项目结构清理脚本 - 渐进式迁移
"""
import os
import shutil
from pathlib import Path

APP_DIR = Path(__file__).parent.resolve()
LEGACY_DIR = APP_DIR / "legacy"

print("=" * 60)
print("AI短剧编辑器 - 项目结构清理")
print("=" * 60)

# 第1步：创建 legacy 目录
print("\n第1步：创建 legacy/ 目录...")
LEGACY_DIR.mkdir(exist_ok=True)
print(f"   创建: {LEGACY_DIR}")

# 需要移动到 legacy 的旧 Tk 文件
legacy_files = [
    "ai_short_drama_editor.py",
    "ai_short_drama_editor_optimized.py",
    "ui_main.py",
    "run_lego.py",
]

# 测试文件也移到 legacy
test_files = [f for f in os.listdir(APP_DIR) if f.startswith("test_") and f.endswith(".py")]

print("\n第2步：移动旧 Tk 文件到 legacy/...")
for filename in legacy_files:
    src = APP_DIR / filename
    if src.exists():
        dst = LEGACY_DIR / filename
        shutil.move(str(src), str(dst))
        print(f"   移动: {filename}")

print("\n第3步：移动测试文件到 legacy/tests/...")
tests_dir = LEGACY_DIR / "tests"
tests_dir.mkdir(exist_ok=True)
for filename in test_files:
    src = APP_DIR / filename
    if src.exists():
        dst = tests_dir / filename
        shutil.move(str(src), str(dst))
        print(f"   移动: {filename}")

# 其他临时文件
temp_files = ["simple_test.py", "test_import.py"]
for filename in temp_files:
    src = APP_DIR / filename
    if src.exists():
        dst = tests_dir / filename
        shutil.move(str(src), str(dst))
        print(f"   移动: {filename}")

print("\n" + "=" * 60)
print("清理完成!")
print("=" * 60)
print("\n当前项目结构:")
print(f"   主程序: main_qt6.py")
print(f"   旧文件: legacy/")
print(f"   测试文件: legacy/tests/")
print("\n启动方式: python main_qt6.py")
print("=" * 60)

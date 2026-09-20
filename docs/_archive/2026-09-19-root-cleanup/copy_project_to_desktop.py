"""
项目源代码复制脚本
====================
把 AI 短剧编辑器 项目文件复制到桌面新目录
排除: venv / __pycache__ / .git / build / 第三方源码等
"""
import os
import sys
import shutil
from pathlib import Path
from datetime import datetime

# 源项目根目录
SOURCE_ROOT = Path(r"d:\本地磁盘(当前分区)(C)\Users\Administrator\Desktop\AI短剧编辑器2")

# 目标目录 (桌面)
DESKTOP = Path(r"d:\本地磁盘(当前分区)(C)\Users\Administrator\Desktop")
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
TARGET_DIR = DESKTOP / f"AI短剧编辑器2_源码副本_{TIMESTAMP}"

# 要排除的目录/文件
EXCLUDE_DIRS = {
    "venv", ".venv", "venv2", "env",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "build", "dist", ".git", ".github",
    "node_modules",
    "openshot-qt", "shotcut",       # 第三方源码
    "libopenshot", "license",       # 第三方库
    "thirdparty",
    "bmf_env", ".bmf_env",          # BMF 虚拟环境
    "packaging_env",                 # PyInstaller 环境
    "cache", ".cache",
    "temp_ai_editor",                # 临时编辑器目录
    "snapshots",                     # 快照
    "plugin_test_results",           # 测试结果
    "plugin_certificates",           # 插件证书
    "ff",                            # FFmpeg 测试目录
    "app/packaging_env",             # 嵌套 venv
    "app/venv", "app/.venv",
    "app/bgms", "app/stickers",      # 资源(太大, 不复制二进制)
    "bgms", "stickers",
    "models",                        # 模型文件太大
    "app/models",
    "output", "app/output",
    "app/temp",                      # 临时测试文件
    "app/短剧AI剪辑输出",
    "app/素材库",
    "app/运营数据",
    "app/cache",
    "app/openclow_data",
    "app/logs",
    "app/__pycache__",
    "app/core/__pycache__",
    "app/core/video_processing/__pycache__",
    "app/modules/__pycache__",
    "app/modules/lego/__pycache__",
    "app/modules/video_player/__pycache__",
    "__pycache__",
    ".vscode", ".codebuddy", ".qoder",
    "editor", "editors",
    "新建文件夹",  # 测试用目录
    "logs", "error_reports",
    "workflow_logs",
    "短剧AI剪辑输出",
    "素材库",
    "运营数据",
}

# 要排除的文件
EXCLUDE_FILES = {
    "*.pyc", "*.pyo", "*.pyd",
    "*.so", "*.dll", "*.pdb",  # 编译产物
    "*.log", "*.txt.bak",
    "*.tmp", "*.bak",
    "*.mp4", "*.avi", "*.mov", "*.mkv",  # 视频文件
    "*.wav", "*.mp3", "*.flac",  # 音频
    "*.png", "*.jpg", "*.jpeg",  # 图片(项目内)
    "*.zip", "*.7z", "*.rar", "*.tar.gz",
    "*.pdf", "*.docx", "*.xlsx",
    "_*.txt",  # 临时日志
    "test_result.txt", "test_c5.log", "test_c5_results.txt",  # 测试输出
    "*.spec",  # PyInstaller spec
    "*.spec.bak",
}


def should_exclude_dir(dirname: str) -> bool:
    """判断目录是否应排除"""
    return dirname in EXCLUDE_DIRS


def should_exclude_file(filename: str) -> bool:
    """判断文件是否应排除"""
    if filename in EXCLUDE_FILES:
        return True
    # 后缀匹配
    for pattern in EXCLUDE_FILES:
        if pattern.startswith("*.") and filename.endswith(pattern[1:]):
            return True
    if filename.startswith("."):
        return False  # 保留 .gitignore .env 等
    return False


def copy_project():
    """执行复制"""
    print(f"源目录: {SOURCE_ROOT}")
    print(f"目标目录: {TARGET_DIR}")
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    if not SOURCE_ROOT.exists():
        print(f"❌ 源目录不存在: {SOURCE_ROOT}")
        return False

    # 创建目标目录
    TARGET_DIR.mkdir(parents=True, exist_ok=True)

    # 统计
    copied_files = 0
    skipped_files = 0
    copied_size = 0

    # 遍历源目录
    for src_root, dirs, files in os.walk(SOURCE_ROOT):
        rel_root = Path(src_root).relative_to(SOURCE_ROOT)

        # 过滤目录
        dirs[:] = [d for d in dirs if not should_exclude_dir(d)]

        # 计算目标路径
        dst_root = TARGET_DIR / rel_root
        dst_root.mkdir(parents=True, exist_ok=True)

        # 复制文件
        for filename in files:
            if should_exclude_file(filename):
                skipped_files += 1
                continue

            src_file = Path(src_root) / filename
            dst_file = dst_root / filename

            try:
                file_size = src_file.stat().st_size
                # 单文件 > 50MB 跳过 (避免复制大模型/视频)
                if file_size > 50 * 1024 * 1024:
                    print(f"  ⏭️  跳过超大文件: {src_file.relative_to(SOURCE_ROOT)} ({file_size // 1024 // 1024} MB)")
                    skipped_files += 1
                    continue

                shutil.copy2(src_file, dst_file)
                copied_files += 1
                copied_size += file_size
            except Exception as e:
                print(f"  ❌ 复制失败 {src_file.relative_to(SOURCE_ROOT)}: {e}")
                skipped_files += 1

    print("=" * 60)
    print(f"✅ 复制完成!")
    print(f"   复制文件: {copied_files}")
    print(f"   跳过文件: {skipped_files}")
    print(f"   总大小:   {copied_size / 1024 / 1024:.2f} MB")
    print(f"   目标路径: {TARGET_DIR}")
    print(f"结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    return True


if __name__ == "__main__":
    try:
        success = copy_project()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n⚠️ 用户中断")
        sys.exit(1)

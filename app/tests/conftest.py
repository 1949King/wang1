"""
app/tests/conftest.py - 测试共享配置与 fixtures

提供所有测试公用的 fixtures 和配置。
"""

import sys
import os
from pathlib import Path

# 确保 app 目录在 sys.path 中（解决 namespace package 问题）
APP_DIR = Path(__file__).parent.parent.resolve()
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

# 同时添加项目根目录
ROOT_DIR = APP_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pytest
import threading
import logging


# ============================================================
# 测试环境设置
# ============================================================

@pytest.fixture(autouse=True)
def reset_core_singletons():
    """每个测试前重置三大核心单例，避免测试间污染。

    在无 GUI 栈(如 PyQt6 缺失)的无头/CI 环境中，core 模块无法导入，
    此时静默跳过重置，避免阻断不依赖 GUI 的单元测试。
    """
    try:
        from app.modules.lego.core import EventBus, MasterClock, DataBus
    except Exception:
        yield
        return

    # 强制重置 EventBus / MasterClock / DataBus 单例
    EventBus._instance = None
    MasterClock._instance = None
    DataBus._instance = None

    yield

    # 测试后也清理
    EventBus._instance = None
    MasterClock._instance = None
    DataBus._instance = None


@pytest.fixture
def temp_dir(tmp_path):
    """临时目录 fixture"""
    return tmp_path


@pytest.fixture
def temp_file(tmp_path):
    """临时文件 fixture"""
    def _create(content: str = "", suffix: str = ".txt") -> Path:
        f = tmp_path / f"test_{os.urandom(4).hex()}{suffix}"
        f.write_text(content, encoding="utf-8")
        return f
    return _create


# ============================================================
# 测试标记说明
# ============================================================
# pytest -m "not slow"          # 跳过慢速测试
# pytest -m "unit"               # 仅运行单元测试
# pytest -m "integration"        # 仅运行集成测试
# pytest app/tests/test_buses.py # 运行特定文件

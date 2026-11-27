"""
app/tests/conftest.py - 测试共享配置与 fixtures

提供所有测试公用的 fixtures 和配置。
"""

import sys
import os
import tempfile
from pathlib import Path

# 确保 app 目录在 sys.path 中（解决 namespace package 问题）
APP_DIR = Path(__file__).parent.parent.resolve()
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

# 同时添加项目根目录
ROOT_DIR = APP_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# 把 tempfile 基准目录钉到项目内 .workbuddy/tmp（2026-09-27 发现的问题）：
# 沙箱环境拦截系统 Temp 写入 → tempfile.gettempdir() 回退到 cwd（项目根），
# 导致每次跑测试都把 sg_*/cover_*/pytest-of-* 等临时目录漏进仓库根。
# .workbuddy/ 已在 .gitignore（第 171 行），落此处既集中又不会污染 git。
_TMP_BASE = ROOT_DIR / ".workbuddy" / "tmp"
try:
    _TMP_BASE.mkdir(parents=True, exist_ok=True)
    tempfile.tempdir = str(_TMP_BASE)
    os.environ.setdefault("TMPDIR", str(_TMP_BASE))
    os.environ.setdefault("TEMP", str(_TMP_BASE))
    os.environ.setdefault("TMP", str(_TMP_BASE))
except Exception:
    pass  # 极端只读环境下不阻断测试

import pytest


# ============================================================
# 测试环境设置
# ============================================================

@pytest.fixture(autouse=True)
def reset_core_singletons():
    """每个测试前重置三大核心单例，避免测试间污染。

    在无 GUI 栈(如 PySide6 缺失)的无头/CI 环境中，core 模块无法导入，
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


@pytest.fixture(autouse=True)
def isolate_ai_ledgers(tmp_path, monkeypatch):
    """把抽卡账本 / 质量先验库重定向到临时目录，防止测试写入生产真相源。

    背景（2026-09-27 深度求索 DEFECT A）：draw_book 与 quality_prior 默认路径
    指向 data/*.json 正式文件；测试若直连会把 score=0.5 的假样本灌进真相源，
    污染 P2 推荐 / quality_prior 路由。此 fixture 用环境变量 + 重置单例双保险，
    让所有测试自动隔离，无需逐用例改动。
    """
    monkeypatch.setenv("DRAW_BOOK_STORE_PATH",
                       str(tmp_path / "draw_book.json"))
    monkeypatch.setenv("QUALITY_PRIOR_PATH",
                       str(tmp_path / "quality_prior.json"))
    # 重置进程级单例，确保新路径在本用例内生效（前一用例可能已建过单例）
    try:
        from app.core.ai import draw_book as _db
        monkeypatch.setattr(_db, "_STORE", None)
    except Exception:
        pass
    try:
        from app.core.ai import quality_prior as _qp
        monkeypatch.setattr(_qp, "_STORE", None)
    except Exception:
        pass
    yield


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

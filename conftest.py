"""
conftest.py
===========
B5: pytest 统一入口的共享 fixtures
位置: 根目录 (与 pytest.ini 配合, pytest 自动发现)

核心 fixtures:
  - qt_app:      Qt 单进程应用 (offscreen)
  - temp_dir:    临时目录 (测试后自动清理)
  - bus:         EventBus 单例 (测试隔离)
  - clock:       MasterClock 单例
  - data_bus:    DataBus 单例
"""
import os
import sys
import pytest
import tempfile
import shutil
from pathlib import Path

# 把 app/ 加进 sys.path, 让测试代码可以直接 from core.xxx 导入
APP_ROOT = Path(__file__).resolve().parent / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

# 把 tempfile 基准目录钉到项目内 .workbuddy/tmp（2026-09-27）：
# 沙箱拦截系统 Temp 写入 → tempfile.gettempdir() 回退到 cwd（项目根），
# 每次跑测试都把 pytest-of-*/sg_* 等临时目录漏进仓库根。.workbuddy/ 已在
# .gitignore（第 171 行），落此处既集中又不会污染 git。放在根 conftest，
# 对 app/tests 与 tests 两个测试目录同时生效。
_TMP_BASE = Path(__file__).resolve().parent / ".workbuddy" / "tmp"
try:
    _TMP_BASE.mkdir(parents=True, exist_ok=True)
    tempfile.tempdir = str(_TMP_BASE)
    os.environ["TMPDIR"] = str(_TMP_BASE)
    os.environ["TEMP"] = str(_TMP_BASE)
    os.environ["TMP"] = str(_TMP_BASE)
except OSError:
    pass


@pytest.fixture(scope="session")
def qt_app():
    """Qt 应用 fixture (session 级别, 整个测试套件共用 1 个 QApplication)"""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    yield app
    # 不主动 quit, 让 pytest 进程结束时自动清理


@pytest.fixture
def temp_dir():
    """临时目录 (每个测试函数独占, 自动清理)"""
    d = tempfile.mkdtemp(prefix="py_test_")
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def bus():
    """EventBus 单例 (测试隔离: 每个测试拿到新实例)"""
    from core.event_bus import EventBus  # 兼容两种路径
    try:
        return EventBus.get_instance()
    except Exception:
        from modules.lego.core import EventBus as _EB
        return _EB.get_instance()


@pytest.fixture
def data_bus():
    """DataBus 单例"""
    try:
        from core.data_bus import DataBus
        return DataBus.get_instance()
    except Exception:
        from modules.lego.core import DataBus as _DB
        return _DB.get_instance()


@pytest.fixture
def clock():
    """MasterClock 单例"""
    try:
        from core.master_clock import MasterClock
        return MasterClock.get_instance()
    except Exception:
        from modules.lego.core import MasterClock as _MC
        return _MC.get_instance()


@pytest.fixture(autouse=True)
def reset_singletons():
    """每个测试结束后, 重置 3 大总线单例, 避免污染下个测试"""
    yield
    # 清理 EventBus 历史订阅
    try:
        from modules.lego.core import EventBus, DataBus
        EventBus._instance = None
        DataBus._instance = None
    except Exception:
        pass


# ============== 测试辅助函数 ==============

def pytest_configure(config):
    """pytest 启动时打印欢迎信息"""
    print("\n" + "=" * 60)
    print("AI 短剧编辑器 测试套件 (B5 整合)")
    print("=" * 60)
    print(f"  APP_ROOT: {APP_ROOT}")
    print(f"  QT_QPA_PLATFORM: {os.environ.get('QT_QPA_PLATFORM', 'N/A')}")
    print("=" * 60 + "\n")

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
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv or ["pytest"])
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


@pytest.fixture(autouse=True)
def isolate_ledger_state(tmp_path, monkeypatch):
    """把「三层价格体系 + 抽检」的账本状态隔离到临时目录（2026-10-09）。

    为什么必须隔离（实测事故，不是洁癖）：
      `budget_pacer.get_pacer()` / `global_price.get_global_price()` /
      `sampling_review.get_review()` 都是**进程级单例**，首次调用会读磁盘上的
      `data/*.json`。以 budget_pacer 为例：读到持久化状态则 `_pi_ready=True`
      （**跳过**「首拍建基线」分支），读不到则走另一条路径 —— 于是同一份代码的
      **覆盖率采样不可复现**：全量 pytest 实测 `budget_pacer.py` 有时覆盖 116 行、
      有时 109 行（取决于单例首次建立时磁盘上有没有该文件、以及哪些测试先跑），
      `_verify/check_coverage.py` 的棘轮因此随机报红。

      次要但同样真实的危害：测试会把 spent / 预算 / 抽检标签写进用户**真实 data/ 目录**。

    做法：① 三个路径环境变量指向本测试的 tmp_path；
          ② 清空进程级单例，使每个测试从干净状态起步。
    与 draw_book / quality_prior 的既有纪律一致（它们的路径早已可由环境变量覆盖，
    本文件补的是漏掉的那三个）。
    """
    state = tmp_path / "ledger_state"
    state.mkdir(parents=True, exist_ok=True)
    for mod_name, env in (
        ("budget_pacer", "BUDGET_PACER_STORE_PATH"),
        ("global_price", "GLOBAL_PRICE_STORE_PATH"),
        ("sampling_review", "SAMPLING_REVIEW_STORE_PATH"),
    ):
        monkeypatch.setenv(env, str(state / f"{mod_name}.json"))
    try:
        from app.core.ai import budget_pacer as _bp
        from app.core.ai import global_price as _gp
        from app.core.ai import sampling_review as _sr
        monkeypatch.setattr(_bp, "_PACER", None, raising=False)
        monkeypatch.setattr(_gp, "_GLOBAL", None, raising=False)
        monkeypatch.setattr(_sr, "_REVIEW", None, raising=False)
    except Exception:
        pass
    yield


# ============== 测试辅助函数 ==============

def pytest_configure(config):
    """pytest 启动时打印欢迎信息"""
    print("\n" + "=" * 60)
    print("AI 短剧编辑器 测试套件 (B5 整合)")
    print("=" * 60)
    print(f"  APP_ROOT: {APP_ROOT}")
    print(f"  QT_QPA_PLATFORM: {os.environ.get('QT_QPA_PLATFORM', 'N/A')}")
    print("=" * 60 + "\n")

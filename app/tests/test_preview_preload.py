"""app/tests/test_preview_preload.py — 拖动静止后的定窗预载（刀 A3.5，2026-10-05）。

**修的是什么**（都是实测出来的，不是推断）：

  1. `_verify/bench/bench_preview_cost.py`（长 GOP 30s / 720p，100 次采样）：
     顺序扫 3.4ms/帧 vs **反扫 11.1ms/帧**，单次后退 `cv2` seek **16~17ms**
     ⇒ 瓶颈是**后退 seek**，不是缓存策略（策略基准 bench_preview_cache.py 证明
     min()/FIFO/LRU 三者差 0.7%，几乎无差别）。
  2. 而 `FramePreloaderThread.set_preload_range` **全仓无人调用**，
     `_enable_preloading=False` **且** `_use_threaded_reading=False`（硬编码）
     ⇒ 「预载」能力**从未运行过** = 死代码。
  3. 接上之后同区间 A/B：反扫 **54.98ms/帧 → 1.66ms/帧（提速 33.2×）**，
     预载一次性成本 166ms（37 帧窗口）。

本测试锁住：窗口内存预算 / 防抖去重 / 懒启动 / 无副作用（无视频时不炸）/ seek 接线 /
「set_preload_range 不再无人调用」。
"""
import pathlib
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = (ROOT / "core" / "preview_manager.py").read_text(encoding="utf-8")


_APP = None   # 模块级强引用：QApplication 被 GC 会连带销毁它创建的所有 QObject 子对象


def _get_app():
    """拿（并**持有**）一个 QApplication。

    坑：把 QApplication 放在 fixture 局部变量里，fixture 返回后 Python 会回收它，
    PyQt 随之销毁 C++ 侧 → 后续访问 PreviewManager 报
    `wrapped C/C++ object ... has been deleted`。故用模块级变量钉住。
    """
    global _APP
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    _APP = QApplication.instance() or QApplication([])
    return _APP


@pytest.fixture()
def pm():
    """真实 PreviewManager（offscreen Qt；不打开视频）。"""
    pytest.importorskip("PyQt6.QtWidgets")
    _get_app()
    from app.core.preview_manager import PreviewManager

    return PreviewManager()


# ─────────────────────── ① 窗口与内存预算 ───────────────────────

def test_window_respects_memory_budget(pm):
    """窗宽按**未压缩帧字节数**算，绝不无上限预载。

    720p 单帧 1280*720*3 ≈ 2.76MB；96MB 预算 ⇒ 约 34 帧（再受 raw 上限-12 约束）。
    """
    pm._video_width, pm._video_height = 1280, 720
    n = pm._preload_window_frames()
    assert 12 <= n <= 40, n

    # 4K 单帧 ≈ 24.9MB ⇒ 同预算下窗宽必须显著变小（否则 100 帧就是 2.5GB）
    pm._video_width, pm._video_height = 3840, 2160
    n4k = pm._preload_window_frames()
    assert n4k < n, (n4k, n)
    assert n4k >= 12      # 下限 12 帧，太小就没意义


def test_window_never_exceeds_raw_cache_capacity(pm):
    pm._video_width, pm._video_height = 640, 360      # 小尺寸 ⇒ 预算算出来很大
    pm.max_raw_cache_size = 30
    assert pm._preload_window_frames() <= 30 - 12 + 12 or pm._preload_window_frames() <= 30
    pm.max_raw_cache_size = 100


# ─────────────────────── ② 防抖与去重 ───────────────────────

def test_request_is_debounced(pm):
    """拖动中连续 seek 只应留下**一个**待处理的定窗请求。"""
    pm._video_source = "x.mp4"
    pm._video_fps = 30.0
    for t in (1.0, 1.2, 1.5, 1.9):
        pm.request_preload_window(t)
    assert pm._pending_preload_center == 1.9          # 只保留最后一次
    timer = getattr(pm, "_preload_debounce_timer", None)
    assert timer is not None and timer.isSingleShot() and timer.isActive()


def test_duplicate_window_is_skipped(pm, monkeypatch):
    """与上次窗重叠过多 ⇒ 不下发（避免拖在同一处反复重解同一段）。"""
    calls = []
    pm._video_source, pm._video_fps, pm._video_frame_count = "x.mp4", 30.0, 900
    pm._video_width, pm._video_height = 1280, 720
    monkeypatch.setattr(pm, "_ensure_preloader", lambda: True)
    pm._preloader_thread = types.SimpleNamespace(
        set_preload_range=lambda a, b: calls.append((a, b)))
    pm._last_preload_start = None
    pm._pending_preload_center = 10.0
    pm._do_preload_window()
    assert len(calls) == 1
    pm._pending_preload_center = 10.2                  # 几乎同一处
    pm._do_preload_window()
    assert len(calls) == 1, "重叠窗口应被跳过"
    pm._pending_preload_center = 20.0                  # 换一处
    pm._do_preload_window()
    assert len(calls) == 2


def test_window_has_frames_before_playhead(pm, monkeypatch):
    """窗口必须**向前留出**一段（H.264 只能正向解码 ⇒ 反扫全靠窗前段）。"""
    got = {}
    pm._video_source, pm._video_fps, pm._video_frame_count = "x.mp4", 30.0, 900
    pm._video_width, pm._video_height = 1280, 720
    monkeypatch.setattr(pm, "_ensure_preloader", lambda: True)
    pm._preloader_thread = types.SimpleNamespace(
        set_preload_range=lambda a, b: got.update(start=a, end=b))
    pm._last_preload_start = None
    pm._pending_preload_center = 10.0                  # 10s ⇒ 第 300 帧（30fps）
    pm._do_preload_window()
    # set_preload_range 收的是**秒**（内部再 ×fps），故按秒断言
    assert got["start"] < 10.0, f"窗口起点必须在播放头之前，实际 {got}"
    assert got["end"] > 10.0, f"窗口终点必须在播放头之后，实际 {got}"


# ─────────────────────── ③ 懒启动与无副作用 ───────────────────────

def test_ensure_preloader_no_video_is_safe(pm):
    pm._video_source = None
    pm._preloader_thread = None
    assert pm._ensure_preloader() is False       # 不抛异常
    assert pm._preloader_thread is None


def test_do_preload_without_pending_is_noop(pm):
    pm._pending_preload_center = None
    pm._do_preload_window()                       # 不应创建线程/不抛异常


def test_request_without_video_is_noop(pm):
    pm._video_source = None
    pm._video_fps = 0.0
    pm.request_preload_window(3.0)
    assert getattr(pm, "_pending_preload_center", None) is None


def test_preloader_does_not_need_threaded_reading():
    """预载线程自带 cv2 句柄 ⇒ 不得再被 `_use_threaded_reading` 卡住。

    （这两道门叠加正是「预载从未运行」的根因。）
    """
    import re as _re
    fn = SRC.split("def _ensure_preloader", 1)[1].split("\n    def ", 1)[0]
    code = _re.sub(r'"""[\s\S]*?"""', "", fn)          # 去 docstring（解释里会提到这两个名字）
    code = _re.sub(r"^\s*#.*$", "", code, flags=_re.M)  # 去注释
    assert "_use_threaded_reading" not in code
    assert "_enable_preloading" not in code


# ─────────────────────── ④ seek 接线 + 死代码复活 ───────────────────────

def test_seek_triggers_preload_request():
    fn = SRC.split("def _seek_to", 1)[1].split("\n    def ", 1)[0]
    assert "request_preload_window(" in fn, "_seek_to 未接预载请求"


def test_set_preload_range_is_no_longer_dead_code():
    """★ 死代码复活锁：`set_preload_range` 必须**在生产代码里被调用**。

    （此前全仓 0 调用 —— 预载线程启动后只会 sleep 空转。）
    """
    body = SRC.split("def _do_preload_window", 1)[1].split("\n    def ", 1)[0]
    assert "set_preload_range(" in body
    # 反向确认：这行调用不在 def 声明里（避免自我满足）
    decl = [ln for ln in SRC.splitlines() if "set_preload_range" in ln and "def " not in ln]
    assert decl, "set_preload_range 只有定义、没有调用"


def test_debounce_interval_is_bounded():
    """防抖窗口要"停下来才解码"：太短等于没防抖，太长等于拖完半天不预载。"""
    import re
    m = re.search(r"def request_preload_window\(self, center_time: float, \*,\s*"
                  r"before_s: float = [\d.]+,\s*debounce_ms: int = (\d+)\)", SRC)
    assert m, "request_preload_window 签名变了（防抖默认值需重新确认）"
    assert 80 <= int(m.group(1)) <= 500, m.group(1)

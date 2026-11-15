# -*- coding: utf-8 -*-
"""`VideoProcessor.process_video` 的闭包回归测试。

背景（2026-11-15 修）：`task()` 里既读 `export_settings` 又给它赋默认值，
但没写 `nonlocal`。Python 的规则是「函数内只要有赋值，这个名字在整个函数里就是局部的」，
于是 `if export_settings is None` 直接抛 `UnboundLocalError`，
再被 `except Exception` 吞掉只写日志 ⇒
**调用方永远收到「任务已提交到线程池」，任务每次都失败，界面毫无异常**。

这个测试的写法要点：绕过 `__init__`（它会起真线程池、建输出目录），
并把线程池换成同步执行，这样 `task()` 的异常就落回测试线程，能被断言抓到。
"""
from __future__ import annotations

import pytest

from app.modules.lego import modules as M


class _SyncPool:
    """把 submit 变成同步执行：异常直接冒到测试里，不会被线程吞掉。"""

    def __init__(self) -> None:
        self.calls = 0

    def submit(self, fn, *args, **kwargs):  # noqa: ANN001 - 与真实 ThreadPool 签名对齐
        self.calls += 1
        return fn(*args, **kwargs)


def _make_processor(tmp_path):
    # 跳过 __init__：它要起线程池 + 建 "短剧AI剪辑输出" 目录，测试里都是噪音
    vp = object.__new__(M.VideoProcessor)
    vp.output_dir = str(tmp_path)
    vp.thread_pool = _SyncPool()
    return vp


def test_default_settings_reach_handler(monkeypatch, tmp_path) -> None:
    """不传 export_settings 时，默认参数字典必须真的传进处理函数。

    修复前：`UnboundLocalError` 被吞 ⇒ 处理函数一次都没被调用。
    """
    vp = _make_processor(tmp_path)
    seen = {}
    monkeypatch.setattr(
        M.VideoProcessor,
        "_basic_process",
        lambda self, src, out, st: seen.update(src=src, out=out, settings=st),
        raising=True,
    )

    msg = vp.process_video("in.mp4", "Other", None)

    assert "提交" in msg
    assert seen, "处理函数没被调用 —— 说明 task() 在入口就抛异常了"
    assert seen["settings"]["format"] == "mp4"
    assert seen["settings"]["resolution"] == "1920x1080"
    assert seen["out"].endswith(".mp4")


def test_explicit_settings_are_respected(monkeypatch, tmp_path) -> None:
    """显式传进来的设置不能被默认值覆盖。"""
    vp = _make_processor(tmp_path)
    seen = {}
    monkeypatch.setattr(
        M.VideoProcessor,
        "_basic_process",
        lambda self, src, out, st: seen.update(settings=st),
        raising=True,
    )

    mine = {"format": "mov", "resolution": "1280x720"}
    vp.process_video("in.mp4", "Other", mine)

    assert seen["settings"]["format"] == "mov"
    assert seen["settings"]["resolution"] == "1280x720"
    assert seen["settings"] is mine, "不该被换成新字典"


def test_no_mode_routing_branch_is_silently_dead(monkeypatch, tmp_path) -> None:
    """模式必须真的路由到对应处理函数（全走 _basic_process 就说明路由没生效）。"""
    vp = _make_processor(tmp_path)
    hit = []
    for name in ("_process_autoclip", "_process_funclip", "_process_videofusion", "_process_lora_edit"):
        monkeypatch.setattr(
            M.VideoProcessor, name, lambda self, s, o, st, _n=name: hit.append(_n), raising=True
        )
    monkeypatch.setattr(
        M.VideoProcessor, "_basic_process", lambda self, s, o, st: hit.append("_basic_process"),
        raising=True,
    )

    for mode, expect in (
        ("AutoClip", "_process_autoclip"),
        ("FunClip", "_process_funclip"),
        ("VideoFusion", "_process_videofusion"),
        ("LoRA Edit", "_process_lora_edit"),
        ("Whatever", "_basic_process"),
    ):
        hit.clear()
        vp.process_video("in.mp4", mode, {"format": "mp4"})
        assert hit == [expect], (mode, hit)


def test_thread_pool_submit_is_used(monkeypatch, tmp_path) -> None:
    """任务必须进线程池（不能在调用线程里干重活卡住 UI）。

    ⚠️ 必须 stub 掉 `_basic_process`：真实现会 `get_render_manager()` →
    import `app/core/video_processing/cpp_engine`，在 pytest 进程里加载原生 C++ 引擎
    会直接 **access violation**（实测崩在 cpp_engine/__init__.py:93），
    整个测试会话被打断。这不是本用例要测的东西，不该让它跑。
    """
    vp = _make_processor(tmp_path)
    monkeypatch.setattr(
        M.VideoProcessor, "_basic_process", lambda self, s, o, st: None, raising=True
    )
    vp.process_video("in.mp4", "Whatever", {"format": "mp4"})
    assert isinstance(vp.thread_pool, _SyncPool)
    assert vp.thread_pool.calls == 1


@pytest.mark.parametrize("bad", ["", None])
def test_bad_mode_does_not_raise(monkeypatch, tmp_path, bad) -> None:
    """模式为空/None 时走基础处理，不许把异常抛给调用方。"""
    vp = _make_processor(tmp_path)
    monkeypatch.setattr(
        M.VideoProcessor, "_basic_process", lambda self, s, o, st: None, raising=True
    )
    assert "提交" in vp.process_video("in.mp4", bad, {"format": "mp4"})

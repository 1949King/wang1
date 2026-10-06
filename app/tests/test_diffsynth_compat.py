"""app/tests/test_diffsynth_compat.py — diffsynth_engine 兼容层回归（2026-10-02）。

锁定的纪律：
  ① **幂等 + 纯增量** —— shim 只往 moviepy 顶层加名字，不改 moviepy.editor 既有行为
     （项目剪辑主路径用的是 1.x API，绝不能被装引擎顺手弄坏）；
  ② **2.x 改名方法必须映射全** —— diffsynth_engine 用到 `subclipped` / `with_audio`，
     少映射一个就是运行时 AttributeError（而不是导入期就报，更难查）；
  ③ **子类而非替换** —— shimmed 类必须**继承** moviepy.editor 的原类（1.x 语义不丢）。

注：本测试**不 import diffsynth_engine**（重依赖，且 pytest 组合场景有崩进程前科 ——
真实导入验证由 _verify 侧/手工子进程做，见 check_video_gen ⑫ 段注释）。
"""
import inspect
import pathlib

from app.core.neural import diffsynth_compat as C


def test_ensure_is_idempotent_and_true():
    assert C.ensure_moviepy2_compat() is True
    assert C.ensure_moviepy2_compat() is True   # 第二次调用无副作用


def test_shim_adds_top_level_names_without_touching_editor():
    """★ 顶层补名 + `moviepy.editor` 原样保留（纯增量，1.x 主路径零影响）。"""
    C.ensure_moviepy2_compat()
    import moviepy
    import moviepy.editor as mpe
    for name in ("ImageSequenceClip", "AudioFileClip", "VideoClip"):
        assert hasattr(moviepy, name), name
    # editor 形态仍在（项目的 autoclip / editor_module 依赖它）
    assert mpe.VideoFileClip is not None
    assert mpe.concatenate_videoclips is not None


def test_shimmed_classes_subclass_editor_classes():
    """★ shimmed 类必须继承 editor 原类 —— 1.x 行为语义（含 in-place set_*）不丢。"""
    C.ensure_moviepy2_compat()
    import moviepy
    import moviepy.editor as mpe
    assert issubclass(moviepy.ImageSequenceClip, mpe.ImageSequenceClip)
    assert issubclass(moviepy.AudioFileClip, mpe.AudioFileClip)
    assert issubclass(moviepy.VideoClip, mpe.VideoClip)


def test_renamed_methods_are_mapped():
    """★ diffsynth_engine 用到的两个 2.x 改名方法都必须存在且可调用。"""
    C.ensure_moviepy2_compat()
    import moviepy
    for cls in (moviepy.ImageSequenceClip, moviepy.AudioFileClip, moviepy.VideoClip):
        assert callable(getattr(cls, "subclipped", None)), cls
        assert callable(getattr(cls, "with_audio", None)), cls
    # 映射方向必须正确（2.x 名 → 1.x 实现），不能是空壳
    # （mixin 定义在函数内，模块级拿不到；直接从 shimmed 类继承来的方法上验源码）
    src_sub = inspect.getsource(moviepy.VideoClip.subclipped)
    src_audio = inspect.getsource(moviepy.VideoClip.with_audio)
    assert "self.subclip(" in src_sub, "subclipped 必须落到 1.x subclip"
    assert "self.set_audio(" in src_audio, "with_audio 必须落到 1.x set_audio"


def test_import_entry_fails_honestly_without_shim(monkeypatch):
    """★ import_diffsynth_engine 的**诚实失败**契约：shim 建不起来 ⇒ 返回 None，不抛异常。

    ⚠️ 本用例**绝不触发真实 import diffsynth_engine**（monkeypatch 把 shim 掐掉）：
    2026-10-02 实测，在**全量 pytest 组合场景**里真 import 会把整个进程**硬崩**
    （faulthandler dump，连异常都不是）—— 与 diffusers 当年的组合崩溃同型。
    单独跑本文件侥幸不崩，全量必崩。**真实导入的验证只能放子进程/手工脚本**。
    """
    monkeypatch.setattr(C, "ensure_moviepy2_compat", lambda: False)
    assert C.import_diffsynth_engine() is None     # 诚实失败：None，不抛


def test_import_entry_real_import_is_guarded():
    """真实 import 分支必须裹在 try/except 里（失败降级为 None + 记日志），不裸奔。"""
    src = inspect.getsource(C.import_diffsynth_engine)
    assert "try:" in src and "except Exception" in src
    assert "exc_info=True" in src                  # 失败必须留日志，不静默
    assert "ensure_moviepy2_compat" in src         # 先垫 shim 再 import 的顺序锁死


def test_why_is_documented():
    """shim 的由来（moviepy 1.x 约束 + 为何不顺手升 2.x）必须留档，防后人误删。"""
    src = pathlib.Path(C.__file__).read_text(encoding="utf-8")
    assert "moviepy" in src and "editor_module" in src
    assert "北极星" in src or "剪辑" in src

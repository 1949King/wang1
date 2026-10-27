# -*- coding: utf-8 -*-
"""`probe_vram` 保守口径测试（P1.5 · 2026-10-28）。

锁的是什么
==========
2026-10-28 实测：torch 的 `mem_get_info()` 在本机（Windows WDDM）**对别的进程占用的显存
基本无感** —— Ollama 实占 3.66GB 时它仍报 6.94GB，与空载一模一样；nvidia-smi 报 2.74GB。

这条偏差不是"数值不准"，而是**方向性错误**：偏乐观 ⇒ 标定档案安全闸（`peak > free_gb`）
放行一个实际装不下的方案 ⇒ 真加载时挤爆。而本机挤爆的表现不是 OOM，是 WDDM 换页
（2026-10-25 实测 68.9s/步）—— 不报错、只慢 50 倍，比 OOM 更难发现。

故这里锁四件事：
  ① `free_gb` 必须等于两个读数的**较小值**（不是 torch 那个）；
  ② 两个原始读数都要保留（诊断"差多少"用）；
  ③ nvidia-smi 不可用 ⇒ 退回 torch 单读数，且 `smi_free_gb` 如实为 None（不假装有两个）；
  ④ nvidia-smi 有 1s 缓存（每次决策起 subprocess 太贵），`force=True` 绕过。

全部用假 torch 模块注入，不依赖本机有没有显卡。
"""
from __future__ import annotations

import importlib.machinery
import sys
import types
from types import SimpleNamespace

import pytest

from app.core.neural import memory_policy as MP


def _fake_torch(free_gb, total_gb=8.0, cuda_ok=True):
    """造一个最小可用的假 torch 模块（带 __spec__ 才能过 find_spec）。"""
    mod = types.ModuleType("torch")
    mod.__spec__ = importlib.machinery.ModuleSpec("torch", None)
    mod.cuda = SimpleNamespace(
        is_available=lambda: cuda_ok,
        mem_get_info=lambda: (int(free_gb * 1024 ** 3), int(total_gb * 1024 ** 3)),
    )
    return mod


@pytest.fixture(autouse=True)
def _reset_smi_cache():
    """每个用例从"没有缓存"开始，免得上一个用例的读数串进来。"""
    MP._smi_cache["t"] = -1e9
    MP._smi_cache["v"] = None
    yield
    MP._smi_cache["t"] = -1e9
    MP._smi_cache["v"] = None


def _install_torch(monkeypatch, free_gb, cuda_ok=True):
    monkeypatch.setitem(sys.modules, "torch", _fake_torch(free_gb, cuda_ok=cuda_ok))


# ══════════════════════════════════════════════════════════════════
# ① 取较小值
# ══════════════════════════════════════════════════════════════════

def test_free_gb_is_the_smaller_reading(monkeypatch):
    """torch 报 6.94、nvidia-smi 报 2.74 ⇒ free_gb 必须是 2.74。

    这就是真机那组数字（LLM 占了 3.66GB 时）。
    """
    _install_torch(monkeypatch, 6.94)
    monkeypatch.setattr(MP, "nvidia_smi_free_gb", lambda force=False: 2.74)

    info = MP.probe_vram()

    assert info["free_gb"] == 2.74
    assert info["torch_free_gb"] == 6.94
    assert info["smi_free_gb"] == 2.74


def test_torch_smaller_than_smi_also_wins(monkeypatch):
    """方向反过来时同样取小值（不许只认某一边）。"""
    _install_torch(monkeypatch, 3.10)
    monkeypatch.setattr(MP, "nvidia_smi_free_gb", lambda force=False: 5.20)

    info = MP.probe_vram()
    assert info["free_gb"] == 3.10


def test_equal_readings_stay_equal(monkeypatch):
    _install_torch(monkeypatch, 4.00)
    monkeypatch.setattr(MP, "nvidia_smi_free_gb", lambda force=False: 4.00)
    assert MP.probe_vram()["free_gb"] == 4.00


# ══════════════════════════════════════════════════════════════════
# ② 两个原始读数都保留
# ══════════════════════════════════════════════════════════════════

def test_both_raw_readings_are_kept_for_diagnosis(monkeypatch):
    """诊断要能看出"差多少"，故原始读数不许被 min 抹掉。"""
    _install_torch(monkeypatch, 6.94)
    monkeypatch.setattr(MP, "nvidia_smi_free_gb", lambda force=False: 2.74)

    info = MP.probe_vram()
    assert set(info) >= {"free_gb", "total_gb", "torch_free_gb", "smi_free_gb"}
    assert info["torch_free_gb"] - info["smi_free_gb"] == pytest.approx(4.20)


# ══════════════════════════════════════════════════════════════════
# ③ 降级诚实
# ══════════════════════════════════════════════════════════════════

def test_smi_unavailable_falls_back_to_torch(monkeypatch):
    """非 NVIDIA 环境（MUSA 等）⇒ 退回 torch 单读数，且如实标 smi=None。"""
    _install_torch(monkeypatch, 7.10)
    monkeypatch.setattr(MP, "nvidia_smi_free_gb", lambda force=False: None)

    info = MP.probe_vram()

    assert info["free_gb"] == 7.10
    assert info["smi_free_gb"] is None, "不许编一个读数出来"


def test_torch_missing_returns_none(monkeypatch):
    """没有 torch ⇒ 整体 None（不虚报）。"""
    monkeypatch.setattr("importlib.util.find_spec", lambda name, *a, **k: None)
    assert MP.probe_vram() is None


def test_cuda_unavailable_returns_none(monkeypatch):
    """torch 在但没 CUDA ⇒ None。"""
    _install_torch(monkeypatch, 8.0, cuda_ok=False)
    assert MP.probe_vram() is None


def test_mem_get_info_exception_returns_none(monkeypatch):
    """mem_get_info 抛异常 ⇒ None，不向上抛。"""
    mod = _fake_torch(8.0)
    mod.cuda.mem_get_info = lambda: (_ for _ in ()).throw(RuntimeError("CUDA error"))
    monkeypatch.setitem(sys.modules, "torch", mod)
    assert MP.probe_vram() is None


# ══════════════════════════════════════════════════════════════════
# nvidia_smi_free_gb 本体
# ══════════════════════════════════════════════════════════════════

class _Out:
    def __init__(self, rc=0, stdout=b""):
        self.returncode = rc
        self.stdout = stdout


def test_smi_parses_nounits_output(monkeypatch):
    """nvidia-smi 的 MiB 输出换算成 GB。"""
    monkeypatch.setattr(MP.subprocess, "run", lambda *a, **k: _Out(0, b"6546\n"))
    assert MP.nvidia_smi_free_gb(force=True) == pytest.approx(6.39, abs=0.01)


def test_smi_nonzero_rc_returns_none(monkeypatch):
    monkeypatch.setattr(MP.subprocess, "run", lambda *a, **k: _Out(1, b""))
    assert MP.nvidia_smi_free_gb(force=True) is None


def test_smi_empty_output_returns_none(monkeypatch):
    monkeypatch.setattr(MP.subprocess, "run", lambda *a, **k: _Out(0, b"\n"))
    assert MP.nvidia_smi_free_gb(force=True) is None


def test_smi_garbage_output_returns_none(monkeypatch):
    monkeypatch.setattr(MP.subprocess, "run", lambda *a, **k: _Out(0, b"not-a-number\n"))
    assert MP.nvidia_smi_free_gb(force=True) is None


def test_smi_binary_missing_returns_none(monkeypatch):
    """没装 nvidia-smi（FileNotFoundError）⇒ None，不抛。"""
    def _boom(*a, **k):
        raise FileNotFoundError("nvidia-smi")
    monkeypatch.setattr(MP.subprocess, "run", _boom)
    assert MP.nvidia_smi_free_gb(force=True) is None


def test_smi_timeout_returns_none(monkeypatch):
    def _boom(*a, **k):
        raise TimeoutError("slow")
    monkeypatch.setattr(MP.subprocess, "run", _boom)
    assert MP.nvidia_smi_free_gb(force=True) is None


# ══════════════════════════════════════════════════════════════════
# ④ 缓存
# ══════════════════════════════════════════════════════════════════

def test_smi_is_cached_within_ttl(monkeypatch):
    """TTL 内重复调用只起一次 subprocess（决策链上会被频繁调用）。"""
    calls = {"n": 0}

    def _run(*a, **k):
        calls["n"] += 1
        return _Out(0, b"5120\n")

    monkeypatch.setattr(MP.subprocess, "run", _run)

    a = MP.nvidia_smi_free_gb()
    b = MP.nvidia_smi_free_gb()
    c = MP.nvidia_smi_free_gb()

    assert a == b == c == 5.0
    assert calls["n"] == 1, "TTL 内不该反复起进程"


def test_smi_force_bypasses_cache(monkeypatch):
    calls = {"n": 0}

    def _run(*a, **k):
        calls["n"] += 1
        return _Out(0, b"5120\n")

    monkeypatch.setattr(MP.subprocess, "run", _run)

    MP.nvidia_smi_free_gb()
    MP.nvidia_smi_free_gb(force=True)
    assert calls["n"] == 2


def test_smi_none_result_is_also_cached(monkeypatch):
    """"查不到"也要缓存，否则每次决策都白等一次超时。"""
    calls = {"n": 0}

    def _run(*a, **k):
        calls["n"] += 1
        return _Out(1, b"")

    monkeypatch.setattr(MP.subprocess, "run", _run)

    assert MP.nvidia_smi_free_gb() is None
    assert MP.nvidia_smi_free_gb() is None
    assert calls["n"] == 1

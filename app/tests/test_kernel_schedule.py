# -*- coding: utf-8 -*-
"""时间轴与调度器交互测试 —— P2 · 2026-10-28。

## 三条"抄上游"的判据，逐条锁

① **先按满步数设表，再截尾**（i2i）。反了会得到另一套 sigma 序列：图变了、不报错。
② **进度/取消按 `len(timesteps)` 算**，不是按 `num_inference_steps`。
   PNDM/UniPC 的 `order > 1` 时两者不等，按请求步数算会让最后几步永远等不到"完成"。
③ **`extra_step_kwargs` 按真实签名探测**。全传会在不支持 `eta` 的调度器上 TypeError；
   全不传会丢掉 DDIM 的 `eta` 随机性 ⇒ 同 seed 不可复现。
"""
from __future__ import annotations

import pytest

from app.core.neural.kernel import schedule as S


class FakeScheduler:
    """最小可用的调度器替身：只记录 `set_timesteps` 被怎么调的。"""

    order = 1
    init_noise_sigma = 1.0

    def __init__(self, order: int = 1) -> None:
        self.order = order
        self.timesteps = []
        self.calls = []

    def set_timesteps(self, n, device=None):
        self.calls.append((n, device))
        # 模拟 order>1 的调度器：步数被展开成 n*order
        self.timesteps = list(range(n)) * self.order
        self.timesteps = sorted(self.timesteps, reverse=True)

    def step(self, noise, t, sample, eta=0.0, generator=None, return_dict=False):
        return (sample,)


# ══════════════════════════════════════════════════════════════════
# build_timesteps
# ══════════════════════════════════════════════════════════════════

def test_build_returns_full_schedule_for_t2i():
    sch = FakeScheduler()
    ts, n = S.build_timesteps(sch, 20, device="cpu", strength=1.0)
    assert n == 20
    assert len(ts) == 20
    assert sch.calls == [(20, "cpu")], "设备必须传给 set_timesteps（否则每步多一次 H2D）"


def test_build_sets_full_steps_then_truncates():
    """i2i：`t_start = n - int(n*strength)`，按 `t_start*order` 切。

    strength=0.5、n=20 ⇒ init=10、t_start=10 ⇒ 取后 10 步。
    若先减步数再设表，`set_timesteps` 会收到 10（而不是 20），
    sigma 序列完全不同 —— 这条断言就是拦那个写法。
    """
    sch = FakeScheduler()
    ts, n = S.build_timesteps(sch, 20, device="cpu", strength=0.5)
    assert sch.calls == [(20, "cpu")], "必须先按满步数设表"
    assert len(ts) == 10
    assert n == 10


def test_build_truncation_respects_order():
    """`order=2` 的调度器：切点要乘 order，否则截出来的是步数的一半再一半。"""
    sch = FakeScheduler(order=2)
    ts, n = S.build_timesteps(sch, 10, device="cpu", strength=0.5)
    # 满表 = 10*2 = 20 个 timestep；t_start = 10 - 5 = 5 ⇒ 切 5*2 = 10 个
    assert len(ts) == 10
    assert n == 10


def test_build_never_returns_zero_steps():
    """strength 极小（或 0）时必须至少给 1 步：0 步会让循环什么都不做，出图是全噪。"""
    sch = FakeScheduler()
    ts, n = S.build_timesteps(sch, 20, device="cpu", strength=0.001)
    assert n >= 1
    assert len(ts) >= 1


def test_build_clamps_steps_to_at_least_one():
    sch = FakeScheduler()
    ts, n = S.build_timesteps(sch, 0, device="cpu", strength=1.0)
    assert n == 1 and sch.calls == [(1, "cpu")]


def test_build_handles_scheduler_without_device_kwarg():
    """个别调度器的 `set_timesteps` 不收 device：不能因此崩，且要尝试搬表。"""
    class _Strict(FakeScheduler):
        def set_timesteps(self, n):
            self.calls.append((n, None))
            self.timesteps = list(range(n))

    sch = _Strict()
    ts, n = S.build_timesteps(sch, 5, device="cuda:0", strength=1.0)
    assert n == 5 and len(ts) == 5
    assert sch.calls == [(5, None)]


# ══════════════════════════════════════════════════════════════════
# extra_step_kwargs
# ══════════════════════════════════════════════════════════════════

def test_extra_kwargs_passes_eta_and_generator_when_declared():
    got = S.extra_step_kwargs(FakeScheduler(), generator="G", eta=0.3)
    assert got == {"eta": 0.3, "generator": "G"}


def test_extra_kwargs_omits_generator_when_none():
    got = S.extra_step_kwargs(FakeScheduler(), generator=None, eta=0.0)
    assert "generator" not in got


def test_extra_kwargs_only_declared_keys():
    """调度器只声明 `sample`（无 eta / generator）⇒ 一个都不传，否则 TypeError。"""
    class _Plain:
        def step(self, model_output, timestep, sample):
            return (sample,)

    assert S.extra_step_kwargs(_Plain(), generator="G", eta=0.3) == {}


def test_extra_kwargs_uninspectable_signature_is_conservative():
    class _Opaque:
        step = object()          # 取不到签名

    assert S.extra_step_kwargs(_Opaque(), generator="G", eta=0.3) == {}


# ══════════════════════════════════════════════════════════════════
# init_noise_sigma / order
# ══════════════════════════════════════════════════════════════════

def test_init_noise_sigma_plain_float():
    class _S:
        init_noise_sigma = 1.5

    assert S.init_noise_sigma(_S()) == 1.5


def test_init_noise_sigma_zero_dim_tensor():
    """部分调度器把它做成 0 维张量：`float(tensor)` 会失败，必须走 `item()`。"""
    torch = pytest.importorskip("torch")

    class _S:
        init_noise_sigma = torch.tensor(2.0)

    assert S.init_noise_sigma(_S()) == 2.0


def test_init_noise_sigma_missing_defaults_one():
    class _S:
        pass

    assert S.init_noise_sigma(_S()) == 1.0


def test_scheduler_order_defaults_one():
    class _S:
        pass

    assert S.scheduler_order(_S()) == 1
    assert S.scheduler_order(FakeScheduler(order=3)) == 3


def test_scheduler_order_never_below_one():
    class _S:
        order = 0

    assert S.scheduler_order(_S()) == 1

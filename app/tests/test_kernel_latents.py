# -*- coding: utf-8 -*-
"""初始潜变量测试 —— P2 · 2026-10-28。

## 为什么这一条值得单独一个文件

验收第一门是「初始 latents **比特一致**」。它会因为一个极不起眼的选择而失败：
`torch.randn(shape, generator=g, device="cuda")` 与
`torch.randn(shape, generator=g)` 再 `.to("cuda")` 生成的是**不同的数**。

于是"同 seed 可复现"当场失效 —— 不报错、只换图。所以这里断言的是 `torch.equal`
（逐位），不是 `allclose`：1e-7 的差异也意味着"这个 seed 的历史结果作废了"。

## `init_noise_sigma` 是参数不是常数

SD 系 = 1.0，视频族（Wan）不乘。写成常数 `* 1.0` 在 SD 上永远看不出问题，
换族才炸 —— 所以测试里用一个 ≠1 的 sigma 来证明它**真的被用上了**。
"""
from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")

from app.core.neural.kernel import latents as LAT


def _cpu_gen(seed: int = 3):
    return torch.Generator("cpu").manual_seed(seed)


# ══════════════════════════════════════════════════════════════════
# 比特一致
# ══════════════════════════════════════════════════════════════════

def test_make_matches_upstream_randn_bitwise():
    """同 seed 同形状 ⇒ 与上游 `randn_tensor` **逐位**相同（不是近似）。"""
    from diffusers.utils.torch_utils import randn_tensor

    ref = randn_tensor((1, 4, 64, 64), generator=_cpu_gen(3), device="cpu", dtype=torch.float32)
    ours = LAT.make(batch=1, channels=4, height=512, width=512, latent_scale=8,
                    generator=_cpu_gen(3), device="cpu", dtype=torch.float32,
                    init_noise_sigma=1.0)
    assert torch.equal(ref, ours), "初始 latents 必须比特一致"


def test_make_is_reproducible_across_calls():
    a = LAT.make(batch=1, channels=4, height=256, width=256, latent_scale=8,
                 generator=_cpu_gen(11), device="cpu", dtype=torch.float32)
    b = LAT.make(batch=1, channels=4, height=256, width=256, latent_scale=8,
                 generator=_cpu_gen(11), device="cpu", dtype=torch.float32)
    assert torch.equal(a, b)


def test_make_different_seed_differs():
    """反向断言：换个 seed 结果必须不同，否则上面的"一致"毫无意义。"""
    a = LAT.make(batch=1, channels=4, height=256, width=256, latent_scale=8,
                 generator=_cpu_gen(1), device="cpu", dtype=torch.float32)
    b = LAT.make(batch=1, channels=4, height=256, width=256, latent_scale=8,
                 generator=_cpu_gen(2), device="cpu", dtype=torch.float32)
    assert not torch.equal(a, b)


# ══════════════════════════════════════════════════════════════════
# 尺寸与 sigma
# ══════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("h,w,scale,expect", [
    (512, 512, 8, (64, 64)),
    (1024, 1024, 8, (128, 128)),
    (513, 511, 8, (64, 63)),      # 向下取整，与上游 // 一致
    (512, 512, 16, (32, 32)),
])
def test_latent_hw_floors(h, w, scale, expect):
    assert LAT.latent_hw(h, w, scale) == expect


def test_make_output_shape():
    out = LAT.make(batch=2, channels=4, height=512, width=768, latent_scale=8,
                   generator=_cpu_gen(0), device="cpu", dtype=torch.float32)
    assert tuple(out.shape) == (2, 4, 64, 96)


def test_init_noise_sigma_is_applied():
    """sigma≠1 时必须真的乘上去（否则视频族会得到错误噪声强度，且只有它能发现）。"""
    gen_a, gen_b = _cpu_gen(7), _cpu_gen(7)
    base = LAT.make(batch=1, channels=4, height=256, width=256, latent_scale=8,
                    generator=gen_a, device="cpu", dtype=torch.float64,
                    init_noise_sigma=1.0)
    scaled = LAT.make(batch=1, channels=4, height=256, width=256, latent_scale=8,
                      generator=gen_b, device="cpu", dtype=torch.float64,
                      init_noise_sigma=2.5)
    assert torch.allclose(scaled, base * 2.5, atol=1e-12)


def test_make_keeps_dtype():
    out = LAT.make(batch=1, channels=4, height=256, width=256, latent_scale=8,
                   generator=_cpu_gen(0), device="cpu", dtype=torch.float16)
    assert out.dtype == torch.float16


# ══════════════════════════════════════════════════════════════════
# 已有潜变量（i2i / 链式续生）
# ══════════════════════════════════════════════════════════════════

def test_given_latents_are_not_resampled():
    given = torch.arange(1 * 4 * 8 * 8, dtype=torch.float32).reshape(1, 4, 8, 8)
    out = LAT.make(batch=1, channels=4, height=64, width=64, latent_scale=8,
                   generator=_cpu_gen(0), device="cpu", dtype=torch.float32,
                   latents=given)
    assert torch.equal(out, given), "给了潜变量就只能搬设备，绝不许重新采样"


def test_given_latents_still_get_sigma():
    """i2i 的 sigma 语义与 t2i 一致：加噪强度由调用方通过 sigma 决定。"""
    given = torch.ones(1, 4, 8, 8)
    out = LAT.make(batch=1, channels=4, height=64, width=64, latent_scale=8,
                   generator=None, device="cpu", dtype=torch.float32,
                   init_noise_sigma=0.5, latents=given)
    assert torch.allclose(out, torch.full_like(given, 0.5))


# ══════════════════════════════════════════════════════════════════
# add_noise
# ══════════════════════════════════════════════════════════════════

class _SchedWithAddNoise:
    def __init__(self) -> None:
        self.calls = []

    def add_noise(self, latents, noise, timestep):
        self.calls.append((latents, noise, timestep))
        return latents + noise * 0.0 + 42.0


def test_add_noise_delegates_to_scheduler():
    """必须调调度器自己的公式：各调度族公式不同，手写只对 eps 族成立。"""
    sch = _SchedWithAddNoise()
    lat = torch.zeros(1, 4, 4, 4)
    noise = torch.ones(1, 4, 4, 4)
    out = LAT.add_noise(lat, noise, 999, sch)
    assert len(sch.calls) == 1, "每调用一次只允许问调度器一次"
    assert float(out.flatten()[0]) == 42.0


def test_add_noise_falls_back_visibly(caplog):
    """调度器没有 add_noise 时退化成相加（仅 eps 族近似），但**必须**留下 warning。"""
    class _NoAddNoise:
        pass

    lat = torch.zeros(1, 4, 2, 2)
    noise = torch.ones(1, 4, 2, 2)
    with caplog.at_level("WARNING", logger="app.core.neural.kernel.latents"):
        out = LAT.add_noise(lat, noise, 1, _NoAddNoise())

    assert float(out.flatten()[0]) == 1.0
    assert any("add_noise" in r.message for r in caplog.records), "退路必须可见"

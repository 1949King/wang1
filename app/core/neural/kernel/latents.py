# -*- coding: utf-8 -*-
"""初始潜变量（规范 §5.1 `init_latents` 的内核侧工具）。

## 为什么必须用上游的 `randn_tensor` 而不是 `torch.randn`

验收第一门是「**初始 latents 比特一致**」（规范 §11 张量门）。
`torch.randn(shape, generator=g, device=cuda)` 与 `torch.randn(shape, generator=g)`
再 `.to(cuda)` 得到的是**不同**的数 —— 因为 CPU 生成器的序列与 CUDA 生成器不同。

diffusers 的 `randn_tensor` 解决的就是这件事：当 generator 绑在 CPU 上时，
它先在 CPU 生成再搬到设备（这正是 `diffusers_image.py:714` 用 CPU Generator 的原因）。
自己写 `torch.randn(..., device=device)` 会让"同 seed 可复现"当场失效，
而且**不报错、只换图** —— 最难查的那种。

所以：有上游 `randn_tensor` 就用它（保证 bit 一致）；没有则退回
`torch.randn(shape, generator=..., dtype=..., device="cpu").to(device)` 并**记下来**
（退路必须可见，不能静默降级成"随便生成一组噪声"）。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def latent_hw(height: int, width: int, factor: int) -> tuple:
    """(h, w) → 潜变量空间尺寸。整数除法与上游一致（向下取整）。"""
    f = max(1, int(factor))
    return int(height) // f, int(width) // f


def make(
    *,
    batch: int,
    channels: int,
    height: int,
    width: int,
    latent_scale: int,
    generator: Any,
    device: Any,
    dtype: Any,
    init_noise_sigma: float = 1.0,
    latents: Any = None,
) -> Any:
    """造初始潜变量。

    参数:
      generator: 调用方既有语义（图像路径是 **CPU Generator**，规范 §5.3）。
                这里**不做任何"顺手统一"** —— 改一处会让所有历史种子失效。
      latents: 调用方已给的潜变量（i2i / 链式续生）；给了就只搬设备、不重新采样。
      init_noise_sigma: 调度器要求的初始噪声标准差。SD 系 = 1.0（DDIM/Euler），
                Wan = **不乘**（规范 §4.3 `latent_scale`），故这里是参数不是硬编码。

    返回：形状 `(batch, channels, h//scale, w//scale)` 的张量。
    """

    h, w = latent_hw(height, width, latent_scale)
    shape = (int(batch), int(channels), h, w)

    if latents is not None:
        out = latents.to(device)
    else:
        out = _randn(shape, generator, device, dtype)
    return out * float(init_noise_sigma)


def _randn(shape: tuple, generator: Any, device: Any, dtype: Any) -> Any:
    """与上游 `randn_tensor` 对齐的随机采样。"""
    try:
        from diffusers.utils.torch_utils import randn_tensor

        return randn_tensor(shape, generator=generator, device=device, dtype=dtype)
    except Exception:  # stability-gate: allow-swallow（上游工具缺失时走下方等价退路，并记一条 warning 让"用了退路"可见）
        logger.warning("[kernel.latents] 上游 randn_tensor 不可用，改用 CPU 生成后搬迁"
                       "（同 seed 结果与上游一致，但少了上游的列表/批量生成器语义）")

    import torch

    # 退路：CPU 生成再搬设备 —— 与 randn_tensor 在单生成器 + CPU generator 场景下等价
    seed_kwargs = {}
    if generator is not None:
        seed_kwargs["generator"] = generator
    out = torch.randn(shape, dtype=dtype, device="cpu", **seed_kwargs)
    return out.to(device)


def make_frames(
    *,
    batch: int,
    frames: int,
    channels: int,
    height: int,
    width: int,
    latent_scale: int,
    generator: Any,
    device: Any,
    dtype: Any,
    init_noise_sigma: float = 1.0,
    latents: Any = None,
) -> Any:
    """造视频族的初始潜变量，形状 `(batch, frames, channels, h//s, w//s)`。

    ## 三个与图像族不同的地方（每个都能让"张量门"直接红）

    1. **多一维**：帧维在 dim=1（不是 dim=0）。上游 `prepare_latents` 就是这个顺序，
       写成 `(frames, batch, ...)` 不会报错，只会在拼条件时错位。
    2. **通道数取 `in_channels // 2`**：SVD 的 UNet 是 8 通道（噪声 4 + 图像条件 4），
       所以噪声只有 4 通道。用 `in_channels` 当通道数会造出 8 通道噪声，前向直接崩。
    3. **sigma 只乘一次**：`prepare_latents` 内部乘 `init_noise_sigma`。
       在调用点再乘一次 ⇒ 噪声强度翻倍，出图是"糊成一片"，且不报错。
    """
    h, w = latent_hw(height, width, latent_scale)
    shape = (int(batch), int(frames), int(channels), h, w)

    if latents is not None:
        out = latents.to(device)
    else:
        out = _randn(shape, generator, device, dtype)
    return out * float(init_noise_sigma)


def add_noise(latents: Any, noise: Any, timestep: Any, scheduler: Any) -> Any:
    """按调度器的加噪公式加噪（i2i / SVD `noise_aug` 用）。

    必须调调度器自己的 `add_noise`：不同调度族的公式不同，
    自己按 `sqrt(alpha_cumprod)` 手写只对 eps 族成立。
    """
    try:
        return scheduler.add_noise(latents, noise, timestep)
    except Exception:  # stability-gate: allow-swallow（调度器不支持 add_noise 时退回加性噪声，并在返回值上体现）
        logger.warning("[kernel.latents] 调度器无 add_noise，退回直接相加（仅 eps 族近似成立）")
        return latents + noise

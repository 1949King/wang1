# -*- coding: utf-8 -*-
"""CFG（无分类器引导）组合（规范 §4.3 `cfg_mode` 的实现侧）。

## 三种组合方式，不是"选一个实现"

| 模式 | 做法 | 用在哪 |
|---|---|---|
| `cat` | `cat([x]*2)` 一次前向 batch=2，出结果后 `chunk(2)` | SD1.5 / SDXL |
| `two_pass` | 跑两次前向分别得 uncond / cond | Wan 等（显存换峰值） |
| `none` | 不做引导 | cfg ≤ 1 时 |

**为什么默认必须是 `cat`**：`StepFeatureCache` 靠上游 `unet` 的 pre-hook 调用次数
推断步号（`inference_cache.py:294-304`）。拆成两次前向会让步号整体偏移一倍 ⇒
步缓存的跳步全错。这条坑写在开发指南 §6.3，这里是它的代码侧落点。

## chunk 顺序是 `(uncond, text)`

不是 `(text, uncond)`。上游是 `torch.cat([negative_prompt_embeds, prompt_embeds])`
（SDXL 明确按此序 cat，SD1.5 同）。写反了不会报错，只会得到"负向引导"：
CFG 越大越难看，而人眼第一时间会以为是"模型问题"。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

#: chunk 顺序契约（ParityContract 里也用这个字面值）
CFG_ORDER = "neg_pos"


def expand_for_guidance(tensor: Any, multiplier: int) -> Any:
    """按 `cfg_batch_multiplier` 把潜变量沿 batch 维复制。

    注意复制的是**同一个 latent**（不是 neg/pos 两份不同的），
    条件差异由 `encoder_hidden_states` 承担 —— 这是 CFG 的本质。
    """
    if multiplier <= 1:
        return tensor
    try:
        import torch

        return torch.cat([tensor] * int(multiplier))
    except Exception:  # stability-gate: allow-swallow（无 torch 时说明调用路径不对，上层会以缺少依赖拒绝，不在这里炸）
        return tensor


def combine(noise: Any, *, mode: str = "cat", scale: float = 1.0,
            rescale: float = 0.0) -> Any:
    """把前向输出合成最终噪声预测。

    `scale <= 1` 时**不做引导**（与上游 `guidance_scale > 1` 的判据一致：
    scale=1 时 uncond + 1*(text-uncond) == text，多做一次减法纯属浪费精度）。
    """
    if mode == "none" or mode == "two_pass" or float(scale) <= 1.0:
        # two_pass 由调用方自己在 forward 阶段分别算好再调 `combine_two_pass`
        return noise
    try:
        uncond, text = noise.chunk(2)
    except Exception:  # stability-gate: allow-swallow（batch 维不对说明 adapter 声明与实现不一致，交给 validate 报原因）
        return noise
    out = uncond + float(scale) * (text - uncond)
    if float(rescale) > 0.0:
        out = rescale_noise_cfg(out, text, guidance_rescale=float(rescale))
    return out


def combine_two_pass(uncond: Any, text: Any, *, scale: float = 1.0,
                     rescale: float = 0.0) -> Any:
    """`two_pass` 模式：两次前向的输出来了之后再做同样的线性组合。"""
    if float(scale) <= 1.0:
        return text
    out = uncond + float(scale) * (text - uncond)
    if float(rescale) > 0.0:
        out = rescale_noise_cfg(out, text, guidance_rescale=float(rescale))
    return out


def rescale_noise_cfg(noise_cfg: Any, noise_pred_text: Any,
                      guidance_rescale: float = 0.0) -> Any:
    """CFG rescale（论文 arXiv:2305.08891 §3.4）。

    重实现而非 import：这是 6 行纯算术，自己写换来"上游变了也不影响内核"（C3），
    同时由 `test_kernel_cfg.py` 与上游逐值对照锁住等价性 —— 有对照就不算重复造轮子。
    """
    import torch


    std_text = noise_pred_text.std(dim=list(range(1, noise_pred_text.ndim)), keepdim=True)
    std_cfg = noise_cfg.std(dim=list(range(1, noise_cfg.ndim)), keepdim=True)
    # `std_cfg == 0`（整步预测恒定）时上游会除以 0 → 整张图变 nan，且不报错。
    # 这里的选择是**整步放弃 rescale**，而不是 clamp 后继续算：
    #   clamp 会得到 `0/eps = 0` ⇒ 结果被乘成 `(1-r)` 倍，幅度被悄悄改小；
    #   nan 会让整图作废但至少显眼；跳过 rescale 则保持原预测不变 —— 三者里只有它不骗人。
    eps = float(torch.finfo(noise_cfg.dtype).eps)
    try:
        if float(std_cfg.min()) <= eps or not bool(torch.isfinite(std_cfg).all()):
            logger.debug("[kernel.cfg] std_cfg≈0，跳过 rescale（保持原始噪声预测）")
            return noise_cfg
        noise_pred_rescaled = noise_cfg * (std_text / std_cfg)
    except Exception:  # stability-gate: allow-swallow（统计量算不出来说明入参不是张量，直接跳过 rescale）
        logger.debug("[kernel.cfg] 无法计算 std，跳过 rescale", exc_info=True)
        return noise_cfg
    return guidance_rescale * noise_pred_rescaled + (1.0 - guidance_rescale) * noise_cfg

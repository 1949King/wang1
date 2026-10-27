# -*- coding: utf-8 -*-
"""时间轴与调度器交互（规范 §5.1 `make_timesteps` 的内核侧工具）。

## 为什么时间轴要单独抽出

调度器的 `set_timesteps` 有三个坑，任何一个踩了都不报错：
  1. **设备**：`set_timesteps(n, device=...)` 把 timesteps 表放到设备上；
     不放会让每步多一次 H2D 拷贝（步数 20+ 时可测）。
  2. **order**：DDIM 的 `order=1`，但 PNDM/UniPC 的 `order>1` 会让
     `len(timesteps) > num_inference_steps`，进度条与取消点都必须按 **len(timesteps)**
     算，不能按 `num_inference_steps` 算 —— 否则最后几步永远等不到"完成"。
  3. **extra_step_kwargs**：不同调度器的 `step()` 签名不同（`eta` / `generator`）。
     不按 `inspect.signature` 探测就传，会在某些调度器上抛 TypeError；
     全都不传又会丢掉 DDIM 的随机性（`eta>0` 时结果不可复现）。

这三条都是"抄上游"抄出来的，不是设计出来的。所以本文件的判据是
**与上游 `retrieve_timesteps` 行为等价**，而不是"我觉得应该这样"。
"""
from __future__ import annotations

import inspect
import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


def build_timesteps(
    scheduler: Any,
    steps: int,
    *,
    device: Any = None,
    strength: float = 1.0,
) -> Tuple[Any, int]:
    """设置并返回时间轴。

    返回 `(timesteps, num_inference_steps)`，其中 `num_inference_steps` 是**实际**步数
    （i2i 按 strength 截断后可能小于请求步数）。

    `strength < 1` 的截断公式与上游 i2i 一致：
      `init_timestep = min(int(steps * strength), steps)`
      `t_start = max(steps - init_timestep, 0)`
      `timesteps = scheduler.timesteps[t_start * order:]`
    顺序很重要：先按**满步数**设表，再截尾 —— 反过来（先减步数再设表）会得到
    一套完全不同的 sigma 序列，图会变、且不报错。
    """
    n = max(1, int(steps))
    try:
        if device is not None:
            scheduler.set_timesteps(n, device=device)
        else:
            scheduler.set_timesteps(n)
    except TypeError:
        # 个别调度器的 set_timesteps 不接受 device（或位置参数语义不同）
        scheduler.set_timesteps(n)
        if device is not None:
            try:
                scheduler.timesteps = scheduler.timesteps.to(device)
            except Exception:  # stability-gate: allow-swallow（搬不到设备只是慢一点：每步多一次拷贝，不影响正确性）
                logger.debug("[kernel.schedule] timesteps 未能搬到设备", exc_info=True)

    timesteps = scheduler.timesteps
    s = float(strength) if strength is not None else 1.0
    if s >= 1.0:
        return timesteps, n

    order = int(getattr(scheduler, "order", 1) or 1)
    # 下界必须是 1：`int(n * 0.001) == 0` 时 `t_start == n`，截出来是空表。
    # 空表的后果不是"少跑几步"，而是"一步都不跑却按成功返回" —— 出图是全噪，
    # 回执里 steps 还写着 1。宁可按最小强度跑 1 步，也不要交一张噪声图。
    init = max(1, min(int(n * s), n))
    t_start = max(n - init, 0)
    sliced = timesteps[t_start * order:]
    return sliced, max(1, len(sliced))


def extra_step_kwargs(scheduler: Any, generator: Any = None,
                      eta: float = 0.0) -> Dict[str, Any]:
    """按调度器 `step()` 的真实签名决定传什么。

    只传它**声明接受**的键，一个不多一个不少 —— 上游 `prepare_extra_step_kwargs` 同逻辑。
    """
    out: Dict[str, Any] = {}
    try:
        params = set(inspect.signature(scheduler.step).parameters.keys())
    except (TypeError, ValueError):  # 签名取不到（C 扩展/装饰器）⇒ 什么都不传，最保守
        logger.debug("[kernel.schedule] 取不到 scheduler.step 签名，按不传可选参数处理")
        return out
    if "eta" in params:
        out["eta"] = float(eta)
    if "generator" in params and generator is not None:
        out["generator"] = generator
    return out


def init_noise_sigma(scheduler: Any) -> float:
    """调度器要求的初始噪声标准差。

    取不到时返回 1.0 并记 debug：SD 系（DDIM/Euler/UniPC）都是 1.0，
    LCM/流匹配族可能不是 —— 所以这里**不静默兜底成"肯定对"**，
    而是让 `AdapterCaps.latent_scale` 决定是否使用这个值（规范 §4.3）。
    """
    v = getattr(scheduler, "init_noise_sigma", None)
    if v is None:
        return 1.0
    try:
        return float(v)
    except (TypeError, ValueError):
        # 少数调度器把它做成张量（0 维），转 float 会失败 → 走 item()
        try:
            return float(v.item())
        except Exception:  # stability-gate: allow-swallow（取不到就按 1.0：SD 系一直如此，且已记 debug）
            logger.debug("[kernel.schedule] init_noise_sigma 无法转数值，按 1.0", exc_info=True)
            return 1.0


def scheduler_order(scheduler: Any) -> int:
    """`order`；拿不到按 1（上游默认）。进度与取消判定都要用它。"""
    try:
        return max(1, int(getattr(scheduler, "order", 1) or 1))
    except (TypeError, ValueError):
        return 1


def describe(scheduler: Any) -> Optional[str]:
    """调度器类名（诊断/证据台账用）。"""
    try:
        return type(scheduler).__name__
    except Exception:  # stability-gate: allow-swallow（纯诊断信息，取不到不影响生成）
        return None

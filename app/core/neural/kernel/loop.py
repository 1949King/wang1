# -*- coding: utf-8 -*-
"""去噪循环 —— **全仓唯一允许出现 for-step 的地方**（规范 §3 H1/H2）。

## 这个文件只有四句话

一步去噪拆成四个动作，各自由 adapter 实现：

```
prepare_step  → 把当前潜变量加工成"模型能吃的形式"（缩放、拼 CFG batch、带上条件）
forward       → 真正的前向（子类决定调哪个网络、传哪些 kwargs）
guide         → 把输出合成最终噪声预测（CFG 线性组合 / 重缩放）
step          → 交给调度器推进一步
```

循环本身**不知道自己跑的是哪个族**：没有族名、没有组件名、没有条件张量名。
这是 C3（上游可替换）唯一能成立的写法 —— 内核不认识上游，才能换掉上游。

## 反过来：为什么不在 adapter 里各自写循环

每个族写一遍 for 循环，等于把"取消在哪检查、进度怎么报、步号怎么算、
异常怎么带上步号"复制 N 份。改动一处就得改 N 处，而漏掉的那一份
**不会报错**，只会让某个族的取消失效或进度卡住 —— 项目对"静默降级"的容忍度是零。

## 取消与进度的位置是刻意选的

- **取消检查在每步开头**：放在末尾会让"最后一步已经跑完还被判取消"，
  出现"结果有效但返回 cancelled"的矛盾态。
- **`before_step`/`after_step` 成对**：`after_step` 里记耗时，配对才能算出单步时间。
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.core.neural.kernel import grad_mode as GRAD
from app.core.neural.kernel.contracts import DenoiseOutput, RunState
from app.core.neural.kernel.hooks import NullHooks, StepEvent

logger = logging.getLogger(__name__)


def denoise(
    adapter: Any,
    state: RunState,
    hooks: Any = None,
    instrument: Any = None,
) -> DenoiseOutput:
    """跑完整条时间轴。

    参数:
      adapter: 至少实现 `prepare_step / forward / guide / step` 四个方法。
               **本函数不检查具体类型** —— 传假 adapter 就能在 CPU 上做逐 step 对照。
      state: `RunState`，`timesteps` 与 `latents` 必填。
      hooks: 步间钩子；None 用 `NullHooks`（零开销）。
      instrument: 分段计时器；None 不记。

    返回: `DenoiseOutput`。取消时 `cancelled=True` 且 `step_count` 是**已完成的步数**
          （不是"跑了几步的一半"）。
    """
    hook = hooks if hooks is not None else NullHooks()
    steps = state.timesteps
    total = _len(steps)
    latents = state.latents

    # 推理态：不建计算图（原因见 grad_mode.py 文档；漏掉不报错、只涨显存与炸解码）
    with GRAD.inference():
        for i, t in enumerate(steps):
            if hook.cancelled():
                # 一条 INFO 足够：这是正常业务路径，不是异常
                logger.info("[kernel.loop] 第 %d/%d 步前收到取消，返回已完成的结果", i, total)
                hook.finished(False, "已取消（完成 %d/%d 步）" % (i, total))
                state.latents = latents
                return DenoiseOutput(latents=latents, state=state,
                                     cancelled=True, step_count=i)

            ev = StepEvent(index=i, total=total, timestep=t)
            hook.before_step(ev)

            prepared = adapter.prepare_step(latents, t, state)
            noise = adapter.forward(prepared, state)
            noise = adapter.guide(noise, prepared, state)
            latents = adapter.step(noise, t, prepared, state)

            hook.after_step(ev, latents)
            if instrument is not None:
                instrument.mark_step({
                    "index": i,
                    "timestep": _scalar(t),
                    "elapsed_ms": ev.elapsed_ms,
                    "absmax": getattr(ev, "_absmax", None),
                })

    hook.finished(True)
    state.latents = latents
    state.steps = total
    return DenoiseOutput(latents=latents, state=state, cancelled=False,
                         step_count=total)


def _len(steps: Any) -> int:
    try:
        return int(len(steps))
    except TypeError:
        return 0


def _scalar(t: Any) -> Optional[float]:
    try:
        return float(t.item())
    except Exception:  # stability-gate: allow-swallow（打点用，转不了就记 None）
        return None


def check_step_order(adapter: Any) -> Optional[str]:
    """契约体检：adapter 是否真的实现了四件事。

    不抛异常而是**返回原因**（规范 §5.1 `validate` 同一纪律）：
    让调用方自己决定拒绝还是记日志，内核不替它决定。
    """
    need = ("prepare_step", "forward", "guide", "step")
    missing = [m for m in need if not callable(getattr(adapter, m, None))]
    if missing:
        return "adapter 缺少必需方法：%s" % ", ".join(missing)
    return None

# -*- coding: utf-8 -*-
"""推理态上下文 —— 全仓唯一决定"要不要建计算图"的地方。

## 为什么这件事必须单独成模块

上游 `StableDiffusionPipeline.__call__` 挂着 `@torch.no_grad()`。
自己写循环时**漏掉它不会立刻报错**：前向照样算，图照样出，
代价只有两个，而且都不像"梯度问题"：

1. **显存**：每一步的激活值都被保留到循环结束，20 步就是 20 份。
   在 8GB 卡上表现为"突然 OOM"，或者更糟 —— WDDM 换页，
   单步 1.4s 变 68.9s，且**不报任何错**。
2. **解码炸栈**：`image_processor.postprocess` 内部走 `numpy()`，
   遇到 `requires_grad=True` 的张量直接 `RuntimeError`。
   报错点在解码，根因在循环 —— 典型的"错在三步之外"。

所以判据只能有一处：`engine.run` 与 `loop.denoise` 都用这里返回的**同一个**
上下文对象，而不是各自写一句 `with torch.no_grad()`。

## 为什么用 `no_grad` 而不是 `inference_mode`

`inference_mode` 更快，但它产出的是**推理张量**：一旦出了作用域还在被原地修改，
会抛 `Inplace update to inference tensor outside InferenceMode is not allowed`。
我们的解码发生在循环之后（作用域之外），`postprocess` 里的 in-place 归一化
正好会踩这条。省下的那点开销不值得换一个"看起来莫名其妙"的崩溃。
"""
from __future__ import annotations

import contextlib

__all__ = ["inference", "enabled"]


@contextlib.contextmanager
def inference():
    """推理态上下文：能拿到 torch 就关梯度，拿不到就空转。

    拿不到 torch 的情形（单测用假 adapter 跑纯 Python 逻辑）不应因缺依赖而失败，
    所以这里**静默空转**而不是抛异常。
    """
    try:
        import torch
    except Exception:  # stability-gate: allow-swallow（无 torch 时纯 Python 路径仍要走通）
        yield
        return
    with torch.no_grad():
        yield


def enabled() -> bool:
    """当前是否处于"不建图"状态（体检 / 单测用）。"""
    try:
        import torch
    except Exception:  # stability-gate: allow-swallow（无 torch 视为不需要建图）
        return True
    return not torch.is_grad_enabled()

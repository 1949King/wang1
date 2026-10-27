# -*- coding: utf-8 -*-
"""自研去噪执行内核（规范 §3）。

对外口径固定：**「自研去噪执行内核」**。
模型权重、scheduler 数学、VAE 算子来自上游 ⇒ 不称「自研推理引擎」
（`docs/design/推理引擎设计规范.md` §2 第 1 条）。

分层（依赖单向向下）：

```
engine.py      唯一知道全流程的地方；三态开关在这里
loop.py        ★ 唯一出现 for-step 的地方，且不含任何族名/组件名（H1）
adapters/      族语义全部在这里；不含 for-step（H2）
latents/schedule/cfg/hooks/instrument/evidence   原子工具，顶层不 import torch（H3）
contracts.py   契约，纯 Python，无任何重依赖
```

用法见 `engine.run()`；命令行体检见 `scripts/kernel_status.py`。
"""
from app.core.neural.kernel.contracts import (
    CONTRACT_VERSION,
    AdapterCaps,
    GenRequest,
    KernelReport,
    ParityContract,
    RunState,
)

__all__ = [
    "CONTRACT_VERSION",
    "AdapterCaps",
    "GenRequest",
    "KernelReport",
    "ParityContract",
    "RunState",
]

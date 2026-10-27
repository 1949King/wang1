# -*- coding: utf-8 -*-
"""族适配器（规范 §3 适配层 / §5）。

**族语义只能出现在这里**：条件怎么拼、时间轴怎么截、潜变量怎么缩放、怎么解码。
内核（`loop.py`）不认识任何族；适配器不许写 for-step（H2 硬线）。
"""
from app.core.neural.kernel.adapters.base import (
    BaseAdapter,
    ComponentBag,
    PreparedStep,
    UnverifiedAdapter,
)
from app.core.neural.kernel.adapters.sd15 import SD15Adapter
from app.core.neural.kernel.adapters.sdxl import SDXLAdapter
from app.core.neural.kernel.adapters.svd import SVDAdapter

__all__ = [
    "BaseAdapter",
    "ComponentBag",
    "PreparedStep",
    "UnverifiedAdapter",
    "SD15Adapter",
    "SDXLAdapter",
    "SVDAdapter",
]

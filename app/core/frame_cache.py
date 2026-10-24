# -*- coding: utf-8 -*-
"""预览帧缓存 —— dict 兼容的**有界真 LRU**（刀 A3.5，2026-10-05）。

为什么要有这个模块
==================
`PreviewManager` 里原本有两个缓存，各有一个**方向性错误**（都不是"慢一点"，是"用错策略"）：

| 缓存 | 原实现 | 错在哪 |
|---|---|---|
| `raw_frame_cache` | `dict` + `min(keys())` 淘汰**最小帧号** | ① **往回拖动时恰好丢掉用户正要去的帧**（越往小拖，越先丢掉小的）——原注释写「min() 淘汰顺序才正确」，实际相反；② 每次插入多一次 O(n) 扫描 |
| `preview_cache` | `OrderedDict` + `popitem(last=False)`，**命中不提权** | 实为 **FIFO 而非 LRU**：来回拖动（scrub back/forth）会反复淘汰「刚用过、马上又要用」的帧 |

本类的语义
==========
- **访问即提权**：`get()` 命中也把条目移到队尾 ⇒ 真 LRU（O(1)）
- **淘汰最久未用**：`popitem(last=False)` 与 `OrderedDict` 同名同义（冻结代码里就是这么调的）
- **dict 兼容**：`.get / [] / []= / del / in / len() / keys() / items() / values() / pop() / clear()`
  ⇒ 可以直接替换 `PreviewManager` 的缓存对象，**调用方（含冻结的 `get_frame_at`）一行不用改**
- **自带 RLock**：读路径原本在 `self._lock` 内、写路径也加锁；类内再加一层防御，
  即使有人绕过外层锁也不会看到半更新的 OrderedDict
- `stats()`：命中/缺失/淘汰计数，供基准与将来的调试面板

⚠️ 与冻结区的关系：本次**没有改动** `preview_manager.get_frame_at`（playback-av 冻结符号）
的任何字符 —— 冻结的只是那段「怎么用缓存」的文本，而「缓存本身怎么实现」在协作对象里。
本类是可独立回退的（把两个属性换回 `OrderedDict()` / `{}` 即回到原行为）。
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any, Callable, Dict, Iterator, Optional


class FrameCache:
    """有界真 LRU 缓存（dict 兼容、线程安全）。

    ``maxsize`` 可在运行时下调（立即收缩），上调后按需自然增长。
    """

    __slots__ = ("_data", "_maxsize", "_lock", "_hits", "_misses", "_evictions", "_on_evict")

    def __init__(self, maxsize: int, *, on_evict: Optional[Callable[[Any, Any], None]] = None):
        self._data: "OrderedDict[Any, Any]" = OrderedDict()
        self._maxsize = int(maxsize)
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._on_evict = on_evict

    # ── 容量 ──────────────────────────────────────────────
    @property
    def maxsize(self) -> int:
        return self._maxsize

    @maxsize.setter
    def maxsize(self, value: int) -> None:
        with self._lock:
            self._maxsize = max(0, int(value))
            self._trim()

    def _trim(self) -> None:
        """超出上限时从**最久未用**端淘汰（O(1) 每次）。调用方需已持锁。"""
        while len(self._data) > self._maxsize:
            key, value = self._data.popitem(last=False)
            self._evictions += 1
            if self._on_evict is not None:
                try:
                    self._on_evict(key, value)
                except Exception:  # stability-gate: allow-swallow（淘汰回调属 best-effort；回调异常绝不拖垮预览）
                    pass

    # ── 读 ────────────────────────────────────────────────
    def get(self, key: Any, default: Any = None) -> Any:
        """命中即提权（真 LRU 的关键；缺了这一步就退化成 FIFO）。"""
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key, last=True)
                self._hits += 1
                return self._data[key]
            self._misses += 1
            return default

    def __getitem__(self, key: Any) -> Any:
        with self._lock:
            if key not in self._data:
                raise KeyError(key)
            self._data.move_to_end(key, last=True)
            self._hits += 1
            return self._data[key]

    def __contains__(self, key: Any) -> bool:
        with self._lock:
            return key in self._data

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)

    def keys(self):
        with self._lock:
            return list(self._data.keys())

    def values(self):
        with self._lock:
            return list(self._data.values())

    def items(self):
        with self._lock:
            return list(self._data.items())

    def __iter__(self) -> Iterator[Any]:
        return iter(self.keys())

    # ── 写 ────────────────────────────────────────────────
    def __setitem__(self, key: Any, value: Any) -> None:
        with self._lock:
            self._data[key] = value
            self._data.move_to_end(key, last=True)   # 覆盖写也视为"最近使用"
            self._trim()

    def setdefault(self, key: Any, default: Any = None) -> Any:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key, last=True)
                return self._data[key]
            self._data[key] = default
            self._trim()
            return default

    def pop(self, key: Any, default: Any = None) -> Any:
        with self._lock:
            if key in self._data:
                return self._data.pop(key)
            return default

    def popitem(self, last: bool = False) -> tuple:
        """与 `OrderedDict.popitem` 同义：``last=False`` 取**最久未用**端。"""
        with self._lock:
            if not self._data:
                raise KeyError("popitem(): cache is empty")
            return self._data.popitem(last=last)

    def move_to_end(self, key: Any, last: bool = True) -> None:
        """兼容 `OrderedDict.move_to_end`。"""
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key, last=last)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def __delitem__(self, key: Any) -> None:
        with self._lock:
            del self._data[key]

    # ── 观测 ──────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        with self._lock:
            total = self._hits + self._misses
            return {
                "size": len(self._data),
                "maxsize": self._maxsize,
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
                "hit_rate": (self._hits / total) if total else 0.0,
            }

    def reset_stats(self) -> None:
        with self._lock:
            self._hits = self._misses = self._evictions = 0

    def __repr__(self) -> str:  # pragma: no cover - 仅调试
        return f"FrameCache(size={len(self._data)}/{self._maxsize})"

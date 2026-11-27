# -*- coding: utf-8 -*-
"""步间钩子：取消、进度、逐 step 打点（规范 §11 可观测门）。

## 为什么取消要单独一个 token，而不是传 bool

`progress_callback` 在 PySide6 里会跨线程调用；传一个 `bool` 意味着"取消状态"
存在调用方的闭包里，而闭包对内核是不可见的 —— 内核只能通过回调**重新进入**
Python 层去问，等于每一步多一次跨界调用，且没有任何地方能证明"中断真的生效了"。

`CancelToken` 把状态收成一个带锁的小对象：
  · 内核每步只做一次 `token.is_set()`（纯内存读，零跨界）；
  · 测试可以精确断言"第 3 步取消 ⇒ 返回 cancelled=True 且只跑了 3 步"；
  · 与 `video_gen` 既有的 `cancelled:True` 语义对齐（规范 §5.2 第 7 条）。

## 为什么钩子全是"可空"的空实现

`NullHooks` 让 `loop.py` 无条件调用钩子，不用到处 `if hooks is not None`。
少一层分支 = 少一处"某条路径忘了报进度"的可能。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


class CancelToken:
    """线程安全的取消标记。

    只做一件事：让"要不要停"这个判断在跨线程场景下有一个**唯一真相**。
    """

    __slots__ = ("_event",)

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    def is_set(self) -> bool:
        return self._event.is_set()

    def reset(self) -> None:
        self._event.clear()


@dataclass
class StepEvent:
    """一步的事实快照（钩子参数）。"""
    index: int
    total: int
    timestep: Any
    elapsed_ms: float = 0.0

    @property
    def is_first(self) -> bool:
        return self.index == 0

    @property
    def is_last(self) -> bool:
        return self.index == self.total - 1


class NullHooks:
    """空钩子：所有回调都不做任何事。默认可直接调用，省掉内核里的 None 判断。"""

    cancel_token: Optional[CancelToken] = None

    def cancelled(self) -> bool:
        return False

    def before_step(self, ev: StepEvent) -> None:
        pass

    def after_step(self, ev: StepEvent, latents: Any) -> None:
        pass

    def finished(self, ok: bool, note: str = "") -> None:
        pass


@dataclass
class Hooks(NullHooks):
    """默认钩子实现：支持取消 + 进度回调 + 逐 step 台账。

    `collect_steps=True` 时把每步的 `max|Δ|` 与耗时记下来 —— 这正是验收协议
    第 11 节"逐 step 打点"要用的东西，不必再另写一个探针。
    """
    cancel_token: Optional[CancelToken] = None
    #: 进度回调 (done:int, total:int, note:str) -> None
    progress: Optional[Callable[[int, int, str], None]] = None
    #: 每步耗时/张量快照收集开关（默认关：开了会有额外同步开销）
    collect_steps: bool = False
    events: List[StepEvent] = field(default_factory=list)
    #: 最近一次 after_step 的事实（**与 collect_steps 无关**）。
    #: 为什么要单独存：`finished()` 曾经拿 `len(events)` 当总步数，
    #: 而 collect_steps=False 时 events 恒为空 ⇒ 完成时进度报 1/1，
    #: 界面表现为"进度条走完又跳回 1/1"。这种错不抛异常，只有人眼能发现。
    done: int = 0
    total_steps: int = 0

    def cancelled(self) -> bool:
        return bool(self.cancel_token is not None and self.cancel_token.is_set())

    def before_step(self, ev: StepEvent) -> None:
        ev.elapsed_ms = 0.0
        if self.collect_steps:
            ev._t0 = time.perf_counter()          # type: ignore[attr-defined]

    def after_step(self, ev: StepEvent, latents: Any) -> None:
        # 先记事实（与 collect_steps 无关）：finished() 要用它报正确的总数
        self.done = ev.index + 1
        self.total_steps = ev.total
        if self.collect_steps:
            t0 = getattr(ev, "_t0", None)
            if t0 is not None:
                ev.elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            # 张量统计只在收集模式下做：默认模式下每步都 `.abs().max()` 会拖慢循环
            try:
                import torch

                if hasattr(latents, "abs"):
                    ev._absmax = float(torch.abs(latents).max().item())  # type: ignore[attr-defined]
            except Exception:  # stability-gate: allow-swallow（打点是诊断，取不到统计不该影响生成）
                pass
            self.events.append(ev)
        if self.progress is not None and (ev.is_last or ev.index % max(1, ev.total // 10) == 0):
            try:
                self.progress(ev.index + 1, ev.total, "去噪 %d/%d" % (ev.index + 1, ev.total))
            except Exception:  # stability-gate: allow-swallow（UI 回调异常不能中断生成，与既有 progress_cb 纪律一致）
                pass

    def finished(self, ok: bool, note: str = "") -> None:
        if self.progress is not None:
            total = self.total_steps or max(self.done, 1)
            done = self.done if self.total_steps else total
            try:
                self.progress(done, total, note or ("完成" if ok else "中止"))
            except Exception:  # stability-gate: allow-swallow（同 after_step：UI 回调不参与正确性）
                pass

    # ── 给验收脚本用的便捷读法 ──────────────────────────────────
    def step_table(self) -> List[Dict[str, Any]]:
        return [
            {"index": e.index, "timestep": _scalar(e.timestep),
             "elapsed_ms": e.elapsed_ms,
             "absmax": getattr(e, "_absmax", None)}
            for e in self.events
        ]


def _scalar(t: Any) -> Any:
    """把 0 维张量降成 python 数；其他原样返回（打印/序列化用）。"""
    try:
        return float(t.item())
    except Exception:  # stability-gate: allow-swallow（只影响展示，取不到就原样返回）
        return t

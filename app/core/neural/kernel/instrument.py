# -*- coding: utf-8 -*-
"""分段计时与显存归因（规范 §10 + §11 测量协议）。

## 为什么不用 `time.time()`

`time.time()` 在 Windows 上的分辨率约 15.6ms，而单步去噪在 8GB 卡上可到 ~90ms、
编码 ~30ms —— 用它测会把分段误差放大到 20% 以上，最后得出"编码比循环还慢"这种假结论。
统一用 `time.perf_counter()`（单调、高分辨率），并且在协议里写明"预热一次再计时"。

## 为什么显存要标 `basis`

规范 §10 第 2 条：`measured` / `estimated` / `registered` **三者不许混用**。
混用的后果在项目里已经发生过：int8 那次"显存降 43.4%"是真数字，但没人说得清
省的是权重还是激活，于是无法判断能不能叠加别的优化。

所以这里每次返回都带 `basis`，并且 `measured` 才允许参与"省了 X%"的结论。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

#: 归因口径三态（与 `vram_budget` 一致）
BASIS_MEASURED = "measured"
BASIS_ESTIMATED = "estimated"
BASIS_REGISTERED = "registered"


@dataclass
class Breakdown:
    """一次生成的分段账（→ `result["kernel"]["breakdown"]`）。"""
    encode_ms: float = 0.0
    loop_ms: float = 0.0
    decode_ms: float = 0.0
    #: 权重常驻；None = 没测（**不写 0**，0 会被读成"不占显存"）
    weight_gb: Optional[float] = None
    #: 峰值显存
    peak_gb: Optional[float] = None
    basis: str = BASIS_MEASURED
    #: 逐 step 明细（仅 collect_steps 时非空）
    steps: List[Dict[str, Any]] = field(default_factory=list)

    def total_ms(self) -> float:
        return round(self.encode_ms + self.loop_ms + self.decode_ms, 2)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "encode_ms": round(self.encode_ms, 2),
            "loop_ms": round(self.loop_ms, 2),
            "decode_ms": round(self.decode_ms, 2),
            "total_ms": self.total_ms(),
            "weight_gb": self.weight_gb,
            "peak_gb": self.peak_gb,
            "basis": self.basis,
            "steps": list(self.steps),
        }


class Instrument:
    """分段秒表 + 显存快照。

    用法::

        ins = Instrument()
        ins.start()
        ...            # encode
        ins.lap("encode")
        ...            # loop
        ins.lap("loop")
        ...            # decode
        ins.lap("decode")
        bd = ins.breakdown()
    """

    #: lap 名 → Breakdown 字段
    _MAP = {"encode": "encode_ms", "loop": "loop_ms", "decode": "decode_ms"}

    def __init__(self, *, measure_vram: bool = True) -> None:
        self._t0 = 0.0
        self._last = 0.0
        self._acc: Dict[str, float] = {}
        self._touched: set = set()
        self._measure_vram = measure_vram
        self._vram_start: Optional[int] = None
        self._vram_peak: Optional[int] = None
        self.steps: List[Dict[str, Any]] = []

    def start(self) -> "Instrument":
        self._t0 = self._last = time.perf_counter()
        self._acc = {}
        self._touched = set()
        self.steps = []
        if self._measure_vram:
            self._vram_start = self._read_allocated()
            self._reset_peak()
        return self

    def lap(self, name: str) -> float:
        """结束一个分段，返回该段毫秒。未知名字抛 ValueError（拼错必须当场红）。"""
        if name not in self._MAP:
            raise ValueError("未知分段名 %r，只允许 %s" % (name, tuple(self._MAP)))
        now = time.perf_counter()
        ms = (now - self._last) * 1000.0
        self._acc[name] = self._acc.get(name, 0.0) + ms
        self._touched.add(name)
        self._last = now
        return round(ms, 2)

    def mark_step(self, entry: Dict[str, Any]) -> None:
        self.steps.append(entry)

    def breakdown(self) -> Breakdown:
        bd = Breakdown()
        for name, ms in self._acc.items():
            setattr(bd, self._MAP[name], round(ms, 2))
        if self._measure_vram:
            peak = self._read_peak()
            if peak is not None:
                bd.peak_gb = round(peak / (1024 ** 3), 3)
            cur = self._read_allocated()
            if cur is not None:
                bd.weight_gb = round(cur / (1024 ** 3), 3)
        if not self._touched:
            # 一段都没测到 ⇒ 这不是 measured，不许冒充
            bd.basis = BASIS_ESTIMATED
        bd.steps = list(self.steps)
        return bd

    # ── torch 只在函数内 import（H3）────────────────────────────
    def _read_allocated(self) -> Optional[int]:
        try:
            import torch

            if not torch.cuda.is_available():
                return None
            torch.cuda.synchronize()
            return int(torch.cuda.memory_allocated())
        except Exception:  # stability-gate: allow-swallow（测不到显存不等于生成失败：账本记 None）
            return None

    def _read_peak(self) -> Optional[int]:
        try:
            import torch

            if not torch.cuda.is_available():
                return None
            return int(torch.cuda.max_memory_allocated())
        except Exception:  # stability-gate: allow-swallow（同上：峰值取不到记 None，不编 0）
            return None

    def _reset_peak(self) -> None:
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.reset_peak_memory_stats()
        except Exception:  # stability-gate: allow-swallow（重置失败只会让峰值偏高，不影响正确性）
            pass

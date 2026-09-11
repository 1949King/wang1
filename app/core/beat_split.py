# -*- coding: utf-8 -*-
"""节拍切点建议：每 N 拍一个切开时刻。空列表诚实返回，不造假拍点。"""
from __future__ import annotations

from typing import List, Optional, Sequence


def beat_split_times(
    beats: Optional[Sequence[float]],
    duration: float,
    *,
    every_n: int = 4,
    min_gap: float = 0.35,
) -> List[float]:
    if not beats:
        return []
    n = max(1, int(every_n))
    dur = float(duration or 0)
    times: List[float] = []
    last = 0.0
    for i, raw in enumerate(beats, 1):
        try:
            t = float(raw)
        except (TypeError, ValueError):
            continue
        if i % n != 0:
            continue
        if t <= min_gap or (dur > 0 and t >= dur - min_gap):
            continue
        if times and t - last < min_gap:
            continue
        times.append(t)
        last = t
    return times

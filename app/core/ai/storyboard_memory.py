# -*- coding: utf-8 -*-
"""分镜记忆规划 —— 把「观众记忆衰减模型」换算成「每个镜头该给多少秒」。

为什么需要这一层
----------------
`memory_model` 只做**评估**：告诉你哪类内容 t 小时后还剩多少记忆。
它不告诉你因此该剪多长。本模块补上**剪辑推论**那一层。

推论直接来自模型，不是拍脑袋的系数
----------------------------------
24 小时保留率（λ 见 `memory_model.DEFAULT_LAMBDA`）：

    细节 11.5%   意义 61.9%   情绪 82.5%

⇒ 细节镜头本来就会被忘记，不值得占用时长；
  情绪锚点是「被记住」的真正载体，值得投入。
⇒ 所以：**总时长守恒，按保留率加权重新分配**。

保底与封顶
----------
纯比例分配会把细节镜头压到零点几秒（低于可感知下限），
所以分配后夹紧到 `[min_duration, max_duration]`，
再把因夹紧产生的余量按比例摊回未夹紧的行 —— 保证总时长仍然守恒。

不做什么
--------
**不猜「这一镜是细节还是情绪」** —— 那是创作判断，由人在画布上选。
本模块只负责：给定类型，算出保留率与建议时长。

⚠️ λ0 是未校准的初始值（`memory_model` 前提 2）。
所以本模块输出的是**相对建议**（哪几镜该让位给哪几镜），
不是绝对值；接了真实完播率/复看率后应重算 λ0 再校准。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from .memory_model import detail_retention, emotion_retention, meaning_retention

__all__ = [
    "MEMORY_TYPES",
    "MEMORY_TYPE_LABELS",
    "DEFAULT_T_HOURS",
    "MIN_DURATION",
    "MAX_DURATION",
    "retention",
    "plan",
]

MEMORY_TYPES = ("detail", "meaning", "emotion")
MEMORY_TYPE_LABELS = {"detail": "细节", "meaning": "意义", "emotion": "情绪"}

DEFAULT_T_HOURS = 24.0     # 「看完一天后还记得什么」—— 短剧复看决策的典型窗口
MIN_DURATION = 0.8         # 低于约 0.8s 已不可感知，再短只会变成噪点
MAX_DURATION = 12.0        # 单镜上限，避免一个情绪锚点吃掉整条片子的预算

_EPS = 1e-9


def _norm_type(value: Any) -> str:
    key = str(value or "").strip().lower()
    return key if key in MEMORY_TYPES else "meaning"


def _pos(value: Any, fallback: float) -> float:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return fallback
    if num != num or num <= 0:      # NaN 或负
        return fallback
    return num


def retention(memory_type: Any, t_hours: float = DEFAULT_T_HOURS) -> float:
    """某类内容在 t 小时后的**基线**保留率（0~1）。

    「基线」= 不叠加情绪/巩固/干扰调制（全取 0），
    即用 `memory_model.DEFAULT_LAMBDA` 的原值 —— 这样同一类型在所有分镜里口径一致，
    规划结果才可比。要算具体某一条片子的实际保留，请直接调 `memory_model`。
    """
    t = max(0.0, float(t_hours))
    key = _norm_type(memory_type)
    if key == "detail":
        return detail_retention(t, d0=1.0)
    if key == "emotion":
        return emotion_retention(t, e0=1.0)
    return meaning_retention(t, s0=1.0)


def _allocate(total: float, weights: Sequence[float], lo: float, hi: float) -> List[float]:
    """按权重分配 total，夹紧到 [lo, hi]，并把夹紧产生的余量摊回未夹紧的行。"""
    n = len(weights)
    if n == 0:
        return []
    sw = sum(weights)
    if sw <= _EPS:
        # 权重全零（理论上不会发生，保留率恒 > 0）：退化为均分
        weights = [1.0] * n
        sw = float(n)
    out = [total * w / sw for w in weights]

    for _ in range(8):
        fixed: List[int] = []
        for i, v in enumerate(out):
            if v <= lo + _EPS:
                out[i] = lo
                fixed.append(i)
            elif v >= hi - _EPS:
                out[i] = hi
                fixed.append(i)
        free = [i for i in range(n) if i not in fixed]
        if not free:
            break
        remainder = total - sum(out[i] for i in fixed)
        if remainder <= lo * len(free):
            # 余量已不够给自由行保底：全部压到下限，总时长守恒让位于保底
            for i in free:
                out[i] = lo
            break
        fw = sum(weights[i] for i in free)
        if fw <= _EPS:
            for i in free:
                out[i] = remainder / len(free)
            break
        for i in free:
            out[i] = remainder * weights[i] / fw

    return [min(hi, max(lo, v)) for v in out]


def plan(
    rows: Optional[Sequence[Dict[str, Any]]] = None,
    *,
    t_hours: float = DEFAULT_T_HOURS,
    min_duration: float = MIN_DURATION,
    max_duration: float = MAX_DURATION,
) -> Dict[str, Any]:
    """给一批分镜行算「保留率 + 建议时长」。

    rows: `[{"id": ..., "memoryType": "detail|meaning|emotion", "duration": 秒}]`

    返回：
        {
          "t_hours", "minDuration", "maxDuration",
          "rows": [{id, memoryType, label, retention, currentDuration,
                    suggestedDuration, delta}],
          "totalCurrent", "totalSuggested",
          "warnings": [str],
        }
    """
    lo = max(0.1, float(min_duration))
    hi = max(lo, float(max_duration))
    t = max(0.0, float(t_hours))

    src = [r for r in (rows or []) if isinstance(r, dict)]
    ids = [str(r.get("id") or f"row_{i}") for i, r in enumerate(src)]
    types = [_norm_type(r.get("memoryType")) for r in src]
    durs = [_pos(r.get("duration"), 3.0) for r in src]

    warnings: List[str] = []
    for i, r in enumerate(src):
        given = str(r.get("memoryType") or "").strip().lower()
        if given and given not in MEMORY_TYPES:
            warnings.append(f"第 {i + 1} 行记忆类型「{given}」无法识别，已按「意义」处理")

    rets = [retention(ty, t) for ty in types]
    total = sum(durs)
    alloc = _allocate(total, rets, lo, hi) if src else []

    out_rows = []
    for i in range(len(src)):
        cur = round(durs[i], 2)
        sug = round(alloc[i], 1) if i < len(alloc) else cur
        out_rows.append({
            "id": ids[i],
            "memoryType": types[i],
            "label": MEMORY_TYPE_LABELS[types[i]],
            "retention": round(rets[i], 4),
            "currentDuration": cur,
            "suggestedDuration": sug,
            "delta": round(sug - cur, 2),
        })

    # ── 干扰提示：相邻同类锚点会互相覆盖（模型的 I 项）──
    for i in range(1, len(types)):
        if types[i] == "emotion" and types[i - 1] == "emotion":
            warnings.append(
                f"第 {i}、{i + 1} 行是相邻情绪锚点：相似记忆会互相干扰，"
                f"建议中间插入一个低记忆密度的镜头隔开"
            )
    emotion_n = sum(1 for ty in types if ty == "emotion")
    if len(types) >= 4 and emotion_n >= max(2, len(types) // 2):
        warnings.append(
            f"{len(types)} 镜里有 {emotion_n} 个情绪锚点：名场面太多反而记不住，"
            f"建议收敛到 1~2 个"
        )

    return {
        "ok": True,
        "t_hours": t,
        "minDuration": lo,
        "maxDuration": hi,
        "rows": out_rows,
        "totalCurrent": round(total, 2),
        "totalSuggested": round(sum(r["suggestedDuration"] for r in out_rows), 2),
        "warnings": warnings,
    }

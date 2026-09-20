# -*- coding: utf-8 -*-
"""记忆衰减模型 —— 给剪辑一个「这一段三天后还剩多少记忆」的量化依据。

定位
----
设计思路借鉴公开的「记忆六变量 + 遗忘数学模型」（艾宾浩斯遗忘曲线 + 巩固理论 +
干扰理论）。本模块是独立实现，供短剧剪辑做记忆强度评估用。

三条使用前提，改参数前务必先读
------------------------------
1. **参数必须夹紧。**  λ = λ0·(1-αE)·(1-βC)·(1+γI)。当 αE ≥ 1 时 λ ≤ 0，
   记忆会「永不遗忘」甚至反向增长 —— 没有物理意义。本模块用 `_MIN_RATE` 兜住。
   原始资料未做这一步，直接照抄会翻车。

2. **默认 λ0 是未校准的初始值，不是事实。**  它们是让曲线形状合理的占位值，
   不代表真实观众。若后续接入真实运营数据，
   应用真实完播率 / 复看率反推 λ0，而非长期沿用这里的默认值。

3. **本模型描述「观众对片段的记忆」，不是「虚构角色的记忆」。**
   同一个指数衰减形式在「角色人格」语境下参数含义完全不同，勿混用。

三个量的分工（剪辑推论）
----------------------
    D 细节保留   衰减最快  → 细节镜头可以剪短剪碎，本来就会被忘记
    S 意义保留   衰减最慢  → 承载意义的镜头要给足时长
    E 情绪残留   近乎平缓  → 情绪锚点是「被记住」的真正载体，值得投入

参考消融视角：干扰项 I 升高会加速遗忘 —— 一条片子里塞太多记忆点会互相覆盖，
「名场面太多反而记不住」正是这个机制。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Dict, Optional

__all__ = [
    "DEFAULT_LAMBDA",
    "DEFAULT_WEIGHTS",
    "MODULATION",
    "MemoryVector",
    "decay_rate",
    "detail_retention",
    "emotion_retention",
    "explain",
    "meaning_retention",
    "memory_score",
]


# 基准衰减率（每小时）。**未校准**，见模块 docstring 前提 2
DEFAULT_LAMBDA: Dict[str, float] = {
    "detail": 0.090,    # 细节：约 8 小时掉到一半
    "meaning": 0.020,   # 意义：约 35 小时掉到一半
    "emotion": 0.008,   # 情绪：约 87 小时掉到一半
}

# λ 调制系数：λ = λ0 · (1-αE) · (1-βC) · (1+γI)
MODULATION: Dict[str, float] = {
    "alpha": 0.60,   # 情绪残留 E 的抑制强度（情绪越强 → 忘得越慢）
    "beta": 0.50,    # 巩固程度 C 的抑制强度（越巩固 → 忘得越慢）
    "gamma": 0.80,   # 干扰程度 I 的增强强度（干扰越大 → 忘得越快）
}

# 综合分权重（派生指标，非原公式）：衰减越慢的分量越代表「被记住」
DEFAULT_WEIGHTS: Dict[str, float] = {
    "detail": 0.20,
    "meaning": 0.45,
    "emotion": 0.35,
}

# λ 下限：防止 αE / βC 取到极值时衰减停滞或逆转
_MIN_RATE = 1e-4


def _unit(value) -> float:
    """把任意输入裁剪到 [0, 1]，非数值与 NaN 归零。"""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(num):
        return 0.0
    return min(1.0, max(0.0, num))


@dataclass(frozen=True)
class MemoryVector:
    """一段内容的记忆六变量，取值统一归一到 [0, 1]。

    S  意义强度    significance
    D  细节完整度  detail integrity
    R  可检索性    retrieval accessibility
    E  情绪残留    emotional residue
    C  巩固程度    consolidation
    I  干扰程度    interference
    """

    S: float = 0.0
    D: float = 1.0
    R: float = 0.5
    E: float = 0.0
    C: float = 0.0
    I: float = 0.0

    def clamped(self) -> "MemoryVector":
        """裁剪到合法范围，避免外部传入越界值把 λ 算穿。"""
        return replace(
            self,
            S=_unit(self.S),
            D=_unit(self.D),
            R=_unit(self.R),
            E=_unit(self.E),
            C=_unit(self.C),
            I=_unit(self.I),
        )

    def as_dict(self) -> Dict[str, float]:
        return {"S": self.S, "D": self.D, "R": self.R, "E": self.E, "C": self.C, "I": self.I}


def decay_rate(
    base: float,
    vector: Optional[MemoryVector] = None,
    *,
    alpha: Optional[float] = None,
    beta: Optional[float] = None,
    gamma: Optional[float] = None,
) -> float:
    """λ = λ0 · (1-αE) · (1-βC) · (1+γI)，并对结果夹紧（前提 1）。

    情绪越强、巩固越深 → λ 越小 → 忘得越慢；
    干扰越大 → λ 越大 → 忘得越快。
    """
    vec = (vector or MemoryVector()).clamped()
    a = MODULATION["alpha"] if alpha is None else float(alpha)
    b = MODULATION["beta"] if beta is None else float(beta)
    g = MODULATION["gamma"] if gamma is None else float(gamma)
    rate = float(base) * (1.0 - a * vec.E) * (1.0 - b * vec.C) * (1.0 + g * vec.I)
    return max(rate, _MIN_RATE)


def _decay(initial: float, rate: float, t_hours: float) -> float:
    """指数衰减主体：R(t) = R0 · e^(-λt)。"""
    if t_hours <= 0:
        return _unit(initial)
    return _unit(initial) * math.exp(-rate * t_hours)


def detail_retention(
    t_hours: float,
    vector: Optional[MemoryVector] = None,
    *,
    d0: float = 1.0,
    alpha: Optional[float] = None,
    beta: Optional[float] = None,
    gamma: Optional[float] = None,
) -> float:
    """D(t) = D0 · e^(-λ_D t)，λ_D 受 E / C / I 调制（原公式中唯一被调制的量）。"""
    vec = (vector or MemoryVector()).clamped()
    rate = decay_rate(
        DEFAULT_LAMBDA["detail"], vec, alpha=alpha, beta=beta, gamma=gamma
    )
    return _decay(d0, rate, t_hours)


def meaning_retention(t_hours: float, *, s0: float = 1.0) -> float:
    """S(t) = S0 · e^(-λ_S t)，且 λ_S < λ_D —— 意义比细节留得久。

    按原始公式，此分量**不**受 E / C / I 调制。
    """
    return _decay(s0, DEFAULT_LAMBDA["meaning"], t_hours)


def emotion_retention(t_hours: float, *, e0: float = 1.0) -> float:
    """E(t) = E0 · e^(-λ_E t)，λ_E 最小 —— 有些情绪留很久。

    按原始公式，此分量**不**受调制。
    """
    return _decay(e0, DEFAULT_LAMBDA["emotion"], t_hours)


def memory_score(
    vector: Optional[MemoryVector] = None,
    *,
    t_hours: float = 72.0,
    weights: Optional[Dict[str, float]] = None,
) -> float:
    """综合记忆强度，0~1。派生指标，非原始公式。

    默认在观看后 72 小时评估：此时细节已几乎归零，分数基本由意义与情绪决定 ——
    对应「三天后还记得什么」这个实际问题。

    可检索性 R 作为乘子（0.5 + 0.5R）：记不住内容 vs 想不起来，是两个不同的失败。
    """
    vec = (vector or MemoryVector()).clamped()
    weight = dict(DEFAULT_WEIGHTS)
    if weights:
        weight.update(weights)
    total = sum(weight.get(k, 0.0) for k in DEFAULT_WEIGHTS) or 1.0

    blended = (
        weight["detail"] * detail_retention(t_hours, vec, d0=vec.D)
        + weight["meaning"] * meaning_retention(t_hours, s0=vec.S)
        + weight["emotion"] * emotion_retention(t_hours, e0=vec.E)
    ) / total
    return _unit(blended * (0.5 + 0.5 * vec.R))


def explain(
    vector: Optional[MemoryVector] = None,
    *,
    t_hours: float = 72.0,
    weights: Optional[Dict[str, float]] = None,
) -> Dict[str, float]:
    """拆解各分量贡献，供报告 / UI 展示（分项之和 = 加权和，已归一）。"""
    vec = (vector or MemoryVector()).clamped()
    weight = dict(DEFAULT_WEIGHTS)
    if weights:
        weight.update(weights)
    total = sum(weight.get(k, 0.0) for k in DEFAULT_WEIGHTS) or 1.0

    detail = detail_retention(t_hours, vec, d0=vec.D)
    meaning = meaning_retention(t_hours, s0=vec.S)
    emotion = emotion_retention(t_hours, e0=vec.E)
    return {
        "t_hours": float(t_hours),
        "detail_retention": detail,
        "meaning_retention": meaning,
        "emotion_retention": emotion,
        "detail_contribution": weight["detail"] * detail / total,
        "meaning_contribution": weight["meaning"] * meaning / total,
        "emotion_contribution": weight["emotion"] * emotion / total,
        "retrieval_multiplier": 0.5 + 0.5 * vec.R,
        "score": memory_score(vec, t_hours=t_hours, weights=weights),
    }

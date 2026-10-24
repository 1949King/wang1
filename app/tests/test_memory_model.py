# -*- coding: utf-8 -*-
"""记忆衰减模型（app/core/ai/memory_model.py）—— 纯数学层单测。

重点覆盖两件事：
  1. 「照搬公式会翻车」的边界（λ 变负 / 越界输入）
  2. 剪辑推论依赖的单调性（情绪越强忘得越慢、干扰越大忘得越快、意义比细节久）
"""

import pytest

from app.core.ai.memory_model import (
    DEFAULT_LAMBDA,
    MemoryVector,
    decay_rate,
    detail_retention,
    emotion_retention,
    explain,
    meaning_retention,
    memory_score,
)


def test_lambda_never_goes_non_positive():
    """前提 1：αE / βC 取极值时 λ 仍须为正，否则记忆会「永不遗忘」。"""
    worst = MemoryVector(E=1.0, C=1.0, I=0.0)
    assert decay_rate(DEFAULT_LAMBDA["detail"], worst) > 0
    # 调制系数放大到 1.0 也不能穿透下限
    assert decay_rate(0.09, worst, alpha=1.0, beta=1.0, gamma=0.0) > 0


def test_base_lambdas_keep_meaning_slower_than_detail():
    assert DEFAULT_LAMBDA["meaning"] < DEFAULT_LAMBDA["detail"]
    assert DEFAULT_LAMBDA["emotion"] < DEFAULT_LAMBDA["meaning"]


def test_emotion_slows_detail_decay():
    """情绪越强 → 忘得越慢（原公式核心断言）。"""
    t = 24.0
    assert detail_retention(t, MemoryVector(E=1.0)) > detail_retention(t, MemoryVector(E=0.0))


def test_consolidation_slows_interference_speeds_up():
    t = 24.0
    base = detail_retention(t, MemoryVector(C=0.0, I=0.0))
    consolidated = detail_retention(t, MemoryVector(C=1.0, I=0.0))
    interfered = detail_retention(t, MemoryVector(C=0.0, I=1.0))
    assert consolidated > base > interfered


def test_meaning_outlives_detail():
    """λ_S < λ_D：同初值下意义的保留率始终高于细节。"""
    for t in (1.0, 6.0, 24.0, 72.0, 168.0):
        assert meaning_retention(t) > detail_retention(t, MemoryVector())


def test_emotion_residue_is_slowest():
    for t in (24.0, 72.0, 168.0):
        assert emotion_retention(t) > meaning_retention(t)


def test_curves_are_monotonic_and_bounded():
    previous = 2.0
    for step in range(0, 200, 4):
        value = detail_retention(float(step), MemoryVector(E=0.5, C=0.5))
        assert 0.0 <= value <= 1.0
        assert value < previous
        previous = value


def test_t_zero_returns_initial():
    vec = MemoryVector(D=0.8, S=0.6, E=0.4)
    assert detail_retention(0.0, vec, d0=vec.D) == pytest.approx(0.8)
    assert meaning_retention(0.0, s0=vec.S) == pytest.approx(0.6)
    assert emotion_retention(0.0, e0=vec.E) == pytest.approx(0.4)


def test_out_of_range_input_is_clamped():
    wild = MemoryVector(S=9.0, D=-3.0, R=5.0, E=2.0, C=-1.0, I=7.0).clamped()
    assert wild.as_dict() == {
        "S": 1.0, "D": 0.0, "R": 1.0, "E": 1.0, "C": 0.0, "I": 1.0,
    }
    # NaN / 越界不该抛异常，且分数仍在合法区间
    assert 0.0 <= memory_score(MemoryVector(S=99, D=99, E=-5, C=float("nan"))) <= 1.0


def test_score_bounds_and_ordering():
    strong = memory_score(MemoryVector(S=1.0, D=1.0, R=1.0, E=1.0, C=1.0, I=0.0))
    weak = memory_score(MemoryVector(S=0.05, D=0.05, R=0.05, E=0.0, C=0.0, I=0.9))
    assert 0.0 <= weak < strong <= 1.0


def test_score_without_vector_is_defined():
    assert 0.0 <= memory_score() <= 1.0
    assert 0.0 <= memory_score(MemoryVector()) <= 1.0


def test_interference_reduces_score():
    """干扰 I 是负资产 —— 「名场面太多反而没记住」的量化表达。"""
    clean = memory_score(MemoryVector(S=0.8, E=0.8, C=0.5, I=0.0))
    noisy = memory_score(MemoryVector(S=0.8, E=0.8, C=0.5, I=1.0))
    assert noisy < clean


def test_explain_is_consistent_with_score():
    vec = MemoryVector(S=0.7, D=0.5, R=0.6, E=0.8, C=0.3, I=0.4)
    parts = explain(vec, t_hours=48.0)
    assert parts["score"] == pytest.approx(memory_score(vec, t_hours=48.0))
    weighted = (
        parts["detail_contribution"]
        + parts["meaning_contribution"]
        + parts["emotion_contribution"]
    )
    assert weighted * parts["retrieval_multiplier"] == pytest.approx(parts["score"])

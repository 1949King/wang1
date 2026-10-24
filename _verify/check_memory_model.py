# -*- coding: utf-8 -*-
"""记忆衰减模型自包含验证。

为什么不直接用 app/tests/test_memory_model.py？
    沙箱环境里 pytest 启动链会调用 wmic.exe 做平台探测，被安全策略拦截。
    本脚本用标准库 assert 覆盖**同一组断言**，可在受限环境快速自检。
    两者应保持同步；完整测试套件仍以 app/tests/test_memory_model.py 为准。

用法（项目根执行）：
    .venv312\\Scripts\\python.exe _verify/check_memory_model.py
"""

from __future__ import annotations

import importlib.util
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 按文件路径加载，绕开 app/__init__.py 的副作用（其 import 链同样会触发硬件探测）
_spec = importlib.util.spec_from_file_location(
    "memory_model", os.path.join(ROOT, "app", "core", "ai", "memory_model.py")
)
_mm = importlib.util.module_from_spec(_spec)
# dataclass 处理类型注解时会回查 sys.modules[cls.__module__]，必须先注册
sys.modules["memory_model"] = _mm
_spec.loader.exec_module(_mm)

DEFAULT_LAMBDA = _mm.DEFAULT_LAMBDA
MemoryVector = _mm.MemoryVector
decay_rate = _mm.decay_rate
detail_retention = _mm.detail_retention
emotion_retention = _mm.emotion_retention
explain = _mm.explain
meaning_retention = _mm.meaning_retention
memory_score = _mm.memory_score

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


def close(a: float, b: float, tol: float = 1e-9) -> bool:
    return math.isclose(a, b, rel_tol=0.0, abs_tol=tol)


# ---- 前提 1：λ 不得 ≤ 0 ----
worst = MemoryVector(E=1.0, C=1.0, I=0.0)
check(decay_rate(DEFAULT_LAMBDA["detail"], worst) > 0, "极值下 λ_D 应仍为正")
check(
    decay_rate(0.09, worst, alpha=1.0, beta=1.0, gamma=0.0) > 0,
    "调制系数拉满时 λ 仍须被夹紧为正",
)

# ---- 基准率次序：λ_D > λ_S > λ_E ----
check(DEFAULT_LAMBDA["meaning"] < DEFAULT_LAMBDA["detail"], "λ_S 应小于 λ_D")
check(DEFAULT_LAMBDA["emotion"] < DEFAULT_LAMBDA["meaning"], "λ_E 应小于 λ_S")

# ---- 情绪减慢细节衰减 ----
check(
    detail_retention(24.0, MemoryVector(E=1.0)) > detail_retention(24.0, MemoryVector(E=0.0)),
    "情绪残留越高，细节保留应越高",
)

# ---- 巩固减慢 / 干扰加速 ----
base = detail_retention(24.0, MemoryVector(C=0.0, I=0.0))
check(detail_retention(24.0, MemoryVector(C=1.0)) > base, "巩固程度应减慢衰减")
check(detail_retention(24.0, MemoryVector(I=1.0)) < base, "干扰程度应加速衰减")

# ---- 意义比细节久，情绪比意义更久 ----
for t in (1.0, 6.0, 24.0, 72.0, 168.0):
    check(meaning_retention(t) > detail_retention(t, MemoryVector()), f"t={t}h 意义应比细节久")
for t in (24.0, 72.0, 168.0):
    check(emotion_retention(t) > meaning_retention(t), f"t={t}h 情绪残留应最久")

# ---- 单调 + 有界 ----
previous = 2.0
for step in range(0, 200, 4):
    value = detail_retention(float(step), MemoryVector(E=0.5, C=0.5))
    check(0.0 <= value <= 1.0, f"t={step}h 保留率越界: {value}")
    check(value < previous, f"t={step}h 曲线非单调")
    previous = value

# ---- t=0 返回初值 ----
vec = MemoryVector(D=0.8, S=0.6, E=0.4)
check(close(detail_retention(0.0, vec, d0=vec.D), 0.8), "t=0 细节应等于 D0")
check(close(meaning_retention(0.0, s0=vec.S), 0.6), "t=0 意义应等于 S0")
check(close(emotion_retention(0.0, e0=vec.E), 0.4), "t=0 情绪应等于 E0")

# ---- 越界 / NaN 输入被夹紧 ----
wild = MemoryVector(S=9.0, D=-3.0, R=5.0, E=2.0, C=-1.0, I=7.0).clamped()
check(
    wild.as_dict() == {"S": 1.0, "D": 0.0, "R": 1.0, "E": 1.0, "C": 0.0, "I": 1.0},
    f"越界输入未被正确夹紧: {wild.as_dict()}",
)
check(0.0 <= memory_score(MemoryVector(S=99, D=99, E=-5, C=float("nan"))) <= 1.0, "NaN 输入应不抛异常且分数合法")

# ---- 分数边界与序 ----
strong = memory_score(MemoryVector(S=1.0, D=1.0, R=1.0, E=1.0, C=1.0, I=0.0))
weak = memory_score(MemoryVector(S=0.05, D=0.05, R=0.05, E=0.0, C=0.0, I=0.9))
check(0.0 <= weak < strong <= 1.0, f"分数序不对: weak={weak}, strong={strong}")
check(0.0 <= memory_score() <= 1.0, "空向量也应给出合法分数")

# ---- 干扰是负资产 ----
clean = memory_score(MemoryVector(S=0.8, E=0.8, C=0.5, I=0.0))
noisy = memory_score(MemoryVector(S=0.8, E=0.8, C=0.5, I=1.0))
check(noisy < clean, "干扰升高应降低记忆分")

# ---- explain 与 score 一致 ----
probe = MemoryVector(S=0.7, D=0.5, R=0.6, E=0.8, C=0.3, I=0.4)
parts = explain(probe, t_hours=48.0)
check(close(parts["score"], memory_score(probe, t_hours=48.0)), "explain.score 与 memory_score 不一致")
weighted = (
    parts["detail_contribution"]
    + parts["meaning_contribution"]
    + parts["emotion_contribution"]
)
check(
    close(weighted * parts["retrieval_multiplier"], parts["score"]),
    "三项贡献 × 可检索乘子 应等于总分",
)

if failures:
    print("FAIL 记忆衰减模型有 %d 项不符预期：" % len(failures))
    for item in failures:
        print("  -", item)
    raise SystemExit(1)

print("OK 记忆衰减模型全部断言通过")
print("  72h 综合记忆分（强）=", round(strong, 4), " （弱）=", round(weak, 4))
print("  24h 细节=", round(detail_retention(24.0, MemoryVector()), 4),
      " 意义=", round(meaning_retention(24.0), 4),
      " 情绪=", round(emotion_retention(24.0), 4))

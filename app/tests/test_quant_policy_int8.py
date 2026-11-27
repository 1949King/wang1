# -*- coding: utf-8 -*-
"""int8 权重只量化策略（T4 生成加速，2026-11-20）。

锁定的纪律（与 fp8 同口径）：
  · 默认 fp16 不变；int8 需 torchao + CUDA（weight-only 不限 GPU 代际）+ ≥4GB 显存；
  · 不满足 ⇒ 回落 fp16 并带原因；严格模式 ⇒ ok=False，绝不静默降级；
  · probe_usable 必须透出 usable_int8（从画像 libs.torchao 与 vram_gb 自算）；
  · 执行端 apply_int8_quantization 走 torchao Int8WeightOnlyConfig，
    组件取 unet（SD 系）或 transformer（Wan 系 DiT），失败不抛。
"""
from __future__ import annotations

import inspect
import sys
import types

from app.core.neural import quant_policy as QP


# ─────────────────────── 归一化 ───────────────────────

def test_normalize_int8_aliases() -> None:
    assert QP.normalize_requested("int8") == "int8"
    assert QP.normalize_requested("W8A16") == "int8"
    assert QP.normalize_requested("int8_weight_only") == "int8"
    # 既有别名不回归
    assert QP.normalize_requested("fp8") == "fp8"
    assert QP.normalize_requested("half") == "fp16"
    assert QP.normalize_requested("nonsense") == ""


# ─────────────────────── 决策 ───────────────────────

def test_int8_usable_returns_int8() -> None:
    r = QP.resolve_precision(requested="int8", usable_int8=True, vram_gb=8.0)
    assert r["ok"] and r["precision"] == "int8" and r["fallback"] == ""


def test_int8_unavailable_falls_back_with_torchao_reason() -> None:
    r = QP.resolve_precision(requested="int8", usable_int8=False, vram_gb=8.0)
    assert r["ok"] and r["precision"] == "fp16" and "torchao" in r["fallback"]


def test_int8_low_vram_threshold() -> None:
    r = QP.resolve_precision(requested="int8", usable_int8=True, vram_gb=3.0)
    assert r["precision"] == "fp16" and "门槛" in r["fallback"]
    # 恰好到门槛 ⇒ 可用（weight-only 量化省的是权重显存，4GB 卡也值得跑）
    ok = QP.resolve_precision(requested="int8", usable_int8=True,
                              vram_gb=QP.INT8_MIN_VRAM_GB)
    assert ok["precision"] == "int8"


def test_int8_strict_fails_instead_of_silent_downgrade() -> None:
    r = QP.resolve_precision(requested="int8", usable_int8=False, vram_gb=8.0, strict=True)
    assert r["ok"] is False and r["precision"] == "fp16" and r["fallback"]


def test_fp8_fp16_default_regression() -> None:
    """int8 引入不得改动 fp8/fp16/默认的既有判定。"""
    assert QP.resolve_precision()["precision"] == "fp16"
    assert QP.resolve_precision(requested="fp16")["precision"] == "fp16"
    r = QP.resolve_precision(requested="fp8", usable_fp8=True, arch="ada", vram_gb=8.0)
    assert r["precision"] == "fp8"
    # int8 可用**不**意味着 fp8 可用（fp8 仍需 Ada+ 能力位）
    r2 = QP.resolve_precision(requested="fp8", usable_fp8=False, usable_int8=True,
                              vram_gb=8.0)
    assert r2["precision"] == "fp16"


# ─────────────────────── 探测 ───────────────────────

def test_probe_usable_exposes_usable_int8(monkeypatch) -> None:
    from app.core.neural import device_profile

    monkeypatch.setattr(device_profile, "probe", lambda: {
        "arch": "sm89", "vram_gb": 8.0,
        "usable": {"fp8": True}, "libs": {"torchao": True}})
    p = QP.probe_usable()
    assert p["usable_int8"] is True and p["usable_fp8"] is True
    # 无 torchao ⇒ int8 不可用
    monkeypatch.setattr(device_profile, "probe", lambda: {
        "arch": "sm89", "vram_gb": 8.0, "usable": {"fp8": False}, "libs": {}})
    assert QP.probe_usable()["usable_int8"] is False
    # 无 CUDA（vram=0）⇒ int8 不可用（weight-only 推理也要 CUDA）
    monkeypatch.setattr(device_profile, "probe", lambda: {
        "arch": "", "vram_gb": 0.0, "usable": {}, "libs": {"torchao": True}})
    assert QP.probe_usable()["usable_int8"] is False


# ─────────────────────── 执行端 ───────────────────────

def _install_fake_torchao(monkeypatch, quantize_fn) -> types.ModuleType:
    """注入假 torchao.quantization（与 fp8 测试同范式，不依赖 GPU/权重）。"""
    fake_quant = types.ModuleType("torchao.quantization")

    class Int8WeightOnlyConfig:
        """假配置类：只验证调用链真的走到 quantize_。"""

    fake_quant.Int8WeightOnlyConfig = Int8WeightOnlyConfig
    fake_quant.quantize_ = quantize_fn
    fake_ao = types.ModuleType("torchao")
    fake_ao.quantization = fake_quant
    monkeypatch.setitem(sys.modules, "torchao", fake_ao)
    monkeypatch.setitem(sys.modules, "torchao.quantization", fake_quant)
    return fake_quant


def test_apply_int8_quantization_calls_quantize(monkeypatch) -> None:
    from app.core.neural import diffusers_image as DI

    seen = {}

    def _quantize(module, config):
        seen["module"] = module
        seen["config"] = config

    fake_quant = _install_fake_torchao(monkeypatch, _quantize)

    class _PipeUnet:
        unet = object()

    ok, why = DI.apply_int8_quantization(_PipeUnet())
    assert ok and why == ""
    assert isinstance(seen["config"], fake_quant.Int8WeightOnlyConfig)

    # Wan 系 DiT 叫 transformer（无 unet）⇒ 兜底取 transformer
    class _PipeTransformer:
        transformer = object()

    ok2, _ = DI.apply_int8_quantization(_PipeTransformer())
    assert ok2

    # 两者皆无 ⇒ 诚实失败（不抛）
    ok3, why3 = DI.apply_int8_quantization(object())
    assert not ok3 and "unet" in why3

    # quantize_ 抛错 ⇒ 返回回落原因（不抛）
    def _boom(module, config):
        raise RuntimeError("nope")

    fake_quant.quantize_ = _boom
    ok4, why4 = DI.apply_int8_quantization(_PipeUnet())
    assert not ok4 and "int8" in why4


def test_engine_request_precision_int8() -> None:
    from app.core.neural.diffusers_image import DiffusersImageEngine

    e = DiffusersImageEngine()
    assert e.request_precision("INT8") == "int8"
    assert e.precision_status()["requested"] == "int8"


def test_load_wires_int8_branch_and_gguf_exclusion() -> None:
    """源码级接线锁：load() 必须传 usable_int8、走 int8 分支、GGUF 互斥覆盖 int8。"""
    from app.core.neural.diffusers_image import DiffusersImageEngine

    src = inspect.getsource(DiffusersImageEngine.load)
    assert "usable_int8" in src, "load 未把 usable_int8 传给 resolve_precision"
    assert 'self._precision == "int8"' in src, "load 缺 int8 执行分支"
    assert "apply_int8_quantization" in src
    assert 'in ("fp8", "int8")' in src, "GGUF 互斥必须同时覆盖 fp8 与 int8"

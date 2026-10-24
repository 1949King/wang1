# -*- coding: utf-8 -*-
"""精度策略纯函数：默认 fp16 / fp8 四条件 / 严格模式。"""
from __future__ import annotations

from app.core.neural import quant_policy as QP


def test_default_is_fp16() -> None:
    r = QP.resolve_precision()
    assert r["ok"] and r["precision"] == "fp16" and r["fallback"] == ""


def test_request_fp16_is_honored() -> None:
    r = QP.resolve_precision(requested="float16")
    assert r["precision"] == "fp16" and r["requested"] == "fp16"


def test_fp8_requires_capability_and_torchao_and_vram() -> None:
    ok = QP.resolve_precision(requested="fp8", usable_fp8=True, arch="ada", vram_gb=8.0)
    assert ok["precision"] == "fp8" and ok["fallback"] == ""
    # 缺 torchao/能力位
    no_lib = QP.resolve_precision(requested="fp8", usable_fp8=False, arch="ada", vram_gb=8.0)
    assert no_lib["precision"] == "fp16" and "torchao" in no_lib["fallback"]
    # 显存不够
    low = QP.resolve_precision(requested="fp8", usable_fp8=True, arch="ada", vram_gb=4.0)
    assert low["precision"] == "fp16" and "门槛" in low["fallback"]


def test_strict_mode_fails_instead_of_silent_downgrade() -> None:
    r = QP.resolve_precision(requested="fp8", usable_fp8=False, arch="ada",
                             vram_gb=8.0, strict=True)
    assert r["ok"] is False and r["precision"] == "fp16" and r["fallback"]
    # 非严格：回落但带原因
    r2 = QP.resolve_precision(requested="fp8", usable_fp8=False, arch="ada", vram_gb=8.0)
    assert r2["ok"] is True and r2["precision"] == "fp16" and r2["fallback"]


def test_normalize_requested() -> None:
    assert QP.normalize_requested("AUTO") == ""
    assert QP.normalize_requested("fp8") == "fp8"
    assert QP.normalize_requested("half") == "fp16"
    assert QP.normalize_requested("nonsense") == ""


def test_engine_request_precision_normalizes_without_loading() -> None:
    from app.core.neural.diffusers_image import DiffusersImageEngine

    e = DiffusersImageEngine()
    assert e.precision_status()["precision"] == "fp16"
    assert e.request_precision("FP8") == "fp8"
    assert e.request_precision("auto") == ""
    assert e.precision_status()["requested"] == ""

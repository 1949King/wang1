# -*- coding: utf-8 -*-
"""量化描述符与台账的自洽性测试（设计稿 §12.4 标准 4）。

这些测试不碰 GPU、不 import torch —— 纯台账逻辑，秒级。
真机数据由 verify_int8_diffusers.py 产出，本文件只保证「账本自身不撒谎」。
"""
from __future__ import annotations

import pytest

from app.core.neural import quant_descriptor as QD


def test_every_evidence_scheme_is_registered():
    """双向守卫：证据里的 scheme 必须有描述符，否则台账会指向空中楼阁。"""
    for e in QD.EVIDENCE:
        assert QD.descriptor(e.scheme) is not None, f"证据引用了未登记的 scheme: {e.scheme}"


def test_evidence_numbers_are_finite_and_ordered():
    """数字必须合理：压缩后不得比压缩前大，PSNR 落在 (0, 100]。"""
    for e in QD.EVIDENCE:
        assert e.unet_gb_after > 0
        assert e.unet_gb_after <= e.unet_gb_before * 1.001, f"{e.scheme}@{e.model_id} 压缩后更大"
        if e.peak_gb_before is not None and e.peak_gb_after is not None:
            assert e.peak_gb_after <= e.peak_gb_before * 1.001, f"{e.scheme}@{e.model_id} 峰值反而涨了"
        if e.peak_gb_after is not None:
            assert e.peak_gb_after > 0
        if e.psnr_db is not None:
            assert 0 < e.psnr_db <= 100, f"{e.scheme}@{e.model_id} PSNR 越界"


def test_verdict_takes_worst_case():
    """任一模型位被判 rejected ⇒ 整方案 rejected（一个模型崩了就不能上）。"""
    state, why = QD.verdict("int8wo_v2")
    assert state == QD.VERDICT_REJECTED
    assert "全黑" in why or "画质" in why


def test_unverified_scheme_is_not_admissible():
    """登记但零证据 ⇒ 不得进主路径（诚实失败）。"""
    state, _ = QD.verdict("int4wo")
    assert state == QD.VERDICT_UNVERIFIED
    ok, why = QD.is_admissible("int4wo")
    assert not ok and "未验证" in why


def test_fp16_always_admissible():
    for s in ("", "fp16", "float16", "none"):
        ok, _ = QD.is_admissible(s)
        assert ok, f"基线精度 {s!r} 不该被拦"


def test_unknown_scheme_is_rejected_with_reason():
    ok, why = QD.is_admissible("int3wo")
    assert not ok and "未登记" in why


def test_rejected_scheme_blocked_even_with_high_psnr_threshold_lowered():
    """把门槛降到 0 也不放行 rejected 方案——否决权高于门槛权。"""
    ok, why = QD.is_admissible("int8wo_v2", min_psnr_db=0.0)
    assert not ok and "否决" in why


def test_summary_shape():
    s = QD.summary()
    assert "fp16" in s["admissible"]
    assert "int8wo_v2" in s["rejected"]
    assert all("scheme" in r and "verdict" in r for r in s["rows"])


def test_describe_is_human_readable():
    text = QD.describe()
    assert "量化准入" in text
    assert "int8wo_v2" in text


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

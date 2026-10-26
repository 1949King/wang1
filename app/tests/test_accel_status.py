# -*- coding: utf-8 -*-
"""加速能力报告（2026-10-27）：诚实三态 + 负收益记录必须保留。"""
from __future__ import annotations

import app.core.neural.accel_status as AS


def test_status_shape_and_honesty():
    st = AS.status()
    for k in ("fp8", "int4", "compile", "tensorrt"):
        item = st[k]
        assert "ok" in item and "lib" in item and "reason" in item
        if not item["ok"]:
            assert item["reason"], f"{k} 不可用时必须给原因"
    assert st["honesty"]
    assert st["measured"]["cudagraphs"]["measured"] is True
    assert st["measured"]["cudagraphs"]["speedup"] < 1, "负收益必须如实登记"


def test_install_hint_covers_all_with_commands():
    h = AS.install_hint()
    for k in ("fp8", "int4", "compile", "tensorrt"):
        assert k in h and "pip install" in h[k]


def test_status_never_raises_when_probe_fails(monkeypatch):
    import app.core.neural.device_profile as DP

    monkeypatch.setattr(DP, "probe", lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    st = AS.status()          # 不崩，且至少给出 device 键
    assert "device" in st
    assert st["fp8"]["ok"] in (True, False)

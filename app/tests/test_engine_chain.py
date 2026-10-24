# -*- coding: utf-8 -*-
"""引擎链化 + 质量总闸：族选择 / 链展开 / plan 透出。"""
from __future__ import annotations

import app.core.ai.execution_planner as EP


def test_arch_follows_quality() -> None:
    assert EP._arch_of("image", "fine") == "sdxl"
    assert EP._arch_of("image", "cinema") == "sdxl"
    assert EP._arch_of("image", "draft") == "sd15"
    assert EP._arch_of("image", "standard") == "sd15"
    assert EP._arch_of("video", "cinema") == "svd"


def test_engines_for_expands_chain_with_model_and_family() -> None:
    ch = EP._engines_for(["local", "cloud"], engine="diffusers",
                         arch="sdxl", accelerators=["fp8"])
    assert [c["order"] for c in ch] == [1, 2]
    assert ch[0]["kind"] == "local" and ch[0]["family"] == "sdxl"
    assert ch[0]["engine"] == "diffusers" and ch[0]["model"].startswith("sdxl")
    assert ch[0]["accelerators"] == ["fp8"]
    assert ch[1]["kind"] == "cloud" and ch[1]["engine"] == "cloud"
    # 反向顺序同样成立
    ch2 = EP._engines_for(["cloud", "local"], engine="diffsynth", arch="sd15", accelerators=[])
    assert [c["kind"] for c in ch2] == ["cloud", "local"]


def test_plan_exposes_engine_chain_and_quality(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SHIGUANG_QUALITY_GATE", str(tmp_path / "qg.json"))
    import app.core.ai.compute_bias as CB
    import app.core.ai.quality_gate as QG

    monkeypatch.setattr(QG, "_GATE", None)
    monkeypatch.setattr(EP, "_engine_probe", lambda cap, q="": {
        "engine": "diffsynth", "available": True, "is_fallback": False,
        "reason": "", "device": {}, "accelerators": [], "engine_reasons": []})
    monkeypatch.setattr(EP, "_hw_probe", lambda: {"tier": "mid"})
    monkeypatch.setattr(EP, "_budget_lambda", lambda: 0.5)
    monkeypatch.setattr(EP, "_cloud_available", lambda: True)
    monkeypatch.setattr(CB, "get_bias", lambda: type("B", (), {"get": lambda s: 50})())
    monkeypatch.setattr(CB, "bias_mode", lambda b: "engine")

    fine = EP.plan(capability="image", quality="fine")
    assert fine["quality"] == "fine"
    # λ=0.5 ≥ 0.35 ⇒ engine 档本地先跑（本地→云端）
    kinds = [e["kind"] for e in fine["engines"]]
    assert kinds == ["local", "cloud"]
    local = fine["engines"][0]
    assert local["family"] == "sdxl" and local["model"].startswith("sdxl")

    draft = EP.plan(capability="image", quality="draft")
    assert draft["engines"][0]["family"] == "sd15"


def test_plan_reads_quality_gate_when_quality_empty(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SHIGUANG_QUALITY_GATE", str(tmp_path / "qg.json"))
    import app.core.ai.compute_bias as CB
    import app.core.ai.quality_gate as QG

    monkeypatch.setattr(QG, "_GATE", None)
    assert QG.get_gate().set("cinema") is True
    monkeypatch.setattr(EP, "_engine_probe", lambda cap, q="": {
        "engine": "diffsynth", "available": True, "is_fallback": False,
        "reason": "", "device": {}, "accelerators": [], "engine_reasons": []})
    monkeypatch.setattr(EP, "_hw_probe", lambda: {"tier": "mid"})
    monkeypatch.setattr(EP, "_budget_lambda", lambda: 0.5)
    monkeypatch.setattr(EP, "_cloud_available", lambda: True)
    monkeypatch.setattr(CB, "get_bias", lambda: type("B", (), {"get": lambda s: 90})())
    monkeypatch.setattr(CB, "bias_mode", lambda b: "cloud")

    p = EP.plan(capability="image")
    assert p["quality"] == "cinema"
    # bias=90 ⇒ cloud 档：云端先、本地兜底；本地那跳的族按 cinema 走 sdxl
    assert [e["kind"] for e in p["engines"]] == ["cloud", "local"]
    assert p["engines"][1]["family"] == "sdxl"


def test_decide_compute_mode_exposes_engines(monkeypatch) -> None:
    """执行器要能拿到 plan 的 engines（否则链只是展示品）。"""
    import app.core.ai.execution_planner as EP2
    import app.core.ai.hybrid_dispatch as HD

    monkeypatch.setattr(EP2, "plan", lambda **kw: {
        "route": "hybrid", "chain": ["local", "cloud"], "mode": "engine",
        "engines": [{"kind": "local", "engine": "diffusers", "model": "sdxl-t2i",
                     "family": "sdxl"}, {"kind": "cloud"}],
        "reasons": [], "model_hint": "sdxl-t2i"})
    dec = HD.decide_compute_mode(channel_id="", capability="image", has_reference=False)
    assert dec["engines"][0]["engine"] == "diffusers"
    assert dec["engines"][0]["model"] == "sdxl-t2i"

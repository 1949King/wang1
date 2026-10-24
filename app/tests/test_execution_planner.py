# -*- coding: utf-8 -*-
"""执行层专项决策器 + 混合算力偏好（V4.46.5 · 2026-10-23）。

锁死四件事：
1. `compute_bias.bias_mode` 的三档边界（≤24 local / 25-74 engine / ≥75 cloud）与持久化往返；
2. `execution_planner.plan()` 的链条裁定：偏好档、显式手选不改道、
   **本地视频是 i2v ⇒ 无参考图时不得声称可本地**（诚实边界）；
3. `hybrid_dispatch` 严格按计划 chain 顺序执行（先本地失败再云端 / 先云端失败再本地）；
4. 目录一致性：`execution.plan` / `execution.status` 注册与目录行双向对齐。

为什么要这些：本项目走过「决策写了但没人消费」的坑（决策空转），
所以测试不仅验决策值，还验**执行器真的按决策走**。
"""
import json

import pytest

import app.core.ai.compute_bias as CB
import app.core.ai.execution_planner as EP
import app.core.ai.hybrid_dispatch as HD


@pytest.fixture()
def bias_store(tmp_path, monkeypatch):
    """把偏好账本钉到 tmp，避免污染 data/compute_bias.json。"""
    p = tmp_path / "compute_bias.json"
    monkeypatch.setenv("COMPUTE_BIAS_STORE_PATH", str(p))
    monkeypatch.setattr(CB, "_instance", None, raising=False)
    yield p
    monkeypatch.setattr(CB, "_instance", None, raising=False)


# ── ① 档位边界与持久化 ────────────────────────────────────────────────
def test_bias_mode_boundaries():
    assert CB.bias_mode(0) == CB.MODE_LOCAL
    assert CB.bias_mode(24) == CB.MODE_LOCAL
    assert CB.bias_mode(25) == CB.MODE_ENGINE
    assert CB.bias_mode(50) == CB.MODE_ENGINE
    assert CB.bias_mode(74) == CB.MODE_ENGINE
    assert CB.bias_mode(75) == CB.MODE_CLOUD
    assert CB.bias_mode(100) == CB.MODE_CLOUD
    # 越界夹到界内；非法值按默认 engine
    assert CB.bias_mode(-5) == CB.MODE_LOCAL
    assert CB.bias_mode(999) == CB.MODE_CLOUD
    assert CB.bias_mode("nonsense") == CB.MODE_ENGINE


def test_bias_persist_roundtrip(bias_store):
    b = CB.get_bias()
    assert b.get() == 50                      # 缺省 engine
    assert b.set(12) is True
    assert json.loads(bias_store.read_text(encoding="utf-8"))["bias"] == 12
    # 新实例读回同一份账本
    CB._instance = None
    assert CB.get_bias().get() == 12
    assert CB.get_bias().mode() == CB.MODE_LOCAL


# ── ② 执行层裁定 ──────────────────────────────────────────────────────
def _stub_env(monkeypatch, *, local=True, cloud=True, tier="mainstream", lam=0.05):
    """把环境探测打桩，专注验裁定逻辑本身。"""
    monkeypatch.setattr(EP, "_engine_probe", lambda *a, **kw: {
        "engine": "diffsynth", "available": local, "is_fallback": False,
        "reason": "stub", "device": {"device_id": "stub"},
        "accelerators": [], "engine_reasons": []}, raising=False)
    monkeypatch.setattr(EP, "_hw_probe", lambda: {
        "tier": tier, "memory_mb": 8192, "gpu_name": "stub", "reason": "stub"},
        raising=False)
    monkeypatch.setattr(EP, "_budget_lambda", lambda: lam, raising=False)
    monkeypatch.setattr(EP, "_cloud_available", lambda: cloud, raising=False)
    monkeypatch.setattr(EP, "_local_model_hint", lambda: "sd15-t2i", raising=False)


def test_plan_local_pref(bias_store, monkeypatch):
    _stub_env(monkeypatch)
    CB.get_bias().set(10)
    r = EP.plan(capability="image")
    assert r["route"] == "local"
    assert r["chain"][0] == "local" and "cloud" in r["chain"]


def test_plan_cloud_pref(bias_store, monkeypatch):
    _stub_env(monkeypatch)
    CB.get_bias().set(90)
    r = EP.plan(capability="image")
    assert r["route"] == "cloud"
    assert r["chain"][0] == "cloud"


def test_plan_engine_pref_is_hybrid(bias_store, monkeypatch):
    _stub_env(monkeypatch, lam=0.05)
    CB.get_bias().set(50)
    r = EP.plan(capability="image")
    assert r["route"] == "hybrid", "engine 档且两路皆可用 ⇒ 真混合"
    assert r["degrade_level"] == 1


def test_plan_video_needs_reference(bias_store, monkeypatch):
    """本机视频模型是 i2v：无参考图/首帧时**不得**声称可本地（诚实边界）。"""
    _stub_env(monkeypatch)
    CB.get_bias().set(10)
    no_ref = EP.plan(capability="video", has_reference=False)
    assert no_ref["route"] != "local"
    assert "local" not in no_ref["chain"]
    with_ref = EP.plan(capability="video", has_reference=True)
    assert with_ref["route"] == "local"
    assert with_ref["chain"][0] == "local"


def test_plan_explicit_channel_wins(bias_store, monkeypatch):
    """用户手选渠道是最高意图：档位偏好不得改道。"""
    _stub_env(monkeypatch)
    CB.get_bias().set(90)   # 偏好云端
    r = EP.plan(capability="image", explicit_channel="local/diffsynth/sd15-t2i")
    assert r["route"] == "local" and r["chain"] == ["local"]
    CB.get_bias().set(10)   # 偏好本地
    r2 = EP.plan(capability="image", explicit_channel="siliconflow")
    assert r2["route"] == "cloud" and r2["chain"] == ["cloud"]


def test_plan_no_cloud_no_local(bias_store, monkeypatch):
    """两路都不可用：仍返回可解释计划（不抛），由调用方如实报错。"""
    _stub_env(monkeypatch, local=False, cloud=False)
    CB.get_bias().set(50)
    r = EP.plan(capability="image")
    assert r["ok"] is True
    assert r["reasons"], "必须给出理由，不能空手而归"


# ── ③ 执行器严格按 chain 执行 ──────────────────────────────────────────
def test_hybrid_follows_chain_local_first(bias_store, monkeypatch):
    order = []
    monkeypatch.setattr(HD, "decide_compute_mode", lambda **kw: {
        "mode": "local", "route": "local", "chain": ["local", "cloud"],
        "use_local": True, "explicit_channel": False, "model_hint": "sd15-t2i",
        "reasons": ["stub"]})
    monkeypatch.setattr(HD, "_local_image", lambda **kw: (
        order.append("local") or {"ok": True, "image_url": "/inbox_file/x.png",
                                  "source": "local"}))
    import app.core.canvas_aigc as CA
    monkeypatch.setattr(CA, "generate_image_openai_compatible", lambda **kw: (
        order.append("cloud") or {"ok": True, "source": "cloud"}))

    r = HD.generate_image_hybrid(prompt="p")
    assert r["ok"] is True and r["source"] == "local"
    assert order == ["local"], "本地成功就不该再打云端"


def test_hybrid_falls_back_to_cloud(bias_store, monkeypatch):
    order = []
    monkeypatch.setattr(HD, "decide_compute_mode", lambda **kw: {
        "mode": "local", "route": "local", "chain": ["local", "cloud"],
        "use_local": True, "explicit_channel": False, "model_hint": "",
        "reasons": ["stub"]})
    monkeypatch.setattr(HD, "_local_image", lambda **kw: (order.append("local") or None))
    import app.core.canvas_aigc as CA
    monkeypatch.setattr(CA, "generate_image_openai_compatible", lambda **kw: (
        order.append("cloud") or {"ok": True, "source": "cloud"}))
    r = HD.generate_image_hybrid(prompt="p")
    assert r["ok"] is True and r["source"] == "cloud"
    assert order == ["local", "cloud"], "必须先试本地、失败再云端"


def test_hybrid_both_fail_reports_chain(bias_store, monkeypatch):
    monkeypatch.setattr(HD, "decide_compute_mode", lambda **kw: {
        "mode": "engine", "route": "hybrid", "chain": ["cloud", "local"],
        "use_local": False, "explicit_channel": False, "model_hint": "",
        "reasons": ["stub"]})
    monkeypatch.setattr(HD, "_local_image", lambda **kw: None)
    import app.core.canvas_aigc as CA
    monkeypatch.setattr(CA, "generate_image_openai_compatible",
                        lambda **kw: {"ok": False, "message": "no channel"})
    r = HD.generate_image_hybrid(prompt="p")
    assert r["ok"] is False
    assert r["tried"] == ["cloud", "local"], "失败时必须交代试过哪些路径"
    # 逐路留痕：云端的真实原因不能被后一路覆盖掉
    assert "no channel" in r["message"] and "云端" in r["message"]
    assert "本地" in r["message"]


# ── ④ 能力注册与目录一致性 ────────────────────────────────────────────
def test_execution_capabilities_registered_and_catalogued():
    from app.core.agent_capability_catalog import verify_catalog_consistency
    from app.core.capability_dispatcher import CapabilityDispatcher
    from app.core.capability_handlers import register_builtin_handlers

    d = CapabilityDispatcher()
    register_builtin_handlers(d)
    ids = {e["capability_id"] for e in d.list_capabilities()}
    assert "execution.plan" in ids
    assert "execution.status" in ids
    problems = verify_catalog_consistency(ids)
    assert problems == [], f"目录/注册不一致: {problems}"

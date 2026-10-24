# -*- coding: utf-8 -*-
"""M4 入口合一 回归（统一引擎，2026-10-24）。

锁死三件事（全部零真权重、零 diffusers lazy 面——0xC0000005 教训）：
1. ④ 端点的注册表路由 helper：model_id→族名复用 ③ 的关键词表（不另造第二套映射）；
2. ③ generate_video_local 的注册表咨询：verification/warnings 随结果透出，
   unverified 族**警示但不拦路**（显式指定 = 最高意图，「未登记 ≠ 不可用」）；
3. execution_planner.status() 的 families 视图（画布由此看到验证态）。
"""

import app.core.neural.model_family as MF


# ── ① 端点 helper ──────────────────────────────────────────────────────
def test_family_of_model_id_reuses_kind_map():
    """族名解析必须复用 ③ 的 _guess_model_kind（单一映射真源）。"""
    from app.core.canvas_routes_local_video import _family_of_model_id

    assert _family_of_model_id("cogvideox-2b") == "cogvideox"
    assert _family_of_model_id("hunyuan-video") == "hunyuan"
    assert _family_of_model_id("svd-xt-i2v") == "svd"
    assert _family_of_model_id("totally-unknown") == ""


def test_delegate_maps_params_and_seed_warning(monkeypatch):
    """委托 ③：参数映射正确；seed 不支持 ⇒ 如实进 warnings（不静默假装）。"""
    import app.core.canvas_routes_local_video as RL
    import app.core.local_video_infer as L

    seen = {}

    def fake_gen(**kw):
        seen.update(kw)
        return {"ok": True, "video_path": "x.mp4"}

    monkeypatch.setattr(L, "generate_video_local", fake_gen)
    res = RL._delegate_local_video_infer(
        {"prompt": "p", "model_id": "cogvideox-2b", "seconds": 3.0, "seed": 42},
        "/tmp/first.png",
        "cogvideox",
    )
    assert res["ok"] is True
    assert seen["model"] == "cogvideox-2b"
    assert seen["duration"] == 3.0
    assert seen["first_frame"] == "/tmp/first.png"
    assert any("seed" in w for w in res.get("warnings") or []), (
        "seed 不被本地通道支持必须说出来，不能静默忽略"
    )


# ── ② ③ 入口的注册表咨询 ───────────────────────────────────────────────
def test_generate_video_local_surfaces_verification(monkeypatch):
    """unverified 族：警示随结果返回，但**不拦路**（本次仍执行）。"""
    import app.core.local_video_infer as L

    monkeypatch.setattr(L, "_torch_available", lambda: True)
    monkeypatch.setattr(L, "_diffusers_available", lambda: True)
    monkeypatch.setattr(L, "_get_device", lambda: ("cuda", 8))
    monkeypatch.setitem(
        L._INFER_FUNC_MAP, "cogvideox", lambda **kw: {"ok": True, "video_path": "v.mp4"}
    )
    r = L.generate_video_local(prompt="p", model="cogvideox-2b", model_path="C:/fake/cogvideox")
    assert r["ok"] is True, "咨询不得拦路（显式指定 = 最高意图）"
    assert r.get("family") == "cogvideox"
    assert r.get("verification") == MF.UNVERIFIED
    assert any("未在本机真机验证" in w for w in r.get("warnings") or [])


def test_generate_video_local_unknown_family_warns_not_blocks(monkeypatch):
    """族未登记 ⇒ 提示补登记，仍执行（「我没登记 ≠ 本机做不到」）。"""
    import app.core.local_video_infer as L

    monkeypatch.setattr(L, "_torch_available", lambda: True)
    monkeypatch.setattr(L, "_diffusers_available", lambda: True)
    monkeypatch.setattr(L, "_get_device", lambda: ("cuda", 8))
    # 借 cogvideox 的执行位，但把 kind 伪造成未登记族
    monkeypatch.setattr(L, "_guess_model_kind", lambda s: "brandnewfam")
    monkeypatch.setitem(
        L._INFER_FUNC_MAP, "brandnewfam", lambda **kw: {"ok": True, "video_path": "v.mp4"}
    )
    r = L.generate_video_local(prompt="p", model="brandnew-1", model_path="C:/fake/new")
    assert r["ok"] is True
    assert any("未登记" in w for w in r.get("warnings") or [])


# ── ③ status 的 families 视图 ─────────────────────────────────────────
def test_planner_status_exposes_families(monkeypatch):
    import app.core.ai.execution_planner as EP

    # 剥掉重探测（本测试只验 families 挂载，engine/hw/cloud 各有自己的测试）
    monkeypatch.setattr(
        EP,
        "_engine_probe",
        lambda *a, **k: {
            "engine": "",
            "available": False,
            "is_fallback": True,
            "reason": "stub",
            "device": {},
            "accelerators": [],
            "engine_reasons": [],
        },
    )
    monkeypatch.setattr(EP, "_hw_probe", lambda: {"tier": "mainstream", "gpu_name": "stub"})
    monkeypatch.setattr(EP, "_cloud_available", lambda: False)
    st = EP.status()
    fam = st.get("families") or {}
    assert fam.get("total") == len(MF.FAMILIES)
    assert any(
        r["family"] == "svd" and r["verification"] == MF.VERIFIED for r in fam.get("families", [])
    )

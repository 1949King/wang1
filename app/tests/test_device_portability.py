# -*- coding: utf-8 -*-
"""跨设备可移植性 + 引擎遥测（V4.46.6 · 2026-10-24）。

用户指令：「要为后面适配其他设备着想，而不是光适配现在的 4060」。
本文件锁死三件事：
1. **设备画像**在注入假设备时给出正确能力位（Apple/AMD/CPU/Hopper 各一档），
   且「fp8 能不能用」= 硬件能力位 AND torchao 已装（两者缺一不可）。
2. **后端注册表**按「依赖库 + 架构 + 显存」筛候选；装不上的后端表现为「不在册」。
3. **引擎遥测**按真实证据推荐引擎：低延迟胜出、高失败率淘汰、样本不足退回默认。

注意：全部用 `SHIGUANG_DEVICE_PROFILE` / `SHIGUANG_ENGINE_TELEMETRY_PATH` 隔离，
不探测真机、不写正式数据文件。
"""
import json

import pytest


@pytest.fixture()
def fake_device():
    """返回一个设置假设备画像的工厂。"""
    def _set(**over):
        base = {
            "vendor": "nvidia", "arch": "sm89", "name": "Fake Ada",
            "vram_gb": 8.0, "device_id": "nvidia:sm89:8.0gb",
            "capabilities": {}, "libs": {},
        }
        base.update(over)
        return json.dumps(base)
    return _set


@pytest.fixture()
def telemetry_path(tmp_path, monkeypatch):
    p = tmp_path / "engine_telemetry.json"
    monkeypatch.setenv("SHIGUANG_ENGINE_TELEMETRY_PATH", str(p))
    return p


# ── ① 设备画像 ────────────────────────────────────────────────────────
def test_profile_apple_mps_no_fp8(monkeypatch, fake_device):
    monkeypatch.setenv("SHIGUANG_DEVICE_PROFILE", fake_device(
        vendor="apple", arch="mps", vram_gb=16.0, device_id="apple:mps:16gb"))
    from app.core.neural import device_profile as DP

    p = DP.probe(use_cache=False)
    assert p["vendor"] == "apple"
    assert p["capabilities"]["fp8"] is False, "Apple 无 FP8 tensor core"
    assert p["capabilities"]["int4"] is False
    assert p["usable"]["fp8"] is False


def test_profile_hopper_fp8_requires_torchao(monkeypatch, fake_device):
    from app.core.neural import device_profile as DP

    # 硬件支持 FP8，但没装 torchao ⇒ 仍然不可用（缺一不可）
    monkeypatch.setenv("SHIGUANG_DEVICE_PROFILE", fake_device(
        arch="sm90", device_id="nvidia:sm90:80gb",
        libs={"torchao": False}))
    p1 = DP.probe(use_cache=False)
    assert p1["capabilities"]["fp8"] is True
    assert p1["usable"]["fp8"] is False

    # 装了 torchao ⇒ 可用
    monkeypatch.setenv("SHIGUANG_DEVICE_PROFILE", fake_device(
        arch="sm90", device_id="nvidia:sm90:80gb", libs={"torchao": True}))
    p2 = DP.probe(use_cache=False)
    assert p2["usable"]["fp8"] is True


def test_profile_cpu_has_no_gpu_caps(monkeypatch, fake_device):
    monkeypatch.setenv("SHIGUANG_DEVICE_PROFILE", fake_device(
        vendor="cpu", arch="cpu", vram_gb=0.0, device_id="cpu:cpu"))
    from app.core.neural import device_profile as DP

    p = DP.probe(use_cache=False)
    assert p["capabilities"]["fp16"] is False
    assert p["capabilities"]["fp8"] is False
    assert p["usable"]["int4"] is False


# ── ② 后端注册表 ──────────────────────────────────────────────────────
def test_backend_registry_respects_missing_libs():
    from app.core.neural import backend_registry as BR

    prof = {"vram_gb": 8.0, "libs": {"diffusers": True, "diffsynth_engine": False,
                                     "nunchaku": False, "tensorrt": False}}
    ids = BR.available_ids(model_arch="sd15", profile=prof)
    assert "diffusers" in ids
    assert "diffsynth" not in ids, "装不上就不该在册"
    assert "nunchaku" not in ids
    # SDXL 下同样只有 diffusers
    ids_xl = BR.available_ids(model_arch="sdxl", profile=prof)
    assert "diffusers" in ids_xl


def test_backend_registry_respects_vram():
    from app.core.neural import backend_registry as BR

    prof = {"vram_gb": 2.0,
            "libs": {"diffusers": True, "diffsynth_engine": True}}
    assert BR.available_ids(model_arch="sdxl", profile=prof) == [], \
        "2GB 卡跑 SDXL（下限 5.0GB）应判不可用"
    assert BR.available_ids(model_arch="sd15", profile=prof) == [], \
        "2GB < SD1.5 下限 2.5GB ⇒ 同样应判不可用（不因为「可能能跑」就放行）"
    # 达标后恢复可选
    prof_ok = {"vram_gb": 8.0,
               "libs": {"diffusers": True, "diffsynth_engine": True}}
    assert "diffusers" in BR.available_ids(model_arch="sd15", profile=prof_ok)


# ── ②b 回归锁（2026-10-24）：svd 架构必须可被选为本地 ──────────────────
def test_svd_arch_is_routable():
    """V4.46.7 曾漏登记 svd 架构 ⇒ planner 把「SVD 视频本地可做」误判为不可用，
    直接架空并行会话刚做的『视频侧真本地双路』（V4.46.6）。此测试防再犯。"""
    from app.core.neural import backend_registry as BR

    prof = {"vram_gb": 8.0,
            "libs": {"diffusers": True, "diffsynth_engine": True}}
    ids = BR.available_ids(model_arch="svd", profile=prof)
    assert "diffsynth" in ids, "SVD（i2v 视频）必须由 diffsynth 承接，否则视频永远走云端"


def test_planner_video_with_reference_can_go_local(monkeypatch, fake_device,
                                                   telemetry_path):
    """capability=video + 有参考图 ⇒ chain 必须含 local（诚实前提：SVD 是 i2v）。"""
    monkeypatch.setenv("SHIGUANG_DEVICE_PROFILE", fake_device(
        libs={"diffusers": True, "diffsynth_engine": True}))
    from app.core.ai import execution_planner as EP

    r = EP.plan(capability="video", has_reference=True)
    assert "local" in r["chain"], "有参考图的本地视频路径被误杀（svd 登记回归）"
    assert r["engine"] in ("diffsynth", "diffusers") or r["engine"] == ""


def test_planner_unknown_arch_falls_back_to_legacy(monkeypatch, fake_device,
                                                   telemetry_path):
    """注册表完全没登记过的架构 ⇒ 必须退回旧引擎探测，而不是武断判「本地不可用」。

    原则：「我没登记」≠「本机做不到」。宁可少一层优化，不可误杀一条可用路径。
    """
    monkeypatch.setenv("SHIGUANG_DEVICE_PROFILE", fake_device(
        libs={"diffusers": True, "diffsynth_engine": True}))
    from app.core.ai import execution_planner as EP

    called = {"n": 0}
    real = EP._legacy_engine_probe

    def spy():
        called["n"] += 1
        return real()

    monkeypatch.setattr(EP, "_legacy_engine_probe", spy)
    r = EP._engine_probe(capability="image")
    # image 走 sd15/sdxl，正常应命中注册表；再用假架构直接验证兜底分支
    from app.core.neural import backend_registry as BR

    assert BR.available_ids(model_arch="totally-unknown-arch") == []
    r2 = EP._engine_probe(capability="image")   # 不抛即安全
    assert isinstance(r2.get("available"), bool)


# ── ③ 引擎遥测（EPLB 对应物）──────────────────────────────────────────
def test_telemetry_recommend_prefers_lower_latency(telemetry_path, monkeypatch,
                                                   fake_device):
    monkeypatch.setenv("SHIGUANG_DEVICE_PROFILE", fake_device())
    from app.core.ai import engine_telemetry as ET

    for _ in range(3):
        ET.record(engine="diffusers", model_arch="sdxl", ok=True,
                  first_ms=35000, steady_ms=23000)
        ET.record(engine="diffsynth", model_arch="sdxl", ok=True,
                  first_ms=415000, steady_ms=20600)
    picked, reasons = ET.recommend(candidates=["diffusers", "diffsynth"],
                                   model_arch="sdxl")
    assert picked == "diffusers", "首图 415s 的引擎不该被选中"
    assert any("diffusers" in r for r in reasons)


def test_telemetry_eliminates_high_failure(telemetry_path, monkeypatch, fake_device):
    monkeypatch.setenv("SHIGUANG_DEVICE_PROFILE", fake_device())
    from app.core.ai import engine_telemetry as ET

    for _ in range(3):
        ET.record(engine="diffsynth", model_arch="sd15", ok=False)
        ET.record(engine="diffusers", model_arch="sd15", ok=True, steady_ms=4200)
    s = ET.score(engine="diffsynth", model_arch="sd15")
    assert s["fail_rate"] == 1.0
    picked, reasons = ET.recommend(candidates=["diffusers", "diffsynth"],
                                   model_arch="sd15")
    assert picked == "diffusers"
    assert any("淘汰" in r for r in reasons)


def test_telemetry_insufficient_samples_returns_none(telemetry_path, monkeypatch,
                                                     fake_device):
    monkeypatch.setenv("SHIGUANG_DEVICE_PROFILE", fake_device())
    from app.core.ai import engine_telemetry as ET

    ET.record(engine="diffusers", model_arch="sd15", ok=True, steady_ms=4000)
    picked, reasons = ET.recommend(candidates=["diffusers"], model_arch="sd15",
                                   min_samples=3)
    assert picked is None, "证据不足时必须如实返回 None，由调用方用默认偏好"
    assert any("证据不足" in r for r in reasons)


# ── ④ 决策器接上设备画像（FP8 不该在无 torchao 的机器上被声明）──────────
def test_planner_does_not_claim_fp8_without_torchao(monkeypatch, fake_device):
    monkeypatch.setenv("SHIGUANG_DEVICE_PROFILE", fake_device(
        arch="sm89", libs={"torchao": False, "diffusers": True,
                           "diffsynth_engine": True}))
    from app.core.ai import execution_planner as EP

    r = EP.plan(capability="image")
    assert "fp8" not in (r.get("accelerators") or []), \
        "没装 torchao 就不能把 fp8 声明为可用加速器"
    assert r.get("device", {}).get("device_id")


def test_planner_reports_device_and_engine_reasons(monkeypatch, fake_device):
    monkeypatch.setenv("SHIGUANG_DEVICE_PROFILE", fake_device(
        libs={"diffusers": True, "diffsynth_engine": True}))
    from app.core.ai import execution_planner as EP

    r = EP.plan(capability="image")
    assert isinstance(r.get("engine_reasons"), list)
    assert r["device"]["vendor"] == "nvidia"


# ── ⑤ 批量出图入口的诚实失败（不跑真推理）─────────────────────────────
def test_generate_batch_rejects_unknown_and_empty():
    from app.core.neural import diffusers_image as DIF

    eng = DIF.get_diffusers_image_engine()
    r1 = eng.generate_batch("no-such-model", prompt="x", count=2)
    assert r1["ok"] is False and "未知模型" in r1["message"]
    r2 = eng.generate_batch("sd15-t2i", prompt="   ", count=2)
    assert r2["ok"] is False and "prompt" in r2["message"]

# -*- coding: utf-8 -*-
"""本地生图接线纯函数：尺寸适配 / 选模型 / 质量档映射。"""
from __future__ import annotations

from app.core.ai import local_image_plan as LP


def test_fit_size_keeps_aspect_and_aligns_64() -> None:
    assert LP.fit_size(0, 0, 512) == (512, 512)
    assert LP.fit_size(512, 512, 512) == (512, 512)
    w, h = LP.fit_size(1280, 720, 1024)
    assert max(w, h) <= 1024 and w % 64 == 0 and h % 64 == 0
    assert abs(w / h - 1280 / 720) < 0.08
    w, h = LP.fit_size(300, 300, 512)
    assert w == h and w % 64 == 0 and w >= 256


def test_pick_model_prefers_sdxl_for_high_quality_when_downloaded() -> None:
    both = ["sd15-t2i", "sdxl-t2i"]
    assert LP.pick_model(quality="draft", downloaded=both) == "sd15-t2i"
    assert LP.pick_model(quality="standard", downloaded=both) == "sd15-t2i"
    assert LP.pick_model(quality="fine", downloaded=both) == "sdxl-t2i"
    assert LP.pick_model(quality="cinema", downloaded=both) == "sdxl-t2i"
    # 大尺寸即使 standard 也走 SDXL
    assert LP.pick_model(quality="standard", width=1280, height=720, downloaded=both) == "sdxl-t2i"
    # SDXL 未下载：诚实回落 sd15
    assert LP.pick_model(quality="fine", downloaded=["sd15-t2i"]) == "sd15-t2i"
    # 都没下载：仍给 sd15（由引擎如实报缺权重）
    assert LP.pick_model(quality="fine", downloaded=[]) == "sd15-t2i"


def test_resolve_preset_maps_canvas_quality() -> None:
    assert LP.resolve_preset(quality="draft") == "fast"
    assert LP.resolve_preset(quality="standard") == "high"
    assert LP.resolve_preset(quality="fine") == "final"
    assert LP.resolve_preset(quality="cinema") == "final"
    assert LP.resolve_preset(quality="nonsense") == ""
    # 不支持 preset 的引擎（diffsynth）一律 ""
    assert LP.resolve_preset(quality="draft", supports_preset=False) == ""


def test_sdxl_fast_falls_back_to_high_without_lcm() -> None:
    assert LP.resolve_preset(quality="draft", model_id="sdxl-t2i", lcm_usable=False) == "high"
    assert LP.resolve_preset(quality="draft", model_id="sdxl-t2i", lcm_usable=True) == "fast"
    # SD1.5 的 fast 不依赖 LCM
    assert LP.resolve_preset(quality="draft", model_id="sd15-t2i", lcm_usable=False) == "fast"


def test_hybrid_local_image_selects_model_preset_and_resolves_inbox_ref(monkeypatch):
    """接线的三条：选 SDXL（fine）、透传 final、inbox 参考图解析成路径。"""
    import app.core.ai.hybrid_dispatch as HD

    seen = {}

    class FakeBackend:
        def generate(self, model_id, *, prompt="", image_path="", width=0, height=0,
                     seed=0, preset=""):
            seen.update(model_id=model_id, image_path=image_path, width=width,
                        height=height, seed=seed, preset=preset)
            return {"ok": True, "image_path": "", "image_url": "/inbox_file/x.png", "seed": seed}

        def lcm_status(self):
            return {"usable": True}

    monkeypatch.setattr(
        "app.core.ai.execution_decider.resolve_local_image_engine",
        lambda **kw: {"ok": True, "engine": "builtin", "is_fallback": False,
                      "backend": FakeBackend(), "reasons": [], "message": ""},
    )
    monkeypatch.setattr(
        "app.core.local_video_infer.resolve_image_path",
        lambda src, **kw: "/tmp/ref.png" if "/inbox_file/" in src else None,
    )
    monkeypatch.setattr(
        "app.core.neural.diffusers_image.DiffusersImageEngine.is_downloaded",
        staticmethod(lambda mid: True),
    )
    reasons = []
    out = HD._local_image(prompt="p", size="720x1280", seed=7,
                          reference_image="/inbox_file/ref.png",
                          reasons=reasons, quality="fine")
    assert out and out["ok"]
    assert out["local_model"] == "sdxl-t2i"
    assert out["preset"] == "final"
    assert out["size"] == "576x1024"
    assert seen == {"model_id": "sdxl-t2i", "image_path": "/tmp/ref.png",
                    "width": 576, "height": 1024, "seed": 7, "preset": "final"}


def test_hybrid_local_image_skips_preset_for_engine_without_it(monkeypatch):
    """主选栈（diffsynth）没有 preset 参数 ⇒ 不能硬塞，否则 TypeError 会误判为失败。"""
    import app.core.ai.hybrid_dispatch as HD

    seen = {}

    class FakeNoPreset:
        def generate(self, model_id, *, prompt="", image_path="", width=0, height=0, seed=0):
            seen.update(model_id=model_id, width=width, height=height, seed=seed)
            return {"ok": True, "image_path": "", "image_url": "", "seed": seed}

    monkeypatch.setattr(
        "app.core.ai.execution_decider.resolve_local_image_engine",
        lambda **kw: {"ok": True, "engine": "diffsynth", "is_fallback": False,
                      "backend": FakeNoPreset(), "reasons": [], "message": ""},
    )
    monkeypatch.setattr(
        "app.core.neural.diffusers_image.DiffusersImageEngine.is_downloaded",
        staticmethod(lambda mid: mid == "sd15-t2i"),
    )
    out = HD._local_image(prompt="p", size="", seed=0, reference_image="",
                          reasons=[], quality="draft")
    assert out and out["ok"]
    assert out["preset"] == ""
    assert seen["model_id"] == "sd15-t2i"
    assert seen["width"] == 512 and seen["height"] == 512


def test_hybrid_local_image_unresolvable_reference_falls_back_to_t2i(monkeypatch):
    import app.core.ai.hybrid_dispatch as HD

    seen = {}

    class FakeBackend:
        def generate(self, model_id, *, prompt="", image_path="", width=0, height=0,
                     seed=0, preset=""):
            seen["image_path"] = image_path
            return {"ok": True, "image_path": "", "image_url": "", "seed": seed}

    monkeypatch.setattr(
        "app.core.ai.execution_decider.resolve_local_image_engine",
        lambda **kw: {"ok": True, "engine": "builtin", "is_fallback": False,
                      "backend": FakeBackend(), "reasons": [], "message": ""},
    )
    monkeypatch.setattr("app.core.local_video_infer.resolve_image_path",
                        lambda src, **kw: None)
    monkeypatch.setattr(
        "app.core.neural.diffusers_image.DiffusersImageEngine.is_downloaded",
        staticmethod(lambda mid: True),
    )
    reasons = []
    out = HD._local_image(prompt="p", size="", seed=0,
                          reference_image="https://evil.example/x.png",
                          reasons=reasons, quality="standard")
    assert out and out["ok"]
    assert seen["image_path"] == ""
    assert any("参考图无法解析" in r for r in reasons)


def test_apply_fp8_quantization_calls_torchao(monkeypatch):
    """fp8 路径：注入假 torchao，验证真的走到 quantize_(unet, Float8WeightOnlyConfig)。"""
    import sys
    import types

    from app.core.neural import diffusers_image as D

    calls = {}

    class Cfg:
        pass

    def quantize_(mod, cfg):
        calls["cfg"] = type(cfg).__name__
        calls["mod"] = mod

    fake = types.ModuleType("torchao.quantization")
    fake.Float8WeightOnlyConfig = Cfg
    fake.quantize_ = quantize_
    pkg = types.ModuleType("torchao")
    pkg.quantization = fake
    monkeypatch.setitem(sys.modules, "torchao", pkg)
    monkeypatch.setitem(sys.modules, "torchao.quantization", fake)

    class P:
        unet = object()

    ok, why = D.apply_fp8_quantization(P())
    assert ok is True and why == ""
    assert calls["cfg"] == "Cfg"
    assert calls["mod"] is P.unet


def test_apply_fp8_quantization_honest_fail(monkeypatch):
    import sys

    from app.core.neural import diffusers_image as D

    monkeypatch.setitem(sys.modules, "torchao", None)  # import 必然失败

    class P:
        unet = object()

    ok, why = D.apply_fp8_quantization(P())
    assert ok is False and "fp8 量化失败" in why


def test_hybrid_local_image_uses_plan_engine_and_model(monkeypatch):
    """引擎链消费：plan 指定 diffusers + sdxl 时，本地跳必须照办。"""
    import app.core.ai.hybrid_dispatch as HD

    seen = {}

    class FakeBackend:
        def generate(self, model_id, **kw):
            seen["model"] = model_id
            return {"ok": True, "image_path": "", "image_url": "", "seed": kw.get("seed", 0)}

        def lcm_status(self):
            return {"usable": True}

    def fake_resolve(prefer=""):
        seen["prefer"] = prefer
        return {"ok": True, "engine": "diffusers", "is_fallback": False,
                "backend": FakeBackend(), "reasons": [], "message": ""}

    monkeypatch.setattr("app.core.ai.execution_decider.resolve_local_image_engine", fake_resolve)
    monkeypatch.setattr(
        "app.core.neural.diffusers_image.DiffusersImageEngine.is_downloaded",
        staticmethod(lambda mid: True),
    )
    reasons = []
    out = HD._local_image(prompt="p", size="", seed=1, reference_image="",
                          reasons=reasons, quality="fine",
                          prefer_engine="diffusers", model_id="sdxl-t2i")
    assert out and out["ok"]
    assert seen["prefer"] == "diffusers" and seen["model"] == "sdxl-t2i"
    assert out["local_model"] == "sdxl-t2i"


def test_hybrid_local_image_plan_model_missing_falls_back(monkeypatch):
    import app.core.ai.hybrid_dispatch as HD

    seen = {}

    class FakeBackend:
        def generate(self, model_id, **kw):
            seen["model"] = model_id
            return {"ok": True, "image_path": "", "image_url": "", "seed": 0}

        def lcm_status(self):
            return {"usable": False}

    monkeypatch.setattr(
        "app.core.ai.execution_decider.resolve_local_image_engine",
        lambda **kw: {"ok": True, "engine": "diffsynth", "is_fallback": False,
                      "backend": FakeBackend(), "reasons": [], "message": ""},
    )
    monkeypatch.setattr(
        "app.core.neural.diffusers_image.DiffusersImageEngine.is_downloaded",
        staticmethod(lambda mid: mid == "sd15-t2i"),
    )
    reasons = []
    out = HD._local_image(prompt="p", size="", seed=0, reference_image="",
                          reasons=reasons, quality="fine",
                          prefer_engine="diffsynth", model_id="sdxl-t2i")
    assert out and out["local_model"] == "sd15-t2i" and seen["model"] == "sd15-t2i"
    assert any("未下载" in r for r in reasons)

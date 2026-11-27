# -*- coding: utf-8 -*-
"""Wan2.2-Lightning 蒸馏 LoRA 加速接线（T4 生成加速，2026-11-20）。

锁定的纪律：
  · LoRA 探测单一真源在 video_gen.find_lightning_lora（tool_weights 委托，不两套逻辑）；
  · 缺 LoRA ⇒ load 诚实失败 + 自取 guidance，**绝不建 pipe、绝不自动下载**；
  · LoRA 加载失败 ⇒ ok=False（不静默当基模跑）；
  · 蒸馏条目 distilled=True ⇒ CFG=1.0、preview=6 步；
  · 非蒸馏模型选 preview ⇒ 诚实回落 fast(10) 并带警告，绝不静默 6 步；
  · Wan 时序 VAE 需 4k+1 帧；Wan kw 宽高取 16 倍数、guidance_scale 单标量。

注：本测试**不加载真模型、不下载权重**——假 diffusers + 假 pipe + 真 imageio 编码。
"""
from __future__ import annotations

import os
import sys
import types

from app.core.neural import video_gen as V

_LIGHTNING_ID = "wan22-ti2v-5b-lightning"


# ─────────────────────── 假管线（与 test_video_gen 同范式）───────────────────────

class _FakePipe:
    """记录 LoRA/offload/调用参数的假管线；__call__ 返回 list[PIL] 帧。"""

    def __init__(self, lora_error: bool = False) -> None:
        self.lora_calls: list = []
        self.calls: list = []
        self.offload_mode = ""
        self.built_from = ""
        self._lora_error = lora_error

    def load_lora_weights(self, path: str) -> None:
        self.lora_calls.append(path)
        if self._lora_error:
            raise RuntimeError("bad lora")

    def enable_sequential_cpu_offload(self) -> None:
        self.offload_mode = "sequential"

    def enable_model_cpu_offload(self) -> None:
        self.offload_mode = "model"

    def to(self, device):
        self.offload_mode = "none"
        return self

    def __call__(self, **kw):
        self.calls.append(kw)
        from PIL import Image

        n = int(kw.get("num_frames", 5))
        frames = [Image.new("RGB", (64, 64), (i * 10 % 256, 0, 0)) for i in range(n)]
        return types.SimpleNamespace(frames=[frames])


def _fake_diffusers(monkeypatch, pipe: _FakePipe) -> None:
    """load() 内 `from diffusers import DiffusionPipeline` 取到假模块。"""
    mod = types.ModuleType("diffusers")

    class DiffusionPipeline:
        @staticmethod
        def from_pretrained(d, **kw):
            pipe.built_from = d
            return pipe

    mod.DiffusionPipeline = DiffusionPipeline
    monkeypatch.setitem(sys.modules, "diffusers", mod)


def _engine_ready(monkeypatch, pipe: _FakePipe) -> V.VideoGenEngine:
    _fake_diffusers(monkeypatch, pipe)
    monkeypatch.setattr(V.VideoGenEngine, "is_available", staticmethod(lambda: True))
    monkeypatch.setattr(V.VideoGenEngine, "is_downloaded", staticmethod(lambda mid: True))
    monkeypatch.setattr(V, "publish_to_inbox",
                        lambda p, name="": {"url": "http://x/v.mp4", "inbox_path": ""})
    return V.VideoGenEngine()


def _put_lora(tmp_path, monkeypatch) -> str:
    p = tmp_path / "Wan2.2-Lightning-4step.safetensors"
    p.write_bytes(b"x")
    monkeypatch.setenv("SHIGUANG_LORA_DIR", str(tmp_path))
    return str(p)


# ─────────────────────── LoRA 探测（单一真源）───────────────────────

def test_find_lightning_lora_env_dir(tmp_path, monkeypatch) -> None:
    p = tmp_path / "Wan2.2-Lightning-4step.safetensors"
    p.write_bytes(b"x")
    monkeypatch.setenv("SHIGUANG_LORA_DIR", str(tmp_path))
    assert V.find_lightning_lora() == str(p)


def test_find_lightning_lora_ignores_non_matching(tmp_path, monkeypatch) -> None:
    """非 lightning 名 / 非 safetensors 都不认；目录不存在不抛。"""
    monkeypatch.setenv("SHIGUANG_LORA_DIR", str(tmp_path))
    monkeypatch.setattr(V, "_REPO_ROOT", str(tmp_path / "no_such_root"))
    (tmp_path / "other.safetensors").write_bytes(b"x")
    (tmp_path / "lightning.pth").write_bytes(b"x")
    assert V.find_lightning_lora() == ""


def test_guidance_has_resource_url_and_safetensors() -> None:
    """guidance 必须含已核资源地址与文件名（下载中心同源）；不得出现 .pth。"""
    g = V.LIGHTNING_LORA_GUIDANCE
    assert "huggingface.co/lightx2v/Wan2.2-Lightning" in g
    assert "*lightning*.safetensors" in g
    assert ".pth" not in g


def test_tool_weights_lora_delegates_to_video_gen() -> None:
    """tool_weights 的 probe/guidance 必须委托 video_gen（不两套搜索逻辑）。"""
    from app.core.neural import tool_weights as TW

    spec = TW.TOOL_WEIGHTS["wan22_lightning_lora"]
    assert spec["probe"] is V.find_lightning_lora
    assert spec["guidance"] == V.LIGHTNING_LORA_GUIDANCE
    assert not hasattr(TW, "_find_lightning_lora"), "旧私有实现应已迁走（单一真源）"


# ─────────────────────── 注册表 / 调优表 ───────────────────────

def test_lightning_registered_reusing_base_repo() -> None:
    spec = V.VIDEO_MODELS[_LIGHTNING_ID]
    assert spec["lora"] == "wan22_lightning"
    assert spec["base_model"] == "wan22-ti2v-5b"
    # 基模复用：同仓同目录 ⇒ 不重复下载 31.9GB
    assert spec["repo"] == V.VIDEO_MODELS["wan22-ti2v-5b"]["repo"]
    assert set(spec["modes"]) == {"t2v", "i2v"}
    assert spec["license"] == "Apache-2.0"


def test_lightning_tuned_distilled_cfg_one() -> None:
    t = V.tuned_for(_LIGHTNING_ID)
    assert t["distilled"] is True
    assert float(t["cfg_min"]) == 1.0 and float(t["cfg_max"]) == 1.0
    assert t["steps"] == V.QUALITY_PRESETS["preview"] == 6
    assert t["offload"] is True and t["decode_chunk_size"] == 1


# ─────────────────────── load：诚实失败 ───────────────────────

def test_load_missing_lora_fails_before_pipe(tmp_path, monkeypatch) -> None:
    """缺 LoRA ⇒ ok=False + 自取 guidance，且**绝不建 pipe**。"""
    monkeypatch.setenv("SHIGUANG_LORA_DIR", str(tmp_path))
    monkeypatch.setattr(V, "_REPO_ROOT", str(tmp_path / "no_such_root"))
    pipe = _FakePipe()
    eng = _engine_ready(monkeypatch, pipe)
    r = eng.load(_LIGHTNING_ID)
    assert r["ok"] is False
    assert "LoRA" in r["message"]
    assert "huggingface.co/lightx2v/Wan2.2-Lightning" in r["message"]
    assert pipe.built_from == "", "缺 LoRA 时不许建 pipe"
    assert pipe.lora_calls == []


def test_load_lora_error_fails_honestly(tmp_path, monkeypatch) -> None:
    """LoRA 文件在但加载抛错 ⇒ ok=False（不静默当基模跑）。"""
    lora = _put_lora(tmp_path, monkeypatch)
    pipe = _FakePipe(lora_error=True)
    eng = _engine_ready(monkeypatch, pipe)
    r = eng.load(_LIGHTNING_ID)
    assert r["ok"] is False and "LoRA" in r["message"]
    assert pipe.lora_calls == [lora]


def test_load_lightning_applies_lora_and_offload(tmp_path, monkeypatch) -> None:
    lora = _put_lora(tmp_path, monkeypatch)
    pipe = _FakePipe()
    eng = _engine_ready(monkeypatch, pipe)
    r = eng.load(_LIGHTNING_ID)
    assert r["ok"], r.get("message")
    assert pipe.lora_calls == [lora]
    assert pipe.offload_mode in ("sequential", "model"), "8GB 登记必须 offload"


# ─────────────────────── generate：Wan 参数口径 ───────────────────────

def test_generate_wan_lightning_t2v_kw_and_frames(tmp_path, monkeypatch) -> None:
    """t2v：CFG=1.0 · 6 步 · 4k+1 帧 · 宽高 16 倍数 · 不读图。"""
    lora = _put_lora(tmp_path, monkeypatch)
    pipe = _FakePipe()
    eng = _engine_ready(monkeypatch, pipe)
    out = str(tmp_path / "out.mp4")
    r = eng.generate(_LIGHTNING_ID, prompt="test", seconds=2.0, fps=7, out_path=out)
    assert r["ok"], r.get("message")
    kw = pipe.calls[-1]
    assert kw["prompt"] == "test" and "image" not in kw
    assert kw["guidance_scale"] == 1.0, "蒸馏权重必须 CFG=1.0"
    assert kw["num_inference_steps"] == 6
    assert kw["width"] % 16 == 0 and kw["height"] % 16 == 0
    assert kw["num_frames"] >= 5 and (kw["num_frames"] - 1) % 4 == 0, "Wan 时序 VAE 需 4k+1"
    assert r["frames"] == kw["num_frames"]
    assert pipe.lora_calls == [lora]
    assert os.path.isfile(out), "真 imageio 编码应落盘"


def test_generate_wan_lightning_i2v_keeps_image(tmp_path, monkeypatch) -> None:
    """i2v：Wan kw 分支不得丢掉 image 键。"""
    _put_lora(tmp_path, monkeypatch)
    from PIL import Image

    img = tmp_path / "in.png"
    Image.new("RGB", (64, 64), (0, 128, 0)).save(img)
    pipe = _FakePipe()
    eng = _engine_ready(monkeypatch, pipe)
    r = eng.generate(_LIGHTNING_ID, image_path=str(img),
                     out_path=str(tmp_path / "o.mp4"))
    assert r["ok"], r.get("message")
    kw = pipe.calls[-1]
    assert "image" in kw and kw["guidance_scale"] == 1.0


def test_preview_non_distilled_falls_back_to_fast_with_warning(tmp_path, monkeypatch) -> None:
    """★ 非蒸馏模型选 preview ⇒ 诚实回落 fast(10) + 警告，绝不静默 6 步。"""
    from PIL import Image

    img = tmp_path / "in.png"
    Image.new("RGB", (64, 64)).save(img)
    pipe = _FakePipe()
    eng = _engine_ready(monkeypatch, pipe)
    r = eng.generate("svd-xt-i2v", image_path=str(img), quality="preview",
                     out_path=str(tmp_path / "o.mp4"))
    assert r["ok"], r.get("message")
    assert r["steps"] == V.QUALITY_PRESETS["fast"] == 10
    assert any("蒸馏" in w for w in r["warnings"]), "回落必须可见（R9）"
    kw = pipe.calls[-1]
    assert kw["num_inference_steps"] == 10
    assert kw["max_guidance_scale"] > 1.0, "非蒸馏基模 CFG 不得关"


def test_preview_distilled_keeps_six_steps(tmp_path, monkeypatch) -> None:
    """蒸馏条目选 preview ⇒ 真 6 步（加速生效），无回落警告。"""
    _put_lora(tmp_path, monkeypatch)
    pipe = _FakePipe()
    eng = _engine_ready(monkeypatch, pipe)
    r = eng.generate(_LIGHTNING_ID, prompt="test", quality="preview",
                     out_path=str(tmp_path / "o.mp4"))
    assert r["ok"], r.get("message")
    assert r["steps"] == 6
    assert not any("回落" in w for w in r["warnings"])

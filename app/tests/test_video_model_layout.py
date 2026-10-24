# -*- coding: utf-8 -*-
"""视频模型落盘判定（2026-10-25 修）：diffusers 变体目录 + transformer/unet 双布局。"""
from __future__ import annotations

import pytest


@pytest.fixture()
def fake_engine(tmp_path, monkeypatch):
    """把 repo_local_dir 指到临时目录（不碰真实缓存）。"""

    class Fake:
        def repo_local_dir(self, repo: str) -> str:
            return str(tmp_path / repo.replace("/", "_"))

    monkeypatch.setattr("app.core.neural_engine.get_neural_engine", lambda: Fake())
    return Fake


def test_local_dir_resolves_diffusers_variant(fake_engine, tmp_path) -> None:
    from app.core.neural import video_gen as VG

    d = tmp_path / "Wan-AI_Wan2.1-T2V-1.3B-Diffusers"
    (d / "transformer").mkdir(parents=True)
    (d / "model_index.json").write_text("{}", encoding="utf-8")
    (d / "transformer" / "diffusion_pytorch_model.safetensors").write_bytes(b"x")

    assert VG.VideoGenEngine.local_dir("wan21-t2v-1.3b") == str(d)
    assert VG.VideoGenEngine.is_downloaded("wan21-t2v-1.3b") is True


def test_unet_layout_still_supported(fake_engine, tmp_path) -> None:
    from app.core.neural import video_gen as VG

    d = tmp_path / "stabilityai_stable-video-diffusion-img2vid-xt"
    (d / "unet").mkdir(parents=True)
    (d / "model_index.json").write_text("{}", encoding="utf-8")
    (d / "unet" / "diffusion_pytorch_model.fp16.safetensors").write_bytes(b"x")

    assert VG.VideoGenEngine.is_downloaded("svd-xt-i2v") is True


def test_missing_model_is_honestly_false(fake_engine) -> None:
    from app.core.neural import video_gen as VG

    assert VG.VideoGenEngine.is_downloaded("wan21-t2v-1.3b") is False
    # 目录不存在时返回「应然路径」，不是空串
    assert VG.VideoGenEngine.local_dir("wan21-t2v-1.3b").endswith("Wan-AI_Wan2.1-T2V-1.3B")


def test_partial_dir_without_weights_is_false(fake_engine, tmp_path) -> None:
    from app.core.neural import video_gen as VG

    d = tmp_path / "Wan-AI_Wan2.1-T2V-1.3B-Diffusers"
    d.mkdir(parents=True)
    (d / "model_index.json").write_text("{}", encoding="utf-8")
    assert VG.VideoGenEngine.is_downloaded("wan21-t2v-1.3b") is False

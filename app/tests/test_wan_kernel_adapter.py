# -*- coding: utf-8 -*-
"""Wan 内核适配器（2026-10-30）：契约自洽 + 形状公式 + 拒绝路径 + 帧转换。

不加载真实模型（27GB）—— 形状/契约类缺陷必须能在 2 秒内抓到。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
import torch

from app.core.neural.kernel.adapters.base import ComponentBag
from app.core.neural.kernel.adapters.wan import WanAdapter
from app.core.neural.kernel.contracts import GenRequest


def test_caps_self_consistent_and_parity_complete():
    a = WanAdapter()
    assert a.caps.violations() == [], a.caps.violations()
    assert a.caps.cfg_mode == "two_pass"
    assert a.caps.latent_rank == 5
    # 视频族必需字段必须填全（守卫 ④ 的口径）
    for k in ("scale_model_input", "init_noise_sigma_once", "noise_aug_before_vae",
              "uncond_repr", "image_latent_concat_dim", "added_time_ids_order",
              "guidance_shape", "decode_chunked", "cfg_order", "encode_delegate"):
        assert k in a.parity.fields, k
    # 未跑通 parity 前不许声称 verified
    assert a.caps.verified == "unverified"


def _bag(model_path="C:/fake/wan", expand=False, vram=8):
    # 必须是真 nn.Module：BaseAdapter._dtype() 要从 .parameters() 推断精度
    net = torch.nn.Linear(4, 4)
    net.config = SimpleNamespace(in_channels=16, expand_timesteps=expand)
    vae = torch.nn.Linear(4, 4)
    vae.config = SimpleNamespace(z_dim=16)
    vae.vae_scale_factor_temporal = 4
    vae.vae_scale_factor_spatial = 8
    sch = SimpleNamespace()
    # from_pipe 把 extras 合并进 parts —— 这里直接按合并后的形态构造
    return ComponentBag({"transformer": net, "vae": vae, "scheduler": sch,
                         "model_path": model_path, "vram_gb": vram})


def test_validate_rejects_missing_model_path_and_wan22():
    a = WanAdapter()
    a.bind(_bag(model_path=""))
    reasons = a.validate()
    assert any("model_path" in r for r in reasons), reasons

    a2 = WanAdapter()
    a2.bind(_bag(expand=True))
    reasons2 = a2.validate()
    assert any("expand_timesteps" in r for r in reasons2), reasons2


def test_init_latents_shape_formula(monkeypatch):
    a = WanAdapter()
    a.bind(_bag())
    # 打桩到 CPU：形状公式与设备无关，但真跑 CUDA 会让这条用例从 3ms 变 40s
    monkeypatch.setattr(a, "_device", lambda: "cpu")
    monkeypatch.setattr(a, "_dtype", lambda: torch.float32)
    req = GenRequest(family="wan", model_id="wan21", frames=17, width=512, height=512)
    lat = a.init_latents(req, cond=None, generator=torch.Generator().manual_seed(0))
    # (frames-1)//4+1 = 5；512//8 = 64；C=16
    assert tuple(lat.shape) == (1, 16, 5, 64, 64), tuple(lat.shape)


def test_as_batch_promotes_2d_embeds(monkeypatch):
    a = WanAdapter()
    a.bind(_bag())
    monkeypatch.setattr(a, "_device", lambda: "cpu")
    monkeypatch.setattr(a, "_dtype", lambda: torch.float32)
    e = torch.zeros(512, 4096)
    out = a._as_batch(e)
    assert out.dim() == 3 and out.shape[0] == 1


def test_to_pil_frames_6d5_to_list():
    a = WanAdapter()
    video = torch.zeros(1, 3, 4, 8, 8)   # [B,C,T,H,W]
    frames = a._to_pil_frames(video)
    assert len(frames) == 4
    assert frames[0].size == (8, 8)
    assert frames[0].mode == "RGB"

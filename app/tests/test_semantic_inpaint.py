# -*- coding: utf-8 -*-
"""app/tests/test_semantic_inpaint.py — T3 本地 SD1.5 语义重绘（2026-11-20）。

核心不变量：**蒙版外像素逐字节保持原图**（羽化回贴 alpha=blur(mask)*(mask>0)）。
权重自取（绝不自动下载）；缺权重 ⇒ guidance（含 OpenRAIL-M 使用限制摘要 + 资源地址）。
纯函数（mask_bbox / feathered_paste）+ mock pipeline，不依赖 torch/diffusers 真权重。
"""
from __future__ import annotations

import numpy as np

from app.core.neural import semantic_inpaint as si


def _img_mask(h=80, w=80):
    rng = np.random.default_rng(42)
    image = rng.integers(0, 256, size=(h, w, 3), dtype=np.uint8)
    mask = np.zeros((h, w), dtype=np.uint8)
    mask[30:50, 30:50] = 255
    return image, mask


# ─────────────────────── 权重目录探测：env 优先 / 认 model_index.json ───────────────────────

def test_find_sd_inpaint_dir_env_and_missing(monkeypatch, tmp_path):
    d = tmp_path / "sd15-inpainting"
    d.mkdir()
    (d / "model_index.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("SHIGUANG_SD_INPAINT_DIR", str(d))
    assert si.find_sd_inpaint_dir() == str(d)
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("SHIGUANG_SD_INPAINT_DIR", str(empty))
    assert si.find_sd_inpaint_dir() == ""


# ─────────────────────── 纯函数：bbox 与羽化回贴不变量 ───────────────────────

def test_mask_bbox_covers_and_clamps():
    _, mask = _img_mask()
    x0, y0, x1, y1 = si.mask_bbox(mask, expand=1.3)
    assert 0 <= x0 <= 30 and 0 <= y0 <= 30
    assert 50 <= x1 <= 80 and 50 <= y1 <= 80
    assert x1 > x0 and y1 > y0


def test_feathered_paste_outside_mask_byte_identical():
    image, mask = _img_mask()
    bbox = si.mask_bbox(mask, 1.3)
    x0, y0, x1, y1 = bbox
    repaint = np.full((y1 - y0, x1 - x0, 3), 123, dtype=np.uint8)
    result = si.feathered_paste(image, repaint, mask, bbox)
    assert result.shape == image.shape
    # 核心不变量：蒙版外逐字节不变
    assert np.array_equal(result[mask == 0], image[mask == 0])


# ─────────────────────── 缺权重 ⇒ 诚实 guidance ───────────────────────

def test_missing_weights_returns_guidance(monkeypatch):
    monkeypatch.setattr(si, "find_sd_inpaint_dir", lambda: "")
    image, mask = _img_mask()
    res = si.semantic_inpaint(image, mask, "重绘")
    assert res["ok"] is False
    g = res.get("guidance") or ""
    assert "OpenRAIL-M" in g
    assert "stable-diffusion-v1-5/stable-diffusion-inpainting" in g
    assert "绝不自动下载" in g


# ─────────────────────── mock pipeline：成功 + 不变量 + remove 绿幕 ───────────────────────

def test_orchestration_mock_preserves_outside_mask(monkeypatch):
    monkeypatch.setattr(si, "find_sd_inpaint_dir", lambda: "/fake/sd15-inpainting")
    monkeypatch.setattr(si, "_load_pipeline", lambda d: object())
    monkeypatch.setattr(si, "_run_pipeline",
                        lambda pipe, img, mask, prompt, steps: (img // 2).astype(np.uint8))
    image, mask = _img_mask()
    res = si.semantic_inpaint(image, mask, "重绘")
    assert res["ok"] is True
    assert res["engine"] == "sd15-inpaint"
    assert res["degraded"] is False
    assert np.array_equal(res["image"][mask == 0], image[mask == 0])


def test_remove_mode_uses_green_prompt(monkeypatch):
    seen = {}

    def _fake_run(pipe, img, mask, prompt, steps):
        seen["prompt"] = prompt
        return img.copy()
    monkeypatch.setattr(si, "find_sd_inpaint_dir", lambda: "/fake/sd15-inpainting")
    monkeypatch.setattr(si, "_load_pipeline", lambda d: object())
    monkeypatch.setattr(si, "_run_pipeline", _fake_run)
    image, mask = _img_mask()
    res = si.semantic_inpaint(image, mask, "", mode="remove")
    assert res["ok"] is True
    assert "绿色" in seen["prompt"]

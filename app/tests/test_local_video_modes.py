# -*- coding: utf-8 -*-
"""本地视频：模型能力（t2v/i2v）单源 + 路由前置判定。

背景（2026-11-15）：此前「谁需要首帧图」有三套说法——
  · 前端 `localVideo.ts` 硬编码 `new Set(["wan21-t2v-1.3b"])`；
  · `_infer_wan` 见到 reference_image 就拒绝；
  · `_infer_cogvideox/hunyuan/ltx` 收下参数后**静默忽略**（等于假装支持）。
现在收口到 `video_gen.available_models()` 的 `modes`，**按模型 id 判而非族名**
（wan21 只有 t2v、wan22 是 t2v+i2v，同族不同能力）。
"""
from __future__ import annotations

import pytest


def test_modes_t2v_only():
    from app.core.canvas_routes_local_video import _model_modes

    assert _model_modes("wan21-t2v-1.3b") == {"t2v": True, "i2v": False}


def test_modes_i2v_only():
    from app.core.canvas_routes_local_video import _model_modes

    assert _model_modes("svd-xt-i2v") == {"t2v": False, "i2v": True}


def test_modes_both_for_ti2v():
    from app.core.canvas_routes_local_video import _model_modes

    assert _model_modes("wan22-ti2v-5b") == {"t2v": True, "i2v": True}


def test_modes_unknown_model_does_not_judge():
    """查不到就两边都放行 —— 不代判，交各族如实拒绝。"""
    from app.core.canvas_routes_local_video import _model_modes

    assert _model_modes("brand-new-model") == {"t2v": True, "i2v": True}


def test_image_to_t2v_only_model_is_rejected_with_actionable_hint():
    """给纯文生视频模型塞首帧图 ⇒ 明确拒绝，并告诉用户怎么改。"""
    from app.core.canvas_routes_local_video import _delegate_local_video_infer

    r = _delegate_local_video_infer({"model_id": "wan21-t2v-1.3b"}, "/tmp/first.png", "wan")
    assert r["ok"] is False
    assert "纯文生视频" in r["message"]
    # 必须给出可操作出口，否则用户只知道失败
    assert "移除首帧图" in r["message"]
    assert "svd-xt-i2v" in r["message"]


def test_no_image_to_i2v_only_model_is_rejected():
    from app.core.canvas_routes_local_video import _delegate_local_video_infer

    r = _delegate_local_video_infer({"model_id": "svd-xt-i2v"}, "", "svd")
    assert r["ok"] is False
    assert "需要首帧图" in r["message"]


def test_t2v_without_image_passes_gate(monkeypatch):
    """wan + 不传图 ⇒ 放行到 generate_video_local（T2V 本来的用法）。"""
    import app.core.local_video_infer as L

    captured: dict = {}

    def _fake(**kw):
        captured.update(kw)
        return {"ok": True, "video_path": "/tmp/out.mp4"}

    monkeypatch.setattr(L, "generate_video_local", _fake, raising=True)

    from app.core.canvas_routes_local_video import _delegate_local_video_infer

    r = _delegate_local_video_infer(
        {"model_id": "wan21-t2v-1.3b", "prompt": "a cat", "seconds": 5, "size": "480x832"},
        "",
        "wan",
    )
    assert r["ok"] is True
    assert captured["model"] == "wan21-t2v-1.3b"
    assert captured["prompt"] == "a cat"
    # 不吃图的模型这里不会被塞图
    assert not captured.get("reference_image")
    assert not captured.get("first_frame")

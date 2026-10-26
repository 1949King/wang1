# -*- coding: utf-8 -*-
"""Wan 的 frames 是 ndarray（output_type="np"）时不能被布尔判断（2026-10-27 实测崩溃修复）。"""
from __future__ import annotations

import numpy as np

import app.core.local_video_infer as LVI


def _frames_from(result_frames):
    """复刻修复后的分支逻辑（与 _infer_wan 内联保持一致）。"""
    _fr = result_frames
    if _fr is None:
        return []
    if hasattr(_fr, "ndim"):
        return _fr[0] if _fr.ndim >= 4 else _fr
    if len(_fr):
        return _fr[0]
    return []


def test_ndarray_frames_do_not_raise():
    arr = np.zeros((1, 5, 64, 64, 3), dtype=np.uint8)   # (batch, T, H, W, C)
    out = _frames_from(arr)
    assert getattr(out, "shape", None) == (5, 64, 64, 3)


def test_ndarray_single_frame_and_none_and_list():
    # ndim=4 ⇒ 视为 (batch, T, H, W, C)，取 batch 0
    assert _frames_from(np.zeros((3, 8, 8, 3), dtype=np.uint8)).shape == (8, 8, 3)
    assert _frames_from(None) == []
    assert _frames_from([]) == []
    assert _frames_from([[1, 2, 3]]) == [1, 2, 3]


def test_save_video_frames_accepts_ndarray(tmp_path):
    """_save_video_frames 必须能吃 ndarray（修复前 Wan 到这一步前后就崩了）。"""
    arr = (np.random.rand(4, 32, 32, 3) * 255).astype(np.uint8)
    out = LVI._save_video_frames(arr, str(tmp_path), 0, fps=8)
    assert isinstance(out, dict), out
    assert out.get("ok") is True, out

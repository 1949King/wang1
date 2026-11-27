# -*- coding: utf-8 -*-
"""app/tests/test_video_upscale_2x.py — T2 视频超分净 2x（2026-11-20）。

_upscale_frames 改 load(scale=2, use_realesrgan=True)：
  · RealESRGAN 固定 4x 输出 ⇒ resize 0.5 得净 2x（上游 esrgan trick）；
  · 权重缺失 ⇒ load False ⇒ 返 False，帧保持原尺寸（诚实降级，上层保留原片）。
"""
from __future__ import annotations

import os

import cv2
import numpy as np

from app.core import generation_postprocess as gp


def _write_frames(frame_dir: str, n: int = 2, size: int = 16) -> None:
    """写 n 张 size×size 的测试帧。"""
    os.makedirs(frame_dir, exist_ok=True)
    for i in range(1, n + 1):
        img = np.zeros((size, size, 3), np.uint8)
        img[:, :, 1] = 128
        cv2.imwrite(os.path.join(frame_dir, "f_%06d.png" % i), img)


def _fake_onnx_engine():
    """桩神经引擎：ONNX 可用，RealESRGAN 推理固定返回 4x 输出（16→64）。"""
    from app.core.neural_engine import InferenceBackend

    class _E:
        is_available = True
        backend = InferenceBackend.ONNX

        def download_model(self, *a, **k):
            raise AssertionError("红线：绝不自动下载权重")

        def load_onnx_model(self, path, name):
            return True

        def run_onnx_inference(self, name, inputs):
            # RealESRGAN x4plus：固定 4x 输出 (1,3,H*4,W*4)
            return [np.zeros((1, 3, 64, 64), np.float32)]

    return _E()


def test_upscale_frames_net_2x_with_realesrgan(monkeypatch, tmp_path):
    """权重在盘 ⇒ 逐帧超分后**净 2x**（4x 输出 resize 0.5），不是 4x。"""
    frame_dir = str(tmp_path / "frames")
    _write_frames(frame_dir)
    w = tmp_path / "realesrgan_x4plus.onnx"
    w.write_bytes(b"fake")
    monkeypatch.setenv("SHIGUANG_REALESRGAN_PATH", str(w))
    monkeypatch.setattr("app.core.neural_engine.get_neural_engine", _fake_onnx_engine)
    assert gp._upscale_frames(frame_dir) is True
    for f in sorted(os.listdir(frame_dir)):
        img = cv2.imread(os.path.join(frame_dir, f))
        assert img.shape[:2] == (32, 32), "RealESRGAN 4x 输出须 resize 0.5 得净 2x"


def test_upscale_frames_missing_weights_keeps_original(monkeypatch, tmp_path):
    """权重缺失 ⇒ 返 False 且帧保持原尺寸（诚实降级，绝不假装超分）。"""
    frame_dir = str(tmp_path / "frames")
    _write_frames(frame_dir)
    monkeypatch.setenv("SHIGUANG_REALESRGAN_PATH", str(tmp_path / "nope.onnx"))
    monkeypatch.setenv("SHIGUANG_ESPCN_DIR", str(tmp_path))
    monkeypatch.setattr("app.core.neural_engine.get_neural_engine", _fake_onnx_engine)
    assert gp._upscale_frames(frame_dir) is False
    for f in sorted(os.listdir(frame_dir)):
        img = cv2.imread(os.path.join(frame_dir, f))
        assert img.shape[:2] == (16, 16), "权重缺失须保留原帧，不假装超分"

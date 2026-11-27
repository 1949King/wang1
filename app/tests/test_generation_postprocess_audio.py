"""app/tests/test_generation_postprocess_audio.py — 视频后处理补音频接线契约（T1 项一，2026-11-20）。

锁死 apply_video_postprocess 的音轨行为：
  - 源有音轨 ⇒ 编码成功后调 mux_source_audio，返回 mux 产物路径。
  - 源无音轨 ⇒ 不调 mux，返回编码路径（旧行为）。
  - mux 失败 ⇒ 返回编码路径，不崩。
  - video_path 不存在 ⇒ 原样返回（:264 回归）。
  - 时序稳定器失败 ⇒ 仅 warning，不阻断后处理。
"""
import os
from unittest.mock import MagicMock, patch

import pytest

from app.core import generation_postprocess as gp


@pytest.fixture
def fake_video(tmp_path):
    """创建一个假视频文件供测试。"""
    v = tmp_path / "gen.mp4"
    v.write_bytes(b"\x00" * 128)
    return str(v)


@pytest.fixture
def stub_pipeline(monkeypatch, fake_video):
    """桩掉抽帧/编码/超分/补帧/稳定器，只测 mux 接线逻辑。"""
    monkeypatch.setattr(gp, "_extract_frames", lambda *a, **kw: 10)
    monkeypatch.setattr(gp, "_encode_frames", lambda *a, **kw: True)
    monkeypatch.setattr(gp, "_upscale_frames", lambda *a, **kw: True)
    monkeypatch.setattr(gp, "_interpolate_frames", lambda *a, **kw: None)
    monkeypatch.setattr(gp, "_read_video_fps", lambda *a, **kw: 24.0)
    # 桩 ffmpeg 路径检查
    monkeypatch.setattr("app.core.ffmpeg_utils.get_ffmpeg", lambda: "/fake/ffmpeg")
    monkeypatch.setattr(os.path, "isfile", lambda p: True)
    return fake_video


class TestAudioMuxWiring:
    """apply_video_postprocess 音轨 mux 接线。"""

    def test_has_audio_calls_mux_and_returns_mux_path(self, stub_pipeline, monkeypatch, tmp_path):
        """源有音轨 ⇒ mux 被调一次，返回 mux 产物。"""
        mux_out = str(tmp_path / "gen_post_mux.mp4")
        mux_mock = MagicMock(return_value=True)
        monkeypatch.setattr(gp, "probe_has_audio", lambda p: True)
        monkeypatch.setattr(gp, "mux_source_audio", mux_mock)
        # 桩稳定器（避免 import 不存在的模块）
        monkeypatch.setattr(gp, "stabilize_frame_sequence", lambda *a, **kw: True)

        result = gp.apply_video_postprocess(stub_pipeline, {"upscale": True})
        assert mux_mock.call_count == 1
        # 返回的路径应是 mux 产物（不是编码产物）
        assert result != stub_pipeline
        assert "_post" in result or "mux" in result

    def test_no_audio_skips_mux(self, stub_pipeline, monkeypatch):
        """源无音轨 ⇒ mux 未被调，返回编码路径。"""
        mux_mock = MagicMock(return_value=True)
        monkeypatch.setattr(gp, "probe_has_audio", lambda p: False)
        monkeypatch.setattr(gp, "mux_source_audio", mux_mock)
        monkeypatch.setattr(gp, "stabilize_frame_sequence", lambda *a, **kw: True)

        result = gp.apply_video_postprocess(stub_pipeline, {"upscale": True})
        mux_mock.assert_not_called()
        assert "_post.mp4" in result

    def test_mux_failure_returns_encode_path(self, stub_pipeline, monkeypatch):
        """mux 失败 ⇒ 返回编码路径，不崩。"""
        monkeypatch.setattr(gp, "probe_has_audio", lambda p: True)
        monkeypatch.setattr(gp, "mux_source_audio", lambda *a, **kw: False)
        monkeypatch.setattr(gp, "stabilize_frame_sequence", lambda *a, **kw: True)

        result = gp.apply_video_postprocess(stub_pipeline, {"upscale": True})
        assert "_post.mp4" in result
        assert result != stub_pipeline  # 编码成功，不是原路径

    def test_video_not_exist_returns_original(self, monkeypatch):
        """video_path 不存在 ⇒ 原样返回（回归 :264）。"""
        # 恢复真实 isfile
        monkeypatch.setattr(os.path, "isfile", os.path.isfile)
        result = gp.apply_video_postprocess("/nonexistent/video.mp4", {"upscale": True})
        assert result == "/nonexistent/video.mp4"

    def test_stabilizer_failure_does_not_block(self, stub_pipeline, monkeypatch):
        """时序稳定器失败 ⇒ 仅 warning，后处理继续。"""
        monkeypatch.setattr(gp, "probe_has_audio", lambda p: False)
        monkeypatch.setattr(gp, "mux_source_audio", lambda *a, **kw: False)
        monkeypatch.setattr(gp, "stabilize_frame_sequence", lambda *a, **kw: False)

        result = gp.apply_video_postprocess(stub_pipeline, {"upscale": True})
        # 稳定器失败不阻断，编码仍成功
        assert "_post.mp4" in result

    def test_no_flags_returns_original(self, fake_video):
        """无 upscale/frame_interpolate 标志 ⇒ 原样返回。"""
        result = gp.apply_video_postprocess(fake_video, {})
        assert result == fake_video

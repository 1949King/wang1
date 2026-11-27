"""app/tests/test_ffmpeg_audio_mux.py — 音轨探测与 mux helper 契约（T1 项一，2026-11-20）。

锁死两条行为：
  1. probe_has_audio：ffprobe 探测源视频是否含音轨，异常/缺失 ⇒ False 不抛。
  2. mux_source_audio：把源音轨 mux 到无声产物，命令必须含
     -map 0:v:0 -map 1:a:0? -c:v copy -c:a aac -shortest；
     源无音轨/非零退出/文件不存在/ffmpeg 缺失 ⇒ False 不抛。
"""
import os
import subprocess
from unittest.mock import MagicMock

import pytest

from app.core import ffmpeg_utils


# ─────────────────────── probe_has_audio ───────────────────────

class TestProbeHasAudio:
    """probe_has_audio 契约。"""

    def test_has_audio_returns_true(self, monkeypatch, tmp_path):
        """ffprobe 输出含流索引 ⇒ True。"""
        video = tmp_path / "src.mp4"
        video.write_bytes(b"\x00" * 64)
        fake_result = MagicMock(returncode=0, stdout="0\n")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake_result)
        monkeypatch.setattr(ffmpeg_utils, "get_ffprobe", lambda: "/fake/ffprobe")
        assert ffmpeg_utils.probe_has_audio(str(video)) is True

    def test_no_audio_returns_false(self, monkeypatch, tmp_path):
        """ffprobe 输出为空 ⇒ False。"""
        video = tmp_path / "src.mp4"
        video.write_bytes(b"\x00" * 64)
        fake_result = MagicMock(returncode=0, stdout="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake_result)
        monkeypatch.setattr(ffmpeg_utils, "get_ffprobe", lambda: "/fake/ffprobe")
        assert ffmpeg_utils.probe_has_audio(str(video)) is False

    def test_file_not_exist_returns_false(self):
        """文件不存在 ⇒ False，不抛。"""
        assert ffmpeg_utils.probe_has_audio("/nonexistent/video.mp4") is False

    def test_ffprobe_missing_returns_false(self, monkeypatch, tmp_path):
        """ffprobe 不可用（返回空串）⇒ False，不抛。"""
        video = tmp_path / "src.mp4"
        video.write_bytes(b"\x00" * 64)
        monkeypatch.setattr(ffmpeg_utils, "get_ffprobe", lambda: "")
        assert ffmpeg_utils.probe_has_audio(str(video)) is False

    def test_subprocess_exception_returns_false(self, monkeypatch, tmp_path):
        """subprocess 抛异常 ⇒ False，不抛。"""
        video = tmp_path / "src.mp4"
        video.write_bytes(b"\x00" * 64)
        monkeypatch.setattr(ffmpeg_utils, "get_ffprobe", lambda: "/fake/ffprobe")

        def _raise(*a, **kw):
            raise OSError("ffprobe crashed")

        monkeypatch.setattr(subprocess, "run", _raise)
        assert ffmpeg_utils.probe_has_audio(str(video)) is False

    def test_nonzero_exit_returns_false(self, monkeypatch, tmp_path):
        """ffprobe 非零退出 ⇒ False。"""
        video = tmp_path / "src.mp4"
        video.write_bytes(b"\x00" * 64)
        fake_result = MagicMock(returncode=1, stdout="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake_result)
        monkeypatch.setattr(ffmpeg_utils, "get_ffprobe", lambda: "/fake/ffprobe")
        assert ffmpeg_utils.probe_has_audio(str(video)) is False


# ─────────────────────── mux_source_audio ───────────────────────

class TestMuxSourceAudio:
    """mux_source_audio 契约。"""

    def test_command_contains_required_flags(self, monkeypatch, tmp_path):
        """命令必须含 -map 0:v:0 -map 1:a:0? -c:v copy -c:a aac -shortest。"""
        silent = tmp_path / "silent.mp4"
        source = tmp_path / "source.mp4"
        out = tmp_path / "out.mp4"
        silent.write_bytes(b"\x00" * 64)
        source.write_bytes(b"\x00" * 64)

        captured_cmd = []

        def _fake_run(cmd, **kw):
            captured_cmd.extend(cmd)
            # 模拟成功：创建输出文件
            out.write_bytes(b"\x00" * 128)
            return MagicMock(returncode=0)

        monkeypatch.setattr(subprocess, "run", _fake_run)
        monkeypatch.setattr(ffmpeg_utils, "get_ffmpeg", lambda: "/fake/ffmpeg")
        # probe_has_audio 返回 True（源有音轨）
        monkeypatch.setattr(ffmpeg_utils, "probe_has_audio", lambda p: True)

        result = ffmpeg_utils.mux_source_audio(str(silent), str(source), str(out))
        assert result is True
        cmd_str = " ".join(captured_cmd)
        assert "-map" in cmd_str
        assert "0:v:0" in cmd_str
        assert "1:a:0?" in cmd_str
        assert "-c:v" in cmd_str and "copy" in cmd_str
        assert "-c:a" in cmd_str and "aac" in cmd_str
        assert "-shortest" in cmd_str

    def test_source_no_audio_returns_false(self, monkeypatch, tmp_path):
        """源无音轨 ⇒ False，不调 ffmpeg。"""
        silent = tmp_path / "silent.mp4"
        source = tmp_path / "source.mp4"
        out = tmp_path / "out.mp4"
        silent.write_bytes(b"\x00" * 64)
        source.write_bytes(b"\x00" * 64)

        called = []
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: called.append(1))
        monkeypatch.setattr(ffmpeg_utils, "get_ffmpeg", lambda: "/fake/ffmpeg")
        monkeypatch.setattr(ffmpeg_utils, "probe_has_audio", lambda p: False)

        assert ffmpeg_utils.mux_source_audio(str(silent), str(source), str(out)) is False
        assert not called, "源无音轨时不应调用 ffmpeg"

    def test_nonzero_exit_returns_false(self, monkeypatch, tmp_path):
        """ffmpeg 非零退出 ⇒ False。"""
        silent = tmp_path / "silent.mp4"
        source = tmp_path / "source.mp4"
        out = tmp_path / "out.mp4"
        silent.write_bytes(b"\x00" * 64)
        source.write_bytes(b"\x00" * 64)

        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: MagicMock(returncode=1))
        monkeypatch.setattr(ffmpeg_utils, "get_ffmpeg", lambda: "/fake/ffmpeg")
        monkeypatch.setattr(ffmpeg_utils, "probe_has_audio", lambda p: True)

        assert ffmpeg_utils.mux_source_audio(str(silent), str(source), str(out)) is False

    def test_file_not_exist_returns_false(self, tmp_path):
        """输入文件不存在 ⇒ False，不抛。"""
        out = tmp_path / "out.mp4"
        assert ffmpeg_utils.mux_source_audio("/no/silent.mp4", "/no/source.mp4", str(out)) is False

    def test_ffmpeg_missing_returns_false(self, monkeypatch, tmp_path):
        """ffmpeg 不可用 ⇒ False，不抛。"""
        silent = tmp_path / "silent.mp4"
        source = tmp_path / "source.mp4"
        out = tmp_path / "out.mp4"
        silent.write_bytes(b"\x00" * 64)
        source.write_bytes(b"\x00" * 64)
        monkeypatch.setattr(ffmpeg_utils, "get_ffmpeg", lambda: "")
        monkeypatch.setattr(ffmpeg_utils, "probe_has_audio", lambda p: True)
        assert ffmpeg_utils.mux_source_audio(str(silent), str(source), str(out)) is False

    def test_subprocess_exception_returns_false(self, monkeypatch, tmp_path):
        """subprocess 抛异常 ⇒ False，不抛。"""
        silent = tmp_path / "silent.mp4"
        source = tmp_path / "source.mp4"
        out = tmp_path / "out.mp4"
        silent.write_bytes(b"\x00" * 64)
        source.write_bytes(b"\x00" * 64)

        def _raise(*a, **kw):
            raise OSError("ffmpeg crashed")

        monkeypatch.setattr(subprocess, "run", _raise)
        monkeypatch.setattr(ffmpeg_utils, "get_ffmpeg", lambda: "/fake/ffmpeg")
        monkeypatch.setattr(ffmpeg_utils, "probe_has_audio", lambda p: True)
        assert ffmpeg_utils.mux_source_audio(str(silent), str(source), str(out)) is False

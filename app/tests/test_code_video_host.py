# -*- coding: utf-8 -*-
"""render_host 纯函数/失败路径测试（V4.45 · 2026-10-19）

不启动 Chromium：只测编排前置（编译/解析/命令构造/校验/发布）。
真渲染冒烟由 `_verify/check_code_video_render.py`（可选）与手工验收覆盖。
"""
from app.core.code_video import render_host
from app.core.code_video.spec import (
    AssetEntry,
    CanvasSettings,
    CodeVideoSpec,
    SpecClip,
    SpecTrack,
    compile_spec,
)


def _spec(**kwargs):
    return CodeVideoSpec(
        canvas=CanvasSettings(width=540, height=960, fps=30, duration=2.0, **kwargs),
        tracks=[SpecTrack(id="v1", kind="video", clips=[
            SpecClip(id="c1", source="asset://shot_1.mp4", range=[0.0, 2.0], kind="video"),
        ])],
        assets={"shot_1.mp4": AssetEntry(kind="video", duration=2.0)},
    )


def test_render_without_input():
    result = render_host.render()
    assert result["ok"] is False
    assert result["stage"] == "compile"


def test_render_compile_error():
    spec = _spec()
    spec.canvas.fps = 60
    result = render_host.render(spec=spec)
    assert result["ok"] is False
    assert result["stage"] == "compile"
    assert "fps" in result["error"]


def test_render_missing_asset_fails_before_chromium(tmp_path):
    spec = _spec()
    compiled, errors = compile_spec(spec)
    assert compiled is not None, errors
    result = render_host.render(compiled=compiled, inbox_dir=str(tmp_path))
    assert result["ok"] is False
    assert result["stage"] == "resolve_assets"
    assert "不存在" in result["error"]


def test_render_security_limit_rejected():
    compiled = {
        "canvas": {"width": 2160, "height": 3840, "fps": 30, "duration": 2.0},
        "tracks": [{"clip": {"id": "c1", "source": "html://a.html", "kind": "text"}}],
        "assets": {},
    }
    result = render_host.render(compiled=compiled, inbox_dir=".")
    assert result["ok"] is False
    assert result["stage"] == "security"


def test_build_encode_cmd_with_audio():
    cmd = render_host._build_encode_cmd(
        "frames", "out.mp4", fps=30, duration=2.0,
        audio_inputs=["a.m4a"], filter_complex="[1:a]anull[aout]", has_audio=True,
    )
    assert "-filter_complex" in cmd
    assert cmd[cmd.index("-map") + 1] == "0:v"
    assert cmd[cmd.index("-map", cmd.index("-map") + 1) + 1] == "[aout]"
    assert "libx264" in cmd
    assert cmd[-1] == "out.mp4"


def test_build_encode_cmd_silent():
    cmd = render_host._build_encode_cmd(
        "frames", "out.mp4", fps=30, duration=2.0,
        audio_inputs=[], filter_complex="", has_audio=False,
    )
    assert "anullsrc=channel_layout=stereo:sample_rate=48000" in cmd
    assert "-filter_complex" not in cmd


def test_validate_output_ok():
    probe = {
        "ok": True,
        "format": {"duration": "2.00"},
        "streams": [{"codec_type": "video", "width": 540, "height": 960,
                     "r_frame_rate": "30/1"}],
    }
    assert render_host._validate_output(
        probe, {"canvas": {"width": 540, "height": 960, "fps": 30, "duration": 2.0}}
    ) == []


def test_validate_output_duration_mismatch():
    probe = {
        "ok": True,
        "format": {"duration": "5.00"},
        "streams": [{"codec_type": "video", "width": 540, "height": 960,
                     "r_frame_rate": "30/1"}],
    }
    errors = render_host._validate_output(
        probe, {"canvas": {"width": 540, "height": 960, "fps": 30, "duration": 2.0}}
    )
    assert any("时长" in e for e in errors)


def test_validate_output_size_mismatch():
    probe = {
        "ok": True,
        "format": {"duration": "2.00"},
        "streams": [{"codec_type": "video", "width": 1080, "height": 1920,
                     "r_frame_rate": "30/1"}],
    }
    errors = render_host._validate_output(
        probe, {"canvas": {"width": 540, "height": 960, "fps": 30, "duration": 2.0}}
    )
    assert any("宽" in e for e in errors)


def test_validate_output_probe_failed():
    assert render_host._validate_output({"ok": False, "error": "boom"}, {"canvas": {}})


def test_publish_local_inbox(tmp_path):
    src = tmp_path / "out.mp4"
    src.write_bytes(b"mp4")
    inbox = tmp_path / "inbox"
    published = render_host._publish(str(src), "x.mp4", str(inbox))
    assert published["inbox_path"] == str(inbox / "x.mp4")
    assert (inbox / "x.mp4").is_file()
    assert published["url"].endswith("/inbox_file/x.mp4")


def test_publish_sanitizes_bad_name(tmp_path):
    src = tmp_path / "out.mp4"
    src.write_bytes(b"mp4")
    published = render_host._publish(str(src), "../evil.mp4", str(tmp_path / "inbox"))
    assert published["inbox_name"].startswith("code_video_")
    assert "evil" not in published["inbox_name"]


def test_ffmpeg_bin_available():
    assert render_host._ffmpeg_bin()

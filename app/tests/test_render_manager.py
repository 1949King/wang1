"""渲染管理器 RenderManager 测试 (pytest 风格)

覆盖: 码率解析、平台预设结构、质量预设降采样、渲染配置拷贝、GPU 编码器选择。
纯逻辑/结构测试, 通过 object.__new__ 绕过 __init__ 的 C++ 引擎 / FFmpeg 后端初始化,
不触发真实渲染。
运行: pytest app/tests/test_render_manager.py -v
"""

import pytest

from app.core.render_manager import (
    HardwareEncoder,
    PLATFORM_PRESETS,
    RenderConfig,
    RenderManager,
    RenderMode,
    _parse_bitrate,
)


class TestParseBitrate:
    """码率字符串解析测试"""

    def test_megabytes(self):
        assert _parse_bitrate("5M") == 5000000

    def test_kilobits(self):
        assert _parse_bitrate("128k") == 128000

    def test_raw_number(self):
        assert _parse_bitrate("3000") == 3000

    def test_empty_returns_default(self):
        assert _parse_bitrate("") == 5000000

    def test_decimal_megabytes(self):
        assert _parse_bitrate("1.5M") == 1500000

    def test_invalid_returns_default(self):
        assert _parse_bitrate("abc") == 5000000


class TestPlatformPresets:
    """平台导出预设结构测试"""

    def test_all_platforms_have_required_fields(self):
        for preset in PLATFORM_PRESETS.values():
            assert "width" in preset
            assert "height" in preset
            assert "fps" in preset
            assert "video_bitrate" in preset

    def test_douyin_vertical(self):
        assert PLATFORM_PRESETS["抖音"]["width"] == 1080
        assert PLATFORM_PRESETS["抖音"]["height"] == 1920

    def test_bilibili_60fps(self):
        assert PLATFORM_PRESETS["B站"]["fps"] == 60.0


class TestRenderConfig:
    """渲染配置数据结构测试"""

    def test_default_config(self):
        cfg = RenderConfig()
        assert cfg.width == 1920
        assert cfg.height == 1080
        assert cfg.video_codec == "libx264"
        assert cfg.mode == RenderMode.STANDARD

    def test_copy_is_independent(self):
        cfg = RenderConfig()
        cloned = cfg.copy()
        cloned.width = 640
        assert cfg.width == 1920
        assert cloned.width == 640


@pytest.fixture
def render_manager_no_gpu():
    """无 GPU 的 RenderManager（绕过 __init__ 后端初始化）"""
    manager = object.__new__(RenderManager)
    manager._hw = {"has_gpu": False, "h264_encoder": HardwareEncoder.NONE}
    return manager


class TestGetPlatformPreset:
    """平台预设 + 质量模式生成配置测试"""

    def test_douyin_preset_dims(self, render_manager_no_gpu):
        cfg = render_manager_no_gpu.get_platform_preset("抖音", RenderMode.STANDARD)
        assert cfg.width == 1080
        assert cfg.height == 1920

    def test_preview_mode_scales_down(self, render_manager_no_gpu):
        cfg = render_manager_no_gpu.get_platform_preset("通用HD", RenderMode.PREVIEW)
        assert cfg.width == 960
        assert cfg.height == 540

    def test_export_mode_uses_export_crf(self, render_manager_no_gpu):
        cfg = render_manager_no_gpu.get_platform_preset("通用HD", RenderMode.EXPORT)
        assert cfg.crf == 18

    def test_gpu_encoder_applied(self):
        manager = object.__new__(RenderManager)
        manager._hw = {"has_gpu": True, "h264_encoder": HardwareEncoder.NVIDIA}
        cfg = manager.get_platform_preset("通用HD", RenderMode.STANDARD)
        assert cfg.gpu_encoder == HardwareEncoder.NVIDIA
        assert cfg.video_codec == "h264_nvenc"
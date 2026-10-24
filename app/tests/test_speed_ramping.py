# -*- coding: utf-8 -*-
"""A3：SpeedRamp 数学 + 多段 FFmpeg filter 构建（无真实 ffmpeg）。"""

from __future__ import annotations

import pytest

from app.core.speed_ramping import (
    SpeedRamp,
    SpeedEasing,
    build_speed_ramp_filter_complex,
    chain_atempo_filters,
    source_time_for_clip_at_timeline,
)


@pytest.mark.unit
class TestSpeedRampMath:
    def test_constant_2x_source_time(self):
        ramp = SpeedRamp(enabled=True)
        ramp.add_keyframe(0.0, 2.0)
        ramp.add_keyframe(10.0, 2.0)
        # 输出 1s → 源 2s
        assert ramp.get_source_time(1.0) == pytest.approx(2.0, abs=1e-3)
        assert ramp.get_source_time(5.0) == pytest.approx(10.0, abs=1e-3)

    def test_get_speed_at_lerp(self):
        ramp = SpeedRamp(enabled=True)
        ramp.add_keyframe(0.0, 0.5)
        ramp.add_keyframe(10.0, 1.5)
        assert ramp.get_speed_at(0.0) == pytest.approx(0.5)
        assert ramp.get_speed_at(5.0) == pytest.approx(1.0)
        assert ramp.get_speed_at(10.0) == pytest.approx(1.5)

    def test_ramp_in_source_monotonic(self):
        ramp = SpeedRamp.preset_preset("ramp_in")
        for kf in ramp.keyframes:
            kf.time = float(kf.time) * 10.0
        times = [ramp.get_source_time(t) for t in (0.0, 1.0, 2.0, 4.0, 8.0)]
        assert all(times[i] <= times[i + 1] + 1e-9 for i in range(len(times) - 1))

    def test_segment_speeds_bullet(self):
        ramp = SpeedRamp.preset_preset("bullet_time")
        for kf in ramp.keyframes:
            kf.time = float(kf.time) * 10.0
        segs = ramp.segment_speeds(10.0)
        assert len(segs) >= 2
        assert all(s[2] > 0 for s in segs)


@pytest.mark.unit
class TestAtempoChain:
    def test_in_range(self):
        assert chain_atempo_filters(1.5) == "atempo=1.500000"

    def test_above_2(self):
        s = chain_atempo_filters(4.0)
        assert "atempo=2.0" in s
        assert s.count("atempo=") >= 2

    def test_below_half(self):
        s = chain_atempo_filters(0.25)
        assert "atempo=0.5" in s


@pytest.mark.unit
class TestFilterComplexBuild:
    def test_multi_segment_has_trim_concat(self):
        ramp = SpeedRamp.preset_preset("fast_slow_fast")
        for kf in ramp.keyframes:
            kf.time = float(kf.time) * 8.0
        fc, maps, avg = build_speed_ramp_filter_complex(ramp, 8.0)
        assert "trim=" in fc
        assert "setpts=" in fc
        assert "atempo=" in fc
        assert "concat=" in fc
        assert "[vout]" in fc and "[aout]" in fc
        assert maps == ["-map", "[vout]", "-map", "[aout]"]
        assert avg > 0

    def test_single_segment_no_concat(self):
        ramp = SpeedRamp(enabled=True)
        ramp.add_keyframe(0.0, 0.5, SpeedEasing.LINEAR)
        ramp.add_keyframe(5.0, 0.5)
        fc, maps, avg = build_speed_ramp_filter_complex(ramp, 5.0)
        assert "concat=" not in fc
        assert "setpts=PTS/0.5" in fc or "setpts=PTS/0.500000" in fc
        assert avg == pytest.approx(0.5)


@pytest.mark.unit
class TestClipSourceRemap:
    def test_constant_speed(self):
        clip = {"start_time": 10.0, "in_point": 2.0, "speed": 2.0}
        # timeline 12 → local 2 → source 2*2+2=6
        assert source_time_for_clip_at_timeline(clip, 12.0) == pytest.approx(6.0)

    def test_speed_ramp_overrides(self):
        ramp = SpeedRamp(enabled=True)
        ramp.add_keyframe(0.0, 2.0)
        ramp.add_keyframe(10.0, 2.0)
        clip = {
            "start_time": 0.0,
            "in_point": 0.0,
            "speed": 1.0,
            "speed_ramp": ramp.to_dict(),
        }
        assert source_time_for_clip_at_timeline(clip, 1.0) == pytest.approx(2.0, abs=1e-3)

    def test_speed_ramp_respects_in_point(self):
        # 2026-09-13 回归：裁剪片段（in_point>0）挂 ramp 时，源时间必须含裁剪偏移
        from app.core.speed_ramping import instant_speed_for_clip_at_timeline
        ramp = SpeedRamp(enabled=True)
        ramp.add_keyframe(0.0, 2.0)
        ramp.add_keyframe(10.0, 2.0)
        clip = {
            "start_time": 5.0,
            "in_point": 30.0,
            "speed": 1.0,
            "speed_ramp": ramp.to_dict(),
        }
        # timeline 5 → local 0 → ramp 源时间 0，再加 in_point=30
        assert source_time_for_clip_at_timeline(clip, 5.0) == pytest.approx(30.0, abs=1e-3)
        # timeline 6 → local 1 → ramp 源时间 2，再加 in_point=30
        assert source_time_for_clip_at_timeline(clip, 6.0) == pytest.approx(32.0, abs=1e-3)
        # 瞬时倍率采样点同样落在源轴（in_point 之后恒 2.0x）
        assert instant_speed_for_clip_at_timeline(clip, 6.0) == pytest.approx(2.0, abs=0.05)

    def test_instant_speed_follows_ramp(self):
        from app.core.speed_ramping import instant_speed_for_clip_at_timeline
        ramp = SpeedRamp(enabled=True)
        ramp.add_keyframe(0.0, 0.5)
        ramp.add_keyframe(10.0, 1.5)
        clip = {
            "start_time": 0.0,
            "in_point": 0.0,
            "speed": 1.0,
            "speed_ramp": ramp.to_dict(),
        }
        # local=0 → source~0 → speed 0.5
        assert instant_speed_for_clip_at_timeline(clip, 0.0) == pytest.approx(0.5, abs=0.05)

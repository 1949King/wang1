# -*- coding: utf-8 -*-
"""B0：字词/句级 ASR ↔ clip 帧级绑定单元测试（无 GUI）。"""

import pytest

from app.core.text_frame_map import (
    FrameBoundaryPolicy,
    Timebase,
    bind_entries_to_clip,
    bind_whisper_segments_to_clip,
    clip_context_from_dict,
    frame_in_from_sec,
    frame_out_exclusive_from_sec,
    from_whisper_segments,
    map_sec_range_to_frames,
    normalize_timed_entry,
    source_abs_to_timeline,
    timeline_to_source_abs,
)


@pytest.mark.unit
class TestFrameBoundaries:
    """边界策略：floor 起点 + ceil 终点（半开区间）。"""

    def test_safe_word_one_second_at_30fps(self):
        r = map_sec_range_to_frames(1.0, 2.0, 30.0)
        assert r.frame_in == 30
        assert r.frame_out == 60
        assert r.frame_count == 30

    def test_avoid_half_word_mid_frame(self):
        # 1.05s~1.42s @30fps → [31, 43)
        r = map_sec_range_to_frames(1.05, 1.42, 30.0)
        assert r.frame_in == 31
        assert r.frame_out == 43

    def test_zero_duration_gets_one_frame(self):
        r = map_sec_range_to_frames(1.0, 1.0, 30.0)
        assert r.frame_out == r.frame_in + 1

    def test_reversed_times_normalized(self):
        r = map_sec_range_to_frames(2.0, 1.0, 30.0)
        assert r.frame_in == 30
        assert r.frame_out == 60


@pytest.mark.unit
class TestClipTimeConversion:
    def test_speed_doubles_source_consumption(self):
        ctx = clip_context_from_dict(
            {"id": "c1", "start_time": 10.0, "in_point": 5.0, "speed": 2.0},
            fps=30.0,
        )
        # 源 +1s → 时间线 +0.5s
        assert source_abs_to_timeline(6.0, ctx) == pytest.approx(10.5)
        assert timeline_to_source_abs(10.5, ctx) == pytest.approx(6.0)


@pytest.mark.unit
class TestWhisperToClipBinding:
    def test_whisper_relative_to_timeline_and_source(self):
        clip = {
            "id": "v1",
            "start_time": 10.0,
            "in_point": 5.0,
            "out_point": 20.0,
            "speed": 1.0,
        }
        segments = [
            {"start": 0.5, "end": 1.5, "text": "你好"},
            {"start": 2.0, "end": 3.0, "text": "世界"},
        ]
        bindings = bind_whisper_segments_to_clip(segments, clip, fps=30.0)

        assert len(bindings) == 2
        b0 = bindings[0]
        assert b0.text == "你好"
        assert b0.source_in_sec == pytest.approx(5.5, abs=1e-3)
        assert b0.timeline_in_sec == pytest.approx(10.5, abs=1e-3)
        assert b0.timeline_frame_in == 315  # floor(10.5 * 30)
        assert b0.timeline_frame_out == 345  # ceil(11.5 * 30)

    def test_from_whisper_skips_empty_text(self):
        segs = [{"start": 0, "end": 1, "text": "  "}, {"start": 1, "end": 2, "text": "有"}]
        entries = from_whisper_segments(segs)
        assert len(entries) == 1
        assert entries[0].text == "有"


@pytest.mark.unit
class TestSubtitleTimelineBinding:
    def test_timeline_absolute_subtitles(self):
        from app.core.text_frame_map import TextTimedEntry, bind_entry_to_clip

        ctx = clip_context_from_dict(
            {"id": "c2", "start_time": 0.0, "in_point": 0.0, "speed": 1.0},
            fps=24.0,
        )
        entry = TextTimedEntry(text="句级", start_sec=1.0, end_sec=2.0, entry_id="sub_1")
        b = bind_entry_to_clip(entry, ctx, timebase=Timebase.TIMELINE)
        assert b.timeline_frame_in == 24
        assert b.timeline_frame_out == 48
        assert b.source_frame_in == 24
        assert b.source_frame_out == 48


@pytest.mark.unit
class TestNormalize:
    def test_whisper_keys(self):
        e = normalize_timed_entry({"start": 1.1, "end": 2.2, "text": "测"})
        assert e is not None
        assert e.start_sec == pytest.approx(1.1)
        assert e.end_sec == pytest.approx(2.2)

    def test_subtitle_manager_keys(self):
        e = normalize_timed_entry(
            {"id": "subtitle_1", "start_time": 3.0, "end_time": 4.0, "text": "幕"}
        )
        assert e is not None
        assert e.entry_id == "subtitle_1"

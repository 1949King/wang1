# -*- coding: utf-8 -*-
"""B2：填充词 / 长静音检测 + B1 执行器接线（纯数据层）。"""

import pytest

from app.core.filler_silence_detect import (
    CleanupConfig,
    CleanupInterval,
    build_cleanup_plan_from_entries,
    build_cleanup_plan_from_whisper,
    detect_silence_gaps,
    execute_cleanup_plan,
    is_pure_filler_text,
    merge_intervals,
    realign_subtitles_after_cleanup,
    ripple_delete_intervals,
)
from app.core.text_frame_map import (
    TextTimedEntry,
    Timebase,
    bind_whisper_segments_to_clip,
    clip_context_from_dict,
)


def _clip(cid="v1", start=10.0, dur=30.0, in_point=5.0):
    return {
        "id": cid,
        "start_time": start,
        "duration": dur,
        "in_point": in_point,
        "out_point": in_point + dur,
        "speed": 1.0,
        "track": 0,
        "type": "video",
        "path": "/fake/video.mp4",
    }


def _timeline_clip(start=0.0, dur=60.0):
    return {
        "id": "main",
        "start_time": start,
        "duration": dur,
        "in_point": 0.0,
        "out_point": dur,
        "track": 0,
        "type": "video",
    }


@pytest.mark.unit
class TestFillerDetection:
    def test_pure_filler_words(self):
        assert is_pure_filler_text("呃", ("呃", "啊"))
        assert is_pure_filler_text("嗯嗯", ("呃", "啊", "嗯"))
        assert not is_pure_filler_text("大家好", ("呃", "啊"))

    def test_whisper_fillers_map_to_timeline(self):
        clip = _clip()
        segments = [
            {"start": 0.0, "end": 0.5, "text": "呃"},
            {"start": 0.5, "end": 2.0, "text": "今天天气不错"},
            {"start": 2.0, "end": 2.3, "text": "嗯"},
        ]
        cfg = CleanupConfig(detect_silence=False)
        plan = build_cleanup_plan_from_whisper(segments, clip, cfg)
        assert all(i.kind == "filler" for i in plan.intervals)
        assert len(plan.intervals) == 2
        first = min(plan.intervals, key=lambda x: x.timeline_in)
        assert first.timeline_in == pytest.approx(10.0, abs=0.05)
        assert first.timeline_out == pytest.approx(10.5, abs=0.05)

    def test_mixed_sentence_not_deleted_by_default(self):
        clip = _clip(start=0.0, dur=20.0, in_point=0.0)
        entries = [
            TextTimedEntry("嗯好的开始", 0.0, 3.0),
        ]
        plan = build_cleanup_plan_from_entries(
            entries,
            clip,
            CleanupConfig(aggressive_fillers=False, detect_silence=False),
            timebase=Timebase.SOURCE_RELATIVE,
        )
        assert plan.intervals == []


@pytest.mark.unit
class TestSilenceDetection:
    def test_inter_segment_gap(self):
        ctx = clip_context_from_dict(_clip(start=0.0, dur=30.0, in_point=0.0), fps=30.0)
        entries = [
            TextTimedEntry("第一句", 0.0, 2.0),
            TextTimedEntry("第二句", 3.0, 5.0),
        ]
        gaps = detect_silence_gaps(entries, ctx, CleanupConfig(silence_min_sec=0.4))
        assert len(gaps) == 1
        assert gaps[0].kind == "silence"
        assert gaps[0].timeline_in == pytest.approx(2.0)
        assert gaps[0].timeline_out == pytest.approx(3.0)

    def test_short_gap_ignored(self):
        ctx = clip_context_from_dict(_clip(start=0.0, dur=30.0, in_point=0.0), fps=30.0)
        entries = [
            TextTimedEntry("A", 0.0, 1.0),
            TextTimedEntry("B", 1.2, 2.0),
        ]
        gaps = detect_silence_gaps(entries, ctx, CleanupConfig(silence_min_sec=0.4))
        assert gaps == []

    def test_skip_silence_for_drama_mode(self):
        clip = _clip(start=0.0, dur=20.0, in_point=0.0)
        segments = [
            {"start": 0.0, "end": 1.0, "text": "对白一"},
            {"start": 2.0, "end": 3.0, "text": "对白二"},
        ]
        cfg = CleanupConfig(skip_inter_segment_silence=True)
        plan = build_cleanup_plan_from_whisper(segments, clip, cfg)
        assert all(i.kind != "silence" for i in plan.intervals)


@pytest.mark.unit
class TestMergeAndExecute:
    def test_merge_overlapping(self):
        merged = merge_intervals(
            [
                CleanupInterval(1.0, 3.0, "filler"),
                CleanupInterval(2.5, 4.0, "filler"),
            ]
        )
        assert len(merged) == 1
        assert merged[0].timeline_in == pytest.approx(1.0)
        assert merged[0].timeline_out == pytest.approx(4.0)

    def test_merge_does_not_cross_kind(self):
        merged = merge_intervals(
            [
                CleanupInterval(1.0, 3.0, "silence"),
                CleanupInterval(3.0, 4.0, "filler"),
            ]
        )
        assert len(merged) == 2

    def test_execute_plan_on_mock_clips(self):
        clips = [_timeline_clip(0.0, 60.0)]
        segments = [
            {"start": 10.0, "end": 15.0, "text": "呃"},
        ]
        cfg = CleanupConfig(detect_silence=False)
        plan = build_cleanup_plan_from_whisper(segments, clips[0], cfg)
        assert len(plan.intervals) == 1
        before_dur = clips[0]["duration"]
        result = execute_cleanup_plan(clips, plan, track=0)
        assert result.ok
        assert result.deleted_duration == pytest.approx(5.0, abs=0.1)
        total_dur = sum(c["duration"] for c in result.clips if c.get("track", 0) == 0)
        assert total_dur == pytest.approx(before_dur - 5.0, abs=0.1)

    def test_ripple_delete_multiple_ranges_right_to_left(self):
        clips = [_timeline_clip(0.0, 60.0)]
        result = ripple_delete_intervals(clips, [(10.0, 12.0), (20.0, 25.0)], track=0)
        assert result.ok
        assert result.deleted_duration == pytest.approx(7.0)
        assert len(result.clips) >= 2

    def test_compound_undo_shape(self):
        clips = [_timeline_clip(0.0, 40.0)]
        result = ripple_delete_intervals(clips, [(5.0, 10.0)], track=0)
        ua = result.undo_action
        assert ua["type"] == "compound"
        assert ua["steps"]


@pytest.mark.unit
class TestBindingsIntegration:
    def test_whisper_binding_matches_detect_interval(self):
        clip = _clip(start=0.0, dur=20.0, in_point=0.0)
        segments = [{"start": 1.0, "end": 1.5, "text": "啊"}]
        bindings = bind_whisper_segments_to_clip(segments, clip, fps=30.0)
        cfg = CleanupConfig(detect_silence=False)
        plan = build_cleanup_plan_from_whisper(segments, clip, cfg)
        assert len(bindings) == 1
        filler_iv = next(i for i in plan.intervals if i.kind == "filler")
        assert filler_iv.timeline_in == pytest.approx(bindings[0].timeline_in_sec)
        assert filler_iv.timeline_out == pytest.approx(bindings[0].timeline_out_sec)


@pytest.mark.unit
class TestRealignSubtitlesAfterCleanup:
    def test_shift_right_and_drop_overlap(self):
        subs = [
            {"id": "a", "text": "前", "start_time": 0.0, "end_time": 2.0},
            {"id": "b", "text": "呃", "start_time": 2.0, "end_time": 2.5},
            {"id": "c", "text": "后", "start_time": 5.0, "end_time": 7.0},
        ]
        intervals = [CleanupInterval(2.0, 2.5, "filler", text="呃")]
        out = realign_subtitles_after_cleanup(subs, intervals)
        assert len(out) == 2
        assert out[0]["text"] == "前"
        assert out[0]["start_time"] == pytest.approx(0.0)
        assert out[1]["text"] == "后"
        assert out[1]["start_time"] == pytest.approx(4.5)
        assert out[1]["end_time"] == pytest.approx(6.5)

    def test_multi_interval_right_to_left(self):
        subs = [
            {"id": "1", "text": "A", "start_time": 0.0, "end_time": 1.0},
            {"id": "2", "text": "B", "start_time": 3.0, "end_time": 4.0},
            {"id": "3", "text": "C", "start_time": 8.0, "end_time": 9.0},
        ]
        intervals = [
            CleanupInterval(1.5, 2.5, "silence"),
            CleanupInterval(5.0, 6.0, "silence"),
        ]
        out = realign_subtitles_after_cleanup(subs, intervals)
        assert [s["text"] for s in out] == ["A", "B", "C"]
        assert out[0]["start_time"] == pytest.approx(0.0)
        assert out[1]["start_time"] == pytest.approx(2.0)  # 3-1
        assert out[2]["start_time"] == pytest.approx(6.0)  # 8-1-1


@pytest.mark.unit
class TestCleanupPlanSubset:
    """M5：勾选子集后执行，不删未选区间。"""

    def test_with_intervals_and_execute_subset(self):
        from app.core.filler_silence_detect import CleanupPlan

        clips = [_timeline_clip(0.0, 30.0)]
        plan = CleanupPlan(
            intervals=[
                CleanupInterval(5.0, 6.0, "filler", text="呃"),
                CleanupInterval(10.0, 12.0, "silence"),
                CleanupInterval(20.0, 21.0, "filler", text="嗯"),
            ],
            clip_id="v1",
        )
        selected = plan.with_intervals([plan.intervals[0], plan.intervals[2]])
        assert len(selected.intervals) == 2
        assert selected.total_duration == pytest.approx(2.0)
        result = execute_cleanup_plan(clips, selected, track=0)
        assert result.ok
        assert result.deleted_duration == pytest.approx(2.0)
        # 未选中的 10–12s 静音不应被删：总时长约 28s
        total = sum(float(c.get("duration", 0) or 0) for c in result.clips)
        assert total == pytest.approx(28.0, abs=0.05)

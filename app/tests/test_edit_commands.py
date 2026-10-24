# -*- coding: utf-8 -*-
"""B1：薄指令执行器单元测试（纯数据层，无 GUI）。"""

import copy

import pytest

from app.core.edit_commands import (
    close_track_gaps,
    ripple_delete_clip_data,
    ripple_delete_timeline_range,
    split_clip_at_timeline,
)


def _clip(cid, start, dur, track=0, in_point=0.0, path="/fake/video.mp4", clip_type="video"):
    return {
        "id": cid,
        "start_time": float(start),
        "duration": float(dur),
        "in_point": float(in_point),
        "out_point": float(in_point) + float(dur),
        "track": track,
        "path": path,
        "type": clip_type,
    }


def _linked_av_pair(start=0.0, dur=60.0, path="/fake/video.mp4"):
    return [
        _clip("v", start, dur, track=0, path=path, clip_type="video"),
        _clip("a", start, dur, track=1, path=path, clip_type="audio"),
    ]


@pytest.mark.unit
class TestSplitClipAtTimeline:
    def test_split_mid_clip(self):
        clips = [_clip("a", 0, 30)]
        out, action = split_clip_at_timeline(clips, "a", 10.0, id_factory=lambda: "b")
        assert action is not None
        left = next(c for c in out if c["id"] == "a")
        right = next(c for c in out if c["id"] == "b")
        assert left["duration"] == pytest.approx(10.0)
        assert right["start_time"] == pytest.approx(10.0)
        assert right["duration"] == pytest.approx(20.0)
        assert right["in_point"] == pytest.approx(10.0)

    def test_no_split_on_boundary(self):
        clips = [_clip("a", 0, 30)]
        out, action = split_clip_at_timeline(clips, "a", 0.0)
        assert action is None
        out2, action2 = split_clip_at_timeline(clips, "a", 30.0)
        assert action2 is None


@pytest.mark.unit
class TestRippleDeleteClipData:
    def test_ripple_shifts_following_clips(self):
        clips = [_clip("a", 0, 10), _clip("b", 10, 10), _clip("c", 20, 10)]
        out, action = ripple_delete_clip_data(clips, "b")
        assert action is not None
        c = next(x for x in out if x["id"] == "c")
        assert c["start_time"] == pytest.approx(10.0)
        assert len(out) == 2

    def test_undo_payload_has_shifts(self):
        clips = [_clip("a", 0, 10), _clip("b", 10, 5)]
        _, action = ripple_delete_clip_data(clips, "a")
        assert action["type"] == "delete"
        assert action["clip"]["id"] == "a"
        assert len(action["ripple_shifts"]) == 1
        assert action["ripple_shifts"][0]["old"] == pytest.approx(10.0)
        assert action["ripple_shifts"][0]["new"] == pytest.approx(0.0)


@pytest.mark.unit
class TestLinkedAvSplit:
    def test_split_video_also_splits_linked_audio(self):
        clips = _linked_av_pair(dur=30.0)
        out, action = split_clip_at_timeline(clips, "v", 10.0, id_factory=lambda: "v2")
        assert action is not None
        audio = next(c for c in out if c["id"] == "a")
        assert audio["duration"] == pytest.approx(30.0)

        from app.core.edit_commands import _split_all_at_timeline_with_linked_av

        out2, steps = _split_all_at_timeline_with_linked_av(clips, 10.0, track=0)
        assert len(steps) == 2
        v_parts = sorted(
            (c for c in out2 if str(c.get("type", "")).lower() != "audio"),
            key=lambda c: c["start_time"],
        )
        a_parts = sorted(
            (c for c in out2 if str(c.get("type", "")).lower() == "audio"),
            key=lambda c: c["start_time"],
        )
        assert len(v_parts) == 2
        assert len(a_parts) == 2
        assert v_parts[0]["duration"] == pytest.approx(10.0)
        assert a_parts[0]["duration"] == pytest.approx(10.0)
        assert a_parts[1]["start_time"] == pytest.approx(10.0)
        assert a_parts[1]["duration"] == pytest.approx(20.0)


@pytest.mark.unit
class TestRippleDeleteTimelineRange:
    def test_delete_middle_of_single_clip(self):
        clips = [_clip("main", 0, 60)]
        result = ripple_delete_timeline_range(clips, 10.0, 15.0, track=0)
        assert result.ok
        assert len(result.clips) == 2
        first = min(result.clips, key=lambda c: c["start_time"])
        second = max(result.clips, key=lambda c: c["start_time"])
        assert first["duration"] == pytest.approx(10.0)
        assert second["start_time"] == pytest.approx(10.0)
        assert second["duration"] == pytest.approx(45.0)
        assert result.deleted_duration == pytest.approx(5.0)

    def test_delete_fully_covers_clip(self):
        clips = [_clip("a", 0, 10), _clip("b", 10, 10), _clip("c", 20, 10)]
        result = ripple_delete_timeline_range(clips, 10.0, 20.0, track=0)
        assert result.ok
        ids = {c["id"] for c in result.clips}
        assert "b" not in ids
        assert len(result.clips) == 2
        c = next(x for x in result.clips if x["id"] == "c")
        assert c["start_time"] == pytest.approx(10.0)

    def test_other_track_untouched(self):
        clips = [
            _clip("v", 0, 30, track=0),
            _clip("a", 0, 30, track=1, path="/fake/bgm.mp3", clip_type="audio"),
        ]
        before = copy.deepcopy(clips)
        result = ripple_delete_timeline_range(clips, 5.0, 10.0, track=0)
        assert result.ok
        audio = next(c for c in result.clips if c["track"] == 1)
        orig = next(c for c in before if c["track"] == 1)
        assert audio["start_time"] == orig["start_time"]
        assert audio["duration"] == orig["duration"]

    def test_ripple_delete_syncs_linked_embedded_audio(self):
        clips = _linked_av_pair(dur=60.0)
        result = ripple_delete_timeline_range(clips, 10.0, 15.0, track=0)
        assert result.ok
        video_parts = sorted(
            (c for c in result.clips if int(c.get("track", 0)) == 0),
            key=lambda c: c["start_time"],
        )
        audio_parts = sorted(
            (c for c in result.clips if str(c.get("type", "")).lower() == "audio"),
            key=lambda c: c["start_time"],
        )
        assert len(video_parts) == 2
        assert len(audio_parts) == 2
        assert video_parts[0]["duration"] == pytest.approx(10.0)
        assert video_parts[1]["start_time"] == pytest.approx(10.0)
        assert video_parts[1]["duration"] == pytest.approx(45.0)
        for vp, ap in zip(video_parts, audio_parts):
            assert ap["start_time"] == pytest.approx(vp["start_time"])
            assert ap["duration"] == pytest.approx(vp["duration"])
            assert ap["in_point"] == pytest.approx(vp["in_point"])
            assert ap["out_point"] == pytest.approx(vp["out_point"])
        assert result.deleted_duration == pytest.approx(5.0)

    def test_invalid_range(self):
        clips = [_clip("a", 0, 10)]
        result = ripple_delete_timeline_range(clips, 5.0, 5.0, track=0)
        assert not result.ok

    def test_compound_undo_action_shape(self):
        clips = [_clip("main", 0, 40)]
        result = ripple_delete_timeline_range(clips, 10.0, 20.0, track=0)
        assert result.ok
        ua = result.undo_action
        assert ua["type"] == "compound"
        assert len(ua["steps"]) >= 2
        types = [s["type"] for s in ua["steps"]]
        assert "split" in types
        assert "delete" in types


@pytest.mark.unit
class TestCloseTrackGaps:
    def test_multi_track_all_rows(self):
        clips = [
            _clip("v1", 0, 10, track=0),
            _clip("v2", 15, 10, track=0),
            _clip("a1", 0, 10, track=1, clip_type="audio"),
            _clip("a2", 12, 10, track=1, clip_type="audio"),
        ]
        result = close_track_gaps(clips, track=None, gap_threshold=0.05)
        assert result.ok
        v2 = next(c for c in result.clips if c["id"] == "v2")
        a2 = next(c for c in result.clips if c["id"] == "a2")
        assert v2["start_time"] == pytest.approx(10.0)
        assert a2["start_time"] == pytest.approx(10.0)
        assert result.undo_action["type"] == "compound"
        assert len(result.steps) == 2

    def test_single_track_filter(self):
        clips = [
            _clip("v1", 0, 10, track=0, path="/fake/a.mp4"),
            _clip("v2", 15, 10, track=0, path="/fake/b.mp4"),
            _clip("a1", 0, 10, track=1, path="/fake/x.mp3", clip_type="audio"),
            _clip("a2", 20, 10, track=1, path="/fake/y.mp3", clip_type="audio"),
        ]
        result = close_track_gaps(clips, track=0, gap_threshold=0.05)
        assert result.ok
        v2 = next(c for c in result.clips if c["id"] == "v2")
        a2 = next(c for c in result.clips if c["id"] == "a2")
        assert v2["start_time"] == pytest.approx(10.0)
        assert a2["start_time"] == pytest.approx(20.0)

    def test_single_track_syncs_linked_av(self):
        """只合视频轨时，同 path 联动音频跟 Δstart。"""
        clips = [
            _clip("v1", 0, 10, track=0, path="/fake/av.mp4"),
            _clip("a1", 0, 10, track=1, path="/fake/av.mp4", clip_type="audio"),
            _clip("v2", 15, 10, track=0, path="/fake/av2.mp4"),
            _clip("a2", 15, 10, track=1, path="/fake/av2.mp4", clip_type="audio"),
        ]
        result = close_track_gaps(clips, track=0, gap_threshold=0.05)
        assert result.ok
        v2 = next(c for c in result.clips if c["id"] == "v2")
        a2 = next(c for c in result.clips if c["id"] == "a2")
        assert v2["start_time"] == pytest.approx(10.0)
        assert a2["start_time"] == pytest.approx(10.0)
        assert any(s.get("clip_id") == "a2" for s in result.steps)


@pytest.mark.unit
class TestExpandCutTargetsLinkedAv:
    """_expand_cut_targets_with_linked_av：双选音画只应去重为 2 个目标。"""

    def test_video_audio_both_seeds_dedupe(self):
        from app.modules.lego.editor_module import EditorModule

        clips = [
            _clip("v", 0, 30, track=0),
            _clip("a", 0, 30, track=1, clip_type="audio"),
        ]
        stub = type(
            "StubEditor",
            (),
            {
                "_clips": clips,
                "_find_linked_av_partners": EditorModule._find_linked_av_partners,
            },
        )()
        targets = EditorModule._expand_cut_targets_with_linked_av(
            stub, clips, 10.0
        )
        assert len(targets) == 2
        assert {t["id"] for t in targets} == {"v", "a"}

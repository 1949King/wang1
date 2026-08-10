"""多选范围 / 吸附边 / 跨轨类型 — 无 UI 冒烟。"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.modules.lego.editor_timeline_tools import (
    clip_compatible_with_track,
    clip_is_audio,
    pick_snap,
    same_track_range_ids,
    _snap_start_excluding,
)


def _tl(clips, playhead=0.0, snap=True, thr=0.25):
    return SimpleNamespace(
        _clips=clips,
        _playhead_pos=playhead,
        _snap_enabled=snap,
        _snap_guide=None,
        snap_threshold_sec=lambda: thr,
        set_snap_guide=lambda t: setattr(_tl, "_last_guide", t),
    )


def test_shift_range_selects_overlap_not_only_start():
    """长片 start 在区间外但与锚点-目标外包络重叠 → 应入选。"""
    clips = [
        {"id": "a", "track": 0, "start_time": 10.0, "duration": 5.0},
        {"id": "mid", "track": 0, "start_time": 5.0, "duration": 17.0},  # [5,22] 盖住 [10,25]
        {"id": "t", "track": 0, "start_time": 20.0, "duration": 5.0},
        {"id": "other", "track": 1, "start_time": 12.0, "duration": 2.0},
        {"id": "before", "track": 0, "start_time": 0.0, "duration": 2.0},  # 不相交
    ]
    tl = _tl(clips)
    ids = same_track_range_ids(tl, "a", "t")
    assert ids == {"a", "mid", "t"}


def test_shift_range_includes_sandwiched_clip():
    clips = [
        {"id": "a", "track": 0, "start_time": 0.0, "duration": 2.0},
        {"id": "m", "track": 0, "start_time": 5.0, "duration": 1.0},
        {"id": "t", "track": 0, "start_time": 10.0, "duration": 2.0},
    ]
    ids = same_track_range_ids(_tl(clips), "a", "t")
    assert ids == {"a", "m", "t"}


def test_shift_range_cross_track_degrades():
    clips = [
        {"id": "a", "track": 0, "start_time": 0.0, "duration": 2.0},
        {"id": "t", "track": 1, "start_time": 5.0, "duration": 2.0},
    ]
    assert same_track_range_ids(_tl(clips), "a", "t") == {"a", "t"}


def test_snap_guide_on_end_alignment_edge():
    """片尾贴合邻片头时，红线应在合缝处（邻片 start），非拖片 start。"""
    clips = [
        {"id": "n", "track": 0, "start_time": 10.0, "duration": 4.0},
        {"id": "d", "track": 0, "start_time": 0.0, "duration": 3.0},
    ]
    guides = []

    def set_guide(t):
        guides.append(t)

    tl = SimpleNamespace(
        _clips=clips,
        _playhead_pos=0.0,
        _snap_enabled=True,
        snap_threshold_sec=lambda: 0.3,
        set_snap_guide=set_guide,
    )
    # 拖片 dur=3，proposed≈7 → 应对齐到 10-3=7，guide=10
    st = _snap_start_excluding(tl, clips[1], 7.05, {"d"})
    assert abs(st - 7.0) < 1e-6
    assert guides and abs(guides[-1] - 10.0) < 1e-6


def test_snap_against_override_track():
    clips = [
        {"id": "on0", "track": 0, "start_time": 5.0, "duration": 2.0},
        {"id": "on1", "track": 1, "start_time": 8.0, "duration": 2.0},
        {"id": "d", "track": 0, "start_time": 0.0, "duration": 2.0},
    ]
    guides = []
    tl = SimpleNamespace(
        _clips=clips,
        _playhead_pos=0.0,
        _snap_enabled=True,
        snap_threshold_sec=lambda: 0.3,
        set_snap_guide=lambda t: guides.append(t),
    )
    # 参照轨 1：应对齐到 8
    st = _snap_start_excluding(tl, clips[2], 8.1, {"d"}, track_i=1)
    assert abs(st - 8.0) < 1e-6


def test_clip_track_compat():
    assert clip_is_audio({"type": "audio"})
    assert clip_is_audio({"type": "video", "path": "a.mp3"})
    assert not clip_is_audio({"type": "video", "path": "a.mp4"})
    assert clip_compatible_with_track({"type": "video"}, {"type": "video"})
    assert not clip_compatible_with_track({"type": "video"}, {"type": "audio"})
    assert clip_compatible_with_track({"type": "audio"}, {"type": "audio"})


def test_pick_snap_prefers_nearest():
    best, guide = pick_snap(1.0, [(0.0, 0.0), (1.05, 1.05), (2.0, 2.0)], 0.2)
    assert abs(best - 1.05) < 1e-9
    assert abs(guide - 1.05) < 1e-9


if __name__ == "__main__":
    test_shift_range_selects_overlap_not_only_start()
    test_shift_range_includes_sandwiched_clip()
    test_shift_range_cross_track_degrades()
    test_snap_guide_on_end_alignment_edge()
    test_snap_against_override_track()
    test_clip_track_compat()
    test_pick_snap_prefers_nearest()
    print("ok")

# -*- coding: utf-8 -*-
"""第 4 波：无损 trim / 高光切点 / 节拍切开 / 章节导出（纯数据，不实例化 Editor）。"""

from __future__ import annotations

import numpy as np
import pytest
from pathlib import Path

from app.core.beat_split import beat_split_times
from app.core.chapter_markers import ChapterMarker, chapters_to_csv, chapters_to_ffmetadata
from app.core.highlight_detect import (
    gray_diff_scene_times,
    merge_silence_into_segments,
    motion_highlight_windows,
    parse_silencedetect,
)
from app.core.lossless_trim import lossless_trim, parse_ffprobe_keyframes, snap_to_keyframe


@pytest.mark.unit
class TestLosslessTrim:
    def test_snap_before_and_after(self):
        kfs = [0.0, 2.0, 4.0, 6.0]
        assert snap_to_keyframe(3.1, kfs, mode="before") == 2.0
        assert snap_to_keyframe(3.1, kfs, mode="after") == 4.0
        assert snap_to_keyframe(0.0, kfs, mode="before") == 0.0

    def test_parse_ffprobe_keyframes(self):
        stdout = "0.000000\n2.002000\n4.004000\n"
        assert parse_ffprobe_keyframes(stdout) == [0.0, 2.002, 4.004]

    def test_missing_src_honest_fail(self, tmp_path):
        dst = tmp_path / "out.mp4"
        result = lossless_trim(
            str(tmp_path / "gone.mp4"),
            1.0,
            3.0,
            str(dst),
            ffmpeg="ffmpeg",
            ffprobe="ffprobe",
        )
        assert result["success"] is False
        assert "不存在" in (result.get("error") or "")
        assert result.get("reencoded") is False


@pytest.mark.unit
class TestHighlightDetect:
    def test_scene_times_from_sampled_grays(self):
        a = np.zeros((18, 32), dtype=np.uint8)
        b = np.full((18, 32), 255, dtype=np.uint8)
        samples = [(0.0, a), (1.0, a), (2.0, b), (3.0, b)]
        times = gray_diff_scene_times(samples, thresh=15.0)
        assert times == pytest.approx([2.0])

    def test_motion_windows_picks_high_motion(self):
        still = np.zeros((9, 16), dtype=np.uint8)
        moving = [np.full((9, 16), v, dtype=np.uint8) for v in (0, 80, 160, 240)]
        samples = [(i * 0.5, still) for i in range(4)] + [
            (2.0 + i * 0.5, fr) for i, fr in enumerate(moving)
        ]
        wins = motion_highlight_windows(samples, window_sec=1.0, top_n=1)
        assert wins
        assert wins[0][0] >= 1.5

    def test_parse_silencedetect(self):
        err = (
            "[silencedetect @ x] silence_start: 1.00\n"
            "[silencedetect @ x] silence_end: 2.50 | silence_duration: 1.50\n"
        )
        assert parse_silencedetect(err) == [(1.0, 2.5)]

    def test_merge_silence_splits_long_scene(self):
        segs = [(0.0, 10.0, "scene")]
        merged = merge_silence_into_segments(segs, [(3.0, 4.0)], min_len=1.0)
        assert len(merged) >= 2
        assert merged[0][1] <= 3.0 + 1e-6


@pytest.mark.unit
class TestBeatSplit:
    def test_every_nth_beat_excludes_ends(self):
        beats = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
        cuts = beat_split_times(beats, duration=8.0, every_n=4, min_gap=0.2)
        assert cuts == [2.0, 4.0]

    def test_funclip_autoclip_call_highlight_helpers(self):
        # autoclip 调用点随 mixin 拆分从 editor_module.py 迁到 editor_ai_process_mixin.py；
        # 断言「调用点存在 + 实现函数存在」而非绑定单一文件
        base = Path(__file__).resolve().parents[1] / "modules" / "lego"
        mixin_text = (base / "editor_ai_process_mixin.py").read_text(encoding="utf-8")
        assert "detect_scene_segments" in mixin_text, "autoclip 场景检测调用点丢失"
        assert "detect_motion_segments" in mixin_text, "autoclip 运动检测调用点丢失"
        grab = Path(__file__).resolve().parents[1] / "core" / "highlight_detect.py"
        grab_text = grab.read_text(encoding="utf-8")
        assert "def detect_scene_segments(" in grab_text
        assert "def detect_motion_segments(" in grab_text
        assert "cap.grab()" in grab_text


@pytest.mark.unit
class TestChapterExport:
    def test_csv_and_ffmetadata(self):
        chs = [
            ChapterMarker(id="a", time=0.0, title="开场", description=""),
            ChapterMarker(id="b", time=12.5, title="反转", description="高潮"),
        ]
        csv = chapters_to_csv(chs)
        assert "time_sec,title,description" in csv
        assert "12.5" in csv and "反转" in csv
        meta = chapters_to_ffmetadata(chs, duration=30.0)
        assert ";FFMETADATA1" in meta
        assert "START=0" in meta
        assert "START=12500" in meta
        assert "END=30000" in meta

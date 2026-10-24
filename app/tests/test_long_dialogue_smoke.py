# -*- coding: utf-8 -*-
"""N2 长对白冒烟：scrub 降载约定仍在 + 密集对白建议不自动写轨。

不实例化 EditorModule / 不碰冻结播放主时钟。
"""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from app.core.filler_silence_detect import (
    CleanupConfig,
    build_cleanup_plan_from_entries,
    execute_cleanup_plan,
)
from app.core.text_frame_map import TextTimedEntry
from app.modules.lego.suggest_checklist import merge_checked_commands, partition_agent_commands

ROOT = Path(__file__).resolve().parents[2]


def test_scrub_coalesce_and_busy_drop_still_in_editor_source():
    src = (ROOT / "app" / "modules" / "lego" / "editor_module.py").read_text(encoding="utf-8")
    assert "_scrub_preview_timer" in src
    assert "setInterval(80)" in src
    assert "_scrub_render_busy" in src
    assert "_scrub_busy_drops" in src
    assert "for_scrub=True" in src
    assert "_preview_scrubbing" in src
    i = src.find("def _show_frame_gl")
    assert i > 0
    assert "_preview_scrubbing" in src[i : i + 900]
    moved = src.find("def _on_timeline_playhead_moved")
    body = src[moved : moved + 800]
    assert "_timeline_playing" in body and "return" in body
    assert "_scrub_preview_pending" in body
    pm = (ROOT / "app" / "core" / "preview_manager.py").read_text(encoding="utf-8")
    assert "for_scrub: bool = False" in pm
    assert "if preload and" in pm or "if preload:" in pm


def test_preview_fast_path_still_skips_named_filter():
    import numpy as np

    from app.core.preview_manager import PreviewManager

    pm = PreviewManager()
    frame = np.zeros((80, 96, 3), dtype=np.uint8)
    frame[:, :, 0] = 160
    full = pm._apply_effects_sync(
        frame.copy(),
        {"filter": "暖色调", "filter_intensity": 0.8, "brightness": 10},
    )
    fast = pm._apply_effects_sync(
        frame.copy(),
        {
            "filter": "暖色调",
            "filter_intensity": 0.8,
            "brightness": 10,
            "_preview_fast": True,
        },
    )
    assert not np.array_equal(full, fast)
    assert np.any(fast[:, :, 0] > frame[0, 0, 0])


def _long_dialogue_entries(n=180, step=1.2):
    """约 3.6 分钟、句均 <2s 的密集对白；夹杂纯填充词。"""
    rows = []
    t = 0.0
    fillers = ("嗯", "啊", "呃")
    for i in range(n):
        text = fillers[i % 17] if i % 17 == 0 else f"对白{i:03d} 今天天气不错"
        rows.append(
            TextTimedEntry(
                text=text,
                start_sec=t,
                end_sec=t + step,
                entry_id=f"e{i}",
            )
        )
        t += step
    return rows


def test_dense_long_dialogue_suggests_without_mutating_clips():
    entries = _long_dialogue_entries()
    clip = {
        "id": "v_long",
        "start_time": 0.0,
        "duration": entries[-1].end_sec,
        "in_point": 0.0,
        "out_point": entries[-1].end_sec,
        "speed": 1.0,
        "track": 0,
        "type": "video",
        "path": "/fake/long_dialogue.mp4",
    }
    original = copy.deepcopy([clip])
    plan = build_cleanup_plan_from_entries(
        entries,
        clip,
        CleanupConfig(detect_fillers=True, detect_silence=True, aggressive_fillers=False),
    )
    assert plan.is_dense_dialogue is True
    assert len(entries) >= 12
    assert original[0]["duration"] == clip["duration"]
    # 建议本身不写轨
    snapshot = copy.deepcopy([clip])
    fillers = [iv for iv in plan.intervals if iv.kind == "filler"]
    assert fillers, "长对白样片应至少检出纯填充词建议"
    subset = plan.with_intervals(fillers[:2])
    result = execute_cleanup_plan(copy.deepcopy(snapshot), subset, track=0)
    assert result.ok
    assert snapshot[0]["duration"] == pytest.approx(entries[-1].end_sec)
    assert result.clips[0]["duration"] < snapshot[0]["duration"]


class _Cmd:
    def __init__(self, action, description="", params=None):
        self.action = action
        self.description = description
        self.params = params or {}


def test_agent_command_checklist_keeps_reads_and_checked_writes_only():
    cmds = [
        _Cmd("answer", "说明"),
        _Cmd("split_clip", "切开", {"t_in": 1, "t_out": 2}),
        _Cmd("ripple_delete", "波纹删", {"t_in": 3, "t_out": 4}),
        _Cmd("info", "提示"),
    ]
    reads, writes = partition_agent_commands(cmds)
    assert [c.action for c in reads] == ["answer", "info"]
    assert [c.action for c in writes] == ["split_clip", "ripple_delete"]
    merged = merge_checked_commands(reads, writes, [1])
    assert [c.action for c in merged] == ["answer", "info", "ripple_delete"]
    skipped_all_writes = merge_checked_commands(reads, writes, [])
    assert [c.action for c in skipped_all_writes] == ["answer", "info"]
    once = merge_checked_commands(reads, writes, [-1, 99, 0, 0])
    assert [c.action for c in once] == ["answer", "info", "split_clip"]

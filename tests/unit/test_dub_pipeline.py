# -*- coding: utf-8 -*-
"""配音编排纯函数单测（配音一致性方案 P0①，2026-10-15）

只测 `app/core/ai/dub_pipeline.py` 的四个纯函数与其**诚实边界**（不猜说话人、
查不到音色标 degraded、无音频证据不改镜头时长）。不加载 Qt / 不跑 TTS。
"""
from __future__ import annotations

from app.core.ai.dub_pipeline import (
    DEFAULT_VOICE_PROFILE,
    assemble_dialogue_track,
    parse_dialogue_lines,
    retime_shots_by_audio,
    route_voices,
)


def test_parse_colon_and_bracket_prefix():
    lines = parse_dialogue_lines("小明：你好\n【小红】我很好\n他今天很好。然后：走了")
    assert lines[0] == {"speaker": "小明", "text": "你好", "order": 1}
    assert lines[1] == {"speaker": "小红", "text": "我很好", "order": 2}
    # 说话人候选含句读 ⇒ 判为叙述句，归旁白（不猜）
    assert lines[2]["speaker"] is None
    assert lines[2]["order"] == 3


def test_parse_narration_label_becomes_none():
    lines = parse_dialogue_lines("旁白：夜色已深\nnarration: the end")
    assert lines[0]["speaker"] is None
    assert lines[1]["speaker"] is None
    assert lines[1]["text"] == "the end"


def test_parse_skips_blank_lines_and_keeps_order():
    lines = parse_dialogue_lines("\n\n甲：一\n\n乙：二\n")
    assert [l["order"] for l in lines] == [1, 2]


def test_route_voices_honest_degrade():
    lines = parse_dialogue_lines("小明：你好\n旁白：夜色已深")
    lookup = {"小明": {"name": "小明"}}  # 未绑定 voice_id
    routed = route_voices(lines, lookup)
    # 具名角色但无音色 ⇒ degraded + 默认声线（不伪造）
    assert routed[0]["degraded"] is True
    assert routed[0]["voice_profile_id"] == DEFAULT_VOICE_PROFILE
    assert routed[0]["route"] == "default_voice"
    # 旁白用默认声线是预期，不算降级
    assert routed[1]["speaker"] is None
    assert routed[1]["route"] == "narration"
    assert routed[1]["degraded"] is False


def test_route_voices_uses_character_voice_profile():
    lines = parse_dialogue_lines("小明：你好")
    lookup = {"小明": {"name": "小明", "voice_profile_id": "male_adult_calm"}}
    routed = route_voices(lines, lookup)
    assert routed[0]["route"] == "character"
    assert routed[0]["degraded"] is False
    assert routed[0]["voice_profile_id"] == "male_adult_calm"


def test_retime_only_overrides_with_audio_evidence():
    shots = [
        {"id": "s1", "dialogue": "你好", "duration": 3.0},
        {"id": "s2", "dialogue": "没有配音的一句", "duration": 2.0},
    ]
    audio = [{"text": "你好", "duration": 1.25}]
    out = retime_shots_by_audio(shots, audio)
    assert out[0]["duration"] == 1.25
    assert out[0]["duration_source"] == "audio"
    # 无音频证据 ⇒ 保留估算，绝不假装已对齐
    assert out[1]["duration"] == 2.0
    assert out[1]["duration_source"] == "estimate"


def test_assemble_dialogue_track_cumulative():
    track = assemble_dialogue_track([
        {"order": 2, "duration": 2.0, "audio_path": "b.wav"},
        {"order": 1, "duration": 1.0, "audio_path": "a.wav"},
    ])
    assert [s["order"] for s in track["segments"]] == [1, 2]
    assert track["segments"][0]["start"] == 0.0
    assert track["segments"][0]["end"] == 1.0
    assert track["segments"][1]["start"] == 1.0
    assert track["segments"][1]["end"] == 3.0
    assert track["total"] == 3.0

# -*- coding: utf-8 -*-
"""音频 filter graph 纯函数测试（V4.45 · 2026-10-19）。"""
from app.core.code_video.audio_graph import (
    atempo_chain,
    build_audio_graph,
    iter_audio_clips,
)

_ASSETS = {"a.mp4": "C:/inbox/a.mp4", "b.mp4": "C:/inbox/b.mp4"}


def _clip(key="a.mp4", start=0.0, end=2.0, speed=1.0, volume=1.0, kind="video"):
    return {
        "source": f"asset://{key}",
        "range": [start, end],
        "kind": kind,
        "speed": speed,
        "volume": volume,
    }


def test_iter_audio_clips_filters():
    tracks = [
        {"clip": _clip()},
        {"clip": _clip(volume=0.0)},
        {"clip": _clip(kind="subtitle")},
        {"clip": {"source": "html://a.html", "kind": "video", "volume": 1.0}},
        {"clip": _clip(kind="audio")},
    ]
    got = iter_audio_clips({"tracks": tracks})
    assert len(got) == 2
    assert all(c["source"].startswith("asset://") for c in got)


def test_atempo_chain():
    assert atempo_chain(1.0) == []
    assert atempo_chain(2.0) == ["atempo=2.000000"]
    assert atempo_chain(4.0) == ["atempo=2.0", "atempo=2.000000"]
    assert atempo_chain(0.25) == ["atempo=0.5", "atempo=0.500000"]
    assert atempo_chain(1.5) == ["atempo=1.500000"]


def test_build_audio_graph_two_clips():
    clips = [_clip("a.mp4", 0.0, 2.0), _clip("b.mp4", 2.0, 4.0, speed=1.5)]
    inputs, graph, has_audio = build_audio_graph(
        clips, {"a.mp4": True, "b.mp4": True}, _ASSETS
    )
    assert has_audio is True
    assert inputs == ["C:/inbox/a.mp4", "C:/inbox/b.mp4"]
    assert "[1:a]atrim=start=0.000000:duration=2.000000" in graph
    assert "[2:a]atrim=start=0.000000:duration=3.000000" in graph  # 2s × 1.5
    assert "atempo=1.500000" in graph
    assert "adelay=2000|2000" in graph
    assert "amix=inputs=2" in graph
    assert graph.endswith("[aout]")


def test_build_audio_graph_skips_silent_assets():
    clips = [_clip("a.mp4"), _clip("b.mp4")]
    inputs, graph, has_audio = build_audio_graph(
        clips, {"a.mp4": True, "b.mp4": False}, _ASSETS
    )
    assert has_audio is True
    assert inputs == ["C:/inbox/a.mp4"]
    assert "amix=inputs=1" in graph


def test_build_audio_graph_no_audio():
    assert build_audio_graph([_clip()], {"a.mp4": False}, _ASSETS) == ([], "", False)
    assert build_audio_graph([], {}, {}) == ([], "", False)


def test_build_audio_graph_skips_missing_path():
    inputs, graph, has_audio = build_audio_graph(
        [_clip("missing.mp4")], {"missing.mp4": True}, _ASSETS
    )
    assert (inputs, graph, has_audio) == ([], "", False)


def test_audio_clip_source_range_used():
    clip = _clip()
    clip["source_range"] = [1.0, 3.0]
    _, graph, _ = build_audio_graph([clip], {"a.mp4": True}, _ASSETS)
    assert "atrim=start=1.000000" in graph

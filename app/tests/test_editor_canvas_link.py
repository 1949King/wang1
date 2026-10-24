# -*- coding: utf-8 -*-
"""剪辑 ↔ 画布 round-trip 纯函数（不写 _clips）。"""

from app.core.editor_canvas_link import (
    extra_from_material_payload,
    guess_outbox_media_type,
    outbox_fields_from_clip,
    public_clip_row,
    stamp_clip,
    suggest_canvas_roundtrip,
)


def test_extra_from_material_payload_aliases():
    extra = extra_from_material_payload(
        {"node_id": "n1", "kind": "shot", "title": "镜01"}
    )
    assert extra["canvas_node_id"] == "n1"
    assert extra["canvas_kind"] == "shot"
    assert extra["canvas_title"] == "镜01"
    assert extra_from_material_payload(None) == {}


def test_stamp_clip_does_not_blank_existing():
    clip = {"id": "c1", "name": "old", "canvas_node_id": "keep"}
    stamp_clip(clip, {"canvas_node_id": "", "canvas_kind": "video"})
    assert clip["canvas_node_id"] == "keep"
    assert clip["canvas_kind"] == "video"


def test_suggest_skips_audio_and_lists_send_and_gaps():
    ctx = {
        "clips": [
            {"id": "a", "type": "audio", "path": "x.wav", "name": "联动音"},
            {"id": "v", "type": "video", "path": "a.mp4", "name": "A"},
            {
                "id": "linked",
                "type": "video",
                "path": "b.mp4",
                "name": "B",
                "canvas_node_id": "node_9",
            },
        ],
        "gaps": [{"t_in": 3.0, "t_out": 5.2, "duration": 2.2}],
    }
    items = suggest_canvas_roundtrip(ctx)
    actions = [x["action"] for x in items]
    assert "send_to_canvas" in actions
    assert "refresh_canvas" in actions
    assert "info" in actions
    assert all(x.get("clip_id") != "a" for x in items if x["action"] != "info")


def test_public_row_and_outbox_fields():
    clip = {
        "id": "c9",
        "name": "镜",
        "path": "D:/x.mp4",
        "start_time": 1,
        "duration": 2,
        "in_point": 0.5,
        "out_point": 2.5,
        "canvas_node_id": "n2",
        "type": "video",
    }
    row = public_clip_row(clip, 0)
    assert row["canvas_node_id"] == "n2"
    assert row["end_time"] == 3
    fields = outbox_fields_from_clip(clip)
    assert fields["clip_id"] == "c9"
    assert fields["canvas_node_id"] == "n2"
    assert fields["in_point"] == 0.5


def test_guess_media_type():
    assert guess_outbox_media_type(".mp3") == "audio"
    assert guess_outbox_media_type(".png", "shot") == "image"
    assert guess_outbox_media_type(".mp4") == "video"

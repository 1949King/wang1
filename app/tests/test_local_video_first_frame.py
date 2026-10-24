# -*- coding: utf-8 -*-
"""SVD 首帧输入链路：resolve_image_path 三态测试（不加载模型、不联网）。"""
from __future__ import annotations

import base64
import os

from app.core.local_video_infer import resolve_image_path

# 1x1 PNG
PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def test_data_url_becomes_file(tmp_path):
    src = "data:image/png;base64," + PNG_B64
    p = resolve_image_path(src, dest_dir=str(tmp_path), name_hint="t")
    assert p and os.path.isfile(p)
    assert p.endswith(".png")


def test_inbox_url_maps_to_canvas_inbox(tmp_path, monkeypatch):
    import app.core.canvas_bridge as cb

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "shot_frame.png").write_bytes(base64.b64decode(PNG_B64))
    monkeypatch.setattr(cb, "canvas_inbox_dir", lambda: str(inbox))
    p = resolve_image_path("http://127.0.0.1:18765/inbox_file/shot_frame.png")
    assert p == str(inbox / "shot_frame.png")


def test_local_path_accepted(tmp_path):
    f = tmp_path / "a.png"
    f.write_bytes(base64.b64decode(PNG_B64))
    assert resolve_image_path(str(f)) == str(f)


def test_unknown_returns_none(tmp_path):
    assert resolve_image_path("") is None
    assert resolve_image_path("https://example.com/x.png") is None
    assert resolve_image_path(str(tmp_path / "nope.png")) is None
